import copy
import importlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

from slop.lib import badge_faults
from slop.lib.badge_wire import DELAYS
from slop.lib.cli import SCEN, load

m = load(next(SCEN.glob("*-badge-load-elsewhere.py")))
ROOT = Path(__file__).resolve().parents[2]
A, B = "1", "2"
X, Y, Z = 12, 11, 10
FULL, RACE, LEAN, OFF = (0.0, 180.0, 190.0), (205.0, 235.0, 235.0), (260.0, 440.0, 460.0), (470.0, 530.0, 535.0)
DM_T = 209.0


def _call(t0, account, offset=0, dur=0.3):
    return {"t0": t0, "t": t0 + dur, "account": account, "route": "GET /api2/v2/chats", "status": 200,
            "query": f"limit=10&offset={offset}&filter=unread"}


def _trace():
    calls, truth, seen = [], [], {}
    for aid in (A, B):
        calls += [_call(1.0 + 6 * k, aid) for k in range(30)]
        calls += [_call(207.5, aid, dur=4.1), _call(221.0, aid)]
        calls += [_call(262.0 + 16 * k, aid) for k in range(12)]
        calls.append({**_call(100.0, aid), "query": "limit=25&offset=0&order=recent"})
        for t, fan, u, cause, arrive in ((10.0, Z, 0, "read", 13.0), (20.0, Y, 1, "unread", 23.0),
                                         (40.0, Z, 1, "dm", 40.01), (50.0, Z, 0, "reply", 55.0),
                                         (205.0, Y, 0, "race", 211.7), (DM_T, X, 1, "race", DM_T + 0.05)):
            truth.append((t, aid, fan, u, cause))
            seen.setdefault((aid, fan), []).append((arrive, u))
    after_race = {A: [X], B: [X]}
    red = {A: 4, B: 4}
    return {"truth": truth, "seen": seen, "init": {aid: {X: 0, Y: 0, Z: 1} for aid in (A, B)},
            "reds": {A: [(5.0, 4)], B: [(5.0, 4)]},
            "ends": {"full": {"t": FULL[2], "unread": {A: [Y], B: [Y]}, "red": red},
                     "race": {"t": RACE[2], "unread": after_race, "red": red},
                     "lean": {"t": LEAN[2], "unread": after_race, "red": red},
                     "off": {"t": OFF[2], "unread": after_race, "red": red}},
            "legs": {"full": FULL, "race": RACE, "lean": LEAN, "off": OFF}, "calls": calls,
            "race": {aid: {"fan": X, "dm_t": DM_T} for aid in (A, B)}}


def _judge(tr):
    return m.judge(**tr)


def test_green_trace_passes_every_check():
    v = _judge(_trace())
    assert {k: ok for k, (ok, _) in v.items()} == {k: True for k in m.CHECKS}, v
    assert v[m.DOT_FLIP_MAX_UNDER_30S][1]["n"] == 6, "elsewhere changes only: DMs and race moves are not judged"


def _break(name):
    tr = _trace()
    if name == "dot_p95":
        for k in [(A, Z), (A, Y), (B, Z), (B, Y)]:
            tr["seen"][k] = [(t + 6.0, u) if u == 0 or t < 30 else (t, u) for t, u in tr["seen"][k]]
    elif name == "dot_max":
        tr["seen"][(A, Z)] = [x for x in tr["seen"][(A, Z)] if x[0] != 13.0]
    elif name == "final_red":
        tr["ends"]["full"]["red"][A] = 6
    elif name == "final_dot":
        tr["ends"]["lean"]["unread"][B] = [X, Y]
    elif name == "gap":
        tr["calls"].append(_call(4.0, A))
    elif name == "flight":
        tr["calls"].append(_call(1.1, A))
    elif name == "pages":
        tr["calls"] += [_call(1.2, A, offset=10), _call(1.25, A, offset=20)]
    elif name == "stale":
        tr["seen"][(A, X)] += [(DM_T + 2.7, 0), (DM_T + 13.0, 1)]
    elif name == "stale_end":
        tr["ends"]["race"]["unread"][B] = []
    elif name == "lean_gap":
        tr["calls"].append(_call(270.0, A))
    elif name == "lean_halve":
        tr["calls"] += [_call(265.0 + 6 * k, aid) for aid in (A, B) for k in range(29)]
    elif name == "off_call":
        tr["calls"].append(_call(500.0, B))
    elif name == "off_red":
        tr["ends"]["off"]["red"][A] = 3
    return tr


@pytest.mark.parametrize("broken, check", [
    ("dot_p95", m.DOT_FLIP_P95_UNDER_8S),
    ("dot_max", m.DOT_FLIP_MAX_UNDER_30S),
    ("final_red", m.FINAL_EQUALS_TRUTH),
    ("final_dot", m.FINAL_EQUALS_TRUTH),
    ("gap", m.READS_GAP_5S),
    ("flight", m.READS_SINGLE_FLIGHT),
    ("pages", m.READS_MAX_2_PAGES),
    ("stale", m.STALE_READ_NEVER_CLEARS),
    ("stale_end", m.STALE_READ_NEVER_CLEARS),
    ("lean_gap", m.LEAN_GAP_15S),
    ("lean_halve", m.LEAN_READS_HALVE),
    ("off_call", m.OFF_ZERO_READS),
    ("off_red", m.OFF_ZERO_READS),
])
def test_each_check_fails_on_its_broken_trace(broken, check):
    ok, detail = _judge(_break(broken))[check]
    assert ok is False, detail


def test_unjudged_without_evidence():
    tr = _trace()
    tr["calls"] = [c for c in tr["calls"] if not (c["t0"] <= DM_T <= c["t"])]
    v = _judge(tr)
    assert v[m.STALE_READ_NEVER_CLEARS][0] is None, "no read spans the DM: the race proved nothing"
    empty = m.judge([], {}, {}, {}, {}, {}, [], {})
    assert all(ok is None for ok, _ in empty.values()), empty
    window_only = _trace()
    window_only["calls"] = [c for c in window_only["calls"] if "filter=unread" not in c["query"]]
    assert m.judge(**window_only)[m.OFF_ZERO_READS][0] is True, "window reads are not Attribution reads"


def _row(fan, created_ms):
    at = datetime.fromtimestamp(created_ms / 1000, timezone.utc).isoformat(timespec="milliseconds")
    return {"withUser": {"id": fan}, "unreadMessagesCount": 1, "hasUnread": True, "isMutedNotifications": False,
            "canSendMessage": True, "lastMessage": {"id": fan, "fromUser": {"id": fan}, "createdAt": at}}


def test_fence_off_fault_turns_the_race_read_into_a_stale_clear(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "service"))
    decide = importlib.import_module("badge_reads_decide")
    asked = 1_700_000_000_000
    window = [_row(X, asked + 1700), _row(Y, asked - 60_000), _row(Z, asked - 90_000)]
    snapshot = [_row(Z, asked - 90_000)]
    assert decide.diff(window, None, snapshot, True, asked) == [(Y, 0)]
    monkeypatch.setattr(decide, "newer_than_ask", decide.newer_than_ask)
    badge_faults._badge_ordering_fence_off()
    flips = decide.diff(window, None, snapshot, True, asked)
    assert (X, 0) in flips
    tr = _trace()
    tr["seen"][(A, X)].append((DM_T + 2.7, 0))
    assert _judge(tr)[m.STALE_READ_NEVER_CLEARS][0] is False
    assert m.STALE_READ_NEVER_CLEARS in badge_faults.register(lambda fn, checks: checks)["badge-ordering-fence-off"]


def _deep_trace():
    tr = _trace()
    deep, w = (236.0, 250.0, 258.0), 13
    tr["legs"]["deep"] = deep
    tr["calls"] += [_call(237.0, A), _call(238.2, A, offset=10), _call(237.5, B)]
    for aid, arrive in ((A, 257.0), (B, 241.0)):
        tr["truth"].append((240.0, aid, w, 0, "read"))
        tr["seen"].setdefault((aid, w), []).append((arrive, 0))
    return tr


def test_two_page_leg_is_measured_on_two_page_creators_only():
    rep = m.two_page_report(**{k: v for k, v in _deep_trace().items() if k in ("truth", "seen", "legs", "calls")})
    assert rep["creators"] == [A] and rep["two_page_reads"] == {A: 1}, rep
    assert rep["n"] == 1 and rep["max_s"] == rep["p95_s"] == 17.0 and rep["gate"] is None, rep
    assert m.two_page_report(**{k: v for k, v in _trace().items() if k in ("truth", "seen", "legs", "calls")}) is None


def test_two_page_leg_never_fails_a_check():
    tr = _deep_trace()
    rep = m.two_page_report(tr["truth"], tr["seen"], tr["legs"], tr["calls"])
    assert rep["max_s"] > m.DOT_P95_S, "past the 8 s budget"
    got = {k: ok for k, (ok, _) in _judge(tr).items()}
    assert got == {k: True for k in m.CHECKS}, got
    assert "two_page_leg" not in m.CHECKS and not [c for c in m.CHECKS if "TWO_PAGE" in c or "DEEP" in c]


def test_sizes_rates_and_relay_constants(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "service"))
    decide = importlib.import_module("badge_reads_decide")
    assert decide.GAP_MS == {"full": m.GAP_S * 1000, "lean": m.LEAN_GAP_S * 1000}
    plan = m.plan([{"id": i} for i in range(m.CHATS)])
    kinds = Counter(f["kind"] for f in plan)
    assert len(plan) == m.CHATS <= 25 and kinds["only_friends"] >= 1 and kinds["muted"] == 1
    assert sum(f["unread"] for f in plan if f["kind"] == "plain") == m.PLAIN_UNREAD
    counted = m.ONLY_FRIENDS + m.RESTRICTED
    assert counted + max(m.PLAIN_UNREAD, m.PLAIN_HIGH) <= 10, "the Unread list stays one page (2 pages: scenario 5)"
    assert counted + m.RACE_UNREAD - 1 < 10, "the race read is one page"
    assert 10 < counted + m.DEEP_FILL <= counted + m.DEEP_HIGH <= m.MAX_PAGES * 10, "the deep leg reads 2 pages"
    assert m.PLAIN_UNREAD <= m.DEEP_FILL < m.DEEP_HIGH <= m.PLAIN
    per_min = 60.0 / m.SLOT_S / len(m.PATTERN)
    assert {k: n * per_min for k, n in Counter(m.PATTERN).items()} == {"read": 10, "reply": 10, "unread": 5, "dm": 15}
    assert {k: v["race_s"] for k, v in m.TIERS.items()} == {"small": 30.0, "full": 30.0}
    assert [(v["creators"], v["full_s"], v["lean_s"], v["off_s"]) for v in m.TIERS.values()] == \
        [(3, 180.0, 180.0, 60.0), (10, 300.0, 300.0, 60.0)]


def test_no_dm_explains_an_elsewhere_frame(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "service"))
    decide = importlib.import_module("badge_reads_decide")
    lag = {"read": DELAYS["click"], "reply": DELAYS["echo_counter"], "unread": DELAYS["click"]}
    slots = [(k * m.SLOT_S, m.PATTERN[k % len(m.PATTERN)]) for k in range(3 * len(m.PATTERN))]
    dms = [t + DELAYS["dm_counter"] for t, kind in slots if kind == "dm"]
    frames = [t + lag[kind] for t, kind in slots if kind != "dm"]
    assert min(abs(f - d) for f in frames for d in dms) > decide.DM_WINDOW_MS / 1000


def test_race_timeline_puts_the_dm_inside_a_complete_read(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "service"))
    decide = importlib.import_module("badge_reads_decide")
    tick = 1.0
    ask_first = DELAYS["click"] + decide.DECIDE_AFTER_MS / 1000
    ask_last = ask_first + tick
    assert ask_last < m.RACE_DM_AT_S < ask_first + m.RACE_SLOW_S, "the DM lands while the read is in flight"
    assert m.RACE_DM_AT_S + m.RACE_DM_COUNTER_S > ask_last + m.RACE_SLOW_S, "no counter frame before the answer"
    assert m.RACE_RELEASE_S > m.RACE_DM_AT_S + m.RACE_DM_COUNTER_S < m.TIERS["small"]["race_s"]


def test_report_records_every_check_with_budgets():
    got = []

    class Ctx:
        def check(self, name, ok, *, budget=False, **detail):
            got.append((name, ok, budget))

    m.report(Ctx(), copy.deepcopy(_judge(_trace())))
    assert [n for n, _, _ in got] == list(m.CHECKS)
    assert {n for n, _, b in got if b} == {m.DOT_FLIP_P95_UNDER_8S, m.DOT_FLIP_MAX_UNDER_30S}
