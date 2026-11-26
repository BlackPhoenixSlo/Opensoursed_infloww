#!/usr/bin/env python3
from __future__ import annotations

import _harness

import asyncio  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from types import SimpleNamespace
from unittest.mock import patch  # noqa: E402

import of_pacing  # noqa: E402

_KNOBS = ("PAGE_GAP_S", "JITTER_S", "RETRY_DEFAULT_S", "RETRY_MAX_S", "USER_WINDOW_S", "COOLDOWNS_S",
          "READ_BUDGET_S", "SEND_BUDGET_S", "POLL_S")
_REAL = {k: getattr(of_pacing, k) for k in _KNOBS}


def _knobs(**kw):
    for k, v in _REAL.items():
        setattr(of_pacing, k, kw.get(k, v))
    of_pacing._next_at.clear()
    of_pacing._last_user.clear()
    of_pacing._gates.clear()


class _E429(Exception):
    def __init__(self, text="Too many requests. Please allow 1 seconds"):
        self.response = SimpleNamespace(status_code=429, text=text)


def case_parse_allow_table():
    _knobs()
    for text, want in [
        ('{"error":{"code":429,"message":"Too many requests. Please allow 1 seconds"}}', 1.0),
        ("Please allow 3 seconds", 3.0),
        ("please ALLOW 2.5 sec", 2.5),
        ("Too many requests", 1.0),
        ("", 1.0),
        (None, 1.0),
        ("Please allow 600 seconds", 10.0),
    ]:
        assert of_pacing.parse_allow(text) == want, (text, of_pacing.parse_allow(text))


def case_retry_after_table():
    _knobs()
    assert of_pacing.retry_after(_E429("Please allow 2 seconds")) == 2.0
    e = Exception()
    e.response = SimpleNamespace(status_code=500, text="Please allow 2 seconds")
    assert of_pacing.retry_after(e) is None
    p = Exception()
    p.detail = {"upstream_status": 429, "upstream_body": '{"message":"Please allow 4 seconds"}'}
    assert of_pacing.retry_after(p) == 4.0
    p.detail = {"upstream_status": 403, "upstream_body": "Please allow 4 seconds"}
    assert of_pacing.retry_after(p) is None
    p.detail = "plain string detail"
    assert of_pacing.retry_after(p) is None
    assert of_pacing.retry_after(ValueError("x")) is None


def case_upstream_and_allow_s_table():
    _knobs()
    e = Exception()
    e.response = SimpleNamespace(status_code=429, text="Please allow 45 seconds", headers={"Retry-After": "120"})
    assert of_pacing.upstream(e) == (429, "Please allow 45 seconds", "120"), of_pacing.upstream(e)
    assert of_pacing.upstream(_E429("x")) == (429, "x", None)
    p = Exception()
    p.detail = {"upstream_status": 429, "upstream_body": "Please allow 4 seconds"}
    assert of_pacing.upstream(p) == (429, "Please allow 4 seconds", None)
    assert of_pacing.upstream(ValueError("x")) == (None, "", None)
    for text, want in [
        ('{"error":{"code":429,"message":"Too many requests. Please allow 45 seconds"}}', 45.0),
        ("Please allow 600 seconds", 600.0),
        ("please ALLOW 2.5 sec", 2.5),
        ("Too many requests", None),
        (None, None),
    ]:
        assert of_pacing.allow_s(text) == want, (text, of_pacing.allow_s(text))


def case_asked_wait_table():
    for args, want in [
        (("120", None), 120.0),
        (("5", 1.0), 5.0),
        ((None, 45.0), 45.0),
        ((None, 600.0), 600.0),
        (("soon", 3.0), 3.0),
        (("-1", 3.0), 3.0),
        ((None, None), None),
    ]:
        assert of_pacing.asked_wait(*args) == want, (args, want)

    with patch.object(of_pacing.time, "time", return_value=1.0):
        assert of_pacing.asked_wait("Thu, 01 Jan 1970 00:00:00 GMT", 7.0) == 7.0
        assert of_pacing.asked_wait("Thu, 01 Jan 1970 00:00:01 GMT", 7.0) == 7.0


def case_outside_walk_plain():
    _knobs(PAGE_GAP_S=0.5)
    t0 = time.monotonic()
    for _ in range(3):
        assert of_pacing.paced("a1", lambda: 7) == 7
    assert time.monotonic() - t0 < 0.1
    n = []

    def boom():
        n.append(1)
        raise _E429()
    try:
        of_pacing.paced("a1", boom)
        raise AssertionError("429 outside a walk must raise")
    except _E429:
        pass
    assert n == [1], n


def case_pacer_shared():
    gap = 0.08
    _knobs(PAGE_GAP_S=gap, JITTER_S=0.0)
    sent: list[tuple[str, float]] = []

    def get(aid):
        sent.append((aid, time.monotonic()))
        return []

    async def job(aid, pages):
        for _ in range(pages):
            await asyncio.to_thread(of_pacing.paced, aid, lambda: get(aid))

    async def main():
        await asyncio.gather(
            of_pacing.walk("a1", "promos", lambda: job("a1", 4)),
            of_pacing.walk("a1", "subscribers", lambda: job("a1", 4)),
            of_pacing.walk("a2", "promos", lambda: job("a2", 1)),
        )
    asyncio.run(main())
    a1 = sorted(t for a, t in sent if a == "a1")
    assert len(a1) == 8, len(a1)
    gaps = [b - a for a, b in zip(a1, a1[1:])]
    assert min(gaps) >= gap - 0.01, gaps
    a2 = [t for a, t in sent if a == "a2"]
    assert len(a2) == 1 and a2[0] - a1[0] < gap, "another Creator must not wait on a1's pacer"


def case_retry_once():
    _knobs(PAGE_GAP_S=0.0, JITTER_S=0.0, RETRY_MAX_S=0.05)
    calls = []

    def flaky(fails):
        def f():
            calls.append(1)
            if len(calls) <= fails:
                raise _E429()
            return {"ok": True}
        return f

    async def run(fails):
        calls.clear()
        return await of_pacing.walk("a1", f"k{fails}",
                                    lambda: asyncio.to_thread(of_pacing.paced, "a1", flaky(fails)))
    assert asyncio.run(run(0)) == {"ok": True} and len(calls) == 1
    t0 = time.monotonic()
    assert asyncio.run(run(1)) == {"ok": True} and len(calls) == 2
    assert time.monotonic() - t0 >= 0.04, "must wait what OF asks (capped) before the retry"
    try:
        asyncio.run(run(2))
        raise AssertionError("second 429 must raise (a failed page, never an empty one)")
    except _E429:
        pass
    assert len(calls) == 2, calls

    def other():
        calls.append(1)
        raise RuntimeError("500")
    calls.clear()
    try:
        asyncio.run(of_pacing.walk("a1", "k500", lambda: asyncio.to_thread(of_pacing.paced, "a1", other)))
        raise AssertionError("non-429 must raise")
    except RuntimeError:
        pass
    assert len(calls) == 1, "only a 429 is retried"


def case_walk_no_claim():
    _knobs()
    runs = []

    async def body(tag):
        runs.append(tag)
        assert of_pacing._WALK.get().kind == "link_prewarm"
        await asyncio.sleep(0.02)
        return tag

    async def main():
        a, b = await asyncio.gather(of_pacing.walk("a1", "link_prewarm", lambda: body("first")),
                                    of_pacing.walk("a1", "link_prewarm", lambda: body("second")))
        assert (a, b) == ("first", "second") and sorted(runs) == ["first", "second"], (a, b, runs)
        inner = await of_pacing.walk("a1", "k", lambda: of_pacing.walk("a1", "k", lambda: body2()))
        assert inner == "inner"
        assert of_pacing._WALK.get() is None, "the walk context must not leak to the caller"
        try:
            await of_pacing.walk("a1", "x", boom)
            raise AssertionError("a walk's error reaches its caller")
        except RuntimeError:
            pass
        assert of_pacing._WALK.get() is None

    async def body2():
        return "inner"

    async def boom():
        raise RuntimeError("walk failed")
    asyncio.run(main())


class _Clock:
    def __init__(self):
        self.t, self.slept = 1000.0, []

    def __call__(self):
        return self.t

    def sleep(self, d):
        self.slept.append(round(d, 3))
        self.t += d


def _absorb(answers, clock, send=False):
    it, n = iter(answers), []

    def call():
        n.append(clock.t)
        a = next(it)
        if isinstance(a, Exception):
            raise a
        return a
    try:
        got = of_pacing.absorb_429("a1", call, send_deadline=clock() + of_pacing.SEND_BUDGET_S if send else None,
                                     sleep=clock.sleep, clock=clock)
    except Exception as e:
        got = type(e)
    return len(n), got


def case_absorb_429_table():
    _knobs(PAGE_GAP_S=5.0, JITTER_S=0.0)
    E = _E429
    fib = [3.0, 5.0, 8.0, 13.0, 21.0, 34.0]
    for answers, send, budget, calls, want, sleeps in [
        (["ok"], False, 90.0, 1, "ok", []),
        ([E(), "ok"], False, 90.0, 2, "ok", [3.0]),
        ([E("Please allow 9 seconds"), E(), "ok"], False, 90.0, 3, "ok", [9.0, 5.0]),
        ([E()] * 7 + ["ok"], True, 1000.0, 8, "ok", fib + [34.0]),
        ([E()] * 5 + ["ok"], False, 90.0, 5, E, fib[:4]),
        ([E()] * 6 + ["ok"], True, 90.0, 7, "ok", fib),
        ([E()] * 7 + ["ok"], True, 90.0, 7, E, fib),
        ([ValueError("boom"), "ok"], False, 90.0, 1, ValueError, []),
    ]:
        of_pacing.SEND_BUDGET_S = budget
        of_pacing._gates.clear()
        clock = _Clock()
        got = _absorb(answers, clock, send) + (clock.slept,)
        assert got == (calls, want, sleeps), (len(answers), send, got)
    of_pacing.SEND_BUDGET_S = _REAL["SEND_BUDGET_S"]
    assert of_pacing._next_at == {}, "a request's call is never paced"

    of_pacing._gates.clear()
    clock = _Clock()
    assert _absorb([E(), E(), "ok"], clock) == (3, "ok") and clock.slept == [3.0, 5.0]
    g = of_pacing._gates["a1"]
    assert not g.closed and g.step == 0 and not g.queue, g
    clock.slept.clear()
    assert _absorb(["ok"], clock) == (1, "ok") and clock.slept == [], "open gate: sent at once"
    assert _absorb([E(), "ok"], clock) == (2, "ok") and clock.slept == [3.0], "ladder reset after success"


def case_send_retry_cutoff_after_oversleep():
    _knobs()
    clock = _Clock()
    sent = []

    def call():
        sent.append(clock.t)
        raise _E429()

    def sleep(delay):
        clock.sleep(delay + 60)

    try:
        of_pacing.absorb_429("a1", call, send_deadline=clock() + of_pacing.SEND_BUDGET_S,
                             sleep=sleep, clock=clock)
    except _E429:
        pass
    assert sent == [1000.0]


async def case_walk_rechecks_gate_and_probes():
    _knobs(PAGE_GAP_S=10.0, JITTER_S=0.0)
    clock = _Clock()
    of_pacing._next_at["a1"] = clock.t + 1
    gate = of_pacing._gates.setdefault("a1", of_pacing._Gate())
    sent = []
    other_probe_active = False

    def sleep(delay):
        nonlocal other_probe_active
        clock.sleep(delay)
        if len(clock.slept) == 1:
            gate.closed = gate.probing = other_probe_active = True
        elif len(clock.slept) == 2:
            gate.probing = other_probe_active = False

    def paged():
        assert not other_probe_active and gate.probing
        sent.append(clock.t)
        if len(sent) == 1:
            raise _E429()

    async def run():
        of_pacing.paced("a1", paged)

    with patch.object(of_pacing.time, "monotonic", clock), patch.object(of_pacing.time, "sleep", sleep):
        await of_pacing.walk("a1", "test", run)

    assert len(sent) == 2, sent
    assert not gate.closed and not gate.probing


async def case_walk_yields_to_queued_send_and_drain():
    _knobs(PAGE_GAP_S=1.0, JITTER_S=0.0)
    clock = _Clock()
    gate = of_pacing._Gate(closed=True, last_429=_E429(), queue={(0, -1)})
    of_pacing._gates["a1"] = gate
    sent = []

    def sleep(delay):
        clock.sleep(delay)
        if not sent:
            assert of_pacing._admit(gate, (0, -1), clock()) == ("probe", 0.0)
            sent.append(("send", clock()))
            of_pacing._open("a1", gate, clock())

    async def run():
        of_pacing.paced("a1", lambda: sent.append(("walk", clock())))

    with patch.object(of_pacing.time, "monotonic", clock), patch.object(of_pacing.time, "sleep", sleep):
        await of_pacing.walk("a1", "test", run)
    assert [kind for kind, _ in sent] == ["send", "walk"], sent
    assert sent[1][1] - sent[0][1] >= of_pacing.PAGE_GAP_S


async def case_walk_429_closes_gate_for_reads():
    _knobs(PAGE_GAP_S=0.0, JITTER_S=0.0)
    clock = _Clock()

    def fail():
        raise _E429()

    def during_cooldown(delay):
        if not clock.slept:
            read_clock = _Clock()
            assert _absorb(["read"], read_clock) == (1, "read")
            assert read_clock.slept == [3.0]
        clock.sleep(delay)

    calls = 0

    async def run():
        def paged():
            nonlocal calls
            calls += 1
            if calls == 1:
                fail()
        of_pacing.paced("a1", paged)

    with patch.object(of_pacing.time, "monotonic", clock), patch.object(of_pacing.time, "sleep", during_cooldown):
        await of_pacing.walk("a1", "test", run)
    assert calls == 2


def case_cancelled_probe_and_waiter_release():
    _knobs()
    clock = _Clock()

    class Cancel(BaseException):
        pass

    def cancel():
        raise Cancel()

    n = 0

    def call():
        nonlocal n
        n += 1
        if n == 1:
            raise _E429()
        cancel()

    for invoke, sleep in [(call, clock.sleep), (lambda: "queued", lambda _d: cancel())]:
        if n == 2:
            of_pacing._gates["a1"].cool_until += 3
        try:
            of_pacing.absorb_429("a1", invoke, sleep=sleep, clock=clock)
        except Cancel:
            pass
        else:
            raise AssertionError("expected cancellation")
        g = of_pacing._gates["a1"]
        assert not g.probing and not g.queue
    assert _absorb(["ok"], clock) == (1, "ok")


def case_retry_after_header_respects_remaining_budget():
    from email.utils import formatdate

    _knobs()
    for header, expected in [("9", [9.0]), (formatdate(1009, usegmt=True), [9.0]), ("80", [])]:
        of_pacing._gates.clear()
        clock = _Clock()
        err = _E429("Too many requests")
        err.response.headers = {"Retry-After": header}
        with patch.object(of_pacing.time, "time", return_value=1000.0):
            assert _absorb([err, "ok"], clock) == ((2, "ok") if expected else (1, _E429))
        assert clock.slept == expected


def case_late_429_extends_cooldown_without_climbing():
    _knobs()
    clock = _Clock()
    g = of_pacing._Gate()
    of_pacing._close("a1", g, _E429(), clock.t)
    step, epoch, cool = g.step, g.epoch, g.cool_until
    late = _E429("Too many requests")
    late.response.headers = {"Retry-After": "60"}
    try:
        of_pacing._gate_call("a1", g, lambda: (_ for _ in ()).throw(late), False, epoch - 1, clock)
    except _E429:
        pass
    assert g.cool_until == clock.t + 60 > cool and (g.step, g.epoch) == (step, epoch), vars(g)


def case_list_read_budget_bounds_a_closed_gate():
    for budget, calls, want, slept in ((of_pacing.LIST_READ_BUDGET_S, 1, _E429, [2.0]),
                                       (None, 2, "ok", [2.0, 5.0])):
        _knobs()
        clock = _Clock()
        of_pacing._gates["a1"] = of_pacing._Gate(closed=True, cool_until=clock.t + 2, step=1, last_429=_E429())
        if budget is None:
            got = _absorb([_E429(), "ok"], clock)
        else:
            with of_pacing.read_budget(budget):
                got = _absorb([_E429(), "ok"], clock)
        assert (got, clock.slept) == ((calls, want), slept), (budget, got, clock.slept)
        if budget is not None:
            assert clock.t - 1000.0 <= budget, clock.t
    assert of_pacing.READ_BUDGET_S == 45.0 and of_pacing._READ_BUDGET.get() is None


def case_read_waiter_cap():
    _knobs()
    clock = _Clock()
    g = of_pacing._gates.setdefault("a1", of_pacing._Gate(
        closed=True, cool_until=clock.t + 3, last_429=_E429()))
    g.queue.update((1, ticket) for ticket in range(-of_pacing.MAX_READ_WAITERS, 0))
    assert _absorb(["read"], clock) == (0, _E429)
    assert clock.slept == [] and len(g.queue) == of_pacing.MAX_READ_WAITERS


def case_accountless_bypasses_gate():
    _knobs()
    clock = _Clock()

    def fail():
        raise _E429()

    try:
        of_pacing.absorb_429(None, fail, sleep=clock.sleep, clock=clock)
    except _E429:
        pass
    assert "None" not in of_pacing._gates


def case_gate_one_probe():
    _knobs(READ_BUDGET_S=1.0)
    clock = _Clock()
    assert _absorb([_E429()], clock) == (1, _E429)
    assert of_pacing._gates["a1"].closed
    assert of_pacing.absorb_429("a2", lambda: "b", sleep=clock.sleep, clock=clock) == "b"
    assert not clock.slept, "another Creator never waits on a1's gate"

    cools, gap = (0.06, 0.1, 0.16), 0.03
    _knobs(PAGE_GAP_S=gap, JITTER_S=0.0, COOLDOWNS_S=cools, RETRY_MAX_S=0.0, POLL_S=0.005)
    events: list[tuple[str, float]] = []
    lock = threading.Lock()
    real_close = of_pacing._close

    def close(aid, g, e, now):
        events.append(("close", time.monotonic()))
        real_close(aid, g, e, now)

    initial = threading.Barrier(10, timeout=5)

    def call():
        with lock:
            events.append(("call", time.monotonic()))
            k = sum(1 for e in events if e[0] == "call")
        if k <= 10:
            initial.wait()
        if k <= 12:
            raise _E429()
        return "ok"

    out: list = []
    go = threading.Barrier(10)

    def worker():
        go.wait()
        out.append(of_pacing.absorb_429("a1", call))
    of_pacing._close = close
    try:
        ts = [threading.Thread(target=worker) for _ in range(10)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(10)
    finally:
        of_pacing._close = real_close
    assert out == ["ok"] * 10, out
    calls = [t for k, t in events if k == "call"]
    closes = [t for k, t in events if k == "close"]
    assert len(calls) == 22 and len(closes) >= 3, (len(calls), len(closes))
    for a, b in zip(closes, closes[1:]):
        assert len([t for t in calls if a < t < b]) == 1, "exactly one probe per cooldown"
    drained = [t for t in calls if t > closes[-1]]
    assert len(drained) == 10, len(drained)
    assert drained[0] - closes[-1] >= cools[-1] / 2, "the probe waits the cooldown"
    assert min(b - a for a, b in zip(drained, drained[1:])) >= gap / 2, "the queue drains paced"
    g = of_pacing._gates["a1"]
    assert not g.closed and not g.queue and g.step == 0, g


def case_walk_waits_cooling():
    _knobs(PAGE_GAP_S=0.0, JITTER_S=0.0)
    g = of_pacing._gates.setdefault("a1", of_pacing._Gate())
    g.closed, g.cool_until = True, time.monotonic() + 0.08
    sent: list[float] = []
    t0 = time.monotonic()

    async def run():
        return await of_pacing.walk("a1", "k", lambda: asyncio.to_thread(
            of_pacing.paced, "a1", lambda: sent.append(time.monotonic())))
    asyncio.run(run())
    assert sent[0] - t0 >= 0.07, sent[0] - t0
    assert of_pacing.paced("a1", lambda: 1) == 1, "outside a walk: never gated"


def case_prewarm_busy_table():
    import link_prewarm
    real = {k: getattr(link_prewarm, k) for k in ("prewarm", "dead_session_map", "is_deactivated",
                                                  "_PREWARM_SPREAD_S")}
    real_list = link_prewarm.account_registry.list_accounts
    walked: list[tuple[str, float]] = []

    async def prewarm(aid):
        walked.append((aid, time.monotonic()))

    async def no_dead():
        return {}

    async def active(_aid):
        return False
    link_prewarm.prewarm, link_prewarm.dead_session_map, link_prewarm.is_deactivated = prewarm, no_dead, active
    link_prewarm._PREWARM_SPREAD_S = 0.0
    link_prewarm.account_registry.list_accounts = lambda: [
        {"id": a, "has_session": True, "platform": "onlyfans"} for a in ("a", "b", "c")]
    try:
        for busy, first, second in [
            ((), ["a", "b", "c"], ["a", "b", "c"]),
            (("b",), ["a", "c"], ["a", "b", "c"]),
            (("a", "b", "c"), [], ["a", "b", "c"]),
        ]:
            _knobs(USER_WINDOW_S=0.2)
            for a in busy:
                of_pacing.note_user(a)
            walked.clear()
            t0 = time.monotonic()
            asyncio.run(link_prewarm.prewarm_all())
            assert [a for a, _ in walked] == first, (busy, walked)
            assert time.monotonic() - t0 < 0.1, "a pass never waits for a busy Creator"
            time.sleep(0.25)
            walked.clear()
            asyncio.run(link_prewarm.prewarm_all())
            assert [a for a, _ in walked] == second, (busy, walked)
    finally:
        for k, v in real.items():
            setattr(link_prewarm, k, v)
        link_prewarm.account_registry.list_accounts = real_list


E1 = ("socks5://u:pw@10.0.0.1:1080", "pool-a")
E2 = ("socks5://u:pw@10.0.0.2:1080", "pool-b")
K1, K2 = "10.0.0.1:1080", "10.0.0.2:1080"


def _spaced(ts: list[float], gap: float) -> bool:
    ts = sorted(ts)
    return all(b - a >= gap - 0.01 for a, b in zip(ts, ts[1:]))


def case_egress_identity_table():
    import proxies as proxy_registry
    a = {"label": "a", "host": "gw.example.com", "port": 8001, "verified_ip": "5.6.7.8"}
    b = {"label": "b", "host": "gw.example.com", "port": 8001}
    c = {"label": "c", "host": "gw.example.com", "port": 8002, "username": "user", "password": "secret"}
    reg, bare = proxy_registry.Ok({"proxies": [a, b, c]}), proxy_registry.Ok({"proxies": [b]})
    url = proxy_registry.proxy_url
    for u, r, key in [
        (None, reg, "direct"),
        ("", reg, "direct"),
        (url(b), reg, "5.6.7.8"),
        (url(b), bare, "gw.example.com:8001"),
        (url(b), proxy_registry.Torn(reg.data), "5.6.7.8"),
        (url(b), proxy_registry.Torn(None), "gw.example.com:8001"),
        (url(c), reg, "gw.example.com:8002"),
        ("http://user:p@ss@gw.example.com:8001", reg, "5.6.7.8"),
        ("http://user:secret@proxy.example.com:8080", reg, "proxy.example.com:8080"),
        ("socks5://127.0.0.1:9050", reg, "127.0.0.1:9050"),
        ("1.2.3.4:3128", reg, "1.2.3.4:3128"),
        ("http://first.last:12345@squid:3128", reg, "squid:3128"),
        ("socks5h://user:secret@gw.example.com:8001", reg, "5.6.7.8"),
        ("http://user:sec ret@[2001:db8::1]:8080", reg, "[2001:db8::1]:8080"),
    ]:
        got = proxy_registry.egress_identity(u, r)
        assert got == key, (u, got, key)
        assert not any(w in got for w in ("secret", "sec ret", "ss", "user", "first", "12345", "@")), got


def _ledger_walks(plan, pages, fail=None):
    sent: list[tuple[str, float]] = []
    failed = set()

    def get(aid):
        sent.append((aid, time.monotonic()))
        if aid == fail and aid not in failed:
            failed.add(aid)
            raise _E429()
        return []

    async def job(aid, eg):
        for _ in range(pages):
            await asyncio.to_thread(of_pacing.paced, aid, lambda: get(aid), lambda: eg)

    async def main():
        await asyncio.gather(*(of_pacing.walk(a, "transactions", lambda a=a, eg=eg: job(a, eg))
                               for a, eg in plan.items()))
    asyncio.run(main())
    return sent


def case_proxy_slot_shared():
    gap = 0.08
    _knobs(PAGE_GAP_S=gap, JITTER_S=0.0)
    sent = _ledger_walks({"a1": K1, "a2": K1, "b1": K2}, 4)
    on1 = [t for a, t in sent if a in ("a1", "a2")]
    on2 = [t for a, t in sent if a == "b1"]
    assert len(on1) == 8 and _spaced(on1, gap), sorted(on1)
    assert len(on2) == 4 and _spaced(on2, gap)
    assert min(on2) - min(on1) < gap / 2, "another endpoint must not wait on E1's slot"
    span1, span2 = max(on1) - min(on1), max(on2) - min(on2)
    assert span1 >= 7 * gap - 0.02 and span2 < 5 * gap, (span1, span2)


def case_proxy_retry_shares_slot():
    import logging
    gap = 0.08
    _knobs(PAGE_GAP_S=gap, JITTER_S=0.0, RETRY_MAX_S=0.01, RETRY_DEFAULT_S=0.01)
    lines: list[str] = []

    class H(logging.Handler):
        def emit(self, r):
            lines.append(r.getMessage())
    h = H()
    of_pacing.log.addHandler(h)
    of_pacing.log.setLevel(logging.INFO)
    try:
        sent = _ledger_walks({"a1": K1, "a2": K1}, 3, fail="a1")
    finally:
        of_pacing.log.removeHandler(h)
    assert sum(1 for a, _ in sent if a == "a1") == 4 and sum(1 for a, _ in sent if a == "a2") == 3, sent
    assert _spaced([t for _, t in sent], gap), "the retry takes the endpoint slot too"
    retry = [x for x in lines if x.startswith("bg_walk_429_retry")]
    assert len(retry) == 1 and "account=a1" in retry[0], retry
    assert f"proxy={of_pacing.exit_label(K1)}" in retry[0] and "proxy=p-" in retry[0], retry
    assert K1 not in retry[0] and "10.0.0.1" not in retry[0], "the exit is logged hashed, never its IP"
    assert "pw" not in retry[0] and "u:" not in retry[0] and "@" not in retry[0], retry
    assert of_pacing.exit_label("direct") == "direct" and of_pacing.exit_label(None) == "-"


_SESSION = {"headers": {"user_id": "0", "x_bc": "bc", "x_of_rev": "rev", "user_agent": "ua"},
            "signing": {"rules": {"static_param": "s", "start": "1", "end": "2",
                                  "checksum_indexes": [1], "checksum_constant": 1}},
            "cookies": []}


def _client(aid, url, label):
    from of_client import OFClient
    sess = {**_SESSION, "headers": {**_SESSION["headers"], "user_id": aid}}
    c = OFClient(sess, proxies={"http": url, "https": url}, proxy_label=label)
    return c


def _record(c, sent, tag):
    c._get_json = lambda path, **kw: sent.append((tag, path.rsplit("/", 1)[-1], time.monotonic())) or []
    return c


def _walk_gets(jobs, pages, kind="transactions"):
    async def job(c, url):
        for _ in range(pages):
            await asyncio.to_thread(c.get_json, url)

    async def main():
        await asyncio.gather(*(of_pacing.walk(a, kind, lambda c=c, u=u: job(c, u)) for a, c, u in jobs))
    asyncio.run(main())


def case_only_the_ledger_walk_is_proxy_paced():
    gap = 0.08
    _knobs(PAGE_GAP_S=gap, JITTER_S=0.0)
    sent: list = []
    a1, a2 = _record(_client("a1", *E1), sent, "a1"), _record(_client("a2", *E1), sent, "a2")
    assert a1.pace_key() == a2.pace_key() == K1, (a1.pace_key(), a2.pace_key())
    stats = "https://onlyfans.com/api2/v2/trial-links/stats"
    _walk_gets([("a1", a1, stats), ("a2", a2, stats)], 3, kind="link_refresh")
    t1 = [t for tag, _, t in sent if tag == "a1"]
    t2 = [t for tag, _, t in sent if tag == "a2"]
    assert _spaced(t1, gap) and _spaced(t2, gap), "each Creator keeps its own spacing"
    assert abs(min(t1) - min(t2)) < gap / 2, "link-stats on one proxy: per Creator only"
    sent.clear()
    _knobs(PAGE_GAP_S=gap, JITTER_S=0.0)
    ledger = "https://onlyfans.com/api2/v2/payouts/transactions?limit=100"
    _walk_gets([("a1", a1, ledger), ("a2", a2, ledger)], 3)
    assert len(sent) == 6 and _spaced([t for *_, t in sent], gap), "ledger pages share the endpoint"
    sent.clear()
    t0 = time.monotonic()
    for _ in range(3):
        a1.get_json(ledger)
    assert time.monotonic() - t0 < gap and len(sent) == 3


def case_failover_old_new_client():
    import json
    import tempfile
    from pathlib import Path

    import accounts as account_registry
    import proxies as proxy_registry
    from of_client import OFClient
    gap = 0.08
    _knobs(PAGE_GAP_S=gap, JITTER_S=0.0)
    tmp = Path(tempfile.mkdtemp(prefix="of_pacing_failover_"))
    real_path, real_latest = proxy_registry.REGISTRY_PATH, account_registry.latest_session_path
    proxy_registry.REGISTRY_PATH = tmp / "proxies.json"
    proxy_registry._last_good_text = None

    def session(aid):
        d = tmp / "sessions" / "accounts" / aid
        d.mkdir(parents=True, exist_ok=True)
        p = d / "session_1.json"
        p.write_text(json.dumps({**_SESSION, "headers": {**_SESSION["headers"], "user_id": aid}}))
        return p

    def reg(on_a, on_b):
        proxy_registry.REGISTRY_PATH.write_text(json.dumps({"proxies": [
            {"label": "pool-a", "scheme": "socks5", "host": "10.0.0.1", "port": 1080, "username": "u",
             "password": "pw", "assigned_account_ids": on_a},
            {"label": "pool-b", "scheme": "socks5", "host": "10.0.0.2", "port": 1080, "username": "u",
             "password": "pw", "assigned_account_ids": on_b}]}))
    account_registry.latest_session_path = session
    try:
        reg(["x"], ["y"])
        sent: list = []
        old = _record(OFClient.from_account("x"), sent, "old")
        reg([], ["x", "y"])
        new = _record(OFClient.from_account("x"), sent, "new")
        y = _record(OFClient.from_account("y"), sent, "y")
        assert old.proxy_label == "pool-a" and new.proxy_label == "pool-b", (old.proxy_label, new.proxy_label)
        ledger = "https://onlyfans.com/api2/v2/payouts/transactions?limit=100"
        _walk_gets([("y", y, ledger), ("x", old, ledger)], 3)
        ty = [t for tag, _, t in sent if tag == "y"]
        to = [t for tag, _, t in sent if tag == "old"]
        assert _spaced(ty, gap) and _spaced(to, gap)
        assert abs(min(ty) - min(to)) < gap / 2, "the old client keeps pool-a's slot, not pool-b's"
        sent.clear()
        _knobs(PAGE_GAP_S=gap, JITTER_S=0.0)
        _walk_gets([("y", y, ledger), ("x", new, ledger)], 3)
        assert len(sent) == 6 and _spaced([t for *_, t in sent], gap), "the new client shares pool-b's slot"
        proxy_registry.REGISTRY_PATH.write_text(json.dumps({"proxies": [
            {"label": "gw-1", "scheme": "http", "host": "gw.example.com", "port": 8001, "username": "u",
             "password": "pw", "verified_ip": "9.9.9.9", "assigned_account_ids": ["x"]},
            {"label": "gw-2", "scheme": "http", "host": "gw.example.com", "port": 8002, "username": "u",
             "password": "pw", "verified_ip": "9.9.9.9", "assigned_account_ids": ["y"]}]}))
        gx, gy = (_record(OFClient.from_account(a), sent, a) for a in ("x", "y"))
        assert gx.pace_key() == gy.pace_key() == "9.9.9.9", (gx.pace_key(), gy.pace_key())
        sent.clear()
        _knobs(PAGE_GAP_S=gap, JITTER_S=0.0)
        _walk_gets([("x", gx, ledger), ("y", gy, ledger)], 3)
        assert len(sent) == 6 and _spaced([t for *_, t in sent], gap), "one exit IP, two ports: one slot"
        def gw(ip=None):
            proxy_registry.REGISTRY_PATH.write_text(json.dumps({"proxies": [
                {"label": "gw-1", "scheme": "http", "host": "gw.example.com", "port": 8001, "username": "u",
                 "password": "pw", "assigned_account_ids": ["x", "y"], **({"verified_ip": ip} if ip else {})}]}))
        gw()
        before = _record(OFClient.from_account("x"), sent, "x")
        assert before.pace_key() == "gw.example.com:8001", before.pace_key()
        gw("7.7.7.7")
        after = _record(OFClient.from_account("y"), sent, "y")
        assert before.pace_key() == after.pace_key() == "7.7.7.7", (before.pace_key(), after.pace_key())
        sent.clear()
        _knobs(PAGE_GAP_S=gap, JITTER_S=0.0)
        _walk_gets([("x", before, ledger), ("y", after, ledger)], 3)
        assert len(sent) == 6 and _spaced([t for *_, t in sent], gap), "built either side of a probe: one slot"
    finally:
        proxy_registry.REGISTRY_PATH, account_registry.latest_session_path = real_path, real_latest
        proxy_registry._last_good_text = None


def case_bare_client_unpaced():
    _knobs(PAGE_GAP_S=0.2, JITTER_S=0.0)
    sent: list[float] = []

    async def job():
        for _ in range(3):
            await asyncio.to_thread(of_pacing.paced, None, lambda: sent.append(time.monotonic()))
    asyncio.run(of_pacing.walk("a1", "k", job))
    assert len(sent) == 3 and sent[-1] - sent[0] < 0.2, sent
    assert not of_pacing._next_at, of_pacing._next_at


try:
    _harness.run()
finally:
    _knobs()
