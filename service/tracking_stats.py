"""Bounded raw click stats for redirect links.

900-second UTC buckets fold into exact report-zone days, including half/quarter
hour offsets and DST boundaries. NULL ref means unclassified old rows; the boot
job rescans those rows without a marker, in resumable chunks.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
import admission
from auth import assert_account_owned
from db.engine import get_session
from click_classify import in_app, ref_family

log = logging.getLogger("of-relay.tracking_stats")
router = APIRouter()
RANGES = (7, 30, 90)
BUCKET_S = 900


def utcnow() -> datetime:
    """Shared click write and report clock."""
    return datetime.now(timezone.utc)


def _days(zone: ZoneInfo | None, n: int) -> tuple[list[date], str, str]:
    tz = zone or timezone.utc
    today = utcnow().astimezone(tz).date()
    days = [today - timedelta(days=n - 1 - i) for i in range(n)]
    lo = datetime.combine(days[0], dtime(), tzinfo=tz).astimezone(timezone.utc)
    hi = datetime.combine(today + timedelta(days=1), dtime(), tzinfo=tz).astimezone(timezone.utc)
    return days, lo.strftime("%Y-%m-%d %H:%M:%S"), hi.strftime("%Y-%m-%d %H:%M:%S")


def _day(bucket: int, zone: ZoneInfo | None) -> str:
    return datetime.fromtimestamp(bucket * BUCKET_S, timezone.utc).astimezone(zone or timezone.utc).date().isoformat()


def _series(days: list[date]) -> dict[str, int]:
    return {day.isoformat(): 0 for day in days}


def _rank(counter: Counter) -> list[dict]:
    return [{"key": k, "clicks": n} for k, n in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


@router.get("/admin/tracking-links/summary")
async def tracking_links_summary(account_id: str = Query(...)) -> dict[str, Any]:
    import stats
    assert_account_owned(account_id)
    zone = await stats._report_zone(account_id)
    days, lo, hi = _days(zone, 30)
    async with admission.TRACKING_STATS_READ, get_session() as s:
        links = (await s.execute(text("SELECT id, name FROM tracking_links WHERE account_id=:aid"),
                                 {"aid": account_id})).all()
        rows = (await s.execute(text("SELECT c.tracking_link_id AS lid, unixepoch(c.clicked_at)/:bucket_s AS bucket, "
                                     "COUNT(*) AS n, SUM(CASE WHEN c.verified THEN 1 ELSE 0 END) AS verified FROM tracking_clicks c JOIN tracking_links l ON l.id=c.tracking_link_id "
                                     "WHERE l.account_id=:aid AND c.clicked_at>=:lo AND c.clicked_at<:hi "
                                     "GROUP BY c.tracking_link_id, bucket"),
                                {"aid": account_id, "lo": lo, "hi": hi, "bucket_s": BUCKET_S})).all()
    by_link = {lid: _series(days) for lid, _ in links}
    verified = 0
    for lid, bucket, n, passed in rows:
        if lid in by_link:
            by_link[lid][_day(bucket, zone)] += n
            verified += passed
    total = _series(days)
    for series in by_link.values():
        for day, n in series.items():
            total[day] += n
    ranked = sorted(((lid, name, sum(by_link[lid].values())) for lid, name in links),
                    key=lambda item: (-item[2], item[1], item[0]))
    top = ranked[0] if ranked and ranked[0][2] else None
    return {"tz": zone.key if zone else None, "today": days[-1].isoformat(),
            "clicks": {"today": total[days[-1].isoformat()], "d7": sum(total[day.isoformat()] for day in days[-7:]),
                       "d30": sum(total.values())},
            "top": {"id": top[0], "name": top[1], "clicks": top[2]} if top else None,
            "spark": {str(lid): [by_link[lid][day.isoformat()] for day in days[-7:]] for lid, _ in links},
            "verified_clicks": verified}


@router.get("/admin/tracking-links/{link_id}/analytics")
async def tracking_link_analytics(link_id: int, account_id: str = Query(...), days: int = Query(30)) -> dict[str, Any]:
    import stats
    if days not in RANGES:
        raise HTTPException(422, f"days must be one of {', '.join(map(str, RANGES))}")
    assert_account_owned(account_id)
    zone = await stats._report_zone(account_id)
    ds, lo, hi = _days(zone, days)
    async with admission.TRACKING_STATS_READ, get_session() as s:
        owner = (await s.execute(text("SELECT account_id FROM tracking_links WHERE id=:lid"), {"lid": link_id})).scalar()
        if owner != account_id:
            raise HTTPException(404, "tracking link not found")
        where = "WHERE tracking_link_id=:lid AND clicked_at>=:lo AND clicked_at<:hi "
        # One statement = one snapshot: series total == breakdown sums (STATS_BREAKDOWN).
        rows = (await s.execute(text("SELECT 'series' AS kind, unixepoch(clicked_at)/:bucket_s AS bucket, "
                                     "NULL AS country, NULL AS in_app, NULL AS ref, COUNT(*) AS n, "
                                     "SUM(verified) AS passed FROM tracking_clicks " + where + "GROUP BY bucket "
                                     "UNION ALL SELECT 'dims', NULL, country, in_app, ref, COUNT(*), NULL FROM tracking_clicks "
                                     + where + "GROUP BY country, in_app, ref"),
                                {"lid": link_id, "lo": lo, "hi": hi, "bucket_s": BUCKET_S})).all()
    series = _series(ds)
    dims: dict[str, Counter] = {"in_app": Counter(), "ref": Counter(), "country": Counter()}
    verified = 0
    for kind, bucket, country, app, ref, n, passed in rows:
        if kind == "series":
            series[_day(bucket, zone)] += n
            verified += passed
        else:
            dims["in_app"][app or ""] += n
            dims["ref"][ref or ""] += n
            dims["country"][country or "XX"] += n
    total = sum(series.values())
    return {"tz": zone.key if zone else None, "from": ds[0].isoformat(), "to": ds[-1].isoformat(),
            "days": days, "series": [{"day": day, "clicks": n} for day, n in series.items()],
            "totals": {"clicks": total, "verified_clicks": verified}, "opened_in": _rank(dims["in_app"]),
            "came_from": _rank(dims["ref"]), "country": _rank(dims["country"])}


def _classify_chunk(engine, last: int, chunk: int) -> tuple[int, int, int, Exception | None]:
    """Classify before acquiring the write lock; commit one idempotent chunk."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, user_agent, referer FROM tracking_clicks "
                                 "WHERE ref IS NULL AND id>:last ORDER BY id LIMIT :chunk"),
                            {"last": last, "chunk": chunk}).all()
    if not rows:
        return last, 0, 0, None
    updates = []
    failures = 0
    first_error = None
    for rid, ua, ref in rows:
        try:
            app, family = in_app(ua), ref_family(ref)
        except Exception as exc:
            failures += 1
            if first_error is None:
                first_error = exc
            app, family = "", "other" if ref else ""
        updates.append({"id": rid, "app": app, "ref": family})
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            conn.execute(text("UPDATE tracking_clicks SET in_app=:app, ref=:ref WHERE id=:id AND ref IS NULL"), updates)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return rows[-1][0], len(rows), failures, first_error


async def classify_old_rows_background(sync_url: str, chunk: int = 2_000) -> int:
    from sqlalchemy import create_engine
    engine = create_engine(sync_url, connect_args={"timeout": 30})
    started = time.monotonic()
    done = last = 0
    row_failures = 0
    failed = False
    delay = 1
    cancelled = False
    try:
        while True:
            try:
                pending = asyncio.create_task(asyncio.to_thread(_classify_chunk, engine, last, chunk))
                try:
                    last, n, failures, first_error = await asyncio.shield(pending)
                except asyncio.CancelledError:
                    cancelled = True
                    try:
                        last, n, failures, first_error = await pending  # finish transaction before disposing engine
                    except Exception:
                        pass
                    else:
                        done += n
                        row_failures += failures
                        if first_error is not None and row_failures == failures:
                            log.error("tracking old click classify failed; storing fallback labels",
                                      exc_info=(type(first_error), first_error, first_error.__traceback__))
                    raise
            except Exception:
                if not failed:
                    log.exception("tracking old clicks classification failed after %d rows; retrying", done)
                failed = True
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)
                continue
            failed = False
            delay = 1
            row_failures += failures
            if first_error is not None and row_failures == failures:
                log.error("tracking old click classify failed; storing fallback labels",
                          exc_info=(type(first_error), first_error, first_error.__traceback__))
            if not n:
                break
            done += n
            await asyncio.sleep(0.01)
        return done
    except asyncio.CancelledError:
        cancelled = True
        raise
    finally:
        engine.dispose()
        log.info("tracking old clicks %s: %d rows in %.2fs; %d row classifier failures",
                 "cancelled" if cancelled else "classified", done, time.monotonic() - started, row_failures)
