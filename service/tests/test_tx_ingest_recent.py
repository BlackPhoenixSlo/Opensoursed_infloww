#!/usr/bin/env python3
"""
The ledger tick: a `recent` walk (trailing 24 h) every tick, the full 7-day
`refresh` once per _FULL_EVERY_S period at the account's crc32 phase (and first
after a restart). On the real run_one_tick with a fake OF client:

    case_recent_tick_is_one_call_over_24h      one transactions GET, start ~ now-24h, on the
        wire startDate=YYYY-MM-DD a day before the window (OF answers an ISO one with
        nothing); stamps last_scan_at/'ok' (green), never moves the backfill watermark
    case_due_full_walks_7d_and_stamps           pages the 7-day window (no startDate on the
        wire: OF's latest 600), stamps _last_full_at
    case_backfill_sends_a_date_only_start_date  the backfill's wire: startDate a day before its
        floor, date only (its walk: test_tx_ingest_backfill.py)
    case_failed_full_does_not_stamp             a page that raises: no stamp, next is full again
    case_truncated_full_does_not_stamp          OF ignoring `offset` (repeated page): no stamp
    case_window_ignored_warns_once              a recent page with a row > 1 day before startDate logs
        ingest_tx_recent_window_ignored once per account per process; the rows still land
    case_inside_slack_no_warning                a row < 1 day before startDate: no warning
    case_recent_empty_walk_warns_once           0 rows while the DB holds a row on/after the
        startDate sent: ingest_tx_recent_walk_empty once per account per process; still 'ok'
    case_quiet_account_empty_walk_no_warning    0 rows, newest held row before the startDate
    case_supervisor_passes_the_mode             supervisor_cycle ticks with the decided mode
    case_health_exposes_last_full_scan_at

Run: ./venv/bin/python service/tests/test_tx_ingest_recent.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import logging  # noqa: E402
import re  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import of_client  # noqa: E402
import transaction_ingest as ti  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Transaction, TransactionScanHistory  # noqa: E402

ACCT = "77001"
OLDEST = datetime(2026, 8, 1)
ti._PAGE_SLEEP_S = 0.0


class _Fake:
    """OF's ledger: `pages` answered in order (a callable raises); every call's kwargs kept,
    and in `wire` the query params the real OFClient.transactions sends for them."""

    def __init__(self, pages):
        self.pages, self.calls, self.wire = list(pages), [], []

    def transactions(self, **kw):
        self.calls.append(kw)
        rec = of_client.OFClient.__new__(of_client.OFClient)
        rec.get_json = lambda path, params=None: self.wire.append(params) or {}
        of_client.OFClient.transactions(rec, **kw)
        p = self.pages.pop(0) if self.pages else {"list": [], "hasMore": False}
        if callable(p):
            p()
        return p


def _row(pid: str, at: datetime) -> dict:
    return {"id": pid, "user": {"id": 555}, "amount": 5.0, "net": 4.0, "fee": 1.0,
            "createdAt": at.isoformat() + "Z", "status": "done", "description": "Tip from u555"}


def _page(rows, more=False) -> dict:
    return {"list": rows, "hasMore": more}


def _boom():
    raise RuntimeError("OF 500")


async def _ready() -> None:
    """A fully backfilled account, idle, no full walk in this process."""
    async with get_session() as s:
        if await s.get(Account, ACCT) is None:
            s.add(Account(id=ACCT, nickname="recent"))
    async with get_session() as s:
        row = await s.get(TransactionScanHistory, ACCT)
        if row is None:
            row = TransactionScanHistory(account_id=ACCT)
            s.add(row)
        row.fully_backfilled = True
        row.backfill_floor = OLDEST
        row.oldest_seen_occurred_at = OLDEST
        row.newest_seen_occurred_at = None
        row.current_status = "ok"
        row.consecutive_failures = 0
        row.paused_until = None
    ti._last_full_at.pop(ACCT, None)
    ti._recent_window_warned.discard(ACCT)
    ti._recent_empty_warned.discard(ACCT)


def _period_start() -> datetime:
    """Start of ACCT's current full-walk period (a walk stamped here makes this period's ticks recent)."""
    full, ph = ti._FULL_EVERY_S, ti.full_phase_s(ACCT, ti._FULL_EVERY_S)
    b = ti.full_bucket(datetime.utcnow(), full_every_s=full, phase_s=ph)
    return datetime(1970, 1, 1) + timedelta(seconds=b * full - ph)


async def _tick(fake: _Fake) -> tuple[str, dict]:
    """Decide the mode as the supervisor does, then run the tick on `fake`."""
    mode = await ti._decide_mode(ACCT)
    orig = ti._client_for
    ti._client_for = lambda _aid: fake
    try:
        return mode, await ti.run_one_tick(ACCT, mode=mode)
    finally:
        ti._client_for = orig


async def _scan() -> TransactionScanHistory:
    async with get_session() as s:
        return await s.get(TransactionScanHistory, ACCT)


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _near(a: datetime, b: datetime, s: float = 5.0) -> bool:
    return abs((a - b).total_seconds()) <= s


async def case_recent_tick_is_one_call_over_24h():
    await _ready()
    full_at = _period_start()
    ti._last_full_at[ACCT] = full_at
    now = datetime.utcnow()
    fake = _Fake([_page([_row("r1", now - timedelta(hours=3)), _row("r2", now - timedelta(hours=20))])])
    mode, res = await _tick(fake)
    assert mode == "recent", mode
    assert res["error"] is None and res["pages"] == 1 and res["rows_inserted"] == 2, res
    assert len(fake.calls) == 1, fake.calls
    c = fake.calls[0]
    assert _near(_at(c["start"]), now - timedelta(hours=24)) and _near(_at(c["end"]), now), c
    assert (c["limit"], c["offset"]) == (ti._PAGE_LIMIT, 0), c
    sd = fake.wire[0]["startDate"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", sd), f"startDate must be date-only, never ISO: {sd!r}"
    assert sd == (_at(c["start"]) - timedelta(days=1)).date().isoformat(), (sd, c["start"])
    assert ti._last_full_at[ACCT] == full_at, "a recent walk must not reset the full-walk clock"
    row = await _scan()
    assert row.current_status == "ok" and _near(row.last_scan_at, datetime.utcnow()), row.current_status
    assert row.oldest_seen_occurred_at == OLDEST, row.oldest_seen_occurred_at
    assert (row.fully_backfilled, row.backfill_floor) == (True, OLDEST)


async def case_due_full_walks_7d_and_stamps():
    await _ready()
    ti._last_full_at[ACCT] = _period_start() - timedelta(seconds=1)   # last period
    now = datetime.utcnow()
    fake = _Fake([_page([_row("f1", now - timedelta(days=1))], more=True),
                  _page([_row("f2", now - timedelta(days=6))])])
    before = datetime.utcnow()
    mode, res = await _tick(fake)
    assert mode == "refresh", mode
    assert res["error"] is None and res["pages"] == 2, res
    assert [c["offset"] for c in fake.calls] == [0, 1], fake.calls
    assert all(_near(_at(c["start"]), now - timedelta(days=7)) for c in fake.calls), fake.calls
    assert not any("startDate" in w for w in fake.wire), fake.wire
    assert ti._last_full_at[ACCT] >= before, ti._last_full_at
    assert (await ti._decide_mode(ACCT)) == "recent", "right after a full walk the next is recent"
    # Restart: the in-memory clock is gone -> the first tick is full again.
    ti._last_full_at.clear()
    assert (await ti._decide_mode(ACCT)) == "refresh"


async def case_backfill_sends_a_date_only_start_date():
    await _ready()
    async with get_session() as s:
        row = await s.get(TransactionScanHistory, ACCT)
        row.fully_backfilled = False
        row.oldest_seen_occurred_at = None
    fake = _Fake([_page([_row("b1", datetime.utcnow() - timedelta(days=2))])])
    mode, res = await _tick(fake)
    assert mode == "backfill" and res["error"] is None and fake.wire, (mode, res, fake.wire)
    assert fake.wire == [{"limit": 100, "offset": 0, "startDate": "2026-07-31"}], fake.wire


async def case_failed_full_does_not_stamp():
    await _ready()
    fake = _Fake([_page([_row("x1", datetime.utcnow() - timedelta(days=2))], more=True), _boom])
    mode, res = await _tick(fake)
    assert mode == "refresh" and res["error"] and "OF 500" in res["error"], (mode, res)
    assert ACCT not in ti._last_full_at, "a failed full walk stamped the full-walk clock"
    assert (await ti._decide_mode(ACCT)) == "refresh", "after a failed full walk the next must be full"


async def case_truncated_full_does_not_stamp():
    await _ready()
    same = _page([_row("t1", datetime.utcnow() - timedelta(days=2))], more=True)
    fake = _Fake([same, same])
    mode, res = await _tick(fake)
    assert mode == "refresh" and res["error"] is None and res["pages"] == 1, (mode, res)
    assert len(fake.calls) == 2, fake.calls
    assert ACCT not in ti._last_full_at, "a walk cut short by the repeated-page guard stamped"


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.msgs: list[str] = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


async def case_window_ignored_warns_once():
    await _ready()
    ti._last_full_at[ACCT] = _period_start()
    grab = _Grab()
    ti.log.addHandler(grab)
    try:
        for n in range(2):
            now = datetime.utcnow()
            fake = _Fake([_page([_row(f"w{n}a", now - timedelta(hours=2)),
                                 _row(f"w{n}b", now - timedelta(days=5))])])
            mode, res = await _tick(fake)
            assert mode == "recent" and res["error"] is None and res["rows_inserted"] == 2, (mode, res)
    finally:
        ti.log.removeHandler(grab)
    hits = [m for m in grab.msgs if m.startswith("ingest_tx_recent_window_ignored")]
    assert len(hits) == 1, grab.msgs
    assert f"account={ACCT} " in hits[0] and "oldest=" in hits[0] and "window_start=" in hits[0], hits
    assert re.search(r"window_start=\d{4}-\d{2}-\d{2}$", hits[0]), hits   # the startDate sent
    async with get_session() as s:
        n = (await s.execute(select(func.count()).select_from(Transaction).where(
            Transaction.account_id == ACCT, Transaction.provider_transaction_id.in_(
                ["w0a", "w0b", "w1a", "w1b"])))).scalar()
    assert n == 4, f"rows outside the window must still land (got {n})"


async def case_inside_slack_no_warning():
    await _ready()
    ti._last_full_at[ACCT] = _period_start()
    grab = _Grab()
    ti.log.addHandler(grab)
    try:
        now = datetime.utcnow()
        sd = datetime.fromisoformat(ti.recent_start_date(now - timedelta(hours=ti._RECENT_WINDOW_H)))
        await _tick(_Fake([_page([_row("s1", now - timedelta(hours=24, minutes=30)),
                                  _row("s2", sd - timedelta(hours=23))])]))
    finally:
        ti.log.removeHandler(grab)
    assert not [m for m in grab.msgs if "recent_window_ignored" in m], grab.msgs


async def _set_newest(at: datetime) -> None:
    async with get_session() as s:
        (await s.get(TransactionScanHistory, ACCT)).newest_seen_occurred_at = at


async def case_recent_empty_walk_warns_once():
    await _ready()
    ti._last_full_at[ACCT] = _period_start()
    await _set_newest(datetime.utcnow() - timedelta(hours=2))
    grab = _Grab()
    ti.log.addHandler(grab)
    try:
        for _ in range(2):
            mode, res = await _tick(_Fake([_page([])]))
            assert mode == "recent" and res["error"] is None and res["rows_inserted"] == 0, (mode, res)
    finally:
        ti.log.removeHandler(grab)
    hits = [m for m in grab.msgs if m.startswith("ingest_tx_recent_walk_empty")]
    assert len(hits) == 1, grab.msgs
    assert re.fullmatch(rf"ingest_tx_recent_walk_empty account={ACCT} start_date=\d{{4}}-\d{{2}}-\d{{2}} "
                        r"newest_seen=\S+", hits[0]), hits
    assert (await _scan()).current_status == "ok"


async def case_quiet_account_empty_walk_no_warning():
    await _ready()
    ti._last_full_at[ACCT] = _period_start()
    await _set_newest(datetime.utcnow() - timedelta(days=5))
    grab = _Grab()
    ti.log.addHandler(grab)
    try:
        mode, res = await _tick(_Fake([_page([])]))
    finally:
        ti.log.removeHandler(grab)
    assert mode == "recent" and res["error"] is None, (mode, res)
    assert not [m for m in grab.msgs if "recent_walk_empty" in m], grab.msgs


async def case_supervisor_passes_the_mode():
    await _ready()
    ticked = []

    async def _sup(aid, mode):
        ticked.append((aid, mode))
        return {}

    async def _only():
        return [ACCT]

    saved = ti.supervised_tick, ti._live_account_ids
    ti.supervised_tick, ti._live_account_ids = _sup, _only
    try:
        await ti.supervisor_cycle()
        ti._last_full_at[ACCT] = _period_start()
        await ti.supervisor_cycle()
    finally:
        ti.supervised_tick, ti._live_account_ids = saved
    assert ticked == [(ACCT, "refresh"), (ACCT, "recent")], ticked


async def case_health_exposes_last_full_scan_at():
    """The /health payload (unscoped: no signed-in principal, as internal curl)."""
    from tx_ingest_admin_api import admin_ingest_tx_health
    at = datetime(2026, 11, 7, 9, 30)
    ti._last_full_at[ACCT] = at
    try:
        rows = {a["account_id"]: a for a in (await admin_ingest_tx_health())["accounts"]}
        assert rows[ACCT]["last_full_scan_at"] == at.isoformat(), rows[ACCT]
        ti._last_full_at.pop(ACCT)
        rows = {a["account_id"]: a for a in (await admin_ingest_tx_health())["accounts"]}
        assert rows[ACCT]["last_full_scan_at"] is None, rows[ACCT]
    finally:
        ti._last_full_at.pop(ACCT, None)


_harness.run()
