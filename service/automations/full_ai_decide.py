"""automations/full_ai_decide.py — Full AI Chat's Route table, pure.

`decide_turn(facts)` maps the Router's answers (the fired set and the
`intensity` Score, `_router_jev`) and the Pending tease to a Route, first
match, holding no rule of its own beyond them (ADR-0032): no counter, window,
cap, stamp, regex or earlier row. Stdlib plus `_router_jev`'s constants only
(pinned by test_full_ai_decide.py), so shadow, replay, test and live share one
table. The rows, in order (D42-D44, Opus a-c, R9):

  promo -> no_send · says_under_18 -> no_send · complains_now -> make_right ·
  asks_if_ai -> ai_dare · stop -> chat (no sell, no hook) ·
  sell: wants_content, says_yes_to_offer with a Pending offer or Pending
  tease, or a Pending tease -> sell_now ·
  tease_price (price) / tease_decline (declines_buying, price not) -> tease ·
  sexual_now -> sext · otherwise -> chat.

The sell flag turns rows sell and tease_* into chat (rows sell_off,
tease_off), the sext flag row sexual_now (row sext_off). A Jev failure is
chat at Heat 1 (row jev_failed), never a no_send. `gif_fits` is never read.

`arm_of(account_id, fan_id)` is the Fan's Arm, a pure salted hash (ADR-0035):
every Decision row carries it with `SALT_VER`; Shadow writes no Enrolment.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Literal

Route = Literal["chat", "sext", "sell_now", "tease", "make_right", "ai_dare", "no_send"]

Arm = Literal["treatment", "holdout"]

# The Arm split (ADR-0035): re-salting or moving the percentage reshuffles
# Arms, so any change needs a new SALT_VER.
# ASSUMPTION: the salt is a code constant, safe because it is no secret (spec
# › Further Notes). Overturned if the owner wants it out of the public tree.
HOLDOUT_PCT = 20
SALT_VER = 1
_ARM_SALT = "full_ai_chat:arm:v1"

# Rows 1-5: (question, Route), first match; no flag touches them.
_FIRST: tuple[tuple[str, Route], ...] = (
    ("promo", "no_send"), ("says_under_18", "no_send"), ("complains_now", "make_right"),
    ("asks_if_ai", "ai_dare"), ("stop", "chat"))


@dataclass(frozen=True)
class Facts:
    fired: frozenset[str]       # the Router question ids at or above threshold
    intensity: float            # his `intensity` Score, 0..4
    pending_offer: bool         # a Pending offer is set
    pending_tease: bool         # the Turn after a sent tease (always false in Shadow)
    jev_ok: bool                # Jev answered
    sell_on: bool = True        # route flags (all on in Shadow)
    sext_on: bool = True


@dataclass(frozen=True)
class Decision:
    route: Route
    heat: int                   # 1..4: his level + 1, at most 4
    row: str                    # the table row that matched
    fired: frozenset[str]


def heat_of(intensity: float) -> int:
    """His level plus one, at most 4 (D44): his level is his `intensity` Score
    rounded to the nearest level, a tie up (Score 0.5 -> level 1 -> Heat 2;
    2.5 -> 3 -> 4), so Heat is 1..4 and never below him.
    ASSUMPTION: Heat reads the Score, not its level probabilities. Overturned
    if Phase 03's Writers read Heat from the probabilities."""
    return min(4, max(0, math.floor(intensity + 0.5)) + 1)


def decide_turn(facts: Facts) -> Decision:
    """The Route for one Turn, first match over Jev's answers."""
    f = facts.fired
    if not facts.jev_ok:        # never a "no": an outage mutes no Fan
        return Decision("chat", 1, "jev_failed", f)
    heat = heat_of(facts.intensity)
    for q, route in _FIRST:
        if q in f:
            return Decision(route, heat, q, f)
    # The Pending tease is a named D32 exception (R9): state, not a Jev answer.
    if "wants_content" in f or ("says_yes_to_offer" in f and facts.pending_offer) or facts.pending_tease:
        return _gated(facts.sell_on, "sell_now", "sell", "sell_off", heat, f)
    if "price" in f or "declines_buying" in f:
        row = "tease_price" if "price" in f else "tease_decline"
        return _gated(facts.sell_on, "tease", row, "tease_off", heat, f)
    if "sexual_now" in f:
        return _gated(facts.sext_on, "sext", "sexual_now", "sext_off", heat, f)
    return Decision("chat", heat, "otherwise", f)


def _gated(on: bool, route: Route, row: str, off_row: str, heat: int, f: frozenset[str]) -> Decision:
    """A flagged row: its Route when the flag is on, else chat under `off_row`."""
    return Decision(route, heat, row, f) if on else Decision("chat", heat, off_row, f)


def arm_of(account_id: str, fan_id: int) -> Arm:
    """The Fan's Arm on Creator `account_id`: sha256 over the salt, the account
    and the Fan (precedent: the buyer-list cleanup token), holdout below
    `HOLDOUT_PCT` of 100, else treatment."""
    raw = f"{_ARM_SALT}:{account_id}:{int(fan_id)}"
    bucket = int(hashlib.sha256(raw.encode()).hexdigest(), 16) % 100
    return "holdout" if bucket < HOLDOUT_PCT else "treatment"
