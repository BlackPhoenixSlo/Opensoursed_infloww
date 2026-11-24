"""Scenario 2b badge-load-amber's checks over synthetic traces: each passes on the right behaviour and fails on the
broken one it guards, and every one goes through the require_amber gate."""
import asyncio
import copy
import importlib
from collections import Counter
from pathlib import Path

import pytest

from slop.lib import badge_load
from slop.lib.badge_wire import DELAYS
from slop.lib.cli import SCEN, load

m = load(next(SCEN.glob("*-badge-load-amber.py")))
ROOT = Path(__file__).resolve().parents[2]
A, B = "1", "2"
LEGS = (0.0, 180.0, 195.0)


def _trace():
    # A: Fans 1, 2 awaiting; 4 read elsewhere at 10; 1 replied elsewhere at 40 (echo at 40.7); 2 DMs at 70;
    # 4 in a mass at 100 (window re-read at 103). B: 5 awaiting; 6 read elsewhere at 20; 5 chat-replied at 60.
    return {
        "truth": {A: [(-5.0, 2), (10.0, 3), (40.0, 2), (70.0, 1), (100.0, 0)],
                  B: [(-5.0, 1), (20.0, 2), (60.0, 1)]},
        "drawn": {A: [(-4.0, 2), (13.0, 3), (41.0, 2), (70.1, 1), (104.0, 0)],
                  B: [(-4.0, 1), (25.0, 2), (61.0, 1)]},
        "legs": LEGS,
        "final": {A: 0, B: 1},
        "both": {
            A: {"pool": [1, 2, 3, 4], "dots0": {1: 0, 2: 0, 3: 0, 4: 1}, "dots": {4: [(13.0, 0)], 2: [(70.05, 1)]},
                "last0": {1: True, 2: True, 3: False, 4: True}, "last": {1: [(40.0, False)], 4: [(100.0, False)]},
                "syncs": {1: [40.7], 2: [70.0]}, "windows": [-10.0, 103.0]},
            B: {"pool": [5, 6], "dots0": {5: 0, 6: 1}, "dots": {6: [(25.0, 0)]}, "last0": {5: True, 6: True},
                "last": {5: [(60.0, False)]}, "syncs": {5: [60.7]}, "windows": [-10.0]},
        },
    }


def _judge(tr):
    return m.judge(**tr)


def test_green_trace_passes_every_check():
    v = _judge(_trace())
    assert {k: ok for k, (ok, _) in v.items()} == {k: True for k in m.CHECKS}, v
    assert v[m.AMBER_MAX_UNDER_30S][1]["n"] == 6, "only truth changes inside the load are judged"


def _break(name):
    tr = _trace()
    if name == "p95":
        tr["drawn"] = {a: [(t + 9.0 if t > 0 else t, n) for t, n in xs] for a, xs in tr["drawn"].items()}
    elif name == "max":
        tr["drawn"][A] = [x for x in tr["drawn"][A] if x[0] != 41.0]
    elif name == "both":
        tr["drawn"][A] = [x for x in tr["drawn"][A] if x[0] != 70.1]
    elif name == "both_mass":
        tr["drawn"][A] = [(-4.0, 2), (13.0, 3), (41.0, 2), (70.1, 1), (140.0, 0)]
        tr["truth"][A][-1] = (130.0, 0)
        tr["both"][A]["dots"][4] = [(13.0, 0), (101.0, 1)]
    elif name == "final":
        tr["final"][B] = 2
    return tr


@pytest.mark.parametrize("broken, check", [
    ("p95", m.AMBER_P95_UNDER_8S),          # every Amber change 9 s late
    ("max", m.AMBER_MAX_UNDER_30S),         # a reply elsewhere never leaves amber until the next DM 30 s on
    ("both", m.NO_FAN_IN_BOTH),             # Fan 2's DM lights his dot but amber still counts him
    ("both_mass", m.NO_FAN_IN_BOTH),        # Fan 4 marked unread (dot red) while amber keeps him
    ("final", m.FINAL_EQUALS_TRUTH),        # B's Amber circle off truth when settled
])
def test_each_check_fails_on_its_broken_trace(broken, check):
    ok, detail = _judge(_break(broken))[check]
    assert ok is False, detail


def test_in_both_is_lenient_inside_the_slack_only():
    kw = dict(pool=[1, 2], dots0={1: 0, 2: 0}, dots={2: [(10.0, 1)]}, last0={1: True, 2: True}, last={},
              syncs={2: [10.0]}, windows=[0.0])
    late = [(0.0, 2), (11.5, 1)]
    assert m.in_both(late, lo=0.0, hi=30.0, **kw)[1] == [], "amber drops 1.5 s after the dot: inside the slack"
    stuck = [(0.0, 2), (13.0, 1)]
    judged, bad = m.in_both(stuck, lo=0.0, hi=30.0, **kw)
    assert judged and bad and bad[0][1:] == (2, 1), "still 2 past the slack: Fan 2 in both circles"
    assert m.in_both([], lo=0.0, hi=30.0, **kw) == (0, [])


def test_unjudged_without_evidence():
    v = m.judge({}, {}, LEGS, {}, {})
    assert all(ok is None for ok, _ in v.values()), v


class _Ctx:
    def __init__(self):
        self.got = []

    def check(self, name, ok, *, budget=False, **detail):
        self.got.append((name, ok, budget, detail.get("reason")))


@pytest.mark.parametrize("present, require, want", [
    (True, False, True),
    (True, True, True),
    (False, False, None),
    (False, True, False),
])
def test_report_goes_through_the_require_amber_gate(present, require, want):
    ctx = _Ctx()
    m.report(ctx, copy.deepcopy(_judge(_trace())) if present else {}, present, require)
    assert [n for n, *_ in ctx.got] == list(m.CHECKS)
    assert {ok for _, ok, _, _ in ctx.got} == {want}
    assert {n for n, _, b, _ in ctx.got if b} == {m.AMBER_P95_UNDER_8S, m.AMBER_MAX_UNDER_30S}
    if not present:
        assert all("amber field is absent" in why for *_, why in ctx.got)


def test_unjudged_check_fails_under_require_amber():
    v = m.judge({}, {}, LEGS, {}, {})
    ctx = _Ctx()
    m.report(ctx, v, True, True)
    assert {ok for _, ok, _, _ in ctx.got} == {False}
    ctx = _Ctx()
    m.report(ctx, v, True, False)
    assert {ok for _, ok, _, _ in ctx.got} == {None}


def test_sizes_rates_and_relay_constants(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "service"))
    transcode = importlib.import_module("event_transcode_decide")
    assert m.QUEUE_TO >= transcode.QUEUE_MIN_RECIPIENTS
    assert [(v["creators"], v["seconds"]) for v in m.TIERS.values()] == [(3, 180.0), (10, 300.0)]
    plan = m.plan([{"id": i} for i in range(m.CHATS)])
    assert len(plan) == m.CHATS <= 25, "every chat inside the 25-row window amber folds"
    assert sum(f["awaiting"] for f in plan) == m.AWAITING
    assert all(f["kind"] == "plain" and not f["unread"] for f in plan if f["awaiting"])
    assert m.AMBER_P95_S == 8.0 and m.AMBER_MAX_S == 30.0 and m.TIMEOUT_S == 900


def test_chat_sends_land_outside_dm_windows(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "service"))
    decide = importlib.import_module("badge_reads_decide")
    pattern = badge_load.PATTERN
    cycle = m.SLOT_S * len(pattern)
    assert m.CHAT_EVERY_S % cycle == 0 and m.QUEUE_EVERY_S % cycle == 0
    dms = [k * m.SLOT_S + DELAYS["dm_counter"] for k in range(3 * len(pattern)) if pattern[k % len(pattern)] == "dm"]
    for rtt in (0.0, 0.25, 0.5, 1.0):
        chats = [m.CHAT_AT_S + k * m.CHAT_EVERY_S + rtt + DELAYS["echo_counter"] for k in range(2)]
        assert min(abs(c - d) for c in chats for d in dms) > decide.DM_WINDOW_MS / 1000, rtt


def test_driver_on_the_fake():
    from slop.lib.test_badge_wire import _world
    aid = "500"
    plan = m.plan([{"id": 1000 + i} for i in range(m.CHATS)])
    plain = {aid: [f["id"] for f in plan if f["kind"] == "plain"]}
    with _world() as (fake, wire):
        wire.seed(aid, plan)
        d = m.Driver(wire, plain, http=None)
        amber = set(d.amber(aid))
        assert len(amber) == m.AWAITING == wire.truth_amber(aid)
        fan = d.act(aid, "reply")
        assert fan in amber and wire.truth_amber(aid) == m.AWAITING - 1
        raw0 = wire.raw_counter(aid)
        sent = d.recipients(aid)
        assert len(sent) == m.QUEUE_TO and set(sent[:m.AWAITING - 1]) == amber - {fan}
        d.act(aid, "queue")
        assert wire.truth_amber(aid) == 0 and wire.raw_counter(aid) == raw0, "a mass to read Fans moves no counter"
        assert [r["via"] for r in wire.reads].count("queue") == m.QUEUE_TO
        unread = set(d.unread(aid))
        assert d.act(aid, "reply") in unread, "no Fan awaiting: a reply goes to an unread one, as in 2a"
        assert Counter(d.done) == Counter({"reply": 2, "queue": 1})


def test_chat_goes_through_the_relay_send_route():
    calls = []

    class Http:
        async def post(self, path, headers=None, json=None):
            calls.append((path, headers))

            class R:
                status_code = 502
            return R()

    from slop.lib.test_badge_wire import _world
    aid = "500"
    plan = m.plan([{"id": 1000 + i} for i in range(m.CHATS)])
    with _world() as (_fake, wire):
        wire.seed(aid, plan)
        d = m.Driver(wire, {aid: [f["id"] for f in plan if f["kind"] == "plain"]}, Http())

        amber0 = set(d.amber(aid))

        async def go():
            fan = d.act(aid, "chat")
            await d.drain()
            return fan
        fan = asyncio.run(go())
        assert fan in amber0 and calls == [(f"/api/of/v2/chats/{fan}/messages", {"X-Account-Id": aid})]
        assert d.failed == Counter({"chat 502": 1}) and wire.truth_amber(aid) == m.AWAITING, "truth moves only at OF"
