"""One account's outbound DM rate: automation queues under OF_DM_PER_MIN (dm_rate, ADR 0025 fix 9).

These cases pin that automation DMs never pass the limit in any window (they
queue for a place), that an operator's DM never waits and only counts, that
the peak and the over-limit sends are counted, that the limit is read at every
DM (env, then the panel), that one turn is one DM (a resend on it counts but
is not "unguarded"), that an automation DM sent with no turn is flagged, that
OFClient.send_message counts every DM, that the paced send's wait keeps the
run's slot (it can be under broadcast_lock) while a direct send's wait hands
it back like a typing hold, and that every automation sender in the code takes
a turn before its send.

Run: ./venv/bin/python service/tests/test_dm_rate.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB + TEST_MODE
import ast
import asyncio
import contextlib
import os
from pathlib import Path

import automation_executor as ax
import dm_rate
import lane_config
import of_client
import run_slot
from automations.rhythm import INLINE_MAX_S

_harness.bootstrap()

ACCT = "acct-dm-rate"
SLACK = 0.03


@contextlib.contextmanager
def _rate(per_min: int | None, window_s: float = 0.6, slack_s: float = 0.0):
    """OF_DM_PER_MIN in the env, a short window and slack (none unless asked),
    every account forgotten."""
    saved_env, saved_w, saved_s = os.environ.get(dm_rate.KNOB), dm_rate.WINDOW_S, dm_rate.SLACK_S
    if per_min is None:
        os.environ.pop(dm_rate.KNOB, None)
    else:
        os.environ[dm_rate.KNOB] = str(per_min)
    dm_rate.WINDOW_S, dm_rate.SLACK_S = window_s, slack_s
    dm_rate._reset()
    try:
        yield
    finally:
        dm_rate.WINDOW_S, dm_rate.SLACK_S = saved_w, saved_s
        dm_rate._reset()
        if saved_env is None:
            os.environ.pop(dm_rate.KNOB, None)
        else:
            os.environ[dm_rate.KNOB] = saved_env


async def _automation_dm(pool: run_slot.SlotPool, account: str = ACCT) -> tuple[float, float]:
    """One automation run's DM: its turn, then the send. (waited, sent at)."""
    async with run_slot.hold(pool):
        waited = await dm_rate.turn(account)
        dm_rate.record(account)
        return waited, asyncio.get_running_loop().time()


def _snap(account: str = ACCT) -> dict:
    return dm_rate.snapshot()[account]


async def case_automation_queues_at_the_limit():
    """Limit 3 a window: seven automation DMs at once. Three go now, the rest
    queue, and no window ever holds more than three sends."""
    with _rate(3):
        pool = run_slot.SlotPool(8)
        t0 = asyncio.get_running_loop().time()
        got = await asyncio.gather(*(_automation_dm(pool) for _ in range(7)))
        sent = sorted(t - t0 for _, t in got)
        assert all(s < SLACK for s in sent[:3]), sent
        assert all(s > dm_rate.WINDOW_S - SLACK for s in sent[3:]), sent
        for i in range(len(sent) - 3):
            assert sent[i + 3] - sent[i] >= dm_rate.WINDOW_S - SLACK, (i, sent)
        s = _snap()
        assert s["peak"] == 3 and s["over"] == 0 and s["unguarded"] == 0, s
        assert s["waits"] == 4 and s["waited_s"] > 0, s
        assert sum(1 for w, _ in got if w > 0) == 4, got


async def case_a_place_frees_after_the_send_plus_the_slack():
    """Limit 1, a 0.4 s window, 0.2 s slack, on a hand-driven clock: the turn
    is at 0 but its DM goes at 0.3 (a wait on the way to the POST), so the
    next place is at 0.3 + 0.4 + 0.2, not at 0.4 (the turn) nor 0.7 (the send
    plus the window: a waiter woken there lands inside it on OF's clock)."""
    with _rate(1, window_s=0.4, slack_s=0.2):
        now = [0.0]
        dm_rate._windows[ACCT] = dm_rate.Window(clock=lambda: now[0])
        async with run_slot.hold(run_slot.SlotPool(1)):
            await dm_rate.turn(ACCT)
            now[0] = 0.3
            dm_rate.record(ACCT)
        w = dm_rate._windows[ACCT]
        for t, gap in ((0.4, 0.5), (0.7, 0.2), (0.89, 0.01), (0.9, 0.0)):
            now[0] = t
            assert abs(w.wait_for(t, 1) - gap) < 1e-9, (t, w.wait_for(t, 1), gap)
        now[0] = 0.75
        assert w._in_window(0.75) == 0 and _snap()["now"] == 0, _snap()   # out of the 60 s, still a place


async def case_a_place_pruned_on_the_way_to_the_send_still_counts():
    """A turn reserved before a long wait on the way to the POST (the account's
    write gate behind a mass): limit 2, the real 60 s window and 1 s slack, on
    a hand-driven clock. The turn is at 0; at 62 s another DM's turn prunes the
    window; the first DM goes at 62.5. It is counted (2 in the window) and a
    third automation DM must wait, not slip past the limit."""
    with _rate(2, window_s=60.0, slack_s=1.0):
        now = [0.0]
        dm_rate._windows[ACCT] = dm_rate.Window(clock=lambda: now[0])
        pool = run_slot.SlotPool(4)
        first = asyncio.Event()
        go = asyncio.Event()

        async def slow():
            async with run_slot.hold(pool):
                await dm_rate.turn(ACCT)
                first.set()
                await go.wait()                  # the gate wait
                dm_rate.record(ACCT)
        task = asyncio.create_task(slow())
        await first.wait()
        now[0] = 62.0
        async with run_slot.hold(pool):
            assert await dm_rate.turn(ACCT) == 0.0
            dm_rate.record(ACCT)
        now[0] = 62.5
        go.set()
        await task
        assert _snap()["now"] == 2, _snap()
        assert dm_rate._windows[ACCT].wait_for(62.5, 2) > 0, "a third DM fits: the slow one was never counted"


async def case_a_dropped_turn_gives_its_place_back_at_once():
    """Limit 1, the real 60 s window: a turn reserved and then dropped (a stop,
    a chatter's pick, the fan's reply) is released, and the next automation DM
    goes at once, not 61 s later. A release after the send, or from another
    task, takes nothing back: the DM stays counted."""
    with _rate(1, window_s=60.0, slack_s=1.0):
        pool = run_slot.SlotPool(4)
        async with run_slot.hold(pool):
            await dm_rate.turn(ACCT)
            dm_rate.release(ACCT)
            dm_rate.release(ACCT)                    # twice: still nothing more
        assert _snap()["now"] == 0, _snap()
        waited, _ = await asyncio.wait_for(_automation_dm(pool), 1.0)
        assert waited == 0.0, ("the dropped turn's place was still held", waited)
        assert _snap()["now"] == 1, _snap()

        async def other_task():
            dm_rate.release(ACCT)
        async with run_slot.hold(pool):
            dm_rate._reset()
            await dm_rate.turn(ACCT)
            await asyncio.create_task(other_task())   # inherits the var, not the turn
            assert _snap()["now"] == 1, "another task took this turn's place back"
            dm_rate.record(ACCT)
            dm_rate.release(ACCT)                     # after the send: nothing to give back
        assert _snap()["now"] == 1, _snap()


async def case_an_operator_dm_never_waits_and_only_counts():
    """The window full of automation: the app's composer send (no run) and an
    operator's run go at once, past the limit (counted as over); automation
    then waits until the window has room again."""
    with _rate(3):
        pool = run_slot.SlotPool(8)
        await asyncio.gather(*(_automation_dm(pool) for _ in range(3)))
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        assert await dm_rate.turn(ACCT) == 0.0          # outside any run: the operator
        dm_rate.record(ACCT)
        async with run_slot.hold(pool, operator=True):
            assert await dm_rate.turn(ACCT) == 0.0
            dm_rate.record(ACCT)
        assert loop.time() - t0 < SLACK
        s = _snap()
        assert s["now"] == 5 and s["peak"] == 5 and s["over"] == 2 and s["unguarded"] == 0, s
        waited, _ = await _automation_dm(pool)
        assert waited >= dm_rate.WINDOW_S - SLACK, waited


async def case_the_limit_is_read_at_every_dm():
    """No env: the code default (23), on the panel live from import. The env
    pins it; a new value applies to the next DM, never pending a restart."""
    with _rate(None):
        assert dm_rate.limit() == dm_rate.DEFAULT_PER_MIN == 23
        assert dm_rate.KNOB in lane_config.knob_names()
    with _rate(2):
        assert dm_rate.limit() == 2
        row = next(r for r in lane_config.describe() if r["name"] == dm_rate.KNOB)
        assert row["value"] == 2 and row["live"] == 2 and not row["pending"], row
        pool = run_slot.SlotPool(4)
        got = await asyncio.gather(*(_automation_dm(pool) for _ in range(3)))
        assert sum(1 for w, _ in got if w > 0) == 1, got
    with _rate(None):
        dm_rate.limit()                                  # leave the live value at the default


async def case_one_turn_is_one_dm():
    """A turn's own send is not counted twice; a second POST on the same turn
    (a refused attachment's text-only resend, a retry) counts as a DM but not
    as unguarded; the next DM needs a turn of its own."""
    with _rate(5):
        pool = run_slot.SlotPool(1)
        async with run_slot.hold(pool):
            await dm_rate.turn(ACCT)
            dm_rate.record(ACCT)
            assert _snap()["now"] == 1, _snap()
            dm_rate.record(ACCT)                         # the resend
            s = _snap()
            assert s["now"] == 2 and s["retries"] == 1 and s["unguarded"] == 0, s
            await dm_rate.turn(ACCT)
            await asyncio.to_thread(dm_rate.record, ACCT)    # the send runs in a worker thread
            assert _snap()["now"] == 3 and _snap()["retries"] == 1, _snap()


async def case_a_turn_is_reused_by_its_task_only():
    """A sender takes its turn where it handles SlotLost; the helper's turn
    under it (send_dropping_bad_media) passes at once, reserving nothing more.
    A child task the turn's task spawns inherits the variable, not the turn."""
    with _rate(1, window_s=0.5):
        async with run_slot.hold(run_slot.SlotPool(4)):
            await dm_rate.turn(ACCT)
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            assert await dm_rate.turn(ACCT) == 0.0 and _snap()["now"] == 1, _snap()
            child = await asyncio.create_task(dm_rate.turn(ACCT))
            assert child >= 0.5 - SLACK and loop.time() - t0 >= 0.5 - SLACK, child


async def case_an_unwired_automation_dm_is_flagged():
    """An automation DM that reaches OF without a turn is counted and flagged
    (a sender this guard does not know); outside a run it is the operator's."""
    with _rate(5):
        async with run_slot.hold(run_slot.SlotPool(1)):
            dm_rate.record(ACCT)
        dm_rate.record(ACCT)
        s = _snap()
        assert s["now"] == 2 and s["unguarded"] == 1, s


def _client(account: str) -> of_client.OFClient:
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.account_id = account
    c.sent = []
    c.request_json = lambda method, path, **kw: c.sent.append((method, path)) or {"id": 1}
    return c


async def case_the_send_path_counts_every_dm():
    """OFClient.send_message counts each DM in its account's window, in the
    worker thread the senders call it from."""
    with _rate(5):
        c = _client(ACCT)
        await asyncio.to_thread(c.send_message, 9, "hey", auto_tag=False)
        c.send_message(9, "", giphy_id="g1", auto_tag=False)
        assert [p for _, p in c.sent] == [f"{of_client.API_BASE}/chats/9/messages"] * 2, c.sent
        assert _snap()["now"] == 2 and _snap()["unguarded"] == 0, _snap()


async def _free(pool: run_slot.SlotPool) -> bool:
    try:
        await asyncio.wait_for(pool.acquire(), 0.05)
    except TimeoutError:
        return False
    pool.release()
    return True


async def _watching(pool: run_slot.SlotPool, body):
    """Run `body(stop)` while sampling whether a fresh run could take the pool;
    the body awaits `stop()` before it leaves its run (its own release)."""
    seen: list[bool] = []
    done = asyncio.Event()

    async def watch():
        while not done.is_set():
            seen.append(await _free(pool))
            await asyncio.sleep(0.05)
    w = asyncio.create_task(watch())

    async def stop():
        done.set()
        await w
    try:
        out = await body(stop)
    finally:
        await stop()
    return out, seen


async def case_a_paced_dm_waits_keeping_its_slot():
    """of_write_paced(dm=True), the window full: the DM waits for room before
    the write, and the run's slot is never free meanwhile (a paced send can be
    under broadcast_lock; ADR 0025's rule)."""
    with _rate(2, window_s=1.5):
        os.environ["AUTOMATION_RELEASE_SLOT_MIN_HOLD_S"] = "1"
        try:
            pool = run_slot.SlotPool(1)
            sends: list[float] = []
            loop = asyncio.get_running_loop()

            async def body(stop):
                async with run_slot.hold(pool):
                    for _ in range(3):
                        await ax.of_write_paced(ACCT, lambda: sends.append(loop.time()) or {"id": 1},
                                                min_gap_s=0.0, send_purpose="gated", dm=True)
                        dm_rate.record(ACCT)
                    await stop()
            _, seen = await _watching(pool, body)
        finally:
            del os.environ["AUTOMATION_RELEASE_SLOT_MIN_HOLD_S"]
        assert sends[2] - sends[0] >= 1.5 - SLACK, sends
        assert seen and True not in seen, seen
        s = _snap()
        assert s["waits"] == 1 and s["unguarded"] == 0 and s["peak"] == 2, s


async def case_a_direct_dm_wait_hands_the_slot_back():
    """A direct send's turn (release_budget_s, as its typing holds) with the
    window full: a fresh run gets the slot while it waits, and the run has it
    back for the send."""
    with _rate(1, window_s=1.5):
        os.environ["AUTOMATION_RELEASE_SLOT_MIN_HOLD_S"] = "1"
        try:
            pool = run_slot.SlotPool(1)

            async def body(stop):
                async with run_slot.hold(pool) as slot:
                    await dm_rate.turn(ACCT, release_budget_s=INLINE_MAX_S)
                    dm_rate.record(ACCT)
                    waited = await dm_rate.turn(ACCT, release_budget_s=INLINE_MAX_S)
                    assert slot.held and slot.releases == 1, (slot.held, slot.releases)
                    dm_rate.record(ACCT)
                    await stop()
                    return waited
            waited, seen = await _watching(pool, body)
        finally:
            del os.environ["AUTOMATION_RELEASE_SLOT_MIN_HOLD_S"]
        assert waited >= 1.5 - SLACK, waited
        assert True in seen, seen
        assert _snap()["unguarded"] == 0 and _snap()["peak"] == 1, _snap()


# ── every automation DM takes a turn ─────────────────────────────────────────

_SVC = Path(ax.__file__).resolve().parent
_SENDS = {"send_message", "send_dropping_bad_media_sync"}


def _calls(node: ast.AST, name: str) -> list[ast.Call]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if (isinstance(f, ast.Attribute) and f.attr == name) or (isinstance(f, ast.Name) and f.id == name):
                out.append(n)
    return out


def _sends(node: ast.AST) -> bool:
    return any(_calls(node, s) for s in _SENDS) or any(
        isinstance(n, ast.Attribute) and n.attr == "send_message" for n in ast.walk(node))


def case_every_automation_sender_takes_a_turn():
    """Across service/automations and _common: a DM through of_write_paced
    says dm=True; a DM through asyncio.to_thread has a dm_rate.turn in the
    same function. (The runtime backstop is the `unguarded` count.)"""
    found = {"paced": 0, "direct": 0}
    for path in sorted((_SVC / "automations").glob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for c in _calls(fn, "of_write_paced"):
                if c.args[1:] and _sends(c.args[1]):
                    found["paced"] += 1
                    kw = {k.arg: k.value for k in c.keywords}
                    assert isinstance(kw.get("dm"), ast.Constant) and kw["dm"].value is True, (
                        f"{path.name}:{c.lineno} of_write_paced DM without dm=True")
            direct = [c for c in _calls(fn, "to_thread") if c.args and _sends(c.args[0])]
            if direct:
                found["direct"] += len(direct)
                turns = _calls(fn, "turn")
                assert any(isinstance(t.func, ast.Attribute) and getattr(t.func.value, "id", "") == "dm_rate"
                           for t in turns), f"{path.name}:{direct[0].lineno} DM in to_thread with no dm_rate.turn in {fn.name}"
    assert found["paced"] >= 4 and found["direct"] >= 7, found


_harness.run()
