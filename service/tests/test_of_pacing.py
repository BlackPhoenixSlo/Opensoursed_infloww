#!/usr/bin/env python3
"""
of_pacing — background OF walks: 429 parse, the shared per-Creator pacer, the
one retry, no claim; the browser name fill's retry; link_metrics.prewarm_all's
busy-Creator deferral. No DB, no OF: fake calls, tiny constants.

  case_parse_allow_table:   "Please allow N seconds" -> N; none -> default; cap.
  case_upstream_and_allow_s_table: (status, body, Retry-After) from an OFAPIError-like
                            response or a _proxy 502 detail (no header); "allow N" uncapped.
  case_retry_after_table:   OFAPIError-like 429 response; _proxy 502 detail with
                            upstream_status 429; anything else -> None.
  case_outside_walk_plain:  no walk -> call() as is: no pause, a 429 raises at once.
  case_bare_client_unpaced: inside a walk, a page with no account (bare client) goes out at
                            once, never under a shared "None" pacer key.
  case_pacer_shared:        two walks (different kinds) on one Creator: every GET
                            >= PAGE_GAP_S after the previous; other Creator unpaced.
  case_retry_once:          a 429 retries the SAME call once; a second 429 raises.
  case_retry_429_off:       walk(retry_429=False): paced still waits its turn, but OF's 429
                            re-raises at once (one call, no wait); the default walk retries.
  case_walk_no_claim:       two walks with one key both run (each its own result);
                            a nested same-key walk runs; the caller never sees the walk.
  case_retry_429_unpaced:   the name fill: 8 at once leave at once (no pacer); a 429
                            is sent once more after OF's wait; a second 429 raises.
  case_prewarm_busy_table:  prewarm_all walks idle Creators in order and skips one with a
                            person's read in the last USER_WINDOW_S (no waiting); the next
                            pass walks it once idle.
  case_egress_key_table:    the endpoint key: scheme://host:port, no credentials, case-folded;
                            DIRECT; the log label never a host, port or credential.
  case_proxy_slot_shared:   ledger pages of two Creators on one endpoint: every departure on it
                            >= PAGE_GAP_S apart; a third Creator on another endpoint unpaced by them.
  case_proxy_retry_shares_slot: a 429's retry takes the endpoint slot too (spaced from the other
                            Creator's pages), still exactly one retry; its log names the label.
  case_link_stats_per_creator: through OFClient.get_json, two Creators on one proxy: link-stats
                            pages leave together (per Creator only), ledger pages are spaced.
  case_failover_old_new_client: ADR-0030 move through real OFClient.from_session_file + get_json:
                            the old client keeps the old endpoint's slot, the new one shares the
                            new endpoint's slot with the Creator already there.

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


def case_upstream_and_allow_s_table():
    _knobs()
    e = Exception()
    e.response = SimpleNamespace(status_code=429, text="Please allow 45 seconds", headers={"Retry-After": "120"})
    assert of_pacing.upstream(e) == (429, "Please allow 45 seconds", "120"), of_pacing.upstream(e)
    assert of_pacing.upstream(_E429("x")) == (429, "x", None)   # a response with no headers
    p = Exception()
    p.detail = {"upstream_status": 429, "upstream_body": "Please allow 4 seconds"}
    assert of_pacing.upstream(p) == (429, "Please allow 4 seconds", None)
    assert of_pacing.upstream(ValueError("x")) == (None, "", None)
    for text, want in [
        ('{"error":{"code":429,"message":"Too many requests. Please allow 45 seconds"}}', 45.0),
        ("Please allow 600 seconds", 600.0),   # uncapped, unlike parse_allow
        ("please ALLOW 2.5 sec", 2.5),
        ("Too many requests", None),
        (None, None),
    ]:
        assert of_pacing.allow_s(text) == want, (text, of_pacing.allow_s(text))


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


def case_retry_429_off():
    gap = 0.08
    _knobs(PAGE_GAP_S=gap, JITTER_S=0.0, RETRY_MAX_S=0.5)
    sent: list[float] = []

    def page():
        sent.append(time.monotonic())
        return {"ok": True}

    def throttled():
        sent.append(time.monotonic())
        raise _E429("Please allow 0.4 seconds")

    async def job():
        await asyncio.to_thread(of_pacing.paced, "a1", page)
        t0 = time.monotonic()
        try:
            await asyncio.to_thread(of_pacing.paced, "a1", throttled)
            raise AssertionError("a 429 must reach the caller with retry_429=False")
        except _E429:
            pass
        return time.monotonic() - t0

    took = asyncio.run(of_pacing.walk("a1", "audience_crawl", job, retry_429=False))
    assert len(sent) == 2, f"no in-place retry: {len(sent)} calls"
    assert sent[1] - sent[0] >= gap - 0.01, "still paced: the page waits its turn"
    assert took < 0.3, f"re-raised at once, not after OF's 0.4 s: {took:.2f}"
    sent.clear()
    try:   # the default walk keeps the in-place retry
        asyncio.run(of_pacing.walk("a1", "k", lambda: asyncio.to_thread(of_pacing.paced, "a1", throttled)))
    except _E429:
        pass
    assert len(sent) == 2, sent


def case_admission_after_pacing_and_retry():
    from unittest.mock import patch
    _knobs(PAGE_GAP_S=0.0, JITTER_S=0.0, RETRY_MAX_S=0.0)

    class Expired(Exception):
        pass

    for aid, retry in (("a1", False), (None, False), ("a1", True)):
        events = []

        def admit():
            events.append("admit")
            if not retry or events.count("admit") == 2:
                raise Expired

        def call():
            events.append("call")
            raise _E429()

        async def run():
            try:
                await of_pacing.walk(aid, "audience_crawl", lambda: asyncio.to_thread(of_pacing.paced, aid, call),
                                     before_call=admit)
                raise AssertionError("expired admission must refuse the departure")
            except Expired:
                pass
            assert of_pacing._WALK.get() is None

        with patch.object(of_pacing, "_wait_turn", lambda *keys: events.append("pace")):
            asyncio.run(run())
        expected = ["pace", "admit", "call", "pace", "admit"] if retry else (
            ["admit"] if aid is None else ["pace", "admit"])
        assert events == expected, events


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


E1 = ("socks5://u:pw@10.0.0.1:1080", "pool-a")
E2 = ("socks5://u:pw@10.0.0.2:1080", "pool-b")


def _spaced(ts: list[float], gap: float) -> bool:
    ts = sorted(ts)
    return all(b - a >= gap - 0.01 for a, b in zip(ts, ts[1:]))


def case_egress_key_table():
    for url, label, key, lb in [
        (None, None, "direct", "direct"),
        ("", "x", "direct", "direct"),
        ("http://user:secret@Proxy.Example.com:8080", "hu-1", "http://proxy.example.com:8080", "hu-1"),
        ("http://other:pw2@proxy.example.com:8080/", "hu-1", "http://proxy.example.com:8080", "hu-1"),
        ("socks5://127.0.0.1:9050", "infloww-0a1b2c3d", "socks5://127.0.0.1:9050", "infloww-0a1b2c3d"),
        ("http://u:p@1.2.3.4:3128", "1.2.3.4:3128", "http://1.2.3.4:3128", None),
        ("http://u:p@1.2.3.4:3128", None, "http://1.2.3.4:3128", None),
        ("http://u:p@h.example.com:1", "bad label;rm", "http://h.example.com:1", "badlabelrm"),
    ]:
        k, got = of_pacing.egress(url, label)
        assert k == key, (url, k)
        assert "secret" not in k and "pw" not in k and "user" not in k
        if lb is None:
            assert got.startswith("p-") and len(got) == 10 and "1.2.3.4" not in got, got
        else:
            assert got == lb, (url, label, got)


def _ledger_walks(plan, pages, fail=None):
    """plan: {account: egress}; each walks `pages` ledger pages at once. `fail`: account whose
    first page OF answers 429 once. Every departure: (account, t)."""
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
            await asyncio.to_thread(of_pacing.paced, aid, lambda: get(aid), eg)

    async def main():
        await asyncio.gather(*(of_pacing.walk(a, "transactions", lambda a=a, eg=eg: job(a, eg))
                               for a, eg in plan.items()))
    asyncio.run(main())
    return sent


def case_proxy_slot_shared():
    gap = 0.08
    _knobs(PAGE_GAP_S=gap, JITTER_S=0.0)
    e1, e2 = of_pacing.egress(*E1), of_pacing.egress(*E2)
    sent = _ledger_walks({"a1": e1, "a2": e1, "b1": e2}, 4)
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
    e1 = of_pacing.egress(*E1)
    lines: list[str] = []

    class H(logging.Handler):
        def emit(self, r):
            lines.append(r.getMessage())
    h = H()
    of_pacing.log.addHandler(h)
    of_pacing.log.setLevel(logging.INFO)
    try:
        sent = _ledger_walks({"a1": e1, "a2": e1}, 3, fail="a1")
    finally:
        of_pacing.log.removeHandler(h)
    assert sum(1 for a, _ in sent if a == "a1") == 4 and sum(1 for a, _ in sent if a == "a2") == 3, sent
    assert _spaced([t for _, t in sent], gap), "the retry takes the endpoint slot too"
    retry = [x for x in lines if x.startswith("bg_walk_429_retry")]
    assert len(retry) == 1 and "account=a1" in retry[0] and "proxy=pool-a" in retry[0], retry
    assert "10.0.0.1" not in retry[0] and "pw" not in retry[0] and "1080" not in retry[0], retry


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


def _walk_gets(jobs, pages):
    """jobs: [(account, client, url)] each its own walk, `pages` GETs at once."""
    async def job(c, url):
        for _ in range(pages):
            await asyncio.to_thread(c.get_json, url)

    async def main():
        await asyncio.gather(*(of_pacing.walk(a, "transactions", lambda c=c, u=u: job(c, u)) for a, c, u in jobs))
    asyncio.run(main())


def case_link_stats_per_creator():
    gap = 0.08
    _knobs(PAGE_GAP_S=gap, JITTER_S=0.0)
    sent: list = []
    a1, a2 = _record(_client("a1", *E1), sent, "a1"), _record(_client("a2", *E1), sent, "a2")
    stats = "https://onlyfans.com/api2/v2/trial-links/stats"
    _walk_gets([("a1", a1, stats), ("a2", a2, stats)], 3)
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
    for _ in range(3):   # outside a walk (a person's read): never paced
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
        reg([], ["x", "y"])   # the move: one registry write; the old client is still out
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
