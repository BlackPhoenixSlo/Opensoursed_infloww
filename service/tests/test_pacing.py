#!/usr/bin/env python3
"""
Human typing pacing — `automations/pacing.py` + the phase split in
`_common.hold_with_typing`.

`pacing.py` is PURE (rng injected, no clock, no DB, no OF call), so most cases
exercise it directly. The two that cover `hold_with_typing` use a fake pump and a
fake `asyncio.sleep` so they assert the SHAPE of the hold without spending it.
(`_harness` is still imported FIRST: `automations` pulls in `_common` → `db.engine`,
and an unbound CHATTERLY_DB_URL falls back to the PROD sqlite file. That footgun
does not care whether the test writes rows.)

Cases:
  case_disabled_is_byte_identical:
      the BACK-COMPAT invariant. cfg=None or enabled=False ⇒ Pace is exactly the
      caller's typing time, zero quiet, zero think, zero added — and NO rng draw,
      so turning the feature on and off cannot shift any other seeded sequence.
  case_emoji_agrees_with_strip:
      `has_emoji` and `_common.strip_emojis` never disagree. They are two copies of
      one character class; if they drift, we charge emoji-picking time for a
      character the send path already removed (or skip it for one it kept).
  case_no_pause_ever_reaches_inline_max:
      the SAFETY invariant, swept over 20k seeds and every knob shape: a paced
      bubble's total never reaches rhythm.INLINE_MAX_S. An inline hold past that
      outlives the 900s fan lease and burns one of the executor's 4 GLOBAL run
      slots → to_thread starvation → relay 500s.
  case_drift_rate_matches_the_knob:
      drift_pct is honoured within sampling error at 0 / 30 / 100, and 0 really
      means never (not "rarely").
  case_knobs_do_not_shift_the_sequence:
      moving drift_pct re-decides WHETHER a bubble pauses without re-rolling the
      draws of any other bubble. The roll is drawn unconditionally for exactly
      this reason.
  case_think_gap_stays_inside_the_typing_phase:
      the stall never starts before the typing phase, never runs past its end, and
      never fires when there was too little typing to plausibly stop in.
  case_welcome_burst_phases_match_the_table:
      send_welcome's own sampler: gif fully quiet U(2,6); the greeting quiet
      U(6,18) ONLY when an image is attempted (and drawing NOTHING when it isn't);
      bubble 1 quiet U(10,25) + enter + typing; bubble 2+ delegated to bubble_pace.
  case_welcome_burst_overrides_are_clamped_and_honoured:
      the two payload bands move the quiet phases, an absurd/inverted/negative one
      is clamped to [0, 45], and junk falls back to the default instead of raising.
  case_welcome_burst_never_reaches_inline_max:
      the same SAFETY invariant as above, for the welcome burst, at the longest
      bubble that can exist and the override band at its clamp.
  case_welcome_burst_same_seed_same_pace:
      a seed replays — what makes a paced burst reproducible and testable.
  case_hold_total_is_invariant:
      hold_with_typing sleeps EXACTLY `seconds` no matter how the phases are
      carved. This is what keeps INLINE_MAX_S, the lease, the run budget and
      run_sim's virtual clock honest without touching any of them.
  case_hold_phases_the_indicator:
      with quiet + a think gap, frames are emitted ONLY during the typing slices —
      nothing during the quiet lead-in, nothing during the stall.
  case_hold_defaults_emit_continuously:
      called the old way (no phase arguments) the frames run start to finish, so
      all 16 existing call sites are untouched.
  case_distribution_beats_the_flat_constant:
      the finding that motivated the whole module, as an executable assertion: the
      paced distribution lands closer to measured human inter-bubble gaps than
      both today's and a flat +11s-per-bubble alternative.

Run: ./venv/bin/python service/tests/test_pacing.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
from random import Random  # noqa: E402

from automations import pacing, rhythm  # noqa: E402
from automations._common import has_emoji, strip_emojis  # noqa: E402
from automations.pacing import (  # noqa: E402
    Pace, PaceConfig, bubble_pace, welcome_burst_pace,
)

ON = PaceConfig(enabled=True, drift_pct=30.0, drift_cap_s=90.0, think_gaps=True)

# The measured 120-day production bands (inter-bubble gap, <=15min), in the order
# used by the distance metric below. See pacing.py's docstring for provenance.
_BANDS = [(0, 3), (3, 6), (6, 11), (11, 21), (21, 41), (41, 61),
          (61, 121), (121, 301), (301, 900)]
_BOT = [7.9, 23.8, 43.1, 22.1, 2.1, 0.1, 0.1, 0.2, 0.5]
_HUMAN = [4.5, 18.0, 30.0, 20.5, 10.1, 3.7, 6.0, 4.1, 3.0]


class _CountingRandom(Random):
    """A Random that reports how many times it was asked for anything."""

    def __init__(self, seed=None):
        super().__init__(seed)
        self.draws = 0

    def random(self):
        self.draws += 1
        return super().random()

    def uniform(self, a, b):
        self.draws += 1
        return super().uniform(a, b)

    def lognormvariate(self, mu, sigma):
        self.draws += 1
        return super().lognormvariate(mu, sigma)


# ── 1. Back-compat ───────────────────────────────────────────────────────────
def case_disabled_is_byte_identical():
    for cfg in (None, PaceConfig(), PaceConfig(enabled=False, drift_pct=100.0)):
        rng = _CountingRandom(7)
        p = bubble_pace(12.5, "hey babe 😈 come here", rng, cfg)
        assert p.total_s == 12.5, (cfg, p)
        assert p.quiet_s == 0.0 and p.think_at_s == 0.0 and p.think_for_s == 0.0, p
        assert p.added_s == 0.0 and p.drifted is False, p
        # No draw at all — the off path must not perturb a shared seed.
        assert rng.draws == 0, f"disabled path drew {rng.draws} times from the rng"
    # A zero/blank typing time is still zero, not a floor.
    assert bubble_pace(0.0, "", Random(1), None).total_s == 0.0


def case_emoji_agrees_with_strip():
    samples = [
        "hey babe 😈", "plain text with none", "ok 🥺 come here", "🔥🔥🔥",
        "cafe ☕ later", "a❤️b", "done ✅", "you like it ?", "no — em dash",
        "it's an apostrophe", "♀ sign", "🇺🇸 flag", "", "   ",
    ]
    for t in samples:
        # strip_emojis also trims/collapses whitespace, so compare on the stripped
        # form of the original — the question is only "did any character go".
        removed = strip_emojis(t) != t.strip()
        assert has_emoji(t) == removed, (
            f"detector/stripper disagree on {t!r}: has_emoji={has_emoji(t)} "
            f"stripped={strip_emojis(t)!r}")


# ── 2. Safety ────────────────────────────────────────────────────────────────
def case_no_pause_ever_reaches_inline_max():
    shapes = [
        PaceConfig(enabled=True, drift_pct=100.0, drift_cap_s=90.0),
        PaceConfig(enabled=True, drift_pct=100.0, drift_cap_s=10_000.0),  # absurd
        PaceConfig(enabled=True, drift_pct=100.0, drift_cap_s=pacing._TOTAL_CEIL_S),
        PaceConfig(enabled=True, drift_pct=50.0, drift_cap_s=-5.0),       # negative
    ]
    worst = 0.0
    for cfg in shapes:
        for seed in range(5000):
            # 60s is _MAX_TYPING_DELAY_S — the largest typing time that can exist.
            p = bubble_pace(60.0, "a 😈 long one", Random(seed), cfg)
            worst = max(worst, p.total_s)
            assert p.total_s < rhythm.INLINE_MAX_S, (cfg, seed, p.total_s)
    assert worst > 60.0, "the sweep never exercised a drift at all"


def case_drift_rate_matches_the_knob():
    for pct, lo, hi in [(0.0, 0.0, 0.0), (30.0, 0.28, 0.32), (100.0, 1.0, 1.0)]:
        cfg = PaceConfig(enabled=True, drift_pct=pct, drift_cap_s=90.0)
        n = 20_000
        hits = sum(bubble_pace(8.0, "ok", Random(s), cfg).drifted for s in range(n))
        rate = hits / n
        assert lo <= rate <= hi, f"drift_pct={pct} produced {rate:.3f}"


def case_knobs_do_not_shift_the_sequence():
    """Moving drift_pct must re-decide WHETHER a bubble pauses without re-rolling
    every other draw — otherwise an operator nudging a slider silently re-paces
    every bubble in the account, including the ones that were already fine."""
    a = PaceConfig(enabled=True, drift_pct=0.0, drift_cap_s=90.0)
    b = PaceConfig(enabled=True, drift_pct=100.0, drift_cap_s=90.0)
    for s in range(200):
        pa = bubble_pace(9.0, "hey babe 😈", Random(s), a)
        pb = bubble_pace(9.0, "hey babe 😈", Random(s), b)
        # The garnish is drawn BEFORE the roll, so it is identical either way.
        enter_a = pa.total_s - 9.0 - pa.quiet_s
        enter_b = pb.total_s - 9.0 - pb.quiet_s
        assert abs(enter_a - enter_b) < 1e-9, (s, enter_a, enter_b)
        # …and the emoji reach (the whole of pa's quiet, since pa never drifts).
        assert pa.quiet_s > 0 and pb.quiet_s >= pa.quiet_s - 1e-9, (s, pa, pb)


def case_think_gap_stays_inside_the_typing_phase():
    seen_gap = seen_none = 0
    for s in range(5000):
        typing_s = 1.0 + (s % 40)          # sweep short → long bubbles
        p = bubble_pace(typing_s, "ok then", Random(s), ON)
        typing_phase = p.total_s - p.quiet_s
        assert p.think_at_s >= 0.0 and p.think_for_s >= 0.0, p
        assert p.think_at_s + p.think_for_s <= typing_phase + 1e-9, (s, p)
        if p.think_for_s > 0:
            seen_gap += 1
            assert p.think_at_s > 0, "a stall at offset 0 is just more quiet time"
        else:
            seen_none += 1
    assert seen_gap and seen_none, (seen_gap, seen_none)
    # Too little typing to stop inside ⇒ never a stall.
    for s in range(500):
        p = bubble_pace(0.5, "hi", Random(s), ON)
        assert p.think_for_s == 0.0, (s, p)
    # …and switching it off is absolute.
    off = PaceConfig(enabled=True, drift_pct=30.0, drift_cap_s=90.0, think_gaps=False)
    assert all(bubble_pace(30.0, "a longer line here", Random(s), off).think_for_s == 0.0
               for s in range(500))


# ── 3b. The welcome burst (send_welcome's sampler) ───────────────────────────
def case_welcome_burst_phases_match_the_table():
    """Each bubble of the welcome burst gets the shape the plan specifies, and no
    other: a GIF is all quiet, the greeting is quiet ONLY when it carries an image,
    the line after it always opens with a quiet gap, and everything past that is an
    ordinary paced bubble.

    Bounds are asserted over a seeded sweep rather than one draw, because a single
    draw cannot tell a U(6,18) from a U(10,25) that happened to land low."""
    gif_lo = gif_hi = None
    for seed in range(400):
        # The GIF: picked, not typed — the whole hold is dark, and there is no
        # typing phase to put a think gap inside.
        g = welcome_burst_pace(role="gif", has_image=False, typing_s=0.0,
                               text="", rng=Random(seed))
        assert 2.0 <= g.total_s <= 6.0, (seed, g)
        assert g.quiet_s == g.total_s, (seed, g)
        assert g.think_for_s == 0.0 and g.think_at_s == 0.0, (seed, g)
        gif_lo = g.total_s if gif_lo is None else min(gif_lo, g.total_s)
        gif_hi = g.total_s if gif_hi is None else max(gif_hi, g.total_s)

        # Bubble 0 WITH an image: a quiet lead-in, then the greeting's typing time
        # with the bar on. Quiet + typing, nothing else.
        b0 = welcome_burst_pace(role="opener", has_image=True, typing_s=4.0,
                                text="Hey S-S-S-Sexy Sofie ! !!", rng=Random(seed))
        assert 6.0 <= b0.quiet_s <= 18.0, (seed, b0)
        assert abs(b0.total_s - (b0.quiet_s + 4.0)) < 1e-9, (seed, b0)
        assert b0.think_for_s == 0.0, (seed, b0)

        # Bubble 1: quiet gap + enter press + typing time.
        b1 = welcome_burst_pace(role="gap", has_image=False, typing_s=8.0,
                                text="it's Sunday afternoon in Vancouver",
                                rng=Random(seed))
        assert 10.0 <= b1.quiet_s <= 25.0, (seed, b1)
        typing_phase = b1.total_s - b1.quiet_s
        assert 8.0 + 0.4 <= typing_phase <= 8.0 + 1.2 + 1e-9, (seed, b1)
        assert b1.think_at_s + b1.think_for_s <= typing_phase + 1e-9, (seed, b1)

        # Bubble 2+: whatever `bubble_pace` says under _WELCOME_PACE — identical,
        # not merely similar, so the question is paced by the shipped engine.
        b2 = welcome_burst_pace(role="tail", has_image=False, typing_s=2.0,
                                text="what's yours?", rng=Random(seed))
        assert b2 == bubble_pace(2.0, "what's yours?", Random(seed),
                                 pacing._WELCOME_PACE), (seed, b2)
    # The GIF beat really is drawn across its band, not pinned at one end.
    assert gif_lo < 3.0 and gif_hi > 5.0, (gif_lo, gif_hi)

    # Bubble 0 with NO image attempted is TODAY's hold exactly — and costs no draw,
    # so it cannot shift a later seeded sequence either.
    rng = _CountingRandom(11)
    p = welcome_burst_pace(role="opener", has_image=False, typing_s=4.0,
                           text="Hey", rng=rng)
    assert p == Pace(total_s=4.0), p
    assert rng.draws == 0, f"the no-image greeting drew {rng.draws} times"


def case_welcome_burst_dispatches_on_role_not_position():
    """A welcome burst is VARIABLE-LENGTH, so a bubble's rhythm has to follow what
    it IS, not where it landed.

    Two live shapes drop the middle bubble — `skip_time_bubble`, and a slot whose
    activity line is blank (`_activity_bubble` returns []) — and in BOTH the
    operator's question becomes the second thing sent. Dispatched on position it
    inherited the time line's long U(10,25) dark gap: a fan watching a blank
    screen for up to 25 seconds before a five-word question, on his very first
    conversation. Nobody chose that; it fell out of the arithmetic.

    So the same role draws the same band whatever else the burst contains, and
    the two bands are provably different rather than merely differently named."""
    zero_tails = 0
    for seed in range(300):
        tail = welcome_burst_pace(role="tail", has_image=False, typing_s=2.0,
                                  text="what's yours?", rng=Random(seed))
        gap = welcome_burst_pace(role="gap", has_image=False, typing_s=2.0,
                                 text="what's yours?", rng=Random(seed))
        # The gap ALWAYS opens with the long dark lead-in...
        assert 10.0 <= gap.quiet_s <= 25.0, (seed, gap)
        # ...and the tail is an ordinary paced bubble, identical to the shipped
        # engine's own output rather than a lookalike.
        assert tail == bubble_pace(2.0, "what's yours?", Random(seed),
                                   pacing._WELCOME_PACE), (seed, tail)
        if tail.quiet_s == 0.0:
            zero_tails += 1
    # Most tails carry no dark gap at all (the drift fires ~35% of the time).
    # Under position dispatch every one of those was a 10-25s stare instead.
    assert zero_tails > 150, zero_tails

    # An unknown role degrades to the SHORT end, never to a long dark gap: this
    # is a live send path, and the alternative to a sane fallback is a fan
    # staring at nothing because of a typo.
    p = welcome_burst_pace(role="mystery", has_image=True, typing_s=2.0,
                           text="hi", rng=Random(7))
    assert p == bubble_pace(2.0, "hi", Random(7), pacing._WELCOME_PACE), p


def case_welcome_burst_overrides_are_clamped_and_honoured():
    """The two payload overrides move the quiet bands, and a hostile value cannot
    move them anywhere dangerous: each end is clamped to [0, 45] before the total
    ceiling clamps the hold again. A malformed override falls back to the default
    instead of raising — a typo on a rule must never cost a fan his welcome."""
    for seed in range(300):
        p = welcome_burst_pace(role="gap", has_image=False, typing_s=5.0,
                               text="hi", rng=Random(seed), gap_quiet=(22.0, 38.0))
        assert 22.0 <= p.quiet_s <= 38.0, (seed, p)   # the operator's ~30s open
        q = welcome_burst_pace(role="opener", has_image=True, typing_s=5.0,
                               text="hi", rng=Random(seed), open_quiet=(0.0, 0.0))
        assert q.quiet_s == 0.0, (seed, q)            # a range of zero really is off
        # Absurd / inverted / negative: clamped to the 45s ceiling, never rejected.
        for bad in [(600.0, 900.0), (38.0, 22.0), (-5.0, 500.0)]:
            r = welcome_burst_pace(role="gap", has_image=False,
                                   typing_s=5.0, text="hi", rng=Random(seed),
                                   gap_quiet=bad)
            assert 0.0 <= r.quiet_s <= pacing.WELCOME_QUIET_MAX_S, (bad, seed, r)
    # Junk shapes degrade to the default band rather than raising.
    for junk in ("nonsense", [], [7], {"lo": 1}, [None, None], ["a", "b"]):
        p = welcome_burst_pace(role="gap", has_image=False, typing_s=5.0,
                               text="hi", rng=Random(3), gap_quiet=junk)
        assert 10.0 <= p.quiet_s <= 25.0, (junk, p)


def case_welcome_burst_never_reaches_inline_max():
    """The SAFETY invariant for the welcome burst, mirroring
    `case_no_pause_ever_reaches_inline_max`: swept over every bubble kind, the
    longest bubble that can exist (60s = `_MAX_TYPING_DELAY_S`) and the override
    band at its clamp, no hold ever reaches `rhythm.INLINE_MAX_S`. An inline hold
    past that outlives the 900s fan lease and burns one of the executor's 4 GLOBAL
    run slots."""
    worst = 0.0
    bands = [None, (45.0, 45.0), (0.0, 45.0), (900.0, 900.0)]
    for band in bands:
        for seed in range(1500):
            for role, img in (("opener", True), ("gap", False),
                              ("tail", False), ("gif", False)):
                p = welcome_burst_pace(role=role, has_image=img,
                                       typing_s=60.0, text="a 😈 long one",
                                       rng=Random(seed), open_quiet=band,
                                       gap_quiet=band)
                worst = max(worst, p.total_s)
                assert p.total_s < rhythm.INLINE_MAX_S, (band, seed, role, p.total_s)
                assert p.total_s <= pacing._TOTAL_CEIL_S + 1e-9, (band, seed, role, p)
                assert 0.0 <= p.quiet_s <= p.total_s + 1e-9, (band, seed, role, p)
    assert worst > 100.0, f"the sweep never exercised the clamp at all ({worst})"


def case_welcome_burst_same_seed_same_pace():
    """A seed replays. The sender keys its rng on
    `welcome_pace:{account}:{fan}:{idx}`, so this is what makes a burst
    reproducible — and what lets a test assert on a hold it did not spend."""
    for role, img in (("opener", True), ("gap", False), ("tail", False),
                      ("gif", False)):
        a = welcome_burst_pace(role=role, has_image=img, typing_s=7.0,
                               text="hey babe 😈", rng=Random("seed-me"))
        b = welcome_burst_pace(role=role, has_image=img, typing_s=7.0,
                               text="hey babe 😈", rng=Random("seed-me"))
        assert a == b, (role, a, b)


# ── 4. hold_with_typing's phases ─────────────────────────────────────────────
def _record_hold(**kw):
    """Run hold_with_typing with sleep + emit faked; return (total_slept, frames).

    `frames` is a list of (elapsed_at_emit,) so a case can assert WHEN the bar was
    on without spending the wall-clock time."""
    from automations import _common

    clock = {"t": 0.0}
    frames: list[float] = []

    async def fake_sleep(s):
        clock["t"] += float(s)

    async def fake_emit(account_id, fan_id):
        frames.append(clock["t"])

    real_sleep = _common.asyncio.sleep
    _common.asyncio.sleep = fake_sleep
    import sys
    import types
    stub = types.ModuleType("of_ws")
    stub.emit_typing = fake_emit
    prev = sys.modules.get("of_ws")
    sys.modules["of_ws"] = stub
    try:
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            _common.hold_with_typing("acc", 1, **kw))
    finally:
        _common.asyncio.sleep = real_sleep
        if prev is not None:
            sys.modules["of_ws"] = prev
        else:
            sys.modules.pop("of_ws", None)
    return clock["t"], frames


def case_hold_total_is_invariant():
    shapes = [
        dict(seconds=40.0, typing_indicator=True),
        dict(seconds=40.0, typing_indicator=True, quiet_s=25.0),
        dict(seconds=40.0, typing_indicator=True, quiet_s=25.0,
             think_at_s=4.0, think_for_s=6.0),
        # over-long / nonsensical phases must be clamped, not overrun
        dict(seconds=40.0, typing_indicator=True, quiet_s=999.0),
        dict(seconds=40.0, typing_indicator=True, quiet_s=10.0,
             think_at_s=5.0, think_for_s=999.0),
        dict(seconds=40.0, typing_indicator=True, think_at_s=999.0, think_for_s=5.0),
        dict(seconds=40.0, typing_indicator=False, quiet_s=25.0,
             think_at_s=4.0, think_for_s=6.0),
    ]
    for kw in shapes:
        total, _ = _record_hold(**kw)
        assert abs(total - 40.0) < 1e-6, f"{kw} slept {total}, not 40.0"


def case_hold_phases_the_indicator():
    # 10s quiet, then a 30s typing phase with a 6s stall starting 4s in.
    total, frames = _record_hold(seconds=40.0, typing_indicator=True, quiet_s=10.0,
                                 think_at_s=4.0, think_for_s=6.0)
    assert abs(total - 40.0) < 1e-6, total
    assert frames, "no typing frames at all"
    assert min(frames) >= 10.0 - 1e-9, f"a frame landed during the quiet lead-in: {min(frames)}"
    # Nothing inside the stall window [14, 20).
    inside = [f for f in frames if 14.0 - 1e-9 < f < 20.0 - 1e-9]
    assert not inside, f"frames emitted during the think gap: {inside}"
    # …and it resumed afterwards.
    assert any(f >= 20.0 - 1e-9 for f in frames), "the bar never came back on"


def case_hold_defaults_emit_continuously():
    """Called the old way, the behaviour is exactly the old behaviour."""
    total, frames = _record_hold(seconds=10.0, typing_indicator=True)
    assert abs(total - 10.0) < 1e-6, total
    assert frames and abs(min(frames)) < 1e-9, frames        # started immediately
    assert len(frames) == 4, frames                          # 10s / 2.5s re-emit
    # Indicator off ⇒ one sleep, no frames, whatever the phases say.
    total, frames = _record_hold(seconds=10.0, typing_indicator=False, quiet_s=3.0)
    assert abs(total - 10.0) < 1e-6 and frames == [], (total, frames)


# ── 5. The finding, as an assertion ──────────────────────────────────────────
def _hist(samples):
    return [100.0 * sum(1 for x in samples if lo <= x < hi) / len(samples)
            for lo, hi in _BANDS]


def _dist(a, b):
    return sum(abs(x - y) for x, y in zip(a, b))


def case_distribution_beats_the_flat_constant():
    """The whole reason this module is not `delay += 11`.

    A flat per-bubble constant relocates the pile instead of dispersing it, and
    measures FURTHER from real human inter-bubble gaps than changing nothing. The
    drift model must beat both. Sampled off the measured baseline bands, so this
    asserts the SHAPE of the fix rather than any one draw."""
    rng = Random(2026)

    def draw_core():
        r, cum = rng.random() * 100.0, 0.0
        for w, (lo, hi) in zip(_BOT, _BANDS):
            cum += w
            if r < cum:
                return rng.uniform(lo, hi)
        return rng.uniform(*_BANDS[-1])

    n = 30_000
    cores = [draw_core() for _ in range(n)]
    today = _hist(cores)
    flat11 = _hist([c + 11.0 for c in cores])
    paced = _hist([
        c + bubble_pace(0.0, "hey 😈" if i % 6 == 0 else "ok", Random(i), ON).total_s
        for i, c in enumerate(cores)])

    d_today, d_flat, d_paced = (_dist(today, _HUMAN), _dist(flat11, _HUMAN),
                                _dist(paced, _HUMAN))
    assert d_flat > d_today, (
        f"the flat constant was supposed to be WORSE than doing nothing "
        f"(flat={d_flat:.1f} today={d_today:.1f}) — if this fails the premise moved")
    assert d_paced < d_today, f"pacing must beat today: {d_paced:.1f} vs {d_today:.1f}"
    assert d_paced < d_flat, f"pacing must beat the flat constant: {d_paced:.1f} vs {d_flat:.1f}"
    # And it must actually build the tail that was missing (>20s share).
    assert sum(paced[4:]) > 3.0 * sum(today[4:]), (sum(paced[4:]), sum(today[4:]))


_harness.run()
