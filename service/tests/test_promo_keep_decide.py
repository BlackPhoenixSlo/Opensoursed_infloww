#!/usr/bin/env python3
"""promo_keep_decide — table tests over Keep running's pure decision (no DB, no OF):

  case_unreachable_waits         no OF read → Wait(of_unreachable), never a create.
  case_live_promo_stands_down    any Live promo → Wait(promo_already_live); the Kept one is
                                 shown first and named, another promo is shown unnamed.
  case_after_end_table           nothing live: the per-campaign screen (no discount, cycle
                                 cap, Cooldown, no of_promo_id) and the first due campaign →
                                 AfterEnd; a promo gone from the read is ended too.
  case_cooldown_names_its_end    held only by the Cooldown → Wait(nothing_due) with when the
                                 earliest hold ends.
  case_mn01_inferred_cap_without_history_waits  a promo ended only by Claims >= cap (OF's
                                 flags still live) is re-created only when it is the Kept
                                 promo, first read at 0, never went down; else Wait. A promo
                                 OF itself ended needs no history.
  case_owned_earlier_promo_never_blocks  a full-by-count promo this campaign replaced (a past
                                 id, or one its reservations replaced) is ended: After-end;
                                 a promo Inflowwww never owned still waits.
  case_breaker_gained_vs_absolute  a row is zero when its replaced promo gained no Claims
                                 (claims_seen - first_claims <= 0, NULL = 0) or its id was
                                 never seen live within NOT_LISTED_S; 3 zero rows in a row
                                 since the tick → TurnOff(breaker).
  case_breaker_hold_from_settle  the newest automatic create not yet seen live holds the
                                 next create until NOT_LISTED_S after its settle.
  case_budget_automatic_only     3 automatic creates in a rolling hour or 8 in a day →
                                 Wait(budget) until the oldest leaves its window (the
                                 caller passes automatic rows only: manual ones never count).
  case_backoff_math              not_before = now + max(Retry-After, 120 s × 2^(k−1) capped
                                 at 6 h); Retry-After over 6 h is honoured in full; a
                                 not_before ahead holds the create (Wait(backoff)).
  case_turn_off_classes          captcha, deactivated, free page, other 4xx turn off; a
                                 first 403/429 backs off only, a second in a row turns off;
                                 session_dead and not_sent never do.
  case_observe_table             the claim memo: a new Kept id starts it, a missing count
                                 never seeds a 0, a drop untrusts the id, other promos and
                                 a failed read leave it alone.
  case_rv_c10_lower_count_with_dead_flags_untrusts  a lower count with OF's flags dead still
                                 untrusts the id (0 -> 8 -> 2 -> 10 never trusts the 10).
B (Pre-emption, behind PROMO_PREEMPT_ENABLED and the campaign's `preempt`):
  case_threshold_caps            ceil(0.9 × cap): 10→9, 11→10, 50→45, 100→90; cap 9 and 0 never.
  case_fill_trust_rules          Fill only on a Trusted count: the Kept id, first read 0, never
                                 down, present, threshold ≤ Claims < cap; a miss waits with
                                 its wait_reason (count_untrusted); switch, tick or cap < 10
                                 off: the plain stand-down, no reason.
  case_fill_gates                breaker hold, back-off, budget and the recovery slot (a create
                                 left in both windows after this one) hold a Fill as a
                                 stand-down with the reason; the breaker's trip still turns off.
  case_rvb_r1_replaced_still_live_is_second_live  any other promo live beside the Kept one,
                                 a replaced one of ours too, waits (second_live); After-end
                                 stands down for it.
  case_rvb_c3_preempt_respects_cap_and_cooldown  Fill/Timed share After-end's screen: the
                                 cycle cap and no discount stand down, the Cooldown waits
                                 (cooldown).
  case_rvb_r3_timed_window_in_of_time  the Timed window is OF's time: raw time left + skew.
  case_timed_window_and_skew     Timed only on OF's finishedAt read twice unchanged, 0 < left ≤
                                 TIMED_LEAD_S, |skew| ≤ 30 s known; else end_unconfirmed /
                                 clock; no finishedAt → no Timed; cap 9 never.
  case_observe_keeps_finished_at  the memo carries the Kept promo's last finishedAt.

Run: ./venv/bin/python service/tests/test_promo_keep_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from dataclasses import replace  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from promo_keep_decide import (AfterEnd, Created, Fill, Inputs, Kept, Memo, Tally, Timed,  # noqa: E402
                               TurnOff, Wait, backoff_until, decide, failure_turns_off, observe,
                               threshold)

NOW = datetime(2026, 11, 19, 12, 0, 0)


def _promo(pid, *, live=True, cap=10, claims=0, cap_inferred=False, present=True, finished_at=None):
    """A normalised OF read item (of_promos.normalise_of_promo's shape, the keys decide reads)."""
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
    # two live (OF lag): the Kept one is shown, so its Re-check is planned
    got = decide(_in([_kept(1, 11)], [other, p]))
    assert got == Wait("promo_already_live", live=p, kept=1), got
    # two Kept campaigns, one superseded by the other: no ping-pong
    got = decide(_in([_kept(1, 11), _kept(2, 12)], [_promo(11, live=False), _promo(12)]))
    assert got.reason == "promo_already_live" and got.kept == 2, got


def case_after_end_table():
    old = NOW - timedelta(minutes=10)
    ended = [_promo(11, live=False)]
    T = Tally
    rows = [   # (campaigns, promos, knobs, want)
        ([_kept(1, 11)], ended, {}, AfterEnd(1, (1,), T(due=1))),
        ([_kept(1, 11)], [], {}, AfterEnd(1, (1,), T(due=1))),            # gone from history
        ([_kept(1, 11, disc=0)], ended, {}, Wait("nothing_due", tally=T(skipped_no_discount=1))),
        ([_kept(1, 11, disc=101)], ended, {}, Wait("nothing_due", tally=T(skipped_no_discount=1))),
        ([_kept(1, 11, count=3)], ended, {"max_reactivations": 3},
         Wait("nothing_due", tally=T(skipped_cap=1))),
        ([_kept(1, 11, count=3)], ended, {}, AfterEnd(1, (1,), T(due=1))),  # 0 = no cycle cap
        ([_kept(1, None)], [], {}, Wait("nothing_due", tally=T(skipped_unverifiable=1))),
        ([_kept(1, 11, last=old)], ended, {}, AfterEnd(1, (1,), T(due=1))),  # past the Cooldown
        ([_kept(1, 11), _kept(2, 12)], [_promo(11, live=False), _promo(12, live=False)], {},
         AfterEnd(1, (1, 2), T(due=2))),                                     # one per run
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
    rows = [   # (promos, memo, want)
        ([full], trusted, AfterEnd(1, (1,), Tally(due=1))),
        ([full], Memo(), Wait("inferred_cap_untrusted", live=full, kept=1)),          # never read
        ([full], Memo(kept_of_promo_id=11, first_claims=3, last_claims=10),            # first read 3
         Wait("inferred_cap_untrusted", live=full, kept=1)),
        ([full], Memo(kept_of_promo_id=11, first_claims=None, last_claims=10),         # untrusted id
         Wait("inferred_cap_untrusted", live=full, kept=1)),
        ([full], Memo(kept_of_promo_id=12, first_claims=0, last_claims=10),            # another id
         Wait("inferred_cap_untrusted", live=full, kept=1)),
        # a promo that is not the Kept one, full by count only: OF says live, never replaced
        ([_promo(99, claims=10, cap_inferred=True), _promo(11, live=False)], trusted,
         Wait("inferred_cap_untrusted", live=_promo(99, claims=10, cap_inferred=True), kept=None)),
        # OF itself ended it: no history needed (#850)
        ([_promo(11, live=False, claims=10)], Memo(), AfterEnd(1, (1,), Tally(due=1))),
    ]
    for promos, memo, want in rows:
        got = decide(_in([_kept(1, 11)], promos, memo=memo))
        assert got == want, (promos, memo, got)


def case_owned_earlier_promo_never_blocks():
    full_a = _promo(11, claims=10, cap_inferred=True)       # A: replaced by B, still listed full
    b_ended = _promo(12, live=False)                        # B: the Kept promo, ended
    rows = [   # (owned_ids, want)
        (frozenset({11}), AfterEnd(1, (1,), Tally(due=1))),
        (frozenset(), Wait("inferred_cap_untrusted", live=full_a, kept=None)),
    ]
    for owned, want in rows:
        got = decide(_in([_kept(1, 12)], [full_a, b_ended], owned_ids=owned))
        assert got == want, (owned, got)
    # the Kept promo itself is never "earlier": its own history still decides
    got = decide(_in([_kept(1, 11)], [full_a], owned_ids=frozenset({11})))
    assert got == Wait("inferred_cap_untrusted", live=full_a, kept=1), got


def _made(ago_s, *, listed=True, seen=5, first=0, cid=1):
    at = NOW - timedelta(seconds=ago_s)
    return Created(campaign_id=cid, settled_at=at, listed_at=at + timedelta(seconds=30) if listed else None,
                   claims_seen=seen, first_claims=first)


def case_breaker_gained_vs_absolute():
    ended = [_promo(11, live=False)]
    go, off = AfterEnd(1, (1,), Tally(due=1)), TurnOff("breaker", 1)
    zero = _made(4000, seen=3, first=3)                     # 3 claims, none gained while Kept
    rows = [   # (creates newest first, ticked_at, want)
        ([zero, zero, zero], None, off),
        ([zero, zero], None, go),                                               # only 2
        ([zero, _made(5000, seen=8, first=3), zero], None, go),                 # one gained
        ([zero, zero, _made(5000, seen=None, first=None)], None, off),          # NULL = 0
        ([zero, zero, _made(5000, seen=4, first=None)], None, go),              # 4 gained
        ([zero, zero, _made(5000, listed=False)], None, off),                   # never live
        ([_made(1000, seen=0), _made(2000, seen=0), zero], NOW - timedelta(seconds=3000), go),  # 2 since the tick
        ([zero, _made(4500, cid=2, seen=9), zero, zero], None, off),            # only this campaign's
    ]
    for creates, ticked, want in rows:
        got = decide(_in([_kept(1, 11, ticked=ticked)], ended, creates=tuple(creates)))
        assert got == want, (creates, ticked, got)
    # the breaker gates only a create: a Live promo still just waits
    got = decide(_in([_kept(1, 11)], [_promo(11)], creates=(zero, zero, zero)))
    assert got.reason == "promo_already_live", got


def case_breaker_hold_from_settle():
    ended = [_promo(11, live=False)]
    rows = [   # (newest create, want reason)
        (_made(120, listed=False), "breaker_hold"),       # not seen live, inside NOT_LISTED_S
        (_made(599, listed=False), "breaker_hold"),
        (_made(601, listed=False), None),                 # window passed: one zero row, go
        (_made(120), None),                               # seen live: go
    ]
    for made, want in rows:
        got = decide(_in([_kept(1, 11)], ended, creates=(made,)))
        assert (got.reason if isinstance(got, Wait) else None) == want, (made, got)
        if want:
            assert got.cooldown_ends == made.settled_at + timedelta(seconds=600), got


def case_observe_table():
    kept = {11}
    m0 = Memo(kept_of_promo_id=11, first_claims=0, last_claims=4, read_at=NOW - timedelta(minutes=5))
    rows = [   # (memo, promos, want)
        (Memo(), [_promo(11, claims=0)], Memo(11, 0, 0, NOW)),
        (Memo(), [_promo(11, claims=3)], Memo(11, 3, 3, NOW)),
        (Memo(), [_promo(11, present=False)], Memo(11, None, None, NOW)),       # never a 0
        (m0, [_promo(11, claims=6)], Memo(11, 0, 6, NOW)),
        (m0, [_promo(11, claims=10, cap_inferred=True)], Memo(11, 0, 10, NOW)),
        (m0, [_promo(11, claims=3)], Memo(11, None, 3, NOW)),                   # went down
        (m0, [_promo(11, present=False)], m0),                                  # no count: no news
        (m0, [_promo(12, claims=0)], m0),                                       # not a Kept promo
        (m0, [_promo(11, live=False, claims=0)], Memo(11, None, 0, NOW)),       # lower, any flags
        (m0, [_promo(11, live=False, claims=6)], m0),                           # OF ended it
        (m0, None, m0),                                                         # failed read
        (m0, [_promo(13, claims=0)], m0),
        (m0, [], m0),
    ]
    for memo, promos, want in rows:
        got = observe(memo, promos, kept, NOW)
        assert got == want, (memo, promos, got)
    # a new Kept id restarts the memo
    assert observe(m0, [_promo(12, claims=0)], {12}, NOW) == Memo(12, 0, 0, NOW)


def case_rv_c10_lower_count_with_dead_flags_untrusts():
    """Reads 0 -> 8 -> 2 (canClaim false) -> 10 (live, full by count): the 2 untrusts the id,
    so the 10 is never a trusted inferred cap (no create)."""
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
    # 8 in a day, at most 2 in the last hour: held until the oldest is 24 h old
    day = tuple(h(m) for m in (10, 70, 200, 300, 400, 500, 600, 1400))
    got = decide(_in(kept, ended, auto_times=day))
    assert got.reason == "budget" and got.cooldown_ends == h(1400) + timedelta(days=1), got
    assert isinstance(decide(_in(kept, ended, auto_times=day[:7])), AfterEnd)
    # older than a day: no longer counted
    assert isinstance(decide(_in(kept, ended, auto_times=(h(1500),) * 9)), AfterEnd)


def case_backoff_math():
    s = timedelta(seconds=1)
    assert backoff_until(NOW, 1, None) == NOW + 120 * s
    assert backoff_until(NOW, 2, None) == NOW + 240 * s
    assert backoff_until(NOW, 3, 30.0) == NOW + 480 * s           # the doubling beats a short ask
    assert backoff_until(NOW, 1, 600.0) == NOW + 600 * s          # Retry-After beats the doubling
    assert backoff_until(NOW, 20, None) == NOW + 21600 * s        # doubling capped at 6 h
    assert backoff_until(NOW, 1, 28800.0) == NOW + 28800 * s      # Retry-After never capped
    ended, kept = [_promo(11, live=False)], [_kept(1, 11)]
    got = decide(_in(kept, ended, not_before=NOW + 60 * s))
    assert got.reason == "backoff" and got.cooldown_ends == NOW + 60 * s, got
    assert isinstance(decide(_in(kept, ended, not_before=NOW - s)), AfterEnd)
    # the breaker still trips first; a back-off never hides a turn-off
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



# ── B: Pre-emption ──────────────────────────────────────────────────────────

def case_threshold_caps():
    for cap, want in ((9, None), (10, 9), (11, 10), (50, 45), (100, 90), (0, None), (1, None)):
        assert threshold(cap) == want, (cap, threshold(cap))


def _fill_in(promos, memo, **kw):
    """Pre-emption on: the switch and the campaign's tick (Kept 1 on promo 11)."""
    kw.setdefault("preempt_enabled", True)
    return _in([_kept(1, 11, preempt=kw.pop("preempt", True))], promos, memo=memo, **kw)


def case_fill_trust_rules():
    at = lambda claims, **k: _promo(11, cap=50, claims=claims, **k)  # noqa: E731
    clean = lambda last: Memo(11, 0, last, NOW)  # noqa: E731
    rows = [   # (promo, memo, extra Inputs, want: Fill / reason / None = plain stand-down)
        (at(45), clean(45), {}, "fill"),
        (at(49), clean(49), {}, "fill"),
        (at(44), clean(44), {}, None),                                  # below the threshold
        (at(45), Memo(11, 3, 45, NOW), {}, "count_untrusted"),          # first read not 0
        (at(45), Memo(11, None, 45, NOW), {}, "count_untrusted"),       # went down / no first count
        (at(45, present=False), clean(44), {}, "count_untrusted"),      # this read has no count
        (at(45), Memo(12, 0, 45, NOW), {}, "count_untrusted"),          # memo of another id
        (at(45), clean(45), {"preempt_enabled": False}, None),          # switch off
        (at(45), clean(45), {"preempt": False}, None),                  # campaign's tick off
        (_promo(11, cap=9, claims=8), clean(8), {}, None),              # cap 9 never
        (_promo(11, cap=0, claims=500), clean(500), {}, None),          # unlimited never
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
    assert reason(auto_times=(h(10),)) == Fill(1, p)                    # 2 of 3 used after it: 1 left
    assert reason(auto_times=(h(10), h(20))) == "no_recovery_slot"     # this one would use the last
    day = tuple(h(m) for m in (100, 200, 300, 400, 500, 600, 700))
    assert reason(auto_times=day) == "no_recovery_slot"                # the 8th of 8: none spare
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
    # the promo a create replaced, still listed live, is a second live promo all the same
    # (OF may still offer it): stand down, never create over it
    old = _promo(10, cap=50, claims=47)
    got = decide(_fill_in([p, old], memo, owned_ids=frozenset({10})))
    assert got == Wait("promo_already_live", live=p, kept=1, wait_reason="second_live"), got
    got = decide(_fill_in([p, old], memo, owned_ids=frozenset({10}), preempt_enabled=False))
    assert got == Wait("promo_already_live", live=p, kept=1), got
    # ... and After-end stands down for it, owned or not
    for owned in (frozenset({10}), frozenset()):
        got = decide(_in([_kept(1, 11)], [_promo(11, live=False), old], owned_ids=owned))
        assert got == Wait("promo_already_live", live=old, kept=None), (owned, got)


def case_rvb_c3_preempt_respects_cap_and_cooldown():
    p, memo = _promo(11, cap=50, claims=46), Memo(11, 0, 46, NOW)

    def run(**kw):
        c = _kept(1, 11, preempt=True, **{k: kw.pop(k) for k in ("count", "last", "disc") if k in kw})
        return decide(_in([c], [p], memo=memo, preempt_enabled=True, **kw))
    assert run() == Fill(1, p)
    # the cycle cap: Keep running is done with this campaign, no Pre-emption either
    assert run(count=3, max_reactivations=3) == Wait("promo_already_live", live=p, kept=1)
    assert run(count=3, max_reactivations=4) == Fill(1, p)
    # the Cooldown since the last create holds it, named on the card
    got = run(last=NOW - timedelta(seconds=60), cooldown_min=2)
    assert got == Wait("promo_already_live", live=p, kept=1, wait_reason="cooldown"), got
    assert run(last=NOW - timedelta(minutes=3), cooldown_min=2) == Fill(1, p)
    # no valid discount: OF would refuse the create
    assert run(disc=0) == Wait("promo_already_live", live=p, kept=1)


def case_rvb_r3_timed_window_in_of_time():
    end = lambda s: (NOW + timedelta(seconds=s)).isoformat() + "+00:00"  # noqa: E731

    def run(left_s, skew):
        p = _promo(11, cap=50, claims=5, finished_at=end(left_s))
        m = Memo(11, 0, 5, NOW, finished_at=end(left_s))
        got = decide(_fill_in([p], m, prior=replace(m, read_at=NOW - timedelta(minutes=1)), skew_s=skew))
        return got if not isinstance(got, Wait) else got.wait_reason
    # skew = our clock minus OF's: OF's now is ours minus skew, its time left is raw + skew
    assert run(115, 25) is None                       # 140 s left to OF: not yet
    assert isinstance(run(130, -25), Timed)           # 105 s left to OF
    assert isinstance(run(-10, 25), Timed)            # 15 s left to OF, already past on ours
    assert run(10, -25) is None                       # already over to OF: After-end's


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
    assert run(121) is None                                   # outside the lead: just waits
    assert run(0) is None and run(-5) is None                 # past: not Timed (After-end's)
    assert run(None) is None                                  # no OF end time: never Timed
    assert run(100, prior_end=end(160)) == "end_unconfirmed"  # finishedAt moved between reads
    assert run(100, prior_end=None) == "end_unconfirmed"      # first sighting
    assert run(100, skew=31) == "clock" and run(100, skew=-31) == "clock"
    assert run(100, skew=None) == "clock"                     # no create of ours measured yet
    assert isinstance(run(100, skew=-30), Timed)
    assert run(100, cap=9, claims=1) is None                  # cap 9 never
    # a Trusted count inside the window still fills while the clock is unknown
    assert run(100, skew=None, claims=46) == Fill(1, _promo(11, cap=50, claims=46, finished_at=end(100)))
    # prior memo of another id is no confirmation
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
    # a read with no count is no claim news, but its end time is
    assert observe(m, [_promo(11, present=False, finished_at=later)], {11}, NOW) == \
        Memo(11, 0, 4, m.read_at, later)


_harness.run()
