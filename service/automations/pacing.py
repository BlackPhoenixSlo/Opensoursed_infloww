from __future__ import annotations

from dataclasses import dataclass
from random import Random

from ._common import has_emoji
from .rhythm import INLINE_MAX_S as _INLINE_MAX_S

_ENTER_S = (0.4, 1.2)
_EMOJI_S = (2.0, 6.0)
_EMOJI_RATE_NOTE = 0.174

_DRIFT_MU, _DRIFT_SIGMA = 3.8, 1.1

_THINK_MIN_TYPING_S = 6.0
_THINK_S = (5.0, 10.0)
_THINK_MAX_SHARE = 0.6



@dataclass(frozen=True)
class PaceConfig:
    enabled: bool = False
    drift_pct: float = 30.0
    drift_cap_s: float = 90.0
    think_gaps: bool = True


# The 120 s bubble window bounds created_at gaps (hold + send round-trip, twice on a 400 retry); past it bubbles stop reading as one reply.
_TOTAL_CEIL_S = _INLINE_MAX_S - 15.0

@dataclass(frozen=True)
class Pace:
    total_s: float
    quiet_s: float = 0.0
    think_at_s: float = 0.0
    think_for_s: float = 0.0
    added_s: float = 0.0
    drifted: bool = False


def _think_gap(typing_phase: float, rng: Random, cfg: PaceConfig) -> tuple[float, float]:
    if not cfg.think_gaps or typing_phase < _THINK_MIN_TYPING_S:
        return 0.0, 0.0
    want = rng.uniform(*_THINK_S)
    think_for = min(want, typing_phase * _THINK_MAX_SHARE)
    span = typing_phase - think_for
    think_at = rng.uniform(span * 0.25, span * 0.75) if span > 0 else 0.0
    return think_at, think_for


def bubble_pace(typing_s: float, text: str, rng: Random,
                cfg: PaceConfig | None = None) -> Pace:
    typing_s = max(0.0, float(typing_s or 0.0))
    if cfg is None or not cfg.enabled:
        return Pace(total_s=typing_s)

    enter = rng.uniform(*_ENTER_S)
    emoji = rng.uniform(*_EMOJI_S) if has_emoji(text) else 0.0

    drift = 0.0
    cap = min(max(0.0, float(cfg.drift_cap_s)), _TOTAL_CEIL_S)
    # Bound the drift by what is left under the total ceiling: a long bubble plus garnish plus a full drift overshoots INLINE_MAX_S.
    cap = min(cap, max(0.0, _TOTAL_CEIL_S - (typing_s + enter + emoji)))
    # Drawn unconditionally so changing the rate does not re-roll every later bubble.
    roll = rng.random()
    if cap > 0 and roll < max(0.0, min(100.0, float(cfg.drift_pct))) / 100.0:
        drift = min(rng.lognormvariate(_DRIFT_MU, _DRIFT_SIGMA), cap)

    quiet = emoji + drift
    typing_phase = typing_s + enter
    total = quiet + typing_phase

    think_at, think_for = _think_gap(typing_phase, rng, cfg)

    return Pace(total_s=total, quiet_s=quiet, think_at_s=think_at,
                think_for_s=think_for, added_s=total - typing_s,
                drifted=drift > 0)


# These numbers are drawn, not measured (the table is established-thread reply gaps); override per rule with pace_open_quiet_s/pace_gap_quiet_s.
_WELCOME_PACE = PaceConfig(enabled=True, drift_pct=35.0, drift_cap_s=20.0,
                           think_gaps=True)
_WELCOME_GIF_S = (2.0, 6.0)
_WELCOME_OPEN_QUIET_S = (6.0, 18.0)
_WELCOME_GAP_QUIET_S = (10.0, 25.0)
WELCOME_QUIET_MAX_S = 45.0


def _welcome_quiet(rng: Random, override: object,
                   default: tuple[float, float]) -> float:
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


# This module owns the role names: a typo in the sender silently degrades that role to bubble_pace.
ROLE_OPENER = "opener"
ROLE_GAP = "gap"
ROLE_TAIL = "tail"
ROLE_GIF = "gif"
WELCOME_ROLES = (ROLE_OPENER, ROLE_GAP, ROLE_TAIL, ROLE_GIF)


def welcome_burst_pace(*, role: str, has_image: bool,
                       typing_s: float, text: str, rng: Random,
                       open_quiet: tuple[float, float] | None = None,
                       gap_quiet: tuple[float, float] | None = None) -> Pace:
    typing_s = max(0.0, float(typing_s or 0.0))

    if role == ROLE_GIF:
        total = min(rng.uniform(*_WELCOME_GIF_S), _TOTAL_CEIL_S)
        return Pace(total_s=total, quiet_s=total, added_s=total - typing_s)

    if role == ROLE_OPENER:
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
