"""
Event transcoder — turns raw OF WebSocket events into canonical SQL rows.

Pattern: `service/events.py:handle_event` calls `transcode(event)` for every
event after the event_inbox write. Recognized events get upserted to
`messages` / `fans` / `chats` / `transactions`. Unknown shapes are logged
(once per event-type-shape) so we can extend over time without losing data.

The most important event by far is **api2_chat_message** — every single DM
flowing through OF's realtime channel. Storing these forever feeds the AI
pipeline:

    fan thread (DB) → Grok → fan_facts + fan_profiles rows

Without persistent message history, every Grok run would have to re-fetch
from OF's API (slow, costly, rate-limited). With it, we can replay,
audit, and re-process at zero marginal cost.

Direction inference:
  • `fromUser.id == account_id` → 'out' (our model sent it)
  • `fromUser.id != account_id` → 'in' (someone else sent it; either our
    fan, OR a creator we follow blasting their mass-message). Both are
    persisted; `fans.source` distinguishes at query time.

Failure mode: every operation is `try/except` + `log.exception` + return.
A bad payload must never break the WS pump or the SSE fan-out.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db import of_writer, write_telemetry
from db.engine import get_session
from db.models import Chat, Fan, Message, Transaction, is_paid_ratchet
from automations._common import source_self_heal_set
import event_transcode_decide as td
import relay_cache
from jsonsafe import dump_capped

# Outbound-echo cache-bust debounce (per account). A mass blast echoes one
# outbound chat_message per recipient; busting list_chats/roster_count on each
# would keep those caches permanently cold for the blast's duration. One bust
# per window suffices — the 60/90s frontend polls are the refetch cadence.
_OUT_BUST_DEBOUNCE_S = 20.0
_last_out_bust: dict[str, float] = {}

# ── "Did this account just blast?" — the broadcast queue ring ──────────
# OF pushes `chat_queue_update` / `chat_queue_finish` frames about a second after
# ANY broadcast leaves the account, ours or one the creator composed in the OF
# app. That makes them the only real-time signal for a HUMAN blast, and the
# inbound-after-a-blast scrape (webhook_dispatch) reads them next to `mass_runs`
# so a blast we fired ourselves survives a relay restart while a human one in the
# restart minute is an accepted loss.
#
# In-process, no DB write: this answers a question with a 60-minute horizon and a
# `mass_runs` row is already the durable record of everything WE send. Keyed on
# RECEIPT time rather than the frame's own `date` — a replayed or clock-skewed
# frame must not look fresh. The ring's rules: `td.queue_fold`.
_queue_finishes: dict[str, td.Ring] = {}

log = logging.getLogger("of-relay.transcode")

# One-time "unknown event shape" log: log the first occurrence of each
# (event_type, payload top-level keys) tuple so we see what's coming
# without spamming once we know the shape.
_seen_unknown: set[tuple[str, tuple[str, ...]]] = set()


# ── Helpers ──────────────────────────────────────────────────────────
# Pure, in event_transcode_decide; the private names stay for their importers
# (server, automations.send_mass_message / scheduled_send, the tests).
_parse_iso = td.parse_iso
_to_cents = td.to_cents
_media_ids = td.media_ids
_strip_html = td.strip_html


# ── Top-level dispatch ─────────────────────────────────────────────

async def transcode(event: dict) -> None:
    """Route an event to the right canonical-table writer. Called
    fire-and-forget from `events.handle_event`."""
    r = td.route(event)
    if r is None:
        return
    lane, event_type, payload = r
    account_id = event.get("__account_id")

    try:
        match lane:
            case "chat_message":
                await _transcode_chat_message(account_id, payload)
            case "ppv":
                # PPV-unlock path. Shape not yet observed in production — we
                # log + record a best-effort transaction so the first one in
                # the wild leaves enough breadcrumbs to refine the parser.
                await _transcode_ppv_unlock(account_id, event_type, payload)
            case "toast":
                await _transcode_toast(account_id, payload)
            case "queue":
                # A broadcast just left this account. No canonical row (the frame
                # carries no body and no recipients) — it goes in the in-process ring
                # above, which is all the 60-minute "did she just blast" question
                # needs. Handled here rather than falling through: the payload has no
                # user blob for `_touch_fan_from_event` and the shape is known, so the
                # discovery log has nothing left to learn from it.
                _record_queue_frame(account_id, event_type, payload)
            case "other":
                # Online/typing/stories/etc. don't get full transcodes yet,
                # but they often carry up-to-date avatar + display name. Touch
                # the Fan row so the inbox cold-start renders from DB without
                # waiting on OF.
                await _touch_fan_from_event(account_id, payload)
                _log_unknown(event_type, payload)
    except Exception:
        log.exception("transcode failed (account=%s type=%s)", account_id, event_type)
        write_telemetry.drop("transcode_exception")


def _record_queue_frame(account_id: Any, event_type: str, payload: Any) -> None:
    """Fold one `chat_queue_*` frame into the account's ring (`td.queue_fold`).
    Never raises."""
    if account_id is None:
        return
    aid = str(account_id)
    _queue_finishes[aid] = td.queue_fold(_queue_finishes.get(aid, ()), event_type, payload,
                                         time.monotonic())


def blasted_within(account_id: Any, *, seconds: float) -> bool:
    """Did a broadcast of ≥5 recipients finish on this account in the last
    `seconds`? Reads the ring above — in-process, so a restart answers False until
    the next blast, which the `mass_runs` half of the caller's check covers for
    everything WE send."""
    return td.blasted(_queue_finishes.get(str(account_id), ()), time.monotonic(), seconds)


async def _transcode_toast(account_id: Any, payload: Any) -> None:
    """OF's own alert frame — `subscribed`, `favorited`, `commented`.

    No canonical row of its own yet (the shapes are still being learned, hence
    the discovery log), but every toast carries a fresh creator-side user blob
    AND is itself a row in the notifications feed, the subscribe lane being
    money.

    A named branch rather than a condition inside the unknown-event
    fall-through: EVERY OF frame reaches that branch, `typing` and online
    frames dwarfing all others, so busting there would keep the money feeds
    permanently cold.
    """
    await _touch_fan_from_event(account_id, payload)
    if account_id:
        relay_cache.invalidate_money_feeds(str(account_id))
        if _has_subscribe_toast(payload):
            # A new subscriber: the welcome sweep need not wait out its
            # cadence (W2 2.10). welcome_sent keeps it one welcome per fan.
            from automation_executor import poke_rule  # lazy: the executor is heavy
            poke_rule(account_id, "send_welcome")
    _log_unknown("toasts", payload)


def _has_subscribe_toast(payload: Any) -> bool:
    """Does this `toasts` frame carry a `subscribed` toast? OF sends a list of
    toasts (`{"toasts": [{"type": ...}]}`); a single dict is accepted too."""
    items = payload if isinstance(payload, list) else [payload]
    return any(isinstance(t, dict) and str(t.get("type") or "").startswith("subscri")
               for t in items)


async def _touch_fan_from_event(account_id: Any, payload: Any) -> None:
    """Opportunistic avatar/display-name refresh for non-message events: the
    frame's user blob (`td.user_blob`) updates Fan(avatar_url, of_username,
    of_display_name). This is a touch, not a transcode — it never creates a new
    Fan row, only updates ones that already exist (the chat-message path creates).
    """
    if not account_id:
        return
    blob = td.user_blob(payload)
    if blob is None:
        return
    # UPDATE-only (no insert) — we don't want a stray toast to mint a Fan
    # row for someone the model has never actually messaged.
    fan_id, fields = blob

    # A typing / online frame repeats the same blob every few seconds: read
    # first (no write lock) and write only what changed — not even updated_at
    # moves when nothing did.
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
    """of_writer op: the touches of one fan, folded into one UPDATE that only
    matches when a field still differs."""
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


# ── api2_chat_message ─────────────────────────────────────────────

async def _transcode_chat_message(account_id: str | None, m: dict) -> None:
    """Upsert messages + fans + chats rows for one OF chat_message event.

    `m` is the payload after key-strip — i.e. the contents of
    `event['api2_chat_message']`. Shape we rely on:

        m = {
            'id': 9684362558908,           # OF message_id (BIGINT)
            'text': '<p>...</p>',
            'price': 9.99,                  # may be 0/null for free
            'isFree': bool,
            'isOpened': bool,               # PPV unlocked or not
            'isTip': bool,
            'isMediaReady': bool,
            'mediaCount': int,
            'media': [{'id': ...}, ...],
            'lockedText': bool,
            'fromUser': {'id': int, 'username': str, 'name': str, ...},
            'createdAt': '2026-05-18T19:06:47+00:00',
            'changedAt': '...',
            'responseType': 'message',
            'isFromQueue': bool,
        }

    OF sometimes omits fields; everything below copes with None. The row, the
    direction and the hook lanes: `td.dm_plan`.
    """
    plan = td.dm_plan(account_id, m, datetime.utcnow())
    if isinstance(plan, td.Skip):
        # Without all three we can't form a primary key — log + bail.
        log.debug("chat_message missing message_id/fan_id/account_id: %s",
                  {"id": plan.message_id, "fan_id": plan.fan_id, "account_id": account_id})
        return

    # For OUTBOUND messages we sent ourselves, fromUser.id == account_id,
    # which means we can't infer the chat partner from this payload alone.
    # OF's chat_message event for outbound doesn't carry the recipient as a
    # field. The outbound write happens at send-time in our send handler
    # (phase B); here we still want to capture the message body but the
    # (account_id, fan_id, message_id) PK requires SOME fan_id. Skip for now
    # and let the send-side handler own outbound persistence.
    if isinstance(plan, td.Outbound):
        # Persistence is owned by the send handler, but the cached OF chat
        # window is stale either way (lastMessage direction flipped → a fan
        # drops off owe-reply, previews moved). This echo is the ONLY signal
        # for sends made outside our send endpoint (OF web, another device,
        # a different automation instance) — bust both readers of the window
        # so the next list/badge fetch re-reads OF. Debounced per account so a
        # burst of outbound echoes cannot keep the caches permanently cold (each
        # 60/90s poll would then pay a full live OF re-read). One bust per window
        # is enough — polls are the refetch cadence anyway, so extra busts
        # between polls buy nothing.
        #
        # ⚠️ The debounce's ORIGINAL rationale was "a mass blast echoes one
        # outbound frame per recipient". It does not: 48 hours of `event_inbox`
        # across the two heaviest accounts hold ZERO outbound `api2_chat_message`
        # frames, blast or otherwise. What OF actually pushes for a broadcast is
        # the `chat_queue_*` pair, recorded above. The debounce stands on its own
        # for the multi-device case; the blast claim was never true, and it is
        # why a list blast has no per-fan row anywhere (plans/blast-splice §0.2).
        aid_out = str(account_id)
        now_mono = time.monotonic()
        if now_mono - _last_out_bust.get(aid_out, 0.0) >= _OUT_BUST_DEBOUNCE_S:
            _last_out_bust[aid_out] = now_mono
            relay_cache.invalidate("list_chats", aid_out)
            relay_cache.invalidate("roster_count", aid_out)
        log.debug("skipping outbound chat_message %s — will be written at send time",
                  plan.message_id)
        return

    aid_s, fan_id, message_id = plan.msg["account_id"], plan.msg["fan_id"], plan.msg["message_id"]
    # We persist the full payload as raw_json so future migrations can
    # backfill new columns without re-fetching from OF. 64 KB cap keeps
    # one rogue media-array from blowing up disk usage.
    await of_writer.write(_write_dms, (plan, dump_capped(m)), key=(aid_s, fan_id))

    log.info(
        "chat_message persisted: account=%s fan=%s msg=%s direction=in price=%s tip=%s",
        account_id, fan_id, message_id, plan.msg["price_cents"], plan.tip_cents,
    )

    # Cache invalidation — must run AFTER the write above has committed
    # (of_writer.write returns once its batch has) so a concurrent reader
    # that re-fetches doesn't cache the pre-commit upstream state.
    relay_cache.patch("list_chats", aid_s, _inbox_patcher(fan_id, m))
    # A tip rides on an inbound chat_message (isTip, $ in tipAmount), so this
    # is the tip lane as well as the DM lane. Deliberately NOT gated on
    # `is_tip`: a plain DM is not a notifications-feed row, but the browser
    # refetches its notif-list on every inbound message anyway, and a gate
    # here that mis-reads one degenerate tip frame silently costs a sale its
    # bust. Unconditional is the cheap side of that trade.
    relay_cache.invalidate_money_feeds(aid_s)
    # Roster strip badge: an inbound DM bumps this model's unread, our reply
    # clears its owe-reply — bust the cached count so the next 60s poll recomputes
    # from OF. This is what keeps the unread badge live off the WS pump.
    relay_cache.invalidate("roster_count", aid_s)

    # W7 webhook-priority dispatch: an inbound DM is now persisted, so kick the
    # owning automation to react in real time (gated per-account, default OFF).
    # Reaching here means direction == "in" (outbound returned early above).
    # Fire-and-forget on the running loop; on_inbound_message never raises, but
    # we guard the create_task too so a dispatch hiccup can't break the pump.
    #
    # Inbound IMAGE (a non-tip photo or gif, `td.dm_plan`) = a buying signal: the
    # image hook OWNS its words — it hands off to on_inbound_message itself, with
    # the image-closer intent when that applies — so firing the words hook too
    # would queue two jobs for one photo. We report WHAT arrived (`has_media`);
    # what that's worth — buying signal vs. joke — is the hook's call, not ours.
    # See webhook_dispatch.on_inbound_image.
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

    # A fan tip rides on this inbound message (isTip; $ in tipAmount, captured as
    # tip_cents — price is 0 for a tip). Kick the tip hook (customs mark) in
    # real time. Separate hook from on_inbound_message
    # so it fires even on a terminal-stage fan.
    if plan.tip_cents > 0:
        try:
            from webhook_dispatch import on_inbound_tip
            asyncio.create_task(
                on_inbound_tip(aid_s, fan_id, message_id, plan.tip_cents)
            )
        except Exception:
            log.debug("tip dispatch hook failed", exc_info=True)


async def _write_dms(conn, items: list) -> list:
    """of_writer op: the inbound DMs of ONE chat queued together, in arrival
    order — each `messages` row, then one `fans` and one `chats` upsert for all
    of them, then the tip ledger rows.

    The chat's unread goes up by the DMs that were NEW rows only: a re-delivered
    frame (WS replay after a reconnect) is already counted, and adding it again
    is how a badge used to read higher than the thread."""
    plans = [p for p, _raw in items]
    first, last = plans[0].msg, plans[-1].msg
    aid, fan_id = first["account_id"], first["fan_id"]
    pk = ["account_id", "fan_id", "message_id"]
    n_new = 0
    for p, raw_json in items:
        row = sqlite_insert(Message).values(**p.msg, raw_json=raw_json)
        res = await conn.execute(row.on_conflict_do_nothing(index_elements=pk))
        if res.rowcount:
            n_new += 1
            continue
        # Already stored: refresh what OF may have flipped (is_paid after an
        # unlock, the body after an edit).
        await conn.execute(row.on_conflict_do_update(
            index_elements=pk,
            set_={
                "body": p.msg["body"],
                # Same ratchet as the scrape upsert (automation_executor): a WS
                # frame arriving after a purchase aged off the feed reports the
                # message unpaid again, and an unconditional write here would
                # undo a sale the other writer had already recorded.
                "is_paid": is_paid_ratchet(p.msg["is_paid"]),
                "is_tip": p.msg["is_tip"],
                "media_count": p.msg["media_count"],
                "raw_json": raw_json,
            },
        ))

    # ── fans upsert ─────────────────────────────────────────
    # New fan: insert with the fields OF gave us. Existing fan: bump
    # last_message_received_at and refresh display info (never clobbered by a
    # blank), leaving AI-extracted facts (his_age, hobbies, ...) untouched.
    # Self-heals a weak/unknown source when a payload carries OF's
    # subscribedOn/subscribedBy. The rules: `td.fan_upsert`.
    values, on_conflict, flags = td.fan_upsert(plans)
    on_conflict.update(updated_at=datetime.utcnow(), **source_self_heal_set(*flags))
    created_at = last["created_at"]
    await conn.execute(sqlite_insert(Fan).values(**values).on_conflict_do_update(
        index_elements=["account_id", "fan_id"], set_=on_conflict))

    # ── chats upsert ────────────────────────────────────────
    # The "preview" we show in the inbox is the first ~120 chars of body,
    # HTML-stripped just enough that it doesn't read raw <p> tags.
    preview = td.strip_html(last["body"])[:120]
    await conn.execute(sqlite_insert(Chat).values(
        account_id=aid,
        fan_id=fan_id,
        last_message_id=last["message_id"],
        last_message_at=created_at,
        last_message_preview=preview,
        unread_count=n_new,
    ).on_conflict_do_update(
        index_elements=["account_id", "fan_id"],
        set_={
            "last_message_id": last["message_id"],
            "last_message_at": created_at,
            "last_message_preview": preview,
            "unread_count": Chat.unread_count + n_new,
        },
    ))

    # ── transaction (tip path) ───────────────────────────────
    # A tip rides on a chat_message with isTip=true; its $ value is in
    # `tipAmount` (dollars), captured as tip_cents — `price` is 0 here.
    for p in plans:
        if p.tip_cents:
            await _record_inbound_payment(
                conn, account_id=aid, fan_id=fan_id, message_id=p.msg["message_id"],
                kind="tip", amount_cents=p.tip_cents, occurred_at=p.msg["created_at"])
    return [None] * len(items)


def _inbox_patcher(fan_id: int, m: dict):
    """`relay_cache.patch` fn for one inbound DM: move the fan's row to the top
    of each cached recent page-0 window, set `lastMessage` to this frame (OF's
    /chats `lastMessage` is the same message shape) and bump the unread count.

    Dropping the whole window on every DM made ~24% of inbox loads a 3-call OF
    re-read (p50 ~2 s). Any window the DM cannot be placed in exactly is
    dropped instead: a deeper page (every row below shifts), a non-recent
    order, or a page-0 window the fan is not in (new chat, or ranked past the
    window — OF's /chats row carries fields we cannot fabricate), and a frame
    without a message id. A frame not newer than the row's `lastMessage` (a WS
    replay, or one the window was already read after) leaves the window as is:
    no second unread bump, no re-ordering."""
    msg_id = _int_or_none(m.get("id"))

    def _fn(extras: tuple, value: Any) -> Any:
        _limit, offset, order, *_rest = extras
        if msg_id is None or offset != 0 or order != "recent" or not isinstance(value, dict):
            return None
        rows_key = "list" if "list" in value else "chats"
        rows = value.get(rows_key) or []
        idx = next((i for i, ch in enumerate(rows)
                    if (ch.get("withUser") or {}).get("id") == fan_id), None)
        if idx is None:
            return None
        last_id = _int_or_none((rows[idx].get("lastMessage") or {}).get("id"))
        if last_id is not None and msg_id <= last_id:
            return value
        row = {
            **rows[idx],
            "lastMessage": m,
            "hasUnread": True,
            "unreadMessagesCount": int(rows[idx].get("unreadMessagesCount") or 0) + 1,
        }
        if m.get("isTip"):
            row["hasUnreadTips"] = True
        return {**value, rows_key: [row] + rows[:idx] + rows[idx + 1:]}
    return _fn


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


async def _transcode_ppv_unlock(
    account_id: str | None, event_type: str, payload: dict
) -> None:
    """Best-effort PPV-unlock handler. The exact OF event shape is still
    unknown to us — _log_unknown logs the first occurrence so we can
    iterate. We attempt to extract message_id, fan_id, and price from
    the most likely fields; on miss, we log and move on rather than
    crashing the pump."""
    if not account_id:
        return
    _log_unknown(event_type, payload)  # keep the discovery log alive
    ppv = td.ppv_fields(payload, datetime.utcnow())
    if ppv is None:
        log.info(
            "ppv-unlock event missing fields (type=%s keys=%s) — skipping payment row",
            event_type, tuple(sorted(payload.keys())),
        )
        return
    await of_writer.write(_write_payments, dict(account_id=str(account_id), **ppv))

    # Post-commit cache invalidation. See `_transcode_chat_message` for the
    # ordering rationale.
    aid_s = str(account_id)
    relay_cache.invalidate_money_feeds(aid_s)
    from automation_executor import poke_rule  # lazy: the executor is heavy
    poke_rule(aid_s, "purchase_followup")   # W2 2.10: a purchase, follow up now

    # Tell the browser a sale landed — same event the ledger ingest emits, so
    # the fan drawer's revenue caches refresh on the spot instead of waiting
    # for the 5-min payouts tick.
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
    """Insert a Transaction + bump fans.lifetime_spend_cents — idempotent
    on (account_id, fan_id, message_id, kind). No unique index exists yet
    (would need a migration), so we SELECT-then-INSERT inside the caller's
    transaction (`s`: a session or the OF-cache writer's connection). Safe because the WS pump processes events serially per
    account. No `raw_json` (see `Transaction.raw_json`): a tip's frame stays on
    its `messages` row, but a PPV unlock's payload survives only in the
    `_log_unknown` shape log and the 2-day `event_inbox`."""
    existing = await s.execute(
        select(Transaction.id).where(
            Transaction.account_id == account_id,
            Transaction.fan_id == fan_id,
            Transaction.message_id == message_id,
            Transaction.kind == kind,
        ).limit(1)
    )
    if existing.scalar() is not None:
        return  # already recorded — don't double-count

    await s.execute(insert(Transaction).values(
        account_id=account_id,
        fan_id=fan_id,
        kind=kind,
        message_id=message_id,
        amount_cents=amount_cents,
        currency="USD",
        occurred_at=occurred_at,
    ))

    # Bump the denormalized rollup so the FanDrawer's lifetime-spend
    # stat is one indexed read instead of a SUM(amount_cents) every open.
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
    """of_writer op: PPV-unlock ledger rows."""
    for p in items:
        await _record_inbound_payment(conn, **p)
    return [None] * len(items)


# ── Unknown-event logger ───────────────────────────────────────────

def _log_unknown(event_type: str, payload: Any) -> None:
    """Log the first time we see a (type, key-shape) combo. Helps us
    build out the transcoder over real samples instead of guessing."""
    if isinstance(payload, dict):
        shape = tuple(sorted(payload.keys()))
    else:
        shape = (type(payload).__name__,)
    fingerprint = (event_type, shape)
    if fingerprint in _seen_unknown:
        return
    _seen_unknown.add(fingerprint)
    log.info("new event shape: type=%s keys=%s", event_type, shape)
