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
of_client.subscribers_chart); the shape check (of_stats_parse.points) drops a
series that does not.
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

Earnings (`of_earnings_daily`): OnlyFans' own figure for a Creator's earnings,
the one its Statistics › Statements page shows (the OF Manager's Statistics
reads the same `/earnings/chart` live). The ledger (`transactions`) only holds
what we ingested since the Creator was connected, and can miss sales; OF fills
those in (owner, 2026-10-24: the DB is a best-effort cache of OF), and the
reports read the larger of the two per Creator, UTC day and category (stats.py
`_of_top_ups`): OF never takes away a sale the ledger holds. So:

  earnings   GET /earnings/chart  filter[<c>_count, <c>_amount] for c in
             EARNINGS and TOTAL: every asked category answered, zero or not,
             `messages` under the key `chat_messages` (REPLY_KEY), each a daily
             `chartAmount` (net, after OF's fee; pending sales in, chargebacks
             out) and `chartCount`, plus the period's `total` (net) and `gross`.
             Days are UTC days, points stamped 00:00+00:00; the hours in
             startDate / endDate change nothing (measured 2026-10-25).

Each day's snapshot re-reads the last `_DAYS` days (OF revises a day for a
chargeback), and each tick fills the newest missing days back to
`_EARNINGS_HISTORY_DAYS` in `_EARNINGS_CHUNK_DAYS`-day reads, at most
`_EARNINGS_CHUNKS_PER_TICK` a tick. A read that answers in another shape (not
one point per consecutive day, e.g. weekly buckets) stores nothing and is
asked again the next tick, as is one whose categories do not add up to OF's
own total (a category under a key we do not read). A day is stored with OF's
TOTAL row; a day without one (stored before 2026-10-25, its PPV messages read
as $0) counts as not stored: read again and overwritten, and the reports read
the ledger's for it meanwhile. Gross per day is derived
(`of_stats_parse.earnings`): OF sends gross only as the period's total.
`earnings_window` is the read stats.py takes OF's days from.
"""
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
import tx_rollup
from cadence import boot_grace
from db.engine import get_session
from db.models import Account, OfEarningsDaily, OfStatsDaily, SubscriberSnapshot

log = logging.getLogger("of-relay.of_stats_daily")

_DAYS = 7                 # complete days each fetch re-reads
_TICK_S = 3600            # how often the loop looks for a Creator due a fetch
_CALL_PAUSE_S = 2.0       # between two OF reads, and between two Creators
_RETRY_AFTER_S = 6 * 3600 # between two fetches for a day not yet stored
_MAX_ATTEMPTS = 3         # fetches per Creator per day, at most
_BOOT_GRACE_S = 300.0
SERIES = ("visitors", "new_subs", "renewals")

# Earnings history kept per Creator: the reports' longest window (stats.MAX_WINDOW_DAYS).
_EARNINGS_HISTORY_DAYS = 400
_EARNINGS_CHUNK_DAYS = 30      # one /earnings/chart read; OF's "Last 30 days" charts daily
_EARNINGS_CHUNKS_PER_TICK = 4  # 120 days of history an hour per Creator
# Categories live in of_stats_parse; same objects here, read off this module by of_top_up.py,
# faults and tests. _points/_amounts/_earnings: compat aliases only; fetch_* call
# of_stats_parse.*, so patch there.
EARNINGS, EARNINGS_KIND, REPLY_KEY, TOTAL = (
    of_stats_parse.EARNINGS, of_stats_parse.EARNINGS_KIND, of_stats_parse.REPLY_KEY, of_stats_parse.TOTAL)
_points, _amounts, _earnings = of_stats_parse.points, of_stats_parse.amounts, of_stats_parse.earnings
# earnings_window's answers, until the next write: every report read asks for
# the same few windows, and only this job writes the table (one relay process).
_WINDOW_CACHE_MAX = 256
_window_cache: OrderedDict[tuple, tuple[dict[tuple[str, str], list[dict[str, Any]]], int]] = OrderedDict()
_earnings_version = 0
_earnings_writes: deque[tuple[int, str, date, date]] = deque(maxlen=1024)  # (version, account, first, last day)
_window_reads: dict[tuple, tuple[int, asyncio.Future]] = {}  # a window being read: later askers share it


def _hits(key: tuple, account_id: str, first: date, last: date) -> bool:
    """Whether a write of `account_id`'s days [first, last] changes window `key`."""
    return (key[0] is None or account_id in key[0]) and key[1] <= last and key[2] >= first


def _unchanged_since(key: tuple, version: int) -> bool:
    """No write since `version` changed window `key` (False when the log no longer reaches back)."""
    if version < _earnings_version - len(_earnings_writes):
        return False
    return not any(v > version and _hits(key, a, f, l) for v, a, f, l in _earnings_writes)


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
    pts = of_stats_parse.points(chart.get("visitors") if isinstance(chart, dict) else None, first, last)
    if pts is not None:
        out["visitors"] = pts
    for col, by in (("new_subs", "new"), ("renewals", "renew")):
        time.sleep(pause_s)
        reply = client.subscribers_chart(start=start, end=end, by=by)
        pts = of_stats_parse.points(reply.get("subscribes") if isinstance(reply, dict) else None, first, last)
        if pts is not None:
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


def fetch_earnings_blocking(client, first: date, last: date) -> dict[str, dict[str, tuple[int, int, int]]] | None:
    """OF's own earnings over [first, last] UTC days (`of_stats_parse.earnings`),
    None when it answered in another shape. Blocking: run in a thread. Raises
    what the client raises."""
    # The same read as Statistics › Statements' sidebar (ofMirrorStatsSources `earningsSide`), with its total.
    reply = client.earnings_chart(start=f"{first.isoformat()} 00:00:00", end=f"{last.isoformat()} 23:59:59",
                                  filter=[f"{c}_{m}" for c in (*EARNINGS, TOTAL) for m in ("count", "amount")])
    got = of_stats_parse.earnings(reply, first, last)
    if got is None:
        log.warning("of_stats_daily: earnings %s..%s answered in an unexpected shape or not adding up to its "
                    "total (keys %s); not stored", first, last,
                    sorted(reply)[:12] if isinstance(reply, dict) else type(reply).__name__)
    return got


async def _upsert_earnings(account_id: str, days: dict[str, dict[str, tuple[int, int, int]]], now: datetime) -> int:
    """Write each day's categories (`of_stats_parse.earnings`). Returns the days written."""
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
        del _window_cache[key]  # only the windows these days fall in
    return len(days)


async def _earnings_days(account_id: str, lo: date, hi: date) -> set[str]:
    """The days stored by a read of every category: those with OF's `TOTAL`. A
    day without it was written before 2026-10-25 with its PPV messages read as
    $0: asked again, its rows overwritten, and read as not stored meanwhile."""
    async with get_session() as s:
        return set((await s.execute(
            select(OfEarningsDaily.day).where(
                OfEarningsDaily.account_id == account_id, OfEarningsDaily.category == TOTAL,
                OfEarningsDaily.day >= lo.isoformat(), OfEarningsDaily.day <= hi.isoformat()))).scalars())


async def backfill_earnings(account_id: str, client, *, now: datetime | None = None,
                            pause_s: float = _CALL_PAUSE_S, chunks: int = _EARNINGS_CHUNKS_PER_TICK) -> int:
    """Fill the newest days of the last `_EARNINGS_HISTORY_DAYS` complete UTC
    days with no stored earnings, one `_EARNINGS_CHUNK_DAYS`-day read at a time,
    at most `chunks` reads. Stops at a reply in another shape (asked again the
    next tick). Returns the days written."""
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
    """Whether a day of the kept history has no stored earnings."""
    now = now or datetime.utcnow()
    last = now.date() - timedelta(days=1)
    lo = last - timedelta(days=_EARNINGS_HISTORY_DAYS - 1)
    return len(await _earnings_days(account_id, lo, last)) < _EARNINGS_HISTORY_DAYS


async def snapshot(account_id: str, client, *, now: datetime | None = None,
                   pause_s: float = _CALL_PAUSE_S) -> int:
    """Fetch the last `_DAYS` complete UTC days for one Creator and store them,
    the earnings too (OF revises a recent day for a chargeback). Returns the
    days of Statistics figures written."""
    now = now or datetime.utcnow()
    last = now.date() - timedelta(days=1)
    first = last - timedelta(days=_DAYS - 1)
    cols = await asyncio.to_thread(fetch_blocking, client, first, last, pause_s=pause_s)
    n = await _upsert(account_id, cols, now) if cols else 0
    await asyncio.sleep(pause_s)
    if (earned := await asyncio.to_thread(fetch_earnings_blocking, client, first, last)) is not None:
        await _upsert_earnings(account_id, earned, now)
    return n


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


async def earnings_window(account_ids: list[str] | None, start: datetime | None, end: datetime | None, *,
                          now: datetime | None = None) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], int]:
    """OnlyFans' own earnings over a report window, for stats.py to read in
    place of the ledger's days. Returns:

      cells  {(account_id, 'YYYY-MM-DD'): one cell per category}, for each
             Creator's stored days among the window's UTC days through
             yesterday (`window_days`), each cell shaped as stats._day_sums'
             (`day`, `account_id`, `kind` = EARNINGS_KIND, tx_rollup.MEASURES;
             OF's net has no missing figure, its fee is gross - net, VAT 0)
      gaps   the (Creator, day) pairs of those days with no stored earnings
             that fall before the Creator was added (`accounts.created_at`):
             days our ledger is known not to hold, so a comparison against
             the window reads them as unknown, not as $0.00

    Kept per (Creators, days) until the job writes one of its days, and read
    once for all who ask while it is read: the answer is shared, so a caller
    must not change it.
    """
    now = now or datetime.utcnow()
    yesterday = now.date() - timedelta(days=1)
    # An open edge: the kept history's first day, or yesterday.
    lo = window_days(start, start)[0] if start else yesterday - timedelta(days=_EARNINGS_HISTORY_DAYS - 1)
    hi = min(window_days(end, end)[1], yesterday) if end else yesterday
    if lo > hi:
        return {}, 0
    key = (None if account_ids is None else tuple(sorted(account_ids)), lo, hi)
    if (hit := _window_cache.get(key)) is not None:
        _window_cache.move_to_end(key)
        return hit
    # Join a read of this window under way unless a write changed the window since it began.
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
        f.exception()  # raised to every asker; retrieved here too, for the one whose request went away


async def _read_window(account_ids: list[str] | None, lo: date, hi: date,
                       ) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], int]:
    """`earnings_window`'s read of the stored days [lo, hi]."""
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
    read = {(r.account_id, r.day) for r in rows if r.category == TOTAL}  # `_earnings_days`
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
