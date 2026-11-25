from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Iterable

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

import automation_executor as ax
from attribution_backfill import TRACKED_STATUSES
from auth import assert_account_owned
from db.engine import get_session
from db.models import LinkClaimer, LinkMeta, PromoCampaign, PromoListSetting, Transaction
from isotime import iso_z
import of_pacing
from of_promos import safe_int, to_cents
from of_tracking_api import _BUCKET, _MetaFields, _blank, _parse_of_time, walk_lock

log = logging.getLogger("of-relay.link_metrics")

router = APIRouter()

WALKED = ("trial", "promo")
EDITABLE = ("trial", "campaign")

_STALE_S = 3600.0
_FAIL_BACKOFF_S = 300.0
# The most OF reads per call on /subscriptions/subscribers: limit 21 silently lost 4 fans and 50 lost 52 (gaps, no dups).
_PAGE = 20
_PAGE_SLEEP_S = 0.4
_MAX_EXTRA_PAGES = 5
_UNKNOWN_MAX_PAGES = 200

_LIFETIME = ("total", "subs", "posts", "messages", "streams", "tips")
_SUMM = {"total": "totalSumm", "subs": "subscribesSumm", "posts": "postsSumm",
         "messages": "messagesSumm", "streams": "streamsSumm", "tips": "tipsSumm"}

_REFRESHING: set[tuple[str, str]] = set()
_FAILED_AT: dict[tuple[str, str], float] = {}
_TASKS: set[asyncio.Task] = set()  # strong refs, so a running refresh is not collected
_REWALKING: set[tuple[str, str, int]] = set()
_LIST_QUEUED: set[tuple[str, str, int]] = set()
_LIST_FAILED_AT: dict[str, float] = {}


def _now() -> datetime:
    return datetime.utcnow()



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


# Neither a short page nor hasMore ends the walk (OF returned 9 fans at offset 0, 10 at offset 10, hasMore true; hasMore can be true on an empty page).
# So the offset moves by the page size and the walk ends on an empty page, hasMore false, or a short page past the claim count.
def walk(client, kind: str, of_id: int, expected: int | None) -> list[dict]:
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
    # subscribe_at is kept from first sight and never moved later (OF's current subscribeAt is its only date per fan).
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
        meta = await meta_row(s, account_id, kind, of_id)
        meta.claim_count = count if count is not None else len(fans)
        meta.walked_at = now
        meta.checked_at = now
        if campaign_id is not None:
            meta.campaign_id = campaign_id


async def meta_row(s, account_id: str, kind: str, of_id: int) -> LinkMeta:
    row = (await s.execute(select(LinkMeta).where(
        LinkMeta.account_id == account_id, LinkMeta.kind == kind, LinkMeta.of_id == of_id))).scalar_one_or_none()
    if row is None:
        row = LinkMeta(account_id=account_id, kind=kind, of_id=of_id)
        s.add(row)
    return row



Link = tuple[int, int, "int | None"]


# One walk at a time under the account's walk lock, shared with of_tracking_api, so tracking-link and trial/promo walks never hit OF at once.
async def refresh(account_id: str, kind: str, links: list[Link]) -> dict[str, int]:
    walked = checked = 0
    async with walk_lock(account_id):
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
                        m = await meta_row(s, account_id, kind, of_id)
                        m.checked_at = now
                        if camp.get(of_id) is not None:
                            m.campaign_id = camp[of_id]
                        checked += 1
    return {"walked": walked, "checked": checked}


async def _refresh_task(account_id: str, kind: str, links: list[Link]) -> None:
    try:
        # Background walk: paced per Creator, OF's 429 retried once.
        await of_pacing.walk(account_id, "link_refresh", lambda: refresh(account_id, kind, links))
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



def links_of_trials(fetched: list[dict]) -> list[Link]:
    return [(t["of_trial_id"], safe_int(t.get("claim_counts")), None) for t in fetched if t.get("of_trial_id")]


# A re-armed promotion keeps its earlier OF promos in link_meta under our campaign id, so the campaign's figures add up across re-arms.
def links_of_promos(fetched: list[dict], mirrors: Iterable[PromoCampaign],
                    past: dict[int, list[int]]) -> list[Link]:
    campaign_of = {o: m.id for m in mirrors for o in [m.of_promo_id, *past.get(m.id, [])] if o}
    return [(p["of_promo_id"], safe_int(p.get("subscriber_count")), campaign_of.get(p["of_promo_id"]))
            for p in fetched if p.get("of_promo_id")]



class _Book:

    def __init__(self, claimers, spend, ledger_since):
        self.claimers: dict[tuple[str, int], list[LinkClaimer]] = claimers
        self.spend: dict[tuple[str, int, int], dict] = spend
        self.ledger_since: datetime | None = ledger_since


# Each ledger row goes to the claim with the latest subscribe_at at or before it (Infloww: spend belongs to the last link/promotion claimed).
# TRACKED_STATUSES only (pending counted): refunds, chargebacks and failed rows are not revenue.
async def _book(account_id: str) -> _Book:
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
    # A fan OF sent without subscribedOnData has no subscribeAt: his spend is "—", never a guess.
    fans = _group_fans(book, kind, of_ids)
    known = [f["spend"] for f in fans.values() if f["spend"] is not None]
    if fans and not known:
        return {**_UNWALKED, "claimers": len(fans), "spend_unknown": len(fans)}
    return {
        "earnings_cents": sum(r["total_cents"] for r in known),
        "earnings_net_cents": sum(r["total_net_cents"] for r in known),
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
    return {"by": by, "updated_at": iso_z(updated_at), "refreshing": refreshing}



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
    the account's walk lock (then the cache, with `refreshing`)."""
    assert_account_owned(account_id)
    refreshing = False
    async with get_session() as s:
        meta = (await s.execute(select(LinkMeta).where(
            LinkMeta.account_id == account_id, LinkMeta.kind == kind, LinkMeta.of_id == of_id))).scalar_one_or_none()
    walked = meta is not None and meta.walked_at is not None
    moved = count is not None and walked and meta.claim_count != count
    if count != 0 and (not walked or moved):
        if walk_lock(account_id).locked():
            refreshing = True
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
                     "subscribe_at": iso_z(c.subscribe_at), "first_seen_at": iso_z(c.first_seen_at),
                     "since": f["spend"], "lifetime": _lifetime(c)})
    fans.sort(key=lambda r: (-((r["since"] or {}).get("total_net_cents") or 0),
                             -((r["lifetime"] or {}).get("total_cents") or 0), r["fan_id"]))
    async with get_session() as s:
        walked_at = (await s.execute(select(func.max(LinkMeta.walked_at)).where(
            LinkMeta.account_id == account_id, LinkMeta.kind == kind,
            LinkMeta.of_id.in_(of_ids)))).scalar()
    return {"fans": fans, "ledger_since": iso_z(book.ledger_since), "walked_at": iso_z(walked_at),
            "refreshing": refreshing}


async def _walk_one(account_id: str, kind: str, of_id: int, count: int | None,
                    campaign_id: int | None) -> None:
    async with walk_lock(account_id):
        client = await asyncio.to_thread(ax._make_client, account_id)
        fans = await asyncio.to_thread(walk, client, kind, of_id, count)
        await _store_walk(account_id, kind, of_id, fans, count, campaign_id)


def _rewalk_later(account_id: str, kind: str, of_id: int, count: int | None, campaign_id: int | None) -> bool:
    key = (account_id, kind, of_id)
    if key in _REWALKING:
        return True
    if walk_lock(account_id).locked():
        return False
    if _backed_off(account_id, kind):
        return False
    _REWALKING.add(key)
    _spawn(_rewalk_task(account_id, kind, of_id, count, campaign_id))
    return True


async def _rewalk_task(account_id: str, kind: str, of_id: int, count: int | None, campaign_id: int | None) -> None:
    try:
        await of_pacing.walk(account_id, "link_rewalk", lambda: _walk_one(account_id, kind, of_id, count, campaign_id))
    except Exception:
        _FAILED_AT[(account_id, kind)] = time.monotonic()
        log.info("link_metrics stale re-walk failed account=%s %s=%s", account_id, kind, of_id, exc_info=True)
    finally:
        _REWALKING.discard((account_id, kind, of_id))



def _list_backoff(account_id: str) -> bool:
    failed = _LIST_FAILED_AT.get(account_id)
    return failed is not None and time.monotonic() - failed < _FAIL_BACKOFF_S


async def _add_one(account_id: str, client, kind: str, of_id: int, list_id: str, count: int) -> None:
    try:
        r = await asyncio.to_thread(client.add_link_claimers_to_list, list_id, kind, of_id)
    except Exception:
        _LIST_FAILED_AT[account_id] = time.monotonic()
        raise
    async with get_session() as s:
        m = await meta_row(s, account_id, kind, of_id)
        if m.list_id == list_id:
            m.list_added_count = count
    log.info("link list add account=%s %s=%s list=%s count=%s added=%s", account_id, kind, of_id, list_id, count,
             r.get("count") if isinstance(r, dict) else None)


async def _point_promos_at_setting(account_id: str, counts: dict[int, int]) -> bool:
    async with get_session() as s:
        st = await s.get(PromoListSetting, account_id)
        if st is None or not st.enabled or not st.list_id:
            return False
        for of_id, n in counts.items():
            if not n or n <= 0:
                continue
            m = await meta_row(s, account_id, "promo", of_id)
            if m.list_id != st.list_id:
                m.list_id = st.list_id
                m.list_added_count = None
            m.list_name = st.list_name
    return True


async def _current_list(account_id: str, kind: str, of_id: int) -> str | None:
    async with get_session() as s:
        return (await s.execute(select(LinkMeta.list_id).where(
            LinkMeta.account_id == account_id, LinkMeta.kind == kind, LinkMeta.of_id == of_id))).scalar_one_or_none()


async def _promo_list_is(account_id: str, list_id: str) -> bool:
    async with get_session() as s:
        st = await s.get(PromoListSetting, account_id)
        return st is not None and bool(st.enabled) and st.list_id == list_id


# OF's add-to-list adds every current claimer and nobody twice, so two overlapping sync paths (walks here, of_tracking_api earnings read) are harmless.
async def sync_lists(account_id: str, kind: str, client, counts: dict[int, int]) -> int:
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
        # Rows were read once: a save since (List changed/cleared, promo setting off) skips this link; an add already sent to OF still lands in the old list.
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
    if kind == "campaign":
        from of_tracking_api import _CLAIMERS_CACHE
        hit = _CLAIMERS_CACHE.get((account_id, m.of_id))
        return hit[0] if hit else 0
    return m.claim_count or 0


async def _list_add_task(account_id: str, kind: str, of_id: int) -> None:
    released = False
    try:
        async with walk_lock(account_id):
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



_TAG_MAX = 100  # Infloww's "Tag name" input limit


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
    async with get_session() as s:
        rows = (await s.execute(select(LinkMeta).where(
            LinkMeta.account_id == account_id, LinkMeta.kind.in_(EDITABLE)))).scalars().all()
    by = {r.of_id: meta_fields(r) for r in rows if r.kind == kind}
    sources = sorted({r.source.lower(): r.source for r in rows if r.source}.values(), key=str.lower)
    tags = sorted({t.lower(): t for r in rows for t in _tags(r)}.values(), key=str.lower)
    return by, sources, tags


class _MetaBody(_MetaFields):
    account_id: str
    kind: str
    of_id: int = Field(..., ge=1)


def clean_meta(body: _MetaFields) -> dict[str, Any]:
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
    async with get_session() as s:
        row = await meta_row(s, account_id, kind, of_id)
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
            row = await meta_row(s, body.account_id, body.kind, of_id)
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



class _PromoListBody(BaseModel):
    account_id: str
    enabled: bool = False
    list_id: str | None = Field(None, pattern=r"^\d{1,20}$")
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
    released = False
    try:
        async with walk_lock(account_id):
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
