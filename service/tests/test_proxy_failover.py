#!/usr/bin/env python3
"""Pool proxy failover and the pool binding (docs/adr/0030; service/proxy_health.py + proxies.py).

Pins: after FAILOVER_AFTER_RECHECKS failed rechecks the Creators on a bad Inflowwww pool proxy move to
pool proxies that answer, in one write (first tier, same country, then least-used); none when no standby
answers, and then retried at every later failed recheck; never onto a herd-guarded one; a custom proxy's
never; a recovered proxy's Creators are not moved back. assign_pool skips bad pool proxies, keeps a
Creator on its bad proxy until its failover is due (the same predicate), never moves a Creator onto a
proxy that failed its probe, binds a Creator on no pool proxy even when none answers (least-used not bad:
a finished login is never thrown away), probes at most ATTACH_PROBES picks, and loses no race with a
concurrent failover.

No network: the probes are fakes; the watcher runs inline (`_spawn`) and never sleeps (`_sleep`).

Run:  ./venv/bin/python service/tests/test_proxy_failover.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import os  # noqa: E402
import random  # noqa: E402


import proxies  # noqa: E402
import proxy_health  # noqa: E402
import proxy_health_decide  # noqa: E402
from _proxy_health_fixtures import (  # noqa: E402
    _Events, _Watch, _advance, _bad, _fail, _on, _pool, _spread_refusals)


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
    proxy_health.note_trace(a, {"ok": True, "geo": "HU"})
    proxy_health.note_trace(c, {"ok": True, "geo": "HU"})
    proxy_health.note_trace(b, {"ok": True, "geo": "DE"})
    with _Watch(False, False, False, True, True, True, geo={b: "DE"}):   # the destination probes keep b in DE
        _fail(a)
    assert _on(c) == ["1", "3", "4", "6"] and _on(b) == ["2", "5"], "both went to the HU standby"


def case_failover_prefers_the_first_tier_then_falls_back():
    """INFLOWW_PROXIES `a,b,|,c`: a's Creators go to b (tier 0, busier) over an idle c (tier 1) while b
    answers; with b dead too, to c. No break: one tier, least-used (case above)."""
    a, b, c = _pool(tier_break=2)
    assert [proxies.get_by_label(x)["tier"] for x in (a, b, c)] == [0, 0, 1]
    for aid in ("3", "6"):
        proxies.unbind_account(c, aid)
    with _Watch(False, False, False, True, True, True) as w:
        _fail(a)
    assert _on(b) == ["1", "2", "4", "5"] and _on(c) == [], f"tier 0 first, though c is idle: {_on(b)} {_on(c)}"
    assert c not in w.probed, f"tier 1 not probed while tier 0 answers: {w.probed}"
    a, b, c = _pool(tier_break=2)
    with _Watch(False, False, False, dead={b}) as w:
        _fail(a)
    assert _on(c) == ["1", "3", "4", "6"] and _on(b) == ["2", "5"], "tier 0 dead: tier 1"
    assert w.probed.count(b) == 1, f"b probed once for the whole move: {w.probed}"


def case_failover_skips_a_destination_that_does_not_answer():
    a, b, c = _pool()
    # confirm a, two rechecks a (fail); b never answers, c does; the next recheck of a passes
    with _Watch(False, False, False, dead={b}) as w:
        _fail(a)
    assert _on(c) == ["1", "3", "4", "6"] and _on(b) == ["2", "5"], "both went to c; nobody onto b"
    assert w.probed.count(b) == 1, f"b probed once for the whole move: {w.probed}"
    # The reviewer's repro: b answers the trace (_Watch's always does) yet refuses OF. Its destination check is
    # probe_of, so it is passed over and counted, and no second move off it follows.
    assert b not in w.traced and proxy_health._state[b]["errors"] >= 1, (w.traced, proxy_health._state.get(b))
    snap = proxy_health.snapshot(b)
    assert snap["state"] == "suspect" and snap["errors"] == 1, f"b's failed probe counts: {snap}"


def case_failover_retried_after_no_destination_answered():
    """F2 (knob off, PROXY_FLAP_BAD_PCT=0): the first failover finds no destination answering (a blip on
    the standbys too) and moves nobody; the next failed recheck tries again."""
    a, b, c = _pool()
    os.environ[proxy_health.FLAP_PCT_ENV] = "0"
    try:
        # a: confirm, recheck 1, recheck 2 fail; failover 1: b, c fail; recheck 3 fails;
        # failover 2: b, c answer; recheck 4 passes.
        with _Watch(False, False, False, False, False, False, True, True, True) as w:
            _fail(a)
    finally:
        os.environ.pop(proxy_health.FLAP_PCT_ENV, None)
    assert _on(a) == [] and sorted(_on(b) + _on(c)) == ["1", "2", "3", "4", "5", "6"], (_on(a), w.probed)
    snap = proxy_health.snapshot(a)
    assert snap["failed_over"] == 2 and snap["state"] == "healthy", snap


def case_failover_skips_a_still_flapping_destination_until_its_window_drains():
    """F2 with the knob at its default (20): one refused probe is no rate (under FLAP_MIN_CALLS attempts), so a
    standby that refused it is judged by its next probe alone; a herd-guarded standby (>= 20 attempts, >= X/2
    refused, in >= FLAP_BUCKETS tenths) is skipped even when its probe answers (no IP change onto it), until its
    window drains."""
    a, b, c = _pool()
    os.environ.pop(proxy_health.FLAP_PCT_ENV, None)
    _bad(a, due=True)
    with _Watch(False, False) as w:                     # the fake watcher owns the clock (_advance)
        assert proxy_health._failover(a) == [] and sorted(w.probed) == sorted([b, c]), w.probed
        assert not proxy_health.herd_guarded(b) and not proxy_health.herd_guarded(c), "one refusal: no rate"
        for other in (b, c):
            _spread_refusals(other, 17, 3)   # 15 % over 3 tenths: not FlapBad, but over half the knob
        assert proxy_health.herd_guarded(b) and proxy_health.herd_guarded(c), "flapping: over half"
        assert proxy_health._failover(a) == [], "answering now, but herd-guarded: skipped"
        assert _on(a) == ["1", "4"] and len(w.probed) == 2, w.probed
        _advance(proxy_health.window_s() / 5 + 1)
        assert proxy_health.herd_guarded(b), "no recency rule: a quiet spell alone does not clear it"
        assert proxy_health._failover(a) == [] and len(w.probed) == 2, w.probed
        _advance(proxy_health.window_s())
        assert not proxy_health.herd_guarded(b) and not proxy_health.herd_guarded(c), "window drained"
        moved = proxy_health._failover(a)
    assert sorted(moved) == ["1", "4"] and _on(a) == [], (moved, _on(a))


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
        proxy_health._state[label] = {**proxy_health_decide.blank(), "down": True, "bad_reason": "down"}
    with _Events() as ev, _Watch(False, False, False, True):
        _fail(a)
    assert _on(a) == ["1", "4"], "nobody moved: no healthy pool proxy existed"
    snap = proxy_health.snapshot(a)
    assert snap["failed_over"] == 0 and snap["failed_over_at"] and snap["state"] == "healthy", snap
    assert [e[1]["down"] for e in ev.seen] == [True, True, False, False], "surfaced down, then back up"


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


def case_assign_pool_prefers_the_first_tier_and_skips_a_flapping_proxy():
    """F3: a new login takes the failover's one destination check: tier 0 first (a busier tier-0 proxy over an
    idle tier-1 one), never a herd-guarded proxy (not bad) while another answers, but one blip (<= 2 tenths) is
    no guard; every pool proxy unusable: still bound, unprobed (a login is never lost), never the dead one."""
    a, b, c = _pool(tier_break=2)   # a, b: tier 0, two Creators each; c: tier 1, emptied below
    for aid in ("3", "6"):
        proxies.unbind_account(c, aid)
    os.environ.pop(proxy_health.FLAP_PCT_ENV, None)
    with _Watch() as w:
        for seed in range(8):
            proxies.unbind_pool("7")
            p, kept = proxy_health.assign_pool("7", random.Random(seed))
            assert not kept and p["label"] in (a, b), f"tier 0 first, though c is idle: {p['label']}"
        assert c not in w.probed, w.probed
        _spread_refusals(a, 16, 4, buckets=1)   # 20 % in one tenth: a blip, over half the knob
        assert proxy_health.still_flapping(a) and a not in proxy_health.unusable_labels(proxy_health.bad_reasons()), "a blip: still usable"
        _advance(proxy_health.window_s())         # drained
        _spread_refusals(a, 17, 3)              # 15 % over 3 tenths: no FlapBad, but herd-guarded
        assert proxy_health.herd_guarded(a) and not proxy_health.snapshot(a)["down"]
        w.probed.clear()
        for seed in range(8):
            proxies.unbind_pool("7")
            p, _ = proxy_health.assign_pool("7", random.Random(seed))
            assert p["label"] == b, f"never onto the flapping one: {p['label']}"
        assert a not in w.probed, w.probed
        _spread_refusals(b, 17, 3)
        _bad(c)
        w.probed.clear()
        proxies.unbind_pool("7")
        p, kept = proxy_health.assign_pool("7", random.Random(0))
    assert not kept and proxies.get_for_account("7")["label"] == p["label"] and w.probed == [], (p, w.probed)
    assert p["label"] != c, "all unusable: a herd-guarded one before the dead one"


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


def case_assign_pool_every_proxy_bad_binds_a_flapping_one_before_a_dead_one():
    """G1 through this module's `dead` (bad_reason "down"): every pool proxy bad, the dead one emptied by
    its failover (the least-used); a new login binds a flap-bad one (it answers most calls), unprobed."""
    a, b, c = _pool()
    for aid in ("1", "4"):
        proxies.unbind_account(a, aid)
    _bad(a)
    for label in (b, c):
        _bad(label)
        proxy_health._state[label]["bad_reason"] = "flapping"
    for seed in range(8):
        proxies.unbind_pool("7")
        with _Watch() as w:
            p, kept = proxy_health.assign_pool("7", random.Random(seed))
        assert not kept and p["label"] in (b, c), f"a flapping one, not the dead least-used: {p['label']}"
        assert w.probed == [], w.probed


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


if __name__ == "__main__":
    _harness.run()
