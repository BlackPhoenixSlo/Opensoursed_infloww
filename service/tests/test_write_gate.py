from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB + TEST_MODE
import ast
import asyncio
from pathlib import Path

import automation_executor as ax
import run_slot
from write_gate import WriteGate

_harness.bootstrap()

GAP = 0.05
SLACK = 0.004  # loop timer granularity


async def _writers(gate: WriteGate, plan: list[tuple[str, bool, float]]) -> list[tuple[str, float]]:
    loop = asyncio.get_running_loop()
    got: list[tuple[str, float]] = []

    async def one(name, op, after):
        await asyncio.sleep(after)
        await gate.turn(GAP, operator=op)
        got.append((name, loop.time()))
    await asyncio.gather(*(one(*p) for p in plan))
    return got


def _spaced(got: list[tuple[str, float]]) -> bool:
    return all(b[1] - a[1] >= GAP - SLACK for a, b in zip(got, got[1:]))


async def case_writes_on_one_account_stay_a_gap_apart():
    gate = WriteGate()
    got = await _writers(gate, [(f"a{i}", False, 0.0) for i in range(5)])
    assert [n for n, _ in got] == [f"a{i}" for i in range(5)], ("FIFO among automation", got)
    assert _spaced(got), got


async def case_an_operator_write_goes_next_not_last():
    gate = WriteGate()
    plan = [(f"a{i}", False, 0.0) for i in range(5)] + [("op", True, GAP / 2)]
    got = await _writers(gate, plan)
    names = [n for n, _ in got]
    assert names[:2] == ["a0", "op"], ("the operator waited behind automation", names)
    assert names[2:] == ["a1", "a2", "a3", "a4"], names
    assert _spaced(got), got


async def case_operators_keep_their_own_order():
    gate = WriteGate()
    plan = [("a0", False, 0.0), ("a1", False, 0.0), ("op1", True, 0.01), ("op2", True, 0.02)]
    names = [n for n, _ in await _writers(gate, plan)]
    assert names == ["a0", "op1", "a1", "op2"], names


async def case_automation_is_served_within_two_gaps_of_a_streaming_operator_leg():
    gate = WriteGate()
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    plan = [(f"op{i}", True, 0.0) for i in range(10)] + [("auto", False, GAP / 2)]
    got = await _writers(gate, plan)
    names = [n for n, _ in got]
    waited = dict(got)["auto"] - (t0 + GAP / 2)
    assert waited <= 2 * GAP + SLACK, ("automation starved behind the operator leg", waited / GAP, names)
    assert [n for n in names if n != "auto"] == [f"op{i}" for i in range(10)], names


async def case_an_idle_account_writes_at_once():
    gate = WriteGate()
    assert await gate.turn(GAP) == 0.0
    await asyncio.sleep(GAP + SLACK)
    assert await gate.turn(GAP, operator=True) == 0.0


async def case_a_cancelled_waiter_neither_blocks_nor_shortens_the_spacing():
    gate = WriteGate()
    loop = asyncio.get_running_loop()
    times: list[float] = []
    await gate.turn(GAP)
    times.append(loop.time())
    doomed = asyncio.create_task(gate.turn(GAP))
    after = asyncio.create_task(gate.turn(GAP))
    await asyncio.sleep(0)
    doomed.cancel()
    await asyncio.gather(doomed, return_exceptions=True)
    await after
    times.append(loop.time())
    assert GAP - SLACK <= times[1] - times[0] < 2 * GAP, ("the cancelled turn was not skipped", times)
    assert gate.waiting() == (0, 0)


async def case_the_tier_reaches_the_gate_from_an_operators_run():
    seen: list[tuple[str, bool]] = []
    real = WriteGate.turn

    import dm_rate

    async def spy(self, gap, *, operator=False):
        seen.append((tag, operator))
        if run_slot.run_of_task() is not None:
            assert operator == (not dm_rate._automation()), (tag, operator)
        return await real(self, 0.0, operator=operator)
    WriteGate.turn = spy
    pool = run_slot.SlotPool(2)
    try:
        tag = "outside"
        await ax.of_write_paced("acc-wg", lambda: None, send_purpose="not_fan_dm")
        tag = "app"
        await ax.of_write_paced("acc-wg", lambda: None, send_purpose="not_fan_dm", operator=True)
        async with run_slot.hold(pool):
            tag = "automation-run"
            await ax.of_write_paced("acc-wg", lambda: None, send_purpose="gated")
        async with run_slot.hold(pool, operator=True):
            tag = "operator-run"
            await ax.of_write_paced("acc-wg", lambda: None, send_purpose="manual")
            async with run_slot.lend(budget_s=120.0):
                async def child():
                    async with run_slot.borrowed(budget_s=120.0):
                        await ax.of_write_paced("acc-wg", lambda: None, send_purpose="manual")
                tag = "operator-borrower"
                await asyncio.create_task(child())
            tag = "operator-spawned"
            await asyncio.create_task(ax.of_write_paced("acc-wg", lambda: None, send_purpose="manual"))
        async with run_slot.hold(pool):
            tag = "automation-spawned"
            await asyncio.create_task(ax.of_write_paced("acc-wg", lambda: None, send_purpose="gated"))
    finally:
        WriteGate.turn = real
    assert seen == [("outside", False), ("app", True), ("automation-run", False),
                    ("operator-run", True), ("operator-borrower", True),
                    ("operator-spawned", True), ("automation-spawned", False)], seen


def case_the_apps_paced_writes_are_the_operators():
    calls = [(path.name, n) for path in sorted(Path(ax.__file__).parent.glob("*.py"))
             for n in ast.walk(ast.parse(path.read_text()))
             if isinstance(n, ast.Call)
             and "of_write_paced" in (getattr(n.func, "id", None), getattr(n.func, "attr", None))]
    assert len(calls) == 3, [(name, c.lineno) for name, c in calls]
    for name, c in calls:
        kw = {k.arg: k.value for k in c.keywords}
        assert isinstance(kw.get("operator"), ast.Constant) and kw["operator"].value is True, (
            "%s:%d of_write_paced without operator=True" % (name, c.lineno))


if __name__ == "__main__":
    _harness.run()
