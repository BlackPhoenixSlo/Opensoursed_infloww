#!/usr/bin/env python3
from __future__ import annotations

import _harness

from dataclasses import replace  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from promo_keep_decide import (AfterEnd, Created, Fill, Inputs, Kept, Memo, Tally, Timed,  # noqa: E402
                               TurnOff, Wait, backoff_until, decide, failure_turns_off, observe,
                               preempt_applies, preempt_failure, threshold)

NOW = datetime(2026, 11, 19, 12, 0, 0)


def _promo(pid, *, live=True, cap=10, claims=0, cap_inferred=False, present=True, finished_at=None):
    return {"of_promo_id": pid, "is_finished": not live or cap_inferred, "subscribe_counts": cap,
            "subscriber_count": claims if present else 0, "claims_present": present,
            "cap_inferred": cap_inferred, "finished_at": finished_at}


def _kept(cid, of_id, *, disc=50, count=0, last=None, ticked=None, preempt=False):
    return Kept(id=cid, of_promo_id=of_id, discount_percent=disc, reactivate_count=count,
                last_reactivated_at=last, ticked_at=ticked, preempt=preempt)


def _in(campaigns, promos, **kw):
    return Inputs(campaigns=tuple(campaigns), promos=None if promos is None else tuple(promos),
                  now=NOW, **kw)


def case_unreachable_waits():
    assert decide(_in([_kept(1, 11)], None)) == Wait("of_unreachable")


def case_live_promo_stands_down():
    p = _promo(11)
    assert decide(_in([_kept(1, 11)], [p])) == Wait("promo_already_live", live=p, kept=1)
    other = _promo(99)
    got = decide(_in([_kept(1, 11)], [other, _promo(11, live=False)]))
    assert got == Wait("promo_already_live", live=other, kept=None), got
    got = decide(_in([_kept(1, 11)], [other, p]))
    assert got == Wait("promo_already_live", live=p, kept=1), got
    got = decide(_in([_kept(1, 11), _kept(2, 12)], [_promo(11, live=False), _promo(12)]))
    assert got.reason == "promo_already_live" and got.kept == 2, got


def case_after_end_table():
    old = NOW - timedelta(minutes=10)
    ended = [_promo(11, live=False)]
    T = Tally
    rows = [
        ([_kept(1, 11)], ended, {}, AfterEnd(1, (1,), T(due=1))),
        ([_kept(1, 11)], [], {}, AfterEnd(1, (1,), T(due=1))),
        ([_kept(1, 11, disc=0)], ended, {}, Wait("nothing_due", tally=T(skipped_no_discount=1))),
        ([_kept(1, 11, disc=101)], ended, {}, Wait("nothing_due", tally=T(skipped_no_discount=1))),
        ([_kept(1, 11, count=3)], ended, {"max_reactivations": 3},
         Wait("nothing_due", tally=T(skipped_cap=1))),
        ([_kept(1, 11, count=3)], ended, {}, AfterEnd(1, (1,), T(due=1))),
        ([_kept(1, None)], [], {}, Wait("nothing_due", tally=T(skipped_unverifiable=1))),
        ([_kept(1, 11, last=old)], ended, {}, AfterEnd(1, (1,), T(due=1))),
        ([_kept(1, 11), _kept(2, 12)], [_promo(11, live=False), _promo(12, live=False)], {},
         AfterEnd(1, (1, 2), T(due=2))),
    ]
    for campaigns, promos, knobs, want in rows:
        got = decide(_in(campaigns, promos, **knobs))
        assert got == want, (campaigns, promos, knobs, got)


def case_cooldown_names_its_end():
    last = NOW - timedelta(seconds=60)
    got = decide(_in([_kept(1, 11, last=last), _kept(2, 12, last=last - timedelta(seconds=30))],
                     [_promo(11, live=False)], cooldown_min=2))
    assert got == Wait("nothing_due", tally=Tally(skipped_cooldown=2),
                       cooldown_ends=last - timedelta(seconds=30) + timedelta(minutes=2)), got


def case_mn01_inferred_cap_without_history_waits():
    full = _promo(11, claims=10, cap_inferred=True)
    trusted = Memo(kept_of_promo_id=11, first_claims=0, last_claims=10, read_at=NOW)
    rows = [
        ([full], trusted, AfterEnd(1, (1,), Tally(due=1))),
        ([full], Memo(), Wait("inferred_cap_untrusted", live=full, kept=1)),
        ([full], Memo(kept_of_promo_id=11, first_claims=3, last_claims=10),
         Wait("inferred_cap_untrusted", live=full, kept=1)),
        ([full], Memo(kept_of_promo_id=11, first_claims=None, last_claims=10),
         Wait("inferred_cap_untrusted", live=full, kept=1)),
        ([full], Memo(kept_of_promo_id=12, first_claims=0, last_claims=10),
         Wait("inferred_cap_untrusted", live=full, kept=1)),
        ([_promo(99, claims=10, cap_inferred=True), _promo(11, live=False)], trusted,
         Wait("inferred_cap_untrusted", live=_promo(99, claims=10, cap_inferred=True), kept=None)),
        ([_promo(11, live=False, claims=10)], Memo(), AfterEnd(1, (1,), Tally(due=1))),
    ]
    for promos, memo, want in rows:
        got = decide(_in([_kept(1, 11)], promos, memo=memo))
        assert got == want, (promos, memo, got)


def case_owned_earlier_promo_never_blocks():
    full_a = _promo(11, claims=10, cap_inferred=True)
    b_ended = _promo(12, live=False)
    rows = [
        (frozenset({11}), AfterEnd(1, (1,), Tally(due=1))),
        (frozenset(), Wait("inferred_cap_untrusted", live=full_a, kept=None)),
    ]
    for owned, want in rows:
        got = decide(_in([_kept(1, 12)], [full_a, b_ended], owned_ids=owned))
        assert got == want, (owned, got)
    got = decide(_in([_kept(1, 11)], [full_a], owned_ids=frozenset({11})))
    assert got == Wait("inferred_cap_untrusted", live=full_a, kept=1), got


def _made(ago_s, *, listed=True, seen=5, first=0, cid=1):
    at = NOW - timedelta(seconds=ago_s)
    return Created(campaign_id=cid, settled_at=at, listed_at=at + timedelta(seconds=30) if listed else None,
                   claims_seen=seen, first_claims=first)


def case_breaker_gained_vs_absolute():
    ended = [_promo(11, live=False)]
    go, off = AfterEnd(1, (1,), Tally(due=1)), TurnOff("breaker", 1)
    zero = _made(4000, seen=3, first=3)
    rows = [
        ([zero, zero, zero], None, off),
        ([zero, zero], None, go),
        ([zero, _made(5000, seen=8, first=3), zero], None, go),
        ([zero, zero, _made(5000, seen=None, first=None)], None, off),
        ([zero, zero, _made(5000, seen=4, first=None)], None, go),
        ([zero, zero, _made(5000, listed=False)], None, off),
        ([_made(1000, seen=0), _made(2000, seen=0), zero], NOW - timedelta(seconds=3000), go),
        ([zero, _made(4500, cid=2, seen=9), zero, zero], None, off),
    ]
    for creates, ticked, want in rows:
        got = decide(_in([_kept(1, 11, ticked=ticked)], ended, creates=tuple(creates)))
        assert got == want, (creates, ticked, got)
    got = decide(_in([_kept(1, 11)], [_promo(11)], creates=(zero, zero, zero)))
    assert got.reason == "promo_already_live", got


def case_breaker_hold_from_settle():
    ended = [_promo(11, live=False)]
    rows = [
        (_made(120, listed=False), "breaker_hold"),
        (_made(599, listed=False), "breaker_hold"),
        (_made(601, listed=False), None),
        (_made(120), None),
    ]
    for made, want in rows:
        got = decide(_in([_kept(1, 11)], ended, creates=(made,)))
        assert (got.reason if isinstance(got, Wait) else None) == want, (made, got)
        if want:
            assert got.cooldown_ends == made.settled_at + timedelta(seconds=600), got


def case_observe_table():
    kept = {11}
    m0 = Memo(kept_of_promo_id=11, first_claims=0, last_claims=4, read_at=NOW - timedelta(minutes=5))
    rows = [
        (Memo(), [_promo(11, claims=0)], Memo(11, 0, 0, NOW)),
        (Memo(), [_promo(11, claims=3)], Memo(11, 3, 3, NOW)),
        (Memo(), [_promo(11, present=False)], Memo(11, None, None, NOW)),
        (m0, [_promo(11, claims=6)], Memo(11, 0, 6, NOW)),
        (m0, [_promo(11, claims=10, cap_inferred=True)], Memo(11, 0, 10, NOW)),
        (m0, [_promo(11, claims=3)], Memo(11, None, 3, NOW)),
        (m0, [_promo(11, present=False)], m0),
        (m0, [_promo(12, claims=0)], m0),
        (m0, [_promo(11, live=False, claims=0)], Memo(11, None, 0, NOW)),
        (m0, [_promo(11, live=False, claims=6)], m0),
        (m0, None, m0),
        (m0, [_promo(13, claims=0)], m0),
        (m0, [], m0),
    ]
    for memo, promos, want in rows:
        got = observe(memo, promos, kept, NOW)
        assert got == want, (memo, promos, got)
    assert observe(m0, [_promo(12, claims=0)], {12}, NOW) == Memo(12, 0, 0, NOW)


def case_rv_c10_lower_count_with_dead_flags_untrusts():
    m = Memo()
    for p in ([_promo(11, claims=0)], [_promo(11, claims=8)], [_promo(11, live=False, claims=2)],
              [_promo(11, claims=10, cap_inferred=True)]):
        m = observe(m, p, {11}, NOW)
    assert m.first_claims is None, m
    v = decide(_in([_kept(1, 11)], [_promo(11, claims=10, cap_inferred=True)], memo=m))
    assert v == Wait("inferred_cap_untrusted", live=_promo(11, claims=10, cap_inferred=True), kept=1), v


def case_budget_automatic_only():
    ended, kept = [_promo(11, live=False)], [_kept(1, 11)]
    h = lambda m: NOW - timedelta(minutes=m)  # noqa: E731
    assert isinstance(decide(_in(kept, ended, auto_times=(h(10), h(50)))), AfterEnd)
    got = decide(_in(kept, ended, auto_times=(h(10), h(30), h(50))))
    assert got.reason == "budget" and got.cooldown_ends == h(50) + timedelta(hours=1), got
    day = tuple(h(m) for m in (10, 70, 200, 300, 400, 500, 600, 1400))
    got = decide(_in(kept, ended, auto_times=day))
    assert got.reason == "budget" and got.cooldown_ends == h(1400) + timedelta(days=1), got
    assert isinstance(decide(_in(kept, ended, auto_times=day[:7])), AfterEnd)
    assert isinstance(decide(_in(kept, ended, auto_times=(h(1500),) * 9)), AfterEnd)


def case_backoff_math():
    s = timedelta(seconds=1)
    assert backoff_until(NOW, 1, None) == NOW + 120 * s
    assert backoff_until(NOW, 2, None) == NOW + 240 * s
    assert backoff_until(NOW, 3, 30.0) == NOW + 480 * s
    assert backoff_until(NOW, 1, 600.0) == NOW + 600 * s
    assert backoff_until(NOW, 20, None) == NOW + 21600 * s
    assert backoff_until(NOW, 1, 28800.0) == NOW + 28800 * s
    ended, kept = [_promo(11, live=False)], [_kept(1, 11)]
    got = decide(_in(kept, ended, not_before=NOW + 60 * s))
    assert got.reason == "backoff" and got.cooldown_ends == NOW + 60 * s, got
    assert isinstance(decide(_in(kept, ended, not_before=NOW - s)), AfterEnd)
    zero = Created(1, NOW - timedelta(hours=1), None, 0, 0)
    got = decide(_in(kept, ended, creates=(zero,) * 3, not_before=NOW + 60 * s))
    assert got == TurnOff("breaker", 1), got


def case_turn_off_classes():
    for cls in ("captcha", "deactivated", "price_free"):
        assert failure_turns_off(cls, None) == cls
    assert failure_turns_off("http_400", None) == "create_refused"
    assert failure_turns_off("http_404", "http_403") == "create_refused"
    for first in ("http_403", "http_429"):
        assert failure_turns_off(first, None) is None
        assert failure_turns_off(first, "http_400") is None
        assert failure_turns_off(first, "not_sent") is None
        for prev in ("http_403", "http_429"):
            assert failure_turns_off(first, prev) == "rate_limited"
    for cls in ("session_dead", "not_sent", None):
        assert failure_turns_off(cls, "http_429") is None


def case_f5_preempt_failure_one_result():
    table = {
        ("captcha", None): ("captcha", False, False),
        ("deactivated", None): ("deactivated", False, False),
        ("price_free", "http_429"): ("price_free", False, False),
        ("http_400", None): (None, True, True),
        ("http_429", None): (None, False, True),
        ("http_429", "http_403"): (None, True, True),
        ("http_500", None): (None, False, True),
        ("session_dead", None): (None, False, False),
        ("session_dead", "http_429"): (None, False, False),
    }
    for (cls, prev), want in table.items():
        assert preempt_failure(cls, prev) == want, (cls, prev, preempt_failure(cls, prev))




def case_f7_preempt_applies_table():
    table = {(True, True, 10): True, (True, True, 50): True, (True, True, 9): False,
             (True, True, 0): False, (True, True, None): False, (False, True, 50): False,
             (True, False, 50): False}
    for (on, ticked, cap), want in table.items():
        assert preempt_applies(on, ticked, cap) is want, (on, ticked, cap)


def case_threshold_caps():
    for cap, want in ((9, None), (10, 9), (11, 10), (50, 45), (100, 90), (0, None), (1, None)):
        assert threshold(cap) == want, (cap, threshold(cap))


def _fill_in(promos, memo, **kw):
    kw.setdefault("preempt_enabled", True)
    return _in([_kept(1, 11, preempt=kw.pop("preempt", True))], promos, memo=memo, **kw)


def case_fill_trust_rules():
    at = lambda claims, **k: _promo(11, cap=50, claims=claims, **k)  # noqa: E731
    clean = lambda last: Memo(11, 0, last, NOW)  # noqa: E731
    rows = [
        (at(45), clean(45), {}, "fill"),
        (at(49), clean(49), {}, "fill"),
        (at(44), clean(44), {}, None),
        (at(45), Memo(11, 3, 45, NOW), {}, "count_untrusted"),
        (at(45), Memo(11, None, 45, NOW), {}, "count_untrusted"),
        (at(45, present=False), clean(44), {}, "count_untrusted"),
        (at(45), Memo(12, 0, 45, NOW), {}, "count_untrusted"),
        (at(45), clean(45), {"preempt_enabled": False}, None),
        (at(45), clean(45), {"preempt": False}, None),
        (_promo(11, cap=9, claims=8), clean(8), {}, None),
        (_promo(11, cap=0, claims=500), clean(500), {}, None),
    ]
    for p, memo, kw, want in rows:
        got = decide(_fill_in([p], memo, **kw))
        if want == "fill":
            assert got == Fill(1, p), (p, memo, kw, got)
        else:
            assert got == Wait("promo_already_live", live=p, kept=1, wait_reason=want), (p, memo, kw, got)


def case_fill_gates():
    p, memo = _promo(11, cap=50, claims=46), Memo(11, 0, 46, NOW)
    h = lambda m: NOW - timedelta(minutes=m)  # noqa: E731

    def reason(**kw):
        got = decide(_fill_in([p], memo, **kw))
        return got.wait_reason if isinstance(got, Wait) else got
    assert reason() == Fill(1, p)
    assert reason(auto_times=(h(10),)) == Fill(1, p)
    assert reason(auto_times=(h(10), h(20))) == "no_recovery_slot"
    day = tuple(h(m) for m in (100, 200, 300, 400, 500, 600, 700))
    assert reason(auto_times=day) == "no_recovery_slot"
    assert reason(auto_times=day[:6]) == Fill(1, p)
    assert reason(not_before=NOW + timedelta(minutes=3)) == "backoff"
    assert reason(auto_times=(h(5), h(6), h(7))) == "budget"
    assert reason(creates=(_made(120, listed=False),)) == "breaker_hold"
    zero = _made(4000, seen=3, first=3)
    assert reason(creates=(zero, zero, zero)) == TurnOff("breaker", 1)


def case_rvb_r1_replaced_still_live_is_second_live():
    p, memo = _promo(11, cap=50, claims=46), Memo(11, 0, 46, NOW)
    other = _promo(99)
    got = decide(_fill_in([p, other], memo))
    assert got == Wait("promo_already_live", live=p, kept=1, wait_reason="second_live"), got
    old = _promo(10, cap=50, claims=47)
    got = decide(_fill_in([p, old], memo, owned_ids=frozenset({10})))
    assert got == Wait("promo_already_live", live=p, kept=1, wait_reason="second_live"), got
    got = decide(_fill_in([p, old], memo, owned_ids=frozenset({10}), preempt_enabled=False))
    assert got == Wait("promo_already_live", live=p, kept=1), got
    for owned in (frozenset({10}), frozenset()):
        got = decide(_in([_kept(1, 11)], [_promo(11, live=False), old], owned_ids=owned))
        assert got == Wait("promo_already_live", live=old, kept=None), (owned, got)


def case_rvb_c3_preempt_respects_cap_and_cooldown():
    p, memo = _promo(11, cap=50, claims=46), Memo(11, 0, 46, NOW)

    def run(**kw):
        c = _kept(1, 11, preempt=True, **{k: kw.pop(k) for k in ("count", "last", "disc") if k in kw})
        return decide(_in([c], [p], memo=memo, preempt_enabled=True, **kw))
    assert run() == Fill(1, p)
    assert run(count=3, max_reactivations=3) == Wait("promo_already_live", live=p, kept=1)
    assert run(count=3, max_reactivations=4) == Fill(1, p)
    got = run(last=NOW - timedelta(seconds=60), cooldown_min=2)
    assert got == Wait("promo_already_live", live=p, kept=1, wait_reason="cooldown"), got
    assert run(last=NOW - timedelta(minutes=3), cooldown_min=2) == Fill(1, p)
    assert run(disc=0) == Wait("promo_already_live", live=p, kept=1)


def case_rvb_r3_timed_window_in_of_time():
    end = lambda s: (NOW + timedelta(seconds=s)).isoformat() + "+00:00"  # noqa: E731

    def run(left_s, skew):
        p = _promo(11, cap=50, claims=5, finished_at=end(left_s))
        m = Memo(11, 0, 5, NOW, finished_at=end(left_s))
        got = decide(_fill_in([p], m, prior=replace(m, read_at=NOW - timedelta(minutes=1)), skew_s=skew))
        return got if not isinstance(got, Wait) else got.wait_reason
    assert run(115, 25) is None
    assert isinstance(run(130, -25), Timed)
    assert isinstance(run(-10, 25), Timed)
    assert run(10, -25) is None


def case_timed_window_and_skew():
    end = lambda s: (NOW + timedelta(seconds=s)).isoformat() + "+00:00"  # noqa: E731

    def run(left_s, *, prior_end=..., skew=0, cap=50, claims=5):
        fin = None if left_s is None else end(left_s)
        p = _promo(11, cap=cap, claims=claims, finished_at=fin)
        prior = Memo(11, 0, claims, NOW - timedelta(minutes=1),
                     finished_at=fin if prior_end is ... else prior_end)
        got = decide(_fill_in([p], Memo(11, 0, claims, NOW, finished_at=fin), prior=prior, skew_s=skew))
        return got if not isinstance(got, Wait) else got.wait_reason
    assert isinstance(run(100), Timed) and run(100).campaign_id == 1
    assert isinstance(run(120), Timed)
    assert run(121) is None
    assert run(0) is None and run(-5) is None
    assert run(None) is None
    assert run(100, prior_end=end(160)) == "end_unconfirmed"
    assert run(100, prior_end=None) == "end_unconfirmed"
    assert run(100, skew=31) == "clock" and run(100, skew=-31) == "clock"
    assert run(100, skew=None) == "clock"
    assert isinstance(run(100, skew=-30), Timed)
    assert run(100, cap=9, claims=1) is None
    assert run(100, skew=None, claims=46) == Fill(1, _promo(11, cap=50, claims=46, finished_at=end(100)))
    p = _promo(11, cap=50, claims=5, finished_at=end(100))
    got = decide(_fill_in([p], Memo(11, 0, 5, NOW, finished_at=end(100)),
                          prior=Memo(12, 0, 5, NOW, finished_at=end(100)), skew_s=0))
    assert got.wait_reason == "end_unconfirmed", got


def case_observe_keeps_finished_at():
    fin = "2026-11-19T12:30:00+00:00"
    assert observe(Memo(), [_promo(11, finished_at=fin)], {11}, NOW) == Memo(11, 0, 0, NOW, fin)
    m = Memo(11, 0, 4, NOW - timedelta(minutes=1), fin)
    later = "2026-11-19T12:40:00+00:00"
    assert observe(m, [_promo(11, claims=5, finished_at=later)], {11}, NOW) == Memo(11, 0, 5, NOW, later)
    assert observe(m, [_promo(11, present=False, finished_at=later)], {11}, NOW) == \
        Memo(11, 0, 4, m.read_at, later)


_harness.run()
