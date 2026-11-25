# ASSUMPTION: by=new / by=renew answer the same shape as the reply without `by`; the shape check drops a series that does not.
# Only complete UTC days are stored: a day OF is still counting never is.
# OF's earnings fill in sales the ledger missed; reports read the larger of the two per creator/day/category: OF never takes away a sale the ledger holds.
# chartAmount is net after OF's fee, pending sales in, chargebacks out; OF sends gross only as the period total.
# Days are UTC; the hours in startDate/endDate change nothing (measured).
# A day without OF's TOTAL row (PPV messages read as $0 before it) counts as not stored: read again and overwritten.
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict, deque
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import account_health
import accounts as account_registry
import client_pool
import of_stats_parse
import platforms
import tx_rollup
from cadence import boot_grace
from db.engine import get_session
from db.models import Account, OfEarningsDaily, OfStatsDaily, SubscriberSnapshot

log = logging.getLogger("of-relay.of_stats_daily")

_DAYS = 7
_SUBS_DAYS = 30  # OF's own "Last 30 days" charts the subscriber charts daily
_TICK_S = 3600
_CALL_PAUSE_S = 2.0
_RETRY_AFTER_S = 6 * 3600
_MAX_ATTEMPTS = 3
_BOOT_GRACE_S = 300.0
SERIES = ("visitors", "new_subs", "renewals")

# The reports' longest window (stats.MAX_WINDOW_DAYS).
_EARNINGS_HISTORY_DAYS = 400
_EARNINGS_CHUNK_DAYS = 30  # one /earnings/chart read; OF's "Last 30 days" charts daily
_EARNINGS_CHUNKS_PER_TICK = 4
EARNINGS, EARNINGS_KIND, REPLY_KEY, TOTAL = (
    of_stats_parse.EARNINGS, of_stats_parse.EARNINGS_KIND, of_stats_parse.REPLY_KEY, of_stats_parse.TOTAL)
_points, _amounts, _earnings = of_stats_parse.points, of_stats_parse.amounts, of_stats_parse.earnings
# Only this job writes the table (one relay process), so cached windows are valid until its next write.
_WINDOW_CACHE_MAX = 256
_window_cache: OrderedDict[tuple, tuple[dict[tuple[str, str], list[dict[str, Any]]], int]] = OrderedDict()
_earnings_version = 0
_earnings_writes: deque[tuple[int, str, date, date]] = deque(maxlen=1024)
_window_reads: dict[tuple, tuple[int, asyncio.Future]] = {}


def _hits(key: tuple, account_id: str, first: date, last: date) -> bool:
    return (key[0] is None or account_id in key[0]) and key[1] <= last and key[2] >= first


def _unchanged_since(key: tuple, version: int) -> bool:
    if version < _earnings_version - len(_earnings_writes):
        return False
    return not any(v > version and _hits(key, a, f, l) for v, a, f, l in _earnings_writes)


def fetch_blocking(client, first: date, last: date, *, pause_s: float = _CALL_PAUSE_S,
                   subs_first: date | None = None) -> dict[str, dict[str, int]]:
    # UNVERIFIED which zone OF reads startDate/endDate in; sent as UTC days, each point stored under the date OF stamps on it.
    start, end = f"{first.isoformat()} 00:00:00", f"{last.isoformat()} 23:59:59"
    out: dict[str, dict[str, int]] = {}
    visitors = client.my_profile_stats(start=start, end=end)
    chart = visitors.get("chart") if isinstance(visitors, dict) else None
    pts = of_stats_parse.points(chart.get("visitors") if isinstance(chart, dict) else None, first, last)
    if pts is not None:
        out["visitors"] = pts
    s_first = subs_first or first
    s_start = f"{s_first.isoformat()} 00:00:00"
    for col, by in (("new_subs", "new"), ("renewals", "renew")):
        time.sleep(pause_s)
        reply = client.subscribers_chart(start=s_start, end=end, by=by)
        pts = of_stats_parse.points(reply.get("subscribes") if isinstance(reply, dict) else None, s_first, last)
        if pts is not None:
            out[col] = pts
    for col in SERIES:
        if col not in out:
            log.warning("of_stats_daily: %s answered in an unexpected shape; not stored", col)
    return out


async def _upsert(account_id: str, cols: dict[str, dict[str, int]], now: datetime) -> int:
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


def fetch_earnings_blocking(client, first: date, last: date) -> dict[str, dict[str, tuple[int, int, int]]] | None:
    reply = client.earnings_chart(start=f"{first.isoformat()} 00:00:00", end=f"{last.isoformat()} 23:59:59",
                                  filter=[f"{c}_{m}" for c in (*EARNINGS, TOTAL) for m in ("count", "amount")])
    got = of_stats_parse.earnings(reply, first, last)
    if got is None:
        log.warning("of_stats_daily: earnings %s..%s answered in an unexpected shape or not adding up to its "
                    "total (keys %s); not stored", first, last,
                    sorted(reply)[:12] if isinstance(reply, dict) else type(reply).__name__)
    return got


async def _upsert_earnings(account_id: str, days: dict[str, dict[str, tuple[int, int, int]]], now: datetime) -> int:
    if not days:
        return 0
    rows = [{"account_id": account_id, "day": d, "category": c, "net_cents": net, "gross_cents": gross,
             "sales": sales, "fetched_at": now}
            for d, cats in days.items() for c, (net, gross, sales) in cats.items()]
    async with get_session() as s:
        stmt = sqlite_insert(OfEarningsDaily)
        for i in range(0, len(rows), 500):
            await s.execute(stmt.on_conflict_do_update(
                index_elements=["account_id", "day", "category"],
                set_={c: stmt.excluded[c] for c in ("net_cents", "gross_cents", "sales", "fetched_at")}),
                rows[i:i + 500])
        await s.commit()
    global _earnings_version
    _earnings_version += 1
    first, last = date.fromisoformat(min(days)), date.fromisoformat(max(days))
    _earnings_writes.append((_earnings_version, account_id, first, last))
    for key in [k for k in _window_cache if _hits(k, account_id, first, last)]:
        del _window_cache[key]
    return len(days)


async def _earnings_days(account_id: str, lo: date, hi: date) -> set[str]:
    async with get_session() as s:
        return set((await s.execute(
            select(OfEarningsDaily.day).where(
                OfEarningsDaily.account_id == account_id, OfEarningsDaily.category == TOTAL,
                OfEarningsDaily.day >= lo.isoformat(), OfEarningsDaily.day <= hi.isoformat()))).scalars())


async def backfill_earnings(account_id: str, client, *, now: datetime | None = None,
                            pause_s: float = _CALL_PAUSE_S, chunks: int = _EARNINGS_CHUNKS_PER_TICK) -> int:
    now = now or datetime.utcnow()
    last = now.date() - timedelta(days=1)
    lo = last - timedelta(days=_EARNINGS_HISTORY_DAYS - 1)
    stored = await _earnings_days(account_id, lo, last)
    written = 0
    for i in range(chunks):
        hi = last
        while hi >= lo and hi.isoformat() in stored:
            hi -= timedelta(days=1)
        if hi < lo:
            break
        first = max(lo, hi - timedelta(days=_EARNINGS_CHUNK_DAYS - 1))
        if i:
            await asyncio.sleep(pause_s)
        got = await asyncio.to_thread(fetch_earnings_blocking, client, first, hi)
        if got is None:
            break
        written += await _upsert_earnings(account_id, got, now)
        stored |= set(got)
    return written


async def earnings_due(account_id: str, *, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    last = now.date() - timedelta(days=1)
    lo = last - timedelta(days=_EARNINGS_HISTORY_DAYS - 1)
    return len(await _earnings_days(account_id, lo, last)) < _EARNINGS_HISTORY_DAYS


async def snapshot(account_id: str, client, *, now: datetime | None = None,
                   pause_s: float = _CALL_PAUSE_S) -> int:
    now = now or datetime.utcnow()
    last = now.date() - timedelta(days=1)
    first = last - timedelta(days=_DAYS - 1)
    cols = await asyncio.to_thread(fetch_blocking, client, first, last, pause_s=pause_s,
                                   subs_first=last - timedelta(days=_SUBS_DAYS - 1))
    n = await _upsert(account_id, cols, now) if cols else 0
    await asyncio.sleep(pause_s)
    if (earned := await asyncio.to_thread(fetch_earnings_blocking, client, first, last)) is not None:
        await _upsert_earnings(account_id, earned, now)
    return n


async def sample_roster(account_id: str, *, now: datetime | None = None) -> bool:
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
    # Attempts are counted on the row so the cap holds across restarts.
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
        if not aid or not meta.get("has_session") or platforms.for_account(aid) is not platforms.ONLYFANS:
            continue
        try:
            await sample_roster(aid, now=now)
            if await account_health.is_session_dead(aid) or await account_health.is_deactivated(aid):
                continue
            client = None
            if await _claim(aid, now):
                client = await asyncio.to_thread(client_pool.get, aid)
                done[aid] = await snapshot(aid, client, now=now, pause_s=pause_s)
                await asyncio.sleep(pause_s)
            if await earnings_due(aid, now=now):
                client = client or await asyncio.to_thread(client_pool.get, aid)
                if n := await backfill_earnings(aid, client, now=now, pause_s=pause_s):
                    log.info("of_stats_daily: earnings history account=%s days=%d", aid, n)
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



def window_days(start: datetime, end: datetime) -> tuple[date, date]:
    # Edges rounded to the nearest UTC midnight: right for any report zone within 12 h of UTC.
    lo = (start + timedelta(hours=12)).date()
    hi = (end + timedelta(microseconds=1) + timedelta(hours=12)).date() - timedelta(days=1)
    return lo, hi


async def window_figures(account_ids: list[str] | None, start: datetime, end: datetime, *,
                         now: datetime | None = None) -> dict[str, dict[str, Any]]:
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


async def earnings_window(account_ids: list[str] | None, start: datetime | None, end: datetime | None, *,
                          now: datetime | None = None) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], int]:
    # The answer is shared between askers: a caller must not change it.
    now = now or datetime.utcnow()
    yesterday = now.date() - timedelta(days=1)
    lo = window_days(start, start)[0] if start else yesterday - timedelta(days=_EARNINGS_HISTORY_DAYS - 1)
    hi = min(window_days(end, end)[1], yesterday) if end else yesterday
    if lo > hi:
        return {}, 0
    key = (None if account_ids is None else tuple(sorted(account_ids)), lo, hi)
    if (hit := _window_cache.get(key)) is not None:
        _window_cache.move_to_end(key)
        return hit
    version, pending = _window_reads.get(key, (None, None))
    if pending is None or not _unchanged_since(key, version):
        version, pending = _earnings_version, asyncio.ensure_future(_read_window(account_ids, lo, hi))
        _window_reads[key] = (version, pending)
        pending.add_done_callback(lambda f, k=key: _read_done(k, f))
    cells, gaps = await asyncio.shield(pending)
    if _unchanged_since(key, version):
        _window_cache[key] = (cells, gaps)
        while len(_window_cache) > _WINDOW_CACHE_MAX:
            _window_cache.popitem(last=False)
    return cells, gaps


def _read_done(key: tuple, f: asyncio.Future) -> None:
    if _window_reads.get(key, (0, None))[1] is f:
        del _window_reads[key]
    if not f.cancelled():
        f.exception()


async def _read_window(account_ids: list[str] | None, lo: date, hi: date,
                       ) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], int]:
    E = OfEarningsDaily
    async with get_session() as s:
        q = select(E.account_id, E.day, E.category, E.net_cents, E.gross_cents, E.sales).where(
            E.day >= lo.isoformat(), E.day <= hi.isoformat())
        a = select(Account.id, Account.created_at)
        if account_ids is not None:
            q = q.where(E.account_id.in_(account_ids))
            a = a.where(Account.id.in_(account_ids))
        rows = (await s.execute(q)).all()
        added = (await s.execute(a)).all()
    read = {(r.account_id, r.day) for r in rows if r.category == TOTAL}
    cells: dict[tuple[str, str], list[dict[str, Any]]] = {k: [] for k in read}
    for r in rows:
        kind = EARNINGS_KIND.get(r.category)
        if kind is None or (r.account_id, r.day) not in read or not (r.net_cents or r.gross_cents or r.sales):
            continue
        cells[(r.account_id, r.day)].append({
            "day": r.day, "account_id": r.account_id, "kind": kind, "category": r.category,
            "gross_cents": r.gross_cents, "net_cents": r.net_cents, "net_missing": 0,
            "net_or_80_cents": r.net_cents, "sales": r.sales,
            "fee_cents": r.gross_cents - r.net_cents, "vat_cents": 0})
    gaps = 0
    for aid, created in added:
        until = min(hi, (created.date() if created else lo) - timedelta(days=1))
        if until < lo:
            continue
        stored = {d for (a_, d) in cells if a_ == aid}
        gaps += (until - lo).days + 1 - sum(1 for d in stored if d <= until.isoformat())
    return cells, gaps
