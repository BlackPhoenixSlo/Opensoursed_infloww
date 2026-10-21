"""of_stats_daily — OnlyFans Statistics figures kept per Creator per UTC day
(roadmap W5 5.5; 05-analytics B4, M12, W3).

OnlyFans answers its Statistics charts live, for the window asked, and keeps
no history we can query later; Creator reports need any window. So once a day
per Creator this job reads the last `_DAYS` complete UTC days of three charts
and stores each day (`of_stats_daily`), and the reports sum the stored days.

  visitors   GET /users/me/profile/stats          chart.visitors[]
  new_subs   GET /subscriptions/subscribers/chart  subscribes[], by=new
  renewals   GET /subscriptions/subscribers/chart  subscribes[], by=renew

Reads only, through the pooled OFClient (`client_pool`), whose single
`_http_call` path refuses denied calls and retries proxy blips; a pause between
calls. Creators whose session is flagged dead (account_health) are skipped, and
a fetch that fails on a dead session flags it. A Creator's fetches for a day
are capped (`_MAX_ATTEMPTS`, `_RETRY_AFTER_S` apart), counted on the day's row
so a restart does not reset them.
Response shapes: service/tests/fixtures/of_statistics_reads.json.
ASSUMPTION: `by=new` / `by=renew` answer the same shape as the recorded reply
without `by` (OF's own Fans > Subscriptions tabs send them and read it so,
of_client.subscribers_chart); the shape check below drops a series that does not.
Rung 4. Overturned by a live capture of either.

Each fetch re-reads the last `_DAYS` days, so a missed day heals on the next
run, and writes only complete days (before today, UTC): a day OF is still
counting is never stored. A series whose points are not one per consecutive
day (a reply in another shape, or bucketed by week) is not stored at all.

`active_fans` / `renew_on` come from no OF call: each tick samples the Smart
Messages roster (`subscriber_snapshot`, automations/lifecycle_messages) at its
latest complete crawl into that crawl's UTC day, so a day's row holds the last
crawl of it. The roster is only crawled while a lifecycle Trigger runs; without
one these stay NULL. `renew_on` is NULL when any listed fan's status is unknown.

Not here, for want of a recorded reply or a client method: OF ranking,
Following, guest / user visitors (Reach's `by=guests|users`), total and expired
fans (`/subscriptions/count/all`), average subscription length.

`window_figures` is the read: per Creator, each sum only when every day of the
window through yesterday is stored, else absent ("-"), never a partial sum.
`new_subs` is read there only for the New subscriber conversion (OF's new
subscribers over its visitors, both OF's own); the New subscribers column
stays ours (stats.per_model `new_subs_count`).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import account_health
import accounts as account_registry
import client_pool
import tx_rollup
from cadence import boot_grace
from db.engine import get_session
from db.models import OfStatsDaily, SubscriberSnapshot

log = logging.getLogger("of-relay.of_stats_daily")

_DAYS = 7                 # complete days each fetch re-reads
_TICK_S = 3600            # how often the loop looks for a Creator due a fetch
_CALL_PAUSE_S = 2.0       # between two OF reads, and between two Creators
_RETRY_AFTER_S = 6 * 3600 # between two fetches for a day not yet stored
_MAX_ATTEMPTS = 3         # fetches per Creator per day, at most
_BOOT_GRACE_S = 300.0
SERIES = ("visitors", "new_subs", "renewals")


def _points(series: Any, first: date, last: date) -> dict[str, int] | None:
    """`[{date, count}]` as {UTC day: count} for the days in [first, last], or
    None when it is not one point per consecutive day with a whole count."""
    if not isinstance(series, list):
        return None
    days: list[date] = []
    out: dict[str, int] = {}
    for p in series:
        try:
            at = datetime.fromisoformat(str(p["date"]).replace("Z", "+00:00"))
            n = p["count"]
        except (KeyError, TypeError, ValueError):
            return None
        if isinstance(n, bool) or not isinstance(n, (int, float)) or n != int(n) or n < 0:
            return None
        days.append(at.date())
        if first <= at.date() <= last:
            out[at.date().isoformat()] = int(n)
    if any((b - a).days != 1 for a, b in zip(days, days[1:])):
        return None
    return out


def fetch_blocking(client, first: date, last: date, *, pause_s: float = _CALL_PAUSE_S) -> dict[str, dict[str, int]]:
    """The three charts over [first, last] as {series: {day: count}}, without the
    series that answered in an unexpected shape. Blocking: run in a thread.
    Raises what the client raises (a dead session, a proxy outage)."""
    # UNVERIFIED: which zone OF reads startDate / endDate in, and cuts its
    # points' days in. They are sent as UTC days, and each point is stored
    # under the date OF stamps on it.
    start, end = f"{first.isoformat()} 00:00:00", f"{last.isoformat()} 23:59:59"
    out: dict[str, dict[str, int]] = {}
    visitors = client.my_profile_stats(start=start, end=end)
    chart = visitors.get("chart") if isinstance(visitors, dict) else None
    if (pts := _points(chart.get("visitors") if isinstance(chart, dict) else None, first, last)) is not None:
        out["visitors"] = pts
    for col, by in (("new_subs", "new"), ("renewals", "renew")):
        time.sleep(pause_s)
        reply = client.subscribers_chart(start=start, end=end, by=by)
        if (pts := _points(reply.get("subscribes") if isinstance(reply, dict) else None, first, last)) is not None:
            out[col] = pts
    for col in SERIES:
        if col not in out:
            log.warning("of_stats_daily: %s answered in an unexpected shape; not stored", col)
    return out


async def _upsert(account_id: str, cols: dict[str, dict[str, int]], now: datetime) -> int:
    """Write each day's figures for the series in `cols`, leaving the row's other
    columns as they are. Returns the days written."""
    days = sorted({d for pts in cols.values() for d in pts})
    async with get_session() as s:
        for day in days:
            values = {c: pts[day] for c, pts in cols.items() if day in pts}
            stmt = sqlite_insert(OfStatsDaily).values(account_id=account_id, day=day, fetched_at=now, **values)
            await s.execute(stmt.on_conflict_do_update(
                index_elements=["account_id", "day"],
                set_={**{c: stmt.excluded[c] for c in values}, "fetched_at": now}))
        await s.commit()
    return len(days)


async def snapshot(account_id: str, client, *, now: datetime | None = None,
                   pause_s: float = _CALL_PAUSE_S) -> int:
    """Fetch the last `_DAYS` complete UTC days for one Creator and store them.
    Returns the days written."""
    now = now or datetime.utcnow()
    last = now.date() - timedelta(days=1)
    cols = await asyncio.to_thread(fetch_blocking, client, last - timedelta(days=_DAYS - 1), last, pause_s=pause_s)
    return await _upsert(account_id, cols, now) if cols else 0


async def sample_roster(account_id: str, *, now: datetime | None = None) -> bool:
    """Store the roster's latest complete crawl (`subscriber_snapshot`) as its
    UTC day's active fans and renew-on count. No OF call. False with no crawl."""
    now = now or datetime.utcnow()
    S = SubscriberSnapshot
    async with get_session() as s:
        last = (await s.execute(select(func.max(S.seen_at)).where(S.account_id == account_id))).scalar()
        if last is None:
            return False
        # Cast: a SUM over the Boolean column would come back as a Boolean.
        active, known, on = (await s.execute(
            select(func.count(), func.count(S.renew_on), func.sum(cast(S.renew_on, Integer)))
            .where(S.account_id == account_id, S.seen_at == last))).one()
        values = {"active_fans": int(active), "renew_on": int(on or 0) if known == active else None}
        stmt = sqlite_insert(OfStatsDaily).values(
            account_id=account_id, day=last.date().isoformat(), fetched_at=now, **values)
        await s.execute(stmt.on_conflict_do_update(
            index_elements=["account_id", "day"], set_={**values, "fetched_at": now}))
        await s.commit()
    return True


async def _claim(account_id: str, now: datetime) -> bool:
    """Count a fetch against yesterday's row when one is due: no OF figure is
    stored for yesterday yet (only a fetch after it ended writes one), fewer
    than `_MAX_ATTEMPTS` were tried, the last over `_RETRY_AFTER_S` ago. On the
    row, so the cap holds across restarts and a reply OF answers in a shape we
    drop is not re-asked every tick."""
    yesterday = (now.date() - timedelta(days=1)).isoformat()
    async with get_session() as s:
        row = await s.get(OfStatsDaily, (account_id, yesterday))
        if row is None:
            s.add(OfStatsDaily(account_id=account_id, day=yesterday, fetched_at=now, attempts=1, attempted_at=now))
        elif (any(getattr(row, c) is not None for c in SERIES) or row.attempts >= _MAX_ATTEMPTS
              or (row.attempted_at is not None and (now - row.attempted_at).total_seconds() < _RETRY_AFTER_S)):
            return False
        else:
            row.attempts += 1
            row.attempted_at = now
        await s.commit()
    return True


async def tick(*, now: datetime | None = None, pause_s: float = _CALL_PAUSE_S) -> dict[str, int]:
    """One pass over the OnlyFans Creators with a live session: sample each
    roster, and fetch the Creators due (never a deactivated one). Returns
    {account_id: days written} for those."""
    now = now or datetime.utcnow()
    done: dict[str, int] = {}
    for meta in account_registry.list_accounts():
        aid = meta.get("id")
        if not aid or not meta.get("has_session") or account_registry.get_platform(aid) == "fansly":
            continue
        try:
            await sample_roster(aid, now=now)
            if (await account_health.is_session_dead(aid) or await account_health.is_deactivated(aid)
                    or not await _claim(aid, now)):
                continue
            client = await asyncio.to_thread(client_pool.get, aid)
            done[aid] = await snapshot(aid, client, now=now, pause_s=pause_s)
            await asyncio.sleep(pause_s)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if reason := account_health.is_session_dead_error(e):
                await account_health.mark_session_dead(aid, reason)
                log.warning("of_stats_daily: session dead account=%s (%s); skipped until it is back", aid, reason)
            else:
                log.warning("of_stats_daily: fetch failed account=%s; at most %d tries a day, %ds apart",
                            aid, _MAX_ATTEMPTS, _RETRY_AFTER_S, exc_info=True)
    return done


async def run_loop() -> None:
    """The background loop (server startup): `tick` every `_TICK_S`, so each
    Creator is fetched once a day, soon after UTC midnight."""
    await boot_grace(_BOOT_GRACE_S, name="of-stats-daily")
    while True:
        try:
            done = await tick()
            if done:
                log.info("of_stats_daily: stored %s", done)
        except asyncio.CancelledError:
            return
        except Exception:
            log.warning("of_stats_daily tick failed", exc_info=True)
        await asyncio.sleep(_TICK_S)


# ── Reading ──────────────────────────────────────────────────────────────

def window_days(start: datetime, end: datetime) -> tuple[date, date]:
    """The UTC days a report window names: its edges rounded to the nearest
    UTC midnight. A window cut at local midnights (Creator reports' range in
    the report time zone) names the same calendar days as its local ones, for
    any zone within 12 hours of UTC: these columns count OF's UTC days (their
    "UTC+00:00" chip)."""
    lo = (start + timedelta(hours=12)).date()
    hi = (end + timedelta(microseconds=1) + timedelta(hours=12)).date() - timedelta(days=1)
    return lo, hi


async def window_figures(account_ids: list[str] | None, start: datetime, end: datetime, *,
                         now: datetime | None = None) -> dict[str, dict[str, Any]]:
    """{account_id: the figures we have} over the window's UTC days through
    yesterday (the last complete one): of_visitors and of_renewals when every
    one of those days is stored, of_new_sub_conversion_pct when both of its
    series are, and of_renew_on / of_renew_on_pct at the last of them."""
    lo, hi = window_days(start, end)
    hi = min(hi, (now or datetime.utcnow()).date() - timedelta(days=1))
    if lo > hi:
        return {}
    days = (hi - lo).days + 1
    b = tx_rollup.Binds()
    lo_, hi_ = b.bind(lo.isoformat()), b.bind(hi.isoformat())
    scope = "" if account_ids is None else " AND " + b.in_("account_id", account_ids)
    sums = ", ".join(f"COUNT({c}) AS n_{c}, SUM({c}) AS {c}" for c in SERIES)
    async with get_session() as s:
        rows = (await s.execute(text(
            f"SELECT account_id, {sums}, MAX(CASE WHEN day = {hi_} THEN active_fans END) AS active_fans, "
            f"MAX(CASE WHEN day = {hi_} THEN renew_on END) AS renew_on "
            f"FROM of_stats_daily WHERE day >= {lo_} AND day <= {hi_}{scope} GROUP BY account_id").bindparams(**b))).all()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        row = out[r.account_id] = {}
        whole = {c: int(getattr(r, c)) for c in SERIES if getattr(r, f"n_{c}") == days}
        if "visitors" in whole:
            row["of_visitors"] = whole["visitors"]
        if "renewals" in whole:
            row["of_renewals"] = whole["renewals"]
        if whole.get("visitors") and "new_subs" in whole:
            row["of_new_sub_conversion_pct"] = round(100 * whole["new_subs"] / whole["visitors"], 2)
        if r.renew_on is not None:
            row["of_renew_on"] = int(r.renew_on)
            if r.active_fans:
                row["of_renew_on_pct"] = round(100 * r.renew_on / r.active_fans, 2)
    return out
