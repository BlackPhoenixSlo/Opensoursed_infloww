import asyncio
from collections import Counter
from pathlib import Path

import pytest

from slop.lib.badge_metrics import amber_gate
from slop.lib.cli import SCEN, load

hover = load(next(SCEN.glob("*-badge-edge-shared-hover.py")))
A, B = "1", "2"


def _win(t, account=A, dur=1.5):
    return {"t0": t, "t": t + dur, "account": account, "route": "GET /api2/v2/chats", "status": 200,
            "query": "limit=25&offset=0&order=recent&skip_users=all"}


def _page(t, offset, account=A):
    return {**_win(t, account), "query": f"limit=15&offset={offset}&order=recent&skip_users=all"}


@pytest.mark.parametrize("starts, ok", [
    ([0, 31, 62], True),
    ([0, 29.5, 60], True),
    ([0, 28.9], False),
    ([0, 5, 10, 15], False),
    ([0, 0.2], False),
])
def test_hover_one_read_per_30s(starts, ok):
    calls = [_win(t) for t in starts] + [_page(t + 0.5, 10) for t in starts] + [_win(3, account=B)]
    got, detail = hover.judge(calls, [], [A, B])[hover.HOVER_ONE_READ_PER_30S]
    assert got is ok, detail
    assert detail["reads"] == {A: len(starts), B: 1}


def test_hover_checks_unjudged_without_reads():
    v = hover.judge([], [(1.0, 1.1, A, 0.5)], [A])
    assert v[hover.HOVER_ONE_READ_PER_30S][0] is None and v[hover.HOVER_ANSWERS_FRESH][0] is None


@pytest.mark.parametrize("answers, ok, joined", [
    ([(0.5, 1.6, A, 1.55), (2.0, 2.01, A, 1.55)], True, 1),
    ([(0.5, 0.52, A, -40.0)], False, 1),
    ([(31.2, 31.21, A, 1.55)], False, 1),
    ([(10.0, 10.01, A, 1.55)], True, 0),
])
def test_hover_answers_fresh(answers, ok, joined):
    calls = [_win(0), _win(31)]
    got, detail = hover.judge(calls, answers, [A])[hover.HOVER_ANSWERS_FRESH]
    assert got is ok, detail
    assert hover.joined(answers, calls) == joined


def test_hover_plan_and_tiers():
    plan = hover.plan([{"id": i} for i in range(hover.CHATS)])
    assert len(plan) == hover.CHATS and sum(f["unread"] for f in plan) == hover.UNREAD
    assert hover.TIERS["small"] == hover.TIERS["full"] == {"creators": 10, "chatters": 30, "hover_s": 120.0}
    assert hover.phase_c() is True
    src = (Path(__file__).resolve().parents[2] / "service" / "badge_reads_decide.py").read_text()
    assert f"HOVER_COOLDOWN_MS = {int(hover.COOLDOWN_S * 1000):_}" in src, "COOLDOWN_S is the relay's"


deep = load(next(SCEN.glob("*-badge-edge-deep-inbox.py")))


def test_deep_plans_seed_the_spec_inbox():
    from slop.lib.all_models_wire import PAGE_CAP
    from service.unread_total_decide import of_counts
    x = deep.plan_deep([{"id": i} for i in range(deep.DEEP_CHATS)])
    kinds = Counter(f["kind"] for f in x)
    assert kinds == {"restricted": 3, "muted": 15, "plain": 32} and all(f["unread"] for f in x)
    listed = [f for f in x if of_counts({"hasUnread": True, "isMutedNotifications": f["muted"]})]
    assert len(listed) == deep.DEEP_RAW == 35 and deep.DEEP_RED == 32
    assert len(listed) > deep.RELAY_PAGES * PAGE_CAP, "X's Unread list must outrun the Relay's 2 pages"
    assert next(i for i, f in enumerate(x) if f["kind"] == "plain") < 25, "X's read target sits in the window"
    y = deep.plan_swap([{"id": i} for i in range(deep.SWAP_CHATS)])
    assert sum(f["unread"] for f in y) == 12 and PAGE_CAP < 12 <= deep.RELAY_PAGES * PAGE_CAP
    awaiting = [i for i, f in enumerate(y) if f["awaiting"]]
    assert len(awaiting) == deep.AWAITING == 10 and max(awaiting) < 25, "every awaiting Fan inside the window"
    assert all(not y[i]["unread"] and not y[i]["muted"] for i in awaiting) and sum(not f["unread"] for f in y) == 18
    assert next(f for f in y if not f["unread"])["awaiting"], "the swap's DM goes to an awaiting Fan"
    assert deep.TIERS["small"] == {"deep": 1, "swap": 1} and sum(deep.TIERS["full"].values()) == 7
    assert deep.phase_c() is True


@pytest.mark.parametrize("title, want", [
    ("Amia — 9+ unread", ("Amia", "9+")),
    ("Amia — 5 unread — Updated 2m ago", ("Amia", "5")),
    ("Amia — 35 unread", ("Amia", "35")),
    ("Amia — unread count unknown", None),
])
def test_title_text(title, want):
    assert deep.title_text(title) == want


def test_row_fan():
    ids = {100000001, 100000002}
    assert deep.row_fan("Fan 100000001 hey there 2m", ids) == 100000001
    assert deep.row_fan("John D. @u100000002 $25", ids) == 100000002
    assert deep.row_fan("John D. talk soon", ids) is None
    assert deep.row_fan("100000001 100000002", ids) is None


@pytest.mark.parametrize("slot_n, text, roster_n, dom, ok", [
    (32, "9+", 32, "9+", True),
    (32, "9+", 32, None, True),
    (35, "9+", 32, "9+", False),
    (32, "9+", 35, "9+", False),
    (32, "32", 32, "9+", False),
    (32, "9+", 32, "35", False),
    (None, "9+", 32, None, False),
])
def test_nine_plus(slot_n, text, roster_n, dom, ok):
    assert deep.nine_plus(slot_n, text, roster_n, dom)[0] is ok


def _row(fan, muted=True):
    return {"withUser": {"id": fan}, "hasUnread": True, "isMutedNotifications": muted}


@pytest.mark.parametrize("api, dom, ok", [
    ([_row(1), _row(2), _row(9, muted=False)], [(1, False), (9, True), (None, True)], True),
    ([_row(1), _row(2, muted=False)], [], False),
    ([_row(1)], [(1, True)], False),
    ([_row(9, muted=False)], [(9, True)], None),
])
def test_muted_no_dot(api, dom, ok):
    assert deep.muted_no_dot({1, 2}, api, dom)[0] is ok


def test_flips_methods_not_shadowed_by_sse_listener_fields():
    f = deep._Flips(None)
    assert not {k for k, v in vars(deep._Flips).items() if callable(v)} & set(vars(f))
    f.flips.append((2.0, "x", 5, False))
    f.flips.append((1.0, "y", 6, True))
    assert f.timeline("x") == [(2.0, 5, False)]


@pytest.mark.parametrize("answers, ok", [
    ([(10.0, "x", 200)], True),
    ([(9.0, "x", 200)], False),
    ([(10.0, "y", 200)], False),
    ([(10.0, "x", 504)], False),
    ([], False),
])
def test_live_list(answers, ok):
    assert deep.live_list(answers, "x", 10.0) is ok


@pytest.mark.parametrize("flips, reads, n, ok", [
    ([], 1, 31, True),
    ([(5.0, 7, True)], 2, 31, True),
    ([(5.0, 7, False)], 1, 31, False),
    ([(5.0, None, False)], 1, 31, False),
    ([], 1, 32, False),
    ([(5.0, 7, False)], 0, 31, None),
])
def test_incomplete_no_flip(flips, reads, n, ok):
    assert deep.incomplete_no_flip(flips, reads, n, 31)[0] is ok


SWAP_ROWS = {1: (True, False), 2: (True, False), 3: (False, False)}


@pytest.mark.parametrize("events, ok", [
    ([(4.9, 3, True), (6.0, 1, False), (6.0, 3, True)], True),
    ([(4.9, 3, True)], False),
    ([(6.0, 1, False)], False),
    ([(4.9, 3, True), (6.0, 1, False), (6.5, 2, False)], False),
])
def test_swap_settles(events, ok):
    assert deep.swap_settles(SWAP_ROWS, events, {2, 3})[0] is ok


@pytest.mark.parametrize("per, ok", [
    ({"a": (True, {}), "b": (None, {})}, True),
    ({"a": (True, {}), "b": (False, {})}, False),
    ({"a": (None, {}), "b": (None, {})}, None),
])
def test_merge(per, ok):
    assert deep.merge(per)[0] is ok


@pytest.mark.parametrize("title, want", [
    ("Amia — 5 unread — 3 awaiting reply", 3),
    ("Amia — 9+ unread — 9+ awaiting reply — Updated 2m ago", 9),
    ("Amia — 5 unread — 0 awaiting reply", 0),
    ("Amia — 5 unread — awaiting reply unknown", None),
    ("Amia — 5 unread", None),
])
def test_amber_title(title, want):
    assert deep.amber_title(title) == want


TRUTH_Y = [(0.0, 10), (50.0, 9), (50.01, 10)]
SLOT_Y = [(1.0, 10), (50.2, 9), (54.0, 10)]


@pytest.mark.parametrize("slot, dom, truth, complete, ok", [
    (SLOT_Y, [(30.0, 9)], TRUTH_Y, True, True),
    ([(1.0, 0)], [(30.0, 0)], [(0.0, 0), (50.0, 1)], False, True),
    ([(1.0, 0), (52.0, 1)], [], [(0.0, 0), (50.0, 1)], False, True),
    ([(1.0, 11)], [], TRUTH_Y, True, False),
    (SLOT_Y + [(70.0, 11)], [], TRUTH_Y, True, False),
    (SLOT_Y, [(60.0, 11)], TRUTH_Y, True, False),
    ([(1.0, 0), (49.0, 1)], [], [(0.0, 0), (50.0, 1)], False, False),
    ([(1.0, 10), (50.2, 9)], [], TRUTH_Y, True, False),
    ([(1.0, 10), (49.0, 10)], [], [(0.0, 10), (49.0, 8)], True, False),
    ([], [], TRUTH_Y, True, None),
])
def test_no_phantom_amber(slot, dom, truth, complete, ok):
    got, detail = deep.no_phantom_amber(slot, dom, truth, 100.0, complete)
    assert got is ok, detail


def test_no_phantom_amber_through_the_gate():
    ok, _ = deep.merge({"x": deep.no_phantom_amber([(1.0, 0)], [], [(0.0, 0)], 100.0, False),
                        "y": deep.no_phantom_amber(SLOT_Y, [], TRUTH_Y, 100.0, True)})
    assert amber_gate(True, False, ok) == (True, None) and amber_gate(True, True, ok) == (True, None)
    assert amber_gate(False, False, ok)[0] is None and amber_gate(False, True, ok)[0] is False
    src = (Path(deep.__file__)).read_text()
    assert "amber_gate(present, ctx.param(\"require_amber\", 0) == 1, ok)" in src
    assert "amber_gate(False, ctx.param(\"require_amber\", 0) == 1)" in src, "B absent: F absent too"


def test_deep_world_on_the_fake():
    from slop.lib.test_badge_wire import _Client, _http, _world
    X, Y = "501", "502"
    x = deep.plan_deep([{"id": 1000 + i} for i in range(deep.DEEP_CHATS)])
    y = deep.plan_swap([{"id": 2000 + i} for i in range(deep.SWAP_CHATS)])
    with _world() as (fake, wire):
        wire.seed(X, x)
        wire.seed(Y, y)
        assert (wire.raw_counter(X), wire.truth_red(X), wire.raw_counter(Y)) == (35, 32, 12)
        pages = [_http(fake, X, "GET", f"/api2/v2/chats?limit=10&offset={o}&filter=unread")[1] for o in (0, 10)]
        assert [len(p["list"]) for p in pages] == [10, 10] and pages[1]["hasMore"], "2 pages leave X incomplete"
        cx, cy = _Client(fake, X), _Client(fake, Y)
        target = {X: next(f["id"] for f in x if f["kind"] == "plain")}
        pair = {Y: (y[0]["id"], y[-1]["id"])}
        deep.fire(wire, target, pair)
        fx = [f for _t, f in cx.wait(1) if "chat_messages" in f]
        fy = [f["chat_messages"] for _t, f in cy.wait(3) if "chat_messages" in f]
        assert [f["chat_messages"] for f in fx] == [34] and wire.truth_red(X) == 31
        assert fy == [12, 12], f"a same-value swap: {fy}"
        assert wire.truth_unread(Y) == {f["id"] for f in y if f["unread"]} - {y[0]["id"]} | {y[-1]["id"]}
        cx.close()
        cy.close()


def test_deep_world_amber_truth_on_the_fake():
    from slop.lib.test_badge_wire import _world
    X, Y = "501", "502"
    x = deep.plan_deep([{"id": 1000 + i} for i in range(deep.DEEP_CHATS)])
    y = deep.plan_swap([{"id": 2000 + i} for i in range(deep.SWAP_CHATS)])
    with _world() as (_fake, wire):
        wire.seed(X, x)
        wire.seed(Y, y)
        assert (wire.truth_amber(X), wire.truth_amber(Y)) == (0, deep.AWAITING)
        target = {X: next(f["id"] for f in x if f["kind"] == "plain")}
        pair = {Y: (next(f["id"] for f in y if f["unread"]), next(f["id"] for f in y if not f["unread"]))}
        deep.fire(wire, target, pair)
        assert wire.truth_amber_fans(X) == set(target.values()), "X's read target is now read and Fan-last"
        assert wire.truth_amber_fans(Y) == {f["id"] for f in y if f["awaiting"]} - {pair[Y][1]} | {pair[Y][0]}
degraded = load(next(SCEN.glob("*-badge-edge-degraded.py")))


def _unread(t0, account=A, status=200, offset=0, dur=0.3):
    return {"t0": t0, "t": t0 + dur, "account": account, "route": "GET /api2/v2/chats", "status": status,
            "query": f"limit=10&offset={offset}&filter=unread&order=recent&skip_users=all"}


@pytest.mark.parametrize("drawn, ok", [
    ({A: [(0, 3), (12, "grey")]}, True),
    ({A: [(0, 3)]}, False),
    ({A: [(12, "grey"), (30, 0)]}, False),
    ({A: [(12, "grey"), (61, 2)]}, True),
    ({A: []}, None),
])
def test_grey_not_zero(drawn, ok):
    got, detail = degraded.judge_grey(drawn, {A: (20, 60)})
    assert got is ok, detail


@pytest.mark.parametrize("calls, logs, ok", [
    ([_unread(15)], [], True),
    ([_unread(25)], [], False),
    ([], [(30.0, A)], False),
    ([_unread(25, account=B)], [(30.0, B)], True),
    ([], [], True),
])
def test_no_reads(calls, logs, ok):
    got, detail = degraded.judge_no_reads(calls, logs, {A: (20, 60)})
    assert got is ok, detail
    assert degraded.judge_no_reads(calls, logs, {})[0] is None


@pytest.mark.parametrize("calls, ok", [
    ([_unread(9.7, status=429), _unread(31)], True),
    ([_unread(9.7, status=429), _unread(15)], False),
    ([_unread(9.7, status=429), _unread(11.2, status=429), _unread(31.5)], True),
    ([_unread(9.7, status=429), _unread(11.2, status=429), _unread(12.6)], False),
    ([_unread(9.7, status=429), _unread(11.2), _unread(15)], None),
    ([_unread(9.7, status=429), _unread(12, offset=10)], False),
    ([_unread(9.7, status=429), _unread(12, account=B)], True),
    ([_unread(9.7), _unread(12)], None),
    ([{**_win(9.7), "status": 429}, _unread(15)], False),
    ([{**_win(9.7), "status": 429}, _unread(31)], True),
    ([{**_win(9.7, account=B), "status": 429}, _unread(15)], None),
])
def test_reads_hold_on_429(calls, ok):
    got, detail = degraded.judge_hold(calls, [A], 20.0)
    assert got is ok, detail


@pytest.mark.parametrize("starts, ok", [
    ([15, 30, 45], True),
    ([16, 33], True),
    ([15], False),
    ([], False),
    ([15, 17, 30], False),
    ([15, 40], False),
])
def test_socket_down_poll_15s(starts, ok):
    calls = [_unread(t) for t in starts] + [_unread(t + 0.4, offset=10) for t in starts] + [_unread(20, account=B)]
    got, detail = degraded.judge_polls(calls, A, 0.0, 50.0)
    assert got is ok, detail


@pytest.mark.parametrize("drawn, ok", [
    ([(0, 2), (8, 3)], True),
    ([(0, 2), (40, 3)], False),
    ([(0, 2)], False),
    ([(0, 2), (6, "grey"), (7, 3)], True),
])
def test_recovery_under_30s(drawn, ok):
    truth = [(0, 2), (5, 3)]
    got, detail = degraded.judge_recovery([(A, "flap", 5.0, 60.0, truth, drawn)])
    assert got is ok, detail
    assert degraded.judge_recovery([(A, "flap", 5.0, 20.0, truth, drawn)])[0] is None


@pytest.mark.parametrize("planned, steps, ok", [
    (3, [(0, 1), (1, 2), (2, 3)], True),
    (3, [(0, 1), (1, 2)], False),
    (3, [(0, 1), (1, 21), (21, 22)], False),
    (3, [(0, 1), (1, None), (2, 3)], False),
    (0, [], None),
])
def test_focus_walk_completes(planned, steps, ok):
    got, detail = degraded.judge_walk(planned, steps)
    assert got is ok, detail


def _counter(t, account):
    return {"t": t, "account": account, "kind": "counter", "value": 1}


@pytest.mark.parametrize("drawn, calls, frames, ok", [
    ([(0, 4), (100.5, "grey")], [_unread(110, account=B)], [_counter(108, B)], True),
    ([(0, 4)], [], [], False),
    ([(0, 4), (100.5, 0)], [], [], False),
    ([(0, 4), (100.5, "grey")], [_unread(t, account=B) for t in (105, 125, 145)], [_counter(108, B)], False),
    ([(0, 4), (100.5, "grey")], [_unread(105, account=B), _unread(170, account=B)], [_counter(108, B)], True),
])
def test_grey_after_restart(drawn, calls, frames, ok):
    got, detail = degraded.judge_restart(calls, frames, A, drawn, 100.0, 101.0, 160.0, {A: 100.2, B: 100.3})
    assert got is ok, detail


@pytest.mark.parametrize("calls, back, ok", [
    ([_unread(t, account=B) for t in (115, 130, 145)], {}, True),
    ([_unread(t, account=B) for t in (115, 130, 145)], {B: 150.0}, True),
    ([_unread(t, account=B) for t in (115, 130, 145)], {B: 100.3}, False),
    ([_unread(t, account=B) for t in (115, 117, 119)], {}, False),
])
def test_restart_socket_down_polls_are_no_storm(calls, back, ok):
    got, detail = degraded.judge_restart(calls, [], A, [(0, 4), (100.5, "grey")], 100.0, 101.0, 160.0, back)
    assert got is ok, detail


def test_known_at_and_log_reads():
    me = {"t0": 103.0, "t": 103.1, "account": A, "route": "GET /api2/v2/users/me", "status": 200, "query": ""}
    assert degraded.known_at([me], [_counter(105, A)], A, 100.0, 160.0) == 103.1
    assert degraded.known_at([{**me, "status": 400}], [_counter(105, A), _counter(99, A)], A, 100.0, 160.0) == 105
    assert degraded.known_at([], [_counter(105, B)], A, 100.0, 160.0) == 160.0
    import time as _t
    stamp = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(1_700_000_000))
    text = "\n".join((
        f"{stamp},250 INFO of-relay.badge_reads: badge_read account=7 kind=frame calls=1 rows=3 counter=4",
        f"{stamp},500 INFO of-relay.badge_reads: badge_read_failed account=8 error=ProxyError",
        f"{stamp},600 INFO of-relay.badge_reads: badge_read account=9 kind=hover calls=- rows=3",
        f"{stamp},800 INFO of-relay.badge_reads: badge_read_429_hold account=7 hold_s=20",
    ))
    assert degraded.log_reads(text) == [(1_700_000_000.25, "7"), (1_700_000_000.5, "8")]


def test_degraded_plan_and_tiers():
    assert degraded.TIERS["small"]["creators"] == 6 and degraded.TIERS["full"]["creators"] == 50
    roles = degraded.roles([str(i) for i in range(6)], degraded.TIERS["small"])
    assert len(roles["at_429"]) == 1 and len(roles["dead"]) == 2 and len(roles["proxy_down"]) == 1
    assert roles["quiet"] not in roles["dead"] + roles["proxy_down"] + [roles["held"]]
    flat = roles["at_429"] + roles["dead"] + roles["proxy_down"] + [roles["held"]]
    assert len(set(flat)) == len(flat)
    full = degraded.roles([str(i) for i in range(50)], degraded.TIERS["full"])
    assert (len(full["at_429"]), len(full["dead"]), len(full["proxy_down"])) == (10, 2, 2)
    assert len(full["flaps"]) == 5 and not set(full["flaps"]) & set(full["dead"] + full["proxy_down"])
    pulses = degraded.pulses(0.0, degraded.TIERS["small"]["main_s"])
    on = sum(b - a for a, b in pulses)
    assert abs(on / degraded.TIERS["small"]["main_s"] - 0.2) < 0.05
    assert degraded.phase_c() is True
    src = (Path(__file__).resolve().parents[2] / "service" / "badge_reads.py").read_text()
    assert f"POLL_MS = {int(degraded.POLL_S * 1000):_}" in src, "POLL_S is the relay's"


def test_degraded_proxy_down_roster_traceback_is_expected(tmp_path):
    from slop.lib.cli import _tracebacks
    err = "Failed to perform, curl: (97) cannot complete SOCKS5 connection to 127.0.0.1. (2)."
    log = tmp_path / "relay.log"
    log.write_text("\n".join([
        "2026-11-23 01:46:36,057 WARNING of-relay: roster-counts: OF read failed for 326014755",
        "Traceback (most recent call last):", '  File "curl.py", line 269, in _check_error', "    raise error",
        f"curl_cffi.curl.CurlError: {err}", "",
        "The above exception was the direct cause of the following exception:", "",
        "Traceback (most recent call last):", '  File "session.py", line 739, in _request_once',
        "    raise error(str(e), e.code, rsp) from e", f"curl_cffi.requests.exceptions.ProxyError: {err}",
        "2026-11-23 01:46:36,062 INFO of-relay: next line", ""]))
    assert _tracebacks(log)[0] == 1, "the chained ProxyError is not an OFFLINE first exception"
    assert _tracebacks(log, tuple(degraded.EXPECTED_TRACEBACKS)) == (0, 2)


class _IpBucket:

    def __init__(self, capacity):
        self.level = capacity

    async def post(self, _path, json):
        if self.level < 1:
            return type("R", (), {"status_code": 429})()
        self.level -= 1
        await asyncio.sleep(0.01)
        self.level += 1
        return type("R", (), {"status_code": 200})()


@pytest.mark.parametrize("at_once, refused", [(hover.LOGINS_AT_ONCE, 0), (hover.TIERS["small"]["chatters"], 10)])
def test_shared_hover_logins_fit_the_ip_bucket(at_once, refused):
    from slop.lib.service_constant import service_number
    cap = service_number("login_throttle", "IP_CAPACITY")
    recs = [{"username": f"c{i}", "password": "p"} for i in range(hover.TIERS["small"]["chatters"])]

    async def go():
        sem, bucket = asyncio.Semaphore(at_once), _IpBucket(cap)
        return Counter(await asyncio.gather(*(hover.sign_in(sem, bucket, r) for r in recs)))

    assert asyncio.run(go())[429] == refused
