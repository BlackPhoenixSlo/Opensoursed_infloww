#!/usr/bin/env python3
"""Proxy health (roadmap 2.14, service/proxy_health.py + proxies.probe).

Pins: the probe is ONE GET of Cloudflare's cdn-cgi/trace through the proxy
(never OnlyFans, never without the proxy) and reads ip / country / colo and
the time to first byte; a failed or garbled probe is not ok. DOWN_AFTER
errors in a row start a confirm probe: when it answers the proxy is a blip
(count restarts, nothing announced); when it fails the proxy is bad (`down`),
announced as `proxy_switched` {down} to each Creator on it, and rechecked
with backoff. One answer brings it back up (announced too); a healthy proxy
staying healthy writes nothing. A ProxyError out of OFClient._http_call
counts as an error and an answer as a success. The Test route keeps the
probe in `health`, /admin/proxies carries `health` and the pool's `bad`
count, /admin/accounts carries `proxy_down`. The confirm waits CONFIRM_GAP_S
after the streak's first error and is skipped when an answer reset the count
meanwhile (a blip); a proxy gone from the registry ends its watcher. A
proxy back up mid-recheck and at DOWN_AFTER again is confirmed by the same
watcher; a streak right after a watcher's end starts the next. Only a
full-policy failure counts (test_proxy_retry_interactive). The periodic probe is off
unless PROXY_HEALTH_INTERVAL_S is set, and probes only proxies a Creator is on.

Failover (docs/adr/0030): after FAILOVER_AFTER_RECHECKS failed rechecks the
Creators on a bad Inflowwww pool proxy move to pool proxies that answer, in
one write (same country first, then least-used); none when no standby
answers, and then retried at every later failed recheck; a custom proxy's
never; a recovered proxy's Creators are not moved back. assign_pool skips bad
pool proxies, keeps a Creator on its bad proxy until its failover is due
(the same predicate), never moves a Creator onto a proxy that failed its
probe, binds a Creator on no pool proxy even when none answers (least-used
not bad: a finished login is never thrown away), probes at most
ATTACH_PROBES picks, and loses no race with a concurrent failover.

No network: the curl session, the probe and the OF client's http are fakes;
the watcher runs inline (`_spawn`) and never sleeps (`_sleep`).

Run:  ./venv/bin/python service/tests/test_proxy_health.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import os  # noqa: E402
import random  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
from pathlib import Path  # noqa: E402

from curl_cffi import CurlInfo, requests as curl_requests  # noqa: E402

import events  # noqa: E402
import proxies  # noqa: E402
import proxy_health  # noqa: E402
import proxy_health_decide  # noqa: E402
from of_client import OFClient, RetryPolicy  # noqa: E402

_TRACE = "fl=1\nh=1.1.1.1\nip=203.0.113.7\nts=1\nvisit_scheme=https\nloc=HU\ncolo=BUD\nhttp=http/2\n"


def _registry() -> None:
    proxies.REGISTRY_PATH = Path(tempfile.mkdtemp(prefix="proxyhealth_")) / "proxies.json"
    proxies.upsert({"label": "hu-1", "scheme": "http", "host": "198.51.100.1", "port": 8080,
                    "username": "u", "password": "p"})
    proxies.upsert({"label": "spare", "scheme": "http", "host": "198.51.100.2", "port": 8080})
    proxies.assign_account("hu-1", "101")
    proxies.assign_account("hu-1", "102")
    proxy_health._state.clear()
    proxy_health._watchers.clear()
    proxy_health.verify_pick = lambda p, **_: True   # a new binding's probe: answers unless a case scripts it


# The watcher's clock inside `_Watch`: a fake `_sleep` advances it, so the
# confirm's deadline loop sees its wait pass.
_CLOCK = [0.0]


def _advance(s: float) -> None:
    _CLOCK[0] += max(s, 0)


def _then(*steps):
    """A `_sleep` that runs steps[i] at its i-th wait (None: just returns).
    Wait 0 is the confirm's (CONFIRM_GAP_S after the first error), then the rechecks'."""
    it = iter(steps)

    def sleep(_s):
        _advance(_s)
        step = next(it, None)
        if step:
            step()
    return sleep


_REAL_VERIFY = proxy_health.verify_pick


# The watcher inline and without waits; the probe answers from a script
# (True = answers; True once it runs out) and is logged per label; a label in
# `dead` never answers and takes nothing from the script. `_Watch(False, False, True)`.
class _Watch:
    def __init__(self, *answers: bool, geo: dict[str, str] | None = None, dead: set[str] = frozenset()):
        self.answers, self.probed, self.slept, self.geo = list(answers), [], [], geo or {}
        self.dead = set(dead)

    def __enter__(self):
        self._real = (proxy_health._spawn, proxy_health._sleep, proxies.probe, proxy_health._now)
        proxy_health._spawn = lambda fn, name: fn()
        _CLOCK[0] = time.time()
        proxy_health._now = lambda: _CLOCK[0]

        def _sleep(s):
            self.slept.append(s)
            _advance(s)
        proxy_health._sleep = _sleep

        def _probe(p, timeout_s=15):
            self.probed.append(p["label"])
            ok = False if p["label"] in self.dead else (self.answers.pop(0) if self.answers else True)
            return ({"ok": True, "ip": "203.0.113.7", "geo": self.geo.get(p["label"], "HU"), "colo": "BUD",
                     "ttfb_ms": 80, "error": None}
                    if ok else {"ok": False, "ip": None, "geo": None, "colo": None, "ttfb_ms": None,
                                "error": "proxy_probe_failed: CONNECT tunnel failed, response 403"})
        proxies.probe = _probe
        return self

    def __exit__(self, *_):
        proxy_health._spawn, proxy_health._sleep, proxies.probe, proxy_health._now = self._real


def _fail(label: str, n: int = proxy_health_decide.DOWN_AFTER) -> None:
    for _ in range(n):
        proxy_health.record(label, False, "CONNECT tunnel failed, response 403")


class _Events:
    def __enter__(self):
        self.seen, self._real = [], events.publish_state
        events.publish_state = lambda t, **kw: self.seen.append((t, kw))
        return self

    def __exit__(self, *_):
        events.publish_state = self._real


class _FakeSession:
    calls: list = []
    reply = None

    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, url, **kw):
        _FakeSession.calls.append((url, kw, self.kw))
        if isinstance(_FakeSession.reply, Exception):
            raise _FakeSession.reply
        return _FakeSession.reply


def _probe_with(reply):
    real = curl_requests.Session
    _FakeSession.calls, _FakeSession.reply = [], reply
    curl_requests.Session = _FakeSession
    try:
        return proxies.probe(proxies.get_by_label("hu-1"))
    finally:
        curl_requests.Session = real


def _resp(text=_TRACE, status=200, ttfb=0.1234):
    return types.SimpleNamespace(status_code=status, text=text,
                                 infos={CurlInfo.STARTTRANSFER_TIME: ttfb})


def case_parse_trace():
    t = proxies.parse_trace(_TRACE)
    assert (t["ip"], t["loc"], t["colo"]) == ("203.0.113.7", "HU", "BUD"), t


def case_probe_reads_the_trace_through_the_proxy():
    _registry()
    out = _probe_with(_resp())
    assert out == {"ok": True, "ip": "203.0.113.7", "geo": "HU", "colo": "BUD",
                   "ttfb_ms": 123, "error": None}, out
    (url, kw, session_kw), = _FakeSession.calls
    assert url == "https://1.1.1.1/cdn-cgi/trace", "Cloudflare's trace, never OnlyFans"
    assert kw["proxies"] == {"http": "http://u:p@198.51.100.1:8080",
                             "https": "http://u:p@198.51.100.1:8080"}, kw
    assert CurlInfo.STARTTRANSFER_TIME in session_kw["curl_infos"]


def case_probe_failures_are_not_ok():
    _registry()
    out = _probe_with(curl_requests.exceptions.ProxyError("CONNECT tunnel failed, response 407"))
    assert out["ok"] is False and "407" in out["error"], out
    out = _probe_with(_resp(status=502))
    assert out["ok"] is False and "502" in out["error"], out
    out = _probe_with(_resp(text="<html>captive portal</html>"))
    assert out["ok"] is False and out["ip"] is None, out


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
        assert snap["probe"]["geo"] == "HU", "the confirm's trace is kept"


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


def _pool(n: int = 3) -> list[str]:
    """Three Inflowwww pool proxies; Creators 1..6 spread two per proxy."""
    proxies.REGISTRY_PATH = Path(tempfile.mkdtemp(prefix="proxyfail_")) / "proxies.json"
    proxies.sync_pool(",".join(f"socks5://pool-{i}.invalid:{9000 + i}" for i in range(n)))
    labels = [p["label"] for p in proxies.pool_entries()]
    for i, aid in enumerate(("1", "2", "3", "4", "5", "6")):
        proxies.assign_account(labels[i % n], aid)
    proxy_health._state.clear()
    proxy_health._watchers.clear()
    proxy_health.verify_pick = _REAL_VERIFY   # probes go through _Watch's scripted proxies.probe
    return labels


def _on(label: str) -> list[str]:
    return sorted(proxies._ids_on(proxies.get_by_label(label)))


def case_failover_moves_pool_creators_after_two_failed_rechecks():
    a, b, c = _pool()
    switched: list[list[str]] = []
    proxies._switch_listeners.append(switched.append)
    try:
        with _Events() as ev, _Watch(False, False, False, True, True, True) as w:
            _fail(a)
    finally:
        proxies._switch_listeners.remove(switched.append)
    assert w.probed.count(a) == 4 and sorted(w.probed[3:5]) == sorted([b, c]), \
        f"confirm, two rechecks, each destination probed once, the recheck that passes: {w.probed}"
    assert _on(a) == [], "its Creators left it"
    assert sorted(_on(b) + _on(c)) == ["1", "2", "3", "4", "5", "6"]
    assert len(_on(b)) == 3 and len(_on(c)) == 3, "least-used: one each, not both onto one"
    assert switched == [["1", "4"]], f"one registry write moved both at once: {switched}"
    snap = proxy_health.snapshot(a)
    assert snap["failed_over"] == 2 and snap["state"] == "healthy", snap
    assert _on(a) == [], "back up: nobody is moved back (the recovered proxy is the standby)"
    moved_events = [e[1] for e in ev.seen if "down" not in e[1]]
    assert sorted(x["account_id"] for x in moved_events) == ["1", "4"], ev.seen
    # The standby is the next pick: least-used, with nobody on it.
    with _Watch():
        p, kept = proxy_health.assign_pool("7", random.Random(1))
    assert p["label"] == a and not kept


def case_failover_prefers_the_same_country():
    a, b, c = _pool()
    proxy_health._keep_probe(a, {"ok": True, "geo": "HU"})
    proxy_health._keep_probe(c, {"ok": True, "geo": "HU"})
    proxy_health._keep_probe(b, {"ok": True, "geo": "DE"})
    with _Watch(False, False, False, True, True, True, geo={b: "DE"}):   # the destination probes keep b in DE
        _fail(a)
    assert _on(c) == ["1", "3", "4", "6"] and _on(b) == ["2", "5"], "both went to the HU standby"


def case_failover_skips_a_destination_that_does_not_answer():
    a, b, c = _pool()
    # confirm a, two rechecks a (fail); b never answers, c does; the next recheck of a passes
    with _Watch(False, False, False, dead={b}) as w:
        _fail(a)
    assert _on(c) == ["1", "3", "4", "6"] and _on(b) == ["2", "5"], "both went to c; nobody onto b"
    assert w.probed.count(b) == 1, f"b probed once for the whole move: {w.probed}"
    snap = proxy_health.snapshot(b)
    assert snap["state"] == "suspect" and snap["errors"] == 1, f"b's failed probe counts: {snap}"


def case_failover_retried_after_no_destination_answered():
    """F2: the first failover finds no destination answering (a blip on the
    standbys too) and moves nobody; the next failed recheck tries again."""
    a, b, c = _pool()
    # a: confirm, recheck 1, recheck 2 fail; failover 1: b, c fail; recheck 3 fails;
    # failover 2: b, c answer; recheck 4 passes.
    with _Watch(False, False, False, False, False, False, True, True, True) as w:
        _fail(a)
    assert _on(a) == [] and sorted(_on(b) + _on(c)) == ["1", "2", "3", "4", "5", "6"], (_on(a), w.probed)
    snap = proxy_health.snapshot(a)
    assert snap["failed_over"] == 2 and snap["state"] == "healthy", snap


def case_failover_of_an_empty_or_custom_proxy_probes_nothing():
    a, b, c = _pool()
    proxies.upsert({"label": "mine", "scheme": "http", "host": "198.51.100.9", "port": 8080})
    proxies.assign_account("mine", "9")
    for aid in _on(a):
        proxies.unbind_pool(aid)
    with _Watch() as w:
        assert proxy_health._failover(a) == [] and proxy_health._failover("mine") == []
    assert w.probed == [], f"nobody to move: no destination probed ({w.probed})"
    assert not proxy_health.snapshot(a).get("failed_over_at"), "not applicable: nothing stamped"


def case_no_standby_nobody_moves_still_surfaced():
    a, b, c = _pool()
    for label in (b, c):   # both standbys bad already
        proxy_health._state[label] = {**proxy_health_decide.blank(), "down": True}
    with _Events() as ev, _Watch(False, False, False, True):
        _fail(a)
    assert _on(a) == ["1", "4"], "nobody moved: no healthy pool proxy existed"
    snap = proxy_health.snapshot(a)
    assert snap["failed_over"] == 0 and snap["failed_over_at"] and snap["state"] == "healthy", snap
    assert [e[1]["down"] for e in ev.seen] == [True, True, False, False], "surfaced down, then back up"


def _bad(label: str, due: bool = False) -> None:
    proxy_health._state[label] = {**proxy_health_decide.blank(), "down": True,
                                  "rechecks_failed": proxy_health_decide.FAILOVER_AFTER_RECHECKS if due else 0}


def case_assign_pool_skips_bad_and_moves_a_held_one_only_when_failover_is_due():
    """F3: one mover policy. A Creator held on a bad proxy is kept until
    `failover_due` (what _failover runs on), then re-picked like a failover."""
    a, b, c = _pool()
    proxy_health.verify_pick = lambda p, **_: True   # every pick answers (probing: the case below)
    _bad(a)
    for seed in range(20):
        proxies.unbind_pool("7")
        assert proxy_health.assign_pool("7", random.Random(seed))[0]["label"] != a, "a bad pool proxy is never picked"
    p, kept = proxy_health.assign_pool("1", random.Random(0))   # 1 is held on bad a, failover not due yet
    assert kept and p["label"] == a and "1" in _on(a), "bad but not due: kept (a re-attach is no faster mover)"
    _bad(a, due=True)
    p, kept = proxy_health.assign_pool("1", random.Random(0))
    assert not kept and p["label"] in (b, c) and "1" not in _on(a), "due: re-picked off the bad one"
    _bad(b, due=True)
    _bad(c, due=True)
    p, kept = proxy_health.assign_pool("4", random.Random(0))
    assert kept and p["label"] == a, "all bad: a held pick is kept"


def case_assign_pool_never_binds_to_a_proxy_that_failed_its_probe():
    a, b, c = _pool()
    for seed in range(12):
        proxies.unbind_pool("7")
        with _Watch(False) as w:   # the first pick's probe fails, the next answers
            label = proxy_health.assign_pool("7", random.Random(seed))[0]["label"]
        assert label != w.probed[0] and label == w.probed[-1], f"passed over {w.probed[0]}: {w.probed} -> {label}"
        assert proxy_health.snapshot(w.probed[0])["errors"] >= 1, "the failed probe counts toward its state"
        proxy_health._state.clear()
    assert label in (a, b, c)


def case_assign_pool_unbound_and_no_pick_answers_binds_the_least_used_not_bad():
    """N6: a pool-wide probe blip never throws a finished login away. At most
    ATTACH_PROBES picks are probed; then the least-used not bad, an untried
    one first."""
    a, b, c = _pool()
    proxies.unbind_pool("6")   # c carries one Creator, a and b two
    for seed in range(8):
        proxies.unbind_pool("7")
        proxy_health._state.clear()
        with _Watch(dead={a, b, c}) as w:
            p, kept = proxy_health.assign_pool("7", random.Random(seed))
        assert not kept and proxies.get_for_account("7")["label"] == p["label"], "bound and stored"
        assert len(w.probed) == proxies.ATTACH_PROBES, f"probes bounded: {w.probed}"
        untried = {a, b, c} - set(w.probed)
        assert p["label"] in untried, f"an untried pick before one that just failed: {w.probed} -> {p['label']}"
    proxy_health._state.clear()
    _bad(c)
    proxies.unbind_pool("7")
    with _Watch(dead={a, b}) as w:
        p, kept = proxy_health.assign_pool("7", random.Random(0))
    assert p["label"] in (a, b) and sorted(w.probed) == sorted([a, b]), "never the bad one"


def case_assign_pool_unbound_and_every_proxy_bad_binds_the_least_used():
    """R5: a login is never lost. A Creator on no pool proxy while every pool
    proxy is bad is bound to the least-used of them (no probe; surfaced as
    proxy_down); LookupError is for an empty pool only."""
    a, b, c = _pool()
    proxies.unbind_pool("6")   # c carries one Creator, a and b two
    for label in (a, b, c):
        _bad(label)
    for seed in range(8):
        proxies.unbind_pool("7")
        with _Watch() as w:
            p, kept = proxy_health.assign_pool("7", random.Random(seed))
        assert not kept and p["label"] == c, f"the least-used: {p['label']}"
        assert proxies.get_for_account("7")["label"] == c, "bound and stored"
        assert w.probed == [], f"no probe when every proxy is bad: {w.probed}"


def case_assign_pool_bound_on_a_due_proxy_and_no_pick_answers_stays():
    a, b, c = _pool()
    _bad(a, due=True)
    with _Watch(dead={b, c}) as w:
        p, kept = proxy_health.assign_pool("1", random.Random(0))
    assert kept and p["label"] == a and "1" in _on(a), "due but no destination answers: stays (no IP change)"
    assert len(w.probed) <= proxies.ATTACH_PROBES, w.probed


def case_assign_pool_loses_a_race_with_a_concurrent_failover():
    """N7: a failover moves Creator 1 off due a while assign_pool probes its
    own pick; assign_pool keeps the failover's binding (one IP change)."""
    a, b, c = _pool()
    _bad(a, due=True)
    raced: list[str] = []

    def _verify(p, **_):
        other = b if p["label"] == c else c
        if not raced:
            proxies.failover_pool(a, bad={a}, geo=lambda q: None,
                                  verify=lambda q: q["label"] == other)
            raced.append(other)
        return True
    proxy_health.verify_pick = _verify
    switched: list[list[str]] = []
    proxies._switch_listeners.append(switched.append)
    try:
        p, kept = proxy_health.assign_pool("1", random.Random(0))
    finally:
        proxies._switch_listeners.remove(switched.append)
    assert kept and p["label"] == raced[0], f"the failover's binding is kept: {p['label']} vs {raced}"
    assert "1" in _on(raced[0]) and "1" not in _on(a) and sum("1" in _on(x) for x in (a, b, c)) == 1
    assert sum("1" in ids for ids in switched) == 1, f"one move for Creator 1, not two: {switched}"
    # Unbound: a concurrent assign bound 7 meanwhile; this one keeps it.
    proxies.unbind_pool("7")

    def _verify_bind(p, **_):
        if proxies.get_for_account("7") is None:
            proxies.assign_account(b, "7")
        return True
    proxy_health.verify_pick = _verify_bind
    p, kept = proxy_health.assign_pool("7", random.Random(0))
    assert kept and p["label"] == b and proxies.get_for_account("7")["label"] == b


def _through_during_the_confirm(then=lambda: None):
    """A `proxies.probe` wrapper (inside `_Watch`): on the confirm probe, an OF call through the proxy
    answers first, then `then()` runs, then the probe answers as scripted."""
    inner = proxies.probe

    def _probe(p, timeout_s=15):
        proxy_health.record(p["label"], True)
        then()
        proxies.probe = inner   # once
        return inner(p, timeout_s)
    proxies.probe = _probe


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
    server._get_request_user = lambda: types.SimpleNamespace(id="o", account_ids={"1", "2", "3", "4", "5", "6"})
    server.account_registry.list_accounts = lambda **_: [{"id": str(i)} for i in range(1, 7)]
    try:
        proxy_health._state[a] = {**proxy_health_decide.blank(), "down": True}
        out = proxies_admin_api.admin_proxies_list()
    finally:
        server._get_request_user, server.account_registry.list_accounts = real_user, real_list
    assert out["pool"] == {"size": 3, "account_ids": out["pool"]["account_ids"], "bad": 1}, out["pool"]
    assert out["proxies"] == [], "pool entries stay unlisted"


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
        ok = _bare_client(lambda url, **kw: types.SimpleNamespace(headers={}, ok=True))
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
            proxies.probe = _boom
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


def case_routes_carry_health():
    _registry()
    import server   # route functions called directly: no request user, the unauthed path
    import proxies_admin_api
    real = proxies.probe
    proxies.probe = lambda p, timeout_s=15: {"ok": True, "ip": "203.0.113.7", "geo": "HU",
                                             "colo": "BUD", "ttfb_ms": 80, "error": None}
    try:
        out = proxies_admin_api.admin_proxies_test("hu-1")
    finally:
        proxies.probe = real
    assert out["colo"] == "BUD", out
    assert proxies.get_by_label("hu-1")["verified_geo"] == "HU", "the Test button still records"
    rows = {p["label"]: p for p in proxies_admin_api.admin_proxies_list()["proxies"]}
    assert rows["hu-1"]["health"]["probe"]["ttfb_ms"] == 80, rows["hu-1"]["health"]
    assert rows["spare"]["health"] == {"down": False, "errors": 0, "state": "healthy"}, rows["spare"]
    assert rows["hu-1"]["health"]["state"] == "healthy"


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
        proxy_health._state["hu-1"] = {**proxy_health_decide.blank(), "down": True}
        out = asyncio.run(accounts_admin_api.admin_accounts_list(Response()))
    finally:
        server._get_request_user, server.account_registry.list_accounts = real_user, real_list
    flags = {a["id"]: a["proxy_down"] for a in out["accounts"]}
    assert flags == {"101": True, "201": False}, flags


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
    real = proxies.probe
    proxies.probe = lambda p, timeout_s=15: probed.append(p["label"]) or {"ok": True}
    try:
        assert proxy_health.probe_all() == 1
    finally:
        proxies.probe = real
    assert probed == ["hu-1"], "the unbound proxy is not probed"


if __name__ == "__main__":
    _harness.run()
