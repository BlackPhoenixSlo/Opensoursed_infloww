"""
messages_unsent.py — the local mirror half of an unsend (`mark_unsent` and
friends), called by the relay's OF routes and by the unsend_messages
automation once OF confirms. `unsent_targets` is the pure rule for which
untagged copies a canceled broadcast retires; `mark_queue_copies_unsent` is its
effect shell. `mark_unsent` / `mark_mass_runs_unsent` are single UPDATEs (their
rule is their WHERE).

messages.py re-exports the shells and `_queue_*` helpers (callers import from
messages); `unsent_targets` is imported from here. This module must not import
messages (messages imports it). attribution is imported lazily to keep it off
messages' import path.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Iterable, Sequence

from sqlalchemy import Select, or_, select, tuple_, update

from db.engine import get_session
from db.models import MassBroadcastCache, MassRun, Message


# ── OF unsend → local mirror ────────────────────────────────────────
# An unsend that OF accepted has to be mirrored onto `messages`, or the
# chat pane's cold-start seed (GET /admin/messages/…, messages.py) paints the
# bubble again on the next reload — as an EMPTY locked shell, since the
# seed carries `media: []` and the row's body is blank for a PPV. The
# relay's DELETE /api/of/v2/messages/{id} and .../queue/{id} routes call
# these right after the upstream call succeeds; the unsend_messages
# automation reaches the same rows through its own `_flip_*` wrappers.

async def mark_unsent(
    account_id: str,
    message_id: int,
    fan_id: int | None = None,
    reason: str = "manual:chat",
) -> int:
    """Flip one per-chat mirror row to unsent. Returns rows flipped (0 when
    we never held the row — OF still unsent it, we just have nothing to
    mirror).

    OF message ids are global, so account + message identifies the row on
    their own and `fan_id` is optional — the relay route parses it out of an
    optional request body. Pass it when you have it: the PK is
    (account_id, fan_id, message_id) and nothing else indexes message_id, so
    with the fan this is a seek and without it a scan of the account's rows.
    Correct either way; the fallback is what keeps a bodyless unsend from
    leaving the stale row this whole helper exists to prevent."""
    stmt = (
        update(Message)
        .where(
            Message.account_id == str(account_id),
            Message.message_id == int(message_id),
        )
        .values(is_unsent=True, unsent_reason=reason,
                unsent_at=datetime.utcnow())
    )
    if fan_id is not None:
        stmt = stmt.where(Message.fan_id == int(fan_id))
    async with get_session() as s:
        res = await s.execute(stmt)
    return res.rowcount or 0


async def mark_mass_runs_unsent(
    account_id: str,
    mass_run_ids: Sequence[int] | Select,
    reason: str = "manual:queue",
) -> int:
    """Flip mass runs' BROADCAST mirror rows once OF cancels their queue.
    `mass_run_ids` is whatever `.in_()` takes — the ids themselves, or a
    SELECT of them (see mark_queue_unsent).

    `funnel_step IS NULL` scopes the flip to the broadcast itself: the
    reply_mass_funnel walker stamps its per-chat follow-ups with the SAME
    mass_run_id (+ a step number), and those stay live on OF when the queue
    is canceled. `purchased_at IS NULL` for the same reason — OF's cancel
    only pulls the broadcast from fans who did NOT buy it, so a purchaser
    keeps their paid copy in-chat forever (seen live on fan 800000667: a
    bought $3.99 PPV vanished from the mirror while OF still showed it)."""
    async with get_session() as s:
        res = await s.execute(
            update(Message)
            .where(
                Message.account_id == str(account_id),
                Message.mass_run_id.in_(mass_run_ids),
                Message.funnel_step.is_(None),
                Message.purchased_at.is_(None),
                Message.is_unsent.is_(False),
            )
            .values(is_unsent=True, unsent_reason=reason,
                    unsent_at=datetime.utcnow())
        )
    return res.rowcount or 0


async def mark_queue_copies_unsent(
    account_id: str,
    queue_id: int,
    *,
    body: str | None,
    sent_at: datetime | None,
    reason: str = "manual:queue",
) -> tuple[int, int]:
    """Flip the UNTAGGED copies of a canceled broadcast, and stamp the run.
    Returns `(copies_flipped, runs_stamped)`.

    `mark_mass_runs_unsent` above only reaches rows that carry a `mass_run_id`,
    and a LIST-audience blast writes none: the per-fan rows we hold for it came
    in later on the inbox poll (`lastMessage`) or a scrape, and neither tags the
    row. So after the 4h mass unsend the copies were gone on OF and still
    `is_unsent = 0` here — every untagged outbound row since 09-04 was — and the
    chat pane's DB seed repainted a retired blast on every open, forever. That is
    the operator's "in the UI those mass messages are not deleted".

    TWO WAYS to recognise a copy, because neither covers the other:
      • `raw_json.queueId == queue_id` — EXACT, at any age. The scrape stores OF's
        frame, and 2,563 outbound rows carry `isFromQueue: true` with the id. Read
        structurally (int or numeric string), never by substring: `LIKE '%queueId%'`
        is a cheap SQL PREFILTER for this branch, not the test.
      • the normalized body matches, inside ±`_BLAST_COPY_SLACK` of `sent_at` — for
        the poll-written rows, which carry no `raw_json` at all. `_norm_body` is
        the same key `adopt_thread_placeholders` pairs on, so OF's `<br />` echo of
        our `\\n` matches; an empty key (a media-only blast) matches nothing.
    Unknown `sent_at` or `body` narrows the window to 7 days and leaves only the id
    branch live — a cache-sourced sweep often has neither.

    `mass_run_id IS NULL` keeps this off the rows `mark_mass_runs_unsent` owns (one
    row, one owner), and `funnel_step`/`purchased_at IS NULL` are its guards for its
    reasons: a funnel follow-up stays live on OF when the queue is canceled, and a
    buyer keeps his paid copy forever.

    ONE SESSION, ONE COMMIT with the `MassRun.unsent_at` stamp: the stamp is what
    stops the chat engines splicing a blast OF no longer serves, so a crash between the
    two writes must not leave the copies hidden and the run still spliceable (or
    the reverse)."""
    # local: keeps attribution off messages' import path.
    from attribution import _BLAST_COPY_SLACK
    slack = _BLAST_COPY_SLACK
    now = datetime.utcnow()
    where = [
        Message.account_id == str(account_id),
        Message.direction == "out",
        Message.mass_run_id.is_(None),
        Message.funnel_step.is_(None),
        Message.purchased_at.is_(None),
        Message.is_unsent.is_(False),
    ]
    if sent_at is not None:
        where.append(Message.created_at >= sent_at - slack)
        # …but the id branch reaches PAST the window (the copy OF delivered 40
        # minutes late), so the upper bound is an OR, not an AND.
        where.append(or_(
            Message.created_at <= sent_at + slack,
            Message.raw_json.like("%queueId%"),
        ))
    else:
        where.append(Message.created_at >= now - timedelta(days=7))
        where.append(Message.raw_json.like("%queueId%"))

    flipped = 0
    async with get_session() as s:
        rows = (await s.execute(
            select(Message.fan_id, Message.message_id, Message.body,
                   Message.created_at, Message.raw_json).where(*where)
        )).all()
        # The WHERE above is the guard (outbound, untagged, live, unbought,
        # not a follow-up); unsent_targets only matches the copies.
        hits = unsent_targets(int(queue_id), rows, body=body, sent_at=sent_at)
        if hits:
            res = await s.execute(
                update(Message)
                .where(
                    Message.account_id == str(account_id),
                    tuple_(Message.fan_id, Message.message_id).in_(hits),
                )
                .values(is_unsent=True, unsent_reason=reason, unsent_at=now)
            )
            flipped = res.rowcount or 0
        stamped = (await s.execute(
            update(MassRun)
            .where(
                MassRun.account_id == str(account_id),
                MassRun.queue_id == int(queue_id),
                MassRun.unsent_at.is_(None),
            )
            .values(unsent_at=now)
        )).rowcount or 0
    return flipped, stamped


async def mark_queue_unsent(
    account_id: str,
    queue_id: int,
    reason: str = "manual:queue",
) -> int:
    """The same flip entered from OF's queue id — what the UI's "also unsend
    from everyone" knows. The queue → runs lookup rides along as a subquery
    so the whole broadcast flips in ONE statement: a per-run loop could stop
    half-applied and leave some recipients' bubbles seeding. 0 when the queue
    was never ours — a scheduled message canceled before it ever sent has no
    mirror rows to flip.

    Also flips the UNTAGGED copies (`mark_queue_copies_unsent`), which for a
    list-audience blast are ALL of them — the tagged half only exists when the
    send had explicit recipients. Counted into the same number: the caller asked
    "how many bubbles did this retire", and where the row came from is not its
    question."""
    run = await mark_mass_runs_unsent(
        account_id,
        select(MassRun.id).where(
            MassRun.account_id == str(account_id),
            MassRun.queue_id == int(queue_id),
        ),
        reason=reason,
    )
    body, sent_at = await _queue_body_and_stamp(account_id, int(queue_id))
    copies, _stamped = await mark_queue_copies_unsent(
        account_id, int(queue_id), body=body, sent_at=sent_at, reason=reason)
    return run + copies


def _queue_id_of(raw_json: str | None) -> int | None:
    """OF's `queueId` off a stored message frame, or None. Structural: a row
    whose JSON is malformed, or whose queueId is neither an int nor a numeric
    string, is NOT a match — a substring test would pair a blast with any row
    that merely mentions the word."""
    if not raw_json:
        return None
    try:
        obj = json.loads(raw_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    qid = obj.get("queueId")
    if isinstance(qid, bool) or qid is None:
        return None
    try:
        return int(qid)
    except (TypeError, ValueError):
        return None


def unsent_targets(
    queue_id: int,
    rows: Iterable[tuple[int, int, str | None, datetime | None, str | None]],
    *,
    body: str | None,
    sent_at: datetime | None,
) -> list[tuple[int, int]]:
    """`(fan_id, message_id)` of the untagged copies a canceled broadcast
    retires, in `rows` order. Pure: `mark_queue_copies_unsent` loads, this
    decides, it UPDATEs.

    `rows` are `(fan_id, message_id, body, created_at, raw_json)` candidates its
    SQL already guarded (outbound, no mass_run_id, no funnel_step, unbought,
    live) and prefiltered (time window / `LIKE '%queueId%'`). A row flips when
    its `raw_json.queueId == queue_id` (exact, any age), or its normalized body
    equals `body`'s inside ±`_BLAST_COPY_SLACK` of `sent_at`. The body branch is
    only honest INSIDE the window — the same text three hours later is a chatter
    typing, not OF delivering. An empty key (no body, a media-only blast) or an
    unknown `sent_at` leaves only the id branch."""
    # local: keeps attribution off messages' import path.
    from attribution import _BLAST_COPY_SLACK, _norm_body
    slack = _BLAST_COPY_SLACK.total_seconds()
    key = _norm_body(body) if body else ""
    hits: list[tuple[int, int]] = []
    for fan_id, message_id, row_body, created_at, raw_json in rows:
        if _queue_id_of(raw_json) == int(queue_id):
            hits.append((int(fan_id), int(message_id)))
            continue
        if not key or sent_at is None or created_at is None:
            continue
        if abs((created_at - sent_at).total_seconds()) > slack:
            continue
        if _norm_body(row_body) == key:
            hits.append((int(fan_id), int(message_id)))
    return hits


async def _queue_body_and_stamp(
    account_id: str, queue_id: int,
) -> tuple[str | None, datetime | None]:
    """What a queue SAID and WHEN it went out — `mass_runs` first (our own send,
    exact), then `mass_broadcast_cache` (OF's own broadcast history, which is how
    we learn about a blast composed in the OF app). Either half may be None; the
    copy matcher degrades accordingly."""
    async with get_session() as s:
        row = (await s.execute(
            select(MassRun.body, MassRun.sent_at).where(
                MassRun.account_id == str(account_id),
                MassRun.queue_id == int(queue_id),
                MassRun.sent_at.is_not(None),
            ).order_by(MassRun.id.desc())
        )).first()
        if row is not None and (row[0] or row[1]):
            return row[0], row[1]
        cached = (await s.execute(
            select(MassBroadcastCache.body_text, MassBroadcastCache.sent_at).where(
                MassBroadcastCache.account_id == str(account_id),
                MassBroadcastCache.queue_id == int(queue_id),
            )
        )).first()
    return (cached[0], cached[1]) if cached is not None else (None, None)
