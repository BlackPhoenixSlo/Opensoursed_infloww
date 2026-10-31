"""
stats_fans.py — Fan reports' reads, split out of stats.py.

  GET /admin/stats/per-fan-data     → per-fan profile data (Fan reports → User
                                       data), read from our DB
  GET /admin/stats/fan-report       → Top fans, Traffic source and New fans over
                                       a window (JSON, or the ranking as CSV)

`new_subs_q` (new subs, each fan once) is per-model's too (stats_per_model.py).
stats.py includes this router where these routes stood (route order). The
report zone is read as `stats._report_zone` at call time (imported in the
route, no import-time cycle), so a patch on `stats` reaches these routes as
before the split.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, column, func, literal_column, or_, select, text
from sqlalchemy.orm import aliased

import csv_export
import tx_rollup
from attribution_backfill import PPV_KINDS, TIP_KINDS, TRACKED_STATUSES
from auth import clamp_account_filter
from db.engine import get_session
from db.models import Fan, LinkClaimer, LinkMeta, PromoCampaign, SubscriberSnapshot, Transaction, TrialLinkMirror
from stats_window import parse_date as _parse_date, scope_ids, stats_guard

router = APIRouter(dependencies=[Depends(stats_guard)])


@router.get("/admin/stats/per-fan-data")
async def per_fan_data(
    account_id: str | None = Query(None),
    limit: int = Query(2000, ge=1, le=5000),
) -> dict[str, Any]:
    """Per-fan profile data (Fan reports → User data), read from our DB. One
    account at a time (the UI picks one); with no account_id, every account the
    principal owns. Owner-gated via clamp_account_filter."""
    from fan_data import _HEADER, build_fan_data

    account_ids = clamp_account_filter(account_id)
    rows: list[dict] = []
    for aid in (account_ids or []):
        rows.extend(await build_fan_data(aid, limit))
    # Spend-desc so the highest-value fans surface first.
    rows.sort(key=lambda r: r.get("total_spend") or 0, reverse=True)
    return {"rows": rows, "count": len(rows), "columns": list(_HEADER)}


def new_subs_q(account_ids: list[str] | None, start: datetime, end: datetime) -> Any:
    """New subs in the window: each fan whose subscription began in it, by a
    subscription sale (pending too, so a sub that fires today shows at once;
    a chargeback flips the row's status and drops it) or by OF's own roster
    (`subscriber_snapshot.subscribe_at`), which also lists free and trial
    subscribers, who leave no sale (roadmap S6). The roster holds the
    subscriptions active at its last crawl, so a free sub that has since
    lapsed is not counted. One row per (account_id, fan_id), `at` his first
    start in the window; per-model counts them, Fan reports buckets them."""
    b = tx_rollup.Binds()
    acct_in = "" if account_ids is None else " AND " + b.in_("account_id", account_ids)
    s_, e_ = b.bind(start.strftime(tx_rollup.TS_FORMAT)), b.bind(end.strftime(tx_rollup.TS_FORMAT))
    return text(
        "SELECT account_id, fan_id, MIN(at) AS at FROM ("
        "SELECT account_id, fan_id, occurred_at AS at FROM transactions WHERE kind = 'subscription' "
        f"AND fan_id IS NOT NULL AND {b.in_('status', TRACKED_STATUSES)} "
        f"AND occurred_at >= {s_} AND occurred_at <= {e_}{acct_in} "
        "UNION ALL SELECT account_id, fan_id, subscribe_at AS at FROM subscriber_snapshot "
        f"WHERE subscribe_at >= {s_} AND subscribe_at <= {e_}{acct_in}) GROUP BY account_id, fan_id"
    ).bindparams(**b).columns(column("account_id"), column("fan_id"), column("at"))


# ── Fan reports: Top fans, Traffic source, New fans (roadmap W5 5.6) ───

FAN_REPORT_FIELDS = ("account_id", "fan_id", "fan_name", "username", "total_cents", "net_or_80_cents",
                     "tips_cents", "ppv_cents", "subs_cents", "subscribed_at")
_FAN_SORTS = {"total": "total_cents", "tips": "tips_cents", "ppv": "ppv_cents", "subs": "subs_cents"}


@router.get("/admin/stats/fan-report", response_model=None)
async def fan_report(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    account_id: str | None = Query(None),
    sort: str = Query("total", pattern="^(total|tips|ppv|subs)$"),
    limit: int = Query(100, ge=1, le=5000),
    format: str = Query("json", pattern="^(json|csv)$"),
) -> dict[str, Any] | StreamingResponse:
    """Fan reports over the window (default the last 30 days), for the
    caller's Creators or the ones named (`account_id`, comma list):

      top_fans  each fan's spend in the window (every kind, cleared and
                pending, as per-model's revenue): total, net (OnlyFans' net,
                else 80% of gross, the reports' `net_or_80` basis), tips, PPV
                and subscriptions; ranked by `sort`, `limit` rows.
                `subscribed_at` is his current subscription's start on OF's
                roster (`subscriber_snapshot`), Subscription length's basis;
                null for a fan the roster never listed.
      traffic   the window's spend by the free trial link or promotion each
                spender claimed (`link_claimers`; a fan under several counts
                under his earliest claim: OF's subscribe_at, else when we first
                saw it), the rest as kind null.
                Tracking links' claimers are read live from OF and never
                stored (of_tracking_api), so they are not a source here.
      growth    per day of the report zone: `new_fans`, the fans whose
                subscription began (a subscription sale or the roster's
                `subscribe_at`, each fan once, on his first day; per-model's
                new subs), and `renewed_fans`, the fans with a rebill.

    `format=csv` streams the whole top_fans ranking instead, `limit` aside,
    under the shared CSV cap (csv_export.CSV_MAX_ROWS).

    ASSUMPTION: no Total fans growth line: nothing stores the subscriber
    count per day (the roster is a current list), and rebuilding it from
    the roster would miss every fan who left before its first crawl. Rung 4.
    Overturned once a daily subscriber snapshot is kept (roadmap 5.5)."""
    import stats
    account_ids, zone_account = scope_ids(account_id)
    zone = await stats._report_zone(zone_account)
    start = _parse_date(from_, field="from", zone=zone) if from_ else datetime.utcnow() - timedelta(days=30)
    end = _parse_date(to, field="to", zone=zone) if to else datetime.utcnow()

    T = Transaction
    scope = [T.status.in_(TRACKED_STATUSES), T.fan_id.is_not(None), T.occurred_at >= start, T.occurred_at <= end]
    if account_ids is not None:
        scope.append(T.account_id.in_(account_ids))

    def _sum_if(cond: Any) -> Any:
        return func.coalesce(func.sum(case((cond, T.amount_cents), else_=0)), 0)

    spend = (
        select(
            T.account_id, T.fan_id,
            func.sum(T.amount_cents).label("total_cents"),
            literal_column(tx_rollup.MEASURES["net_or_80_cents"][1]).label("net_or_80_cents"),
            _sum_if(T.kind.in_(TIP_KINDS)).label("tips_cents"),
            _sum_if(T.kind.in_(PPV_KINDS)).label("ppv_cents"),
            _sum_if(T.kind.in_(("subscription", "rebill"))).label("subs_cents"),
        )
        .where(*scope)
        .group_by(T.account_id, T.fan_id)
        .subquery()
    )
    top_q = (
        select(spend, Fan.of_display_name, Fan.of_username, SubscriberSnapshot.subscribe_at)
        .outerjoin(Fan, and_(Fan.account_id == spend.c.account_id, Fan.fan_id == spend.c.fan_id))
        .outerjoin(SubscriberSnapshot, and_(SubscriberSnapshot.account_id == spend.c.account_id,
                                            SubscriberSnapshot.fan_id == spend.c.fan_id))
        .order_by(spend.c[_FAN_SORTS[sort]].desc(), spend.c.total_cents.desc(), spend.c.fan_id)
    )

    def _fan(r: Any) -> dict[str, Any]:
        return {
            "account_id": r.account_id, "fan_id": int(r.fan_id),
            "fan_name": r.of_display_name, "username": r.of_username,
            "total_cents": int(r.total_cents or 0), "net_or_80_cents": int(r.net_or_80_cents or 0),
            "tips_cents": int(r.tips_cents or 0), "ppv_cents": int(r.ppv_cents or 0),
            "subs_cents": int(r.subs_cents or 0),
            "subscribed_at": r.subscribe_at.isoformat() if r.subscribe_at else None,
        }

    if format == "csv":
        async def _rows(s):
            async for r in csv_export.query_rows(s, top_q):
                yield _fan(r)

        safe = csv_export.safe_filename_part
        return csv_export.download(
            f"top-fans_{safe(from_, 'start')}_to_{safe(to, 'now')}.csv", _rows, FAN_REPORT_FIELDS,
            lambda rec: ["" if rec[k] is None else rec[k] for k in FAN_REPORT_FIELDS],
        )

    # Each fan's earliest claim, then the window's spend by that link.
    LC = LinkClaimer
    ranked = select(LC.id, LC.account_id, LC.fan_id, func.row_number().over(
        partition_by=(LC.account_id, LC.fan_id),
        order_by=(func.coalesce(LC.subscribe_at, LC.first_seen_at), LC.id)).label("n"))
    if account_ids is not None:
        ranked = ranked.where(LC.account_id.in_(account_ids))
    ranked = ranked.subquery()
    first_claim = (
        select(ranked.c.account_id, ranked.c.fan_id, ranked.c.id.label("cid"))
        .where(ranked.c.n == 1)
        .subquery()
    )
    claim = aliased(LinkClaimer)
    traffic_q = (
        select(spend.c.account_id, claim.kind, claim.of_id,
               func.count().label("fans"), func.sum(spend.c.total_cents).label("total_cents"))
        .select_from(spend)
        .outerjoin(first_claim, and_(first_claim.c.account_id == spend.c.account_id,
                                     first_claim.c.fan_id == spend.c.fan_id))
        .outerjoin(claim, claim.id == first_claim.c.cid)
        .group_by(spend.c.account_id, claim.kind, claim.of_id)
        .order_by(func.sum(spend.c.total_cents).desc())
    )

    new_q = new_subs_q(account_ids, start, end)  # each fan on his first day in the window
    renew_q = (
        select(T.account_id, T.fan_id, T.occurred_at)
        .where(*scope, T.kind == "rebill")
    )

    async with get_session() as s:
        top = [_fan(r) for r in (await s.execute(top_q.limit(limit))).all()]
        traffic_rows = (await s.execute(traffic_q)).all()
        new_rows = (await s.execute(new_q)).all()
        renew_rows = (await s.execute(renew_q)).all()
        traffic = await _link_names(s, traffic_rows)

    def _day(at: Any) -> str:
        if isinstance(at, str):  # the text() union hands back SQLite's stored string
            at = datetime.fromisoformat(at)
        if zone is not None:
            at = at.replace(tzinfo=timezone.utc).astimezone(zone)
        return at.date().isoformat()

    growth: dict[str, dict[str, Any]] = {}

    def _bump(day: str, key: str) -> None:
        growth.setdefault(day, {"day": day, "new_fans": 0, "renewed_fans": 0})[key] += 1

    for r in new_rows:
        _bump(_day(r.at), "new_fans")
    # A fan billed twice in a day (a re-sub after a chargeback) renewed once.
    for day, _aid, _fid in {(_day(r.occurred_at), r.account_id, r.fan_id) for r in renew_rows}:
        _bump(day, "renewed_fans")

    return {"top_fans": top, "traffic": traffic, "growth": sorted(growth.values(), key=lambda g: g["day"])}


async def _link_names(s, rows: list[Any]) -> list[dict[str, Any]]:
    """Traffic rows named: a trial link by its mirror, a promotion by its
    campaign (through `link_meta.campaign_id`, which a re-armed promotion's
    earlier OF ids keep, else the campaign's current OF id), and the link's
    Source as the operator typed it."""
    keys = {(r.account_id, r.kind, int(r.of_id)) for r in rows if r.kind}
    trials: dict[tuple[str, int], str] = {}
    promos: dict[tuple[str, int], str] = {}
    metas: dict[tuple[str, str, int], Any] = {}
    if keys:
        aids = {k[0] for k in keys}
        ids = {k[2] for k in keys}
        for t in (await s.execute(select(TrialLinkMirror).where(
                TrialLinkMirror.account_id.in_(aids), TrialLinkMirror.of_trial_id.in_(ids)))).scalars():
            trials[(t.account_id, int(t.of_trial_id))] = t.name
        for m in (await s.execute(select(LinkMeta).where(
                LinkMeta.account_id.in_(aids), LinkMeta.of_id.in_(ids)))).scalars():
            metas[(m.account_id, m.kind, int(m.of_id))] = m
        camp_ids = {m.campaign_id for m in metas.values() if m.campaign_id}
        campaigns = (await s.execute(select(PromoCampaign).where(
            PromoCampaign.account_id.in_(aids),
            or_(PromoCampaign.of_promo_id.in_(ids), PromoCampaign.id.in_(camp_ids))))).scalars().all()
        by_id = {p.id: p.name for p in campaigns}
        promos = {(p.account_id, int(p.of_promo_id)): p.name for p in campaigns if p.of_promo_id is not None}
        for (aid, kind, of_id), m in metas.items():
            if kind == "promo" and m.campaign_id in by_id:
                promos[(aid, of_id)] = by_id[m.campaign_id]
    out = []
    for r in rows:
        of_id = int(r.of_id) if r.kind else None
        meta = metas.get((r.account_id, r.kind, of_id)) if r.kind else None
        names = trials if r.kind == "trial" else promos
        out.append({
            "account_id": r.account_id, "kind": r.kind, "of_id": of_id,
            "name": names.get((r.account_id, of_id)) if r.kind else None,
            "source": meta.source if meta is not None else None,
            "fans": int(r.fans or 0), "total_cents": int(r.total_cents or 0),
        })
    return out
