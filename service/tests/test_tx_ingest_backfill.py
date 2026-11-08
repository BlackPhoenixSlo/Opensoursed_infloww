#!/usr/bin/env python3
"""
The ledger backfill's marker walk, on the real run_one_tick and write path, against a fake
OF ledger that answers as AE's did (measured 2026-11-07): `start` / `end` ignored, date-only
`startDate` from UTC midnight on (an ISO one is format-dependent: empty here), newest first, 100 a page,
`offset` >= 600 empty with hasMore false (offset 500 says true), `marker` inclusive,
`nextMarker` = the next page's first createdAt, the last page hasMore false, no nextMarker.

Run: ./venv/bin/python service/tests/test_tx_ingest_backfill.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import calendar  # noqa: E402
import logging  # noqa: E402
from collections import Counter  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import events  # noqa: E402
import of_client  # noqa: E402
import of_pacing  # noqa: E402
import transaction_chargebacks as cb  # noqa: E402
import transaction_ingest as ti  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Transaction, TransactionScanHistory  # noqa: E402

FAN = 555
ti._PAGE_SLEEP_S = 0.0
logging.getLogger("of-relay.ingest_tx").setLevel(logging.CRITICAL)


def _now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def _floor() -> datetime:
    return (_now() - timedelta(days=90)).replace(hour=12, minute=0, second=0)


# Every write path a walk takes: PPV (_link_ppv_message, try_stamp_message), first charge, renewal, tip.
_DESCRIPTIONS = ("Tip from u555", "Payment for message from u555", "Subscription from u555",
                 "Recurring subscription from u555")


def _row(pid, at: datetime, *, cents: int = 100, status: str = "done", description: str | None = None) -> dict:
    return {"id": pid, "user": {"id": FAN}, "amount": cents / 100, "net": cents / 125, "fee": cents / 500,
            "createdAt": at.isoformat() + "+00:00", "status": status,
            "description": description or _DESCRIPTIONS[sum(map(ord, str(pid))) % len(_DESCRIPTIONS)]}


def _epoch(raw: dict) -> int:
    at = datetime.fromisoformat(raw["createdAt"].replace("Z", "+00:00"))
    return calendar.timegm(at.utctimetuple())


class _OF:
    """The measured ledger. `before(params)`, when set, runs first for every request (raises:
    a failed page). `answer(params, body)`, when set, may replace the body."""

    def __init__(self, rows: list[dict]):
        self.rows, self.wire = rows, []
        self.before = self.answer = None
        self.disputes, self.cb_wire = [], []

    def chargebacks(self, *, limit: int, offset: int = 0, **kw) -> dict:
        self.cb_wire.append(offset)
        return {"list": self.disputes[offset:offset + limit], "marker": 0}

    def transactions(self, **kw):
        rec = of_client.OFClient.__new__(of_client.OFClient)
        out: list[dict] = []
        rec.get_json = lambda path, params=None: out.append(params) or {}
        of_client.OFClient.transactions(rec, **kw)
        params = out[0]
        self.wire.append(params)
        if self.before:
            self.before(params)
        body = self._page(params)
        return self.answer(params, body) if self.answer else body

    def _page(self, q: dict) -> dict:
        sd, lim, off = q.get("startDate"), min(q["limit"], 100), q["offset"]
        if off >= 600 or (sd and len(sd) != 10):
            return {"hasMore": False, "list": [], "marker": None}
        rows = sorted(self.rows, key=_epoch, reverse=True)
        if sd:
            rows = [r for r in rows if _epoch(r) >= calendar.timegm(datetime.fromisoformat(sd).timetuple())]
        if q.get("marker") is not None:
            rows = [r for r in rows if _epoch(r) <= q["marker"]]
        more = off + lim < len(rows)
        return {"hasMore": more, "list": rows[off:off + lim], "marker": q.get("marker"),
                "nextMarker": _epoch(rows[off + lim]) if more else None}


def _spread(n: int, *, newest_h: float = 1.0, step_s: int = 1800, prefix: str = "r", cents: int = 100,
            ties: int = 1, status: str = "done") -> list[dict]:
    """`n` rows newest first, `step_s` apart in groups of `ties` rows of the same second."""
    top = _now() - timedelta(hours=newest_h)
    return [_row(f"{prefix}{i}", top - timedelta(seconds=step_s * (i // ties)), cents=cents, status=status)
            for i in range(n)]


async def _account(aid: str, *, floor: datetime | None = None, cursor: datetime | None = None,
                   full: bool = False) -> None:
    async with get_session() as s:
        s.add(Account(id=aid, nickname=aid))
        s.add(TransactionScanHistory(
            account_id=aid, backfill_floor=floor or _floor(), oldest_seen_occurred_at=cursor,
            fully_backfilled=full, current_status="idle"))


async def _tick(aid: str, of: _OF, mode: str = "backfill") -> dict:
    orig = ti._client_for
    ti._client_for = lambda _aid: of
    try:
        return await ti.run_one_tick(aid, mode=mode)
    finally:
        ti._client_for = orig


async def _walk(aid: str, of: _OF, ticks: int = 20) -> int:
    """Backfill ticks until the walk says done; how many it took."""
    for n in range(1, ticks + 1):
        await _tick(aid, of)
        if (await _scan(aid)).fully_backfilled:
            return n
    raise AssertionError(f"not done after {ticks} ticks: {await _scan(aid)}")


async def _scan(aid: str) -> TransactionScanHistory:
    async with get_session() as s:
        return await s.get(TransactionScanHistory, aid)


async def _unstamp(aid: str) -> None:
    """No full-walk watermark yet (persisted TransactionScanHistory.last_full_at)."""
    async with get_session() as s:
        (await s.get(TransactionScanHistory, aid)).last_full_at = None


async def _held(aid: str) -> Counter:
    async with get_session() as s:
        return Counter((await s.execute(select(Transaction.provider_transaction_id).where(
            Transaction.account_id == aid))).scalars().all())


async def _lifetime(aid: str) -> int:
    async with get_session() as s:
        fan = await s.get(Fan, (aid, FAN))
        return fan.lifetime_spend_cents if fan else 0


async def _exactly(aid: str, rows: list[dict]) -> None:
    held = await _held(aid)
    want = {str(r["id"]) for r in rows}
    assert not want - set(held), f"lost {len(want - set(held))} rows, e.g. {sorted(want - set(held))[:3]}"
    assert not set(held) - want, f"extra rows {sorted(set(held) - want)[:3]}"
    assert max(held.values()) == 1, "a provider id held twice"


async def case_the_wire_is_date_only_start_marker_and_no_start_end():
    aid = "bf_wire"
    floor = _floor()
    await _account(aid, floor=floor)
    of = _OF(_spread(250, step_s=60))
    res = await _tick(aid, of)
    assert res["error"] is None, res
    want = (floor - timedelta(days=1)).date().isoformat()
    assert [w["startDate"] for w in of.wire] == [want] * 3, of.wire
    assert all(w["offset"] == 0 and w["limit"] == 100 for w in of.wire), of.wire
    assert not any("start" in w or "end" in w for w in of.wire), of.wire
    assert "marker" not in of.wire[0], of.wire[0]
    assert [w["marker"] for w in of.wire[1:]] == [_epoch(of.rows[100]), _epoch(of.rows[200])], of.wire


async def case_a_whole_window_past_600_lands_exactly_once():
    aid = "bf_whole"
    floor = _floor()
    await _account(aid, floor=floor)
    inside = _spread(1500, step_s=4000, cents=100)
    below = [_row(f"old{i}", floor - timedelta(days=3, hours=i), cents=999) for i in range(30)]
    of = _OF([*inside, *below])
    assert await _walk(aid, of) == 1
    await _exactly(aid, inside)
    assert await _lifetime(aid) == 150_000, await _lifetime(aid)
    scan = await _scan(aid)
    assert scan.fully_backfilled and scan.current_status == "ok" and scan.rows_inserted_total == 1500, scan
    assert len(of.wire) == 15, len(of.wire)


async def case_the_tick_cap_stops_short_and_the_next_tick_resumes_at_the_cursor():
    aid = "bf_cap"
    await _account(aid)
    rows = _spread(4500, step_s=1500, cents=100)
    of = _OF(rows)
    await _tick(aid, of)
    assert len(of.wire) == ti._BACKFILL_TICK_PAGES == 40, len(of.wire)
    scan = await _scan(aid)
    assert not scan.fully_backfilled and scan.current_status == "backfill_partial", scan
    cursor = scan.oldest_seen_occurred_at
    assert cursor == datetime.fromisoformat(rows[3999]["createdAt"]).replace(tzinfo=None), cursor
    assert len(await _held(aid)) == 4000
    of.wire.clear()
    await _tick(aid, of)
    assert "marker" not in of.wire[0], "a resumed tick reads the recent rows first"
    walk = [w for w in of.wire if "marker" in w]
    assert walk[0]["marker"] == calendar.timegm(cursor.timetuple()), "inclusive marker from the cursor"
    assert (await _scan(aid)).fully_backfilled
    await _exactly(aid, rows)
    assert await _lifetime(aid) == 450_000, "the resumed tick's re-reads must not count again"


async def case_same_second_rows_across_pages_are_neither_skipped_nor_double_counted():
    aid = "bf_ties"
    await _account(aid)
    rows = _spread(950, step_s=600, ties=7, cents=100)
    of = _OF(rows)
    assert await _walk(aid, of) == 1
    await _exactly(aid, rows)
    assert await _lifetime(aid) == 95_000


async def case_same_second_rows_at_a_tick_boundary_are_re_read():
    aid = "bf_tie_cap"
    await _account(aid)
    rows = _spread(150, newest_h=96, step_s=600, ties=30, cents=100)   # below the recent read
    of = _OF(rows)
    orig, ti._BACKFILL_TICK_PAGES = ti._BACKFILL_TICK_PAGES, 1
    try:
        await _tick(aid, of)
        assert len(await _held(aid)) == 100, "the page ended 10 rows into a 30-row second"
        assert not (await _scan(aid)).fully_backfilled
        of.wire.clear()
        assert await _walk(aid, of) == 1
        assert of.wire[-1]["marker"] == _epoch(rows[99]), of.wire
    finally:
        ti._BACKFILL_TICK_PAGES = orig
    await _exactly(aid, rows)
    assert await _lifetime(aid) == 15_000


async def case_a_second_429_mid_walk_keeps_the_cursor_is_not_complete_and_resumes():
    aid = "bf_429"
    await _account(aid)
    rows = _spread(800, step_s=4000)
    of = _OF(rows)
    calls = {"n": 0}

    def fail(_q):
        calls["n"] += 1
        if calls["n"] == 4:
            raise RuntimeError("OF 429 twice")

    of.before = fail
    res = await _tick(aid, of)
    assert res["error"] and "429" in res["error"], res
    scan = await _scan(aid)
    assert not scan.fully_backfilled, "an error mid-walk marked the backfill complete"
    want = datetime.fromisoformat(rows[299]["createdAt"]).replace(tzinfo=None)
    assert scan.oldest_seen_occurred_at == want, "the failure path dropped the walk's place"
    assert scan.consecutive_failures == 0, "a walk that progressed must not walk into a pause"
    assert res["rows_inserted"] == 300, res
    of.before = None
    assert await _walk(aid, of) == 1
    await _exactly(aid, rows)
    assert await _lifetime(aid) == 80_000


async def case_repeated_429s_with_no_page_held_still_count_toward_the_pause():
    aid = "bf_dead"
    await _account(aid)
    of = _OF(_spread(10))

    def fail(_q):
        raise RuntimeError("OF 401")

    of.before = fail
    for _ in range(3):
        await _tick(aid, of)
    scan = await _scan(aid)
    assert scan.consecutive_failures == 3 and scan.current_status == "paused", scan
    assert not scan.fully_backfilled and scan.oldest_seen_occurred_at is None, scan


async def case_a_crash_before_the_cursor_save_re_reads_and_skips_nothing():
    aid = "bf_crash"
    await _account(aid)
    rows = _spread(300, step_s=4000)
    of = _OF(rows)
    real, saves = ti._save_backfill_page, {"n": 0}

    async def boom(*a, **kw):
        saves["n"] += 1
        if saves["n"] == 2:
            raise RuntimeError("killed after the page's commit, before its cursor")
        return await real(*a, **kw)

    ti._save_backfill_page = boom
    try:
        res = await _tick(aid, of)
    finally:
        ti._save_backfill_page = real
    assert res["error"], res
    scan = await _scan(aid)
    assert scan.oldest_seen_occurred_at == datetime.fromisoformat(rows[99]["createdAt"]).replace(tzinfo=None)
    assert not scan.fully_backfilled
    assert await _walk(aid, of) == 1
    await _exactly(aid, rows)
    assert await _lifetime(aid) == 30_000


async def case_offset_cap_style_empty_page_mid_walk_is_not_complete():
    aid = "bf_empty_mid"
    await _account(aid)
    rows = _spread(300, step_s=4000)
    of = _OF(rows)
    n = {"pages": 0}

    def answer(_q, body):
        n["pages"] += 1
        return {"hasMore": False, "list": []} if n["pages"] == 2 else body

    of.answer = answer
    res = await _tick(aid, of)
    assert res["error"] is None, res
    scan = await _scan(aid)
    assert not scan.fully_backfilled and scan.current_status == "backfill_stalled", scan
    assert len(await _held(aid)) == 100
    of.answer = None
    assert await _walk(aid, of) == 1
    await _exactly(aid, rows)


async def case_empty_first_page_completes_only_when_nothing_is_held_in_the_window():
    quiet, busy, stale = "bf_first_quiet", "bf_first_busy", "bf_first_stale"
    floor = _floor()
    for aid in (quiet, busy, stale):
        await _account(aid, floor=floor)
    async with get_session() as s:
        s.add(Transaction(account_id=busy, fan_id=FAN, amount_cents=1, kind="tip", status="cleared",
                          provider_transaction_id="held1", source="ledger", occurred_at=floor - timedelta(hours=23)))   # on startDate's day: held
        s.add(Transaction(account_id=stale, fan_id=FAN, amount_cents=1, kind="tip", status="cleared",
                          provider_transaction_id="held2", source="ledger", occurred_at=floor - timedelta(days=3)))     # before startDate: not in the window
    await _tick(quiet, _OF([]))
    await _tick(stale, _OF([_row("before", floor - timedelta(days=3))]))
    res = await _tick(busy, _OF([]))
    assert res["error"] is None, res
    assert (await _scan(quiet)).fully_backfilled, "an empty account is done"
    assert (await _scan(stale)).fully_backfilled, "a row before startDate is not in the window"
    scan = await _scan(busy)
    assert not scan.fully_backfilled and scan.current_status == "backfill_stalled", scan


async def _stops(aid: str, rows: list[dict], answer) -> TransactionScanHistory:
    await _account(aid)
    of = _OF(rows)
    of.answer = answer
    res = await _tick(aid, of)
    assert res["error"] is None, res
    scan = await _scan(aid)
    assert not scan.fully_backfilled and scan.current_status == "backfill_stalled", scan
    assert scan.last_error.startswith("backfill_stopped: "), scan.last_error
    assert len(of.wire) <= 3, of.wire
    return scan


async def case_has_more_without_next_marker_stops_not_complete():
    def answer(_q, body):
        return {**body, "nextMarker": None}
    scan = await _stops("bf_no_marker", _spread(300, step_s=4000), answer)
    assert scan.oldest_seen_occurred_at is not None


async def case_a_marker_that_does_not_decrease_stops_not_complete():
    def answer(q, body):
        return {**body, "nextMarker": q.get("marker") or body["nextMarker"]}
    await _stops("bf_stuck", _spread(300, step_s=4000), answer)


async def case_a_repeated_page_stops_not_complete():
    first: list = []

    def answer(_q, body):
        first.append(body)
        return {**first[0], "nextMarker": first[0]["nextMarker"] - len(first)}
    aid = "bf_repeat"
    await _stops(aid, _spread(300, step_s=4000), answer)
    assert len(await _held(aid)) == 100


async def case_more_than_a_page_in_one_second_stops_never_skips():
    aid = "bf_flood"
    await _account(aid)
    rows = [*_spread(250, ties=250, newest_h=72), *_spread(50, newest_h=96, prefix="below")]
    of = _OF(rows)
    await _tick(aid, of)
    scan = await _scan(aid)
    assert not scan.fully_backfilled, "the rows behind the stuck second would be lost"
    assert len(of.wire) == 2 and scan.current_status == "backfill_stalled", (of.wire, scan)
    assert len(await _held(aid)) == 100


async def case_a_row_landing_mid_walk_lands_next_tick_and_the_cursor_stays():
    aid = "bf_fresh"
    await _account(aid)
    rows = _spread(4500, step_s=1500)
    of = _OF(rows)
    await _tick(aid, of)
    cursor = (await _scan(aid)).oldest_seen_occurred_at
    fresh = _row("new1", _now() - timedelta(minutes=2), cents=700)
    of.rows = [fresh, *rows]

    def no_walk(q):
        if q.get("marker"):
            raise RuntimeError("the walk's first page fails: only the recent read lands")

    of.before = no_walk
    await _tick(aid, of)
    of.before = None
    scan = await _scan(aid)
    assert "new1" in await _held(aid), "a new row starved behind the backfill"
    assert scan.oldest_seen_occurred_at == cursor, "the recent read moved the cursor"
    assert scan.newest_seen_occurred_at == datetime.fromisoformat(fresh["createdAt"]).replace(tzinfo=None), scan
    assert await _walk(aid, of) == 1
    await _exactly(aid, [fresh, *rows])
    assert await _lifetime(aid) == 450_000 + 700


async def case_a_walk_back_from_an_outage_reads_what_landed_above_its_top():
    aid = "bf_outage"
    now = _now()
    rows = _spread(300, newest_h=24 * 20, step_s=3600)
    await _account(aid, cursor=datetime.fromisoformat(rows[99]["createdAt"]).replace(tzinfo=None))
    async with get_session() as s:
        (await s.get(TransactionScanHistory, aid)).newest_seen_occurred_at = \
            datetime.fromisoformat(rows[0]["createdAt"]).replace(tzinfo=None)
    assert await ti._write_page(aid, rows[:100]) == (100, 0)
    during = [_row(f"gap{i}", now - timedelta(days=5 + i)) for i in range(10)]
    of = _OF([*during, *rows])
    assert await _walk(aid, of) == 1
    await _exactly(aid, [*during, *rows])
    assert await _lifetime(aid) == 31_000


async def case_a_row_landing_above_a_finishing_walk_lands_on_the_recent_walk():
    aid = "bf_fresh_midpage"
    await _account(aid)
    rows = _spread(350, step_s=4000)
    of = _OF(rows)
    late = _row("late1", _now() - timedelta(minutes=1), cents=300)
    done = {"n": 0}

    def before(_q):
        done["n"] += 1
        if done["n"] == 2:
            of.rows = [late, *rows]

    of.before = before
    await _tick(aid, of)
    assert (await _scan(aid)).fully_backfilled   # the walk had passed the top when it landed
    await _exactly(aid, rows)
    of.before = None
    assert (await _tick(aid, of, mode="recent"))["error"] is None
    await _exactly(aid, [late, *rows])
    assert await _lifetime(aid) == 35_000 + 300


async def case_pending_rows_are_walked_and_flips_update_without_a_burst():
    aid = "bf_sse"
    await _account(aid)
    now = _now()
    old = [_row(f"o{i}", now - timedelta(days=10 + i), status="loading") for i in range(50)]
    recent = _row("rec", now - timedelta(hours=2), status="loading")
    of = _OF([recent, *old])
    await _tick(aid, of)
    async with get_session() as s:
        held = dict((await s.execute(select(Transaction.provider_transaction_id, Transaction.status).where(
            Transaction.account_id == aid))).all())
    assert len(held) == 51 and set(held.values()) == {"pending"}, held
    assert await _lifetime(aid) == 5100, "pending rows are revenue as before"

    of.rows = [{**r, "status": "done"} for r in of.rows]
    await ti.trigger_backfill(aid, since=now - timedelta(days=90))
    announced: list = []
    real = events.announce_transaction

    async def spy(account_id, fan_id, *, occurred_at=None, capped=False, **kw):
        announced.append((occurred_at, capped))

    events.announce_transaction = spy
    try:
        await _tick(aid, of)
    finally:
        events.announce_transaction = real
    async with get_session() as s:
        statuses = Counter((await s.execute(select(Transaction.status).where(
            Transaction.account_id == aid))).scalars().all())
    assert statuses == {"cleared": 51}, statuses
    assert len(announced) == 51 and all(capped for _, capped in announced), announced[:3]
    assert await _lifetime(aid) == 5100, "a re-read flip adds nothing"


async def case_recent_and_full_walks_flips_are_not_capped():
    aid = "bf_sse_recent"
    await _account(aid, full=True)
    now = _now()
    of = _OF([_row("p1", now - timedelta(hours=3), status="loading")])
    await _tick(aid, of, mode="recent")
    of.rows = [{**r, "status": "done"} for r in of.rows]
    announced: list = []
    real = events.announce_transaction

    async def spy(account_id, fan_id, *, occurred_at=None, capped=False, **kw):
        announced.append(capped)

    events.announce_transaction = spy
    try:
        await _tick(aid, of, mode="recent")
    finally:
        events.announce_transaction = real
    assert announced == [False], announced


async def case_a_row_the_writer_swallowed_holds_the_cursor_and_completion():
    aid = "bf_poison"
    await _account(aid)
    rows = _spread(300, step_s=4000)
    rows[50]["amount"] = 1e18   # cents overflow SQLite's INTEGER: this row alone fails
    of = _OF(rows)
    await _tick(aid, of)
    scan = await _scan(aid)
    assert not scan.fully_backfilled, "a lost row was recorded as done"
    assert scan.oldest_seen_occurred_at is None, "the cursor passed a row the DB does not hold"
    assert len(of.wire) == 1, of.wire
    assert "r50" not in await _held(aid) and len(await _held(aid)) == 99
    rows[50]["amount"] = 1.0
    assert await _walk(aid, of) == 1
    await _exactly(aid, rows)
    assert await _lifetime(aid) == 30_000


async def case_ids_sent_as_numbers_count_as_held():
    aid = "bf_numeric"
    await _account(aid)
    rows = [_row(9_000_000_000 + i, _now() - timedelta(hours=i + 1)) for i in range(150)]
    of = _OF(rows)
    await _tick(aid, of)
    assert (await _scan(aid)).fully_backfilled
    assert len(await _held(aid)) == 150


async def case_a_legacy_row_with_its_seen_range_below_the_window_walks_from_the_top():
    aid = "bf_legacy"
    floor = _floor()
    await _account(aid, floor=floor, cursor=floor - timedelta(days=20))
    rows = _spread(150, step_s=4000)
    of = _OF(rows)
    assert await _walk(aid, of) == 1
    assert "marker" not in of.wire[0]
    await _exactly(aid, rows)


async def case_an_admin_backfill_on_a_recorded_complete_account_walks_on_from_its_cursor():
    """15891843's shape: fully_backfilled=1, floor 07-26, oldest held 10-17."""
    aid = "bf_old_done"
    floor = _floor()
    rows = _spread(1200, step_s=6000)
    await _account(aid, floor=floor, cursor=datetime.fromisoformat(rows[599]["createdAt"]).replace(tzinfo=None),
                   full=True)
    assert await ti._write_page(aid, rows[:600]) == (600, 0)
    of = _OF(rows)
    await _tick(aid, of)
    assert (await _scan(aid)).fully_backfilled
    await _exactly(aid, rows)
    assert await _lifetime(aid) == 120_000


async def case_a_refresh_on_an_unfinished_backfill_leaves_its_cursor():
    aid = "bf_refresh_mid"
    await _account(aid)
    rows = _spread(700, step_s=4000)
    of = _OF(rows)
    orig, ti._BACKFILL_TICK_PAGES = ti._BACKFILL_TICK_PAGES, 2
    try:
        await _tick(aid, of)
    finally:
        ti._BACKFILL_TICK_PAGES = orig
    cursor = (await _scan(aid)).oldest_seen_occurred_at
    await _tick(aid, of, mode="refresh")   # OF's latest 600, past the 200 the walk held
    assert (await _scan(aid)).oldest_seen_occurred_at == cursor, "a refresh moved the backfill's cursor"
    assert await _walk(aid, of) == 1
    await _exactly(aid, rows)


async def case_the_admin_run_is_a_paced_walk():
    from tx_ingest_admin_api import _TxRunBody, admin_ingest_tx_run
    aid = "bf_admin"
    await _account(aid)
    kinds: list = []

    class Paced(_OF):
        def transactions(self, **kw):
            walk = of_pacing._WALK.get()
            kinds.append(walk and walk.kind)
            return super().transactions(**kw)

    of = Paced(_spread(150, step_s=4000))
    orig = ti._client_for
    ti._client_for = lambda _aid: of
    try:
        out = await admin_ingest_tx_run(aid, _TxRunBody(mode="backfill"))
        assert out["accepted"], out
        for t in [t for t in __import__("asyncio").all_tasks() if t.get_name().endswith(aid)]:
            await t
    finally:
        ti._client_for = orig
    assert kinds == ["transactions", "transactions"], kinds
    assert (await _scan(aid)).fully_backfilled


def _dispute(row: dict, status: str = "undo") -> dict:
    """OF's /payouts/chargebacks item naming `row`'s sale: the ledger row with another id."""
    words = row["description"]
    kind = "tips" if words.startswith("Tip") else "chat_messages" if words.startswith("Payment") else "subscribes"
    return {"id": 0, "createdAt": _now().isoformat() + "+00:00", "paymentType": kind,
            "payment": row | {"id": f"dispute-{row['id']}", "status": status}}


async def _status(aid: str, pid: str) -> str:
    async with get_session() as s:
        return (await s.execute(select(Transaction.status).where(
            Transaction.account_id == aid, Transaction.provider_transaction_id == pid))).scalar_one()


async def _disputed(aid: str, row: dict) -> None:
    """`row` held, then flipped to chargedback by the disputes path (its amount off lifetime)."""
    await ti._write_page(aid, [row | {"status": "done"}])
    r = await cb.apply_chargebacks(aid, [_dispute(row)])
    assert r["applied"] == 1, r


async def _rewalk(aid: str) -> None:
    async with get_session() as s:
        scan = await s.get(TransactionScanHistory, aid)
        scan.fully_backfilled, scan.oldest_seen_occurred_at = False, None


async def case_a_walk_rereading_a_disputed_row_applies_its_amount_at_most_once():
    """Whatever the ledger says of a row the disputes path already reversed, three whole walks
    leave status and lifetime agreeing, and the amount is off once or back once, never twice."""
    at = _now() - timedelta(days=20)
    for n, (ledger, listed, want_status, want_lifetime) in enumerate([
        ("undo", True, "chargedback", 300),             # the ledger caught up: nothing moves
        ("done", True, "chargedback", 300),             # disagrees, the dispute stands: back, off again
        ("pending_return", True, "chargedback", 300),   # the same out of a still-revenue status
        ("undo", False, "chargedback", 300),            # the dispute aged out of the list
        ("done", False, "cleared", 800),                # no dispute any more: OF's ledger wins, once
        ("refunded", True, "refunded", 300),            # reversal to reversal: no second deduct
        ("failed", True, "failed", 800),                # #287's rule: leaving a reversal puts it back
    ]):
        aid = f"bf_cb_{n}"
        await _account(aid)
        sale = _row(f"sale{n}", at, cents=500)
        other = _row(f"other{n}", at - timedelta(days=1), cents=300)
        await ti._write_page(aid, [other])
        await _disputed(aid, sale)
        assert await _lifetime(aid) == 300
        of = _OF([sale | {"status": ledger}, other])
        of.disputes = [_dispute(sale)] if listed else []
        for _ in range(3):
            await _rewalk(aid)
            await _walk(aid, of)
            case = (ledger, listed, await _status(aid, f"sale{n}"), await _lifetime(aid))
            assert case[2:] == (want_status, want_lifetime), case
        await _exactly(aid, [sale, other])


async def case_a_backfill_tick_that_moved_a_row_out_of_a_reversal_polls_short_of_complete():
    """Should a dispute stand on a row the ledger calls `done` (0 of 89 measured, not ruled out)
    the marker page puts it back; the tick's poll takes it off again, walk done or not."""
    aid = "bf_cb_partial"
    await _account(aid)
    rows = _spread(150, newest_h=48)
    sale = rows[50]
    await _disputed(aid, sale)
    of = _OF(rows)
    of.disputes = [_dispute(sale)]
    of.answer = lambda q, body: body if q.get("marker") is None else {"list": [], "hasMore": False}
    res = await _tick(aid, of)
    scan = await _scan(aid)
    assert res["error"] is None and not scan.fully_backfilled and scan.current_status == "backfill_stalled", res
    assert len(of.cb_wire) == 1, of.cb_wire
    assert await _status(aid, sale["id"]) == "chargedback"
    assert await _lifetime(aid) == 100 * 99, "every sale of the page but the disputed one"


async def case_a_tick_failing_after_it_moved_a_row_out_of_a_reversal_polls_too():
    aid = "bf_cb_failed"
    await _account(aid)
    rows = _spread(150, newest_h=48)
    sale = rows[50]
    await _disputed(aid, sale)
    of = _OF(rows)
    of.disputes = [_dispute(sale)]

    def fail(q: dict) -> None:
        if q.get("marker") is not None:
            raise RuntimeError("OF 500")

    of.before = fail
    assert (await _tick(aid, of))["error"], "the marker page failed"
    assert len(of.cb_wire) == 1, of.cb_wire
    assert await _status(aid, sale["id"]) == "chargedback"
    assert await _lifetime(aid) == 100 * 99
    of.before = None
    await _walk(aid, of)
    assert await _status(aid, sale["id"]) == "chargedback"
    assert await _lifetime(aid) == 100 * 149
    await _exactly(aid, rows)


async def case_a_dispute_on_a_row_the_walk_has_not_reached_applies_once_it_lands():
    aid = "bf_cb_later"
    await _account(aid)
    rows = _spread(350, newest_h=48)
    sale = rows[320]
    of = _OF(rows)
    of.disputes = [_dispute(sale)]
    cap, ti._BACKFILL_TICK_PAGES = ti._BACKFILL_TICK_PAGES, 1
    try:
        await _tick(aid, of)
        assert not await _rows_of(aid, sale["id"]), "the walk is pages above it"
        assert await _walk(aid, of) > 1
    finally:
        ti._BACKFILL_TICK_PAGES = cap
    assert await _status(aid, sale["id"]) == "chargedback"
    assert await _lifetime(aid) == 100 * 349
    await _exactly(aid, rows)


async def _rows_of(aid: str, pid: str) -> int:
    return (await _held(aid))[pid]


async def case_a_walks_flip_is_capped_and_the_polls_is_announced():
    """Both flips of a disagreeing old row: the walk's stays quiet (the cap), the poll's is the
    news #287 announces; the poll runs outside the walk's cap."""
    aid = "bf_cb_sse"
    await _account(aid)
    sale = _row("old", _now() - timedelta(days=20), cents=500)
    await _disputed(aid, sale)
    of = _OF([sale | {"status": "done"}])
    of.disputes = [_dispute(sale)]
    announced: list = []
    real = events.announce_transaction

    async def spy(account_id, fan_id, *, occurred_at=None, capped=False, status=None, **kw):
        announced.append((status, capped))

    events.announce_transaction = spy
    try:
        await _walk(aid, of)
    finally:
        events.announce_transaction = real
    assert announced == [("cleared", True), ("chargedback", False)], announced


def _at(raw: dict) -> datetime:
    return datetime.fromisoformat(raw["createdAt"]).replace(tzinfo=None)


async def _interrupted_walk(aid: str, per_day: int = 110, old: int = 800) -> tuple[_OF, list[dict]]:
    """A walk two pages in, on a Creator making `per_day` rows, then 14 days of session
    outage: rows well past OF's 600-row offset cap landed above the walk's top."""
    await _account(aid)
    step = 86400 // per_day
    below = _spread(old, newest_h=24 * 15, step_s=step, prefix="o")
    of = _OF(below)
    cap, ti._BACKFILL_TICK_PAGES = ti._BACKFILL_TICK_PAGES, 2
    try:
        await _tick(aid, of)
    finally:
        ti._BACKFILL_TICK_PAGES = cap
    scan = await _scan(aid)
    assert scan.newest_seen_occurred_at == _at(below[0]) and not scan.fully_backfilled, scan
    gap = _spread(14 * per_day, newest_h=1, step_s=step, prefix="g")
    of.rows = [*gap, *below]
    return of, of.rows


async def case_an_outage_past_the_offset_cap_is_read_whole_before_complete():
    """Finding 1: 110 rows a day, 14 days off mid-walk, 1540 rows above the walk's top."""
    aid = "bf_gap"
    of, rows = await _interrupted_walk(aid)
    await _walk(aid, of)
    await _exactly(aid, rows)
    assert await _lifetime(aid) == 100 * len(rows)


async def case_a_read_short_of_the_gap_clears_the_cursor_and_walks_from_the_top():
    aid = "bf_gap_top"
    of, rows = await _interrupted_walk(aid)
    n = len(of.wire)
    cap, ti._BACKFILL_TICK_PAGES = ti._BACKFILL_TICK_PAGES, 2
    try:
        await _tick(aid, of)
    finally:
        ti._BACKFILL_TICK_PAGES = cap
    sent = of.wire[n:]
    assert [w["offset"] for w in sent[:6]] == [0, 100, 200, 300, 400, 500], sent[:6]
    assert "marker" not in sent[6] and sent[6]["offset"] == 0, sent[6:]
    assert sent[7]["marker"] == _epoch(rows[100]) and len(sent) == 8, sent[6:]
    scan = await _scan(aid)
    assert (scan.oldest_seen_occurred_at, scan.newest_seen_occurred_at) == (_at(rows[199]), _at(rows[0])), scan
    assert not scan.fully_backfilled


async def case_a_refresh_between_outage_and_resume_cannot_hide_the_gap():
    """The full walk's top must not move newest_seen on an unfinished walk."""
    aid = "bf_gap_refresh"
    of, rows = await _interrupted_walk(aid)
    was = (await _scan(aid)).newest_seen_occurred_at
    await _tick(aid, of, mode="refresh")
    assert (await _scan(aid)).newest_seen_occurred_at == was, "a refresh hid the gap"
    await _walk(aid, of)
    await _exactly(aid, rows)


async def case_a_recent_read_cut_short_moves_no_newest_seen():
    """A failed read leaves newest_seen where it is, or the next read would stop above the gap."""
    aid = "bf_gap_fail"
    of, rows = await _interrupted_walk(aid)
    was = (await _scan(aid)).newest_seen_occurred_at

    def fail(q: dict) -> None:
        if q["offset"] == 300:
            raise RuntimeError("OF 500")

    of.before = fail
    assert (await _tick(aid, of))["error"]
    assert (await _scan(aid)).newest_seen_occurred_at == was, "the read's first pages moved newest_seen"
    of.before = None
    await _walk(aid, of)
    await _exactly(aid, rows)


async def case_a_gap_under_the_cap_keeps_the_cursor():
    aid = "bf_gap_small"
    of, rows = await _interrupted_walk(aid)
    of.rows = rows[-800 - 300:]   # 300 rows above the walk's top: the read reaches it
    cursor = (await _scan(aid)).oldest_seen_occurred_at
    n = len(of.wire)
    await _tick(aid, of)
    walk = [w for w in of.wire[n:] if "marker" in w]
    assert walk[0]["marker"] == calendar.timegm(cursor.timetuple()), walk[0]
    await _walk(aid, of)
    await _exactly(aid, of.rows)


async def case_a_recent_read_blank_on_its_first_page_walks_nothing():
    aid = "bf_read_blank"
    of, rows = await _interrupted_walk(aid)
    was = await _scan(aid)
    of.answer = lambda q, body: {"list": [], "hasMore": False, "nextMarker": None}
    n = len(of.wire)
    await _tick(aid, of)
    assert len(of.wire) == n + 1, of.wire[n:]
    scan = await _scan(aid)
    assert scan.oldest_seen_occurred_at == was.oldest_seen_occurred_at
    assert scan.newest_seen_occurred_at == was.newest_seen_occurred_at
    assert scan.current_status == "backfill_stalled" and not scan.fully_backfilled, scan
    of.answer = None
    await _walk(aid, of)
    await _exactly(aid, rows)


async def case_a_stopped_walk_says_why_and_refreshes_when_a_full_walk_is_due():
    """Finding 2: stops other than tick_cap never read green, full walks still run, their
    disputes poll with them, and the cursor stays."""
    aid = "bf_stall"
    await _account(aid)
    rows = _spread(350, step_s=4000)
    sale = rows[10]
    of = _OF(rows)
    of.disputes = [_dispute(sale)]
    of.answer = lambda q, body: {**body, "nextMarker": None}
    assert (await _tick(aid, of))["error"] is None
    scan = await _scan(aid)
    assert not scan.fully_backfilled and scan.current_status == "backfill_stalled", scan
    assert scan.last_error == "backfill_stopped: no_next_marker", scan.last_error
    cursor = scan.oldest_seen_occurred_at
    await _unstamp(aid)
    assert await ti._decide_mode(aid) == "refresh", "a stalled walk must not stop the full walks"
    of.rows = [sale | {"status": "pending_return"}, *rows[:10], *rows[11:]]
    assert (await _tick(aid, of, mode="refresh"))["error"] is None
    scan = await _scan(aid)
    assert scan.oldest_seen_occurred_at == cursor, "a refresh moved the walk's cursor"
    assert scan.current_status == "backfill_stalled", "the refresh hid the stall"
    assert scan.last_error == "backfill_stopped: no_next_marker", scan.last_error
    assert of.cb_wire, "the full walk polls disputes"
    assert await _status(aid, sale["id"]) == "chargedback"
    assert await ti._decide_mode(aid) == "backfill", "this period's full walk is done"
    of.answer = None
    await _walk(aid, of)
    scan = await _scan(aid)
    assert scan.fully_backfilled and scan.current_status == "ok" and scan.last_error is None, scan
    await _exactly(aid, rows)


async def case_a_refresh_cut_short_on_an_unfinished_walk_still_gives_the_walk_its_turn():
    aid = "bf_stall_short"
    await _account(aid)
    rows = _spread(350, step_s=4000)
    of = _OF(rows)
    of.answer = lambda q, body: {**body, "nextMarker": None}
    await _tick(aid, of)
    of.answer = lambda q, body: {**body, "list": rows[:100], "hasMore": True}   # the repeated-page guard
    await _unstamp(aid)
    await _tick(aid, of, mode="refresh")
    assert await ti._decide_mode(aid) == "backfill", "a walk starved by refreshes that never finish"


async def case_a_failing_refresh_on_an_unfinished_walk_still_gives_the_walk_its_turn():
    """Round 2, B: a full walk that keeps failing would freeze the walk behind it, then pause it."""
    aid = "bf_refresh_fails"
    await _account(aid)
    of = _OF(_spread(350, step_s=4000))
    cap, ti._BACKFILL_TICK_PAGES = ti._BACKFILL_TICK_PAGES, 1
    try:
        await _tick(aid, of)
    finally:
        ti._BACKFILL_TICK_PAGES = cap
    cursor = (await _scan(aid)).oldest_seen_occurred_at
    await _unstamp(aid)
    assert await ti._decide_mode(aid) == "refresh"

    def down(_q):
        raise RuntimeError("OF down")

    of.before = down
    res = await _tick(aid, of, mode="refresh")
    assert res["error"], res
    assert await ti._decide_mode(aid) == "backfill", "a walk frozen behind a failing refresh"
    assert (await _scan(aid)).oldest_seen_occurred_at == cursor
    of.before = None
    await _walk(aid, of)
    await _exactly(aid, of.rows)


async def case_a_failing_refresh_on_a_finished_account_spends_its_period():
    aid = "bf_refresh_fails_done"
    await _account(aid, cursor=_floor(), full=True)
    of = _OF(_spread(50, step_s=4000))

    def down(_q):
        raise RuntimeError("OF down")

    of.before = down
    await _unstamp(aid)
    res = await _tick(aid, of, mode="refresh")
    scan = await _scan(aid)
    assert res["error"] and scan.current_status == "error" and scan.consecutive_failures == 1, scan
    # One full walk per period, a failed one too (AE 2026-11-08: re-walked every tick until paused).
    assert scan.last_full_at is not None and await ti._decide_mode(aid) == "recent"


async def case_a_short_reactivation_past_600_rows_reads_the_whole_gap_and_completes_again():
    """Round 2, A: 6 days off at 111 rows a day. The full walk alone reads the latest 600."""
    aid = "bf_short_gap"
    await _account(aid)
    off_at = _now() - timedelta(days=6)
    old = _spread(200, newest_h=6 * 24 + 1, step_s=600, prefix="old")
    of = _OF(old)
    await _walk(aid, of)
    gap = _spread(666, newest_h=0.5, step_s=776, prefix="gap")
    of.rows = [*gap, *old]
    of.wire.clear()
    await _unstamp(aid)
    await ti.backfill_after_reactivation(aid, off_at)
    for _ in range(4):
        await _tick(aid, of, mode=await ti._decide_mode(aid))
    await _exactly(aid, of.rows)
    assert await _lifetime(aid) == sum(round(r["amount"] * 100) for r in of.rows)
    scan = await _scan(aid)
    assert scan.fully_backfilled and scan.current_status == "ok", scan
    assert scan.backfill_floor == off_at, scan.backfill_floor
    assert of.wire[0]["startDate"] == (off_at - timedelta(days=1)).date().isoformat(), of.wire[0]


async def case_a_ws_only_tip_does_not_stall_a_cold_account_with_no_ledger():
    """Round 2, E: a pump's tip holds no ledger row (no provider id), so it says nothing about a blank page."""
    aid = "bf_ws_only"
    await _account(aid)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=FAN))
        s.add(Transaction(account_id=aid, fan_id=FAN, amount_cents=500, kind="tip", status="cleared",
                          source="ws", occurred_at=_now() - timedelta(hours=1)))
    await _tick(aid, _OF([]))
    scan = await _scan(aid)
    assert scan.fully_backfilled and scan.current_status == "ok", scan


async def case_a_ws_only_tip_cannot_complete_a_blank_answer_with_rows_behind_it():
    aid = "bf_ws_blank"
    await _account(aid)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=FAN))
        s.add(Transaction(account_id=aid, fan_id=FAN, amount_cents=500, kind="tip", status="cleared",
                          source="ws", occurred_at=_now() - timedelta(hours=1)))
    of = _OF(_spread(150, step_s=4000))
    of.answer = lambda q, body: ({"hasMore": False, "list": [], "marker": None} if "startDate" in q else body)
    await _tick(aid, of)
    scan = await _scan(aid)
    assert not scan.fully_backfilled and scan.current_status == "backfill_stalled", scan


async def case_a_tick_cap_stays_partial_and_green():
    aid = "bf_cap_green"
    await _account(aid)
    of = _OF(_spread(350, step_s=4000))
    cap, ti._BACKFILL_TICK_PAGES = ti._BACKFILL_TICK_PAGES, 1
    try:
        await _tick(aid, of)
    finally:
        ti._BACKFILL_TICK_PAGES = cap
    scan = await _scan(aid)
    assert scan.current_status == "backfill_partial" and scan.last_error is None, scan


async def case_a_blank_first_page_with_rows_behind_it_never_completes():
    """Finding 3: a reactivation whose first page comes back blank would be done for good."""
    aid = "bf_blank"
    await _account(aid)
    rows = _spread(150, step_s=4000)
    of = _OF(rows)
    of.answer = lambda q, body: body if "startDate" not in q else {"list": [], "hasMore": False, "nextMarker": None}
    assert (await _tick(aid, of))["error"] is None
    scan = await _scan(aid)
    assert not scan.fully_backfilled and scan.current_status == "backfill_stalled", scan
    assert scan.last_error == "backfill_stopped: blank_first_page", scan.last_error
    probe = of.wire[-1]
    assert probe["limit"] == 1 and "startDate" not in probe and "marker" not in probe, of.wire
    of.answer = None
    await _walk(aid, of)
    await _exactly(aid, rows)


async def case_a_real_empty_window_completes_once_the_probe_says_so():
    floor = _floor()
    old, new = "bf_empty_old", "bf_empty_new"
    await _account(old, floor=floor)
    await _account(new, floor=floor)
    of = _OF([_row("before", floor - timedelta(days=3))])   # the no-filter row sits below startDate
    await _tick(old, of)
    assert (await _scan(old)).fully_backfilled, of.wire
    assert of.wire[-1]["limit"] == 1, of.wire
    await _tick(new, _OF([]))
    assert (await _scan(new)).fully_backfilled, "a Creator with no rows at all is done"


async def case_a_blank_probe_on_an_account_holding_rows_never_completes():
    floor = _floor()
    aid = "bf_blank_held"
    await _account(aid, floor=floor)
    async with get_session() as s:
        s.add(Transaction(account_id=aid, fan_id=FAN, amount_cents=1, kind="tip", status="cleared",
                          provider_transaction_id="held", source="ledger", occurred_at=floor - timedelta(days=3)))
    await _tick(aid, _OF([]))
    scan = await _scan(aid)
    assert not scan.fully_backfilled and scan.current_status == "backfill_stalled", scan


async def case_a_second_trigger_on_an_unfinished_backfill_keeps_the_older_floor():
    """Finding 4: reactivated, walked part of the way, reactivated again: the older gap stays asked for."""
    aid = "bf_floor"
    older, later = _now() - timedelta(days=60), _now() - timedelta(days=20)
    await _account(aid, floor=older)
    await ti.trigger_backfill(aid, since=later)
    assert (await _scan(aid)).backfill_floor == older, "the second trigger dropped [older, later)"
    await ti.trigger_backfill(aid, since=older - timedelta(days=1))
    assert (await _scan(aid)).backfill_floor == older - timedelta(days=1)
    async with get_session() as s:
        (await s.get(TransactionScanHistory, aid)).fully_backfilled = True
    await ti.trigger_backfill(aid, since=later)
    assert (await _scan(aid)).backfill_floor == later, "a finished walk's floor is no debt"


async def case_a_last_page_without_has_more_stops_not_complete():
    """Finding 5: only hasMore false says the end; 0 of 101 pages lacked it (measured)."""
    aid = "bf_no_has_more"
    await _account(aid)
    rows = _spread(50, step_s=4000)
    of = _OF(rows)

    def answer(_q, body):
        return {k: v for k, v in body.items() if k != "hasMore"}

    of.answer = answer
    await _tick(aid, of)
    scan = await _scan(aid)
    assert not scan.fully_backfilled and scan.current_status == "backfill_stalled", scan
    assert scan.last_error == "backfill_stopped: no_has_more", scan.last_error
    of.answer = None
    await _walk(aid, of)
    await _exactly(aid, rows)


async def case_a_tick_moving_no_row_out_of_a_reversal_polls_no_disputes():
    """Findings 6+7: dispute `undo` with ledger `done`: 0 of 89 measured; no per-tick spend on it."""
    aid = "bf_cb_quiet"
    await _account(aid)
    rows = _spread(350, newest_h=48)
    of = _OF(rows)
    of.disputes = [_dispute(rows[300])]
    cap, ti._BACKFILL_TICK_PAGES = ti._BACKFILL_TICK_PAGES, 1
    try:
        await _tick(aid, of)
        assert of.cb_wire == [], "nothing moved out of a reversal"
        await _walk(aid, of)
    finally:
        ti._BACKFILL_TICK_PAGES = cap
    assert len(of.cb_wire) == 1, "the completed walk's own poll, once"
    assert await _status(aid, rows[300]["id"]) == "chargedback"


async def case_a_poll_that_fails_is_retried_by_the_next_tick():
    aid = "bf_cb_retry"
    await _account(aid)
    rows = _spread(350, newest_h=48)
    sale = rows[50]
    await _disputed(aid, sale)
    of = _OF(rows)
    of.disputes = [_dispute(sale)]
    real, calls = of.chargebacks, []

    def boom(**kw):
        calls.append(kw)
        raise RuntimeError("OF 500")

    of.chargebacks = boom
    cap, ti._BACKFILL_TICK_PAGES = ti._BACKFILL_TICK_PAGES, 1
    try:
        await _tick(aid, of)
        assert calls, "the reinstate asked for a poll"
        assert await _status(aid, sale["id"]) == "cleared" and await _lifetime(aid) == 100 * 100
        of.chargebacks = real
        await _tick(aid, of)
        assert of.cb_wire, "the next tick retries the poll"
    finally:
        ti._BACKFILL_TICK_PAGES = cap
    assert await _status(aid, sale["id"]) == "chargedback"


async def case_a_ledger_undo_with_a_dispute_done_stays_reversed():
    """The measured contradiction (id 23b743c7): dispute `done`, ledger `undo`, OF stats count it
    earned. #287's rule: the ledger's undo is held as chargedback, the dispute's done writes
    nothing, so we count it reversed; pinned, not endorsed."""
    aid = "bf_cb_contra"
    await _account(aid)
    sale = _row("contra", _now() - timedelta(days=87), cents=1101, status="undo")
    keep = _row("keep", _now() - timedelta(days=88), cents=300)
    of = _OF([sale, keep])
    of.disputes = [_dispute(sale, status="done")]
    await _walk(aid, of)
    assert of.cb_wire, "the completed walk polled"
    assert await _status(aid, "contra") == "chargedback"
    assert await _lifetime(aid) == 300


async def case_a_tip_held_one_second_off_the_ledger_is_promoted_once_and_the_cursor_is_ofs():
    """26 tips measured with OF's createdAt 1 s before the WS row's occurred_at (the pump's clock).
    The cursor comes from OF's stamp; a held WS tip is promoted by fingerprint, never doubled."""
    aid = "bf_ws_clock"
    await _account(aid)
    rows = _spread(150, newest_h=48)
    tip = rows[99]     # the page's last row: the cursor's own second
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=FAN, lifetime_spend_cents=100))
        s.add(Transaction(account_id=aid, fan_id=FAN, amount_cents=100, kind="tip", status="pending",
                          occurred_at=_at(tip) + timedelta(seconds=1)))
    of = _OF(rows)
    cap, ti._BACKFILL_TICK_PAGES = ti._BACKFILL_TICK_PAGES, 1
    try:
        await _tick(aid, of)
    finally:
        ti._BACKFILL_TICK_PAGES = cap
    assert (await _scan(aid)).oldest_seen_occurred_at == _at(tip), "the cursor sits on OF's stamp"
    await _walk(aid, of)
    await _exactly(aid, rows)
    assert await _lifetime(aid) == 100 * 150, "promoted, not added"


async def case_steady_state_walks_keep_their_wire():
    """Not the backfill's: recent keeps offset paging and its startDate, full sends none."""
    aid = "bf_steady"
    await _account(aid, full=True, cursor=_floor())
    of = _OF(_spread(30, step_s=60))
    await _tick(aid, of, mode="recent")
    assert len(of.wire) == 1 and "marker" not in of.wire[0] and "startDate" in of.wire[0], of.wire
    of.wire.clear()
    await _tick(aid, of, mode="refresh")
    assert len(of.wire) == 1 and "marker" not in of.wire[0] and "startDate" not in of.wire[0], of.wire
    async with get_session() as s:
        count = (await s.execute(select(func.count()).select_from(Transaction).where(
            Transaction.account_id == aid))).scalar_one()
    assert count == 30


_harness.run()
