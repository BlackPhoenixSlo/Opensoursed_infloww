"""One account's OF write spacing serves the operator first (write_gate, ADR 0025).

`automation_executor.of_write_paced` waits at the account's `WriteGate`. These
cases pin that every write still starts at least the gap after the one before
(the spacing OF sees), that an operator's write waiting behind automation's
goes next rather than last, that an idle account writes at once, that a
cancelled waiter neither blocks nor shortens the spacing, and that the tier
reaches the gate: from an operator's run (owner or borrower) by default, and
from the app's own writes (chat delete, vault import) explicitly.

Run: ./venv/bin/python service/tests/test_write_gate.py
"""
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
SLACK = 0.004     # loop timer granularity


async def _writers(gate: WriteGate, plan: list[tuple[str, bool, float]]) -> list[tuple[str, float]]:
    """Start each (name, operator, after_s) writer; their grant times, in order."""
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
    """Five automation writes queue on one account; the operator's chat delete
    arrives after them and starts at the next turn, a gap after the write in
    flight — not five gaps later. The spacing between every write holds."""
    gate = WriteGate()
    plan = [(f"a{i}", False, 0.0) for i in range(5)] + [("op", True, GAP / 2)]
    got = await _writers(gate, plan)
    names = [n for n, _ in got]
    assert names[:2] == ["a0", "op"], ("the operator waited behind automation", names)
    assert names[2:] == ["a1", "a2", "a3", "a4"], names
    assert _spaced(got), got


async def case_operators_keep_their_own_order():
    """Operators keep their arrival order; with automation waiting they take
    every other turn, never two in a row."""
    gate = WriteGate()
    plan = [("a0", False, 0.0), ("a1", False, 0.0), ("op1", True, 0.01), ("op2", True, 0.02)]
    names = [n for n, _ in await _writers(gate, plan)]
    assert names == ["a0", "op1", "a1", "op2"], names


async def case_automation_is_served_within_two_gaps_of_a_streaming_operator_leg():
    """A priority mass leg runs in the operator tier: ten of its sends queue on
    the account, and an automation write (a mass send under broadcast_lock,
    keeping its run slot) arrives behind them. It goes within two gaps, not
    after the whole leg, and the leg keeps its order."""
    gate = WriteGate()
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    plan = [(f"op{i}", True, 0.0) for i in range(10)] + [("auto", False, GAP / 2)]
    got = await _writers(gate, plan)
    names = [n for n, _ in got]
    waited = dict(got)["auto"] - (t0 + GAP / 2)
    assert waited <= 2 * GAP + SLACK, ("automation starved behind the operator leg", waited / GAP, names)
    assert [n for n in names if n != "auto"] == [f"op{i}" for i in range(10)], names
    # (The spacing is case_writes_on_one_account_stay_a_gap_apart's: eleven
    # wake-ups measured here jitter past SLACK on a loaded machine.)


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
    """of_write_paced with no `operator`: an operator's run (a child borrowing
    its lent slot, or any task it spawned) writes in the operator tier,
    automation's does not; outside a run it is automation unless the caller
    says otherwise. Inside a run the gate's tier is dm_rate's (run_of_task)."""
    seen: list[tuple[str, bool]] = []
    real = WriteGate.turn

    import dm_rate

    async def spy(self, gap, *, operator=False):
        seen.append((tag, operator))
        if run_slot.run_of_task() is not None:      # one test of whose work it is, gate and DM rate alike
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
            tag = "operator-spawned"                  # a plain task the run spawned, no borrow
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
    """The relay's own of_write_paced calls (chat delete, the vault import's
    carrier writes and its linked-fan send) run in a request, outside any run:
    each must say it is the operator's."""
    src = Path(ax.__file__).with_name("server.py").read_text()
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "of_write_paced"]
    assert len(calls) == 3, len(calls)
    for c in calls:
        kw = {k.arg: k.value for k in c.keywords}
        assert isinstance(kw.get("operator"), ast.Constant) and kw["operator"].value is True, (
            "server.py:%d of_write_paced without operator=True" % c.lineno)


if __name__ == "__main__":
    _harness.run()
