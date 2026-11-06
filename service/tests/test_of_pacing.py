#!/usr/bin/env python3
"""
of_pacing — background OF walks: 429 parse, the shared per-Creator pacer, the
one retry, no claim; the browser name fill's retry; link_metrics.prewarm_all's
busy-Creator deferral. No DB, no OF: fake calls, tiny constants.

  case_parse_allow_table:   "Please allow N seconds" -> N; none -> default; cap.
  case_retry_after_table:   OFAPIError-like 429 response; _proxy 502 detail with
                            upstream_status 429; anything else -> None.
  case_outside_walk_plain:  no walk -> call() as is: no pause, a 429 raises at once.
  case_pacer_shared:        two walks (different kinds) on one Creator: every GET
                            >= PAGE_GAP_S after the previous; other Creator unpaced.
  case_retry_once:          a 429 retries the SAME call once; a second 429 raises.
  case_walk_no_claim:       two walks with one key both run (each its own result);
                            a nested same-key walk runs; the caller never sees the walk.
  case_retry_429_unpaced:   the name fill: 8 at once leave at once (no pacer); a 429
                            is sent once more after OF's wait; a second 429 raises.
  case_prewarm_busy_table:  prewarm_all walks idle Creators in order and skips one with a
                            person's read in the last USER_WINDOW_S (no waiting); the next
                            pass walks it once idle.

Run: ./venv/bin/python service/tests/test_of_pacing.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import asyncio  # noqa: E402
import time  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import of_pacing  # noqa: E402

_KNOBS = ("PAGE_GAP_S", "JITTER_S", "RETRY_DEFAULT_S", "RETRY_MAX_S", "USER_WINDOW_S")
_REAL = {k: getattr(of_pacing, k) for k in _KNOBS}


def _knobs(**kw):
    for k, v in _REAL.items():
        setattr(of_pacing, k, kw.get(k, v))
    of_pacing._next_at.clear()
    of_pacing._last_user.clear()


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


def case_retry_429_unpaced():
    _knobs(PAGE_GAP_S=0.5, RETRY_MAX_S=0.05)
    sent: list[float] = []

    async def ok():
        sent.append(time.monotonic())
        return {"ok": 1}

    async def main():
        t0 = time.monotonic()
        res = await asyncio.gather(*(of_pacing.retry_429("a1", ok) for _ in range(8)))
        assert res == [{"ok": 1}] * 8
        assert max(sent) - t0 < 0.05, "the name fill is never paced"
        for fails, want in ((1, 2), (2, 2)):
            n = []

            async def flaky():
                n.append(time.monotonic())
                if len(n) <= fails:
                    raise _E429()
                return "done"
            try:
                assert await of_pacing.retry_429("a1", flaky) == "done" and fails == 1
            except _E429:
                assert fails == 2, "a second 429 raises"
            assert len(n) == want, (fails, n)
            assert n[1] - n[0] >= 0.04, "waits what OF asks (capped)"
    asyncio.run(main())


def case_prewarm_busy_table():
    import link_metrics
    real = {k: getattr(link_metrics, k) for k in ("prewarm", "dead_session_map", "is_deactivated",
                                                  "_PREWARM_SPREAD_S")}
    real_list = link_metrics.account_registry.list_accounts
    walked: list[tuple[str, float]] = []

    async def prewarm(aid):
        walked.append((aid, time.monotonic()))

    async def no_dead():
        return {}

    async def active(_aid):
        return False
    link_metrics.prewarm, link_metrics.dead_session_map, link_metrics.is_deactivated = prewarm, no_dead, active
    link_metrics._PREWARM_SPREAD_S = 0.0
    link_metrics.account_registry.list_accounts = lambda: [
        {"id": a, "has_session": True, "platform": "onlyfans"} for a in ("a", "b", "c")]
    try:
        # busy: Creators with a person's read now; pass 1 / pass 2 (busy idle by then) walk order
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
            asyncio.run(link_metrics.prewarm_all())
            assert [a for a, _ in walked] == first, (busy, walked)
            assert time.monotonic() - t0 < 0.1, "a pass never waits for a busy Creator"
            time.sleep(0.25)   # the person's read leaves the window
            walked.clear()
            asyncio.run(link_metrics.prewarm_all())
            assert [a for a, _ in walked] == second, (busy, walked)
    finally:
        for k, v in real.items():
            setattr(link_metrics, k, v)
        link_metrics.account_registry.list_accounts = real_list


try:
    _harness.run()
finally:
    _knobs()
