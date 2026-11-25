from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import case, func, insert, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db import of_writer, write_telemetry
from db.engine import get_session
from db.models import Chat, Fan, Message, Transaction, is_paid_ratchet
from automations._common import source_self_heal_set
import event_transcode_decide as td
from events_decide import InboxRowUnpatched, PriorInboxRow, can_stub_chat_view
import relay_cache
from jsonsafe import dump_capped

# An outbound echo is the only signal for sends made outside our endpoint (OF web, other device); debounced so bursts don't keep caches cold.
_OUT_BUST_DEBOUNCE_S = 20.0
_last_out_bust: dict[str, float] = {}

# chat_queue_* frames are the only real-time signal for a HUMAN blast; in-process, keyed on receipt time (a replayed frame must not look fresh).
_queue_finishes: dict[str, td.Ring] = {}

log = logging.getLogger("of-relay.transcode")

_seen_unknown: set[tuple[str, tuple[str, ...]]] = set()
# A reconnect replays toasts: remember the last ids per Creator so a toast counts once.
_TOAST_IDS_KEPT = 64
_toast_ids: dict[str, deque] = {}


_parse_iso = td.parse_iso
_to_cents = td.to_cents
_media_ids = td.media_ids
_strip_html = td.strip_html



async def transcode(event: dict, prior: PriorInboxRow = InboxRowUnpatched.VALUE) -> None:
    r = td.route(event)
    if r is None:
        return
    lane, event_type, payload = r
    account_id = event.get("__account_id")

    try:
        match lane:
            case "chat_message":
                await _transcode_chat_message(account_id, payload, prior)
            case "ppv":
                await _transcode_ppv_unlock(account_id, event_type, payload)
            case "toast":
                await _transcode_toast(account_id, payload)
            case "queue":
                _record_queue_frame(account_id, event_type, payload)
            case "other":
                await _touch_fan_from_event(account_id, payload)
                _log_unknown(event_type, payload)
    except Exception:
        log.exception("transcode failed (account=%s type=%s)", account_id, event_type)
        write_telemetry.drop("transcode_exception")


def _record_queue_frame(account_id: Any, event_type: str, payload: Any) -> None:
    if account_id is None:
        return
    aid = str(account_id)
    before = _queue_finishes.get(aid, ())
    after = _queue_finishes[aid] = td.queue_fold(before, event_type, payload, time.monotonic())
    if td.queue_reread(before, after):
        import badge_reads  # noqa: PLC0415 — lazy: it loads the live Relay (events, of_ws, the refresher)
        badge_reads.request_window_read(aid)


def blasted_within(account_id: Any, *, seconds: float) -> bool:
    return td.blasted(_queue_finishes.get(str(account_id), ()), time.monotonic(), seconds)


async def _transcode_toast(account_id: Any, payload: Any) -> None:
    await _touch_fan_from_event(account_id, payload)
    if account_id:
        relay_cache.invalidate_money_feeds(str(account_id))
        n = _subscribe_toasts(payload, str(account_id))
        if n:
            from automation_executor import poke_rule
            from automations.promo_reactivate import should_poke
            poke_rule(account_id, "send_welcome")
            if should_poke(str(account_id), n):
                poke_rule(account_id, "promo_reactivate")
    _log_unknown("toasts", payload)


def _subscribe_toasts(payload: Any, account_id: str) -> int:
    items = payload if isinstance(payload, list) else [payload]
    seen = _toast_ids.setdefault(account_id, deque(maxlen=_TOAST_IDS_KEPT))
    n = 0
    for t in items:
        if not (isinstance(t, dict) and str(t.get("type") or "").startswith("subscri")):
            continue
        tid = t.get("id")
        if tid is not None:
            if tid in seen:
                continue
            seen.append(tid)
        n += 1
    return n


async def _touch_fan_from_event(account_id: Any, payload: Any) -> None:
    if not account_id:
        return
    blob = td.user_blob(payload)
    if blob is None:
        return
    fan_id, fields = blob

    async with get_session() as s:
        row = (await s.execute(
            select(*(getattr(Fan, k) for k in fields))
            .where(Fan.account_id == str(account_id), Fan.fan_id == fan_id)
        )).first()
    if row is None or all(v == cur for v, cur in zip(fields.values(), row)):
        return
    aid = str(account_id)
    await of_writer.write(_touch_fans, (aid, fan_id, fields), key=("touch", aid, fan_id))


async def _touch_fans(conn, items: list) -> list:
    aid, fan_id, _ = items[0]
    fields: dict[str, Any] = {}
    for _a, _f, f in items:
        fields.update(f)
    await conn.execute(
        update(Fan)
        .where(Fan.account_id == aid, Fan.fan_id == fan_id,
               or_(*(getattr(Fan, k).is_distinct_from(v) for k, v in fields.items())))
        .values(**fields, updated_at=datetime.utcnow())
    )
    return [None] * len(items)



async def _transcode_chat_message(account_id: str | None, m: dict, prior: PriorInboxRow = InboxRowUnpatched.VALUE) -> None:
    plan = td.dm_plan(account_id, m, datetime.utcnow())
    if isinstance(plan, td.Echo):
        await _transcode_echo(str(account_id), plan, m)
        return
    if isinstance(plan, td.Skip):
        log.debug("chat_message missing message_id/fan_id/account_id: %s",
                  {"id": plan.message_id, "fan_id": plan.fan_id, "account_id": account_id})
        return

    if isinstance(plan, td.Outbound):
        # The echo names no recipient and the send handler owns outbound persistence: only bust caches here.
        aid_out = str(account_id)
        relay_cache.invalidate("get_chat", aid_out)
        now_mono = time.monotonic()
        if now_mono - _last_out_bust.get(aid_out, 0.0) >= _OUT_BUST_DEBOUNCE_S:
            _last_out_bust[aid_out] = now_mono
            relay_cache.invalidate("list_chats", aid_out)
            relay_cache.invalidate("roster_count", aid_out)
        log.debug("skipping outbound chat_message %s — will be written at send time",
                  plan.message_id)
        return

    aid_s, fan_id, message_id = plan.msg["account_id"], plan.msg["fan_id"], plan.msg["message_id"]
    # raw_json is capped at 64 KB so one rogue media array cannot blow up disk.
    is_new = await of_writer.write(_write_dms, (plan, dump_capped(m)), key=(aid_s, fan_id))

    log.info(
        "chat_message persisted: account=%s fan=%s msg=%s direction=in price=%s tip=%s",
        account_id, fan_id, message_id, plan.msg["price_cents"], plan.tip_cents,
    )

    if is_new is not False:
        import unread_total
        created = plan.msg["created_at"]
        unread_total.on_dm_in(aid_s, fan_id, int(created.replace(tzinfo=timezone.utc).timestamp() * 1000), prior)
    if prior is InboxRowUnpatched.VALUE:
        relay_cache.patch("list_chats", aid_s, _inbox_patcher(fan_id, m))
    try:
        relay_cache.invalidate("get_chat", aid_s, match=lambda ex, c=int(fan_id): ex == (c,))
    except (TypeError, ValueError):
        pass
    if td.money_bust(m):
        relay_cache.invalidate_money_feeds(aid_s)
    relay_cache.invalidate("roster_count", aid_s)

    # The image hook owns its words and hands off itself: firing the words hook too would queue two jobs for one photo.
    if plan.image:
        try:
            from webhook_dispatch import on_inbound_image
            asyncio.create_task(
                on_inbound_image(aid_s, fan_id, message_id,
                                 has_media=plan.has_media)
            )
        except Exception:
            log.debug("image dispatch hook failed", exc_info=True)
    else:
        try:
            from webhook_dispatch import on_inbound_message
            asyncio.create_task(
                on_inbound_message(aid_s, fan_id, message_id)
            )
        except Exception:
            log.debug("webhook_dispatch hook failed", exc_info=True)

    if plan.tip_cents > 0:
        try:
            from webhook_dispatch import on_inbound_tip
            asyncio.create_task(
                on_inbound_tip(aid_s, fan_id, message_id, plan.tip_cents)
            )
        except Exception:
            log.debug("tip dispatch hook failed", exc_info=True)


_deferred_echoes: set[asyncio.Task] = set()


async def _transcode_echo(aid: str, echo: td.Echo, m: dict) -> None:
    import sends_inflight
    now = datetime.utcnow()
    if sends_inflight.pending(aid, echo.fan_id):
        log.debug("creator_echo_deferred account=%s fan=%s msg=%s", aid, echo.fan_id, echo.message_id)
        task = asyncio.create_task(_wait_for_attribution(aid, echo, m, now))
        _deferred_echoes.add(task)
        task.add_done_callback(_deferred_echoes.discard)
        return
    await _store_echo(aid, echo, m, now)


async def _wait_for_attribution(aid: str, echo: td.Echo, m: dict, now: datetime) -> None:
    import sends_inflight
    deadline = time.monotonic() + sends_inflight.ECHO_WAIT_S
    while sends_inflight.pending(aid, echo.fan_id) and time.monotonic() < deadline:
        await asyncio.sleep(sends_inflight.ECHO_POLL_S)
    await _store_echo(aid, echo, m, now, deferred=True)


async def _store_echo(aid: str, echo: td.Echo, m: dict, now: datetime, *, deferred: bool = False) -> None:
    try:
        row = td.echo_row(aid, m, echo, now)
        new = row is not None and await of_writer.write(_write_echo, (row, dump_capped(m), deferred),
                                                        key=("echo", aid, echo.fan_id))
    except Exception:
        log.exception("creator_echo_failed account=%s fan=%s msg=%s", aid, echo.fan_id, echo.message_id)
        new = False
    if new:
        relay_cache.patch("list_chats", aid, _inbox_patcher(echo.fan_id, {**m, "fromUser": {"id": _int_or_none(aid)}},
                                                            outbound=True, created_at=row["created_at"]))
        import relay_hooks
        relay_hooks.fire_outbound_sent(aid, echo.fan_id, echo.message_id, row["created_at"])
        log.info("creator_echo_stored account=%s fan=%s msg=%s priced=%d", aid, echo.fan_id, echo.message_id,
                 row["price_cents"] > 0)
    relay_cache.invalidate("get_chat", aid, match=lambda ex, c=echo.fan_id: ex == (c,))


async def _write_echo(conn, items: list) -> list:
    from attribution import _MASS_PLACEHOLDER_BASE, _preview_text
    new: list[bool] = []
    for row, raw_json, deferred in items:
        res = await conn.execute(sqlite_insert(Message).values(**row, raw_json=raw_json).on_conflict_do_nothing(
            index_elements=["account_id", "fan_id", "message_id"]))
        new.append(bool(res.rowcount))
        if res.rowcount:
            mid, at = row["message_id"], row["created_at"]
            preview = {
                "last_message_id": mid,
                "last_message_at": at,
                "last_message_preview": _preview_text(row["body"]),
            }
            try:
                await conn.execute(sqlite_insert(Chat).values(
                    account_id=row["account_id"], fan_id=row["fan_id"], **preview, unread_count=0,
                ).on_conflict_do_update(
                    index_elements=["account_id", "fan_id"],
                    set_=preview if deferred else {**preview, "unread_count": 0},
                    where=(
                        Chat.last_message_at.is_(None)
                        | (Chat.last_message_at < at)
                        | ((Chat.last_message_at == at) & (
                            Chat.last_message_id.is_(None)
                            | (Chat.last_message_id < mid)
                            | (Chat.last_message_id >= _MASS_PLACEHOLDER_BASE)
                        ))
                    ),
                ))
            except Exception:
                log.debug("echo preview advance skipped account=%s fan=%s msg=%s",
                          row["account_id"], row["fan_id"], mid, exc_info=True)
    return new


async def _write_dms(conn, items: list) -> list:
    plans = [p for p, _raw in items]
    first = plans[0].msg
    newest = max(plans, key=lambda p: p.msg["message_id"]).msg
    aid, fan_id = first["account_id"], first["fan_id"]
    pk = ["account_id", "fan_id", "message_id"]
    n_new = 0
    new: list[bool] = []
    for p, raw_json in items:
        row = sqlite_insert(Message).values(**p.msg, raw_json=raw_json)
        res = await conn.execute(row.on_conflict_do_nothing(index_elements=pk))
        new.append(bool(res.rowcount))
        if res.rowcount:
            n_new += 1
            continue
        await conn.execute(row.on_conflict_do_update(
            index_elements=pk,
            set_={
                "body": p.msg["body"],
                # A WS frame after a purchase aged off the feed reports unpaid again: ratchet so it cannot undo a recorded sale.
                "is_paid": is_paid_ratchet(p.msg["is_paid"]),
                "is_tip": p.msg["is_tip"],
                "media_count": p.msg["media_count"],
                "raw_json": raw_json,
            },
        ))

    values, on_conflict, flags = td.fan_upsert(plans)
    received = on_conflict["last_message_received_at"]
    on_conflict["last_message_received_at"] = case(
        (or_(Fan.last_message_received_at.is_(None), Fan.last_message_received_at <= received), received),
        else_=Fan.last_message_received_at)
    on_conflict.update(updated_at=datetime.utcnow(), **source_self_heal_set(*flags))
    await conn.execute(sqlite_insert(Fan).values(**values).on_conflict_do_update(
        index_elements=["account_id", "fan_id"], set_=on_conflict))

    # Per-column CASE, not a statement-level WHERE: the unread bump must still land. A stored mass placeholder id is synthetic and above every real one, so time decides there.
    preview = td.strip_html(newest["body"])[:120]
    mid, created_at = newest["message_id"], newest["created_at"]
    from attribution import _MASS_PLACEHOLDER_BASE
    fwd = or_(Chat.last_message_id.is_(None), Chat.last_message_id <= mid,
              (Chat.last_message_id >= _MASS_PLACEHOLDER_BASE)
              & or_(Chat.last_message_at.is_(None), Chat.last_message_at <= created_at))
    await conn.execute(sqlite_insert(Chat).values(
        account_id=aid,
        fan_id=fan_id,
        last_message_id=mid,
        last_message_at=created_at,
        last_message_preview=preview,
        unread_count=n_new,
    ).on_conflict_do_update(
        index_elements=["account_id", "fan_id"],
        set_={
            "last_message_id": case((fwd, mid), else_=Chat.last_message_id),
            "last_message_at": case((fwd, created_at), else_=Chat.last_message_at),
            "last_message_preview": case((fwd, preview), else_=Chat.last_message_preview),
            "unread_count": Chat.unread_count + n_new,
        },
    ))

    for p in plans:
        if p.tip_cents:
            await _record_inbound_payment(
                conn, account_id=aid, fan_id=fan_id, message_id=p.msg["message_id"],
                kind="tip", amount_cents=p.tip_cents, occurred_at=p.msg["created_at"])
    return new


def _inbox_patcher(fan_id: int | str, m: dict, *, outbound: bool = False, created_at: datetime | None = None):
    from attribution import _MASS_PLACEHOLDER_BASE

    msg_id = _int_or_none(m.get("id"))
    fan_key = str(fan_id)

    def _fn(extras: tuple, value: Any) -> Any:
        limit, offset, order, filt, list_id, q, *_ = (*extras, None, None, None)
        if msg_id is None or offset != 0 or order != "recent" or not isinstance(value, dict):
            return value if outbound else None
        rows_key = "list" if "list" in value else "chats"
        rows = value.get(rows_key) or []
        idx = next((i for i, ch in enumerate(rows)
                    if str((ch.get("withUser") or {}).get("id")) == fan_key), None)
        if idx is None:
            if outbound:
                return value
            if not isinstance(limit, int) or not can_stub_chat_view(filt, list_id, q):
                return None
            return _stub_on_top(limit, value, rows_key, rows, m)
        last = rows[idx].get("lastMessage") or {}
        last_id = _int_or_none(last.get("id"))
        synthetic = last_id is not None and last_id >= _MASS_PLACEHOLDER_BASE
        at = created_at or _parse_iso(m.get("createdAt"))
        last_at = _parse_iso(last.get("createdAt"))
        if (outbound or synthetic) and at is not None and last_at is not None:
            if at < last_at or (at == last_at and not synthetic and last_id is not None and msg_id <= last_id):
                return value
        elif last_id is not None and msg_id <= last_id:
            return value
        if outbound:
            row = {**rows[idx], "lastMessage": m}
        else:
            row = {
                **rows[idx],
                "lastMessage": m,
                "hasUnread": True,
                "unreadMessagesCount": int(rows[idx].get("unreadMessagesCount") or 0) + 1,
            }
        if m.get("isTip") and not outbound:
            row["hasUnreadTips"] = True
        return {**value, rows_key: [row] + rows[:idx] + rows[idx + 1:]}
    return _fn


def _message_ms(message: dict) -> float | None:
    created = message.get("createdAt")
    if isinstance(created, (int, float)) and not isinstance(created, bool):
        return created * 1000 if abs(created) < 1e11 else created
    if isinstance(created, str):
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            return None
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp() * 1000
    return None


def _stub_on_top(limit: int, value: dict, rows_key: str, rows: list, m: dict) -> Any:
    tail = _message_ms(rows[-1].get("lastMessage") or {}) if rows else None
    frame = _message_ms(m)
    if rows and (tail is None or frame is None or not frame >= tail):
        return None
    if not rows:
        asked_at = value.get("asked_at")
        if not isinstance(asked_at, (int, float)) or frame is None or not frame > asked_at:
            return value
    stub = {"withUser": dict(m.get("fromUser") or {}), "lastMessage": m,
            "hasUnread": True, "unreadMessagesCount": 1}
    if m.get("isTip"):
        stub["hasUnreadTips"] = True
    out = {**value, rows_key: [stub, *rows][:limit]}
    if len(rows) >= limit:
        out["hasMore"] = True
    return relay_cache.Expired(out)


def patch_inbox_at_receipt(account_id: Any, event: dict) -> PriorInboxRow:
    if account_id is None or not td.is_inbound_dm(event):
        return InboxRowUnpatched.VALUE
    try:
        m = td.route(event)[2]
        fan_id = m["fromUser"]["id"]
        aid = str(account_id)
        import unread_total  # noqa: PLC0415 — lazy: unread_total → shared_refresher → events
        prior = unread_total.peek_window_row(aid, int(fan_id))
        relay_cache.patch("list_chats", aid, _inbox_patcher(fan_id, m))
        return prior
    except Exception:  # noqa: BLE001 — the persist worker patches instead
        log.warning("inbox receipt patch failed account=%s", account_id, exc_info=True)
        return InboxRowUnpatched.VALUE


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


async def _transcode_ppv_unlock(
    account_id: str | None, event_type: str, payload: dict
) -> None:
    if not account_id:
        return
    _log_unknown(event_type, payload)
    ppv = td.ppv_fields(payload, datetime.utcnow())
    if ppv is None:
        log.info(
            "ppv-unlock event missing fields (type=%s keys=%s) — skipping payment row",
            event_type, tuple(sorted(payload.keys())),
        )
        return
    await of_writer.write(_write_payments, dict(account_id=str(account_id), **ppv))

    aid_s = str(account_id)
    relay_cache.invalidate_money_feeds(aid_s)
    from automation_executor import poke_rule
    poke_rule(aid_s, "purchase_followup")

    from events import announce_transaction
    await announce_transaction(aid_s, ppv["fan_id"], kind="ppv", reason="ws_unlock")


async def _record_inbound_payment(
    s,
    *,
    account_id: str,
    fan_id: int,
    message_id: int,
    kind: str,
    amount_cents: int,
    occurred_at: datetime,
) -> None:
    # SELECT-then-INSERT is safe: the WS pump processes events serially per account.
    existing = await s.execute(
        select(Transaction.id).where(
            Transaction.account_id == account_id,
            Transaction.fan_id == fan_id,
            Transaction.message_id == message_id,
            Transaction.kind == kind,
        ).limit(1)
    )
    if existing.scalar() is not None:
        return

    await s.execute(insert(Transaction).values(
        account_id=account_id,
        fan_id=fan_id,
        kind=kind,
        message_id=message_id,
        amount_cents=amount_cents,
        currency="USD",
        occurred_at=occurred_at,
    ))

    await s.execute(
        update(Fan)
        .where(Fan.account_id == account_id, Fan.fan_id == fan_id)
        .values(lifetime_spend_cents=func.coalesce(Fan.lifetime_spend_cents, 0) + amount_cents,
                updated_at=datetime.utcnow())
    )

    log.info(
        "transaction persisted: account=%s fan=%s kind=%s amount=%s",
        account_id, fan_id, kind, amount_cents,
    )


async def _write_payments(conn, items: list) -> list:
    for p in items:
        await _record_inbound_payment(conn, **p)
    return [None] * len(items)



def _log_unknown(event_type: str, payload: Any) -> None:
    if isinstance(payload, dict):
        shape = tuple(sorted(payload.keys()))
    else:
        shape = (type(payload).__name__,)
    fingerprint = (event_type, shape)
    if fingerprint in _seen_unknown:
        return
    _seen_unknown.add(fingerprint)
    log.info("new event shape: type=%s keys=%s", event_type, shape)
