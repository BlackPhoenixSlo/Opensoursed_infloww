"""service/audiences.py — build mass-send audiences from the local DB.

These return plain `list[int]` fan-id lists meant to be handed to
`OFClient.send_mass_message(included_users=...)` (the `userIds` body field).
DB-first: no OF call needed — we already have every message in `messages`.

It is also the one home for the house broadcast POLICY constants below (the
default contact-guard windows, and the OF-side list names a "reach everyone"
send targets) — those are audience decisions too, they just resolve OF-side
rather than from our tables.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import func, select

from db.engine import get_session
from db.models import (
    Blacklist, Fan, FunnelResponder, FunnelState, List as ListModel, ListMember,
    MassRun, Message, NudgeState, ScheduledJob, SubscriberSnapshot, Transaction,
)
import of_pacing
import of_paging
from fans import _NON_REVENUE_STATUSES

log = logging.getLogger("of-relay.audiences")

# Default contact-guard windows for LIST/ONLINE broadcasts (send_mass_message,
# mass_premade, the UI composer). Absent → these; explicit 0 → off.
BROADCAST_DEFAULT_OUTBOUND_H = 6.0  # skip fans WE touched in the last 6h
BROADCAST_DEFAULT_INBOUND_H = 2.0   # skip fans who messaged US in the last 2h

# The house "everyone" audience — OF's two built-in buckets, resolved server-side
# at send time. BOTH, always: "fans" alone is only the ACTIVE paid subs, and on a
# free page that is a fraction of the reachable list — the same day's fans+following
# blasts reached ~3,000 recipients (live 2026-08-11). Nothing else is targeted: a
# userLists send reaches exactly the named lists, so every other audience is
# excluded by omission.
# A tuple so a caller can't mutate the house default; copy it into payloads.
BROADCAST_LISTS: tuple[str, ...] = ("fans", "following")

# One lock per account around the Auto_Exclude sync + OF send: two concurrent
# broadcasts rewriting the same OF list would attach each other's exclude sets.
# Module-level is process-wide — the relay runs the executor AND the API.
_broadcast_locks: dict[str, asyncio.Lock] = {}


def broadcast_lock(account_id: str) -> asyncio.Lock:
    return _broadcast_locks.setdefault(str(account_id), asyncio.Lock())


async def recent_chat_fan_ids(
    account_id: str,
    *,
    hours: float = 2.0,
    direction: str | None = None,
    limit: int | None = None,
    exclude_bots: bool = True,
    exclude_blacklisted: bool = True,
) -> list[int]:
    """Fan ids we exchanged a message with in the last `hours`, newest first.

    `direction`: None = either side (default), 'in' = fans who messaged us,
    'out' = fans we messaged. `limit` caps the list (the "N ids" cap).
    Bots and blacklisted fans are dropped by default.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with get_session() as s:
        # Newest activity per fan, so a `limit` keeps the MOST recent chatters.
        q = (
            select(Message.fan_id)
            .where(Message.account_id == account_id, Message.created_at >= since)
        )
        if direction in ("in", "out"):
            q = q.where(Message.direction == direction)
        q = (
            q.group_by(Message.fan_id)
            .order_by(func.max(Message.created_at).desc())
        )
        if limit:
            q = q.limit(int(limit))
        ids = [int(r) for r in (await s.execute(q)).scalars().all() if r]
        if not ids:
            return []

        drop: set[int] = set()
        if exclude_bots:
            bots = (await s.execute(
                select(Fan.fan_id).where(
                    Fan.account_id == account_id,
                    Fan.fan_id.in_(ids),
                    Fan.is_bot.is_(True),
                )
            )).scalars().all()
            drop.update(int(b) for b in bots)
        if exclude_blacklisted:
            # Blacklist is global (no account scoping) — just fan_id.
            bl = (await s.execute(
                select(Blacklist.fan_id).where(Blacklist.fan_id.in_(ids))
            )).scalars().all()
            drop.update(int(b) for b in bl)

        return [i for i in ids if i not in drop]


def resolve_window_hours(value, default: float) -> float:
    """The shared None→default / 0→off convention for contact-guard windows:
    key absent/None → `default` hours; an explicit 0 (or negative) → 0.0 =
    guard off; unparseable → `default`."""
    if value is None:
        return float(default)
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return float(default)


async def _recent_nudged_ids(account_id: str, hours: float) -> set[int]:
    """Fan ids stamped in `NudgeState.last_nudged_at` within `hours` — the
    proactive-touch ledger nudge_online writes
    INSTEAD of a `messages` row. Naive-UTC cutoff to match the stored stamps.
    `hours` None/0 → empty."""
    if not hours or hours <= 0:
        return set()
    cutoff = datetime.utcnow() - timedelta(hours=float(hours))
    async with get_session() as s:
        nudged = (await s.execute(
            select(NudgeState.fan_id).where(
                NudgeState.account_id == str(account_id),
                NudgeState.last_nudged_at.is_not(None),
                NudgeState.last_nudged_at >= cutoff,
            )
        )).scalars().all()
    return {int(n) for n in nudged}


async def contact_guard_excludes(
    account_id: str,
    *,
    outbound_hours: float | None = None,
    inbound_hours: float | None = None,
    either_hours: float | None = None,
    extra_ids: Iterable[int] | None = None,
) -> set[int]:
    """Fan ids a PROACTIVE touch must skip — the cross-automation contact guard.

    Unions every "we already touched them / they're already engaged" ledger:
      • `messages` outbound within `outbound_hours` — 1:1 sends AND explicit-id
        mass sends (those write optimistic rows the moment they fire),
      • `NudgeState.last_nudged_at` within `outbound_hours` —
        nudge_online stamps NudgeState INSTEAD of messages (deliberate: per-fan
        rows for every nudge would reshuffle inbox previews constantly),
      • `messages` inbound within `inbound_hours` — active repliers,
      • `messages` in EITHER direction within `either_hours` — "last chatted"
        (the send-side `exclude_last_chat_hours`): a fan we OR they messaged
        recently, so a still-warm two-way chat isn't interrupted by a blast.
        Also folds in the nudge ledger (a nudge is an outbound contact),
      • any `extra_ids` (explicit excludes, exclude-list members, …).

    Bots/blacklisted are NOT filtered out here — this builds an EXCLUDE set,
    not an audience; dropping a blacklisted fan from the excludes would let a
    broadcast reach them. (`recent_chat_fan_ids`' defaults are for includes.)
    A window that is None/0 is off. Returns a plain set[int].
    """
    out: set[int] = {int(x) for x in (extra_ids or [])}
    for hours, direction, nudges_too in (
        (outbound_hours, "out", True),
        (inbound_hours, "in", False),
        # BOTH directions — the inbound guard above only drops fans who messaged
        # US; a warm two-way chat needs the outbound side too.
        (either_hours, None, True),
    ):
        if hours and hours > 0:
            out |= set(await recent_chat_fan_ids(
                account_id, hours=float(hours), direction=direction,
                exclude_bots=False, exclude_blacklisted=False,
            ))
            if nudges_too:
                out |= await _recent_nudged_ids(account_id, float(hours))
    return out


# The one system exclude list (kind='exclude'): a fan on MASSdmEXCLUDE is
# skipped from EVERY mass send — priced PPV blasts, unpriced text, online blast,
# nudge. Mirrored to a same-named pinned OF list by service/lists.py. (It used to
# have a PPV-only twin, MASSppvEXCLUDE; merged into this one 2026-10-21.)
MASSDMEXCLUDE_LIST = "MASSdmEXCLUDE"


async def exclude_list_fan_ids(account_id: str, name: str) -> set[int]:
    """Fan ids on the account's kind='exclude' list with the given NAME
    (MASSDMEXCLUDE). Subtracted from every mass send so a flagged fan never
    receives a broadcast.
    Local-only (of_list_id is NULL) — no OF round-trip."""
    async with get_session() as s:
        rows = (await s.execute(
            select(ListMember.fan_id).where(
                ListMember.list_id.in_(
                    select(ListModel.id).where(
                        ListModel.account_id == str(account_id),
                        ListModel.kind == "exclude",
                        ListModel.name == name,
                    )
                )
            )
        )).scalars().all()
    return {int(x) for x in rows if x is not None}


# Pending-job kinds whose payload names its recipients. These jobs sit in
# `scheduled_jobs` with a future `run_at` and write NO `messages` row until they
# fire — so the time-window contact guard (which reads `messages`) is blind to
# them. `pending_send_fan_ids` extracts their targets so a broadcast fired NOW
# doesn't double-hit a fan a ≤15-min scheduled/drip send is about to reach.
_PENDING_SEND_KINDS = ("scheduled_send", "send_mass_message", "mass_premade")


def _payload_recipient_ids(payload: dict) -> set[int]:
    """Fan ids a queued send payload targets: `fan_id` (scheduled_send 1:1) +
    `included_users`/`fan_ids` (explicit mass) + the same, nested per message
    in a mass_premade `messages` list. Non-numeric entries are dropped."""
    ids: set[int] = set()

    def add(v: object) -> None:
        try:
            ids.add(int(v))
        except (TypeError, ValueError):
            pass

    add(payload.get("fan_id"))
    for key in ("included_users", "fan_ids"):
        for v in payload.get(key) or []:
            add(v)
    for m in payload.get("messages") or []:
        if isinstance(m, dict):
            ids |= _payload_recipient_ids(m)
    return ids


async def pending_send_fan_ids(account_id: str) -> set[int]:
    """Fan ids ALREADY QUEUED for an outbound send whose `messages` row doesn't
    exist yet — the not-yet-fired scheduled / drip jobs the time-window contact
    guard can't see. Reads PENDING `scheduled_jobs` of `_PENDING_SEND_KINDS` and
    unions each payload's named recipients.

    Closes the "15-min-delay sends aren't tracked → re-runs double-hit" gap: a
    chatter's ≤15-min deferred 1:1 (`scheduled_send`) or a queued/drip broadcast
    that hasn't sent yet would otherwise slip past the guard, so a blast fired
    now re-hits a fan who is about to receive one. A job that is already firing
    is 'running' (not 'pending'), so this never cannibalises the caller's own
    recipients."""
    out: set[int] = set()
    async with get_session() as s:
        rows = (await s.execute(
            select(ScheduledJob.payload_json).where(
                ScheduledJob.account_id == str(account_id),
                ScheduledJob.status == "pending",
                ScheduledJob.kind.in_(_PENDING_SEND_KINDS),
            )
        )).scalars().all()
    for payload_json in rows:
        try:
            payload = json.loads(payload_json or "{}")
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            out |= _payload_recipient_ids(payload)
    return out


async def funnel_responder_ids(account_id: str, funnel_id: int) -> set[int]:
    """Fans who ALREADY ANSWERED this funnel — the durable per-funnel dedup set
    (R1/R2). Union of:
      • the `funnel_responders` ledger (written by reply_mass_funnel at discovery
        for every confirmed opener-replier — precise + survives pruning/unsend),
      • `funnel_state` fans for any run of this funnel (belt-and-suspenders for
        fans mid-funnel whose ledger row predates this feature).
    A funnel Send subtracts these so a responder is never re-sent the opener,
    while a brand-new funnel (no rows) is unaffected. Keyed on funnel_id, so
    re-running the SAME funnel to a fresh audience still skips prior answerers
    (a future 'reset responders' action would DELETE the ledger rows)."""
    out: set[int] = set()
    async with get_session() as s:
        led = (await s.execute(
            select(FunnelResponder.fan_id).where(
                FunnelResponder.account_id == str(account_id),
                FunnelResponder.funnel_id == int(funnel_id),
            )
        )).scalars().all()
        out |= {int(x) for x in led}
        st = (await s.execute(
            select(FunnelState.fan_id)
            .join(MassRun, FunnelState.mass_run_id == MassRun.id)
            .where(
                MassRun.account_id == str(account_id),
                MassRun.funnel_id == int(funnel_id),
            )
        )).scalars().all()
        out |= {int(x) for x in st}
    return out


async def close_funnel_discovery_for_queue(
    account_id: str, queue_id: int | None = None, mass_run_id: int | None = None,
) -> int | None:
    """Stamp a funnel `mass_run`'s `discovery_closed_at` (idempotent) when its
    first mass is unsent/deleted — so reply_mass_funnel STOPS enrolling NEW
    repliers off it (#R4). The walker keeps advancing already-engaged fans until
    a purchase halts them (#30). Resolve by `mass_run_id` (validated to the
    account) if given, else the most recent funnel `MassRun` by
    (account_id, queue_id, funnel_id IS NOT NULL). Non-funnel runs are a no-op.
    Returns the closed mass_run_id, or None if unresolved (logged, never raises).
    Called from every unsend path (unsend_messages per-target + cache sweep, and
    the manual DELETE /messages/queue endpoint)."""
    async with get_session() as s:
        run = None
        if mass_run_id is not None:
            run = await s.get(MassRun, int(mass_run_id))
            if run is not None and run.account_id != str(account_id):
                run = None
        if run is None and queue_id is not None:
            run = (await s.execute(
                select(MassRun).where(
                    MassRun.account_id == str(account_id),
                    MassRun.queue_id == int(queue_id),
                    MassRun.funnel_id.is_not(None),
                ).order_by(MassRun.id.desc())
            )).scalars().first()
        if run is None:
            log.info("close_funnel_discovery unresolved account=%s queue=%s run=%s",
                     account_id, queue_id, mass_run_id)
            return None
        if run.funnel_id is None:
            return None  # not a funnel run → nothing to close
        if run.discovery_closed_at is None:  # idempotent
            run.discovery_closed_at = datetime.utcnow()
        return int(run.id)


# How many currently-online fans one thresholded online send reads (OF pages
# the online list 20 at a time, so this is at most 50 reads), and the most ids
# one thresholded send carries in `userIds`. 1000 is the ceiling this route
# already sends explicit ids at (`unread_limit` le=1000); no OF limit is
# captured, so a bigger audience is refused rather than split across POSTs.
ONLINE_ROSTER_MAX = 1000
THRESHOLD_IDS_MAX = 1000


class AudienceUnknown(ValueError):
    """A thresholded send whose picked audience can't be read as ids. Refused:
    sending to every qualifying fan instead would widen it."""


async def _read_list_members(client, names: list[str], what: str) -> set[int]:
    """Members of OF lists, read the way `resolve_recipients_blocking` records
    a list blast; AudienceUnknown when OF won't page one of them."""
    got = await asyncio.to_thread(lambda: resolve_recipients_blocking(client, user_lists=names))
    if got is None:
        raise AudienceUnknown(f"Couldn't read who is on {what} {', '.join(names)}, so a "
                              "thresholded send can't be resolved. Nothing was sent.")
    return set(got)


async def _threshold_base(
    account_id: str, *, user_lists: list | None, excluded_lists: list | None,
    included: list, roster: list[dict] | None, expired_over_days: float | None,
    client, now: datetime,
) -> set[int]:
    """The ids the send would reach WITHOUT the fan-record thresholds, for them
    to narrow: the explicit ids plus every picked list's members. With `roster`
    (online now) only those online; OF's online list is online ∩ Fans, so a
    picked Fans makes it the whole answer. Expired over is applied here: the
    built-in Fans/Following (active rosters an expired fan is never on) stand
    for the crawl's fans expired N+ days, and every other member must be one.
    The excluded lists' members are subtracted, because OF's `excludedLists`
    is verified on list audiences only (of_client.schedule_mass_message), not
    on explicit `userIds`. Raises AudienceUnknown when something can't be read."""
    from automations.lifecycle_messages import expired_fans
    names = [str(n).strip() for n in (user_lists or []) if str(n).strip()]
    online = None if roster is None else {
        int(u["id"]) for u in roster if isinstance(u, dict) and u.get("id") is not None}
    gone = None
    if expired_over_days:
        gone = await expired_fans(account_id, ended_by=now - timedelta(days=float(expired_over_days)))
        if gone is None:
            raise AudienceUnknown(
                "Expired fans aren't known yet: no complete subscriber crawl has run "
                "for this creator (the Smart Lists sync and the lifecycle Triggers run it).")
    built_in = [n for n in names if n.lower() in ("fans", "following")]
    if online is not None and any(n.lower() == "fans" for n in names):
        base = set(online)
    elif gone is not None and built_in:
        # Every expired fan is already the answer: the base is cut to `gone` below.
        base = set(gone)
    else:
        base = {int(i) for i in included}
        if names:
            base |= await _read_list_members(client, names, "the picked list")
        if online is not None:
            base &= online
    if gone is not None:
        base &= set(gone)
    excl = [str(n).strip() for n in (excluded_lists or []) if str(n).strip()]
    if excl and base:
        base -= await _read_list_members(client, excl, "the excluded list")
    return base


async def threshold_fan_ids(
    account_id: str,
    candidates: set[int],
    *,
    min_spent_cents: int | None = None,
    min_tips_cents: int | None = None,
    subscribed_over_days: float | None = None,
    roster: list[dict] | None = None,
    now: datetime | None = None,
) -> set[int]:
    """The `candidates` (`_threshold_base`) that clear EVERY set threshold —
    the online-fans mass message's Total spent / Tipped over / Subscribed over,
    from our own records (Expired over is the base's). None/0 is off.

      • spent   — `fans.lifetime_spend_cents` (every ingest path bumps it),
      • tipped  — the sum of the fan's paid `tip` transactions,
      • subscribed over N days — the earliest subscribe date we know: the
        `fans.subscribed_at` column, the Smart Messages roster snapshot, his
        first subscription/rebill charge, and `subscribedOnData.subscribeAt`
        on `roster` rows (OF subscriber objects, when the caller has them).
        A candidate with no fans row still passes on a known date.

    A fan with no data for a threshold fails it (fail closed: a threshold can
    only shrink the audience). Bots and blacklisted fans never pass."""
    from automations.lifecycle_messages import _sub_data
    now = now or datetime.utcnow()
    roster_since: dict[int, datetime] = {}
    for u in roster or []:
        try:
            fid = int(u["id"])
        except (KeyError, TypeError, ValueError):
            continue
        at = _sub_data(u)[0]
        roster_since[fid] = at if at is not None else roster_since.get(fid)
    async with get_session() as s:
        fans = {int(fid): (int(spent or 0), sub_at, bool(bot))
                for fid, spent, sub_at, bot in (await s.execute(
                    select(Fan.fan_id, Fan.lifetime_spend_cents, Fan.subscribed_at, Fan.is_bot)
                    .where(Fan.account_id == str(account_id)))).all()}
        pool = {int(f) for f in candidates} - {f for f, (_, _, bot) in fans.items() if bot}
        if min_spent_cents:
            pool = {f for f in pool if f in fans and fans[f][0] >= int(min_spent_cents)}
        if min_tips_cents and pool:
            pool &= {int(f) for f in (await s.execute(
                select(Transaction.fan_id)
                .where(Transaction.account_id == str(account_id),
                       Transaction.kind == "tip",
                       Transaction.fan_id.is_not(None),
                       Transaction.status.notin_(_NON_REVENUE_STATUSES))
                .group_by(Transaction.fan_id)
                .having(func.sum(Transaction.amount_cents) >= int(min_tips_cents)))).scalars()}
        if subscribed_over_days and pool:
            since: dict[int, datetime] = {f: at for f, at in roster_since.items() if at}
            def _keep(fid, at):
                if at is not None and (fid not in since or at < since[fid]):
                    since[fid] = at
            for f, (_, sub_at, _) in fans.items():
                _keep(f, sub_at)
            for f, at in (await s.execute(
                select(SubscriberSnapshot.fan_id, SubscriberSnapshot.subscribe_at)
                .where(SubscriberSnapshot.account_id == str(account_id)))).all():
                _keep(int(f), at)
            for f, at in (await s.execute(
                select(Transaction.fan_id, func.min(Transaction.occurred_at))
                .where(Transaction.account_id == str(account_id),
                       Transaction.kind.in_(("subscription", "rebill")),
                       Transaction.fan_id.is_not(None))
                .group_by(Transaction.fan_id))).all():
                _keep(int(f), at)
            cutoff = now - timedelta(days=float(subscribed_over_days))
            pool = {f for f in pool if f in since and since[f] <= cutoff}
        if pool:
            # Blacklist is global (no account scoping) and small.
            pool -= {int(b) for b in (await s.execute(select(Blacklist.fan_id))).scalars()}
    return pool


async def resolve_mass_audience(
    account_id: str,
    *,
    included_users: list[int] | None = None,
    excluded_users: list[int] | None = None,
    recent_chat_hours: float | None = None,
    recent_chat_limit: int | None = None,
    exclude_replied_hours: float | None = None,
    exclude_inbound_hours: float | None = None,
    exclude_last_chat_hours: float | None = None,
    exclude_funnel_responders: int | None = None,
    unread_limit: int | None = None,
    exclude_pending_sends: bool = True,
    exclude_list_name: str | None = None,
    min_spent_cents: int | None = None,
    min_tips_cents: int | None = None,
    subscribed_over_days: float | None = None,
    expired_over_days: float | None = None,
    online_now: bool = False,
    user_lists: list | None = None,
    excluded_user_lists: list | None = None,
    client=None,
) -> dict:
    """Merge the DB/OF-sourced audience knobs into explicit include/exclude
    fan-id lists — the SAME resolution the relay's `/messages/queue` handler
    does, lifted out so the automation path (mass_premade → send_mass_message)
    targets the identical audience as the Mass Online composer.

    ADD to the include set:
      • `recent_chat_hours` (capped to `recent_chat_limit`) — fans we exchanged
        a message with recently (newest first, from the local `messages` table),
      • `unread_limit` — fans with unread messages (the OF "Unread" inbox tab;
        needs an OF `client` — one is built lazily off-thread if not given).
    ADD to the exclude set (via `contact_guard_excludes` — any outbound TOUCH,
    so nudges stamped only in NudgeState count too, and bots/blacklisted are
    kept in the excludes):
      • `exclude_replied_hours` — fans we sent an OUTBOUND message to (or
        nudged) recently,
      • `exclude_inbound_hours` — fans who messaged us INBOUND recently.

    Bots + blacklisted fans are dropped from the INCLUDE side by
    `recent_chat_fan_ids`. Returns `{"included_users": [...],
    "excluded_users": [...]}` (deduped, order kept).
    """
    included = list(included_users or [])
    excluded = list(excluded_users or [])

    if recent_chat_hours:
        recent_ids = await recent_chat_fan_ids(
            account_id, hours=recent_chat_hours, limit=recent_chat_limit,
        )
        included = list(dict.fromkeys([*included, *recent_ids]))

    if unread_limit:
        c = client
        if c is None:
            # Off-thread: building the client + the unread lookup are blocking.
            import automation_executor as ax
            c = await asyncio.to_thread(ax._make_client, account_id)
        unread_ids = await asyncio.to_thread(
            lambda: c.unread_chat_fan_ids(max_fans=int(unread_limit))
        )
        included = list(dict.fromkeys([*included, *unread_ids]))

    # Thresholds (the online-fans mass message's Total spent / Tipped over /
    # Subscribed over / Expired over): every recipient must clear them, so the
    # audience becomes explicit ids — who the send would reach without them
    # (`_threshold_base`: the ids above plus the picked lists' members, online
    # now with `online_now`), narrowed to the fans who qualify. Never wider than
    # the picked audience; a list that can't be read raises AudienceUnknown.
    # `online_now` reads OF's online list NOW (the verified `filter[online]=1`
    # subscribers list nudge_online polls); its rows also carry OF's own
    # subscribe date for the tenure check. The caller drops its list/online
    # audience: the result IS the audience.
    if min_spent_cents or min_tips_cents or subscribed_over_days or expired_over_days:
        c = client
        if c is None and (online_now or user_lists or excluded_user_lists):
            import automation_executor as ax
            c = await asyncio.to_thread(ax._make_client, account_id)
        roster = None
        if online_now:
            # One past the cap: a cut roster would silently drop online fans.
            roster = await asyncio.to_thread(
                lambda: c.iter_online_subscribers(max_fans=ONLINE_ROSTER_MAX + 1))
            if len(roster) > ONLINE_ROSTER_MAX:
                raise AudienceUnknown(
                    f"More than {ONLINE_ROSTER_MAX} fans are online right now, more than a "
                    "thresholded online send reads. Turn off online-only to narrow a list "
                    "instead. Nothing was sent.")
        now = datetime.utcnow()
        base = await _threshold_base(
            account_id, user_lists=user_lists, excluded_lists=excluded_user_lists,
            included=included, roster=roster, expired_over_days=expired_over_days,
            client=c, now=now,
        )
        included = sorted(await threshold_fan_ids(
            account_id, base, min_spent_cents=min_spent_cents, min_tips_cents=min_tips_cents,
            subscribed_over_days=subscribed_over_days, roster=roster, now=now,
        ))

    excludes: list[Iterable] = [excluded]
    if exclude_replied_hours or exclude_inbound_hours or exclude_last_chat_hours:
        guard = await contact_guard_excludes(
            account_id,
            outbound_hours=exclude_replied_hours,
            inbound_hours=exclude_inbound_hours,
            either_hours=exclude_last_chat_hours,
        )
        excludes.append(sorted(guard))

    # Opt-out: subtract the mass-exclude list's members (MASSDMEXCLUDE, for
    # every send). Added to `excluded` so they drop from the explicit userIds set
    # below AND feed `ensure_exclude_list` for list/online audiences. None → no
    # list applied.
    if exclude_list_name:
        excludes.append(sorted(await exclude_list_fan_ids(account_id, exclude_list_name)))

    # Pending/queued sends the messages-based guards can't see yet: a ≤15-min
    # scheduled 1:1 or a drip/queued broadcast writes no `messages` row until it
    # fires, so a blast now would double-hit a fan who's already about to be
    # reached. Exclude their queued targets. Always-on; pass
    # exclude_pending_sends=False to skip. See `pending_send_fan_ids`.
    if exclude_pending_sends:
        excludes.append(sorted(await pending_send_fan_ids(account_id)))

    # Funnel-responder dedup (R1/R2): drop fans who already answered THIS funnel
    # (see `final_audience` for the skipped/total split). For a list send the
    # caller materializes members into `included` first (D6), so the skipped
    # count reflects the real recipients.
    resp: set[int] = set()
    if exclude_funnel_responders:
        resp = await funnel_responder_ids(account_id, int(exclude_funnel_responders))

    out = final_audience(included, excludes, responders=resp)   # no crawl here: never Fail
    return {
        "included_users": out.included,
        "excluded_users": out.excluded,
        # Precise "removed from THIS send" (responders ∩ explicit includes).
        "skipped_funnel_responders": out.skipped_responders,
        # All known answerers for the funnel (ALL are excluded, incl. via the
        # Auto_Exclude list for OF-native audiences we can't enumerate locally) —
        # the honest "N already answered" number for a list/online funnel launch.
        "funnel_responders_total": out.responders_total,
    }


@dataclass(frozen=True)
class Fail:
    """A refused audience: the caller sends / records NOTHING."""
    reason: str


@dataclass(frozen=True)
class Audience:
    included: list            # base order kept, excludes removed
    skipped_responders: list[int]
    responders_total: int
    sources: tuple = ()       # the exclude sources, responders last; see `excluded`

    @property
    def excluded(self) -> list:
        """Every exclude source, first-seen order, deduped. Built on read: only
        `resolve_mass_audience` needs it, `resolve_recipients_blocking` never does."""
        return list(dict.fromkeys(x for src in self.sources for x in src))


def final_audience(
    base: Iterable,
    excludes: Iterable[Iterable] = (),
    *,
    responders: Iterable[int] = (),
    truncated: Iterable[str] = (),
) -> Audience | Fail:
    """THE set algebra `resolve_mass_audience` and `resolve_recipients_blocking`
    share. Pure.

      • `truncated` — labels of crawls that hit the paging backstop. ANY → Fail:
        a truncated crawl is a FAILED sync, never a partial audience (a short
        read would silently drop everyone past the ceiling).
      • `base` — the include ids in send order, kept verbatim (order and any
        duplicates; ids may arrive as str) minus every excluded id.
      • `excludes` — id sources (re-iterable: lists / sets), merged in order,
        first-seen dedupe.
      • `responders` — a funnel's answerers: ALL appended to the excludes (so the
        caller's list-exclude path, Auto_Exclude, drops them for a list/online
        audience too); the ones in `base` are reported as `skipped_responders`
        (the count the UI prints), all of them as `responders_total`.

    Subtracting HERE matters: OF's queue body has no per-user exclusion field
    (`excludedUsers` is silently dropped; verified live 2026-06-12), so excluded
    ids left inside `userIds` WOULD receive the blast. List/online audiences need
    `ensure_exclude_list`."""
    cut = [str(t) for t in truncated]
    if cut:
        return Fail("truncated:" + ",".join(cut))
    base = list(base)
    resp = {int(r) for r in responders}
    skipped = sorted({int(i) for i in base} & resp) if resp else []
    sources = (*excludes, sorted(resp))
    excl = {int(x) for src in sources for x in src}
    return Audience(included=[i for i in base if int(i) not in excl],
                    skipped_responders=skipped, responders_total=len(resp), sources=sources)


AUTO_EXCLUDE_LIST_NAME = "Auto_Exclude"


# Paging moved to the leaf `of_paging`; the old private names stay importable
# from here as the SAME objects (automations/*, lists.py, …). Calls in THIS
# module go through `of_paging.<name>` at call time so a patch of
# `of_paging.page_all_checked` reaches them.
_LIST_PAGE = of_paging.LIST_PAGE
_ROSTER_PAGE = of_paging.ROSTER_PAGE
_page_all_checked = of_paging.page_all_checked
_page_all = of_paging.page_all
_ids_from_pages = of_paging.ids_from_pages


def _crawl_until_cut(crawls) -> tuple[list[set[int]], list[str]]:
    """Run `(label, crawl)` pairs in order, `crawl()` -> (ids, hit_backstop).
    Returns (the id sets read, [label of the cut crawl] or []). Stops loading at
    the first cut — `final_audience` decides what a cut means."""
    got: list[set[int]] = []
    for label, crawl in crawls:
        ids, cut = crawl()
        if cut:
            return got, [label]
        got.append(ids)
    return got, []


def resolve_recipients_blocking(
    client,
    *,
    user_lists: Iterable | None = None,
    included_users: Iterable[int] | None = None,
    excluded_users: Iterable[int] | None = None,
    excluded_user_lists: Iterable | None = None,
    filters: dict | None = None,
    online_only: bool = False,
) -> list[int] | None:
    """WHO OF WILL ACTUALLY SEND THIS BLAST TO — read off OF's own rosters at send
    time — or `None` when that cannot be known. Blocking; call via
    `asyncio.to_thread`. Recorded on `mass_runs.recipients_json` so the chat engine
    can splice the blast into a replier's history within a second of the send.

    WHY IT IS READ AND NOT INFERRED. A `userLists` send writes no per-fan rows, so
    the obvious cheap answer is "everyone in our `fans` table minus
    `excluded_users`". Measured on prod (plans/blast-splice §0.3) that answer is
    wrong for 4 of the 27 chat fans on the incident account — expired subscribers
    OF silently skips, with nothing local that says so: `fans.subscription_status`
    is NULL on all 866 fans of the two blast accounts and `fans.source` is
    upgrade-only. Splicing a man a blast he never received puts words in his mouth
    in HER prompt, which is worse than splicing nothing at all.

    FAILS CLOSED, always, and every branch below is a refusal rather than a
    best-effort answer:
      • `filters` / `online_only` — "online right now" is a moment, not a roster;
        by the time we could page it the set has moved,
      • a `user_lists` entry that is neither `fans`/`following` nor a numeric OF
        list id — we do not know what OF resolved it to,
      • ANY crawl that reports truncation (`of_paging.page_all_checked`'s flag) or raises —
        a short read would silently drop everyone past the ceiling and mark them
        non-recipients.
    A refusal returns None, the caller leaves `recipients_json` NULL, and the run is
    simply never spliced.
    NEVER a partial set: a half-recorded audience is indistinguishable from a
    complete one at read time.

    The remaining over-approximation is a fan on the roster whom OF still skipped
    (blocked, restricted, un-DMable) — the same permanent stragglers
    `_sync_exclude_list_blocking` above already tolerates, and the reason §7's live
    check compares `len(recipients)` against the `chat_queue_finish.total` frame
    rather than demanding equality."""
    if filters or online_only:
        # Not a failure — a deliberate refusal, and the common one (Mass Online).
        log.info("resolve_recipients: online/filtered audience is not a roster "
                 "— leaving the run unrecorded")
        return None
    try:
        def roster(page):          # fans / following: OF's active rosters
            return lambda: of_paging.ids_from_pages(
                lambda off: page(type="active", limit=of_paging.ROSTER_PAGE, offset=off))

        def custom(lid):           # a custom OF list id
            return lambda: of_paging.list_member_ids(client, lid)

        crawls = []
        for raw in (user_lists or []):
            name = str(raw).strip().lower()
            if name == "fans":
                crawls.append((repr(raw), roster(client.subscribers)))
            elif name == "following":
                crawls.append((repr(raw), roster(client.following)))
            elif name.isdigit():
                # A custom OF list id passed straight through to `userLists`.
                crawls.append((repr(raw), custom(int(name))))
            else:
                log.warning("resolve_recipients: unknown user_list %r — audience "
                            "not recorded", raw)
                return None
        n_inc = len(crawls)
        # Every exclusion WE sent, crawled rather than assumed — `excluded_user_lists`
        # holds the AUTOFENCE list and Auto_Exclude (which is where the per-fan
        # `excluded_users` of a list audience actually land: OF's queue body has no
        # per-user exclusion field, see `ensure_exclude_list`).
        crawls += [(f"exclude list {lid!r}", custom(lid)) for lid in (excluded_user_lists or [])]
        sets, cut = _crawl_until_cut(crawls)

        ids = {int(x) for x in (included_users or []) if x is not None}.union(*sets[:n_inc])
        excl = {int(x) for x in (excluded_users or []) if x is not None}
        out = final_audience(sorted(ids), [excl, *sets[n_inc:]], truncated=cut)
        if isinstance(out, Fail):
            log.warning("resolve_recipients: crawl hit the paging backstop (%s) "
                        "— audience not recorded", out.reason)
            return None
        return out.included
    except Exception:
        # The send already succeeded by the time we are called. A roster we could
        # not read costs a splice and nothing else, so it is a WARNING and a None.
        log.warning("resolve_recipients failed — audience not recorded",
                    exc_info=True)
        return None


# Module-level imports of the Auto_Exclude block, kept beside it (this block's
# own region of the file). Leaf modules: no import cycle.
import time  # noqa: E402

import auto_exclude_decide as aed  # noqa: E402


def _auto_exclude_list_id_blocking(client) -> int:
    """The account's Auto_Exclude OF list id, made when missing. Blocking."""
    lists = of_paging.page_all(
        lambda off: client.get_lists(limit=of_paging.LIST_PAGE, offset=off))
    list_id = next((it.get("id") for it in lists
                    if (it.get("name") or "") == AUTO_EXCLUDE_LIST_NAME), None)
    if list_id is None:
        list_id = client.create_list(AUTO_EXCLUDE_LIST_NAME).get("id")
    return list_id


def _sync_exclude_list_blocking(client, ids: set[int]) -> int:
    """Reconcile the account's Auto_Exclude OF custom list to exactly `ids`.
    Blocking (sync OF client) — call via asyncio.to_thread. Returns list id."""
    list_id = _auto_exclude_list_id_blocking(client)

    members, truncated = of_paging.list_member_ids(client, list_id)
    if truncated:
        # Past the backstop: members beyond it are unread, so a stale one there is
        # never removed (an over-exclude). Not raised: the callers fail the send
        # closed on a raise, which would change who gets the blast — loud instead.
        log.error("auto_exclude: Auto_Exclude list=%s crawl hit the paging backstop "
                  "(%d members read) — stale members past it are NOT removed",
                  list_id, len(members))
    _reconcile_exclude_list_blocking(client, list_id, members, ids)
    return int(list_id)


def _reconcile_exclude_list_blocking(client, list_id, members: set[int], ids: set[int]) -> None:
    """A crawled Auto_Exclude to exactly `ids`: `_add_missing_blocking`, then
    remove `members − ids`. Blocking. `members` ends as the list's membership:
    crawled + confirmed adds − confirmed removes (a failed remove stays)."""
    # Stale members are REMOVED, not just superseded — a fan left behind from
    # a previous tick would be excluded from every future broadcast forever.
    stale = sorted(members - ids)
    _add_missing_blocking(client, list_id, members, ids)
    for uid in stale:
        try:
            client.remove_user_from_list(list_id, uid)
        except Exception:  # noqa: BLE001 — a stale member we can't drop is harmless
            log.warning("auto_exclude remove failed account-list=%s uid=%s", list_id, uid)
            continue
        members.discard(uid)


def _add_missing_blocking(client, list_id, members: set[int], ids: set[int]) -> None:
    """Add `ids − members` one by one, ascending; each confirmed add joins
    `members`. Raises only when not one of `ids` is on the list. Blocking."""
    # Per-user adds are best-effort: OF 403s "Unable to add user to user list"
    # for the odd un-listable id (deleted/blocked/restricted account, the creator
    # herself). ONE such id must not abort the whole exclude build and sink the
    # broadcast — skip it and carry on. An un-addable id is almost always also
    # undeliverable, so leaving it off the guard is low-risk. If EVERY add fails
    # the list is unusable, so re-raise the last error (a systemic auth problem,
    # not a stray fan).
    to_add = sorted(ids - members)
    add_fail = 0
    last_err: Exception | None = None
    for uid in to_add:
        try:
            client.add_user_to_list(list_id, uid)
        except Exception as e:  # noqa: BLE001 — per-user tolerance, see above
            add_fail += 1
            last_err = e
            continue
        members.add(uid)
    # Judge the guard by its COVERAGE, never by this tick's add success rate.
    # The old test was `add_fail == len(to_add)` and it sank live broadcasts:
    # an un-addable id never becomes a member, so it returns in `to_add` on
    # EVERY later tick. Once the list reaches steady state (all the real fans
    # already on it) those permanent stragglers are the ONLY entries left to
    # add — so "every add failed" is the ROUTINE case, not the systemic one it
    # was meant to catch, and it fail-closed ~40% of ppv_send's broadcasts
    # (47 of 116 attempts over 45 days, measured from the broadcast:all cell in
    # automation_runs.stats_json — the run itself still reads 'ok' at the top,
    # which is why it hid; see the `reason` propagation in ppv_send). Note a
    # failed sync mints NO mass_runs row at all, so that table cannot be used
    # to count these. What actually makes the guard unusable is an EMPTY list, so
    # that is what we test: if not one id we need excluded is on the list, the
    # next broadcast would blast everyone — fail loudly. If 447 are on it and
    # one straggler won't add, the guard is intact; honour the docstring above
    # ("ONE such id must not abort the whole exclude build") and carry on.
    if ids and not (ids & members):
        raise last_err or RuntimeError(
            "auto_exclude: no ids could be listed — exclude guard is empty")
    if add_fail:
        log.warning("auto_exclude partial account-list=%s added=%d skipped=%d (last=%r)",
                    list_id, len(to_add) - add_fail, add_fail, last_err)


# ── An Auto_Exclude past the 20k backstop (owner decision O2) ─────────────────
# `ensure_exclude_list` crawls the list and reconciles it on every send
# (`_reconcile_exclude_list_blocking`, as `_sync_exclude_list_blocking` does)
# until that crawl hits `of_paging.MAX_PAGES`. Past it, a per-send crawl costs the
# whole read inside `broadcast_lock` and never drops its unread stale members, so
# the list keeps an in-process mirror instead (`aed.Mirror` in `_ae_mirrors`: its
# presence means "big"; per process + per account like `_broadcast_locks`, cold
# after a restart): a send re-resolves the list id (a changed id drops the mirror:
# crawled cold again), then adds only the guard ids the mirror lacks
# (`_add_missing_blocking`), no crawl, no removes. A background refresh
# (single-flight per account, an asyncio task off the send) crawls the whole list
# past the backstop, then reconciles it to the newest guard in `aed.BATCH`-sized
# batches, one short `broadcast_lock` hold each. Declared lag, both closed by the
# next refresh: stale members (over-exclude) and a guard id removed on OF's side.
_ae_mirrors: dict[str, aed.Mirror] = {}        # account -> mirror (big lists only)
_ae_refreshes: dict[str, asyncio.Task] = {}    # account -> its refresh task (single-flight)
AE_PAGE_TRIES = 3             # a refresh page retried in place: the crawl resumes, never restarts


def _ensure_exclude_blocking(account_id: str, client, ids: set[int],
                             verified: dict | None = None) -> tuple[int, bool]:
    """(Auto_Exclude list id, schedule a background refresh). Blocking; the
    caller holds `broadcast_lock`. Same list id as a warm mirror: adds only.
    Else one checked crawl as today; not truncated -> today's reconcile
    (`verified[list id]` = the membership after it); truncated -> a new mirror
    (its crawl cost logged), adds only, refresh. A mirror never verifies."""
    list_id = int(_auto_exclude_list_id_blocking(client))
    m = _ae_mirrors.get(account_id)
    if m is not None and m.list_id == list_id:
        m.guard = frozenset(ids)
        _add_missing_blocking(client, list_id, m.members, ids)
        return list_id, aed.refresh_due(m, time.time())
    if m is not None:
        log.warning("auto_exclude: Auto_Exclude list=%s is now list=%s on OF — mirror "
                    "dropped, crawled again", m.list_id, list_id)
        del _ae_mirrors[account_id]
    t0 = time.monotonic()
    members, truncated = of_paging.list_member_ids(client, list_id)
    if not truncated:
        _reconcile_exclude_list_blocking(client, list_id, members, ids)
        if verified is not None:
            verified[list_id] = frozenset(members)
        return list_id, False
    log.warning("auto_exclude: Auto_Exclude list=%s past the paging backstop (%d read in "
                "%.1fs) — incremental: adds only, stale members go in the background refresh",
                list_id, len(members), time.monotonic() - t0)
    m = _ae_mirrors[account_id] = aed.Mirror(list_id, members, frozenset(ids), time.time())
    _add_missing_blocking(client, list_id, m.members, ids)
    return list_id, True


class _ResumableLists:
    """`list_users_in` retried in place (AE_PAGE_TRIES): a refresh crawl that
    hits one failed page resumes at that offset instead of starting over.
    `pages`: the pages read, so the refresh tells "big" by the pager's own rule."""

    def __init__(self, client):
        self._c = client
        self.pages = 0

    def list_users_in(self, list_id, **kw):
        for i in range(AE_PAGE_TRIES):
            try:
                page = self._c.list_users_in(list_id, **kw)
            except Exception as e:  # noqa: BLE001 — retried, the last one raises
                if i == AE_PAGE_TRIES - 1 or of_pacing.retry_after(e) is not None:
                    raise   # OF's 429: of_pacing already sent it twice (a failed page)
                time.sleep(1.0 + i)
                continue
            self.pages += 1
            return page

    def get_list(self, list_id):
        return self._c.get_list(list_id)   # of_paging.list_size: the count check, not a page


def _ae_apply_batch_blocking(client, m: aed.Mirror, kind: str, uids: list[int],
                             skip: set[int], stats: aed.RefreshStats) -> None:
    """One refresh batch (`aed.next_batch`): add or remove each id, the mirror
    following each confirmed call; a failed id joins `skip` for this refresh.
    Blocking; run under `broadcast_lock`."""
    add = kind == "add"
    call = client.add_user_to_list if add else client.remove_user_from_list
    for uid in uids:
        try:
            call(m.list_id, uid)
        except Exception:  # noqa: BLE001 — refused add (deleted / blocked) or a stale member we can't drop
            skip.add(uid)
            if add:
                stats.add_fail += 1
            else:
                stats.remove_fail += 1
            continue
        if add:
            m.members.add(uid)
            stats.adds += 1
        else:
            m.members.discard(uid)
            stats.removes += 1


async def _refresh_auto_exclude(account_id: str, client) -> aed.RefreshStats | None:
    """A big Auto_Exclude's background refresh: crawl it whole without the lock,
    then in one hold mirror = crawled ∪ the adds sends confirmed meanwhile, then
    one hold per `aed.next_batch` against the newest guard (adds first: an id
    removed on OF's side comes back). Crawled fully before any remove: offset
    paging shifts under removals. Stops when the mirror was replaced (list id
    changed). A crawl that fits under `of_paging.MAX_PAGES` drops the mirror:
    crawled per send again. The attempt is stamped even when it fails, so
    REFRESH_EVERY_S paces retries."""
    aid = str(account_id)
    m = _ae_mirrors.get(aid)
    if m is None:
        return None
    t0 = time.monotonic()
    stats = aed.RefreshStats()
    try:
        async with broadcast_lock(aid):
            snap = set(m.members)
        lists = _ResumableLists(client)
        crawled, truncated = await asyncio.to_thread(
            of_paging.list_member_ids, lists, m.list_id, max_pages=aed.REFRESH_MAX_PAGES)
        stats.crawled, stats.crawl_s = len(crawled), round(time.monotonic() - t0, 2)
        if truncated:
            log.error("auto_exclude refresh account=%s list=%s crawl hit its %d-page backstop "
                      "(%d read) — mirror kept, nothing removed", aid, m.list_id,
                      aed.REFRESH_MAX_PAGES, len(crawled))
            return stats
        async with broadcast_lock(aid):
            if _ae_mirrors.get(aid) is not m:
                return stats
            m.members = crawled | (m.members - snap)
        skip: set[int] = set()
        while True:
            async with broadcast_lock(aid):
                batch = (aed.next_batch(m.members, m.guard, aed.BATCH, skip)
                         if _ae_mirrors.get(aid) is m else None)
                if batch is not None:
                    await asyncio.to_thread(_ae_apply_batch_blocking, client, m, *batch,
                                            skip, stats)
                    stats.holds += 1
            if batch is None:
                break
            await asyncio.sleep(0)
        if lists.pages <= of_paging.MAX_PAGES and _ae_mirrors.get(aid) is m:
            del _ae_mirrors[aid]
    finally:
        m.refreshed_at = time.time()
        stats.s = round(time.monotonic() - t0, 2)
    log.info("auto_exclude refresh account=%s list=%s members=%d %s", aid, m.list_id,
             len(m.members), stats)
    return stats


async def _run_auto_exclude_refresh(account_id: str, client) -> None:
    try:
        # A background walk (of_pacing): the crawl at the shared per-Creator pace, OF's 429
        # retried once. Single-flight: _ae_refreshes. Lock holds never pace: GETs only.
        await of_pacing.walk(account_id, "auto_exclude", lambda: _refresh_auto_exclude(account_id, client))
    except Exception:  # noqa: BLE001 — the next due send schedules another
        log.warning("auto_exclude refresh failed account=%s", account_id, exc_info=True)


def _schedule_auto_exclude_refresh(account_id: str, client):
    """Start the account's background refresh unless one runs (single-flight)."""
    aid = str(account_id)
    t = _ae_refreshes.get(aid)
    if t is not None and not t.done():
        return t
    t = asyncio.get_running_loop().create_task(_run_auto_exclude_refresh(aid, client))
    _ae_refreshes[aid] = t
    return t


async def ensure_exclude_list(
    account_id: str,
    ids: Iterable[int],
    *,
    client=None,
    verified: dict | None = None,
) -> int | None:
    """Mirror `ids` into the per-account Auto_Exclude OF custom list and return
    its id — the ONLY way to exclude individual fans from a `userLists`/online
    broadcast. OF's queue endpoint has no per-user exclusion field (verified
    live 2026-06-12: `excludedUsers` is silently dropped) but DOES honor
    `excludedLists`, so callers pass the returned id via `excluded_user_lists`.

    Returns None for an empty `ids` (nothing to exclude — don't attach the
    list, it may hold stale members from a previous run). Raises on OF
    errors: callers decide whether to fail the broadcast (recommended — a
    blast without its guard is exactly the bug this exists to fix) or warn.

    A list past the 20k paging backstop is kept incrementally (the block above
    `_ensure_exclude_blocking`): every `ids` is on it at return, bar ids OF
    refused to list; its stale members go in a background refresh.

    `verified` (out-param, like `audience_fence_for_broadcast`'s `stats`): on the
    exact path (the list crawled whole) it gains `{list id: frozenset(members)}`,
    the membership after the reconcile (crawled + confirmed adds − confirmed
    removes; a failed remove stays), which the send's Audience crawl subtracts
    without reading the list again. The mirror path sets nothing.
    """
    idset = {int(x) for x in (ids or set())}
    if not idset:
        return None
    c = client
    if c is None:
        import automation_executor as ax
        c = await asyncio.to_thread(ax._make_client, account_id)
    aid = str(account_id)
    list_id, refresh = await asyncio.to_thread(_ensure_exclude_blocking, aid, c, idset, verified)
    if refresh:
        _schedule_auto_exclude_refresh(aid, c)
    log.info("auto_exclude synced account=%s list=%s ids=%d",
             account_id, list_id, len(idset))
    return list_id
