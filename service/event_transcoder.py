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
# W30 F28: each Creator's last subscribe-toast ids, so a replayed toast (a reconnect
# re-sending it) counts once. Bounded: _TOAST_IDS_KEPT per Creator.
_TOAST_IDS_KEPT = 64
_toast_ids: dict[str, deque] = {}


# ── Helpers ──────────────────────────────────────────────────────────
# Pure, in event_transcode_decide; the private names stay for their importers
# (server, automations.send_mass_message / scheduled_send, the tests).
_parse_iso = td.parse_iso
_to_cents = td.to_cents
_media_ids = td.media_ids
_strip_html = td.strip_html


# ── Top-level dispatch ─────────────────────────────────────────────

async def transcode(event: dict, prior: PriorInboxRow = InboxRowUnpatched.VALUE) -> None:
    """Route an event to the right canonical-table writer. Called
    fire-and-forget from `events.handle_event`. `prior`: `patch_inbox_at_receipt`'s answer."""
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
    """Fold one `chat_queue_*` frame into the account's ring (`td.queue_fold`); a finished blast new to it asks one
    gated window re-read (`badge_reads.request_window_read`, no I/O here). Never raises."""
    if account_id is None:
        return
    aid = str(account_id)
    before = _queue_finishes.get(aid, ())
    after = _queue_finishes[aid] = td.queue_fold(before, event_type, payload, time.monotonic())
    if td.queue_reread(before, after):
        import badge_reads  # noqa: PLC0415 — lazy: it loads the live Relay (events, of_ws, the refresher)
        badge_reads.request_window_read(aid)


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
        n = _subscribe_toasts(payload, str(account_id))
        if n:
            # A new subscriber: the welcome sweep need not wait out its
            # cadence (W2 2.10). welcome_sent keeps it one welcome per fan.
            # A claim may also have filled or ended the kept promo, but each
            # re-check is an OF list read: the toast gate pokes it only when
            # these claims could reach a trigger (or it knows too little).
            from automation_executor import poke_rule  # lazy: the executor is heavy
            from automations.promo_reactivate import should_poke
            poke_rule(account_id, "send_welcome")
            if should_poke(str(account_id), n):
                poke_rule(account_id, "promo_reactivate")
    _log_unknown("toasts", payload)


def _subscribe_toasts(payload: Any, account_id: str) -> int:
    """How many new `subscribed` toasts this `toasts` frame carries. OF sends a list of
    toasts (`{"toasts": [{"type": ...}]}`); a single dict is accepted too. A toast whose
    `id` this Creator already counted (a replay) is not new; one with no id always is."""
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

async def _transcode_chat_message(account_id: str | None, m: dict, prior: PriorInboxRow = InboxRowUnpatched.VALUE) -> None:
    """Upsert messages + fans + chats rows for one OF chat_message event.

    `m` is the payload after key-strip — i.e. the contents of
    `event['api2_chat_message']`. Shape we rely on:

        m = {
            'id': 9684362558908,           # OF message_id (BIGINT)
            'text': '<p>...</p>',
            'price': 9.99,                  # may be 0/null for free (null/missing still busts the money feeds)
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
    direction and the hook lanes: `td.dm_plan`. Only a plain DM (`isTip` false,
    `price` a number equal to 0) keeps the money feeds' cache; a null or missing
    `price` or `isTip` cannot tell and still busts it (fail-safe, `td.money_bust`).
    """
    plan = td.dm_plan(account_id, m, datetime.utcnow())
    if isinstance(plan, td.Echo):
        await _transcode_echo(str(account_id), plan, m)
        return
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
        # Chat detail (server.of_get_chat): the echo names no recipient, so drop
        # the account's details. Not debounced: a 30s TTL entry is cheap to refill.
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
    # We persist the full payload as raw_json so future migrations can
    # backfill new columns without re-fetching from OF. 64 KB cap keeps
    # one rogue media-array from blowing up disk usage.
    is_new = await of_writer.write(_write_dms, (plan, dump_capped(m)), key=(aid_s, fan_id))

    log.info(
        "chat_message persisted: account=%s fan=%s msg=%s direction=in price=%s tip=%s",
        account_id, fan_id, message_id, plan.msg["price_cents"], plan.tip_cents,
    )

    # The Unread total moves by the chat's prior state: the held window row from
    # before the receipt patch (`prior`), else peeked now, before the patch below
    # flags it unread (Knob off: no-op). The receipt patch done, the window has it.
    # A re-delivered frame (WS replay) is already counted: new rows only. on_dm_in never raises.
    if is_new is not False:     # False: the row was already stored
        import unread_total
        # Stamped with the message's createdAt (naive UTC, always set: td.dm_plan): a /users/me asked after it
        # already counts it.
        created = plan.msg["created_at"]
        unread_total.on_dm_in(aid_s, fan_id, int(created.replace(tzinfo=timezone.utc).timestamp() * 1000), prior)
    if prior is InboxRowUnpatched.VALUE:
        relay_cache.patch("list_chats", aid_s, _inbox_patcher(fan_id, m))
    # The fan's chat detail (server.of_get_chat: lastMessage moved) — that chat only.
    try:
        relay_cache.invalidate("get_chat", aid_s, match=lambda ex, c=int(fan_id): ex == (c,))
    except (TypeError, ValueError):
        pass
    # A tip rides on an inbound chat_message (isTip, $ in tipAmount), so this
    # is the tip lane as well as the DM lane. A plain DM (isTip false, price 0)
    # is no money row and keeps the money feeds' cache; a tip, a priced DM or a
    # frame lacking the fields to tell still clears it (`td.money_bust`, phase-01
    # story 52).
    if td.money_bust(m):
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
    """of_writer op: echo rows; per item, was it new (only a new row advances the chat preview)."""
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
    """of_writer op: the inbound DMs of ONE chat queued together, in arrival
    order — each `messages` row, then one `fans` and one `chats` upsert for all
    of them, then the tip ledger rows.

    The chat's unread goes up by the DMs that were NEW rows only: a re-delivered
    frame (WS replay after a reconnect) is already counted, and adding it again
    is how a badge used to read higher than the thread.

    Forward only: the chat's last message / time / preview follow the batch's
    highest message id, and only when it is at least the stored one (a stored mass
    placeholder id, >= attribution._MASS_PLACEHOLDER_BASE, yields to a DM at or after
    its time, as _advance_chat_preview's rule); the Fan's
    last-received time the batch's latest, only when it is at least the stored
    one (a NULL takes any). A late or re-delivered older DM moves neither back
    (forward by id like messages.py; unlike it, `<=` and the placeholder band)."""
    plans = [p for p, _raw in items]
    first = plans[0].msg
    newest = max(plans, key=lambda p: p.msg["message_id"]).msg
    aid, fan_id = first["account_id"], first["fan_id"]
    pk = ["account_id", "fan_id", "message_id"]
    n_new = 0
    new: list[bool] = []       # per item: a new row (the caller's Unread total hook counts those only)
    for p, raw_json in items:
        row = sqlite_insert(Message).values(**p.msg, raw_json=raw_json)
        res = await conn.execute(row.on_conflict_do_nothing(index_elements=pk))
        new.append(bool(res.rowcount))
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
    received = on_conflict["last_message_received_at"]
    on_conflict["last_message_received_at"] = case(
        (or_(Fan.last_message_received_at.is_(None), Fan.last_message_received_at <= received), received),
        else_=Fan.last_message_received_at)
    on_conflict.update(updated_at=datetime.utcnow(), **source_self_heal_set(*flags))
    await conn.execute(sqlite_insert(Fan).values(**values).on_conflict_do_update(
        index_elements=["account_id", "fan_id"], set_=on_conflict))

    # ── chats upsert ────────────────────────────────────────
    # The "preview" we show in the inbox is the first ~120 chars of body,
    # HTML-stripped just enough that it doesn't read raw <p> tags.
    # Per-column CASE, not a statement-level WHERE: the unread bump must still land.
    # `<=`: a same-id re-delivery still refreshes an edited preview.
    preview = td.strip_html(newest["body"])[:120]
    mid, created_at = newest["message_id"], newest["created_at"]
    # A mass send's optimistic row (attribution._advance_chat_preview) stores a synthetic
    # id above every real one: in that band time decides, as it does there.
    from attribution import _MASS_PLACEHOLDER_BASE  # local, as messages.py
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

    # ── transaction (tip path) ───────────────────────────────
    # A tip rides on a chat_message with isTip=true; its $ value is in
    # `tipAmount` (dollars), captured as tip_cents — `price` is 0 here.
    for p in plans:
        if p.tip_cents:
            await _record_inbound_payment(
                conn, account_id=aid, fan_id=fan_id, message_id=p.msg["message_id"],
                kind="tip", amount_cents=p.tip_cents, occurred_at=p.msg["created_at"])
    return new


def _inbox_patcher(fan_id: int | str, m: dict, *, outbound: bool = False, created_at: datetime | None = None):
    """`relay_cache.patch` fn for one inbound DM: move the fan's row to the top
    of each cached recent page-0 window, set `lastMessage` to this frame (OF's
    /chats `lastMessage` is the same message shape) and bump the unread count.

    Dropping the whole window on every DM made ~24% of inbox loads a 3-call OF
    re-read (p50 ~2 s). Any window the DM cannot be placed in exactly is
    dropped instead: a deeper page (every row below shifts), a non-recent
    order, a frame without a message id, and a page-0 window the fan is not in
    unless `_stub_on_top` can place it. A frame not newer than the row's `lastMessage` (a WS
    replay, or one the window was already read after) leaves the window as is:
    no second unread bump, no re-ordering."""
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
    """A fan new to a page-0 recent window the DM belongs in (unfiltered or Unread, no folder or search): a stub row
    from the frame on top, trimmed to the limit, the entry expired so the next read re-reads OF's real row. Other
    windows drop."""
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
    """Patch before SSE and return the prior row (None if the fan was absent)."""
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
