#!/usr/bin/env python3
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
    with _Watch():
        p, kept = proxy_health.assign_pool("7", random.Random(1))
    assert p["label"] == a and not kept


def case_failover_prefers_the_same_country():
    a, b, c = _pool()
    proxy_health.note_trace(a, {"ok": True, "geo": "HU"})
    proxy_health.note_trace(c, {"ok": True, "geo": "HU"})
    proxy_health.note_trace(b, {"ok": True, "geo": "DE"})
    with _Watch(False, False, False, True, True, True, geo={b: "DE"}):
        _fail(a)
    assert _on(c) == ["1", "3", "4", "6"] and _on(b) == ["2", "5"], "both went to the HU standby"


def case_failover_prefers_the_first_tier_then_falls_back():
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
    with _Watch(False, False, False, dead={b}) as w:
        _fail(a)
    assert _on(c) == ["1", "3", "4", "6"] and _on(b) == ["2", "5"], "both went to c; nobody onto b"
    assert w.probed.count(b) == 1, f"b probed once for the whole move: {w.probed}"
    assert b not in w.traced and proxy_health._state[b]["errors"] >= 1, (w.traced, proxy_health._state.get(b))
    snap = proxy_health.snapshot(b)
    assert snap["state"] == "suspect" and snap["errors"] == 1, f"b's failed probe counts: {snap}"


def case_failover_retried_after_no_destination_answered():
    a, b, c = _pool()
    os.environ[proxy_health.FLAP_PCT_ENV] = "0"
    try:
        with _Watch(False, False, False, False, False, False, True, True, True) as w:
            _fail(a)
    finally:
        os.environ.pop(proxy_health.FLAP_PCT_ENV, None)
    assert _on(a) == [] and sorted(_on(b) + _on(c)) == ["1", "2", "3", "4", "5", "6"], (_on(a), w.probed)
    snap = proxy_health.snapshot(a)
    assert snap["failed_over"] == 2 and snap["state"] == "healthy", snap


def case_failover_skips_a_still_flapping_destination_until_its_window_drains():
    a, b, c = _pool()
    os.environ.pop(proxy_health.FLAP_PCT_ENV, None)
    _bad(a, due=True)
    with _Watch(False, False) as w:
        assert proxy_health._failover(a) == [] and sorted(w.probed) == sorted([b, c]), w.probed
        assert not proxy_health.herd_guarded(b) and not proxy_health.herd_guarded(c), "one refusal: no rate"
        for other in (b, c):
            _spread_refusals(other, 17, 3)
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
    for label in (b, c):
        proxy_health._state[label] = {**proxy_health_decide.blank(), "down": True, "bad_reason": "down"}
    with _Events() as ev, _Watch(False, False, False, True):
        _fail(a)
    assert _on(a) == ["1", "4"], "nobody moved: no healthy pool proxy existed"
    snap = proxy_health.snapshot(a)
    assert snap["failed_over"] == 0 and snap["failed_over_at"] and snap["state"] == "healthy", snap
    assert [e[1]["down"] for e in ev.seen] == [True, True, False, False], "surfaced down, then back up"


def case_assign_pool_skips_bad_and_moves_a_held_one_only_when_failover_is_due():
    a, b, c = _pool()
    proxy_health.verify_pick = lambda p, **_: True
    _bad(a)
    for seed in range(20):
        proxies.unbind_pool("7")
        assert proxy_health.assign_pool("7", random.Random(seed))[0]["label"] != a, "a bad pool proxy is never picked"
    p, kept = proxy_health.assign_pool("1", random.Random(0))
    assert kept and p["label"] == a and "1" in _on(a), "bad but not due: kept (a re-attach is no faster mover)"
    _bad(a, due=True)
    p, kept = proxy_health.assign_pool("1", random.Random(0))
    assert not kept and p["label"] in (b, c) and "1" not in _on(a), "due: re-picked off the bad one"
    _bad(b, due=True)
    _bad(c, due=True)
    p, kept = proxy_health.assign_pool("4", random.Random(0))
    assert kept and p["label"] == a, "all bad: a held pick is kept"


def case_assign_pool_prefers_the_first_tier_and_skips_a_flapping_proxy():
    a, b, c = _pool(tier_break=2)
    for aid in ("3", "6"):
        proxies.unbind_account(c, aid)
    os.environ.pop(proxy_health.FLAP_PCT_ENV, None)
    with _Watch() as w:
        for seed in range(8):
            proxies.unbind_pool("7")
            p, kept = proxy_health.assign_pool("7", random.Random(seed))
            assert not kept and p["label"] in (a, b), f"tier 0 first, though c is idle: {p['label']}"
        assert c not in w.probed, w.probed
        _spread_refusals(a, 16, 4, buckets=1)
        assert proxy_health.still_flapping(a) and a not in proxy_health.unusable_labels(proxy_health.bad_reasons()), "a blip: still usable"
        _advance(proxy_health.window_s())
        _spread_refusals(a, 17, 3)
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
        with _Watch(False) as w:
            label = proxy_health.assign_pool("7", random.Random(seed))[0]["label"]
        assert label != w.probed[0] and label == w.probed[-1], f"passed over {w.probed[0]}: {w.probed} -> {label}"
        assert proxy_health.snapshot(w.probed[0])["errors"] >= 1, "the failed probe counts toward its state"
        proxy_health._state.clear()
    assert label in (a, b, c)


def case_assign_pool_unbound_and_no_pick_answers_binds_the_least_used_not_bad():
    a, b, c = _pool()
    proxies.unbind_pool("6")
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
    a, b, c = _pool()
    proxies.unbind_pool("6")
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
    a, b, c = _pool()
    _bad(a, due=True)
    raced: list[str] = []

    def _verify(p, **_):
        other = b if p["label"] == c else c
        if not raced:
            proxies.failover_pool(a, bad={a}, geo=lambda q: None,
                                  verify=lambda q: q["label"] == other, deactivated=frozenset())
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
