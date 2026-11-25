import asyncio
import types

import pytest

from slop.lib import all_models_faults as amf
from slop.lib import all_models_refresher as r


def test_per_creator_min_counts_only_the_refresher_kind():
    by = {r.KIND: 20, "walk:app_open_warm": 99}
    assert r.per_creator_min(by, 10, 120) == 1.0
    assert r.per_creator_min({}, 10, 120) == 0.0
    assert r.per_creator_min(None, 10, 120) is None


@pytest.mark.parametrize("n3,n1,ok", [
    (1.0, 1.0, True),
    (1.2, 0.95, True),
    (1.2, 0.9, False),
    (3.0, 1.0, False),
    (0.0, 0.0, False),
    (0.75, 0.8, False),
    (None, 1.0, False),
])
def test_flat_in_n(n3, n1, ok):
    assert r.flat_in_n(n3, n1) is ok


def _fr(age_s: float, cycle_s=60, at=True) -> dict:
    now = 1_000_000_000
    return {"now": now, "at": now - int(age_s * 1000) if at else None, "cycle_s": cycle_s}


def _s(phase: str, **rows) -> dict:
    return {"t": 0, "phase": phase, "rows": rows}


def test_staleness_within_cycle_plus_queue_wait():
    st = r.staleness([_s("idle", a=_fr(30), b=_fr(64.5)), _s("idle_one_tab", a=_fr(70), b=_fr(2))])
    assert st["max_s"] == 70 and st["excess_s"] == 10 and st["cycle_s"] == 60
    assert st["per_creator"] == {"a": 70, "b": 64.5}
    assert st["worst"]["creator"] == "a" and st["worst"]["phase"] == "idle_one_tab"
    assert r.within_cycle(st)


def test_staleness_past_the_bound_fails():
    st = r.staleness([_s("idle", a=_fr(70.1))])
    assert st["excess_s"] == 10.1 and not r.within_cycle(st)


@pytest.mark.parametrize("rows,key", [
    ({"a": _fr(5), "b": _fr(5, at=False)}, "never"),
    ({"a": _fr(5), "b": None}, "missing"),
    ({"a": _fr(5), "b": _fr(5, cycle_s=None)}, "missing"),
])
def test_staleness_gaps_fail(rows, key):
    st = r.staleness([_s("idle", **rows)])
    assert st[key] == ["b"] and not r.within_cycle(st)


def test_no_samples_fails():
    assert not r.within_cycle(r.staleness([]))


def test_register_targets_flat_in_n_alone():
    got = amf.register(lambda apply, targets: types.SimpleNamespace(apply=apply, targets=targets))
    assert got["refresher-per-subscriber"].targets == (amf.REFRESHER_FLAT_IN_N,)
    assert got["warm-ignores-reuse"].targets == (amf.SECOND_OPEN_SHARED, amf.OPEN_AFTER_CYCLE_REUSED)
    from slop.lib.faults import FAULTS
    assert FAULTS["refresher-per-subscriber"].targets == (amf.REFRESHER_FLAT_IN_N,)


def test_fault_queues_one_entry_per_further_tab_subscriber(monkeypatch):
    ex = types.SimpleNamespace(jobs={}, task=object())

    class _Job:
        def __init__(self, feed, poll, run=None, wanted=None):
            self.feed, self.poll, self.run, self.wanted = feed, poll, run, wanted

    def refresh(aid, run, *, wanted):
        took = aid not in ex.jobs
        ex.jobs.setdefault(aid, _Job(False, None, run, wanted))
        return took

    warm = types.SimpleNamespace(_Job=_Job, _gate=lambda aid: ("exit", ex), refresh=refresh)
    sub = lambda tab, accounts: types.SimpleNamespace(tab=tab, accounts=accounts)  # noqa: E731
    events = types.SimpleNamespace(_subs={1: sub(True, frozenset({"1", "2"})), 2: sub(True, frozenset({"1"})),
                                          3: sub(True, frozenset({"1"})), 4: sub(False, frozenset({"1"})),
                                          5: sub(True, None)})
    walks, reads = [], []

    async def walk(aid, kind, run):
        walks.append((aid, kind))
        return await run()

    async def shared_refresher_reads(aid):
        reads.append(aid)
        return True

    server = types.SimpleNamespace(shared_refresher_reads=shared_refresher_reads)
    for name, mod in (("app_open_warm", warm), ("events", events), ("of_pacing", types.SimpleNamespace(walk=walk)),
                      ("shared_refresher", types.SimpleNamespace(_server=lambda: server))):
        monkeypatch.setitem(__import__("sys").modules, name, mod)
    amf._refresher_per_subscriber()

    async def real_run(aid):
        raise AssertionError("the real job is the gate's, not run here")

    async def real_wanted(aid):
        return False

    assert warm.refresh("1", real_run, wanted=real_wanted) is True
    assert warm.refresh("2", real_run, wanted=real_wanted) is True
    assert list(ex.jobs) == ["1", "1#sub1", "1#sub2", "2"]
    assert ex.jobs["1"].run is real_run and ex.jobs["1"].wanted is real_wanted

    async def turn(key):
        job = ex.jobs[key]
        assert await job.wanted(key) is True
        await job.run(key)

    for key in ("1#sub1", "1#sub2"):
        asyncio.run(turn(key))
        del ex.jobs[key]
    assert walks == [("1", "shared_refresher")] * 2 and reads == ["1", "1"]
    assert warm.refresh("1", real_run, wanted=real_wanted) is False
    assert sorted(k for k in ex.jobs if k.startswith("1")) == ["1", "1#sub1", "1#sub2"]


def _sample(t: float, **rows) -> dict:
    return {"t": t, "rows": rows}


def test_fresh_until_maps_the_relay_clock_through_the_sample():
    s = _sample(100.0, a=_fr(50), b=_fr(5), c=_fr(59.5), d=None, e=_fr(5, at=False), f=_fr(5, cycle_s=None))
    assert r.fresh_until(s, 109.9) == ["a", "b"]
    assert r.fresh_until(s, 110.0) == ["b"]
    assert r.fresh_until(s, 100.4) == ["a", "b", "c"]
    assert r.fresh_until({"t": 0, "rows": {}}, 0) == []


def _verdict(**kw) -> dict:
    base = {"fresh": ["a", "b", "c", "d"], "warmed": {}, "answers": ["reused"], "own_total": 12, "n_creators": 4}
    return r.open_after_cycle(**{**base, **kw})


def test_open_after_cycle_every_creator_within_cycle_reused():
    v = _verdict()
    assert v["ok"] and v["failed"] == [] and v["warm_read_within_cycle"] == [] and v["warm_started_past_cycle"] == []


@pytest.mark.parametrize("kw,why", [
    ({"warmed": {"a": 5}}, "warm read"),
    ({"warmed": {"a": 5, "b": 5, "c": 5, "d": 5}, "answers": ["started"]}, "warm read"),
    ({"answers": ["started"]}, "answers"),
    ({"answers": [None]}, "answers"),
    ({"answers": []}, "answers"),
    ({"own_total": r.OPEN_TOTAL_MAX + 1}, "own total"),
    ({"own_total": None}, "own total"),
    ({"fresh": ["a"]}, "within Cycle"),
])
def test_open_after_cycle_fails(kw, why):
    v = _verdict(**kw)
    assert not v["ok"] and any(why in f for f in v["failed"]), v


def test_open_after_cycle_a_creator_past_its_cycle_may_start():
    v = _verdict(fresh=["a", "b", "c"], warmed={"d": 6}, answers=["started"])
    assert v["ok"] and v["warm_started_past_cycle"] == ["d"], v
    assert _verdict(fresh=["a", "b", "c"], warmed={"d": 6}, answers=["reused"])["ok"]


def test_warm_ignores_reuse_targets_both_reuse_checks():
    got = amf.register(lambda apply, targets: types.SimpleNamespace(apply=apply, targets=targets))
    assert got["warm-ignores-reuse"].targets == (amf.SECOND_OPEN_SHARED, amf.OPEN_AFTER_CYCLE_REUSED)


def test_warm_ignores_reuse_forgets_warms_and_the_shared_last_refresh(monkeypatch):
    warmed = {"1": 5.0}
    calls = []

    async def start(*a, **kw):
        calls.append(dict(warmed))
        return {}
    warm = types.SimpleNamespace(start=start, _warmed_at=warmed)
    sr = types.SimpleNamespace(last_refresh=lambda aid: 99.0)
    for name, mod in (("app_open_warm", warm), ("shared_refresher", sr)):
        monkeypatch.setitem(__import__("sys").modules, name, mod)
    amf._warm_ignores_reuse()
    asyncio.run(warm.start(("user", "u"), ["1"]))
    assert calls == [{}], "every warm forgotten before the decision"
    assert sr.last_refresh("1") is None, "the shared Last refresh ignored (netting on)"


def _counter(**per) -> dict:
    out = {}
    for aid, (me, lists) in per.items():
        out[(r.KIND, r.ME_KEY, aid)] = me
        out[(r.KIND, r.LIST_KEY, aid)] = lists
        out[("route:GET /admin/screens/inbox", r.LIST_KEY, aid)] = 99
    return out


def test_per_cycle_one_users_me_and_at_most_one_window_a_cycle():
    v = r.per_cycle(_counter(a=(5, 0), b=(5, 0)), _counter(a=(7, 3), b=(7, 0)), ["a", "b"], 121.5, 60)
    assert v["users_me"] == {"a": 2, "b": 2} and v["list_calls"] == {"a": 3, "b": 0}
    assert v["cap_reads"] == 3 and v["ok"]


@pytest.mark.parametrize("me,lists", [(4, 0), (2, 10)])
def test_per_cycle_over_the_cap(me, lists):
    assert not r.per_cycle(_counter(a=(0, 0)), _counter(a=(me, lists)), ["a"], 120, 60)["ok"]


def test_per_cycle_without_the_counter():
    assert r.per_cycle(None, {}, ["a"], 120, 60) is None


def _g(row, chip):
    return {"row_cleared_ms": row, "chip_dropped_ms": chip}


def test_clears_within_every_tab_row_and_chip():
    assert r.clears_within({"a": _g(30_000, 31_000), "b": _g(65_000, 2_000)}, 65_000)["ok"]
    v = r.clears_within({"a": _g(30_000, None), "b": _g(65_001, 1), "c": _g(None, None)}, 65_000)
    assert not v["ok"] and v["late_or_never"] == ["a.chip_dropped_ms", "b.row_cleared_ms", "c.chip_dropped_ms",
                                                  "c.row_cleared_ms"]
    assert not r.clears_within({}, 65_000)["ok"]


@pytest.mark.parametrize("badge,ok,diff", [(17, True, 0), (21, False, 4), (None, False, None)])
def test_fresh_badge(badge, ok, diff):
    v = r.fresh_badge(badge, {"a": 8, "b": 9})
    assert v["ok"] is ok and v["diff"] == diff and v["truth"] == 17


def test_unread_total_frozen_targets_the_two_unread_checks():
    got = amf.register(lambda apply, targets: types.SimpleNamespace(apply=apply, targets=targets))
    assert got["unread-total-frozen"].targets == (amf.READ_ON_OF_CLEARS, amf.FRESH_BADGE_TRUE)


def test_unread_total_frozen_keeps_each_creators_first_number(monkeypatch):
    seen = []
    ut = types.SimpleNamespace(observe=lambda aid, body, at: seen.append((aid, body.get("chatMessagesCount"), at)))
    decide = types.SimpleNamespace(count=lambda body: body.get("chatMessagesCount"))
    for name, mod in (("unread_total", ut), ("unread_total_decide", decide)):
        monkeypatch.setitem(__import__("sys").modules, name, mod)
    amf._unread_total_frozen()
    ut.observe("1", {"chatMessagesCount": 9}, 1)
    ut.observe("1", {"chatMessagesCount": 8}, 2)
    ut.observe("1", {}, 3)
    ut.observe("2", {"chatMessagesCount": 4}, 4)
    assert seen == [("1", 9, 1), ("1", None, 3), ("2", 4, 4)]


def _c(phase: str, text):
    return {"t": 0, "phase": phase, "text": text}


@pytest.mark.parametrize("samples,ok,stale,read", [
    ([_c("idle", "Unread70"), _c("idle_one_tab", "Unread 64")], True, 0, 2),
    ([_c("idle", "Unread70"), _c("idle", "Unread70as of 2 min")], False, 1, 2),
    ([_c("idle", "Unread 70 As Of")], True, 0, 1),
    ([_c("idle", None), _c("idle", "Unread70")], True, 0, 1),
    ([_c("idle", None)], False, None, 0),
    ([], False, None, 0),
])
def test_quiet_stale(samples, ok, stale, read):
    v = r.quiet_stale(samples)
    assert v["ok"] is ok and v["quiet_stale_samples"] == stale and v["samples"] == read
    assert v["missing"] == len(samples) - read


def test_quiet_stale_per_phase_and_first_stale():
    v = r.quiet_stale([_c("idle", "Unread70"), _c("idle", "Unread70as of 2 min"), _c("idle_one_tab", None),
                       _c("idle_one_tab", "Unread64as of 5 min")])
    assert v["per_phase"] == {"idle": [2, 1], "idle_one_tab": [1, 1]}
    assert v["first_stale"]["text"] == "Unread70as of 2 min"


def test_fresh_ping_off_targets_quiet_not_stale_alone():
    got = amf.register(lambda apply, targets: types.SimpleNamespace(apply=apply, targets=targets))
    assert got["fresh-ping-off"].targets == (amf.QUIET_NOT_STALE,)
    from slop.lib.faults import FAULTS
    assert FAULTS["fresh-ping-off"].targets == (amf.QUIET_NOT_STALE,)


def test_fresh_ping_off_drops_the_pings_fresh(monkeypatch):
    ev = types.SimpleNamespace(_fresh=lambda sub, sr: {"1": 5})
    monkeypatch.setitem(__import__("sys").modules, "events", ev)
    amf._fresh_ping_off()
    assert ev._fresh(object(), object()) is None
