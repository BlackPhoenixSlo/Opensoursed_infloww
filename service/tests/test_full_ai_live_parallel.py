#!/usr/bin/env python3
"""test_full_ai_live_parallel — Full AI Chat jobs for different Fans of one Creator overlap.

Through the executor (`_drain_due_jobs_once` -> plan_dispatch -> run_once -> the kind):

  case_two_fans_overlap_real_path  two Fans' DMs: both live Turns start before either ends;
                                   both reply, one row each
  case_paced_sends_one_at_a_time   those Turns' OF writes still go through the account's write
                                   gate: starts >= the gap apart, never two at once
  case_same_fan_never_overlaps     two jobs of one Fan: one run at a time, both run; a second job
                                   of a Fan whose Turn runs here is busy (+20 s), never a 2nd Turn
  case_model_wait_frees_the_slot   ONE run slot, two Fans: both Turns are waiting on their Writer at
                                   the same time (the slot goes back while a model answers), both reply
  case_lost_slot_closes_the_walk   a Writer walk on a lost slot: SlotLost, the walk never starts and
                                   is closed (no "never awaited" warning)
  case_cap_respected               6 Fans, AUTOMATION_FULL_AI_PER_CREATOR=3: at most 3 at once,
                                   all 6 run; =1: one at a time (the old behaviour)
  case_other_kinds_exclusive       another kind with jobs for 2 Fans: one run per account at once
  case_reap_spares_running_fans    a run's reap: a dead Fan's `sending` row + lease reaped, a Fan
                                   running in this process spared; its own Fan reaped
  case_reap_spares_a_turn_started_during_its_await  a Turn that starts while another reap waits
                                   on the DB keeps its `sending` row and lease
  case_crash_requeue_no_double_send  a `running` job left by a dead process: requeued, the rerun
                                   reaps the `sending` row and sends nothing
  case_model_cap_timeout_sends_nothing  the Model-call cap saturated (1, held by a parked freed call):
                                   every Writer try `timeout`, one decision row, no OF send, the Run
                                   slot back, the cap's counts as before the Turn

OF faked (`_full_ai_live_helpers.world`), Jevs / Writers faked. Temp DB only; no paid call.

Run: cd service && nice -n 10 ../venv/bin/python tests/test_full_ai_live_parallel.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import automation_executor as ax  # noqa: E402
import llm_client  # noqa: E402
import model_cap  # noqa: E402
import of_write  # noqa: E402
import run_slot  # noqa: E402
import webhook_dispatch as wd  # noqa: E402
from _full_ai_fixtures import _msg  # noqa: E402
from _full_ai_live_helpers import DEEPSEEK, KIND, LINE, clear_pause, live_rows, seed_live, world  # noqa: E402
from _of_fixtures import FakeOF  # noqa: E402
from automation_registry import _REGISTRY  # noqa: E402
from automations import full_ai_live, full_ai_turn  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AiDecision, AutomationRun, FanLease, ScheduledJob  # noqa: E402

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


async def case_model_wait_frees_the_slot():
    aid, fans = "fa_par_freed", [8351, 8352]
    rid = await seed_live(aid)
    await _no_sweep(aid, rid)
    await _dms(aid, fans, 93510)
    real_write, real_size, real_sem = full_ai_turn.write, ax._size_run_slots, ax._run_sem
    inside, peak, both = 0, 0, asyncio.Event()

    async def write(*a, **kw):                  # the Writer walk: each waits (<= 15 s) for the other
        nonlocal inside, peak
        inside += 1
        peak = max(peak, inside)
        if inside >= 2:
            both.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(both.wait(), 15)
        try:
            return await real_write(*a, **kw)
        finally:
            inside -= 1

    async def keep(pool):                       # the pool stays at the one slot set here
        return None
    full_ai_turn.write, ax._size_run_slots, ax._run_sem = write, keep, run_slot.SlotPool(1)
    try:
        with world() as (fake, *_):
            await _drain_all(aid)
        assert ax._run_sem.free == 1, ax._run_sem.free
    finally:
        full_ai_turn.write, ax._size_run_slots, ax._run_sem = real_write, real_size, real_sem
    assert peak == 2, f"one slot pinned by a model wait: Writers at once = {peak}"
    for fan in fans:
        (row,) = await live_rows(aid, fan)
        assert row.status == "sent", (fan, row.status)
        assert any(s["fan_id"] == fan for s in fake.sent), (fan, fake.sent)


async def case_lost_slot_closes_the_walk():
    import gc
    import warnings
    ran: list[int] = []

    async def walk():
        ran.append(1)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        async with run_slot.hold(run_slot.SlotPool(1)) as slot:
            slot.lost = True
            call = walk()
            try:
                await full_ai_turn._capped(call, time.monotonic() + 30)
                raise AssertionError("no SlotLost")
            except run_slot.SlotLost:
                pass
        assert call.cr_frame is None, "the walk is left open"
        del call
        gc.collect()
    assert ran == []


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


async def case_reap_spares_a_turn_started_during_its_await():
    """Fan A's reap waits on the DB after reading `_running`; Fan B's Turn starts in that gap (in
    `_running`, its own reap, its lease, its `sending` row). A's reap must not reap B."""
    aid, a_fan, b_fan = "fa_par_reap_gap", 8341, 8342
    await seed_live(aid)
    real, gate, parked = full_ai_live.get_session, asyncio.Event(), asyncio.Event()

    @contextlib.asynccontextmanager
    async def gated():
        if not parked.is_set():            # A's reap only: park inside its session open
            parked.set()
            await gate.wait()
        async with real() as s:
            yield s

    async def turn_b():                    # run(): into `_running`, then _run's reap, lease, row
        full_ai_live._running.add((aid, b_fan))
        await full_ai_live.reap(aid, b_fan)
        await _sending(aid, b_fan)

    full_ai_live.get_session = gated
    try:
        full_ai_live._running.add((aid, a_fan))
        a = asyncio.create_task(full_ai_live.reap(aid, a_fan))
        await asyncio.wait_for(parked.wait(), 5)
        b = asyncio.create_task(turn_b())
        await asyncio.sleep(0.5)           # B gets as far as it can while A is parked
        gate.set()
        await asyncio.wait_for(asyncio.gather(a, b), 10)
        rows, leases = await _state(aid)
        assert rows == {b_fan: "sending"} and leases == {b_fan}, (rows, leases)
    finally:
        full_ai_live.get_session = real
        full_ai_live._running.difference_update({(aid, a_fan), (aid, b_fan)})


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


async def case_model_cap_timeout_sends_nothing():
    aid, fan = "fa_par_model_cap", 8361
    rid = await seed_live(aid)
    await _no_sweep(aid, rid)
    await _dms(aid, [fan], 93610)
    real_size, real_sem, real_wait = ax._size_run_slots, ax._run_sem, model_cap.WAIT_S
    old_env = os.environ.get(model_cap.ENV)

    async def keep(pool):
        return None

    async def blocker():                        # another automation run's freed call holds the one permit
        async with run_slot.hold(run_slot.SlotPool(1)):
            return await run_slot.freed(llm_client.chat(
                model="deepseek-v4-flash", messages=[{"role": "user", "content": "x"}], purpose="model_cap_block",
                account_id=aid), budget_s=120)
    os.environ[model_cap.ENV] = "1"
    model_cap.WAIT_S = 0.05
    ax._size_run_slots, ax._run_sem = keep, run_slot.SlotPool(2)
    held = None
    try:
        with world(writers={DEEPSEEK: ["park", *[LINE] * 9]}) as (fake, *_, fw):   # the blocker parks on its 1st post
            held = asyncio.create_task(blocker())
            await asyncio.wait_for(fw.parked.wait(), 5)
            before = (model_cap.in_flight(), model_cap.queued())
            assert before == (1, 0), before
            await _drain_all(aid)
            assert ax._run_sem.free == 2, ax._run_sem.free
            assert (model_cap.in_flight(), model_cap.queued()) == before
            assert not held.done(), "the blocker should still hold the permit"
    finally:
        if held is not None:                    # world()'s exit set fw.go: the blocker's post answers
            await asyncio.wait_for(asyncio.gather(held, return_exceptions=True), 5)
        ax._size_run_slots, ax._run_sem, model_cap.WAIT_S = real_size, real_sem, real_wait
        if old_env is None:
            os.environ.pop(model_cap.ENV, None)
        else:
            os.environ[model_cap.ENV] = old_env
    (row,) = await live_rows(aid)              # exactly one decision row
    assert row.fan_id == fan and row.status != "sent", (row.fan_id, row.status)
    assert not any(s["fan_id"] == fan for s in fake.sent), fake.sent
    attempts = json.loads(row.reply_json or "{}").get("attempts") or []
    assert attempts and {a["outcome"] for a in attempts} == {"timeout"}, attempts
    async with get_session() as s:             # the Run slot came back: no SlotLost, the run ended ok
        runs = (await s.execute(select(AutomationRun.status, AutomationRun.error_text).where(
            AutomationRun.account_id == aid, AutomationRun.kind == KIND))).all()
        jobs = (await s.execute(select(ScheduledJob.status).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == KIND))).scalars().all()
    assert runs and {r.status for r in runs} == {"ok"}, runs
    assert not any("SlotLost" in (r.error_text or "") for r in runs), runs
    assert jobs and set(jobs) == {"done"}, jobs
    assert (model_cap.in_flight(), model_cap.queued()) == (0, 0)


_harness.run()
