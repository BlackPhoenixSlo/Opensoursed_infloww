"""service/of_tracking_api.py — OnlyFans-NATIVE tracking links (/campaigns).

Distinct from the internal /t/<slug> redirector (tracking_links_api.py). These
are OnlyFans' OWN tracking links: OF mints a short profile URL per campaign and
reports, natively, how many people CLICKED it (countTransitions) and how many of
those actually SUBSCRIBED (countSubscribers) — real subscriber attribution the
internal redirect can never have.

OF is the entire source of truth (it stores the name too), so there is NO mirror
table — we read/create/delete straight against /campaigns.

The public share URL:
    https://onlyfans.com/<username>/c<campaignCode>

The /campaigns payload carries only `campaignCode`; OF's web app builds the link
client-side. Its Copy-link (statistics-reach-campaigns.js, `copyLink`) is
"https://onlyfans.com" + "/" + authUser.username + "/c" + campaignCode, and the
profile route takes `/:userId/:campaignCode` with the code as `c<digits>`:
exactly `_campaign_url` below, so `url_verified` is True. OF offers Copy-link
only while `endDate` is null (a live link).

Earnings per link (Infloww's Earnings, Fans who spent, Details):
  OF's `GET /campaigns/{id}/claimers` (OFClient.campaign_claimers) lists the
  fans each link brought in — ids, no money. Their spend comes from our own
  `transactions` ledger (gross `amount_cents`, OF's own `net_cents`), in
  TRACKED_STATUSES only (refunds / chargebacks / failed are not revenue).
  Infloww attributes "each fan's spending to the last ... link clicked by the
  fan"; OF gives no claim time, so each transaction goes to the fan's claiming
  link created most recently before it whose window (createdAt to endDate) is
  still open (`_spend`). A link with no createdAt gets no figure. Claimer lists
  are cached per link for _CLAIMERS_TTL (refetched early when countSubscribers
  moves; zero-subscriber links cost no OF call; a failure waits
  _CLAIMERS_FAIL_TTL), and the whole computation is memoised per account for
  _COMPUTED_TTL behind a per-account lock.

Routes (owner-gated, under /admin/*):
  GET    /admin/of-tracking-links?account_id=   list campaigns (+ url, stats),
         every page, deleted ones included with is_deleted:true
  POST   /admin/of-tracking-links               create {name[, promo_cost, source,
         tags, list_id, list_name]}: the name goes to OF; the rest is kept
         locally (link_metrics), as the Edit dialog's save
  GET    /admin/of-tracking-links/earnings?account_id=   per-link earnings
         (gross + net, fans who spent); available:false when OF is down
  GET    /admin/of-tracking-links/{campaign_id}/fans?account_id=   the link's
         fans with spend by kind (Subs, Posts, Messages, Streams, Tips)
  DELETE /admin/of-tracking-links/{campaign_id}?account_id=   delete on OF
         (the UI's "Deactivate": permanent, as Infloww's own; OF keeps the
         deleted campaign and its counts behind with_deleted=1)
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

import automation_executor as ax
import link_share_api
from attribution_backfill import TRACKED_STATUSES
from auth import assert_account_owned
from db.engine import get_session
from db.models import Transaction
from of_promos import safe_int

log = logging.getLogger("of-relay.of_tracking_api")

router = APIRouter()

# The share-URL format lives in exactly one place. See the module note.
_URL_VERIFIED = True


def _campaign_url(username: str | None, code: Any) -> str | None:
    if not username or code is None:
        return None
    return f"https://onlyfans.com/{username}/c{code}"


def _serialize(c: dict, username: str | None) -> dict:
    code = c.get("campaignCode")
    return {
        "id": c.get("id"),
        "code": code,
        "name": c.get("campaignName") or "",
        "url": _campaign_url(username, code),
        "url_verified": _URL_VERIFIED,
        # OF's native attribution — the whole reason to prefer these.
        "clicks": safe_int(c.get("countTransitions")),
        "subscribers": safe_int(c.get("countSubscribers")),
        "created_at": c.get("createdAt"),
        "end_date": c.get("endDate"),
        "is_deleted": bool(c.get("isDeleted")),
        "source": "onlyfans",
    }


async def _client_and_username(account_id: str):
    """(client, username) or raises 502 if the account has no live session.
    username is best-effort — a missing me() must not break list/create."""
    client = await asyncio.to_thread(ax._make_client, account_id)
    username = None
    try:
        me = await asyncio.to_thread(client.me)
        username = (me or {}).get("username")
    except Exception:
        log.info("of-tracking: me() failed account=%s — url will be null", account_id, exc_info=True)
    return client, username


# /campaigns pages ({list, hasMore}); a bare read returns only the first page.
_PAGE = 100
_MAX_PAGES = 50  # 5,000 links: a guard against an offset OF ignores, not a real cap


def _read_all(client) -> list[dict] | None:
    """Every campaign, deleted ones included, paging offset while hasMore
    holds. None when any page is not a list shape (OF unavailable): a silently
    partial list would read as links that vanished."""
    out: list[dict] = []
    seen: set = set()
    offset = 0
    for _ in range(_MAX_PAGES):
        raw = client.tracking_links(limit=_PAGE, offset=offset, with_deleted=True)
        rows = raw.get("list", raw) if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return None
        fresh = 0
        for c in rows:
            if not isinstance(c, dict):
                continue
            key = c.get("id") if c.get("id") is not None else ("code", c.get("campaignCode"))
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
            fresh += 1
        has_more = isinstance(raw, dict) and bool(raw.get("hasMore"))
        if not has_more or not rows or fresh == 0:
            break
        offset += len(rows)
    return out


@router.get("/admin/of-tracking-links")
async def list_of_tracking_links(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    try:
        client, username = await _client_and_username(account_id)
        rows = await asyncio.to_thread(_read_all, client)
    except Exception:
        log.info("of-tracking list failed account=%s", account_id, exc_info=True)
        return {"links": [], "username": None, "url_verified": _URL_VERIFIED,
                "of_available": False}
    if rows is None:
        return {"links": [], "username": username, "url_verified": _URL_VERIFIED,
                "of_available": False}
    # Deleted (Infloww's "Deactivated") rows ride along with is_deleted:true;
    # the UI hides them unless "Show deactivated links" is on.
    links = [_serialize(c, username) for c in rows]
    # The Edit dialog's Promo cost / Source / Tag, kept locally (link_metrics).
    from link_metrics import meta_fields, meta_for   # link_metrics imports this module
    meta, sources, tags = await meta_for(account_id, "campaign")
    for r in links:
        r.update(meta.get(safe_int(r["id"])) or meta_fields(None))
    return {"links": links, "username": username, "url_verified": _URL_VERIFIED,
            "of_available": True, "sources": sources, "tags": tags}


# ── Earnings: claimers (OF) x transactions (ours) ─────────────────────

# Infloww's Details columns, from our ledger kinds. A kind not listed lands in
# "other" so Total still holds every cent the fan spent.
_BUCKET = {
    "subscription": "subs", "rebill": "subs",
    "ppv_post": "posts",
    "ppv_message": "messages", "custom": "messages",
    "ppv_stream": "streams",
    "tip": "tips", "tip_post": "tips", "tip_stream": "tips",
}
_BUCKETS = ("subs", "posts", "messages", "streams", "tips", "other")

_CLAIMERS_TTL = 2 * 3600.0
_CLAIMERS_FAIL_TTL = 5 * 60.0   # an OF error (a 429) is not retried for this long
_CLAIMERS_PAGE = 50
_CLAIMERS_PAGE_SLEEP_S = 0.4    # between pages, as transaction_ingest paces OF
_CLAIMERS_MAX_PAGES = 400       # 20,000 fans per link: a guard against an ignored offset
# (account_id, campaign_id) -> (countSubscribers, fetched_at monotonic, fans)
_CLAIMERS_CACHE: dict[tuple[str, int], tuple[int, float, list[dict]]] = {}
# (account_id, campaign_id) -> monotonic time of the last OF failure
_CLAIMERS_FAILED: dict[tuple[str, int], float] = {}

# The whole computation per account, memoised briefly so opening Details (or a
# refetch) reuses it instead of re-reading every OF page; one at a time per account.
_COMPUTED_TTL = 60.0
_COMPUTED: dict[str, tuple[float, "_Computed"]] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def _parse_of_time(v: Any) -> datetime | None:
    """OF's createdAt ("…T…+00:00") or endDate ("YYYY-MM-DD HH:MM:SS") as naive
    UTC, the way transactions.occurred_at is stored. endDate carries no zone and
    is UTC: live 2026-10-18, 24 links created and deleted seconds apart read
    createdAt 03:01:27+00:00, endDate 03:01:31 on a UTC+2 creator."""
    if not v or not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def _fetch_claimers(client, campaign_id: int) -> list[dict]:
    """Every fan OF lists under the link, paging offset while hasMore holds.
    Raises on an OF error (the caller marks that link unavailable)."""
    fans: list[dict] = []
    seen: set[int] = set()
    offset = 0
    for page in range(_CLAIMERS_MAX_PAGES):
        if page:
            time.sleep(_CLAIMERS_PAGE_SLEEP_S)
        raw = client.campaign_claimers(campaign_id, limit=_CLAIMERS_PAGE, offset=offset)
        rows = raw.get("list") if isinstance(raw, dict) else None
        if not isinstance(rows, list):
            raise ValueError(f"claimers {campaign_id}: unexpected payload")
        fresh = 0
        for u in rows:
            fid = safe_int(u.get("id")) if isinstance(u, dict) else 0
            if not fid or fid in seen:
                continue
            seen.add(fid)
            fans.append({"fan_id": fid, "name": u.get("name") or u.get("displayName") or "",
                         "username": u.get("username") or ""})
            fresh += 1
        if not raw.get("hasMore") or not rows or fresh == 0:
            break
        offset += len(rows)
    return fans


def _claimers_cached(client, account_id: str, c: dict) -> list[dict]:
    """The link's fans from cache, refetched past the TTL or as soon as OF's
    countSubscribers moves. Zero subscribers: no fans, no OF call. A recent OF
    failure re-raises without calling OF again."""
    cid = safe_int(c.get("id"))
    subs = safe_int(c.get("countSubscribers"))
    if subs <= 0:
        return []
    key = (account_id, cid)
    hit = _CLAIMERS_CACHE.get(key)
    if hit and hit[0] == subs and time.monotonic() - hit[1] < _CLAIMERS_TTL:
        return hit[2]
    failed_at = _CLAIMERS_FAILED.get(key)
    if failed_at is not None and time.monotonic() - failed_at < _CLAIMERS_FAIL_TTL:
        raise RuntimeError(f"claimers {cid}: failed recently, not retried yet")
    try:
        fans = _fetch_claimers(client, cid)
    except Exception:
        _CLAIMERS_FAILED[key] = time.monotonic()
        raise
    _CLAIMERS_FAILED.pop(key, None)
    _CLAIMERS_CACHE[key] = (subs, time.monotonic(), fans)
    return fans


class _Computed:
    """One account's earnings: per link, per fan, per bucket."""

    def __init__(self, campaigns, fans_by, unknown, spend, ledger_since):
        self.campaigns: list[dict] = campaigns
        self.fans_by: dict[int, list[dict]] = fans_by      # links OF answered for
        self.unknown: set[int] = unknown                   # OF failed, or no createdAt
        self.spend: dict[tuple[int, int], dict] = spend    # (campaign, fan) -> buckets
        self.ledger_since: datetime | None = ledger_since  # the account's earliest ledger row
        self.claimed_by: dict[int, list[int]] = {}
        for cid, fans in fans_by.items():
            for f in fans:
                self.claimed_by.setdefault(f["fan_id"], []).append(cid)


def _blank() -> dict[str, Any]:
    return {**{f"{b}_cents": 0 for b in _BUCKETS}, **{f"{b}_net_cents": 0 for b in _BUCKETS},
            "total_cents": 0, "total_net_cents": 0, "net_missing_count": 0}


def _gather(client, account_id: str, campaigns: list[dict]) -> tuple[dict[int, list[dict]], set[int]]:
    """{campaign_id: fans} for every dated link OF answered for, and the ids with
    no figure: OF failed on them, or they carry no createdAt (no window start,
    so no honest spend; never all-time)."""
    fans_by: dict[int, list[dict]] = {}
    unknown: set[int] = set()
    for c in campaigns:
        cid = safe_int(c.get("id"))
        if not cid:
            continue
        if _parse_of_time(c.get("createdAt")) is None:
            unknown.add(cid)
            continue
        try:
            fans_by[cid] = _claimers_cached(client, account_id, c)
        except Exception:
            log.info("of-tracking claimers failed account=%s id=%s", account_id, cid, exc_info=True)
            unknown.add(cid)
    return fans_by, unknown


async def _spend(account_id: str, campaigns: list[dict], fans_by: dict[int, list[dict]]):
    """((campaign, fan) -> buckets, the account's earliest ledger time).

    Time-sliced attribution (Infloww's "last link clicked wins", OF giving no
    claim time): each transaction of a fan goes to the fan's claiming link with
    the latest createdAt at or before it whose window is still open (before its
    endDate); past a deactivated link's end it falls back to the next-latest open
    one. A fan claimed by one link counts inside that link's window only.

    One read of the account's ledger since the earliest link, filtered to
    claimers here (no IN list, so no bound-parameter ceiling). TRACKED_STATUSES
    only: refunds, chargebacks and failed rows are not revenue. fan_id is the OF
    user id on every ledger row, rebills included; a row without one can't be
    tied to a link and is not counted."""
    window = {safe_int(c.get("id")): (_parse_of_time(c.get("createdAt")), _parse_of_time(c.get("endDate")))
              for c in campaigns}
    claims: dict[int, list[tuple[datetime, int, datetime | None]]] = {}
    for cid, fans in fans_by.items():
        start, end = window[cid]
        for f in fans:
            claims.setdefault(f["fan_id"], []).append((start, cid, end))
    for lst in claims.values():
        lst.sort(reverse=True)   # latest createdAt first, ties to the higher id

    out: dict[tuple[int, int], dict] = {}
    async with get_session() as s:
        since = (await s.execute(select(func.min(Transaction.occurred_at))
                                 .where(Transaction.account_id == account_id))).scalar()
        if not claims:
            return out, since
        floor = min(st for lst in claims.values() for st, _c, _e in lst)
        rows = (await s.execute(
            select(Transaction.fan_id, Transaction.kind, Transaction.occurred_at,
                   Transaction.amount_cents, Transaction.net_cents)
            .where(Transaction.account_id == account_id,
                   Transaction.status.in_(TRACKED_STATUSES),
                   Transaction.fan_id.is_not(None),
                   Transaction.occurred_at >= floor)
        )).all()
    for fid, kind, at, gross, net in rows:
        lst = claims.get(int(fid))
        if not lst:
            continue
        cid = next((c for st, c, end in lst if st <= at and (end is None or at < end)), None)
        if cid is None:
            continue
        row = out.setdefault((cid, int(fid)), _blank())
        b = _BUCKET.get(kind, "other")
        row[f"{b}_cents"] += int(gross or 0)
        row["total_cents"] += int(gross or 0)
        if net is None:
            row["net_missing_count"] += 1
        else:
            row[f"{b}_net_cents"] += int(net)
            row["total_net_cents"] += int(net)
    return out, since


def _is_spender(row: dict | None) -> bool:
    """Infloww's Spending CVR counts "fans who spent on content or gave tips":
    any spend beyond the subscription itself."""
    return bool(row) and row["total_cents"] - row["subs_cents"] > 0


async def _compute(account_id: str) -> _Computed | None:
    """The account's earnings, memoised for _COMPUTED_TTL, one computation at a
    time per account. None when OF is unavailable (not memoised)."""
    lock = _LOCKS.setdefault(account_id, asyncio.Lock())
    async with lock:
        hit = _COMPUTED.get(account_id)
        if hit and time.monotonic() - hit[0] < _COMPUTED_TTL:
            return hit[1]
        client = await asyncio.to_thread(ax._make_client, account_id)
        campaigns = await asyncio.to_thread(_read_all, client)
        if campaigns is None:
            return None
        fans_by, unknown = await asyncio.to_thread(_gather, client, account_id, campaigns)
        await _sync_lists(account_id, client, campaigns)
        spend, since = await _spend(account_id, campaigns, fans_by)
        got = _Computed(campaigns, fans_by, unknown, spend, since)
        _COMPUTED[account_id] = (time.monotonic(), got)
        return got


async def _sync_lists(account_id: str, client, campaigns: list[dict]) -> None:
    """The Edit dialog's List: OF's add-to-list again for a link whose countSubscribers grew past the last add
    (link_metrics.sync_lists; under the account's lock, paced, an OF error backs the account off)."""
    from link_metrics import sync_lists   # link_metrics imports this module
    try:
        await sync_lists(account_id, "campaign", client,
                         {safe_int(c.get("id")): safe_int(c.get("countSubscribers")) for c in campaigns})
    except Exception:
        log.info("of-tracking list add failed account=%s", account_id, exc_info=True)


async def prewarm(account_id: str) -> bool:
    """link_metrics.prewarm_all's tracking-link pass, under the account's lock:
    OF's /campaigns read, the claimers re-read only for a link whose
    countSubscribers moved since its cached read, then the List adds. A link
    whose count held keeps its claimers, renewed (an expired _CLAIMERS_TTL alone
    costs no OF call here); one never read since boot waits for its page. A link
    OF failed on within _CLAIMERS_FAIL_TTL is not retried. False when OF's
    /campaigns read failed."""
    lock = _LOCKS.setdefault(account_id, asyncio.Lock())
    async with lock:
        client = await asyncio.to_thread(ax._make_client, account_id)
        campaigns = await asyncio.to_thread(_read_all, client)
        if campaigns is None:
            return False
        now = time.monotonic()
        moved: list[dict] = []
        for c in campaigns:
            key = (account_id, safe_int(c.get("id")))
            hit = _CLAIMERS_CACHE.get(key)
            if hit is None:
                continue
            if hit[0] == safe_int(c.get("countSubscribers")):
                _CLAIMERS_CACHE[key] = (hit[0], now, hit[2])
            else:
                moved.append(c)
        await asyncio.to_thread(_gather, client, account_id, moved)
        await _sync_lists(account_id, client, campaigns)
        return True


@router.get("/admin/of-tracking-links/earnings")
async def of_tracking_links_earnings(account_id: str = Query(...)) -> dict[str, Any]:
    """Per link: earnings (gross and net), fans who spent, fans counted (the
    link's claimers). A link with no figure (OF failed on it, or no createdAt)
    comes back with earnings null (the UI's "—"); OF down altogether is
    available:false, never a 500."""
    assert_account_owned(account_id)
    try:
        got = await _compute(account_id)
    except Exception:
        log.info("of-tracking earnings failed account=%s", account_id, exc_info=True)
        got = None
    if got is None:
        return {"available": False, "links": []}
    links = link_figures(got)
    # Share links on these links take the read just made (link_share_api; never fails the read).
    await link_share_api.refresh_shares(account_id, "campaign", {
        r["id"]: {**_serialize(c, None), **r} for c, r in zip(_dated(got), links)})
    return {"available": True, "links": links}


def _dated(got: _Computed) -> list[dict]:
    """The campaigns that have an id, in OF's order: link_figures' rows."""
    return [c for c in got.campaigns if safe_int(c.get("id"))]


def link_figures(got: _Computed) -> list[dict[str, Any]]:
    """Per link (`_dated`'s order): earnings (gross and net), fans who spent,
    fans counted; all None for a link with no figure."""
    links = []
    for c in _dated(got):
        cid = safe_int(c.get("id"))
        if cid in got.unknown:
            links.append({"id": cid, "earnings_cents": None, "earnings_net_cents": None,
                          "fans_who_spent": None, "fans_counted": None, "net_missing_count": 0})
            continue
        fans = got.fans_by.get(cid, [])
        rows = [got.spend.get((cid, f["fan_id"])) for f in fans]
        links.append({
            "id": cid,
            "earnings_cents": sum(r["total_cents"] for r in rows if r),
            "earnings_net_cents": sum(r["total_net_cents"] for r in rows if r),
            "fans_who_spent": sum(1 for r in rows if _is_spender(r)),
            "fans_counted": len(fans),
            "net_missing_count": sum(r["net_missing_count"] for r in rows if r),
        })
    return links


@router.get("/admin/of-tracking-links/{campaign_id}/fans")
async def of_tracking_link_fans(campaign_id: int, account_id: str = Query(...)) -> dict[str, Any]:
    """The Details overlay: every fan OF lists under the link, with the spend
    attributed to this link by kind (gross and net), most spent first; the rows
    sum to the link's Earnings. `also_claimed_by` names the fan's other links
    (their spend is split by time between them). `counted_from` is when the
    figures can start: the later of the link's creation and the account's
    earliest ledger row (the ledger backfills about 90 days). Search and paging
    are client-side."""
    assert_account_owned(account_id)
    try:
        got = await _compute(account_id)
    except Exception:
        log.info("of-tracking fans failed account=%s id=%s", account_id, campaign_id, exc_info=True)
        got = None
    if got is None:
        raise HTTPException(502, "Unable to load page. Try again later")
    link = next((c for c in got.campaigns if safe_int(c.get("id")) == campaign_id), None)
    if link is None:
        raise HTTPException(404, "tracking link not found")
    if campaign_id not in got.fans_by:
        raise HTTPException(502, "Unable to load page. Try again later")
    fans = []
    for f in got.fans_by[campaign_id]:
        row = got.spend.get((campaign_id, f["fan_id"])) or _blank()
        others = [c for c in got.claimed_by.get(f["fan_id"], []) if c != campaign_id]
        fans.append({**f, **row, "also_claimed_by": others})
    fans.sort(key=lambda r: (-r["total_cents"], r["fan_id"]))
    created = _parse_of_time(link.get("createdAt"))
    since = max(created, got.ledger_since) if created and got.ledger_since else created
    return {"fans": fans, "counted_from": since.isoformat() + "Z" if since else None}


class _MetaFields(BaseModel):
    """The Edit dialog's fields, kept locally (link_metrics): PUT /admin/link-meta
    and the create below take the same ones."""
    # Dollars, as Infloww's "Promo cost ($)" (11 characters with its commas):
    # up to 99,999,999.99. None or 0 is unset (its "—" rules).
    promo_cost: float | None = Field(None, ge=0, le=99_999_999.99)
    source: str | None = Field(None, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    # OF's custom fan list (a number; built-in lists take no adds) and its name for the List column.
    list_id: str | None = Field(None, pattern=r"^\d{1,20}$")
    list_name: str | None = Field(None, max_length=64)


class _CreateBody(_MetaFields):
    account_id: str
    name: str


@router.post("/admin/of-tracking-links")
async def create_of_tracking_link(body: _CreateBody = Body(...)) -> dict[str, Any]:
    """Create on OF by name; Source, Promo cost, Tag and List are stored for the
    new id as the Edit dialog's save stores them. OF's reply without an id:
    the link is created, the fields are not (`meta_saved:false`), never lost
    silently."""
    assert_account_owned(body.account_id)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    from link_metrics import clean_meta, meta_fields, store_meta   # link_metrics imports this module
    meta = clean_meta(body)          # a bad field is refused before OF creates anything

    try:
        client, username = await _client_and_username(body.account_id)
        res = await asyncio.to_thread(lambda: client.create_tracking_link(name=name))
    except Exception as e:
        log.warning("of-tracking create failed account=%s", body.account_id, exc_info=True)
        raise HTTPException(502, f"OnlyFans tracking-link create failed (session/API): {repr(e)[:200]}")

    # OF's create returns the campaign (bare dict) or a list holding it.
    created = res
    if isinstance(res, list) and res:
        created = res[0]
    if not isinstance(created, dict):
        # Fall back to re-reading the list to find it by name.
        try:
            rows = await asyncio.to_thread(_read_all, client) or []
            created = next((c for c in rows
                            if c.get("campaignName") == name and not c.get("isDeleted")), {})
        except Exception:
            created = {}
    _COMPUTED.pop(body.account_id, None)
    out = _serialize(created, username)
    cid = safe_int(out["id"])
    wanted = meta["promo_cost_cents"] is not None or meta["source"] or meta["tags"] or meta["list_id"]
    out.update(meta_fields(None))
    out["meta_saved"] = True
    if wanted:
        if cid:
            # A new link has no claimers: count 0 is "added", so the List's first add runs once one claims.
            out.update(await store_meta(body.account_id, "campaign", cid, meta, claim_count=0))
        else:
            out["meta_saved"] = False
    log.info("of_tracking_created account=%s id=%s code=%s meta_saved=%s", body.account_id, out["id"], out["code"],
             out["meta_saved"])
    return out


@router.delete("/admin/of-tracking-links/{campaign_id}")
async def delete_of_tracking_link(campaign_id: int, account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    try:
        client = await asyncio.to_thread(ax._make_client, account_id)
        await asyncio.to_thread(client.delete_tracking_link, int(campaign_id))
    except Exception as e:
        log.warning("of-tracking delete failed account=%s id=%s", account_id, campaign_id, exc_info=True)
        raise HTTPException(502, f"OnlyFans tracking-link delete failed: {repr(e)[:200]}")
    _COMPUTED.pop(account_id, None)
    log.info("of_tracking_deleted account=%s id=%s", account_id, campaign_id)
    return {"deleted": campaign_id}
