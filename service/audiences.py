from __future__ import annotations

import asyncio
import contextlib
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
import platforms
from send_tripwire import CellHeld
from fans import _NON_REVENUE_STATUSES
from side_effect_gate import PLATFORM_LACKS_PREFIX

log = logging.getLogger("of-relay.audiences")

BROADCAST_DEFAULT_OUTBOUND_H = 6.0
BROADCAST_DEFAULT_INBOUND_H = 2.0

# BOTH always: "fans" alone is only active paid subs, a fraction of the reachable list on a free page; a tuple so callers can't mutate the default.
BROADCAST_LISTS: tuple[str, ...] = ("fans", "following")

# One lock per account: concurrent broadcasts rewriting the same OF list would attach each other's exclude sets; process-wide (relay runs executor and API).
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
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with get_session() as s:
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
            bl = (await s.execute(
                select(Blacklist.fan_id).where(Blacklist.fan_id.in_(ids))
            )).scalars().all()
            drop.update(int(b) for b in bl)

        return [i for i in ids if i not in drop]


def resolve_window_hours(value, default: float) -> float:
    if value is None:
        return float(default)
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return float(default)


async def _recent_nudged_ids(account_id: str, hours: float) -> set[int]:
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
    # Bots/blacklisted are NOT filtered: this is an EXCLUDE set, dropping a blacklisted fan would let a broadcast reach them. nudge_online stamps NudgeState instead of messages.
    out: set[int] = {int(x) for x in (extra_ids or [])}
    for hours, direction, nudges_too in (
        (outbound_hours, "out", True),
        (inbound_hours, "in", False),
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


# A fan on this list is skipped from EVERY mass send; mirrored to a same-named pinned OF list by service/lists.py.
MASSDMEXCLUDE_LIST = "MASSdmEXCLUDE"


async def exclude_list_fan_ids(account_id: str, name: str) -> set[int]:
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


# Queued jobs write no `messages` row until they fire, so the time-window contact guard is blind to them.
_PENDING_SEND_KINDS = ("scheduled_send", "send_mass_message", "mass_premade")


def _payload_recipient_ids(payload: dict) -> set[int]:
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
            return None
        if run.discovery_closed_at is None:
            run.discovery_closed_at = datetime.utcnow()
        return int(run.id)


# No OF limit is captured for userIds, so a bigger audience is refused rather than split across POSTs.
ONLINE_ROSTER_MAX = 1000
THRESHOLD_IDS_MAX = 1000


class AudienceUnknown(ValueError):
    # Refused: sending to every qualifying fan instead would widen the audience.
    pass


class AudienceRefusal(AudienceUnknown):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"This platform can't read that audience in full ({reason}). Nothing was sent.")


def audience_refusal(account_id: str, user_lists, excluded) -> str | None:
    names = {str(n).strip().lower() for g in (user_lists, excluded) for n in (g or ())}
    if "following" not in names:
        return None
    return f"{PLATFORM_LACKS_PREFIX}following" if platforms.refusal_for_account(account_id, "following") else None


async def _read_list_members(client, names: list[str], what: str, *, account_id: str) -> set[int]:
    got = await asyncio.to_thread(roster_audience_blocking, client, user_lists=names, account_id=account_id)
    if got is None:
        raise AudienceUnknown(f"Couldn't read who is on {what} {', '.join(names)}, so the "
                              "send's audience can't be resolved. Nothing was sent.")
    return set(got)


async def drop_exclude_list_members(client, ids: Iterable, excluded_lists, *, account_id: str) -> list[int]:
    # OF's `excludedLists` is verified on list audiences only, not explicit `userIds`, so exclude lists are subtracted here.
    ids = [int(i) for i in ids]
    excl = [str(n).strip() for n in (excluded_lists or []) if str(n).strip()]
    if not excl or not ids:
        return ids
    drop = await _read_list_members(client, excl, "the excluded list", account_id=account_id)
    return [i for i in ids if i not in drop]


async def _threshold_base(
    account_id: str, *, user_lists: list | None, excluded_lists: list | None,
    included: list, roster: list[dict] | None, expired_over_days: float | None,
    client, now: datetime,
) -> set[int]:
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
        base = set(gone)
    else:
        base = {int(i) for i in included}
        if names:
            base |= await _read_list_members(client, names, "the picked list", account_id=account_id)
        if online is not None:
            base &= online
    if gone is not None:
        base &= set(gone)
    return set(await drop_exclude_list_members(client, base, excluded_lists, account_id=account_id))


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
    # Fail closed: a fan with no data for a threshold fails it, so a threshold can only shrink the audience.
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
            import automation_executor as ax
            c = await asyncio.to_thread(ax._make_client, account_id)
        unread_ids = await asyncio.to_thread(
            lambda: c.unread_chat_fan_ids(max_fans=int(unread_limit))
        )
        included = list(dict.fromkeys([*included, *unread_ids]))

    if min_spent_cents or min_tips_cents or subscribed_over_days or expired_over_days:
        c = client
        if c is None and (online_now or user_lists or excluded_user_lists):
            import automation_executor as ax
            c = await asyncio.to_thread(ax._make_client, account_id)
        roster = None
        if online_now:
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

    if exclude_list_name:
        excludes.append(sorted(await exclude_list_fan_ids(account_id, exclude_list_name)))

    if exclude_pending_sends:
        excludes.append(sorted(await pending_send_fan_ids(account_id)))

    resp: set[int] = set()
    if exclude_funnel_responders:
        resp = await funnel_responder_ids(account_id, int(exclude_funnel_responders))

    out = final_audience(included, excludes, responders=resp)
    return {
        "included_users": out.included,
        "excluded_users": out.excluded,
        "skipped_funnel_responders": out.skipped_responders,
        "funnel_responders_total": out.responders_total,
    }


@dataclass(frozen=True)
class Fail:
    reason: str


@dataclass(frozen=True)
class Audience:
    included: list
    skipped_responders: list[int]
    responders_total: int
    sources: tuple = ()

    @property
    def excluded(self) -> list:
        return list(dict.fromkeys(x for src in self.sources for x in src))


def final_audience(
    base: Iterable,
    excludes: Iterable[Iterable] = (),
    *,
    responders: Iterable[int] = (),
    truncated: Iterable[str] = (),
) -> Audience | Fail:
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


_LIST_PAGE = of_paging.LIST_PAGE
_ROSTER_PAGE = of_paging.ROSTER_PAGE
_page_all_checked = of_paging.page_all_checked
_page_all = of_paging.page_all
_ids_from_pages = of_paging.ids_from_pages


LIST_INCOMPLETE = f"{PLATFORM_LACKS_PREFIX}list_users_in:incomplete"


def lacks_reason(e: Exception) -> str | None:
    if isinstance(e, of_paging.ListGone):
        return f"{PLATFORM_LACKS_PREFIX}list_users_in:unknown_list"
    reason = getattr(e, "reason", None)
    return reason if isinstance(reason, str) and reason.startswith(PLATFORM_LACKS_PREFIX) else None


def _crawl_until_cut(crawls, one_page: bool) -> tuple[list[set[int]], list[str]]:
    got: list[set[int]] = []
    for label, crawl, why in crawls:
        try:
            ids, cut = crawl()
        except Exception as e:
            if reason := lacks_reason(e):
                raise AudienceRefusal(reason) from e
            if one_page:
                raise AudienceRefusal(why) from e
            raise
        if cut:
            if one_page:
                raise AudienceRefusal(why)
            return got, [label]
        got.append(ids)
    return got, []


def roster_audience_blocking(
    client,
    *,
    user_lists: Iterable | None = None,
    excluded_user_lists: Iterable | None = None,
    account_id: str,
) -> list[int] | None:
    list_page = platforms.for_account(account_id).list_page
    try:
        def roster(page):
            return lambda: of_paging.ids_from_pages(
                lambda off: page(type="active", limit=of_paging.ROSTER_PAGE, offset=off))

        def custom(lid):
            return lambda: of_paging.list_member_ids(client, lid, list_page=list_page)

        crawls = []
        for raw in (user_lists or []):
            name = str(raw).strip().lower()
            if name == "fans":
                crawls.append((repr(raw), roster(client.subscribers),
                               f"{PLATFORM_LACKS_PREFIX}subscribers:incomplete"))
            elif name == "following":
                crawls.append((repr(raw), roster(client.following), f"{PLATFORM_LACKS_PREFIX}following"))
            elif name.isdigit():
                crawls.append((repr(raw), custom(int(name)), LIST_INCOMPLETE))
            else:
                log.warning("roster_audience: unknown user_list %r", raw)
                return None
        n_inc = len(crawls)
        crawls += [(f"exclude list {lid!r}", custom(lid), LIST_INCOMPLETE)
                   for lid in (excluded_user_lists or [])]
        sets, cut = _crawl_until_cut(crawls, list_page is not None)

        ids = set().union(*sets[:n_inc])
        out = final_audience(sorted(ids), sets[n_inc:], truncated=cut)
        if isinstance(out, Fail):
            log.warning("roster_audience: crawl hit the paging backstop (%s)", out.reason)
            return None
        return out.included
    except AudienceRefusal as e:
        log.warning("roster_audience refused — %s", e.reason, exc_info=e.__cause__)
        raise
    except Exception:
        log.warning("roster_audience failed — audience unknown", exc_info=True)
        return None


import time  # noqa: E402

import auto_exclude_decide as aed  # noqa: E402


def _auto_exclude_list_id_blocking(client) -> int:
    list_id = of_paging.find_list_id(client, AUTO_EXCLUDE_LIST_NAME)
    if list_id is None:
        list_id = client.create_list(AUTO_EXCLUDE_LIST_NAME).get("id")
    return list_id


def _reconcile_exclude_list_blocking(client, list_id, members: set[int], ids: set[int]) -> None:
    stale = sorted(members - ids)
    _add_missing_blocking(client, list_id, members, ids)
    for uid in stale:
        try:
            client.remove_user_from_list(list_id, uid)
        except CellHeld:
            raise
        except Exception:  # noqa: BLE001 — a stale member we can't drop is harmless
            log.warning("auto_exclude remove failed account-list=%s uid=%s", list_id, uid)
            continue
        members.discard(uid)


def _add_missing_blocking(client, list_id, members: set[int], ids: set[int]) -> None:
    to_add = sorted(ids - members)
    add_fail = 0
    last_err: Exception | None = None
    for uid in to_add:
        try:
            client.add_user_to_list(list_id, uid)
        except Exception as e:  # noqa: BLE001 — per-user tolerance, see above
            if not of_paging.unlistable(e):
                raise
            add_fail += 1
            last_err = e
            continue
        members.add(uid)
    # Judge by coverage, not add success: an un-addable id returns in to_add every tick, so at steady state "every add failed" is routine, not systemic.
    if ids and not (ids & members):
        raise last_err or RuntimeError(
            "auto_exclude: no ids could be listed — exclude guard is empty")
    if add_fail:
        log.warning("auto_exclude partial account-list=%s added=%d skipped=%d (last=%r)",
                    list_id, len(to_add) - add_fail, add_fail, last_err)


_ae_mirrors: dict[str, aed.Mirror] = {}
_ae_refreshes: dict[str, asyncio.Task] = {}
AE_PAGE_TRIES = 3


def _ensure_exclude_blocking(account_id: str, client, ids: set[int]) -> tuple[int, bool]:
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
    members, truncated = of_paging.list_member_ids(
        client, list_id, list_page=platforms.for_account(account_id).list_page)
    if not truncated:
        _reconcile_exclude_list_blocking(client, list_id, members, ids)
        return list_id, False
    log.warning("auto_exclude: Auto_Exclude list=%s past the paging backstop (%d read in "
                "%.1fs) — incremental: adds only, stale members go in the background refresh",
                list_id, len(members), time.monotonic() - t0)
    m = _ae_mirrors[account_id] = aed.Mirror(list_id, members, frozenset(ids), time.time())
    _add_missing_blocking(client, list_id, m.members, ids)
    return list_id, True


class _ResumableLists:

    def __init__(self, client):
        self._c = client
        self.pages = 0

    def list_users_in(self, list_id, **kw):
        for i in range(AE_PAGE_TRIES):
            try:
                page = self._c.list_users_in(list_id, **kw)
            except Exception as e:  # noqa: BLE001 — retried, the last one raises
                if i == AE_PAGE_TRIES - 1 or of_pacing.retry_after(e) is not None:
                    raise
                time.sleep(1.0 + i)
                continue
            self.pages += 1
            return page

    def get_list(self, list_id):
        return self._c.get_list(list_id)


def _ae_apply_batch_blocking(client, m: aed.Mirror, kind: str, uids: list[int],
                             skip: set[int], stats: aed.RefreshStats) -> None:
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
            of_paging.list_member_ids, lists, m.list_id, max_pages=aed.REFRESH_MAX_PAGES,
            list_page=platforms.for_account(aid).list_page)
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
        await of_pacing.walk(account_id, "auto_exclude", lambda: _refresh_auto_exclude(account_id, client))
    except Exception:  # noqa: BLE001 — the next due send schedules another
        log.warning("auto_exclude refresh failed account=%s", account_id, exc_info=True)


def _schedule_auto_exclude_refresh(account_id: str, client):
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
    claim=None,
) -> int | None:
    idset = {int(x) for x in (ids or set())}
    if not idset:
        return None
    c = client
    if c is None:
        import automation_executor as ax
        c = await asyncio.to_thread(ax._make_client, account_id)
    aid = str(account_id)
    with claim.preparing() if claim is not None else contextlib.nullcontext():
        list_id, refresh = await asyncio.to_thread(_ensure_exclude_blocking, aid, c, idset)
    if refresh:
        _schedule_auto_exclude_refresh(aid, c)
    log.info("auto_exclude synced account=%s list=%s ids=%d",
             account_id, list_id, len(idset))
    return list_id
