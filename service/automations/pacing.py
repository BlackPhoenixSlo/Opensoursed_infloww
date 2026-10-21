"""
service/automations/pacing.py — how a bubble is TYPED, not when a reply starts.

This module owns the gaps BETWEEN the bubbles of one burst, and what the fan's
"…is typing" indicator does while they land. Its live consumer is the welcome
burst (`welcome_burst_pace`, called by send_welcome).

WHY IT EXISTS. Until now the only thing between two bubbles was
`typing_delay_seconds(text, wpm)` = `words / wpm * 60`. Bubble length is narrowly
distributed, so the gap was too — and measured over 120 days of production the
result is a distribution no person produces:

    inter-bubble gap      BOT      HUMAN chatter    FAN (in→in)
    0-2s                  7.9%          4.5%           1.3%
    3-5s                 23.8%         18.0%           5.2%
    6-10s                43.1%         30.0%          14.8%     ← the pile
    11-20s               22.1%         20.5%          22.2%
    21-40s                2.1%         10.1%          18.9%
    41-60s                0.1%          3.7%           7.7%
    61-120s               0.1%          6.0%           9.6%
    2-5min                0.2%          4.1%          10.2%
    5-15min               0.5%          3.0%          10.2%
    ── above 20s          3.0%         26.9%          56.6%
    n                    35,688        1,952         23,426

The tell is NOT that she is too fast on average. The bottom of the distribution
already matches (p10 3s vs 4s). The tell is the last row: **she never once stops
mid-reply.** Nothing in the old code path could produce a 90-second inter-bubble
gap, so across 35,688 samples it essentially never happened.

WHY IT IS NOT A CONSTANT. The obvious fix — "add N seconds to every bubble" — was
simulated against the table above and is WORSE THAN DOING NOTHING. A flat +11s
moves 66% of all gaps into the 11-20s band: the same pile, relocated to the one
band that already matched, plus a hard floor at 11s where humans put 44% of their
gaps below. Distance-to-human goes 47.8 → 134.3. The same is true of a flat
5-10s "thinking" pause (→ 118.5). Every budget tier of a grid search spends its
seconds on RARE LONG pauses instead; the fitted optimum for a 5-10s always-on
break is probability ZERO. So:

    dispersion, not delay. One bubble in ~three gets a real pause; the rest are
    left alone, which is what preserves the fast bursts a person actually sends.

THE THREE TERMS (all on idx >= 1 only):
  • ENTER PRESS — uniform(0.4, 1.2)s, always. The cheapest term in the file: it
    moves bot p10 from 3s to 4s, which is exactly the human p10.
  • EMOJI REACH — uniform(2, 6)s, only when the FINAL bubble text carries one.
    17.4% of bot bubbles do (humans: 12.8%). Charged on the finalized string, so
    an account running `strip_emojis` pays nothing — the emoji is already gone by
    the time `parts` is built (`finalize_draft` strips before the split).
  • THE DRIFT — a lognormal pause on `p_drift` of bubbles, capped. This is the
    entire fix; the two above are garnish. Capped at 90s by default so the hold
    stays INLINE-SAFE (`rhythm.INLINE_MAX_S` is 120): a gap that needs the
    scheduler is a different feature with a lease, a job row and a wake poll, and
    this module deliberately does not open that door.

THE INDICATOR IS THE OTHER HALF, AND IT IS FREE. `hold_with_typing` re-emits OF's
live typing frame every 2.5s for the WHOLE hold, so today the bar is on for
exactly as long as the gap, on every bubble, on every account — a perfectly
reliable oracle that says "the entire delay was typing". Real people type, stop,
and type again. So a pace carries THREE numbers the caller hands straight to
`hold_with_typing`, and only the first one affects timing at all:

    total_s   what the caller holds. THE ONLY number that moves a clock.
    quiet_s   leading slice with the indicator OFF (she hasn't started typing:
              she's reading, thinking, reaching for the emoji tray).
    think_*   a silent slice INSIDE the typing phase — she stopped mid-sentence.
              Costs zero added latency. It is a redistribution, not an addition.

INVARIANT, load-bearing: `total_s` is the whole hold. `quiet_s` and `think_*`
only decide WHEN frames are emitted inside it. That is what keeps every existing
guard honest without touching one of them — `rhythm.INLINE_MAX_S`, the fan lease
TTL and the deferral boundary all read a single total and keep reading the same one.

PURE + SEEDED: `rng` is injected, there is no wall clock and no global random,
so a test is not flaky and a sim replays. The caller passes its OWN `Random`
(seeded per bubble).

`PaceConfig()` defaults to DISABLED (⇒ `bubble_pace` returns the caller's typing
time and nothing else, byte-identically, without drawing from the rng at all).
"""
from __future__ import annotations

from dataclasses import dataclass
from random import Random

from ._common import has_emoji
from .rhythm import INLINE_MAX_S as _INLINE_MAX_S

# ── The three terms. Deliberately NOT operator knobs: an operator has no basis on
# which to answer "how long does it take to press enter", and every one of these is
# measured or bounded rather than chosen. The RATE and the CAP are knobs (see
# PaceConfig) because those are policy — how human vs how fast — and that is a
# question about the account, not about typing.
_ENTER_S = (0.4, 1.2)        # find the send button and hit it
_EMOJI_S = (2.0, 6.0)        # open the tray, scroll, pick
_EMOJI_RATE_NOTE = 0.174     # measured share of bot bubbles carrying an emoji.
                             # Not used in code — the check below is exact, per
                             # bubble. Recorded so the number in the docstring has
                             # a home next to the thing it justifies.

# The drift: a lognormal whose median is ~e^mu seconds. mu=3.8 ⇒ ~45s median, and
# sigma=1.1 gives the long right shoulder the 61-120s / 2-5min bands need. These
# came out of a grid search against the blended human+fan target above; at the
# inline-safe cap (90s) they are the best-fitting pair in the sweep.
_DRIFT_MU, _DRIFT_SIGMA = 3.8, 1.1

# A pause is only believable as "she stopped typing" if there was typing to stop.
# Below this the typing phase is over before a person could have paused inside it,
# so the think-gap is skipped rather than scaled to something meaningless.
_THINK_MIN_TYPING_S = 6.0
_THINK_S = (5.0, 10.0)       # the operator's number, and a natural mid-sentence stall
_THINK_MAX_SHARE = 0.6       # never eat more than this much of the typing phase

# `has_emoji` is imported from `_common`, where `strip_emojis` already lives. The
# emoji charge is only correct if it asks the SAME question the send path answers
# when it decides whether the character survives, so the two share one pattern
# rather than two that a test has to police. Note this is always evaluated on the
# FINALIZED bubble (post `finalize_draft`, post typo/non-native, post
# `strip_emojis`) — an account running the emoji strip has none left by then and
# correctly pays nothing.


@dataclass(frozen=True)
class PaceConfig:
    """The pacing knobs. The operator surface that persisted them (the legacy AI
    Chatter config) was removed; the welcome burst builds its own fixed instance
    (`_WELCOME_PACE`)."""
    enabled: bool = False
    # How often a bubble gets a real pause. The whole fix lives here. 0 ⇒ the
    # drift never fires and only the enter/emoji garnish remains.
    drift_pct: float = 30.0
    # The ceiling on one drift, in seconds. Clamped to `_TOTAL_CEIL_S` to stay
    # inline safe.
    drift_cap_s: float = 90.0
    # The mid-typing stall. Costs no latency — it only blanks the indicator.
    think_gaps: bool = True


# The ceiling on a WHOLE paced bubble — typing time included, not just the drift.
# Derived from rhythm rather than retyped so the two cannot drift apart; rhythm.py
# is pure stdlib, so this adds no import weight and no cycle.
#
# ⚠️ TWO different 120s limits bind here, and the SECOND one is the tight one.
# `rhythm.INLINE_MAX_S` bounds the HOLD. The bubble window (also 120s)
# bounds the gap between the `created_at` of two consecutive outbound rows — which
# is the hold PLUS the `to_thread(client.send_message)` round-trip, and on the
# price-validation-400 retry path it is the hold plus TWO of them. Past that window
# the bubbles stop being read as ONE reply, so each starts burning its own unit of
# `msg_limits_by_signal` — the regression that once turned 184 replies into 1202
# cadence skips. So the margin is sized for a network round-trip, not float dust.
_TOTAL_CEIL_S = _INLINE_MAX_S - 15.0

@dataclass(frozen=True)
class Pace:
    """What the caller holds, and what the fan sees while it holds.

    ONLY `total_s` moves a clock. `quiet_s` / `think_at_s` / `think_for_s`
    redistribute the indicator inside that same total — see the module docstring's
    INVARIANT. `added_s` is bookkeeping: the part of `total_s` this module added on
    top of the caller's typing time, so the caller can charge it to its inline
    budget without re-deriving it."""
    total_s: float
    quiet_s: float = 0.0
    think_at_s: float = 0.0
    think_for_s: float = 0.0
    added_s: float = 0.0
    drifted: bool = False


def _think_gap(typing_phase: float, rng: Random, cfg: PaceConfig) -> tuple[float, float]:
    """`(think_at_s, think_for_s)` — the one mid-sentence stall, or (0, 0).

    Pure redistribution: the caller has already fixed its total, and this only
    decides where inside the TYPING phase the bar goes dark. Landed strictly
    inside the phase, never at either edge — a gap at offset 0 is just more quiet
    time, and one at the end is a pause before the send, which reads as exactly
    the machine beat it exists to break up.

    Shared by `bubble_pace` and `welcome_burst_pace` so the two cannot drift into
    two different notions of "she stopped typing for a second". The draw order
    (duration, then offset) is part of the contract: it is what makes a seeded
    Pace replay."""
    if not cfg.think_gaps or typing_phase < _THINK_MIN_TYPING_S:
        return 0.0, 0.0
    want = rng.uniform(*_THINK_S)
    think_for = min(want, typing_phase * _THINK_MAX_SHARE)
    span = typing_phase - think_for
    think_at = rng.uniform(span * 0.25, span * 0.75) if span > 0 else 0.0
    return think_at, think_for


def bubble_pace(typing_s: float, text: str, rng: Random,
                cfg: PaceConfig | None = None) -> Pace:
    """The pace for ONE bubble of a multi-bubble burst.

    `typing_s` is the caller's existing `typing_delay_seconds(text, wpm)` — the
    only length-correlated term, and it is kept exactly as-is. Everything this
    function adds is drawn, never fixed.

    Disabled (or no config) ⇒ `Pace(total_s=typing_s)`: the same number the caller
    already had, zero quiet time, no think gap. `hold_with_typing` then behaves
    byte-identically to today. No rng is drawn on that path, so turning the
    feature on and off cannot shift any other seeded sequence."""
    typing_s = max(0.0, float(typing_s or 0.0))
    if cfg is None or not cfg.enabled:
        return Pace(total_s=typing_s)

    # ── The garnish. Always drawn (in this fixed order, so a seed replays).
    enter = rng.uniform(*_ENTER_S)
    emoji = rng.uniform(*_EMOJI_S) if has_emoji(text) else 0.0

    # ── The fix. One bubble in ~three genuinely stops.
    drift = 0.0
    cap = min(max(0.0, float(cfg.drift_cap_s)), _TOTAL_CEIL_S)
    # ⚠️ The DRIFT cap is not the TOTAL cap, and conflating them is a live bug this
    # test caught: `typing_s` reaches _MAX_TYPING_DELAY_S (60s) on a long bubble, so
    # 60 + garnish + a 90s drift is 157s — past rhythm.INLINE_MAX_S, where the hold
    # outlives the 900s fan lease and burns one of the executor's 4 GLOBAL run slots.
    # Bound what is LEFT after the terms already drawn, so the ceiling holds no
    # matter how long the bubble or how generous the knob.
    cap = min(cap, max(0.0, _TOTAL_CEIL_S - (typing_s + enter + emoji)))
    # Draw the roll UNCONDITIONALLY so the rng sequence does not depend on the
    # rate — moving the rate must not re-roll every later bubble into a different
    # draw.
    roll = rng.random()
    if cap > 0 and roll < max(0.0, min(100.0, float(cfg.drift_pct))) / 100.0:
        drift = min(rng.lognormvariate(_DRIFT_MU, _DRIFT_SIGMA), cap)

    # She is not typing while she reaches for an emoji, and she is not typing
    # while she is doing something else entirely. Both are QUIET — the indicator
    # stays dark and the fan simply sees nothing, which is what a person looks
    # like when they have put the phone down.
    quiet = emoji + drift
    typing_phase = typing_s + enter
    total = quiet + typing_phase

    # ── The mid-sentence stall. Pure redistribution: it takes a slice OUT of the
    # typing phase rather than adding one, so `total` above is already final and
    # nothing downstream sees a different number because of it.
    think_at, think_for = _think_gap(typing_phase, rng, cfg)

    return Pace(total_s=total, quiet_s=quiet, think_at_s=think_at,
                think_for_s=think_for, added_s=total - typing_s,
                drifted=drift > 0)


# ── The welcome burst (send_welcome's second consumer of this module) ────────
#
# A welcome is not a reply: there is no inbound message being answered, nothing
# was read before bubble 0, and the burst's SHAPE is fixed (greeting[+image] → the line → the
# operator's question → the GIF) rather than however many parts a draft split into.
# What carries over is the finding itself — dispersion not delay, and phases where
# the "…is typing" bar is honestly dark because she is not typing.
#
# ⚠️ HONESTY: these numbers are DRAWN, not measured. This module's table is 120 days
# of ESTABLISHED-thread reply gaps; no welcome burst has ever been measured. They are
# deliberately SHORTER than the operator's 30s/20s illustration for exactly that
# reason. An account that wants his numbers sets `pace_open_quiet_s` /
# `pace_gap_quiet_s` on the rule payload — one JSON edit, no deploy.
_WELCOME_PACE = PaceConfig(enabled=True, drift_pct=35.0, drift_cap_s=20.0,
                           think_gaps=True)
_WELCOME_GIF_S = (2.0, 6.0)          # a GIF is PICKED, not typed: the hold is all quiet
_WELCOME_OPEN_QUIET_S = (6.0, 18.0)  # before the greeting — only when an image is attempted
_WELCOME_GAP_QUIET_S = (10.0, 25.0)  # before the line that follows the greeting
# The bound on an OPERATOR-supplied range, applied before the total ceiling applies
# its own. 45s of dark screen is already past anything the measured table justifies;
# past that a fan is watching nothing happen on his very first message.
WELCOME_QUIET_MAX_S = 45.0


def _welcome_quiet(rng: Random, override: object,
                   default: tuple[float, float]) -> float:
    """One quiet draw from `override` if it is a usable [lo, hi], else `default`.

    The override rides the RULE PAYLOAD (raw JSON, no typed editor), so it arrives
    as whatever the operator typed. A malformed one falls back to the default
    rather than raising: a bad number on a rule must never cost a fan his welcome."""
    lo, hi = default
    if override is not None:
        try:
            lo, hi = float(override[0]), float(override[1])
        except (TypeError, ValueError, IndexError, KeyError):
            lo, hi = default
        else:
            lo = min(max(0.0, lo), WELCOME_QUIET_MAX_S)
            hi = min(max(0.0, hi), WELCOME_QUIET_MAX_S)
            if hi < lo:
                lo, hi = hi, lo
    return rng.uniform(lo, hi)


# The parts a welcome burst is made of, in send order. A bubble's ROLE, not its
# position, is what decides its rhythm — a burst is variable-length, so position
# decides nothing.
#
# ⚠️ THIS MODULE OWNS THE NAMES, and `send_welcome` imports them (it already
# imports `welcome_burst_pace` from here; nothing here imports it, so this is the
# only direction that can hold). They used to exist in four places: `WELCOME_ROLES`
# here, imported by nobody; `send_welcome._ROLE_*`, which is what actually crosses
# the boundary; bare literals in `welcome_burst_pace` below; and two more in
# BrainPanel. Renaming a role in the sender therefore did not break anything —
# it silently degraded that role to `bubble_pace`, the documented "unknown role is
# paced as tail" fallback, on a live send path. The fallback is a sound decision;
# the defect was that a TYPO and a DELIBERATE DEFAULT were indistinguishable.
ROLE_OPENER = "opener"   # the greeting, and the only bubble that carries an image
ROLE_GAP = "gap"         # the time / activity line after it — the optional one
ROLE_TAIL = "tail"       # the operator's question, appended word-for-word
ROLE_GIF = "gif"         # the text-less giphy bubble (never in `bubbles`)
WELCOME_ROLES = (ROLE_OPENER, ROLE_GAP, ROLE_TAIL, ROLE_GIF)


def welcome_burst_pace(*, role: str, has_image: bool,
                       typing_s: float, text: str, rng: Random,
                       open_quiet: tuple[float, float] | None = None,
                       gap_quiet: tuple[float, float] | None = None) -> Pace:
    """How long send_welcome holds before a bubble, and what the fan sees.

    Pure and seeded exactly like the rest of this module: the caller passes its own
    `Random` (seeded per bubble — `welcome_pace:{account}:{fan}:{idx}`), so a burst
    replays and a test is not flaky. There is NO env check in here; the caller
    decides whether the feature is on, and when it is off this function is never
    called at all, so nothing is drawn.

    ⚠️ IT DISPATCHES ON `role`, NOT ON THE BUBBLE'S INDEX, and that is a bug fix
    rather than a preference. The burst is VARIABLE-LENGTH: the middle bubble
    disappears when `skip_time_bubble` is on AND when `_activity_bubble` returns
    nothing for an unfilled slot (a live shape — `test_send_welcome`'s blank-slot
    pin case). In both of those the operator's QUESTION slides into position 1, and
    an index-dispatching sampler silently paid it the long U(10,25) "gap before the
    second line" instead of the short beat it is. Nobody decided that; it just fell
    out of the arithmetic. The caller knows each bubble's role while it is
    composing them, so it says so.

    The four roles, all drawn, in this fixed order:

      "gif"     fully quiet U(2,6)s. She picked it, she did not type it, and there
                is no indicator to run — a seeded sticker beat. Replaces send_welcome's flat 3.0s.
      "opener"  the greeting. Quiet U(6,18)s ONLY when an image is ATTEMPTED
                (`has_image`) — she was choosing a picture — then the greeting's
                own typing time with the bar on. No image ⇒ no quiet at all,
                which is today's hold exactly.
      "gap"     the time/activity line after the greeting: quiet U(10,25)s, then
                an enter press and the typing time, with a think-gap allowed
                inside the typing phase. This is the bubble the burst may not
                have at all.
      "tail"    the operator's question and anything after it — an ordinary
                `bubble_pace` under `_WELCOME_PACE`. Usually a few seconds.

    An unknown role is paced as "tail": the conservative end (a few seconds, no
    long dark gap), because this is a live send path and the alternative to a
    sane fallback is a fan staring at nothing over a typo.

    ⚠️ `Pace.total_s` is still the ONLY number that moves a clock (see this
    module's INVARIANT). Quiet shrinks first so no hold exceeds `_TOTAL_CEIL_S`;
    the worst default single hold is 25 + 1.2 + 60 = 86.2s, and the clamped worst
    is 105s — both under `rhythm.INLINE_MAX_S`."""
    typing_s = max(0.0, float(typing_s or 0.0))

    if role == ROLE_GIF:
        total = min(rng.uniform(*_WELCOME_GIF_S), _TOTAL_CEIL_S)
        return Pace(total_s=total, quiet_s=total, added_s=total - typing_s)

    if role == ROLE_OPENER:
        # No draw at all without an image — the off-by-shape path stays byte-clean.
        quiet = (_welcome_quiet(rng, open_quiet, _WELCOME_OPEN_QUIET_S)
                 if has_image else 0.0)
        quiet = min(quiet, max(0.0, _TOTAL_CEIL_S - typing_s))
        return Pace(total_s=quiet + typing_s, quiet_s=quiet, added_s=quiet)

    if role == ROLE_GAP:
        quiet = _welcome_quiet(rng, gap_quiet, _WELCOME_GAP_QUIET_S)
        enter = rng.uniform(*_ENTER_S)
        typing_phase = typing_s + enter
        quiet = min(quiet, max(0.0, _TOTAL_CEIL_S - typing_phase))
        total = quiet + typing_phase
        think_at, think_for = _think_gap(typing_phase, rng, _WELCOME_PACE)
        return Pace(total_s=total, quiet_s=quiet, think_at_s=think_at,
                    think_for_s=think_for, added_s=total - typing_s)

    return bubble_pace(typing_s, text, rng, _WELCOME_PACE)
