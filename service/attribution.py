"""
Outbound message attribution writer.

When the relay's `POST /api/of/v2/chats/{chat_id}/messages` handler returns
successfully from OF, we immediately write a `messages` row stamped with
the human actor (from `X-Employee-Id`) or — if no header was present —
the system "Automation" employee. The transcoder pump intentionally skips
outbound chat_message events (event_transcoder.py:158-170), so this is
the single source of truth for outbound persistence.

Design notes:
  • Idempotent: insert-or-ignore against (account_id, fan_id, message_id)
    composite PK so retries / future ws-echo collisions are no-ops.
  • Never raises: the OF send already succeeded; the user's request must
    not 500 because of a DB hiccup or a missing Automation row (migration
    0011 not yet run).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Iterable

import re

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

# `_norm_body` (the placeholder pairing key) and `_seconds_apart` live in the pure
# `attribution_pair`; re-exported here because other modules import them from us.
from attribution_pair import (  # noqa: F401
    _DEFAULT_MANUAL_YIELD_S,
    _norm_body,
    _seconds_apart,
    adopt_windows,
    hard_yield,
    manual_yield_s,
    pair_placeholders,
)
from db.engine import get_session
from db.models import Chat, Message, Transaction

log = logging.getLogger("of-relay.attribution")


def _preview_text(body: str | None) -> str:
    """Inbox-list preview: HTML-stripped, clipped to 120 chars. Mirrors the
    WS transcoder's preview (event_transcoder._strip_html + [:120]) so an
    outbound send and an inbound message read identically in the chat list."""
    if not body:
        return ""
    return re.sub(r"<[^>]+>", "", body).strip()[:120]


async def _advance_chat_preview(
    *,
    account_id: str,
    fan_id: int,
    message_id: int,
    body: str,
    created_at: datetime,
    conn=None,
) -> None:
    """Advance the inbox `chats` preview for an OUTBOUND send.

    The OF-WS pump skips outbound chat events, so without this the inbox seed
    (`/admin/chats/recent`, read straight from `chats`) keeps showing the fan's
    last INBOUND text after an automation / mass send already replied — the
    preview lags until a scrape or the next inbound event overwrites it.

    Forward-only by time: the `WHERE` guard only advances the preview when this
    send is at-or-after the row's current `last_message_at`, so an out-of-order
    or backfilled write can't clobber a newer preview the transcoder set.

    Also zeros `unread_count`: an outbound reply that is the newest message means
    we've answered the fan, so the left-rail unread (blue) badge must clear — it
    only ever went up on inbound WS and previously only zeroed when a chatter
    opened the chat, leaving already-answered fans stuck blue. The same
    forward-only `WHERE` protects this: if a fan message arrived AFTER this send,
    `last_message_at > created_at` fails the guard and the inbound unread is kept.

    Runs in its OWN session — or, given `conn`, inside the caller's
    transaction (the send's own, see write_outbound_attribution), where a
    failed statement undoes only itself — and swallows every error: the
    `chats` FK to `accounts` (or any other hiccup) must never roll back the
    already-written `messages` row or block the live SSE emit. Best-effort,
    like the rest of this module.
    """
    preview = _preview_text(body)
    stmt = (
        sqlite_insert(Chat)
        .values(
            account_id=str(account_id),
            fan_id=int(fan_id),
            last_message_id=int(message_id),
            last_message_at=created_at,
            last_message_preview=preview,
            unread_count=0,
        )
        .on_conflict_do_update(
            index_elements=["account_id", "fan_id"],
            set_={
                "last_message_id": int(message_id),
                "last_message_at": created_at,
                "last_message_preview": preview,
                # We replied → clear the unread (blue) badge for this fan. The
                # forward-only WHERE below keeps this from wiping a fan message
                # that landed after our send.
                "unread_count": 0,
            },
            where=(
                (Chat.last_message_at.is_(None))
                | (Chat.last_message_at <= created_at)
            ),
        )
    )
    try:
        if conn is not None:
            await conn.execute(stmt)
        else:
            async with get_session() as s:
                await s.execute(stmt)
    except Exception:
        log.debug(
            "chat preview advance skipped (account=%s fan=%s msg=%s)",
            account_id, fan_id, message_id, exc_info=True,
        )


async def _manual_yield_seconds(account_id: str) -> int:
    """Per-account manual-chatter stand-down in seconds (Instant reply settings):
    loads `webhook_config_json`, `attribution_pair.manual_yield_s` decides.
    A failed read → the 60 s default."""
    try:
        from db.models import AccountAiConfig
        async with get_session() as s:
            cfg = await s.get(AccountAiConfig, str(account_id))
    except Exception:
        log.debug("manual_yield_seconds read failed", exc_info=True)
        return _DEFAULT_MANUAL_YIELD_S
    return manual_yield_s(cfg.webhook_config_json if cfg else None)


# Synthetic-id band for optimistic mass placeholders. Picked to sit in the
# gap between two hard constraints:
#   • ABOVE every real OF message_id (currently ~9.9e12 and rising slowly)
#     so a freshly-broadcast row sorts as the newest message (the timeline
#     orders by message_id DESC) — that's where a just-sent message belongs
#     and it keeps the row on page 1 of GET /admin/messages.
#   • BELOW JS's 2**53 safe-integer ceiling (9.007e15) so the id round-trips
#     through the frontend's Number-typed `message_id` without precision
#     loss — two placeholders that differ by 1 (consecutive mass_run_ids)
#     must stay distinct as React keys.
# 5e15 leaves ~500x headroom over today's OF ids and ~4e15 of room under the
# ceiling for the (small, autoincrement) mass_run_id. Bump it toward 2**53 if
# OF's ids ever climb close.
_MASS_PLACEHOLDER_BASE = 5_000_000_000_000_000
# Exclusive upper bound of the placeholder band. NOT cosmetic: 6e15 is where
# transaction_ingest._TIP_MSG_ID_BASE starts its own synthetic band of PERMANENT
# ledger-tip history. `adopt_thread_placeholders` scans this band by range and
# DELETES what it matches, so an open-ended `>= BASE` would put those tip rows in
# range of a delete. The ceiling is the guard, not a tidiness nicety.
_MASS_PLACEHOLDER_CEIL = 6_000_000_000_000_000
# How far apart a placeholder and its real row may be and still be the same send.
# The stub is written as the send goes out; the real row lands on the next ingest,
# so the true distance is seconds to a few minutes. Six hours is deliberately
# generous — it forgives a stalled ingest or a backfill — while still refusing the
# pairing this bound exists to stop: a stub whose real row NEVER arrived adopting a
# same-caption send weeks later and stamping it with the wrong run.
_MAX_ADOPT_SECONDS = 6 * 3600.0

# How far from a run's `sent_at` an UNTAGGED outbound row may sit and still be a
# COPY of that broadcast rather than somebody typing. The one home for the
# question, shared by the chat engines' presence pre-pass (so they never splice a
# blast a fan already has) and by `messages.mark_queue_copies_unsent` (so the mirror
# retires the same rows OF just pulled). Two different answers would mean the
# engine splices what the unsend just hid, or hides what it just spliced.
#
# Thirty minutes and not thirty seconds: OF delivers a 23-recipient queue in ~3s,
# but the poll writes each chat's `lastMessage` with OF's OWN delivery stamp and a
# 745-recipient queue is not instantaneous. The false positive — a chatter retyping
# the blast's text 1:1 inside the window — costs one hidden row in the local seed
# (OF still shows it) and one suppressed splice; accepted knowingly.
_BLAST_COPY_SLACK = timedelta(minutes=30)


def _slug_sender(display_name: str) -> str:
    """`"Kingsley 1"` → `"kingsley1"`. Lowercase + strip whitespace so the tag
    reads like the operator's shorthand ("mass-kingsley1") rather than a
    spaced/cased display name. Empty in → empty out."""
    return re.sub(r"\s+", "", (display_name or "").strip().lower())


async def mass_sender_tag(sent_by_employee_id: int | None) -> str:
    """Visible attribution token for a MASS row's `sender_name` — e.g.
    ``"mass-kingsley1"`` for the human who fired the broadcast. Denormalized on
    the message row itself so the tag survives an employee delete and shows in
    raw exports, independent of the `Employee` join the Messages tab does.

    Returns "" (no tag) when:
      • no employee id (degraded chatter resolution), or
      • the id is the system Automation sentinel — an automation-fired mass
        already labels itself via `automation_kind`, so "mass-automation" would
        be noise.

    Best-effort: any lookup failure returns "" — a missing tag must never break
    the (already-succeeded) send's attribution write. A failed sentinel lookup
    assumes a human sender and still resolves the tag.
    """
    if sent_by_employee_id is None:
        return ""
    try:
        from employees import get_automation_employee_id
        auto_id = await get_automation_employee_id()
    except Exception:
        auto_id = None
    return await _mass_sender_tag(sent_by_employee_id, auto_id)


async def _mass_sender_tag(sent_by_employee_id: int | None, auto_id: int | None) -> str:
    """`mass_sender_tag` with the Automation sentinel's id already resolved (None:
    its lookup failed). The one home of the "no sender / sentinel → no tag" rule."""
    if sent_by_employee_id is None:
        return ""
    try:
        if auto_id is not None and int(sent_by_employee_id) == int(auto_id):
            return ""
        from db.models import Employee
        async with get_session() as s:
            emp = await s.get(Employee, int(sent_by_employee_id))
        slug = _slug_sender(emp.display_name) if emp is not None else ""
        return f"mass-{slug}" if slug else ""
    except Exception:
        log.debug("mass_sender_tag resolve failed (emp=%s)",
                  sent_by_employee_id, exc_info=True)
        return ""


def mass_placeholder_message_id(mass_run_id: int) -> int:
    """Collision-proof synthetic `message_id` for an un-reconciled mass
    placeholder row.

    Stable per `(account_id, fan_id, mass_run_id)`: exactly one optimistic
    row per recipient per broadcast, so re-running the close path (which
    is `on_conflict_do_nothing`) never duplicates. See `_MASS_PLACEHOLDER_BASE`
    for why it lands where it does.
    """
    return _MASS_PLACEHOLDER_BASE + int(mass_run_id)


async def _backfill_attribution(
    *,
    account_id: str,
    fan_id: int,
    message_id: int,
    sent_by_employee_id: int | None,
    automation_kind: str | None,
    mass_run_id: int | None,
    funnel_step: str | None,
) -> None:
    """Tag a row somebody else inserted first.

    The insert in `write_outbound_attribution` is `on_conflict_do_nothing`, which
    is right for the chat-preview bump — a duplicate re-run must not re-bump the
    inbox — but it also meant that whenever the WS pump inserted the same
    `(account_id, fan_id, message_id)` first, the send lost its attribution
    permanently. The pump writes the row straight off the websocket with
    `automation_kind` NULL and its own conflict clause never sets that column, so
    nothing downstream could repair it.

    That is not a reporting nit. `_Cand` reads a NULL `automation_kind` as proof a
    HUMAN sent the message:

        if automation_kind is None and mass_run_id is None:
            c.last_human_out_at = created_at

    …and `resume_after_manual_hours` then stands the engine down on that fan — an
    hour of silence on the house default, longer on accounts that raised it. So a
    lost race doesn't just miscount a send, it mutes the bot for a fan who is
    sitting there waiting. Measured 07-26: 309 rows in six days that `vault_sends`
    proves we sent, carrying no attribution at all.

    `coalesce(existing, ours)` per column, so the first writer that actually HAD a
    value keeps it — a second attribution call, or an ingest that already tagged
    the row, is a no-op — and columns we have nothing for are left alone rather
    than blanked. Body, media and `raw_json` are deliberately untouched: the pump
    has the real OF payload for those and we only ever had placeholders."""
    ours = {"sent_by_employee_id": sent_by_employee_id,
            "automation_kind": automation_kind,
            "mass_run_id": mass_run_id,
            "funnel_step": funnel_step}
    have = {k: v for k, v in ours.items() if v is not None}
    if not have:
        return                      # nothing to say about this row
    try:
        async with get_session() as s:
            await s.execute(
                update(Message)
                .where(Message.account_id == str(account_id),
                       Message.fan_id == int(fan_id),
                       Message.message_id == int(message_id))
                .values(**{k: func.coalesce(getattr(Message, k), v)
                           for k, v in have.items()})
            )
        log.info("attribution backfilled onto an existing row: account=%s fan=%s "
                 "msg=%s kind=%s", account_id, fan_id, message_id, automation_kind)
    except Exception:
        # Never break a send over bookkeeping — same contract as the insert above.
        log.warning("attribution backfill failed account=%s fan=%s msg=%s",
                    account_id, fan_id, message_id, exc_info=True)


async def write_outbound_attribution(
    *,
    account_id: str,
    fan_id: int,
    message_id: int,
    sent_by_employee_id: int | None,
    body: str,
    price_cents: int,
    created_at: datetime,
    mass_run_id: int | None = None,
    funnel_step: int | None = None,
    automation_kind: str | None = None,
    emit_live: bool = False,
) -> None:
    """Write the outbound `messages` row.

    `automation_kind`: which automation sent this row (`welcome_chatter_for_info`,
    `send_welcome`, `followup`, `autoreply`, `send_mass_message`,
    `reply_mass_funnel`, `nudge_online`, …). NULL for human / relay sends. This
    is the per-automation breakdown of the otherwise-flat `sent_by_employee_id`
    Automation sentinel — the Messages tab and the per-automation stats panel
    read it.

    `funnel_step` (reply_mass_funnel / A11): the 1-indexed funnel step this row
    represents, so the chat history and audits can tell a funnel message apart
    from a plain reply. NULL for non-funnel sends.

    `emit_live` (WORKER→SSE bridge): when True, emit a synthetic
    `api2_chat_message` SSE event after a successful write so an open chat
    updates live (the OF-WS pump skips outbound, so worker writes have no live
    path otherwise). Defaults False — the human per-chat send path (server.py)
    relies on optimistic UI + reconcile and must NOT get a second live row, so
    only background workers (automations) opt in.

    Best-effort: catches every exception so the caller (the send handler)
    never raises because of a DB write. The OF send already succeeded
    upstream — we don't want a transient DB failure to surface as a 500
    to the user when the message actually went through.

    `sent_by_employee_id` resolution:
      • Caller-provided id wins (parsed from `X-Employee-Id`).
      • If None, fall back to the system Automation employee via
        `get_automation_employee_id()`.
      • If that lookup itself fails (LookupError from migration 0011 not
        having run, or anything else), log a WARNING and write NULL —
        attribution is degraded but the row still lands.
    """
    # The Automation sentinel's id, looked up at most ONCE per write: by the
    # fallback below when it runs, else for the tag / yield decision further down.
    auto_id: int | None = None
    if sent_by_employee_id is None:
        # Chatter session present? Then the resolver in employees.py
        # SHOULD have returned a mirror Employee id, but raised /
        # short-circuited (logged at WARN via that path). Writing
        # Automation here would falsely credit the system sentinel for
        # a chatter's send. Leave it NULL so the row is honest and the
        # UI's "render only on truthy display_name" guard hides the
        # bogus label entirely.
        try:
            from chatters import get_request_chatter
            chatter = get_request_chatter()
        except Exception:
            chatter = None
        if chatter is not None:
            log.warning(
                "outbound message %s left sent_by_employee_id=NULL — "
                "chatter resolver returned None for chatter=%s account=%s. "
                "Inspect logs for 'chatter→employee resolution failed'.",
                message_id, chatter.id, account_id,
            )
        else:
            try:
                from employees import get_automation_employee_id
                sent_by_employee_id = auto_id = await get_automation_employee_id()
            except LookupError:
                log.warning(
                    "Automation employee not found (migration 0011 not run?); "
                    "writing message %s with sent_by_employee_id=NULL",
                    message_id,
                )
            except Exception:
                log.warning(
                    "Automation employee lookup raised; writing message %s "
                    "with sent_by_employee_id=NULL",
                    message_id,
                    exc_info=True,
                )

    # MASS row → the visible sender tag ("mass-kingsley1", `_mass_sender_tag`); a
    # 1:1 send stays untagged (the Messages tab surfaces it via the Employee join).
    # 1:1 row → maybe the W7 HARD YIELD (`attribution_pair.hard_yield`: who counts
    # as a human 1:1 sender, why a broadcast never rests its audience). Both AFTER
    # the sent_by fallback above, so an automation-fired send (Automation
    # sentinel) gets neither. Reads only, BEFORE the write, so the row, the preview
    # and the cooldown are ONE short write transaction. A failed sentinel lookup
    # skips the yield (the tag still resolves); late imports avoid the
    # attribution↔executor cycle.
    if sent_by_employee_id is not None and auto_id is None:
        try:
            from employees import get_automation_employee_id
            auto_id = await get_automation_employee_id()
        except Exception:
            if mass_run_id is None:
                log.debug("w7 hard-yield cooldown skipped", exc_info=True)
    if mass_run_id is not None:
        mass_tag = await _mass_sender_tag(sent_by_employee_id, auto_id)
    else:
        mass_tag = ""
    # Stand-down duration is per-account (Instant reply settings,
    # webhook_config_json.manual_yield_minutes); default 1 min, 0 disables.
    yield_s = (await _manual_yield_seconds(str(account_id))
               if hard_yield(mass_run_id=mass_run_id, sent_by=sent_by_employee_id,
                             automation_id=auto_id) else 0)

    try:
        # Ours, not OF's (who sent it is nowhere on OF): its own immediate
        # transaction, not the OF-cache writer's batch.
        from db import of_writer
        async with of_writer.immediate() as conn:
            stmt = sqlite_insert(Message).values(
                account_id=str(account_id),
                fan_id=int(fan_id),
                message_id=int(message_id),
                direction="out",
                sender_name=mass_tag,
                body=body,
                media_ids="[]",
                media_count=0,
                price_cents=int(price_cents),
                is_paid=False if (price_cents or 0) > 0 else None,
                is_tip=False,
                sent_by_employee_id=sent_by_employee_id,
                mass_run_id=mass_run_id,
                funnel_step=funnel_step,
                automation_kind=automation_kind,
                raw_json=None,
                created_at=created_at,
                ingested_at=datetime.utcnow(),
            ).on_conflict_do_nothing(
                index_elements=["account_id", "fan_id", "message_id"],
            )
            res = await conn.execute(stmt)
            if (res.rowcount or 0) > 0:
                # Advance the inbox preview — only on a real insert, so a
                # duplicate re-run can't re-bump the chat. Keeps the local
                # `/admin/chats/recent` seed in step with the just-sent text
                # instead of lagging on the fan's last inbound message. Its own
                # try/except (never breaks the write).
                await _advance_chat_preview(
                    account_id=str(account_id), fan_id=int(fan_id),
                    message_id=int(message_id), body=body, created_at=created_at,
                    conn=conn,
                )
                if yield_s > 0:
                    try:
                        from automation_executor import start_fan_cooldown
                        await start_fan_cooldown(str(account_id), int(fan_id),
                                                 cooldown_s=yield_s, conn=conn)
                    except Exception:
                        log.debug("w7 hard-yield cooldown skipped", exc_info=True)
        if (res.rowcount or 0) == 0:
            # Somebody inserted this row first — tag it anyway. See the docstring
            # on _backfill_attribution: losing the tag does not just skew stats,
            # it MUTES the engine on that fan.
            await _backfill_attribution(
                account_id=str(account_id), fan_id=int(fan_id),
                message_id=int(message_id),
                sent_by_employee_id=sent_by_employee_id,
                automation_kind=automation_kind,
                mass_run_id=mass_run_id, funnel_step=funnel_step,
            )
        log.info(
            "attribution: account=%s fan=%s msg=%s emp=%s mass_run=%s",
            account_id, fan_id, message_id, sent_by_employee_id, mass_run_id,
        )
        # Emit ONLY when a row was actually inserted — on_conflict_do_nothing
        # makes a re-run/duplicate a no-op, and re-broadcasting it would re-bump
        # an already-shown chat to the top of the inbox for nothing.
        if emit_live and (res.rowcount or 0) > 0:
            from events import publish_db_message  # local import avoids a cycle
            await publish_db_message(
                account_id=str(account_id), fan_id=int(fan_id),
                message_id=int(message_id), body=body, created_at=created_at,
                price_cents=int(price_cents),
            )

    except Exception:
        log.exception(
            "attribution write failed (account=%s fan=%s msg=%s)",
            account_id, fan_id, message_id,
        )


async def write_mass_optimistic_rows(
    *,
    account_id: str,
    fan_ids: Iterable[int],
    mass_run_id: int,
    sent_by_employee_id: int | None,
    body: str,
    price_cents: int,
    created_at: datetime,
    automation_kind: str | None = None,
    emit_live: bool = False,
) -> int:
    """Write one optimistic outbound `messages` row per *known* recipient at
    mass-send time. Returns the number of rows attempted.

    `emit_live` (WORKER→SSE bridge): when True, emit a synthetic
    `api2_chat_message` per recipient after the write so each open chat shows
    the broadcast live. Defaults False; only background workers opt in.

    Why this exists: OF's broadcast endpoint (`POST /messages/queue`) returns
    a queue object, not per-fan message ids, and the WS pump deliberately
    skips outbound chat_message events (event_transcoder.py ~236). So without
    this, a mass send lands NO `messages` row and the chat cache shows nothing
    until — if ever — a reconciler backfills it. Each row carries:

      • a synthetic `message_id` (`mass_placeholder_message_id`) that can't
        collide with a real OF id,
      • `temp_id` so a later reconciler can match + replace it,
      • `mass_run_id` linking it to the broadcast.

    When OF echoes the real per-fan id, the caller writes the real row via
    `write_outbound_attribution` and drops the placeholder via
    `reconcile_mass_placeholder`.

    Only EXPLICIT recipients (`userIds`) are knowable here, and a list audience
    (`userLists`) is deliberately NOT expanded into rows: 833 recipients × 7
    blasts a day is a quarter of a million synthetic rows a month for a thread
    the fan may never open. What a list audience gets instead is the SAME row,
    materialized at READ time — `mass_runs` now carries the body, the send stamp
    and the recorded recipient set, and the chat engines' history read builds exactly this
    tuple in memory for each recipient thread that lacks the copy
    (plans/blast-splice A.3). Change the shape here and change it there.
    The durable row still arrives from OF, via the scrape.

    Best-effort: never raises (the OF send already succeeded). Idempotent via
    `on_conflict_do_nothing` on the composite PK.
    """
    placeholder_id = mass_placeholder_message_id(mass_run_id)
    # NULL = no PPV; False = PPV not yet purchased. Mirrors the per-chat
    # outbound writer above so the PPV/All-Messages tabs read consistently.
    is_paid = False if (price_cents or 0) > 0 else None
    # Visible "who fired this broadcast" tag (e.g. "mass-kingsley1"); "" for an
    # automation-fired mass (its automation_kind already labels it). Resolved
    # once — one employee per broadcast.
    sender_tag = await mass_sender_tag(sent_by_employee_id)

    seen: set[int] = set()
    rows: list[dict] = []
    for raw in fan_ids:
        try:
            fid = int(raw)
        except (TypeError, ValueError):
            continue
        if fid in seen:
            continue
        seen.add(fid)
        rows.append({
            "account_id": str(account_id),
            "fan_id": fid,
            "message_id": placeholder_id,
            "direction": "out",
            "sender_name": sender_tag,
            "body": body,
            "media_ids": "[]",
            "media_count": 0,
            "price_cents": int(price_cents),
            "is_paid": is_paid,
            "is_tip": False,
            "sent_by_employee_id": sent_by_employee_id,
            "temp_id": f"mass:{int(mass_run_id)}:{fid}",
            "mass_run_id": int(mass_run_id),
            "automation_kind": automation_kind,
            "raw_json": None,
            "created_at": created_at,
            "ingested_at": datetime.utcnow(),
        })

    if not rows:
        return 0

    try:
        async with get_session() as s:
            stmt = sqlite_insert(Message).values(rows).on_conflict_do_nothing(
                index_elements=["account_id", "fan_id", "message_id"],
            )
            await s.execute(stmt)
        # Advance each recipient's inbox preview to the broadcast text so the
        # local seed shows the just-sent mass message instead of the fan's last
        # inbound. Time-guarded forward-only inside _advance_chat_preview.
        for r in rows:
            await _advance_chat_preview(
                account_id=str(account_id), fan_id=int(r["fan_id"]),
                message_id=int(r["message_id"]), body=body, created_at=created_at,
            )
        log.info(
            "mass optimistic: account=%s run=%s rows=%d emp=%s",
            account_id, mass_run_id, len(rows), sent_by_employee_id,
        )
        if emit_live:
            from events import publish_db_message  # local import avoids a cycle
            for r in rows:
                await publish_db_message(
                    account_id=str(account_id), fan_id=int(r["fan_id"]),
                    message_id=int(r["message_id"]), body=body,
                    created_at=created_at, price_cents=int(price_cents),
                )
    except Exception:
        log.exception(
            "mass optimistic write failed (account=%s run=%s)",
            account_id, mass_run_id,
        )
    return len(rows)


async def stamp_mass_recipients(mass_run_id: int | None, ids) -> int | None:
    """Record WHO OF sent a broadcast to on its `mass_runs` row. Returns how many
    ids were written, or None when nothing was.

    `ids` is whatever `audiences.resolve_recipients_blocking` returned:
    `None` (the audience could not be known) leaves `recipients_json` NULL, which
    is the one value the read side treats as "never splice this run". An empty
    LIST is different and is written as `[]` — "we know, and it reached nobody".

    Best-effort like every other writer in this module: the OF send already
    happened, so a failure here costs the splice and nothing else."""
    if mass_run_id is None or ids is None:
        return None
    try:
        clean = sorted({int(x) for x in ids if x is not None})
    except (TypeError, ValueError):
        log.warning("stamp_mass_recipients: unusable id list for run=%s", mass_run_id)
        return None
    try:
        from db.models import MassRun  # local import: avoids a models import cycle
        async with get_session() as s:
            mr = await s.get(MassRun, int(mass_run_id))
            if mr is None:
                return None
            mr.recipients_json = json.dumps(clean)
        return len(clean)
    except Exception:
        log.warning("stamp_mass_recipients failed (run=%s)", mass_run_id, exc_info=True)
        return None


async def adopt_thread_placeholders(s, *, account_id: str, fan_id: int) -> int:
    """Fold every un-reconciled optimistic placeholder in ONE thread into OF's
    real rows. Runs on the INGEST side, inside the caller's session. Returns how
    many were adopted.

    Why this exists: `write_mass_optimistic_rows` stamps a synthetic-id row at
    send time because OF's queue endpoint returns no per-fan ids and the WS pump
    skips outbound. When OF *does* echo the ids inline, send_mass_message calls
    `reconcile_mass_placeholder` right away. When it does NOT — `ppv_send`, and
    any list/online audience — the real row only shows up hours later via the
    scrape, and nothing ever dropped the placeholder. Two costs, both live in
    prod: the thread rendered the PPV twice, and the real row (carrying no
    `automation_kind`) read as a HUMAN send, poisoning every "did a chatter
    touched this thread" signal and inflating creator-typed message counts.

    PER THREAD, not per message, and that is the whole shape of it. OF gives us
    no id linking a placeholder to its real row, so the pairing key is
    (account, fan) + NORMALIZED body (`_norm_body` — OF echoes our `\n` back as
    `<br />`, and the byte-equality key this shipped with matched no multi-line
    caption at all) — which means the work is inherently about a thread's whole
    placeholder set, not about the one row being upserted.
    Measured on prod 2026-07-25, only 9.4% of placeholders (1,448 of 15,341) ever
    have a real twin at all, so a per-message hook would spend a lookup on every
    outbound row of every re-scrape to find nothing the overwhelming majority of
    the time. One indexed range-seek per thread that usually returns empty is
    both cheaper and MORE complete: an older placeholder heals as soon as the
    thread is touched again, instead of only when its own message re-upserts.

    `price_cents` is adopted only when OF's row reports 0 and the placeholder
    holds a real price — OF omits the price on some scraped PPV rows, and that
    zero would otherwise erase the sale's value. `is_paid`/`purchased_at` move
    the same one-way: a stub that KNOWS about a purchase can promote a real row
    OF scraped as unpaid, never the reverse.

    Deleting a row means everything that POINTS at it moves first, in this same
    session, or the delete silently destroys the reference:
      • `transactions.message_id` — the ledger links a purchase straight to the
        synthetic id (27 live rows, $552.80), and an orphan falls into the
        revenue view's orphan branch. Repointed; an unresolvable collision on
        `uq_tx_msg` REFUSES the adoption rather than dropping either side.
      • `chats.last_message_id` — the inbox preview. Both ingest updaters
        advance on numeric-id monotonicity, and a real OF id (~1.1e13) can never
        exceed 5e15, so a chat left pointing at a deleted stub is frozen
        FOREVER. Remapped to the real row.

    Best-effort: a failure leaves today's harmless duplicate, never a missing
    message, so it swallows and reports 0.
    """
    try:
        # Cheap PK-range seek; the overwhelmingly common answer is "none".
        placeholders = (await s.execute(
            select(Message).where(
                Message.account_id == str(account_id),
                Message.fan_id == int(fan_id),
                Message.message_id >= _MASS_PLACEHOLDER_BASE,
                Message.message_id < _MASS_PLACEHOLDER_CEIL,
            )
        )).scalars().all()
        if not placeholders:
            return 0

        # Keyed placeholders only (`_norm_body` "" is a refusal — media-only stubs
        # never pair). Normalizing stays linear: each stub here and again in
        # `pair_placeholders`, each real row once there, never per PAIR — prod's
        # worst thread is 51 stubs x 1,901 outbound rows on the INBOX RENDER path
        # (messages.py), so O(P + R), not O(P x R).
        keyed = [p for p in placeholders if _norm_body(p.body)]
        if not keyed:
            return 0

        # Read only the outbound rows that could WIN a pair: those within the
        # bound of some KEYED placeholder. This is the fast exit the removed
        # `body.in_()` filter used to provide, and it has to be tight, because
        # this runs on the inbox poll (60-90s) for every outbound-last chat and
        # 93.7% of stubs never pair — so whatever this costs, it costs forever.
        #
        # Per-stub ranges OR'd together, not one `[min-6h, max+6h]` span: a
        # thread holding a July stub and a September one would otherwise read
        # every outbound row in between, all of which are further than the bound
        # from BOTH and can never win. Overlapping ranges are merged first so a
        # burst of stubs seconds apart is one clause, not fifty.
        #
        # Keyed placeholders only. A media-only stub (`<photo>`, key "") is
        # unpairable and never deleted, so it would widen this read on every
        # poll for the life of the thread and buy nothing.
        #
        # Rows with an unusable created_at fall outside every range, and would
        # have scored `inf` anyway (see `_seconds_apart`).
        ranges = adopt_windows([p.created_at for p in keyed if p.created_at is not None],
                               timedelta(seconds=_MAX_ADOPT_SECONDS))
        if not ranges:
            return 0        # every keyed stub has an unusable clock — all `inf`
        reals = (await s.execute(
            select(Message).where(
                Message.account_id == str(account_id),
                Message.fan_id == int(fan_id),
                Message.message_id < _MASS_PLACEHOLDER_BASE,
                Message.direction == "out",
                or_(*[and_(Message.created_at >= lo, Message.created_at <= hi)
                      for lo, hi in ranges]),
            )
        )).scalars().all()

        # Which stub folds into which row: `pair_placeholders` (nearest-first,
        # the 6 h bound, one-to-one, a row another run already holds is left).
        adopted = 0
        for ph, real in pair_placeholders(keyed, reals, _MAX_ADOPT_SECONDS):
            # Move the ledger reference BEFORE the delete, or refuse the pair.
            # The pair has already claimed BOTH sides (see pair_placeholders), so
            # a refusal leaves today's duplicate — the status quo, reversible —
            # rather than letting either row fall through to a farther, wrong one.
            if not await _repoint_transaction(
                s, account_id=account_id, fan_id=fan_id,
                old_id=int(ph.message_id), new_id=int(real.message_id),
            ):
                continue
            real.automation_kind = real.automation_kind or ph.automation_kind
            real.mass_run_id = real.mass_run_id or ph.mass_run_id
            real.sent_by_employee_id = (real.sent_by_employee_id
                                        or ph.sent_by_employee_id)
            if not (real.price_cents or 0) and (ph.price_cents or 0):
                real.price_cents = int(ph.price_cents)
            # One-way, like the price: a stub that saw the unlock promotes a row
            # OF scraped as unpaid. Never the reverse — OF's `True` is truth.
            if ph.is_paid and not real.is_paid:
                real.is_paid = True
            if real.purchased_at is None and ph.purchased_at is not None:
                real.purchased_at = ph.purchased_at
            # One-way too: an unsend that landed on the stub before the scrape
            # paired it (the auto-unsend race) must survive the delete, or the
            # sender's DB shows a broadcast OF already took down as live.
            if ph.is_unsent and not real.is_unsent:
                real.is_unsent = True
                real.unsent_at = real.unsent_at or ph.unsent_at
                real.unsent_reason = real.unsent_reason or ph.unsent_reason
                real.unsent_by_employee_id = (real.unsent_by_employee_id
                                              or ph.unsent_by_employee_id)
            # The inbox preview points at the id we are about to delete.
            await s.execute(
                update(Chat)
                .where(
                    Chat.account_id == str(account_id),
                    Chat.fan_id == int(fan_id),
                    Chat.last_message_id == int(ph.message_id),
                )
                .values(
                    last_message_id=int(real.message_id),
                    last_message_at=real.created_at,
                    last_message_preview=_preview_text(real.body),
                )
            )
            await s.delete(ph)
            adopted += 1
        return adopted
    except Exception:
        log.exception("placeholder adopt failed (account=%s fan=%s)",
                      account_id, fan_id)
        return 0


_LOGGED_TX_COLLISIONS: set[tuple[str, int, int]] = set()
_LOGGED_TX_COLLISIONS_MAX = 512


async def _repoint_transaction(
    s, *, account_id: str, fan_id: int, old_id: int, new_id: int,
) -> bool:
    """Move any ledger row referencing the placeholder onto the real row.
    Returns False when the move cannot be made — the caller must then leave the
    placeholder (and its duplicate) alone rather than delete a referenced row.

    Why this is not optional: `transaction_ingest`'s PPV candidate query does not
    exclude the 5e15 band, so a purchase can and does link straight to a
    synthetic id (27 live rows, $552.80; 4 of them on rows the pairing fix now
    deletes). Deleting underneath the reference drops those dollars into the
    revenue view's orphan branch, where no later ingest can recover them —
    nothing ever re-derives a message_id for an already-ingested ledger row.

    The refusal case is `uq_tx_msg`, the partial-unique on
    (account_id, fan_id, message_id): if the REAL row already carries its own
    transaction, the purchase was recorded twice and there is no non-destructive
    merge — repointing violates the constraint, and deleting either side loses an
    amount. Keeping today's duplicate message is the cheaper wrong.
    """
    rows = (await s.execute(
        select(Transaction).where(
            Transaction.account_id == str(account_id),
            Transaction.fan_id == int(fan_id),
            Transaction.message_id == int(old_id),
        )
    )).scalars().all()
    if not rows:
        return True
    taken = (await s.execute(
        select(Transaction.id).where(
            Transaction.account_id == str(account_id),
            Transaction.fan_id == int(fan_id),
            Transaction.message_id == int(new_id),
        ).limit(1)
    )).scalar_one_or_none()
    # >1 row on the stub can only exist as legacy pre-constraint data; repointing
    # them all would collide with each other on the way in.
    if taken is not None or len(rows) > 1:
        # Once per pair per process. A refused pair is retried on EVERY ingest of
        # the thread and never resolves itself, so an unconditional warn is a
        # permanent 60-90s heartbeat in the relay log for a condition nobody can
        # act on twice. Bounded so a pathological account cannot grow it forever.
        seen = (str(account_id), int(old_id), int(new_id))
        if seen not in _LOGGED_TX_COLLISIONS:
            if len(_LOGGED_TX_COLLISIONS) >= _LOGGED_TX_COLLISIONS_MAX:
                _LOGGED_TX_COLLISIONS.clear()
            _LOGGED_TX_COLLISIONS.add(seen)
            log.warning(
                "placeholder adopt refused — ledger collision (account=%s fan=%s "
                "stub=%s real=%s stub_rows=%d real_taken=%s)",
                account_id, fan_id, old_id, new_id, len(rows), taken,
            )
        return False
    rows[0].message_id = int(new_id)
    return True


async def reconcile_mass_placeholder(
    *,
    account_id: str,
    fan_id: int,
    mass_run_id: int,
) -> None:
    """Drop the optimistic placeholder row for `(account, fan, run)` once the
    real OF `message_id` for that recipient has been persisted.

    Best-effort: the real row is already written, so a failed cleanup leaves a
    harmless duplicate (the placeholder), never a missing message.
    """
    try:
        async with get_session() as s:
            await s.execute(
                delete(Message).where(
                    Message.account_id == str(account_id),
                    Message.fan_id == int(fan_id),
                    Message.message_id == mass_placeholder_message_id(mass_run_id),
                )
            )
    except Exception:
        log.exception(
            "mass placeholder reconcile failed (account=%s fan=%s run=%s)",
            account_id, fan_id, mass_run_id,
        )
