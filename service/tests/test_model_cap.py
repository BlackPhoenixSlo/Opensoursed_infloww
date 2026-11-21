#!/usr/bin/env python3
"""test_model_cap — the Relay-wide Model-call cap on off-slot automation `llm_client.chat` calls
(spec docs/spec/ingest-llm-caps/phase-0B-model-call-cap.md, Testing Decisions).

Runs are real `run_slot.hold(SlotPool(k))` + `run_slot.freed(llm_client.chat(...))`; the wire is
`_full_ai_fixtures.FakeWriterHTTP`, its `park` posts waiting until released. Temp DB only; no paid call.

  case_cap_bounds_freed_calls          (a) cap + 5 freed calls: peak in flight = cap, all complete
  case_employee_and_operator_bypass    (b) cap saturated: a no-run call and an operator run's call return
  case_run_holding_its_slot_bypasses   (c) release kill switch off: a held run's call never waits
  case_queued_call_times_out_clean     (d) LLMModelCapTimeout at min(timeout_s, WAIT_S); no row, no spend,
                                           no request
  case_cancel_returns_permits          (e) a cancelled holder / waiter gives its permit / place back
  case_knob_read_at_use                (f) env, then stored, change the bound at the next call; never pending
  case_long_wait_and_timeout_log       (g) long wait -> one outcome=got line, timeout -> outcome=timeout,
                                           short wait -> none
  case_writer_reads_cap_as_timeout     (h) full_ai_writers._outcome(...) == "timeout"
  case_retries_keep_one_permit         (i) 429 then 200 inside one chat: one permit across both attempts

Run: nice -n 10 ./venv/bin/python service/tests/test_model_cap.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from _full_ai_fixtures import FakeWriterHTTP  # noqa: E402

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import lane_config  # noqa: E402
import llm_client  # noqa: E402
import model_cap  # noqa: E402
import run_slot  # noqa: E402
from automations import full_ai_writers  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, GrokCall, GrokDailyCost  # noqa: E402

AID = "model_cap_acct"
MODEL = "deepseek-v4-flash"
B = 120.0          # the run's take-back budget (rhythm.INLINE_MAX_S)
HOST = "api.deepseek.com"


def Wire(*script: str) -> FakeWriterHTTP:
    """The shared Writers' wire on the DeepSeek host: `script` answered one per post (`park`
    waits for `.go`); each request records `cap` = (in_flight, queued) at its post."""
    return FakeWriterHTTP({HOST: list(script)},
                          on_post=lambda r: r.update(cap=(model_cap.in_flight(), model_cap.queued())))


def texts(w: FakeWriterHTTP) -> list[str]:
    return [r["body"]["messages"][-1]["content"] for r in w.requests]


def chat(text: str = "hi", **kw):
    return llm_client.chat(model=MODEL, messages=[{"role": "user", "content": text}],
                           purpose="model_cap_test", account_id=AID, **kw)


async def run_call(pool: run_slot.SlotPool, text: str = "hi", *, operator: bool = False, **kw):
    """One automation run: holds a slot of `pool`, hands it back while its model answers."""
    async with run_slot.hold(pool, operator=operator):
        return await run_slot.freed(chat(text, **kw), budget_s=B)


@contextlib.contextmanager
def env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def patched(mod, **kv):
    old = {k: getattr(mod, k) for k in kv}
    for k, v in kv.items():
        setattr(mod, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(mod, k, v)


async def until(pred, timeout: float = 5.0) -> None:
    t = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > t:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.005)


async def settle(tasks) -> list:
    return await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 10)


async def seed() -> None:
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID))
            await s.flush()
            s.add(AccountAiConfig(account_id=AID, daily_cost_cap_cents=10_000_000))


async def case_cap_bounds_freed_calls():
    await seed()
    pool = run_slot.SlotPool(10)
    with env(AUTOMATION_MAX_MODEL_CALLS=2), Wire(*["park"] * 5).on() as w:
        tasks = [asyncio.create_task(run_call(pool, f"park{i}")) for i in range(5)]
        await until(lambda: model_cap.in_flight() == 2 and model_cap.queued() == 3 and w.parking == 2)
        await asyncio.sleep(0.05)
        assert (w.parking, model_cap.queued(), pool.free) == (2, 3, 10), (w.parking, pool.free)
        w.go.set()
        res = await settle(tasks)
    assert all(isinstance(r, llm_client.LLMResult) for r in res), res
    assert len(w.requests) == 5 and max(r["cap"][0] for r in w.requests) == 2, w.requests
    assert (model_cap.in_flight(), model_cap.queued(), pool.free) == (0, 0, 10)


async def case_employee_and_operator_bypass():
    await seed()
    pool = run_slot.SlotPool(4, reserve=1)
    with env(AUTOMATION_MAX_MODEL_CALLS=1), Wire("park", "ok:ok", "ok:ok").on() as w:
        holder = asyncio.create_task(run_call(pool, "park"))
        await until(lambda: model_cap.in_flight() == 1 and w.parking == 1)
        for who, call in (("employee", lambda: chat("now")),
                          ("operator", lambda: run_call(pool, "now", operator=True))):
            t0 = time.monotonic()
            res = await asyncio.wait_for(call(), 5)
            took = time.monotonic() - t0
            assert isinstance(res, llm_client.LLMResult), (who, res)
            assert took < 1.0, f"{who} call took {took:.3f}s with the cap saturated"   # a capped call would wait 20 s
            assert (model_cap.in_flight(), model_cap.queued()) == (1, 0), who
        assert not holder.done()
        w.go.set()
        await settle([holder])
    assert (model_cap.in_flight(), model_cap.queued()) == (0, 0)


async def case_run_holding_its_slot_bypasses():
    await seed()
    pool = run_slot.SlotPool(4)
    with env(AUTOMATION_MAX_MODEL_CALLS=1), Wire("park", "ok:ok").on() as w:
        holder = asyncio.create_task(run_call(pool, "park"))
        await until(lambda: model_cap.in_flight() == 1 and w.parking == 1)
        with env(AUTOMATION_RELEASE_SLOT_ON_HOLD=0):
            async with run_slot.hold(pool) as slot:
                t0 = time.monotonic()
                res = await asyncio.wait_for(run_slot.freed(chat("now"), budget_s=B), 5)
                took = time.monotonic() - t0
                assert slot.held
        assert isinstance(res, llm_client.LLMResult), res
        assert took < 1.0, f"held run's call took {took:.3f}s"   # a capped call would wait 20 s
        assert model_cap.queued() == 0
        w.go.set()
        await settle([holder])


async def _counts() -> tuple[int, tuple]:
    async with get_session() as s:
        n = (await s.execute(select(func.count()).select_from(GrokCall))).scalar_one()
        daily = (await s.execute(select(GrokDailyCost.cost_cents, GrokDailyCost.call_count).where(
            GrokDailyCost.account_id == AID, GrokDailyCost.provider == "chat"))).all()
    return n, tuple(daily)


async def case_queued_call_times_out_clean():
    await seed()
    pool = run_slot.SlotPool(4)
    with env(AUTOMATION_MAX_MODEL_CALLS=1), patched(model_cap, WAIT_S=0.4), Wire("park").on() as w:
        holder = asyncio.create_task(run_call(pool, "park"))
        await until(lambda: model_cap.in_flight() == 1 and w.parking == 1)
        for timeout_s, want in ((0.15, 0.15), (None, 0.4), (5.0, 0.4)):
            before, made = await _counts(), w.clients
            t0 = time.monotonic()
            try:
                await run_call(pool, "late", timeout_s=timeout_s)
                raise AssertionError("no cap timeout")
            except llm_client.LLMModelCapTimeout as e:
                took = time.monotonic() - t0
                assert isinstance(e, llm_client.LLMHTTPError) and e.status is None, e
            assert want - 0.02 <= took < want + 0.3, (timeout_s, took)
            assert await _counts() == before, "a cap timeout wrote a row or moved the spend"
            assert w.clients == made, "a cap timeout constructed a client"
            assert (model_cap.in_flight(), model_cap.queued(), pool.free) == (1, 0, 4)   # holder's slot freed
        w.go.set()
        await settle([holder])
    assert (model_cap.in_flight(), model_cap.queued(), pool.free) == (0, 0, 4)


async def case_cancel_returns_permits():
    await seed()
    pool = run_slot.SlotPool(4)
    with env(AUTOMATION_MAX_MODEL_CALLS=1), Wire("park", "park").on() as w:
        holder = asyncio.create_task(run_call(pool, "park-h"))
        await until(lambda: model_cap.in_flight() == 1 and w.parking == 1)
        a = asyncio.create_task(run_call(pool, "park-a"))
        b = asyncio.create_task(run_call(pool, "park-b"))
        await until(lambda: model_cap.queued() == 2)
        a.cancel()
        await settle([a])
        assert (model_cap.in_flight(), model_cap.queued()) == (1, 1)
        holder.cancel()
        await settle([holder])
        await until(lambda: w.parking == 1 and model_cap.queued() == 0)   # b got the permit
        assert model_cap.in_flight() == 1
        b.cancel()
        await settle([b])
    assert (model_cap.in_flight(), model_cap.queued(), pool.free) == (0, 0, 4)


async def case_knob_read_at_use():
    await seed()
    pool = run_slot.SlotPool(8)
    tasks: list[asyncio.Task] = []
    try:
        with patched(model_cap, WAIT_S=0.2), Wire("park", "park", "park").on() as w:
            with env(AUTOMATION_MAX_MODEL_CALLS=1):
                tasks.append(asyncio.create_task(run_call(pool, "park1")))
                await until(lambda: w.parking == 1)
                try:
                    await run_call(pool, "late")
                    raise AssertionError("cap 1 let a second call in")
                except llm_client.LLMModelCapTimeout:
                    pass
            with env(AUTOMATION_MAX_MODEL_CALLS=2):              # env changed: no restart
                tasks.append(asyncio.create_task(run_call(pool, "park2")))
                await until(lambda: w.parking == 2)
            with env(AUTOMATION_MAX_MODEL_CALLS=None):
                lane_config.set_many({model_cap.ENV: 3})          # saved from the panel
                tasks.append(asyncio.create_task(run_call(pool, "park3")))
                await until(lambda: w.parking == 3)
                assert model_cap.in_flight() == 3
                row = next(r for r in lane_config.describe() if r["name"] == model_cap.ENV)
                assert (row["value"], row["live"], row["default"], row["pending"]) == (3, 3, 50, False), row
                lane_config.set_many({model_cap.ENV: 1})          # shrink: the next call waits
                try:
                    await run_call(pool, "late")
                    raise AssertionError("shrunk to 1, yet a 4th call went in")
                except llm_client.LLMModelCapTimeout as e:
                    assert "cap 1" in str(e), e
                row = next(r for r in lane_config.describe() if r["name"] == model_cap.ENV)
                assert row["pending"] is False, row
            w.go.set()
            await settle(tasks)
    finally:
        lane_config.set_many({model_cap.ENV: None})
    assert (model_cap.in_flight(), model_cap.queued()) == (0, 0)


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


async def case_long_wait_and_timeout_log():
    await seed()
    pool = run_slot.SlotPool(4)
    h = _Lines()
    lg = logging.getLogger("of-relay")
    lg.addHandler(h)
    try:
        with env(AUTOMATION_MAX_MODEL_CALLS=1), patched(model_cap, LONG_WAIT_S=0.1, WAIT_S=0.3), \
                Wire("ok:ok", "park", "ok:ok", "park").on() as w:
            await run_call(pool, "short")                                  # free cap: no line
            assert not [x for x in h.lines if "model_cap_wait" in x], h.lines
            holder = asyncio.create_task(run_call(pool, "park"))
            await until(lambda: w.parking == 1)
            waiter = asyncio.create_task(run_call(pool, "after"))
            await until(lambda: model_cap.queued() == 1)
            await asyncio.sleep(0.15)
            w.go.set()                                                     # waiter got it after >= 0.1 s
            await settle([holder, waiter])
            got = [x for x in h.lines if "model_cap_wait" in x]
            assert len(got) == 1 and "outcome=got" in got[0], got
            assert "purpose=model_cap_test" in got[0] and "cap=1" in got[0], got
            w.go.clear()
            holder = asyncio.create_task(run_call(pool, "park"))
            await until(lambda: w.parking == 1)
            try:
                await run_call(pool, "late")
                raise AssertionError("no cap timeout")
            except llm_client.LLMModelCapTimeout:
                pass
            lines = [x for x in h.lines if "model_cap_wait" in x]
            assert len(lines) == 2 and "outcome=timeout" in lines[1], lines
            w.go.set()
            await settle([holder])
    finally:
        lg.removeHandler(h)
    import re
    assert re.fullmatch(r"model_cap_wait outcome=got purpose=\S+ waited_ms=\d+ cap=\d+ in_flight=\d+ queued=\d+", got[0]), got


async def case_writer_reads_cap_as_timeout():
    e = llm_client.LLMModelCapTimeout(20.0, 50)
    assert full_ai_writers._outcome(e) == "timeout"
    assert full_ai_writers.retryable("timeout")
    assert str(e) == "model-call cap: waited 20.0s (cap 50)", str(e)


async def case_retries_keep_one_permit():
    await seed()
    pool = run_slot.SlotPool(4)
    with env(AUTOMATION_MAX_MODEL_CALLS=1), patched(llm_client, _LLM_RETRY_BACKOFF_S=0), \
            Wire("park:429", "ok:ok", "ok:ok").on() as w:
        holder = asyncio.create_task(run_call(pool, "park-retry", max_attempts=2))
        await until(lambda: w.parking == 1)
        other = asyncio.create_task(run_call(pool, "other"))
        await until(lambda: model_cap.queued() == 1)
        w.go.set()
        res = await settle([holder, other])
    assert all(isinstance(r, llm_client.LLMResult) for r in res), res
    assert texts(w) == ["park-retry", "park-retry", "other"], w.requests
    # the 2nd attempt ran with the permit still held and the other call still queued
    assert w.requests[1]["cap"] == (1, 1), w.requests


_harness.run()
