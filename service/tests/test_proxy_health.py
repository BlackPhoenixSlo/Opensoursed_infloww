#!/usr/bin/env python3
"""Proxy health (roadmap 2.14, service/proxy_health.py + proxy_probe.py).

Pins (the probes and the Test button: test_proxy_probe.py; failover and
the pool binding: test_proxy_failover.py): DOWN_AFTER
errors in a row start a confirm probe: when it answers the proxy is a blip
(count restarts, nothing announced); when it fails the proxy is bad (`down`),
announced as `proxy_switched` {down} to each Creator on it, and rechecked
with backoff. One answer brings it back up (announced too); a healthy proxy
staying healthy writes nothing. A ProxyError out of OFClient._http_call
counts as an error and an answer as a success. /admin/proxies carries the
pool's `bad` count, /admin/accounts carries `proxy_down`. The confirm waits CONFIRM_GAP_S
after the streak's first error and is skipped when an answer reset the count
meanwhile (a blip); a proxy gone from the registry ends its watcher. A
proxy back up mid-recheck and at DOWN_AFTER again is confirmed by the same
watcher; a streak right after a watcher's end starts the next. Only a
full-policy failure counts (test_proxy_retry_interactive). The periodic probe is off
unless PROXY_HEALTH_INTERVAL_S is set, and probes only proxies a Creator is on.

No network: the curl session, the probe and the OF client's http are fakes;
the watcher runs inline (`_spawn`) and never sleeps (`_sleep`).

Run:  ./venv/bin/python service/tests/test_proxy_health.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import os  # noqa: E402
import random  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402

from curl_cffi import requests as curl_requests  # noqa: E402

import proxies  # noqa: E402
import proxy_health  # noqa: E402
import proxy_health_decide  # noqa: E402
import proxy_probe  # noqa: E402
from of_client import OFClient, RetryPolicy  # noqa: E402
from _proxy_health_fixtures import (  # noqa: E402
    _Events, _Watch, _advance, _fail, _on, _pool, _registry, _spread_refusals, _then)


def case_down_after_consecutive_errors_confirmed_and_back_up():
    _registry()
    # The confirm fails; the first recheck "wait" is an answer through the proxy
    # (a Creator still on it), which ends the watcher.
    with _Events() as ev, _Watch(False) as w:
        _fail("hu-1", proxy_health_decide.DOWN_AFTER - 1)
        snap = proxy_health.snapshot("hu-1")
        assert not snap["down"] and snap["state"] == "suspect" and ev.seen == [] and w.probed == [], snap
        proxy_health._sleep = _then(None, lambda: proxy_health.record("hu-1", True))
        proxy_health.record("hu-1", False, "boom")
        assert w.probed == ["hu-1"], "the third error confirms with one probe"
        assert sorted(ev.seen, key=lambda e: (e[1]["account_id"], not e[1]["down"])) == [
            ("proxy_switched", {"account_id": "101", "proxied": True, "down": True}),
            ("proxy_switched", {"account_id": "101", "proxied": True, "down": False}),
            ("proxy_switched", {"account_id": "102", "proxied": True, "down": True}),
            ("proxy_switched", {"account_id": "102", "proxied": True, "down": False}),
        ], ev.seen
        snap = proxy_health.snapshot("hu-1")
        assert not snap["down"] and snap["state"] == "healthy" and snap["errors"] == 0, snap
        assert proxy_health.down_labels() == set() and not proxy_health._watchers


def case_confirm_that_answers_is_a_blip():
    _registry()
    with _Events() as ev, _Watch(True) as w:
        _fail("hu-1")
        assert w.probed == ["hu-1"] and ev.seen == [], "answered: nothing announced"
        assert 0 < w.slept[0] <= proxy_health.CONFIRM_GAP_S, f"the confirm waited out a blip first: {w.slept}"
        snap = proxy_health.snapshot("hu-1")
        assert not snap["down"] and snap["errors"] == 0 and snap["state"] == "healthy", snap
        assert snap["probe"]["ttfb_ms"] == 80 and snap["probe"]["ok"], "the confirm's probe result is kept"


def case_confirm_waits_and_a_blip_that_ends_meanwhile_probes_nothing():
    """F5: three counted failures inside one blip. The confirm would go through
    the same blip, so it waits CONFIRM_GAP_S from the streak's first error; any
    answer through the proxy meanwhile ends the streak without a probe."""
    _registry()
    with _Events() as ev, _Watch(False) as w:
        proxy_health._sleep = _then(lambda: proxy_health.record("hu-1", True))
        _fail("hu-1")
        assert w.probed == [] and ev.seen == [], "the blip ended in the wait: no probe, nothing announced"
        assert proxy_health.snapshot("hu-1")["state"] == "healthy" and not proxy_health._watchers
    os.environ[proxy_health.RECHECK_ENV] = "2"
    try:
        assert proxy_health.confirm_gap_s() == proxy_health.CONFIRM_GAP_S * 2 / proxy_health.RECHECK_S, \
            "PROXY_RECHECK_S scales the confirm's wait with the rechecks"
    finally:
        os.environ.pop(proxy_health.RECHECK_ENV, None)
    assert proxy_health.confirm_gap_s() == proxy_health.CONFIRM_GAP_S


def case_recheck_backoff_then_back_up():
    _registry()
    os.environ[proxy_health.RECHECK_ENV] = "5"
    try:
        with _Events() as ev, _Watch(False, False, False, True) as w:
            _fail("hu-1")
    finally:
        os.environ.pop(proxy_health.RECHECK_ENV, None)
    assert w.probed == ["hu-1"] * 4, w.probed   # confirm + 3 rechecks
    assert w.slept[1:] == [5, 10, 20], w.slept
    assert 0 < w.slept[0] <= proxy_health.CONFIRM_GAP_S * 5 / proxy_health.RECHECK_S, w.slept
    snap = proxy_health.snapshot("hu-1")
    assert not snap["down"] and snap["state"] == "healthy" and snap["next_recheck_at"] is None, snap
    assert [e[1]["down"] for e in ev.seen] == [True, True, False, False], ev.seen
    assert snap.get("failed_over", 0) == 0, "a custom proxy's Creators are never moved"


def _through_during_the_confirm(then=lambda: None):
    """A `proxy_probe.probe_of` wrapper (inside `_Watch`): on the confirm probe, an OF call through the proxy
    answers first, then `then()` runs, then the probe answers as scripted."""
    inner = proxy_probe.probe_of

    def _probe(p, timeout_s=15):
        proxy_health.record(p["label"], True)
        then()
        proxy_probe.probe_of = inner   # once
        return inner(p, timeout_s)
    proxy_probe.probe_of = _probe


def _new_streak_confirmed_after_its_gap(w, ev) -> None:
    """The first confirm's probe failed after a call got through and a whole new streak: not bad; the same
    watcher waits a full CONFIRM_GAP_S from the new streak's first error, its confirm fails: bad. The
    recheck then answers: back up."""
    gap = proxy_health.confirm_gap_s()
    assert w.probed == ["hu-1"] * 3, f"confirm, the new streak's confirm, one recheck: {w.probed}"
    assert [round(s, 6) for s in w.slept[:3]] == [gap, 0.0, gap], \
        f"a full gap before each confirm (0: the rejected confirm's Wait(0, ConfirmDue) back to the wait): {w.slept}"
    assert [kw["down"] for _, kw in ev.seen] == [True, True, False, False], \
        f"bad announced once (by the 2nd confirm), then back up: {ev.seen}"
    snap = proxy_health.snapshot("hu-1")
    assert not snap["down"] and snap["state"] == "healthy" and not proxy_health._watchers, snap


def case_failed_confirm_after_a_call_got_through_is_not_bad():
    """ADR 0030: a call that got through while the confirm probed means the proxy is not bad, even
    though the probe itself failed. With a whole new streak since, the same watcher confirms that one
    CONFIRM_GAP_S after its first error (nobody is left watching a proxy at DOWN_AFTER)."""
    _registry()
    with _Events() as ev, _Watch(False) as w:
        _through_during_the_confirm()
        _fail("hu-1")
        assert w.probed == ["hu-1"] and ev.seen == [], f"probed once, nothing announced: {ev.seen}"
        snap = proxy_health.snapshot("hu-1")
        assert not snap["down"] and snap["state"] == "healthy" and not proxy_health._watchers, snap
    _registry()
    with _Events() as ev, _Watch(False, False) as w:
        _through_during_the_confirm(lambda: _fail("hu-1"))   # a new streak lands during the probe
        _fail("hu-1")
        _new_streak_confirmed_after_its_gap(w, ev)


def case_confirm_is_for_the_streak_it_waited_on():
    """The streak a confirm probes for is the one its wait was decided on, in the same lock section: a
    reset and a whole new streak landing after that decision, before the probe, make a failed probe
    not bad, and the new streak gets its own full CONFIRM_GAP_S (no confirm sooner)."""
    _registry()
    real_step, injected = proxy_health._step, []

    def _step(label, event):
        nxt = real_step(label, event)
        if isinstance(nxt, proxy_health_decide.Confirm) and not injected:
            injected.append(nxt)
            proxy_health.record(label, True)
            _fail(label)
        return nxt
    try:
        proxy_health._step = _step
        with _Events() as ev, _Watch(False, False) as w:
            _fail("hu-1")
            assert injected == [proxy_health_decide.Confirm(1)], injected
            _new_streak_confirmed_after_its_gap(w, ev)
    finally:
        proxy_health._step = real_step


def case_confirm_waits_again_for_a_streak_that_restarted_in_the_wait():
    """N5: the streak ended and a new one began during the confirm's wait:
    the confirm waits CONFIRM_GAP_S from the new streak's first error."""
    _registry()
    with _Watch(False, True) as w:
        waits: list[tuple[float, list[str]]] = []
        steps = iter([lambda: (proxy_health.record("hu-1", True), _fail("hu-1"))])

        def _sleep(s):
            waits.append((s, list(w.probed)))
            _advance(s)
            step = next(steps, None)
            if step:
                step()
        proxy_health._sleep = _sleep
        _fail("hu-1")
    assert len(waits) >= 2 and waits[0][1] == [] and waits[1][1] == [], f"no probe before the second wait: {waits}"
    assert waits[1][0] > proxy_health.confirm_gap_s() - 1, f"a full gap from the new streak: {waits}"
    assert w.probed[0] == "hu-1"


def case_one_endpoint_counts_once_custom_or_pool():
    """F7: an endpoint held as a custom entry (verified) and as a pool entry
    (not yet) is one egress: its custom bindings make the pool entry used."""
    a, b, c = _pool()
    pa = proxies.get_by_label(a)
    proxies.upsert({"label": "same", "scheme": "socks5", "host": pa["host"], "port": pa["port"]})
    proxies.record_verification("same", ip="203.0.113.50", geo=None, ok=True)
    for aid in ("20", "21", "22"):
        proxies.assign_account("same", aid)
    proxy_health.verify_pick = lambda p, **_: True
    for seed in range(10):
        proxies.unbind_pool("7")
        assert proxy_health.assign_pool("7", random.Random(seed))[0]["label"] != a, \
            "a's endpoint already carries 2 + 3 Creators"


def case_proxies_list_counts_bad_pool():
    a, b, c = _pool()
    import server
    import proxies_admin_api
    real_user, real_list = server._get_request_user, server.account_registry.list_accounts
    server._get_request_user = lambda: types.SimpleNamespace(id="o", account_ids={"1", "2", "3", "4", "5", "6"},
                                                             is_admin=True)
    server.account_registry.list_accounts = lambda **_: [{"id": str(i)} for i in range(1, 7)]
    try:
        proxy_health._state[a] = {**proxy_health_decide.blank(), "down": True, "bad_reason": "down"}
        out = proxies_admin_api.admin_proxies_list()
    finally:
        server._get_request_user, server.account_registry.list_accounts = real_user, real_list
    rows = out["pool"].pop("proxies")
    assert out["pool"] == {"size": 3, "account_ids": out["pool"]["account_ids"], "bad": 1}, out["pool"]
    assert [r["slot"] for r in rows] == [1, 2, 3] and [r["health"]["down"] for r in rows] == [True, False, False], rows
    assert out["proxies"] == [], "pool entries stay unlisted"


def case_health_view_shows_cross_agency_totals_to_the_site_owner_only():
    """The refusal window's counts and the in-flight counts are every Agency's traffic through the proxy:
    the site owner sees them, an Agency's owner the share alone, on custom and pool rows alike."""
    import proxies_admin_api
    h = {"state": "bad", "down": True, "errors": 2, "bad_reason": "flapping", "inflight": 3, "inflight_peak": 9,
         "refusals": {"window_s": 600.0, "refused": 31, "calls": 100, "pct": 31.0}}
    view = proxies_admin_api._health_view
    for site_owner, keys, want in [
        (True, None, h),
        (False, None, {"state": "bad", "down": True, "errors": 2, "bad_reason": "flapping",
                       "refusals": {"window_s": 600.0, "pct": 31.0}}),
        (True, ("state", "down", "refusals", "inflight", "inflight_peak"),
         {"state": "bad", "down": True, "refusals": h["refusals"], "inflight": 3, "inflight_peak": 9}),
        (False, ("state", "down", "refusals", "inflight", "inflight_peak"),
         {"state": "bad", "down": True, "refusals": {"window_s": 600.0, "pct": 31.0}}),
        (False, ("state",), {"state": "bad"}),
    ]:
        got = view(dict(h), site_owner, keys=keys)
        assert got == want, (site_owner, keys, got)
    assert h["refusals"]["calls"] == 100, "the snapshot itself is never trimmed"

    _registry()
    import server
    real_user, real_list = server._get_request_user, server.account_registry.list_accounts
    server.account_registry.list_accounts = lambda **_: [{"id": "101"}]
    try:
        for is_admin in (True, False):
            server._get_request_user = lambda: types.SimpleNamespace(id=None, account_ids={"101"}, is_admin=is_admin)
            row = {p["label"]: p for p in proxies_admin_api.admin_proxies_list()["proxies"]}["hu-1"]
            assert ("calls" in row["health"]["refusals"]) is is_admin and ("inflight" in row["health"]) is is_admin, \
                (is_admin, row["health"])
    finally:
        server._get_request_user, server.account_registry.list_accounts = real_user, real_list


def case_recheck_period_floor():
    os.environ.pop(proxy_health.RECHECK_ENV, None)
    assert proxy_health.recheck_s() == proxy_health.RECHECK_S
    os.environ[proxy_health.RECHECK_ENV] = "0.01"
    try:
        assert proxy_health.recheck_s() == proxy_health._MIN_RECHECK_S
    finally:
        os.environ.pop(proxy_health.RECHECK_ENV, None)


def case_an_answer_resets_the_count():
    _registry()
    for _ in range(proxy_health_decide.DOWN_AFTER - 1):
        proxy_health.record("hu-1", False, "boom")
    proxy_health.record("hu-1", True)
    proxy_health.record("hu-1", False, "boom")
    assert proxy_health.snapshot("hu-1")["errors"] == 1, "errors must be consecutive"
    assert proxy_health.snapshot("hu-1")["state"] == "suspect"


def case_healthy_success_writes_nothing():
    _registry()
    proxy_health.record("hu-1", True)
    proxy_health.record(None, False, "direct: no proxy")
    assert proxy_health._state == {}


def _bare_client(get):
    c = OFClient.__new__(OFClient)
    c.account_id = "101"
    c.user_id = "101"
    c.proxy_label = "hu-1"
    c.proxy_url = "http://u:p@198.51.100.1:8080"
    c.timeout_s = 5
    c._x_hash = "x"
    c.http = types.SimpleNamespace(get=get)
    c._signed_headers = lambda url: {}
    c._proxy_retry = lambda fn, **kw: OFClient._proxy_retry(c, fn, **{**kw, "policy": RetryPolicy(1, 0.0, True)})
    c._persist_cf_cookies = lambda r: None
    return c


def case_of_calls_feed_the_state():
    _registry()

    def _refused(url, **kw):
        raise curl_requests.exceptions.ProxyError("CONNECT tunnel failed, response 403")
    c = _bare_client(_refused)
    with _Events(), _Watch(False) as w:
        proxy_health._sleep = _then(None, lambda: proxy_health.record("hu-1", True))  # ends the watcher
        for _ in range(proxy_health_decide.DOWN_AFTER):
            try:
                c._http_call("GET", "https://onlyfans.com/api2/v2/users/me")
            except curl_requests.exceptions.ProxyError:
                pass
            else:
                raise AssertionError("the ProxyError must still reach the caller")
        assert w.probed == ["hu-1"], "three refused calls confirm with one probe"
        _fail("hu-1", proxy_health_decide.DOWN_AFTER - 1)
        proxy_health._state["hu-1"]["down"] = True   # as after a failed confirm
        ok = _bare_client(lambda url, **kw: types.SimpleNamespace(headers={}, ok=True, status_code=200))
        ok._http_call("GET", "https://onlyfans.com/api2/v2/users/me")
    assert not proxy_health.snapshot("hu-1")["down"]


def case_a_refused_proxy_connect_counts_a_timeout_does_not():
    _registry()
    from curl_cffi.const import CurlECode

    def _raises(exc):
        def _get(url, **kw):
            raise exc
        return _bare_client(_get)
    with _Events():
        for exc in (curl_requests.exceptions.Timeout("Operation timed out", CurlECode.OPERATION_TIMEDOUT),
                    curl_requests.exceptions.ConnectionError("TLS reset", CurlECode.RECV_ERROR)):
            try:
                _raises(exc)._http_call("GET", "https://onlyfans.com/api2/v2/users/me")
            except Exception:
                pass
        assert proxy_health.snapshot("hu-1")["errors"] == 0, "not told apart from OF: not counted"
        refused = curl_requests.exceptions.ConnectionError(
            "Failed to connect to 198.51.100.1 port 8080", CurlECode.COULDNT_CONNECT)
        try:
            _raises(refused)._http_call("GET", "https://onlyfans.com/api2/v2/users/me")
        except curl_requests.exceptions.ConnectionError:
            pass
        else:
            raise AssertionError("the error must still reach the caller")
        assert proxy_health.snapshot("hu-1")["errors"] == 1


def case_watcher_ends_when_the_proxy_is_gone():
    """F15: a proxy deleted while bad: its watcher stops and its state goes."""
    _registry()
    with _Events(), _Watch(False):
        proxy_health._sleep = _then(None, lambda: proxies.remove("hu-1"))
        _fail("hu-1")
    assert "hu-1" not in proxy_health._state and not proxy_health._watchers


def case_an_error_right_after_the_watchers_last_step_starts_a_new_watcher():
    """N1: the watcher's last step releases its claim in its own lock section (Unwatch), so a streak's
    DOWN_AFTER-th error landing right after that decide, before the watcher has returned, starts a new
    watcher. A blip the confirm's wait outlasts (an answer resets the count: ConfirmDue ends the
    watcher), then the proxy dies for good: DOWN_AFTER errors injected just after that ConfirmDue's
    decide. Measured red with the claim released in `_watch`'s finally (the proxy left at DOWN_AFTER
    errors, nobody watching)."""
    _registry()
    real_step, ends, spawned = proxy_health._step, [], []

    def _step(label, event):
        seen = []

        def _seen():
            seen.append(event())
            return seen[-1]
        nxt = real_step(label, _seen)
        if not ends and nxt is None and isinstance(seen[0], proxy_health_decide.ConfirmDue):
            ends.append(seen[0])
            _fail(label)   # dead for good: the whole streak lands right at the watcher's end
        return nxt
    try:
        proxy_health._step = _step
        with _Events() as ev, _Watch(False, True) as w:
            inline = proxy_health._spawn
            proxy_health._spawn = lambda fn, name: (spawned.append(name), inline(fn, name))
            proxy_health._sleep = _then(lambda: proxy_health.record("hu-1", True))   # the blip ends in the wait
            _fail("hu-1")
    finally:
        proxy_health._step = real_step
    assert len(ends) == 1, ends
    assert spawned == ["proxy-watch-hu-1"] * 2, f"the streak after the watcher's end got its own: {spawned}"
    assert w.probed == ["hu-1"] * 2, f"the new watcher's confirm (fails: bad), a recheck (answers): {w.probed}"
    assert [kw["down"] for _, kw in ev.seen] == [True, True, False, False], ev.seen
    assert proxy_health.snapshot("hu-1")["state"] == "healthy" and not proxy_health._watchers


def case_back_at_the_bar_during_a_recheck_sleep_is_confirmed_by_the_same_watcher():
    """F1: bad, the watcher sleeps before a recheck; a call answers (back up), then DOWN_AFTER errors land
    with the claim still held (no new watcher). The waking watcher goes back to the confirm phase: the
    confirm fails (bad again), the next recheck answers. Measured red with the recheck's not-down
    branch ending the watcher (the proxy left at DOWN_AFTER errors, nobody watching)."""
    _registry()
    spawned: list[str] = []
    with _Events() as ev, _Watch(False, False, True) as w:
        inline = proxy_health._spawn
        proxy_health._spawn = lambda fn, name: (spawned.append(name), inline(fn, name))
        proxy_health._sleep = _then(None, lambda: (proxy_health.record("hu-1", True), _fail("hu-1")))
        _fail("hu-1")
    assert spawned == ["proxy-watch-hu-1"], f"one watcher throughout: {spawned}"
    assert w.probed == ["hu-1"] * 3, f"confirm (bad), the new streak's confirm (bad), a recheck: {w.probed}"
    assert [kw["down"] for _, kw in ev.seen] == [True, True, False, False, True, True, False, False], ev.seen
    assert proxy_health.snapshot("hu-1")["state"] == "healthy" and not proxy_health._watchers


def case_a_watcher_that_raises_releases_its_claim():
    _registry()
    spawned: list[str] = []
    proxy_health.log.disabled = True   # its traceback, logged on purpose
    try:
        with _Watch() as w:
            proxy_health._spawn = lambda fn, name: (spawned.append(name), fn())

            def _boom(p, timeout_s=15):
                raise RuntimeError("probe blew up")
            proxy_probe.probe_of = _boom
            _fail("hu-1")
            assert not proxy_health._watchers, "the dead watcher's claim is released"
            _fail("hu-1", 1)
    finally:
        proxy_health.log.disabled = False
    assert spawned == ["proxy-watch-hu-1"] * 2 and not w.probed, f"the next error starts another: {spawned}"


def case_concurrent_errors_start_one_watcher_and_one_failover():
    """Two errors at once at the DOWN_AFTER-th: `_step` claims the label under its lock, so exactly one
    watcher is spawned; that watcher, run after the race with a probe that never answers, calls
    failover_pool once at the first failover due point. The interleaving is forced, not hoped for: A's
    claim (`_watchers.add`) starts B and holds until B is blocked on the lock (the claim is inside it: B
    then sees the claim) or B's error is through (it is not: B decided before the claim and spawned a
    second watcher). Measured red every run with `_watchers.add` moved out of the lock."""
    import threading
    real_lock, real_watchers, real_failover = proxy_health._lock, proxy_health._watchers, proxies.failover_pool
    b_moved = threading.Event()   # B is blocked on the lock, or its whole error went through
    racer: list[threading.Thread] = []

    def _b():
        proxy_health.record("hu-1", False, "CONNECT tunnel failed, response 403")
        b_moved.set()

    class _Lock:   # the real lock; tells A when B has to wait for it
        def __enter__(self):
            if not real_lock.acquire(blocking=False):
                if racer and threading.current_thread() is racer[0]:
                    b_moved.set()
                real_lock.acquire()
            return self

        def __exit__(self, *_):
            real_lock.release()

    class _Claims(set):   # A's claim lets B race first
        def add(self, label):
            if not racer:
                racer.append(threading.Thread(target=_b))
                racer[0].start()
                assert b_moved.wait(10), "B neither blocked on the lock nor got through"
            super().add(label)

    try:
        _registry()
        proxy_health._lock, proxy_health._watchers = _Lock(), _Claims()
        spawned, failovers = [], []
        proxies.failover_pool = lambda label, **_: failovers.append(label) or []
        with _Events() as ev, _Watch(dead={"hu-1"}):
            proxy_health._spawn = lambda fn, name: spawned.append((name, fn))
            # the confirm's wait, two recheck waits (the 2nd failed recheck fails over), then it leaves
            proxy_health._sleep = _then(None, None, None, lambda: proxies.remove("hu-1"))
            _fail("hu-1", proxy_health_decide.DOWN_AFTER)   # A: its DOWN_AFTER-th error claims the label
            assert racer, "A's claim did not go through _watchers.add under the lock: the race never ran"
            racer[0].join(10)
            assert not racer[0].is_alive()
            assert [name for name, _ in spawned] == ["proxy-watch-hu-1"], f"one watcher for 2 racing errors: {spawned}"
            assert proxy_health._state["hu-1"]["errors"] == proxy_health_decide.DOWN_AFTER + 1, \
                "both racing errors counted"
            assert proxy_health._watchers == {"hu-1"}
            spawned[0][1]()
        assert failovers == ["hu-1"], f"one failover: {failovers}"
        assert ev.seen == [("proxy_switched", {"account_id": aid, "proxied": True, "down": True})
                           for aid in ("101", "102")] + [
            ("proxy_switched", {"account_id": aid, "proxied": False}) for aid in ("101", "102")
        ], f"bad announced once, then the removal unbinds them; nothing else: {ev.seen}"
        assert "hu-1" not in proxy_health._state and not proxy_health._watchers
    finally:
        proxy_health._lock, proxy_health._watchers = real_lock, real_watchers
        proxies.failover_pool = real_failover


def case_accounts_list_flags_proxy_down():
    _registry()
    import server
    import accounts_admin_api
    from fastapi import Response
    import asyncio
    fake_user = types.SimpleNamespace(account_ids={"101", "201"})
    real_user, real_list = server._get_request_user, server.account_registry.list_accounts
    server._get_request_user = lambda: fake_user
    server.account_registry.list_accounts = lambda **_: [{"id": "101"}, {"id": "201"}]
    try:
        proxy_health._state["hu-1"] = {**proxy_health_decide.blank(), "down": True, "bad_reason": "down"}
        out = asyncio.run(accounts_admin_api.admin_accounts_list(Response()))
    finally:
        server._get_request_user, server.account_registry.list_accounts = real_user, real_list
    flags = {a["id"]: a["proxy_down"] for a in out["accounts"]}
    assert flags == {"101": True, "201": False}, flags


def case_accounts_list_reads_each_binding_once_and_survives_an_unbind():
    """One registry read per account, the reason from that read's label: an unbind between reads (the old
    second `get_for_account(...)["label"]`) cannot 500, a failover between them cannot borrow another
    proxy's reason. 101 on flapping hu-1, 102 unbound when read, 201 on nothing."""
    _registry()
    import server
    import accounts_admin_api
    from fastapi import Response
    import asyncio
    fake_user = types.SimpleNamespace(account_ids={"101", "102", "201"})
    real_user, real_list = server._get_request_user, server.account_registry.list_accounts
    real_get = proxies.get_for_account
    reads: list[str] = []

    def _get(aid):
        reads.append(aid)
        return None if aid == "102" else real_get(aid)
    server._get_request_user = lambda: fake_user
    server.account_registry.list_accounts = lambda **_: [{"id": "101"}, {"id": "102"}, {"id": "201"}]
    proxies.get_for_account = _get
    try:
        proxy_health._state["hu-1"] = {**proxy_health_decide.blank(), "down": True, "bad_reason": "flapping"}
        out = asyncio.run(accounts_admin_api.admin_accounts_list(Response()))
    finally:
        server._get_request_user, server.account_registry.list_accounts = real_user, real_list
        proxies.get_for_account = real_get
    rows = {a["id"]: (a["proxy_down"], a.get("proxy_bad_reason")) for a in out["accounts"]}
    assert rows == {"101": (True, "flapping"), "102": (False, None), "201": (False, None)}, rows
    assert sorted(reads) == ["101", "102", "201"], f"one read per account: {reads}"
    assert proxy_health.bad_reasons() == {"hu-1": "flapping"}


def case_periodic_probe_is_opt_in():
    os.environ.pop(proxy_health.INTERVAL_ENV, None)
    assert proxy_health.interval_s() == 0
    os.environ[proxy_health.INTERVAL_ENV] = "60"
    try:
        assert proxy_health.interval_s() == proxy_health._MIN_INTERVAL_S, "floored, never chatty"
    finally:
        os.environ.pop(proxy_health.INTERVAL_ENV, None)


def case_probe_all_only_creator_proxies():
    _registry()
    probed: list[str] = []
    real = proxy_probe.probe_of
    proxy_probe.probe_of = lambda p, timeout_s=15: probed.append(p["label"]) or {"ok": True}
    try:
        assert proxy_health.probe_all() == 1
    finally:
        proxy_probe.probe_of = real
    assert probed == ["hu-1"], "the unbound proxy is not probed"


# ── refusal telemetry and the flap knob ──
def _refused_then(n: int):
    """A raw call refused `n` times (ProxyError), then answering."""
    left = [n]

    def fn():
        if left[0]:
            left[0] -= 1
            raise curl_requests.exceptions.ProxyError("CONNECT tunnel failed, response 403")
        return types.SimpleNamespace(ok=True)
    return fn


def case_refusal_window_counts_every_attempt_and_prunes():
    _registry()
    clock, real_now = [1000.0], proxy_health._now
    proxy_health._now = lambda: clock[0]
    try:
        c = _bare_client(lambda url, **kw: None)
        OFClient._proxy_retry(c, _refused_then(2), policy=RetryPolicy(3, 0.0, False))   # refused, refused, ok
        from curl_cffi.const import CurlECode

        def _timeout():
            raise curl_requests.exceptions.Timeout("Operation timed out", CurlECode.OPERATION_TIMEDOUT)
        try:
            OFClient._proxy_retry(c, _timeout)
        except curl_requests.exceptions.Timeout:
            pass
        assert proxy_health.refusals("hu-1") == {"window_s": 600.0, "refused": 2, "calls": 3, "pct": 66.7}, \
            "every attempt, whatever the policy; a timeout is left out"
        assert proxy_health.snapshot("hu-1")["refusals"]["calls"] == 3
        clock[0] += 599
        assert proxy_health.refusals("hu-1")["calls"] == 3
        clock[0] += 2
        assert proxy_health.refusals("hu-1") == {"window_s": 600.0, "refused": 0, "calls": 0, "pct": 0.0}, "pruned"
        os.environ[proxy_health.FLAP_WINDOW_ENV] = "60"
        try:
            assert proxy_health.refusals("hu-1")["window_s"] == 60.0
        finally:
            os.environ.pop(proxy_health.FLAP_WINDOW_ENV, None)
        real_cap, proxy_health._WINDOW_CAP = proxy_health._WINDOW_CAP, 5
        try:
            for i in range(8):
                proxy_health._sample("hu-1", i < 3)   # 3 refused then 5 ok: the cap keeps the last 5
            assert proxy_health.refusals("hu-1")["refused"] == 0 and proxy_health.refusals("hu-1")["calls"] == 5
        finally:
            proxy_health._WINDOW_CAP = real_cap
    finally:
        proxy_health._now = real_now


def case_inflight_counts_concurrent_attempts():
    import threading
    _registry()
    n, gate = 5, threading.Barrier(5 + 1)
    seen = []

    def fn():
        gate.wait(5)        # all n inside fn
        gate.wait(5)        # the main thread has read inflight
        return types.SimpleNamespace(ok=True)
    c = _bare_client(lambda url, **kw: None)
    threads = [threading.Thread(target=OFClient._proxy_retry, args=(c, fn)) for _ in range(n)]
    for t in threads:
        t.start()
    gate.wait(5)
    seen.append(proxy_health.snapshot("hu-1")["inflight"])
    gate.wait(5)
    for t in threads:
        t.join(5)
    snap = proxy_health.snapshot("hu-1")
    assert seen == [n] and snap["inflight"] == 0 and snap["inflight_peak"] == n, (seen, snap)
    assert snap["refusals"]["calls"] == n
    bare = _bare_client(lambda url, **kw: None)
    bare.proxy_label = None
    OFClient._proxy_retry(bare, lambda: types.SimpleNamespace(ok=True))
    assert set(proxy_health._tele) == {"hu-1"}, "a client with no proxy label counts nothing"


def case_flap_knob_on_by_default_zero_turns_it_off():
    """Env unset: the knob is FLAP_PCT_DEFAULT (20, the owner's 2026-11-05 call): the 20th attempt at >= 20 %,
    refusals in 3 tenths of the window, marks the pool proxy bad (bad_reason "flapping"). PROXY_FLAP_BAD_PCT=0
    turns it off: the same window marks nothing and `flapping` is False."""
    a, b, c = _pool()
    os.environ.pop(proxy_health.FLAP_PCT_ENV, None)
    assert proxy_health.flap_bad_pct() == proxy_health.FLAP_PCT_DEFAULT == 20.0
    with _Events() as ev, _Watch():
        _spread_refusals(a, 15, 4)                               # 19 attempts, 21 %: too few to judge
        assert not proxy_health.snapshot(a)["down"] and ev.seen == []
        spawned = []
        proxy_health._spawn = lambda fn, name: spawned.append(fn)   # the watcher as a thread: not run here
        proxy_health._sample(a, True)                            # the 20th, 25 %: bad
        snap = proxy_health.snapshot(a)
        assert snap["state"] == "bad" and snap["bad_reason"] == "flapping" and len(spawned) == 1, snap
        assert [(e[1]["account_id"], e[1]["down"]) for e in ev.seen] == [("1", True), ("4", True)], ev.seen
    a, b, c = _pool()
    os.environ[proxy_health.FLAP_PCT_ENV] = "0"
    try:
        assert proxy_health.flap_bad_pct() == 0.0
        with _Events() as ev, _Watch():
            _spread_refusals(a, 0, 50)
        snap = proxy_health.snapshot(a)
        assert snap["refusals"]["pct"] == 100.0 and not snap["down"] and snap["state"] == "healthy", snap
        assert ev.seen == [] and not proxy_health.still_flapping(a)
    finally:
        os.environ.pop(proxy_health.FLAP_PCT_ENV, None)


def case_flap_knob_marks_bad_fails_over_and_clears_below_half():
    """PROXY_FLAP_BAD_PCT=30: the 20th attempt at >= 30 %, refusals in 3 tenths of the window, marks the pool
    proxy bad (no confirm; bad_reason "flapping"); each recheck probe answers, but while the rate (its own sample
    counted) stays >= 15 % (half: hysteresis, over >= 20 attempts) it is a failed one: the second
    moves its Creators (the existing failover); 21 % still fails; the first under 15 % brings it back."""
    a, b, c = _pool()
    os.environ[proxy_health.FLAP_PCT_ENV] = "30"
    os.environ[proxy_health.RECHECK_ENV] = "5"
    try:
        with _Events() as ev, _Watch() as w:
            _spread_refusals(a, 13, 6)                           # 19 attempts, 31.6 %: too few to judge
            assert not proxy_health.snapshot(a)["down"] and ev.seen == []
            spawned = []
            proxy_health._spawn = lambda fn, name: spawned.append(fn)   # as a thread: after the announce
            proxy_health._sample(a, True)                        # the 20th, 35 %: bad
            snap = proxy_health.snapshot(a)
            assert snap["state"] == "bad" and snap["bad_reason"] == "flapping" and len(spawned) == 1, snap
            assert [(e[1]["account_id"], e[1]["down"]) for e in ev.seen] == [("1", True), ("4", True)], ev.seen

            def oks(n):
                return lambda: [proxy_health._sample(a, False) for _ in range(n)]
            # rechecks: 7/21 33 %, 7/22 32 % (failover), +10 ok: 7/33 21 % (>= 15: still bad), +15 ok: 7/49 14 %
            proxy_health._sleep = _then(None, None, oks(10), oks(15))
            spawned[0]()
    finally:
        os.environ.pop(proxy_health.FLAP_PCT_ENV, None)
        os.environ.pop(proxy_health.RECHECK_ENV, None)
    assert w.probed.count(a) == 4, w.probed
    assert _on(a) == [], "moved at the second failed recheck"
    snap = proxy_health.snapshot(a)
    assert snap["state"] == "healthy" and "bad_reason" not in snap and snap["refusals"] == {
        "window_s": 600.0, "refused": 7, "calls": 49, "pct": 14.3}, snap
    assert snap["failed_over"] == 2, snap


def case_flap_blip_or_down_streak_is_not_flap_bad():
    """A short full outage (25 refusals at 100 % inside 10 s: one or two tenths of the window) is the ADR path's
    (the 30 s confirm), never FlapBad; nor is a proxy with a DOWN_AFTER streak open (its confirm owns it)."""
    _registry()
    os.environ[proxy_health.FLAP_PCT_ENV] = "30"
    try:
        with _Events() as ev, _Watch():
            for _ in range(25):
                proxy_health._sample("hu-1", True)
                _advance(0.4)
            assert not proxy_health.snapshot("hu-1")["down"] and ev.seen == [], "a blip: no FlapBad"
            proxy_health._state["hu-1"] = {**proxy_health_decide.blank(), "errors": proxy_health_decide.DOWN_AFTER}
            proxy_health._watchers.add("hu-1")   # its confirm is under way
            _spread_refusals("hu-1", 0, 9)
            assert not proxy_health.snapshot("hu-1")["down"] and ev.seen == [], "the streak's confirm owns it"
    finally:
        os.environ.pop(proxy_health.FLAP_PCT_ENV, None)


def case_flap_failover_never_moves_onto_a_flapping_proxy():
    """Herd guard: every pool proxy refusing (b, c at 25 % over 3 tenths: under the knob, so not bad, but over
    half of it) and a goes flap-bad: its failover finds no destination (their probes would answer), nobody moves."""
    a, b, c = _pool()
    os.environ[proxy_health.FLAP_PCT_ENV] = "30"
    os.environ[proxy_health.RECHECK_ENV] = "5"
    try:
        with _Events(), _Watch() as w:
            spawned = []
            proxy_health._spawn = lambda fn, name: spawned.append(fn)
            _spread_refusals(a, 13, 7)
            assert proxy_health.snapshot(a)["bad_reason"] == "flapping"
            for other in (b, c):
                _spread_refusals(other, 18, 6)
            assert proxy_health.herd_guarded(b) and not proxy_health.snapshot(b)["down"]
            spawned[0]()
    finally:
        os.environ.pop(proxy_health.FLAP_PCT_ENV, None)
        os.environ.pop(proxy_health.RECHECK_ENV, None)
    assert _on(a) == ["1", "4"], "nobody moved onto a flapping proxy"
    assert b not in w.probed and c not in w.probed, w.probed
    assert proxy_health.snapshot(a).get("failed_over", 0) == 0


def case_flap_hysteresis_probe_class_and_bad_reason():
    """Still flapping down to X/2 % over >= FLAP_MIN_CALLS attempts, never marked bad below X, with no recency
    rule (it holds until the window drains); knob off: never flapping, even at 100 %; a probe timeout is in
    neither column, a refused one is; outage-bad reads "down"."""
    _registry()
    os.environ[proxy_health.FLAP_PCT_ENV] = "30"
    clock, real = [time.time()], proxy_health._now
    proxy_health._now = lambda: clock[0]
    try:
        for refused, flapping in ((2, False), (3, True), (5, True)):   # of 20: 10 %, 15 % (= half), 25 %
            proxy_health._tele.clear()
            for i in range(20):
                proxy_health._sample("hu-1", i < refused)
            assert proxy_health.still_flapping("hu-1") is flapping, refused
            assert not proxy_health.snapshot("hu-1")["down"], "under X: never marked bad"
        clock[0] += proxy_health.window_s() / 5 + 1
        assert proxy_health.still_flapping("hu-1"), "quiet for window/5: still flapping (no recency rule)"
        clock[0] += proxy_health.window_s()
        assert not proxy_health.still_flapping("hu-1"), "the window drained: no longer flapping"
        proxy_health._tele.clear()
        proxy_health._sample("hu-1", True)
        assert not proxy_health.still_flapping("hu-1"), "one refusal of one: too few attempts to judge"
    finally:
        proxy_health._now = real
        os.environ[proxy_health.FLAP_PCT_ENV] = "0"
    try:
        proxy_health._tele.clear()
        for _ in range(30):
            proxy_health._sample("hu-1", True)
        assert not proxy_health.still_flapping("hu-1"), "knob off (0): never flapping"
    finally:
        os.environ.pop(proxy_health.FLAP_PCT_ENV, None)
    proxy_health._tele.clear()
    proxy_health._keep_probe("hu-1", {"ok": False, "error": "proxy_probe_failed: Operation timed out", "refused": False})
    assert proxy_health.refusals("hu-1")["calls"] == 0, "a probe timeout is not a refusal"
    proxy_health._keep_probe("hu-1", {"ok": False, "error": "proxy_probe_failed: CONNECT 403", "refused": True})
    proxy_health._keep_probe("hu-1", {"ok": True})
    assert proxy_health.refusals("hu-1") == {"window_s": 600.0, "refused": 1, "calls": 2, "pct": 50.0}
    proxy_health._state["hu-1"] = {**proxy_health_decide.blank(), "down": True, "bad_reason": "down"}
    assert proxy_health.snapshot("hu-1")["bad_reason"] == "down"


def case_verify_pick_judges_by_probe_of_and_fills_the_region_once():
    a, b, c = _pool()
    with _Watch(True, True, False) as w:
        assert proxy_health.verify_pick(proxies.get_by_label(a))
        assert proxy_health.verify_pick(proxies.get_by_label(a))
        assert not proxy_health.verify_pick(proxies.get_by_label(b)), "refuses OF: passed over"
    assert w.probed == [a, a, b] and w.traced == [a], f"one trace, for a's unknown region: {w.traced}"
    assert proxy_health.last_geo(proxies.get_by_label(a)) == "HU"
    assert proxy_health._state[b]["errors"] == 1, "the failed destination check counts"


def case_a_login_attach_never_waits_on_the_region_trace():
    a, b, c = _pool()
    with _Watch(True) as w:   # every geo unknown: a failover's verify would trace once
        p, kept = proxy_health.assign_pool("7", random.Random(1))
    assert w.probed == [p["label"]] and w.traced == [], f"attach: one probe_of, no trace: {w.traced}"
    assert proxy_health.last_geo(p) is None


if __name__ == "__main__":
    _harness.run()
