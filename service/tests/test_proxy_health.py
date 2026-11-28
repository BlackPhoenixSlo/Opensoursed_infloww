#!/usr/bin/env python3
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
from _of_wire import fake_wire  # noqa: E402
from _proxy_health_fixtures import (  # noqa: E402
    _Events, _Watch, _advance, _fail, _on, _pool, _registry, _spread_refusals, _then)


def case_down_after_consecutive_errors_confirmed_and_back_up():
    _registry()
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
    assert w.probed == ["hu-1"] * 4, w.probed
    assert w.slept[1:] == [5, 10, 20], w.slept
    assert 0 < w.slept[0] <= proxy_health.CONFIRM_GAP_S * 5 / proxy_health.RECHECK_S, w.slept
    snap = proxy_health.snapshot("hu-1")
    assert not snap["down"] and snap["state"] == "healthy" and snap["next_recheck_at"] is None, snap
    assert [e[1]["down"] for e in ev.seen] == [True, True, False, False], ev.seen
    assert snap.get("failed_over", 0) == 0, "a custom proxy's Creators are never moved"


def _through_during_the_confirm(then=lambda: None):
    inner = proxy_probe.probe_of

    def _probe(p, timeout_s=15):
        proxy_health.record(p["label"], True)
        then()
        proxy_probe.probe_of = inner
        return inner(p, timeout_s)
    proxy_probe.probe_of = _probe


def _new_streak_confirmed_after_its_gap(w, ev) -> None:
    gap = proxy_health.confirm_gap_s()
    assert w.probed == ["hu-1"] * 3, f"confirm, the new streak's confirm, one recheck: {w.probed}"
    assert [round(s, 6) for s in w.slept[:3]] == [gap, 0.0, gap], \
        f"a full gap before each confirm (0: the rejected confirm's Wait(0, ConfirmDue) back to the wait): {w.slept}"
    assert [kw["down"] for _, kw in ev.seen] == [True, True, False, False], \
        f"bad announced once (by the 2nd confirm), then back up: {ev.seen}"
    snap = proxy_health.snapshot("hu-1")
    assert not snap["down"] and snap["state"] == "healthy" and not proxy_health._watchers, snap


def case_failed_confirm_after_a_call_got_through_is_not_bad():
    _registry()
    with _Events() as ev, _Watch(False) as w:
        _through_during_the_confirm()
        _fail("hu-1")
        assert w.probed == ["hu-1"] and ev.seen == [], f"probed once, nothing announced: {ev.seen}"
        snap = proxy_health.snapshot("hu-1")
        assert not snap["down"] and snap["state"] == "healthy" and not proxy_health._watchers, snap
    _registry()
    with _Events() as ev, _Watch(False, False) as w:
        _through_during_the_confirm(lambda: _fail("hu-1"))
        _fail("hu-1")
        _new_streak_confirmed_after_its_gap(w, ev)


def case_confirm_is_for_the_streak_it_waited_on():
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
    fake_wire(c, types.SimpleNamespace(get=get))
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
        proxy_health._sleep = _then(None, lambda: proxy_health.record("hu-1", True))
        for _ in range(proxy_health_decide.DOWN_AFTER):
            try:
                c._http_call("GET", "https://onlyfans.com/api2/v2/users/me")
            except curl_requests.exceptions.ProxyError:
                pass
            else:
                raise AssertionError("the ProxyError must still reach the caller")
        assert w.probed == ["hu-1"], "three refused calls confirm with one probe"
        _fail("hu-1", proxy_health_decide.DOWN_AFTER - 1)
        proxy_health._state["hu-1"]["down"] = True
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
    _registry()
    with _Events(), _Watch(False):
        proxy_health._sleep = _then(None, lambda: proxies.remove("hu-1"))
        _fail("hu-1")
    assert "hu-1" not in proxy_health._state and not proxy_health._watchers


def case_an_error_right_after_the_watchers_last_step_starts_a_new_watcher():
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
            _fail(label)
        return nxt
    try:
        proxy_health._step = _step
        with _Events() as ev, _Watch(False, True) as w:
            inline = proxy_health._spawn
            proxy_health._spawn = lambda fn, name: (spawned.append(name), inline(fn, name))
            proxy_health._sleep = _then(lambda: proxy_health.record("hu-1", True))
            _fail("hu-1")
    finally:
        proxy_health._step = real_step
    assert len(ends) == 1, ends
    assert spawned == ["proxy-watch-hu-1"] * 2, f"the streak after the watcher's end got its own: {spawned}"
    assert w.probed == ["hu-1"] * 2, f"the new watcher's confirm (fails: bad), a recheck (answers): {w.probed}"
    assert [kw["down"] for _, kw in ev.seen] == [True, True, False, False], ev.seen
    assert proxy_health.snapshot("hu-1")["state"] == "healthy" and not proxy_health._watchers


def case_back_at_the_bar_during_a_recheck_sleep_is_confirmed_by_the_same_watcher():
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
    proxy_health.log.disabled = True
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
    import threading
    real_lock, real_watchers, real_failover = proxy_health._lock, proxy_health._watchers, proxies.failover_pool
    b_moved = threading.Event()
    racer: list[threading.Thread] = []

    def _b():
        proxy_health.record("hu-1", False, "CONNECT tunnel failed, response 403")
        b_moved.set()

    class _Lock:
        def __enter__(self):
            if not real_lock.acquire(blocking=False):
                if racer and threading.current_thread() is racer[0]:
                    b_moved.set()
                real_lock.acquire()
            return self

        def __exit__(self, *_):
            real_lock.release()

    class _Claims(set):
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
            proxy_health._sleep = _then(None, None, None, lambda: proxies.remove("hu-1"))
            _fail("hu-1", proxy_health_decide.DOWN_AFTER)
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


def case_rebalance_moves_once_only_when_all_is_calm():
    import logging
    a, b, c, d = _pool(4)
    proxies.unbind_account(d, "4")
    lines: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda r: lines.append(r.getMessage())
    proxy_health.log.addHandler(handler)
    try:
        proxy_health._state[b] = {**proxy_health_decide.blank(), "down": True, "bad_reason": "down"}
        with _Watch() as w:
            assert proxy_health.rebalance(since=0) is None
        assert _on(d) == [] and w.probed == [], "something down: no rebalance"
        proxy_health._state.clear()
        with _Watch() as w:
            proxy_health._state[c] = {**proxy_health_decide.blank(), "failed_over_at": proxy_health._now()}
            assert proxy_health.rebalance(since=proxy_health._now() - 1) is None
            assert _on(d) == [] and w.probed == [], "a failover since the last pass: no rebalance"
            assert proxy_health.rebalance(since=proxy_health._now() + 1) == ("5", a, d)
        assert _on(a) == ["1"] and _on(d) == ["5"] and w.probed == [d], (w.probed, _on(a), _on(d))
        assert f"proxy rebalance: moved 5 {a} -> {d}" in lines, lines
        with _Watch():
            assert proxy_health.probe_all() == 4 and _on(a) == ["1"], "the probe pass never rebalances"
    finally:
        proxy_health.log.removeHandler(handler)


def case_rebalance_env():
    env = proxy_health.REBALANCE_INTERVAL_ENV
    for raw, want in [(None, 600.0), ("", 600.0), ("0", 0.0), ("-1", 0.0), ("60", 600.0), ("900", 900.0),
                      ("x", 600.0)]:
        os.environ.pop(env, None)
        if raw is not None:
            os.environ[env] = raw
        assert proxy_health.rebalance_interval_s() == want, (raw, proxy_health.rebalance_interval_s())
    os.environ.pop(env, None)
    for raw, want in [(None, (0,)), ("", (0,)), ("0,2", (0, 2)), ("x", (0,))]:
        os.environ.pop(proxy_health.REBALANCE_TIERS_ENV, None)
        if raw is not None:
            os.environ[proxy_health.REBALANCE_TIERS_ENV] = raw
        assert proxy_health.rebalance_tiers() == want, (raw, proxy_health.rebalance_tiers())
    os.environ.pop(proxy_health.REBALANCE_TIERS_ENV, None)


def case_rebalance_loop_off_at_zero():
    import asyncio
    os.environ[proxy_health.REBALANCE_INTERVAL_ENV] = "0"
    try:
        asyncio.run(asyncio.wait_for(proxy_health.rebalance_loop(), 1))
    finally:
        os.environ.pop(proxy_health.REBALANCE_INTERVAL_ENV, None)


def _refused_then(n: int):
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
        OFClient._proxy_retry(c, _refused_then(2), policy=RetryPolicy(3, 0.0, False))
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
                proxy_health._sample("hu-1", i < 3)
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
        gate.wait(5)
        gate.wait(5)
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
    a, b, c = _pool()
    os.environ.pop(proxy_health.FLAP_PCT_ENV, None)
    assert proxy_health.flap_bad_pct() == proxy_health.FLAP_PCT_DEFAULT == 20.0
    with _Events() as ev, _Watch():
        _spread_refusals(a, 15, 4)
        assert not proxy_health.snapshot(a)["down"] and ev.seen == []
        spawned = []
        proxy_health._spawn = lambda fn, name: spawned.append(fn)
        proxy_health._sample(a, True)
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
    a, b, c = _pool()
    os.environ[proxy_health.FLAP_PCT_ENV] = "30"
    os.environ[proxy_health.RECHECK_ENV] = "5"
    try:
        with _Events() as ev, _Watch() as w:
            _spread_refusals(a, 13, 6)
            assert not proxy_health.snapshot(a)["down"] and ev.seen == []
            spawned = []
            proxy_health._spawn = lambda fn, name: spawned.append(fn)
            proxy_health._sample(a, True)
            snap = proxy_health.snapshot(a)
            assert snap["state"] == "bad" and snap["bad_reason"] == "flapping" and len(spawned) == 1, snap
            assert [(e[1]["account_id"], e[1]["down"]) for e in ev.seen] == [("1", True), ("4", True)], ev.seen

            def oks(n):
                return lambda: [proxy_health._sample(a, False) for _ in range(n)]
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
    _registry()
    os.environ[proxy_health.FLAP_PCT_ENV] = "30"
    try:
        with _Events() as ev, _Watch():
            for _ in range(25):
                proxy_health._sample("hu-1", True)
                _advance(0.4)
            assert not proxy_health.snapshot("hu-1")["down"] and ev.seen == [], "a blip: no FlapBad"
            proxy_health._state["hu-1"] = {**proxy_health_decide.blank(), "errors": proxy_health_decide.DOWN_AFTER}
            proxy_health._watchers.add("hu-1")
            _spread_refusals("hu-1", 0, 9)
            assert not proxy_health.snapshot("hu-1")["down"] and ev.seen == [], "the streak's confirm owns it"
    finally:
        os.environ.pop(proxy_health.FLAP_PCT_ENV, None)


def case_flap_failover_never_moves_onto_a_flapping_proxy():
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
    _registry()
    os.environ[proxy_health.FLAP_PCT_ENV] = "30"
    clock, real = [time.time()], proxy_health._now
    proxy_health._now = lambda: clock[0]
    try:
        for refused, flapping in ((2, False), (3, True), (5, True)):
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
    with _Watch(True) as w:
        p, kept = proxy_health.assign_pool("7", random.Random(1))
    assert w.probed == [p["label"]] and w.traced == [], f"attach: one probe_of, no trace: {w.traced}"
    assert proxy_health.last_geo(p) is None


if __name__ == "__main__":
    _harness.run()
