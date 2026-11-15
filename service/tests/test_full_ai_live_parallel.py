#!/usr/bin/env python3
"""test_full_ai_live_parallel — Full AI Chat jobs for different Fans of one Creator overlap.

Through the executor (`_drain_due_jobs_once` -> plan_dispatch -> run_once -> the kind):

  case_two_fans_overlap_real_path  two Fans' DMs: both live Turns start before either ends;
                                   both reply, one row each
  case_paced_sends_one_at_a_time   those Turns' OF writes still go through the account's write
                                   gate: starts >= the gap apart, never two at once
  case_same_fan_never_overlaps     two jobs of one Fan: one run at a time, both run; a second job
                                   of a Fan whose Turn runs here is busy (+20 s), never a 2nd Turn
  case_cap_respected               6 Fans, AUTOMATION_FULL_AI_PER_CREATOR=3: at most 3 at once,
                                   all 6 run; =1: one at a time (the old behaviour)
  case_other_kinds_exclusive       another kind with jobs for 2 Fans: one run per account at once
  case_reap_spares_running_fans    a run's reap: a dead Fan's `sending` row + lease reaped, a Fan
                                   running in this process spared; its own Fan reaped
  case_crash_requeue_no_double_send  a `running` job left by a dead process: requeued, the rerun
                                   reaps the `sending` row and sends nothing

OF faked (`_full_ai_live_helpers.world`), Jevs / Writers faked. Temp DB only; no paid call.

Run: cd service && nice -n 10 ../venv/bin/python tests/test_full_ai_live_parallel.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import automation_executor as ax  # noqa: E402
import of_write  # noqa: E402
import webhook_dispatch as wd  # noqa: E402
from _full_ai_fixtures import _msg  # noqa: E402
from _full_ai_live_helpers import KIND, clear_pause, live_rows, seed_live, world  # noqa: E402
from _of_fixtures import FakeOF  # noqa: E402
from automation_registry import _REGISTRY  # noqa: E402
from automations import full_ai_live, full_ai_turn  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AiDecision, FanLease, ScheduledJob  # noqa: E402

SERIAL = "zz_parallel_test_serial"   # a kind that is not per-fan
CAP_ENV = "AUTOMATION_FULL_AI_PER_CREATOR"


async def _drain_all(aid: str, rounds: int = 20) -> None:
    """Supervisor passes until the account has no due pending job (no supervisor loop here)."""
    for _ in range(rounds):
        await ax._drain_due_jobs_once()
        await ax._join_inflight_runs()
        async with get_session() as s:
            left = (await s.execute(select(ScheduledJob.id).where(
                ScheduledJob.account_id == aid, ScheduledJob.status == "pending",
                ScheduledJob.run_at <= datetime.utcnow()))).first()
        if left is None:
            return
    raise AssertionError(f"{aid}: jobs still pending after {rounds} passes")


async def _no_sweep(aid: str, rid: int) -> None:
    """The rule just fired: the materializer adds no sweep job beside the Fans' jobs."""
    async with get_session() as s:
        s.add(ScheduledJob(account_id=aid, kind=KIND, payload_json="{}", run_at=datetime.utcnow(),
                           status="done", rule_id=rid))


async def _dms(aid: str, fans: list[int], mid0: int) -> None:
    """Each Fan's DM lands 3 min ago (past the reply speed) and the hook queues his job."""
    for i, fan in enumerate(fans):
        await _msg(aid, fan, mid0 + i, "in", "hey you, how was your day",
                   datetime.utcnow() - timedelta(minutes=3))
        await wd.on_inbound_message(aid, fan, mid0 + i)


class Meter:
    """A fake kind body: records `aid`'s runs at once and per Fan (other accounts' jobs: no-op)."""

    def __init__(self, aid: str, hold_s: float = 0.05):
        self.aid, self.hold_s, self.now, self.peak, self.fans_now, self.fan_peak, self.ran = (
            aid, hold_s, 0, 0, {}, 0, [])

    async def __call__(self, account_id, payload, *, run_id):
        if account_id != self.aid:
            return {}
        fan = (payload.get("only_fan_ids") or [None])[0]
        self.now += 1
        self.fans_now[fan] = self.fans_now.get(fan, 0) + 1
        self.peak, self.fan_peak = max(self.peak, self.now), max(self.fan_peak, self.fans_now[fan])
        try:
            await asyncio.sleep(self.hold_s)
        finally:
            self.now -= 1
            self.fans_now[fan] -= 1
        self.ran.append(fan)
        return {}


@contextlib.contextmanager
def _kind(kind: str, fn):
    saved = _REGISTRY.get(kind)
    _REGISTRY[kind] = fn
    try:
        yield fn
    finally:
        if saved is None:
            _REGISTRY.pop(kind, None)
        else:
            _REGISTRY[kind] = saved


@contextlib.contextmanager
def _cap(n: int | None):
    old = os.environ.get(CAP_ENV)
    if n is None:
        os.environ.pop(CAP_ENV, None)
    else:
        os.environ[CAP_ENV] = str(n)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(CAP_ENV, None)
        else:
            os.environ[CAP_ENV] = old


async def _account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _jobs(aid: str, kind: str, fans: list) -> None:
    for fan in fans:
        await ax.enqueue_job(aid, kind, payload={"only_fan_ids": [fan], "anchor": 1})


@contextlib.contextmanager
def _rendezvous(n: int, log: list):
    """Wrap run_turn: each Turn logs start / end; a Turn waits (<= 5 s) for `n` started."""
    real = full_ai_turn.run_turn
    started, ev = set(), asyncio.Event()

    async def turn(facts, io=None):
        started.add(facts.fan_id)
        log.append(("start", facts.fan_id))
        if len(started) >= n:
            ev.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(ev.wait(), 5)
        try:
            return await real(facts, io)
        finally:
            log.append(("end", facts.fan_id))
    full_ai_turn.run_turn = turn
    try:
        yield
    finally:
        full_ai_turn.run_turn = real


class TimedOF(FakeOF):
    """FakeOF whose sends log (start, end, fan) and take 20 ms (run in the write's thread)."""

    def __init__(self):
        super().__init__()
        self.spans, self._lock = [], threading.Lock()

    def send_message(self, chat_id, text, **kw):
        t0 = time.monotonic()
        time.sleep(0.02)
        res = super().send_message(chat_id, text, **kw)
        with self._lock:
            self.spans.append((t0, time.monotonic(), int(chat_id)))
        return res


async def case_two_fans_overlap_real_path():
    aid, fans = "fa_par_overlap", [8301, 8302]
    rid = await seed_live(aid)
    await _no_sweep(aid, rid)
    await _dms(aid, fans, 93010)
    log: list = []
    with world() as (fake, *_), _rendezvous(2, log):
        await _drain_all(aid)
    first_end = next(i for i, e in enumerate(log) if e[0] == "end")
    assert {f for e, f in log[:first_end] if e == "start"} == set(fans), f"Turns did not overlap: {log}"
    for fan in fans:
        (row,) = await live_rows(aid, fan)
        assert row.status == "sent", (fan, row.status)
        assert any(s["fan_id"] == fan for s in fake.sent), (fan, fake.sent)
    assert not full_ai_live._running


async def case_paced_sends_one_at_a_time():
    aid, fans, gap = "fa_par_paced", [8311, 8312, 8313], 0.3
    rid = await seed_live(aid)
    await _no_sweep(aid, rid)
    await _dms(aid, fans, 93110)
    real_paced = of_write.of_write_paced
    of = TimedOF()
    log: list = []

    async def paced(account_id, fn, **kw):
        assert kw.get("dm") is True, kw          # a DM write: the DM rate too
        return await real_paced(account_id, fn, **{**kw, "min_gap_s": gap, "pause_s": 0.0})
    with world(fake=of), _rendezvous(3, log):
        ax.of_write_paced = paced                # world() restores the real one on exit
        await _drain_all(aid)
    spans = sorted(of.spans)
    assert len({f for *_, f in spans}) == 3 and len(spans) >= 3, spans
    for (s0, e0, _), (s1, _e1, _) in zip(spans, spans[1:]):
        assert s1 >= e0, f"two OF writes at once: {spans}"
        assert s1 - s0 >= gap * 0.95, f"writes {s1 - s0:.3f}s apart < gap {gap}: {spans}"


async def case_same_fan_never_overlaps():
    aid = "fa_par_same_fan"
    await _account(aid)
    meter = Meter(aid)
    with _kind(KIND, meter):
        await _jobs(aid, KIND, [1, 1, 2])
        await _drain_all(aid)
    assert meter.fan_peak == 1 and sorted(meter.ran) == [1, 1, 2], (meter.fan_peak, meter.ran)
    # a second job of a Fan whose Turn runs here: busy, retried at +20 s, no second Turn
    aid2, fan = "fa_par_busy", 8321
    rid = await seed_live(aid2)
    key = (aid2, fan)
    full_ai_live._running.add(key)
    try:
        res = await full_ai_live.run(aid2, {"only_fan_ids": [fan], "anchor": 1, "_rule_id": rid}, run_id=0)
    finally:
        full_ai_live._running.discard(key)
    assert res == {"skipped": "busy", "tries": 1}, res
    async with get_session() as s:
        (job,) = (await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid2, ScheduledJob.status == "pending"))).scalars()
    assert job.run_at > datetime.utcnow() + timedelta(seconds=15), job.run_at
    assert await live_rows(aid2) == []


async def case_cap_respected():
    for cap, aid in ((3, "fa_par_cap3"), (1, "fa_par_cap1")):
        await _account(aid)
        meter = Meter(aid, hold_s=0.1)
        with _cap(cap), _kind(KIND, meter):
            await _jobs(aid, KIND, list(range(1, 7)))
            await _drain_all(aid)
        assert meter.peak == cap and sorted(meter.ran) == list(range(1, 7)), (cap, meter.peak, meter.ran)
    assert ax._per_fan_caps() == {KIND: ax._FULL_AI_PER_CREATOR} and ax._FULL_AI_PER_CREATOR == 4
    assert not [k for k in ax._run_locks if len(k) == 3], "per-fan run locks left behind"


async def case_other_kinds_exclusive():
    aid = "fa_par_serial"
    await _account(aid)
    meter = Meter(aid)
    with _kind(SERIAL, meter):
        await _jobs(aid, SERIAL, [1, 2])
        pairs = [p for p in await ax._due_job_pairs() if p.account_id == aid]
        assert [(p.kind, p.fan) for p in pairs] == [(SERIAL, None)], pairs
        await _drain_all(aid)
    assert meter.peak == 1 and sorted(meter.ran) == [1, 2], (meter.peak, meter.ran)


async def _sending(aid: str, fan: int) -> int:
    async with get_session() as s:
        row = AiDecision(account_id=aid, fan_id=fan, mode="live", trigger_kind="inbound",
                         trigger_key=str(fan), status="sending", reply_json="{}", route="chat", heat=1,
                         route_row="test", question_version="test")
        s.add(row)
        s.add(FanLease(account_id=aid, fan_id=fan, automation_kind=KIND,
                       leased_until=datetime.utcnow() + timedelta(minutes=30)))
        await s.flush()
        return row.id


async def _state(aid: str) -> tuple[dict, set]:
    async with get_session() as s:
        rows = {r.fan_id: r.status for r in (await s.execute(
            select(AiDecision).where(AiDecision.account_id == aid))).scalars()}
        leases = {r.fan_id for r in (await s.execute(
            select(FanLease).where(FanLease.account_id == aid, FanLease.automation_kind == KIND))).scalars()}
    return rows, leases


async def case_reap_spares_running_fans():
    aid, dead, me, other = "fa_par_reap", 8331, 8332, 8333
    await seed_live(aid)
    for fan in (dead, me, other):
        await _sending(aid, fan)
    full_ai_live._running.update({(aid, me), (aid, other)})
    try:
        assert await full_ai_live.reap(aid, me) == 2
        rows, leases = await _state(aid)
        assert rows == {dead: "unconfirmed", me: "unconfirmed", other: "sending"}, rows
        assert leases == {other}, leases
    finally:
        full_ai_live._running.difference_update({(aid, me), (aid, other)})
    assert await full_ai_live.reap(aid) == 1            # nothing running: all of them, as before
    assert await _state(aid) == ({dead: "unconfirmed", me: "unconfirmed", other: "unconfirmed"}, set())


async def case_crash_requeue_no_double_send():
    aid, fan, mid = "fa_par_crash", 8341, 93410
    rid = await seed_live(aid)
    await _no_sweep(aid, rid)
    await _dms(aid, [fan], mid)
    with world() as (fake, *_):
        await _drain_all(aid)
    (row,) = await live_rows(aid, fan)
    n_sent = len(fake.sent)
    assert row.status == "sent" and n_sent >= 1, (row.status, fake.sent)
    # the process died mid-Turn: the row still `sending`, the job `running`
    async with get_session() as s:
        await s.execute(update(AiDecision).where(AiDecision.id == row.id).values(status="sending"))
        job = (await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == KIND,
            ScheduledJob.status == "done", ScheduledJob.rule_id.is_(None)))).scalars().first()
        job.status = "running"
        job_id = job.id
    await clear_pause(aid, fan)
    await ax._reconcile_orphans()
    async with get_session() as s:
        assert (await s.get(ScheduledJob, job_id)).status == "pending"
    with world() as (fake2, *_):
        await _drain_all(aid)
    (row,) = await live_rows(aid, fan)
    assert row.status == "unconfirmed" and fake2.sent == [], (row.status, fake2.sent)
    async with get_session() as s:
        assert (await s.get(ScheduledJob, job_id)).status == "done"


_harness.run()
