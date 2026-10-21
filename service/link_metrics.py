"""service/link_metrics.py — Free trial links' and Profile promotions' per-link
figures (Infloww's Earnings, Fans who spent, Spend/Claim, AEPS; a promotion's
"Revenue from N fans"), the Details fan table's "Since claim / Lifetime" spend,
and the operator's Promo cost, Source and Tag on Free trial links and Tracking
links (Infloww's Edit dialog; stored here, never written to OnlyFans), and their List:
the OnlyFans fan list the link's claimers go into through OF's own add-to-list.

The same machinery as of_tracking_api's tracking-link earnings: OF's claimers
list per link x our `transactions` ledger, in TRACKED_STATUSES, by the same
kind buckets, one walk at a time per account (the same per-account lock, so the
tracking-link and trial/promo walks never hit OF at once). What differs:

  * The claimers are OF's /subscriptions/subscribers?filter[trial_id|promoId]
    (OFClient.offer_claims). Each fan carries subscribedOnData: subscribeAt
    (the fan's current subscription start, OF's only date per fan) and the
    lifetime *Summ in dollars (net: matched to our net_cents to the cent, see
    .scratch/tracking-links-earnings/live-verification.md). Promotion
    claimers carry the same subscribedOnData as trial ones (confirmed live
    2026-10-18, .scratch/growth-todo/capture.md). They are kept in
    `link_claimers`, so subscribeAt is the one first seen and is never moved
    later, and the walk survives a restart.
  * A walk re-runs only when OF's claim count for the link (the list call's
    claimCounts / claimsCount) differs from the count at the last walk.
  * Spend through the link = the fan's ledger rows at or after subscribeAt. A
    fan claimed by several trial links or promotions has each row attributed
    to the claim with the latest subscribeAt at or before it (Infloww: "each
    fan's spending is always attributed to the last free trial link, tracking
    link or promotion campaign"; tracking links keep their own time slices).
  * A fan OF sends without subscribedOnData has no subscribeAt: first-seen
    time is shown, and the fan's spend is "—" rather than a guess.
  * Lazy refresh: the list routes return what is cached with the time it was
    last checked; past _STALE_S they start a background refresh, which reuses
    the counts the list call already read from OF (no second list read).
  * Pre-warm: `prewarm_all` (server.py; each account about every
    PREWARM_EVERY_S) makes the pages' list reads for every account with a
    live session, one account at a time, the starts spread over half an
    hour, so a page opens on figures from the last hour. It re-reads a
    link's claimers only when its count moved (tracking links too) and
    honours the OF failure back-off; its worst-case OF call budget is on
    `prewarm`.
  * Lifetime sums (Details only) are re-read with the walk. A link whose
    count did not move is re-walked in the background when its Details are
    opened past _STALE_S after the last walk; the list figures come from the
    ledger and never need it.
  * List: OF's "Add to list" adds every current claimer in one call and adds
    nobody twice (live 2026-10-18 on a tracking link, 2026-10-19 on a trial
    link and a promotion: {"count": n}, then {"count": 0}). It runs
    once when a List is first saved, then again only when the link's claim
    count grows past the count at the last add (`refresh()` for trial links,
    of_tracking_api's earnings read for tracking links), under the account's
    lock, paced; an OF error backs the account's adds off. Those reads run
    when a page is open and on the hourly pre-warm, so later claimers wait
    for the next one. Changing the List moves future adds only; clearing it stops them.
    A pass reads its rows once and re-reads each link's List before its add:
    one changed or cleared meanwhile is skipped (an add already sent to OF
    still lands in the old list), and the save's own add covers a new one.
  * Profile promotions' List is one account-level setting (Infloww's "Add
    fans to list" switch and list, promo_list_settings), not per promotion.
    While it is on, each promotions pass first points every promotion with
    claims at the setting's list (a promotion newly pointed there counts as
    not added yet), then applies the same count rule; off, nothing is added.
    Turning it on or changing it queues one pass at once, on the counts last
    read (a low one costs one more idempotent add later).
  * A re-armed promotion (automations/promo_reactivate re-points of_promo_id)
    keeps its earlier OF promos in link_meta under our campaign id, so the
    campaign's figures add up across re-arms.

The walk: pages of 20, the most OF reads per call on /subscriptions/subscribers
(live 2026-10-18 on 96 fans: limit 10, 15 and 20 return every fan in the same
order; limit 21 lost 4 and limit 50 lost 52, silently, gaps but no dups).
Neither a short page nor hasMore ends it: OF answered offset 0 with 9 fans and
offset 10 with 10 more, both hasMore:true, pages run short mid-list, and
hasMore can be true on an empty page. So the offset moves by the page size, and
the walk ends on an empty page, an explicit hasMore:false, or a short page once
the offset is past the link's claim count. A link whose claim count OF reports
but whose list is empty (an old promotion: 2 claims, 0 rows at every limit)
ends on the first, empty, page and is stored with no fans; it is re-walked only
when the count moves, like any other.

Routes (owner-gated, under /admin/*):
  GET /admin/link-metrics/fans?account_id=&kind=trial|promo&of_id=[&campaign_id=][&count=]
      the Details rows: since-claim spend by kind (gross and net) and OF's
      lifetime sums; walks a never-walked link on demand.
  PUT /admin/link-meta   {account_id, kind: trial|campaign, of_id, promo_cost,
      source, tags, list_id, list_name}   the Edit dialog's save.
  PUT /admin/link-meta/batch   {account_id, kind, of_ids, [promo_cost], [source], [tags]}
      batch edit: the fields sent are set on every link, the rest left alone.
  GET /admin/promo-list?account_id=   Profile promotion's "Add fans to list":
      {enabled, list_id, list_name}
  PUT /admin/promo-list   {account_id, enabled, list_id, list_name}
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from datetime import datetime
from typing import Any, Iterable

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

import accounts as account_registry
import automation_executor as ax
from account_health import dead_session_map, is_deactivated
from attribution_backfill import TRACKED_STATUSES
from auth import assert_account_owned
from db.engine import get_session
from db.models import LinkClaimer, LinkMeta, PromoCampaign, PromoListSetting, Transaction
import of_tracking_api
from of_promos import fetch_of_promos, fetch_of_trials, safe_int, to_cents
from of_tracking_api import _BUCKET, _LOCKS, _MetaFields, _blank, _parse_of_time

log = logging.getLogger("of-relay.link_metrics")

router = APIRouter()

WALKED = ("trial", "promo")       # kinds whose claimers we walk
EDITABLE = ("trial", "campaign")  # kinds with Infloww's Edit dialog (promo cost, source, tag)

_STALE_S = 3600.0                 # cached figures up to an hour old are fine
_FAIL_BACKOFF_S = 300.0           # after an OF failure, no new refresh for this long
_PAGE = 20                        # the most OF reads per call here; above 20 it skips fans (module note)
_PAGE_SLEEP_S = 0.4               # between pages, as transaction_ingest paces OF
_MAX_EXTRA_PAGES = 5              # past the claim count before giving up on an offset OF ignores
_UNKNOWN_MAX_PAGES = 200          # an on-demand walk with no count to go by

_LIFETIME = ("total", "subs", "posts", "messages", "streams", "tips")
_SUMM = {"total": "totalSumm", "subs": "subscribesSumm", "posts": "postsSumm",
         "messages": "messagesSumm", "streams": "streamsSumm", "tips": "tipsSumm"}

_REFRESHING: set[tuple[str, str]] = set()
_FAILED_AT: dict[tuple[str, str], float] = {}
_TASKS: set[asyncio.Task] = set()   # strong refs, so a running refresh is not collected
_REWALKING: set[tuple[str, str, int]] = set()   # Details' stale re-walks queued or running
_LIST_QUEUED: set[tuple[str, str, int]] = set()  # a save's first add-to-list, queued or running
_LIST_FAILED_AT: dict[str, float] = {}           # account -> the last failed add-to-list (back-off)


def _now() -> datetime:
    return datetime.utcnow()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _lock(account_id: str) -> asyncio.Lock:
    return _LOCKS.setdefault(account_id, asyncio.Lock())


# ── The walk ──────────────────────────────────────────────────────────

def _parse_claimer(u: dict) -> dict | None:
    fid = safe_int(u.get("id"))
    if not fid:
        return None
    d = u.get("subscribedOnData")
    d = d if isinstance(d, dict) else None
    return {
        "fan_id": fid,
        "name": u.get("name") or u.get("displayName") or "",
        "username": u.get("username") or "",
        "subscribe_at": _parse_of_time(d.get("subscribeAt")) if d else None,
        "lifetime": {k: to_cents(d.get(s)) for k, s in _SUMM.items()} if d else None,
    }


def walk(client, kind: str, of_id: int, expected: int | None) -> list[dict]:
    """Every fan OF lists under the trial link / promotion. `expected` is OF's
    claim count from the list call (None: not known). Raises on an OF error or
    an unusable payload (the caller keeps the cache it had)."""
    fans: list[dict] = []
    seen: set[int] = set()
    offset = 0
    max_pages = (-(-expected // _PAGE) + _MAX_EXTRA_PAGES) if expected else _UNKNOWN_MAX_PAGES
    for page in range(max_pages):
        if page:
            time.sleep(_PAGE_SLEEP_S)
        raw = client.offer_claims(of_id, kind, limit=_PAGE, offset=offset)
        rows = raw.get("list") if isinstance(raw, dict) else None
        if not isinstance(rows, list):
            raise ValueError(f"{kind} claimers {of_id}: unexpected payload")
        for u in rows:
            f = _parse_claimer(u) if isinstance(u, dict) else None
            if f and f["fan_id"] not in seen:
                seen.add(f["fan_id"])
                fans.append(f)
        offset += _PAGE
        if not rows or raw.get("hasMore") is False:
            break
        if len(rows) < _PAGE and expected is not None and offset >= expected:
            break
    return fans


async def _store_walk(account_id: str, kind: str, of_id: int, fans: list[dict],
                      count: int | None, campaign_id: int | None) -> None:
    """Upsert the walked fans and the link's walk state. subscribe_at is kept
    from first sight: an existing value is never moved later."""
    now = _now()
    async with get_session() as s:
        have = {c.fan_id: c for c in (await s.execute(
            select(LinkClaimer).where(LinkClaimer.account_id == account_id,
                                      LinkClaimer.kind == kind, LinkClaimer.of_id == of_id)
        )).scalars().all()}
        for f in fans:
            row = have.get(f["fan_id"])
            if row is None:
                row = LinkClaimer(account_id=account_id, kind=kind, of_id=of_id, fan_id=f["fan_id"],
                                  first_seen_at=now, subscribe_at=f["subscribe_at"])
                s.add(row)
            elif f["subscribe_at"] and (row.subscribe_at is None or f["subscribe_at"] < row.subscribe_at):
                row.subscribe_at = f["subscribe_at"]
            row.name = f["name"] or row.name
            row.username = f["username"] or row.username
            if f["lifetime"] is not None:
                for k in _LIFETIME:
                    setattr(row, f"lifetime_{k}_cents", f["lifetime"][k])
        meta = await _meta_row(s, account_id, kind, of_id)
        meta.claim_count = count if count is not None else len(fans)
        meta.walked_at = now
        meta.checked_at = now
        if campaign_id is not None:
            meta.campaign_id = campaign_id


async def _meta_row(s, account_id: str, kind: str, of_id: int) -> LinkMeta:
    row = (await s.execute(select(LinkMeta).where(
        LinkMeta.account_id == account_id, LinkMeta.kind == kind, LinkMeta.of_id == of_id))).scalar_one_or_none()
    if row is None:
        row = LinkMeta(account_id=account_id, kind=kind, of_id=of_id)
        s.add(row)
    return row


# ── Refresh ───────────────────────────────────────────────────────────

Link = tuple[int, int, "int | None"]   # (of_id, OF's claim count, our promo campaign id)


async def refresh(account_id: str, kind: str, links: list[Link]) -> dict[str, int]:
    """Re-walk the links whose OF claim count moved since their last walk, one
    at a time under the account's lock; mark the rest checked. An OF failure
    stops the pass (most likely a 429) and backs off; what was walked stays."""
    walked = checked = 0
    async with _lock(account_id):
        async with get_session() as s:
            metas = {m.of_id: m for m in (await s.execute(select(LinkMeta).where(
                LinkMeta.account_id == account_id, LinkMeta.kind == kind))).scalars().all()}
        client = None
        same: list[int] = []
        try:
            for of_id, count, campaign_id in links:
                m = metas.get(of_id)
                if count <= 0 or (m is not None and m.walked_at is not None and m.claim_count == count):
                    same.append(of_id)
                    continue
                if client is None:
                    client = await asyncio.to_thread(ax._make_client, account_id)
                fans = await asyncio.to_thread(walk, client, kind, of_id, count)
                await _store_walk(account_id, kind, of_id, fans, count, campaign_id)
                walked += 1
            await sync_lists(account_id, kind, client, {of_id: count for of_id, count, _c in links})
        except Exception:
            _FAILED_AT[(account_id, kind)] = time.monotonic()
            log.info("link_metrics refresh failed account=%s kind=%s", account_id, kind, exc_info=True)
        finally:
            if same:
                now = _now()
                camp = {of_id: c for of_id, _n, c in links}
                async with get_session() as s:
                    for of_id in same:
                        m = await _meta_row(s, account_id, kind, of_id)
                        m.checked_at = now
                        if camp.get(of_id) is not None:
                            m.campaign_id = camp[of_id]
                        checked += 1
    return {"walked": walked, "checked": checked}


async def _refresh_task(account_id: str, kind: str, links: list[Link]) -> None:
    try:
        await refresh(account_id, kind, links)
    finally:
        _REFRESHING.discard((account_id, kind))


def _spawn(coro) -> None:
    t = asyncio.get_running_loop().create_task(coro)
    _TASKS.add(t)
    t.add_done_callback(_TASKS.discard)


def _backed_off(account_id: str, kind: str) -> bool:
    failed = _FAILED_AT.get((account_id, kind))
    return failed is not None and time.monotonic() - failed < _FAIL_BACKOFF_S


def maybe_refresh(account_id: str, kind: str, links: list[Link], updated_at: datetime | None) -> bool:
    """Start a background refresh when the cache is over an hour old (or was
    never read), none is running for the account and kind, and OF did not just
    fail. True when one is running after the call."""
    key = (account_id, kind)
    if key in _REFRESHING:
        return True
    if updated_at is not None and (_now() - updated_at).total_seconds() < _STALE_S:
        return False
    if _backed_off(account_id, kind):
        return False
    if not links:
        return False
    _REFRESHING.add(key)
    _spawn(_refresh_task(account_id, kind, links))
    return True


# ── Pre-warm ──────────────────────────────────────────────────────────

PREWARM_EVERY_S = _STALE_S          # each account's cycle: a page opens on figures under an hour old
_PREWARM_SPREAD_S = PREWARM_EVERY_S / 2   # the accounts' passes start spread over this, jittered
# server.py's loop sleeps this after a pass, which itself spends about
# _PREWARM_SPREAD_S staggering, so each account comes round about every PREWARM_EVERY_S.
PREWARM_PAUSE_S = PREWARM_EVERY_S - _PREWARM_SPREAD_S


def links_of_trials(fetched: list[dict]) -> list[Link]:
    """OF's /trials rows (of_promos.fetch_of_trials) as a refresh walks them."""
    return [(t["of_trial_id"], safe_int(t.get("claim_counts")), None) for t in fetched if t.get("of_trial_id")]


def links_of_promos(fetched: list[dict], mirrors: Iterable[PromoCampaign],
                    past: dict[int, list[int]]) -> list[Link]:
    """OF's /promotions rows as a refresh walks them, each with our campaign id:
    the campaign's current OF promo and its earlier re-arms (past_promo_ids)."""
    campaign_of = {o: m.id for m in mirrors for o in [m.of_promo_id, *past.get(m.id, [])] if o}
    return [(p["of_promo_id"], safe_int(p.get("subscriber_count")), campaign_of.get(p["of_promo_id"]))
            for p in fetched if p.get("of_promo_id")]


async def prewarm(account_id: str) -> None:
    """Read one account's link figures ahead of any page, by the page's rules:
    the same per-account lock, pacing and OF failure back-off, and a link's
    claimers are re-read only when OF's count for it moved.

    OF calls per account per pass, worst case (the list reads always run):
      tracking  ceil(links / 100) /campaigns pages, plus every claimer page
                (50 a page) of each link whose countSubscribers moved
      trial     ceil(links / 100) /trials pages (at most 10), plus every
                claimer page (20 a page, up to 5 past the count) of each moved link
      promo     ceil(promos / 100) /promotions pages (at most 12), the same
      lists     one add-to-list per link with a List whose count grew
    An hour in which no count moved costs the three list reads (one page each
    up to 100 links). A kind backed off by a recent OF failure is skipped; a
    list OF does not answer, or a failed trial walk, ends the pass, and a
    tracking link OF failed on is not retried for _CLAIMERS_FAIL_TTL."""
    if not await of_tracking_api.prewarm(account_id):
        return
    if not _backed_off(account_id, "trial"):
        trials = await fetch_of_trials(account_id)
        if trials is None:
            return
        await refresh(account_id, "trial", links_of_trials(trials))
        if _backed_off(account_id, "trial"):
            return
    if not _backed_off(account_id, "promo"):
        promos = await fetch_of_promos(account_id)
        if promos is None:
            return
        async with get_session() as s:
            mirrors = (await s.execute(select(PromoCampaign).where(
                PromoCampaign.account_id == account_id))).scalars().all()
        await refresh(account_id, "promo", links_of_promos(promos, mirrors, await past_promo_ids(account_id)))


async def prewarm_all() -> None:
    """Every OnlyFans account with a session, one at a time, their starts spread
    over _PREWARM_SPREAD_S with jitter (no burst of every account at once, and
    no shared minute OF could line the accounts up by). An account whose
    session is marked dead is skipped: its OF reads could only fail. So is a
    deactivated Creator: it gets no OF call."""
    live = [m["id"] for m in account_registry.list_accounts()
            if m.get("has_session") and m.get("platform") == "onlyfans"]
    gap = _PREWARM_SPREAD_S / max(len(live), 1)
    for i, aid in enumerate(live):
        if i:
            await asyncio.sleep(gap * random.uniform(0.5, 1.5))
        if aid in await dead_session_map() or await is_deactivated(aid):
            continue
        try:
            await prewarm(aid)
        except Exception:
            log.info("link_metrics prewarm failed account=%s", aid, exc_info=True)


# ── Figures: claimers x ledger ────────────────────────────────────────

class _Book:
    """The account's walked claimers and their attributed ledger spend."""

    def __init__(self, claimers, spend, ledger_since):
        self.claimers: dict[tuple[str, int], list[LinkClaimer]] = claimers
        self.spend: dict[tuple[str, int, int], dict] = spend
        self.ledger_since: datetime | None = ledger_since


async def _book(account_id: str) -> _Book:
    """Every trial / promo claimer of the account, and each ledger row of
    theirs attributed to the claim with the latest subscribe_at at or before it
    (ties to the later-seen claim). TRACKED_STATUSES only: refunds, chargebacks
    and failed rows are not revenue."""
    async with get_session() as s:
        rows = (await s.execute(select(LinkClaimer).where(
            LinkClaimer.account_id == account_id, LinkClaimer.kind.in_(WALKED)))).scalars().all()
        since = (await s.execute(select(func.min(Transaction.occurred_at))
                                 .where(Transaction.account_id == account_id))).scalar()
        claimers: dict[tuple[str, int], list[LinkClaimer]] = {}
        claims: dict[int, list[tuple[datetime, datetime, str, int]]] = {}
        for c in rows:
            claimers.setdefault((c.kind, c.of_id), []).append(c)
            if c.subscribe_at is not None:
                claims.setdefault(c.fan_id, []).append((c.subscribe_at, c.first_seen_at, c.kind, c.of_id))
        spend: dict[tuple[str, int, int], dict] = {}
        if not claims:
            return _Book(claimers, spend, since)
        for lst in claims.values():
            lst.sort(reverse=True)
        floor = min(st for lst in claims.values() for st, *_ in lst)
        tx = (await s.execute(
            select(Transaction.fan_id, Transaction.kind, Transaction.occurred_at,
                   Transaction.amount_cents, Transaction.net_cents)
            .where(Transaction.account_id == account_id,
                   Transaction.status.in_(TRACKED_STATUSES),
                   Transaction.fan_id.is_not(None),
                   Transaction.occurred_at >= floor)
        )).all()
    for fid, tkind, at, gross, net in tx:
        lst = claims.get(int(fid))
        hit = next(((k, o) for st, _seen, k, o in lst if st <= at), None) if lst else None
        if hit is None:
            continue
        row = spend.setdefault((hit[0], hit[1], int(fid)), _blank())
        b = _BUCKET.get(tkind, "other")
        row[f"{b}_cents"] += int(gross or 0)
        row["total_cents"] += int(gross or 0)
        if net is None:
            row["net_missing_count"] += 1
        else:
            row[f"{b}_net_cents"] += int(net)
            row["total_net_cents"] += int(net)
    return _Book(claimers, spend, since)


def _group_fans(book: _Book, kind: str, of_ids: Iterable[int]) -> dict[int, dict]:
    """fan_id -> {claimer: the earliest claim's row, spend: summed buckets or
    None when no claim of the fan's carries subscribe_at} over the group's links."""
    out: dict[int, dict] = {}
    for of_id in of_ids:
        for c in book.claimers.get((kind, of_id), []):
            f = out.setdefault(c.fan_id, {"claimer": c, "spend": None})
            if (c.subscribe_at or c.first_seen_at) < (f["claimer"].subscribe_at or f["claimer"].first_seen_at):
                f["claimer"] = c
            if c.subscribe_at is None:
                continue
            got = book.spend.get((kind, of_id, c.fan_id)) or _blank()
            if f["spend"] is None:
                f["spend"] = _blank()
            for k, v in got.items():
                f["spend"][k] += v
    return out


_UNWALKED = {"earnings_cents": None, "earnings_net_cents": None, "fans_who_spent": None,
             "fans_counted": None, "claimers": None, "spend_unknown": 0, "net_missing_count": 0}


def _figures(book: _Book, kind: str, of_ids: list[int]) -> dict[str, Any]:
    """One row's figures over its walked claimers. Earnings None when no
    claimer has a subscribe_at (OF sent no subscribedOnData). fans_counted is
    the Spend/Claim and AEPS denominator: the claimers whose spend is known."""
    fans = _group_fans(book, kind, of_ids)
    known = [f["spend"] for f in fans.values() if f["spend"] is not None]
    if fans and not known:
        return {**_UNWALKED, "claimers": len(fans), "spend_unknown": len(fans)}
    return {
        "earnings_cents": sum(r["total_cents"] for r in known),
        "earnings_net_cents": sum(r["total_net_cents"] for r in known),
        # Spend/Claim's "purchased subscriptions, spent on content, or gave tips": any spend.
        "fans_who_spent": sum(1 for r in known if r["total_cents"] > 0),
        "fans_counted": len(known),
        "claimers": len(fans),
        "spend_unknown": len(fans) - len(known),
        "net_missing_count": sum(r["net_missing_count"] for r in known),
    }


async def _walked_ids(account_id: str, kind: str) -> set[int]:
    async with get_session() as s:
        return set((await s.execute(select(LinkMeta.of_id).where(
            LinkMeta.account_id == account_id, LinkMeta.kind == kind,
            LinkMeta.walked_at.is_not(None)))).scalars().all())


async def past_promo_ids(account_id: str) -> dict[int, list[int]]:
    """Our campaign id -> the OF promo ids recorded under it in link_meta: its
    earlier re-arms, and the current one once a refresh has seen it."""
    async with get_session() as s:
        rows = (await s.execute(select(LinkMeta.campaign_id, LinkMeta.of_id).where(
            LinkMeta.account_id == account_id, LinkMeta.kind == "promo",
            LinkMeta.campaign_id.is_not(None)))).all()
    out: dict[int, list[int]] = {}
    for cid, oid in rows:
        out.setdefault(int(cid), []).append(int(oid))
    return out


async def for_list(account_id: str, kind: str, groups: dict[Any, list[int]],
                   links: list[Link] | None) -> dict[str, Any]:
    """The list route's figures: {by: {group key: figures}, updated_at, refreshing}.

    groups: row key -> the row's OF ids (a promotion campaign's every re-arm).
    links:  what a refresh walks, with OF's counts from the list call; None
            when OF was not reachable (no refresh is started on stale counts).
    updated_at is when every one of `links` was last checked (None: some never
    was); past an hour a background refresh starts."""
    walked = await _walked_ids(account_id, kind)
    book = await _book(account_id)
    # A row none of whose links was walked yet is "—", not 0.
    by = {key: _figures(book, kind, of_ids) if any(o in walked for o in of_ids) else dict(_UNWALKED)
          for key, of_ids in groups.items()}
    updated_at = None
    refreshing = (account_id, kind) in _REFRESHING
    if links is not None:
        ids = [o for o, _n, _c in links]
        async with get_session() as s:
            checked = dict((await s.execute(select(LinkMeta.of_id, LinkMeta.checked_at).where(
                LinkMeta.account_id == account_id, LinkMeta.kind == kind))).all())
        times = [checked.get(o) for o in ids]
        updated_at = None if (not times or any(t is None for t in times)) else min(times)
        refreshing = maybe_refresh(account_id, kind, links, updated_at)
    return {"by": by, "updated_at": _iso(updated_at), "refreshing": refreshing}


# ── Details: the link's fans ─────────────────────────────────────────

def _lifetime(c: LinkClaimer) -> dict[str, int] | None:
    if c.lifetime_total_cents is None:
        return None
    return {f"{k}_cents": int(getattr(c, f"lifetime_{k}_cents") or 0) for k in _LIFETIME}


@router.get("/admin/link-metrics/fans")
async def link_fans(account_id: str = Query(...), kind: str = Query(..., pattern="^(trial|promo)$"),
                    of_id: int = Query(..., ge=1), campaign_id: int | None = Query(None, ge=1),
                    count: int | None = Query(None, ge=0)) -> dict[str, Any]:
    """Details: every fan OF lists under the trial link (or the promotion
    campaign, every re-arm), with spend since the claim (our ledger, by kind,
    gross and net; null without subscribeAt) and OF's lifetime sums (net;
    null without subscribedOnData). A link never walked, or whose claim count
    (`count`, from the list row) moved, is walked now, unless a refresh holds
    the account's lock (then the cache, with `refreshing`)."""
    assert_account_owned(account_id)
    refreshing = False
    async with get_session() as s:
        meta = (await s.execute(select(LinkMeta).where(
            LinkMeta.account_id == account_id, LinkMeta.kind == kind, LinkMeta.of_id == of_id))).scalar_one_or_none()
    walked = meta is not None and meta.walked_at is not None
    moved = count is not None and walked and meta.claim_count != count
    if count != 0 and (not walked or moved):
        if _lock(account_id).locked():
            refreshing = True        # a refresh is walking OF for this account; show what is cached
        else:
            try:
                await _walk_one(account_id, kind, of_id, count, campaign_id)
                walked = True
            except Exception:
                log.info("link_metrics on-demand walk failed account=%s %s=%s", account_id, kind, of_id,
                         exc_info=True)
                if not walked:
                    raise HTTPException(502, "Unable to load page. Try again later")
    elif count != 0 and walked and (_now() - meta.walked_at).total_seconds() >= _STALE_S:
        # Same count, but Lifetime is OF's running sums: re-read them in the background; the page polls.
        refreshing = _rewalk_later(account_id, kind, of_id, meta.claim_count if count is None else count, campaign_id)
    of_ids = [of_id]
    if kind == "promo" and campaign_id is not None:
        of_ids += [o for o in (await past_promo_ids(account_id)).get(campaign_id, []) if o != of_id]
    book = await _book(account_id)
    fans = []
    for fid, f in _group_fans(book, kind, of_ids).items():
        c = f["claimer"]
        fans.append({"fan_id": fid, "name": c.name or "", "username": c.username or "",
                     "subscribe_at": _iso(c.subscribe_at), "first_seen_at": _iso(c.first_seen_at),
                     "since": f["spend"], "lifetime": _lifetime(c)})
    fans.sort(key=lambda r: (-((r["since"] or {}).get("total_net_cents") or 0),
                             -((r["lifetime"] or {}).get("total_cents") or 0), r["fan_id"]))
    async with get_session() as s:
        walked_at = (await s.execute(select(func.max(LinkMeta.walked_at)).where(
            LinkMeta.account_id == account_id, LinkMeta.kind == kind,
            LinkMeta.of_id.in_(of_ids)))).scalar()
    return {"fans": fans, "ledger_since": _iso(book.ledger_since), "walked_at": _iso(walked_at),
            "refreshing": refreshing}


async def _walk_one(account_id: str, kind: str, of_id: int, count: int | None,
                    campaign_id: int | None) -> None:
    async with _lock(account_id):
        client = await asyncio.to_thread(ax._make_client, account_id)
        fans = await asyncio.to_thread(walk, client, kind, of_id, count)
        await _store_walk(account_id, kind, of_id, fans, count, campaign_id)


def _rewalk_later(account_id: str, kind: str, of_id: int, count: int | None, campaign_id: int | None) -> bool:
    """Queue one background re-walk of the link (Details' stale Lifetime). Not
    while the account's lock is held (a walk is on OF already) or inside an OF
    failure's back-off; once per link at a time. True while one is queued."""
    key = (account_id, kind, of_id)
    if key in _REWALKING:
        return True
    if _lock(account_id).locked():
        return False
    if _backed_off(account_id, kind):
        return False
    _REWALKING.add(key)
    _spawn(_rewalk_task(account_id, kind, of_id, count, campaign_id))
    return True


async def _rewalk_task(account_id: str, kind: str, of_id: int, count: int | None, campaign_id: int | None) -> None:
    try:
        await _walk_one(account_id, kind, of_id, count, campaign_id)
    except Exception:
        _FAILED_AT[(account_id, kind)] = time.monotonic()
        log.info("link_metrics stale re-walk failed account=%s %s=%s", account_id, kind, of_id, exc_info=True)
    finally:
        _REWALKING.discard((account_id, kind, of_id))


# ── List: OF's add-to-list on a link's claimers ──────────────────────

def _list_backoff(account_id: str) -> bool:
    failed = _LIST_FAILED_AT.get(account_id)
    return failed is not None and time.monotonic() - failed < _FAIL_BACKOFF_S


async def _add_one(account_id: str, client, kind: str, of_id: int, list_id: str, count: int) -> None:
    """One OF add-to-list for the link; on success the count it covered is
    recorded (if the link still feeds that list). An OF error backs the
    account's adds off and re-raises."""
    try:
        r = await asyncio.to_thread(client.add_link_claimers_to_list, list_id, kind, of_id)
    except Exception:
        _LIST_FAILED_AT[account_id] = time.monotonic()
        raise
    async with get_session() as s:
        m = await _meta_row(s, account_id, kind, of_id)
        if m.list_id == list_id:
            m.list_added_count = count
    log.info("link list add account=%s %s=%s list=%s count=%s added=%s", account_id, kind, of_id, list_id, count,
             r.get("count") if isinstance(r, dict) else None)


async def _point_promos_at_setting(account_id: str, counts: dict[int, int]) -> bool:
    """Profile promotions' account-level List: False when it is off. On, every
    promotion with claims in `counts` feeds the setting's list; one that fed
    another list (or none) is marked not added yet, so its claimers go in once."""
    async with get_session() as s:
        st = await s.get(PromoListSetting, account_id)
        if st is None or not st.enabled or not st.list_id:
            return False
        for of_id, n in counts.items():
            if not n or n <= 0:
                continue
            m = await _meta_row(s, account_id, "promo", of_id)
            if m.list_id != st.list_id:
                m.list_id = st.list_id
                m.list_added_count = None
            m.list_name = st.list_name
    return True


async def _current_list(account_id: str, kind: str, of_id: int) -> str | None:
    """The link's List as stored now."""
    async with get_session() as s:
        return (await s.execute(select(LinkMeta.list_id).where(
            LinkMeta.account_id == account_id, LinkMeta.kind == kind, LinkMeta.of_id == of_id))).scalar_one_or_none()


async def _promo_list_is(account_id: str, list_id: str) -> bool:
    """The account's promotion List is on and is still `list_id`."""
    async with get_session() as s:
        st = await s.get(PromoListSetting, account_id)
        return st is not None and bool(st.enabled) and st.list_id == list_id


async def sync_lists(account_id: str, kind: str, client, counts: dict[int, int]) -> int:
    """With the account's lock held: OF's add-to-list for each of the kind's
    links with a List whose claim count (`counts`, from OF's list read) grew
    past the last add. Paced; the first OF error stops the pass (raised).
    `client` None: one is made only if an add is due. Promotions follow the
    account's one setting (off: nothing)."""
    if _list_backoff(account_id):
        return 0
    if kind == "promo" and not await _point_promos_at_setting(account_id, counts):
        return 0
    async with get_session() as s:
        rows = (await s.execute(select(LinkMeta).where(
            LinkMeta.account_id == account_id, LinkMeta.kind == kind, LinkMeta.list_id.is_not(None)))).scalars().all()
    added = 0
    for m in rows:
        n = counts.get(m.of_id)
        if not n or n <= 0 or (m.list_added_count is not None and n <= m.list_added_count):
            continue
        # The rows were read once: a save since (List changed or cleared; for promotions, the setting off or on
        # another list) skips this one, so later adds in the pass skip the old list. An add already sent to
        # OnlyFans still lands there. The save's own add, queued behind this lock, covers a new list.
        if await _current_list(account_id, kind, m.of_id) != m.list_id or (
                kind == "promo" and not await _promo_list_is(account_id, m.list_id)):
            continue
        if client is None:
            client = await asyncio.to_thread(ax._make_client, account_id)
        if added:
            await asyncio.sleep(_PAGE_SLEEP_S)
        await _add_one(account_id, client, kind, m.of_id, m.list_id, n)
        added += 1
    return added


def _known_count(account_id: str, kind: str, m: LinkMeta) -> int:
    """The link's claim count as last read from OF (0 if never): what a save's
    first add covers. A low guess costs one more idempotent add later."""
    if kind == "campaign":
        from of_tracking_api import _CLAIMERS_CACHE
        hit = _CLAIMERS_CACHE.get((account_id, m.of_id))
        return hit[0] if hit else 0
    return m.claim_count or 0


async def _list_add_task(account_id: str, kind: str, of_id: int) -> None:
    """A save's first add-to-list, in the background under the account's lock
    (a walk may hold it). Skipped if the List was cleared or added meanwhile;
    a failure leaves it due, so the next refresh / earnings read retries after
    the back-off. The queue mark covers only the wait for the lock: a save
    after that queues its own add, whose mark this task leaves alone."""
    released = False
    try:
        async with _lock(account_id):
            _LIST_QUEUED.discard((account_id, kind, of_id))
            released = True
            async with get_session() as s:
                m = (await s.execute(select(LinkMeta).where(
                    LinkMeta.account_id == account_id, LinkMeta.kind == kind,
                    LinkMeta.of_id == of_id))).scalar_one_or_none()
            if m is None or not m.list_id or m.list_added_count is not None or _list_backoff(account_id):
                return
            client = await asyncio.to_thread(ax._make_client, account_id)
            await _add_one(account_id, client, kind, of_id, m.list_id, _known_count(account_id, kind, m))
    except Exception:
        log.info("link list first add failed account=%s %s=%s", account_id, kind, of_id, exc_info=True)
    finally:
        if not released:
            _LIST_QUEUED.discard((account_id, kind, of_id))


# ── Promo cost, Source, Tag (the Edit dialog) ────────────────────────

_TAG_MAX = 100       # Infloww's "Tag name" input


def _tags(row: LinkMeta | None) -> list[str]:
    try:
        v = json.loads(row.tags_json) if row is not None and row.tags_json else []
    except ValueError:
        return []
    return [t for t in v if isinstance(t, str)] if isinstance(v, list) else []


def meta_fields(row: LinkMeta | None) -> dict[str, Any]:
    return {"promo_cost_cents": row.promo_cost_cents if row is not None else None,
            "link_source": row.source if row is not None else None,
            "tags": _tags(row),
            "list_id": row.list_id if row is not None else None,
            "list_name": row.list_name if row is not None else None}


async def meta_for(account_id: str, kind: str) -> tuple[dict[int, dict], list[str], list[str]]:
    """(of_id -> {promo_cost_cents, link_source, tags, list_id, list_name}) for the kind, and the
    account's Sources and Tags in use on any link (the dialog's suggestions and
    the list's filter options; Infloww shares them between its link kinds)."""
    async with get_session() as s:
        rows = (await s.execute(select(LinkMeta).where(
            LinkMeta.account_id == account_id, LinkMeta.kind.in_(EDITABLE)))).scalars().all()
    by = {r.of_id: meta_fields(r) for r in rows if r.kind == kind}
    # One spelling per value, case-insensitively (the save dedupes the same way).
    sources = sorted({r.source.lower(): r.source for r in rows if r.source}.values(), key=str.lower)
    tags = sorted({t.lower(): t for r in rows for t in _tags(r)}.values(), key=str.lower)
    return by, sources, tags


class _MetaBody(_MetaFields):
    account_id: str
    kind: str
    of_id: int = Field(..., ge=1)


def clean_meta(body: _MetaFields) -> dict[str, Any]:
    """The fields as stored: cost in cents (None unset), a trimmed Source,
    tags trimmed and deduped case-insensitively, the List (its name only with
    an id). 422 on a tag over Infloww's 100 characters."""
    tags: list[str] = []
    for t in body.tags:
        t = (t or "").strip()
        if len(t) > _TAG_MAX:
            raise HTTPException(422, f"a tag is at most {_TAG_MAX} characters")
        if t and t.lower() not in {x.lower() for x in tags}:
            tags.append(t)
    list_id = body.list_id or None
    return {"promo_cost_cents": None if body.promo_cost is None else int(round(body.promo_cost * 100)),
            "source": (body.source or "").strip() or None,
            "tags": tags,
            "list_id": list_id,
            "list_name": ((body.list_name or "").strip() or None) if list_id else None}


async def store_meta(account_id: str, kind: str, of_id: int, meta: dict[str, Any],
                     claim_count: int | None = None) -> dict[str, Any]:
    """Write clean_meta()'s fields to the link's row (the Edit dialog's save and
    the Create dialog's). A List set or changed is not added to yet; with
    `claim_count` (a new link: 0) that count counts as added. Then, if the
    List is due its first add, one is queued in the background."""
    async with get_session() as s:
        row = await _meta_row(s, account_id, kind, of_id)
        row.promo_cost_cents = meta["promo_cost_cents"]
        row.source = meta["source"]
        row.tags_json = json.dumps(meta["tags"]) if meta["tags"] else None
        if meta["list_id"] != row.list_id:
            row.list_id = meta["list_id"]
            row.list_added_count = claim_count if meta["list_id"] else None
        row.list_name = meta["list_name"]
        row.updated_at = _now()
        out = meta_fields(row)
        due = bool(row.list_id) and row.list_added_count is None
    key = (account_id, kind, of_id)
    if due and key not in _LIST_QUEUED:
        _LIST_QUEUED.add(key)
        _spawn(_list_add_task(account_id, kind, of_id))
    return out


@router.put("/admin/link-meta")
async def save_link_meta(body: _MetaBody = Body(...)) -> dict[str, Any]:
    """Infloww's Edit dialog on a free trial link or tracking link: Promo cost,
    Source and Tag, kept here (nothing written to OnlyFans), and List: picking
    one adds the link's claimers to that OF list once, in the background."""
    assert_account_owned(body.account_id)
    if body.kind not in EDITABLE:
        raise HTTPException(422, "kind: trial or campaign")
    out = await store_meta(body.account_id, body.kind, body.of_id, clean_meta(body))
    log.info("link_meta saved account=%s kind=%s of_id=%s", body.account_id, body.kind, body.of_id)
    return {"kind": body.kind, "of_id": body.of_id, **out}


_BATCH_FIELDS = ("promo_cost", "source", "tags")


class _BatchBody(_MetaFields):
    account_id: str
    kind: str
    of_ids: list[int] = Field(..., min_length=1, max_length=500)


@router.put("/admin/link-meta/batch")
async def save_link_meta_batch(body: _BatchBody = Body(...)) -> dict[str, Any]:
    """Infloww's batch edit on the picked links: each of Promo cost, Source and
    Tag that the body carries is set on every link (null or [] clears it); one
    it leaves out stays as each link has it. List is not batch-edited (it adds
    fans on OnlyFans). Stored here only, as the Edit dialog's save."""
    assert_account_owned(body.account_id)
    if body.kind not in EDITABLE:
        raise HTTPException(422, "kind: trial or campaign")
    fields = [f for f in _BATCH_FIELDS if f in body.model_fields_set]
    if not fields:
        raise HTTPException(422, "nothing to change: send promo_cost, source or tags")
    if any(i < 1 for i in body.of_ids):
        raise HTTPException(422, "of_ids: OnlyFans link ids")
    meta = clean_meta(body)
    ids = list(dict.fromkeys(body.of_ids))
    now = _now()
    async with get_session() as s:
        for of_id in ids:
            row = await _meta_row(s, body.account_id, body.kind, of_id)
            if "promo_cost" in fields:
                row.promo_cost_cents = meta["promo_cost_cents"]
            if "source" in fields:
                row.source = meta["source"]
            if "tags" in fields:
                row.tags_json = json.dumps(meta["tags"]) if meta["tags"] else None
            row.updated_at = now
    log.info("link_meta batch saved account=%s kind=%s links=%s fields=%s", body.account_id, body.kind, len(ids),
             ",".join(fields))
    return {"kind": body.kind, "of_ids": ids, "fields": fields}


# ── Profile promotion: "Add fans to list" (account-level) ─────────────

class _PromoListBody(BaseModel):
    account_id: str
    enabled: bool = False
    list_id: str | None = Field(None, pattern=r"^\d{1,20}$")   # OF's custom list (a number)
    list_name: str | None = Field(None, max_length=64)


def _promo_list_out(row: PromoListSetting | None) -> dict[str, Any]:
    return {"enabled": bool(row is not None and row.enabled and row.list_id),
            "list_id": row.list_id if row is not None else None,
            "list_name": row.list_name if row is not None else None}


@router.get("/admin/promo-list")
async def get_promo_list(account_id: str = Query(...)) -> dict[str, Any]:
    """Profile promotion's "Add fans to list": off with no list until saved."""
    assert_account_owned(account_id)
    async with get_session() as s:
        return _promo_list_out(await s.get(PromoListSetting, account_id))


async def _promo_list_task(account_id: str) -> None:
    """A save that turned the promotion List on or changed it: one pass now,
    under the account's lock, on each promotion's last-read claim count. The
    queue mark covers only the wait for the lock: a save after that queues one
    more pass, whose mark this task leaves alone."""
    released = False
    try:
        async with _lock(account_id):
            _LIST_QUEUED.discard((account_id, "promo", 0))
            released = True
            async with get_session() as s:
                counts = dict((await s.execute(select(LinkMeta.of_id, LinkMeta.claim_count).where(
                    LinkMeta.account_id == account_id, LinkMeta.kind == "promo"))).all())
            await sync_lists(account_id, "promo", None, {o: n or 0 for o, n in counts.items()})
    except Exception:
        log.info("promo list first add failed account=%s", account_id, exc_info=True)
    finally:
        if not released:
            _LIST_QUEUED.discard((account_id, "promo", 0))


@router.put("/admin/promo-list")
async def save_promo_list(body: _PromoListBody = Body(...)) -> dict[str, Any]:
    """Infloww's Profile promotion "Add fans to list": turning it on or
    changing the list adds every promotion's current claimers once, in the
    background (OF's own add-to-list; fans already added stay when it is
    changed or turned off). Later claimers are added only by a promotions
    refresh, i.e. when the page is opened with figures over an hour old; there
    is no scheduler."""
    assert_account_owned(body.account_id)
    list_id = body.list_id or None
    if body.enabled and not list_id:
        raise HTTPException(422, "pick a list to add fans to")
    async with get_session() as s:
        row = await s.get(PromoListSetting, body.account_id)
        if row is None:
            row = PromoListSetting(account_id=body.account_id, enabled=False)
            s.add(row)
        due = body.enabled and (not row.enabled or row.list_id != list_id)
        row.enabled = body.enabled
        row.list_id = list_id
        row.list_name = ((body.list_name or "").strip() or None) if list_id else None
        row.updated_at = _now()
        out = _promo_list_out(row)
    key = (body.account_id, "promo", 0)
    if due and key not in _LIST_QUEUED:
        _LIST_QUEUED.add(key)
        _spawn(_promo_list_task(body.account_id))
    log.info("promo list saved account=%s enabled=%s", body.account_id, out["enabled"])
    return out
