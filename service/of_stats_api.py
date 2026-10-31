"""service/of_stats_api.py — server.py's analytics block, moved wholesale: the
OF mirror's read-only Statistics / Statements / Reach routes (`/api/of/v2/...`
charts, tops, lists, streaks, referrals) and `/admin/stats/referrals`, plus the
read-only Settings reads that sat in that block (`/users/me/profile/views/qr`,
`/sessions`, `/streams/users/blocked`, `/users/me/start-date-model`,
`/users/settings/notifications/{transport}`) and `/posts/bookmarks/all`.

Server-global helpers (`_proxy`, `_get_client`, `_load_client`,
`_priority_lane_background`) are relay_host's call-time forwards, so a test's
`server._get_client = fake` still reaches these routes; `_account_ttl` resolves
once, at import, so import this module only after (or from) server.py.

Included mid-file in server.py for route order (pinned by
service/tests/test_route_order.py).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

import account_health
import accounts as account_registry
import admission
import of_promos
import relay_cache
from relay_host import account_ttl as _account_ttl
from relay_host import get_client as _get_client
from relay_host import load_client as _load_client
from relay_host import priority_lane_background as _priority_lane_background
from relay_host import proxy as _proxy
from stats_window import scope_ids as _stats_scope_ids
from stats_window import stats_guard as _stats_guard

log = logging.getLogger("of-relay")

router = APIRouter()

# ── Analytics (Statistics > Earnings/Engagement/Reach tabs) ────────
# All accept startDate/endDate as ISO with space (OF spec). Default = 30d window.

_CHART_FILTER_KEY = re.compile(r"^[a-z][a-z_]{0,40}$")

def _chart_filter(filter: str | None) -> list[str] | None:
    """Comma-separated series names → OF's filter[k]=k keys (422 on junk)."""
    if not filter:
        return None
    keys = [k.strip() for k in filter.split(",") if k.strip()]
    if not keys or not all(_CHART_FILTER_KEY.match(k) for k in keys):
        raise HTTPException(status_code=422, detail="filter: comma-separated series names")
    return keys

@router.get("/api/of/v2/earnings/chart")
@_account_ttl("earnings_chart", 120)
def of_earnings_chart(
    start: str | None = Query(None), end: str | None = Query(None),
    filter: str | None = Query(None, description="Comma-separated series, e.g. "
                               "'tips_count,tips_amount' (Statements) or "
                               "'total_amount,subscribes_amount,…' (Overview)"),
    monthlyTotal: int = Query(0, ge=0, le=1, description="1 = Overview's monthly bars (dates ignored)"),
):
    """Earnings series for Statistics (Overview chart, Statements sidebar and
    category radios). OF only returns the series named in `filter` — with none
    it answers [], which is why these charts were blank."""
    keys = _chart_filter(filter)
    return _proxy(lambda: _get_client().earnings_chart(
        start=start, end=end, filter=keys, monthly_total=bool(monthlyTotal)))

# /posts/chart and /posts/top stay in server.py, above /posts/{post_id}
# (its "Posts shortcuts" section), so the int-typed dynamic route doesn't
# shadow them. Nothing here.

@router.get("/api/of/v2/users/me/stats/overview")
@_account_ttl("me_stats", 120)
def of_my_stats_overview(start: str | None = Query(None), end: str | None = Query(None),
                          by: str = Query("visitors")):
    """My stats overview (visitors/engagement)."""
    return _proxy(lambda: _get_client().my_stats_overview(start=start, end=end, by=by))

@router.get("/api/of/v2/users/me/stats/top/post")
@_account_ttl("me_stats", 120)
def of_my_stats_top_posts(start: str | None = Query(None), end: str | None = Query(None),
                          limit: int = Query(10, ge=1, le=50)):
    """My best-performing posts across types."""
    return _proxy(lambda: _get_client().my_stats_top_posts(start=start, end=end, limit=limit))

_PROFILE_STATS_BLOCKS = {"chart", "topDomains", "topCountries"}

@router.get("/api/of/v2/users/me/profile/stats")
def of_my_profile_stats(start: str | None = Query(None), end: str | None = Query(None),
                         limit: int = Query(10, ge=0, le=50),
                         by: str | None = Query(None, pattern="^(total|guests|users)$",
                                                description="Reach's All / Guests / Users chips"),
                         filter: str | None = Query(None, description="Comma-separated blocks: "
                                                    "chart, topDomains, topCountries (OF's filter[])")):
    """Visitor source breakdown (Statistics → Reach)."""
    blocks = [b.strip() for b in filter.split(",") if b.strip()] if filter else None
    if blocks is not None and (not blocks or not set(blocks) <= _PROFILE_STATS_BLOCKS):
        raise HTTPException(status_code=422, detail="filter: chart, topDomains and/or topCountries")
    return _proxy(lambda: _get_client().my_profile_stats(
        start=start, end=end, limit=limit, by=by, filter=blocks))

@router.get("/api/of/v2/users/me/profile/views/qr")
def of_my_qr_views():
    """Settings > QR code's scan count: OF's GET /users/me/profile/views/qr ({count})."""
    return _proxy(lambda: _get_client().qr_views())

@router.get("/api/of/v2/sessions")
def of_sessions():
    """Settings > Account > Login sessions, read-only: OF's GET /sessions (a list). Ending
    sessions (OF's DELETE /sessions) has no relay route."""
    return _proxy(lambda: _get_client().sessions())

@router.get("/api/of/v2/streams/users/blocked")
def of_stream_blocked_users(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0),
                            query: str = Query("", max_length=64)):
    """Settings > Streaming > Blocked users, read-only: OF's GET /streams/users/blocked
    ({list, hasMore}). Blocking and unblocking have no relay route."""
    return _proxy(lambda: _get_client().stream_blocked_users(limit=limit, offset=offset, query=query))

@router.get("/api/of/v2/users/me/start-date-model")
def of_my_start_date():
    """When I became a creator — used to range-cap charts."""
    return _proxy(lambda: _get_client().my_start_date())

@router.get("/api/of/v2/payouts/chargebacks/ratio")
@_account_ttl("payouts", 60)
def of_chargebacks_ratio(start: str | None = Query(None), end: str | None = Query(None)):
    """Chargeback-rate risk metric."""
    return _proxy(lambda: _get_client().chargebacks_ratio(start=start, end=end))

# ── Statistics pages: lists, tops, streaks (OF app.js module 977600) ──
# Read-only GETs, one per call OF's own Statistics pages make; paths and query
# params copied from OF's client. `start`/`end` are 'YYYY-MM-DD HH:MM:SS' and
# default to the last 30 days, like every other analytics route here.

@router.get("/api/of/v2/payouts/chargebacks")
@_account_ttl("payouts", 60)
def of_chargebacks(start: str | None = Query(None), end: str | None = Query(None),
                   limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0),
                   marker: str | None = Query(None, max_length=64)):
    """Statements › Chargebacks list: {list, marker} (no hasMore; a full page means more)."""
    return _proxy(lambda: _get_client().chargebacks(
        start=start, end=end, limit=limit, offset=offset, marker=marker))

@router.get("/api/of/v2/users/me/stats/top/{kind}")
@_account_ttl("me_stats", 120)
def of_my_stats_top(kind: str, start: str | None = Query(None), end: str | None = Query(None)):
    """Overview › Top highlights: top message / stream / story, or top fan per
    category (an object keyed by category). /top/post is its own route above."""
    if kind not in ("message", "stream", "story", "fan"):
        raise HTTPException(status_code=404, detail="unknown top kind")
    return _proxy(lambda: _get_client().stats_top(kind, start=start, end=end))

@router.get("/api/of/v2/streaks")
def of_streaks(start: str | None = Query(None), end: str | None = Query(None)):
    """Overview › Streaks calendar: {list:[streak]}."""
    return _proxy(lambda: _get_client().streaks(start=start, end=end))

@router.get("/api/of/v2/streaks/top")
def of_streaks_top():
    """Overview › Streaks: the longest streak (`days`)."""
    return _proxy(lambda: _get_client().streaks_top())

@router.get("/api/of/v2/users/me/stats/today-activity")
@_account_ttl("me_stats", 120)
def of_today_activity():
    """Overview › Streaks: whether today already counts toward the streak."""
    return _proxy(lambda: _get_client().today_activity())

@router.get("/api/of/v2/users/me/stats/messages/direct")
@_account_ttl("me_stats", 120)
def of_direct_message_stats(startDate: str = Query(..., description="YYYY-MM-DD HH:MM:SS"),
                            endDate: str = Query(..., description="YYYY-MM-DD HH:MM:SS"),
                            limit: int = Query(50, ge=1, le=100),
                            offset: int = Query(0, ge=0),
                            query: str | None = Query(None, max_length=200)):
    """Engagement › Messages › Direct messages tab (and its search box):
    {hasMore, items:[message]}. Same params as the mass-messages route."""
    return _proxy(lambda: _get_client().engagement_messages(
        "direct", start_date=startDate, end_date=endDate, limit=limit, offset=offset, query=query))

@router.get("/api/of/v2/messages/queue/chart")
def of_messages_chart(type: str = Query("group", pattern="^(group|direct)$"),
                      start: str | None = Query(None), end: str | None = Query(None)):
    """Engagement › Messages chart + totals for one tab: OF's
    filter[{type}_messages] and filter[{type}_messages_purchases], withTotal."""
    return _proxy(lambda: _get_client().messages_chart(type, start=start, end=end))

# The queue id rides in the query, not the path, so the permission map can give
# this read to Statistics alone: a `/messages/queue/{id}/...` path could only be
# mapped through the `/messages/queue` prefix, which also carries the queue's writes.
@router.get("/api/of/v2/messages/queue/buyers")
def of_mass_message_buyers(queue_id: int = Query(..., ge=1, description="The mass message's queue id"),
                           limit: int = Query(10, ge=1, le=50),
                           offset: int = Query(0, ge=0),
                           marker: str | None = Query(None, max_length=64),
                           skip_users: str | None = Query(None, pattern="^(all|none)$")):
    """Who bought one mass message (the row's buyers list) — OF's
    /messages/queue/{queue_id}/buyers."""
    return _proxy(lambda: _get_client().mass_message_buyers(
        queue_id, limit=limit, offset=offset, marker=marker, skip_users=skip_users))

@router.get("/api/of/v2/subscriptions/subscribers/latest")
def of_subscribers_latest(by: str = Query("total", pattern="^(total|renew|new)$"),
                          start: str | None = Query(None), end: str | None = Query(None),
                          offset: int = Query(0, ge=0)):
    """Fans › Subscriptions table, tab All (total) / Renews (renew) / New (new):
    {users, hasMore}, 10 a page."""
    return _proxy(lambda: _get_client().subscribers_latest(by=by, start=start, end=end, offset=offset))

@router.get("/api/of/v2/subscriptions/subscribers/top")
def of_subscribers_top(by: str = Query("total", pattern="^(total|subscribes|tips|messages|post|streams)$"),
                       start: str | None = Query(None), end: str | None = Query(None),
                       offset: int = Query(0, ge=0)):
    """Fans › Top fans by total / subscriptions / tips / messages / posts /
    streams: {users, hasMore}, 10 a page."""
    return _proxy(lambda: _get_client().subscribers_top(by=by, start=start, end=end, offset=offset))

@router.get("/api/of/v2/fans-activity/list")
def of_fans_activity(format: str = Query("table", pattern="^(table|hours)$"),
                     start: str | None = Query(None), end: str | None = Query(None),
                     timeZone: str = Query("UTC", pattern=r"^[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+)*$")):
    """Fans › Fans activity: weekday table or hourly bars in the owner's timezone."""
    return _proxy(lambda: _get_client().fans_activity(
        format=format, start=start, end=end, time_zone=timeZone))

@router.get("/api/of/v2/streams/top")
def of_streams_top(by: str = Query("purchases", pattern="^(purchases|tips|views|likes|comments)$"),
                   start: str | None = Query(None), end: str | None = Query(None),
                   limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Engagement › Streaming list: {items, hasMore}."""
    return _proxy(lambda: _get_client().streams_top(
        by=by, start=start, end=end, limit=limit, offset=offset))

@router.get("/api/of/v2/stories/top")
def of_stories_top(by: str = Query("tips", pattern="^(tips|views|likes|comments)$"),
                   start: str | None = Query(None), end: str | None = Query(None),
                   limit: int = Query(4, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Engagement › Stories list: {items, hasMore}."""
    return _proxy(lambda: _get_client().stories_top(
        by=by, start=start, end=end, limit=limit, offset=offset))

@router.get("/api/of/v2/promotions/stats")
def of_promotions_stats(start: str | None = Query(None), end: str | None = Query(None),
                        limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)):
    """Reach › Promotions table: OF's dated /promotions?offset&startDate&endDate&limit,
    {items, hasMore}. Its own path (not /promotions) so the permission map can give
    this read to Statistics without the promotion writes."""
    return _proxy(lambda: _get_client().promotions_stats(
        start=start, end=end, limit=limit, offset=offset))

@router.get("/api/of/v2/campaigns/stats")
def of_campaigns_stats(start: str | None = Query(None), end: str | None = Query(None),
                       limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0),
                       field: str | None = Query(None, pattern="^[A-Za-z_]{1,40}$"),
                       sort: str | None = Query(None, pattern="^(asc|desc)$")):
    """Reach › Tracking links table: OF's /campaigns?limit&offset&pagination=1&dates
    &with_deleted=1&sorting_deleted=0&stats=true (+field/sort), {list, hasMore}.
    Its own path (not /campaigns) so the permission map can give this read to
    Statistics without the tracking-link writes."""
    return _proxy(lambda: _get_client().campaigns_stats(
        start=start, end=end, limit=limit, offset=offset, field=field, sort=sort))

@router.get("/api/of/v2/trials/stats")
def of_trials_stats(start: str | None = Query(None), end: str | None = Query(None),
                    limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)):
    """Reach › Free trial links table: {items, hasMore}."""
    return _proxy(lambda: _get_client().trials_stats(
        start=start, end=end, limit=limit, offset=offset))

# Reach's "claimed" / subscribers lists, one per row, paged by 10 like OF's
# user-list modal. The row id rides in the query: `/promotions/{id}`,
# `/trials/{id}` and `/campaigns/{id}` are OF settings' writes.
@router.get("/api/of/v2/promotions/claims")
def of_promotion_claims(promo_id: int = Query(..., ge=1), limit: int = Query(10, ge=1, le=50),
                        offset: int = Query(0, ge=0)):
    """Reach › Promotions › claimed: OF's /subscriptions/subscribers
    ?filter[promoId]=<promo_id>&format=infinite, {list:[user], hasMore}."""
    return _proxy(lambda: _get_client().offer_claims(promo_id, "promo", limit=limit, offset=offset))

@router.get("/api/of/v2/trials/claims")
def of_trial_claims(trial_id: int = Query(..., ge=1), limit: int = Query(10, ge=1, le=50),
                    offset: int = Query(0, ge=0)):
    """Reach › Free trial links › claimed: OF's /subscriptions/subscribers
    ?filter[trial_id]=<trial_id>&format=infinite, {list:[user], hasMore}."""
    return _proxy(lambda: _get_client().offer_claims(trial_id, "trial", limit=limit, offset=offset))

@router.get("/api/of/v2/campaigns/claimers")
def of_campaign_claimers(campaign_id: int = Query(..., ge=1), limit: int = Query(10, ge=1, le=50),
                         offset: int = Query(0, ge=0),
                         query: str | None = Query(None, max_length=100, description="the modal's search box")):
    """Reach › Tracking links › subscribers: OF's /campaigns/{campaign_id}/claimers,
    {list:[user], hasMore}."""
    return _proxy(lambda: _get_client().campaign_claimers(
        campaign_id, limit=limit, offset=offset, query=query))

# Charts OF's Statistics pages draw (module 977600; campaigns via 616150).
@router.get("/api/of/v2/payouts/chart")
@_account_ttl("payouts", 60)
def of_payouts_chart(start: str | None = Query(None), end: str | None = Query(None)):
    """Statements › Payout requests chart: {total, delta, chartAmount, chartCount}."""
    return _proxy(lambda: _get_client().payouts_chart(start=start, end=end))

@router.get("/api/of/v2/payouts/referrals/chart")
@_account_ttl("payouts", 60)
def of_referrals_chart(start: str | None = Query(None), end: str | None = Query(None)):
    """Statements › Referrals chart: {total, delta, chartAmount, chartCount}."""
    return _proxy(lambda: _get_client().referrals_chart(start=start, end=end))


# The referrals fan-out's overall budget: a Creator OF has not answered for by
# then is listed `unavailable` and the rest return. Its read keeps running
# (parked below, not cancelled) and lands in the cache for the next ask.
_REFERRALS_BUDGET_S = max(1.0, float(os.environ.get("REFERRALS_BUDGET_S", "10")))
_referrals_running: set[asyncio.Task] = set()
# Creators with a referrals read in flight, one at a time each: a miss for
# another window while one runs is `unavailable` rather than a second read, so
# flipping through date ranges cannot stack OF reads up behind the slots.
_referrals_reading: set[str] = set()


@router.get("/admin/stats/referrals", dependencies=[Depends(_stats_guard)])
async def admin_stats_referrals(
    account_id: str | None = Query(None, description="One id or several comma-separated; omit for every Creator"),
    from_: str = Query(..., alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    to: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    """Referral earnings per Creator over `from`..`to` (whole days), for the
    Dashboard's Referrals tile and Creator reports' Referrals channel.

    No transaction carries them, so this is OF's Statements › Referrals
    chart, ONE read per Creator (`referrals_chart`), at background priority,
    cached 5 minutes in the `payouts` namespace like the proxy above. The
    fan-out holds `admission.REFERRALS_READ` slots and answers within
    `_REFERRALS_BUDGET_S`. Read-only. OF buckets the days in its own time
    zone, not the report zone, so `by_day` and the window's edges can sit a
    few hours off the ledger's days. Scoped like the stats reads (the
    caller's Creators, 403 on a foreign id), then narrowed to Creators with a
    session; Fansly has no referral program, so its Creators are skipped. A
    Creator whose read fails, runs past the budget, is still reading another
    window, or is deactivated (it gets no OF call) is listed in `unavailable`
    rather than failing the rest. Rows `{account_id, total_cents, by_day:
    [{day, cents}]}`; OF's amounts are dollars."""
    scoped, _ = _stats_scope_ids(account_id)
    metas = account_registry.list_accounts()
    live = {m["id"] for m in metas if m.get("has_session")}
    ids = [a for a in (scoped if scoped is not None else [m["id"] for m in metas])
           if a in live and account_registry.get_platform(a) != "fansly"]
    off = await account_health.deactivated_ids()
    start, end = f"{from_} 00:00:00", f"{to} 23:59:59"

    async def one(aid: str) -> dict[str, Any]:
        def read():
            with _priority_lane_background(aid):
                return _load_client(aid).referrals_chart(start=start, end=end)

        async def fetch():
            # Only a cache miss takes a slot: a hit never queues behind OF reads.
            if aid in _referrals_reading:
                raise RuntimeError("a read for another window is still running")
            _referrals_reading.add(aid)
            try:
                async with admission.REFERRALS_READ:
                    return await asyncio.to_thread(read)
            finally:
                _referrals_reading.discard(aid)
        data = await relay_cache.get_or_fetch("payouts", aid, ("referrals", start, end), 300.0, fetch) or {}
        by_day = [{"day": str(p.get("date") or "")[:10], "cents": of_promos.to_cents(p.get("count"))}
                  for p in data.get("chartAmount") or [] if p.get("date")]
        return {"account_id": aid, "total_cents": of_promos.to_cents(data.get("total")), "by_day": by_day}

    tasks = {asyncio.create_task(one(a)): a for a in ids if a not in off}
    done, late = await asyncio.wait(set(tasks), timeout=_REFERRALS_BUDGET_S) if tasks else (set(), set())
    rows: list[dict[str, Any]] = []
    unavailable: list[str] = [a for a in ids if a in off]
    for t, aid in tasks.items():
        if t in late:
            _referrals_running.add(t)  # deliberately NOT cancelled
            t.add_done_callback(_referrals_running.discard)
            unavailable.append(aid)
        elif t.exception() is not None:
            log.warning("referrals read failed for %s: %r", aid, t.exception())
            unavailable.append(aid)
        else:
            rows.append(t.result())
    return {"rows": rows, "unavailable": unavailable}

@router.get("/api/of/v2/payouts/chargebacks/chart")
@_account_ttl("payouts", 60)
def of_chargebacks_chart(start: str | None = Query(None), end: str | None = Query(None)):
    """Statements › Chargebacks chart: {total, delta, chartAmount, chartCount}."""
    return _proxy(lambda: _get_client().chargebacks_chart(start=start, end=end))


@router.get("/api/of/v2/promotions/chart")
def of_promotions_chart(start: str | None = Query(None), end: str | None = Query(None)):
    """Reach › Promotions chart: {<series>: {chart, total, delta}}."""
    return _proxy(lambda: _get_client().promotions_chart(start=start, end=end))

@router.get("/api/of/v2/trials/chart")
def of_trials_chart(start: str | None = Query(None), end: str | None = Query(None)):
    """Reach › Free trial links chart: {<series>: {chart, total, delta}}."""
    return _proxy(lambda: _get_client().trials_chart(start=start, end=end))

@router.get("/api/of/v2/campaigns/chart")
def of_campaigns_chart(start: str | None = Query(None), end: str | None = Query(None)):
    """Reach › Tracking links chart: {clicks: {chart, total, delta}, claims: {...}}."""
    return _proxy(lambda: _get_client().campaigns_chart(start=start, end=end))

@router.get("/api/of/v2/stories/chart")
def of_stories_chart(by: str = Query("tips", pattern="^(tips|views|likes|comments)$"),
                     start: str | None = Query(None), end: str | None = Query(None)):
    """Engagement › Stories chart for one tab: {<by>|stories: {chart, total, delta}}."""
    return _proxy(lambda: _get_client().stories_chart(by=by, start=start, end=end))

@router.get("/api/of/v2/streams/chart")
def of_streams_chart(by: str = Query("purchases", pattern="^(purchases|tips|views|likes|comments)$"),
                     start: str | None = Query(None), end: str | None = Query(None)):
    """Engagement › Streaming chart for one tab: {<by>|duration: {chart, total, delta}}."""
    return _proxy(lambda: _get_client().streams_chart(by=by, start=start, end=end))

# The stream / story stats popup's Viewers and Tippers lists. The id rides in the
# query (as on /messages/queue/buyers) so the permission map can give these reads
# to Statistics: `/streams/{id}/...` and `/stories/{id}/...` could only be mapped
# through `/streams` and `/stories`, which are Go live's and Home's / New post's.
@router.get("/api/of/v2/streams/viewers")
def of_stream_viewers(stream_id: int = Query(..., ge=1), limit: int = Query(10, ge=1, le=50),
                      offset: int = Query(0, ge=0),
                      tips_only: int = Query(0, ge=0, le=1, description="1 = the Tippers tab")):
    """OF's /streams/{stream_id}/viewers: {list:[user], hasMore?}."""
    return _proxy(lambda: _get_client().stream_viewers(
        stream_id, limit=limit, offset=offset, tips_only=bool(tips_only)))

@router.get("/api/of/v2/stories/viewers")
def of_story_viewers(story_id: int = Query(..., ge=1), limit: int = Query(10, ge=1, le=50),
                     offset: int = Query(0, ge=0),
                     tips_only: int = Query(0, ge=0, le=1, description="1 = the Tippers tab")):
    """OF's /stories/{story_id}/viewers: {list:[user], hasMore?}."""
    return _proxy(lambda: _get_client().story_viewers(
        story_id, limit=limit, offset=offset, tips_only=bool(tips_only)))


@router.get("/api/of/v2/payouts/download-approved-invoice")
def of_payout_invoice(invoiceId: int = Query(..., ge=1),
                      isRefbonus: int = Query(0, ge=0, le=1, description="1 = a referral payout")):
    """An approved payout request's invoice, as OF's Download invoice link
    fetches it. OF answers 200 application/pdf with an attachment
    Content-Disposition (confirmed live); that PDF and OF's file name come back
    as sent. Anything else is a 502 carrying only OF's status code: the upstream
    URL is never logged nor returned."""
    r = _proxy(lambda: _get_client().payout_invoice(invoiceId, referral=bool(isRefbonus)))
    if not r.ok or "application/pdf" not in (r.headers.get("content-type") or "").lower():
        log.warning("payout invoice download failed: upstream %s, not a PDF", r.status_code)
        raise HTTPException(status_code=502, detail={"upstream_status": r.status_code})
    return Response(content=r.content, media_type="application/pdf", headers={
        "Cache-Control": "no-store",
        "Content-Disposition": r.headers.get("content-disposition") or "attachment"})

@router.get("/api/of/v2/users/me/referrals")
def of_my_referrals(onlyPerformers: int = Query(0, ge=0, le=1,
                                                description="1 = Referred creators, 0 = Referred users"),
                    start: str | None = Query(None), end: str | None = Query(None),
                    offset: int = Query(0, ge=0), marker: str | None = Query(None, max_length=64)):
    """Statements › Referrals › Referred creators / Referred users: {list, hasMore}."""
    return _proxy(lambda: _get_client().referrals(
        start=start, end=end, offset=offset, marker=marker, only_performers=bool(onlyPerformers)))

# ── Bookmarks (Collections → Bookmarks tab) ────────────────────────

@router.get("/api/of/v2/posts/bookmarks/all")
def of_bookmarks_all(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Paginated bookmarks feed (the OF UI tab)."""
    return _proxy(lambda: _get_client().bookmarks_all(limit=limit, offset=offset))


# ── Referrals ──────────────────────────────────────────────────────

@router.get("/api/of/v2/payments/referrals/balance")
def of_referrals_balance():
    """Referral earnings balance."""
    return _proxy(lambda: _get_client().referrals_balance())

@router.get("/api/of/v2/payouts/requests/referral")
@_account_ttl("payouts", 60)
def of_referral_payouts(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0),
                        start: str | None = Query(None, max_length=32), end: str | None = Query(None, max_length=32),
                        marker: str | None = Query(None, max_length=64)):
    """Referral payout history, paged as /payouts/requests (start, end, marker)."""
    return _proxy(lambda: _get_client().referral_payouts(
        limit=limit, offset=offset, start=start, end=end, marker=marker))

# ── Notification transports (Settings > Notifications, read-only) ──


@router.get("/api/of/v2/users/settings/notifications/{transport}")
def of_notification_settings(transport: str, group: int | None = Query(None)):
    """One transport's notification toggles (read-only); `group=1` passes through."""
    if transport not in ("email", "message", "toast", "webpush", "sms", "telegram"):
        raise HTTPException(status_code=404, detail="unknown notification transport")
    return _proxy(lambda: _get_client().notification_settings(transport, group=group))
