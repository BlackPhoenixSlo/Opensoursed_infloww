"""automations/full_ai_decide.py — Full AI Chat's Route table, pure.

`decide_turn(facts)` maps the Router's answers (the fired set and the
`intensity` Score, `_router_jev`) and the Pending tease to a Route, first
match, holding no rule of its own beyond them (ADR-0032): no counter, window,
cap, stamp, regex or earlier row. Stdlib plus `_router_jev`'s constants only
(pinned by test_full_ai_decide.py), so shadow, replay, test and live share one
table. The rows, in order (D42-D44, Opus a-c, R9, 03b ticket 47):

  promo -> no_send · says_under_18 -> no_send · complains_now -> make_right ·
  asks_if_ai -> ai_dare · stop -> chat (no sell, no hook) ·
  haggle: counter_offer (DRAFT) with an open Offer or a Pending tease -> sell_now ·
  sell: wants_content, says_yes_to_offer with a Pending offer or Pending
  tease, or a Pending tease -> sell_now ·
  tease_price (price) / tease_decline (declines_buying, price not) -> tease ·
  offer_moment (DRAFT) -> sell_now ·
  sexual_now -> sext · otherwise -> chat.

Route flags (R10): an off flag drops its rows (sell flag: haggle, sell,
tease_*, offer_moment; sext flag: sexual_now) and the walk goes on, so a later
row still matches (wants_content + sexual_now with selling off is sext). The
Decision records the dropped rows in `dropped`. A walk that reaches
`otherwise` with a row dropped names the first naming drop: sell_off (haggle
or sell), tease_off (a tease row), sext_off; a dropped offer_moment names none
(he asked for nothing, so no sell-off line). Shadow passes every flag on, so
its table is unchanged. A Jev failure is chat at Heat 1 (row jev_failed),
never a no_send. `gif_fits` is never read.

DRAFT gate (ticket 47): counter_offer and offer_moment count only with
`draft_on` (test Mode and config `draft_questions`; Shadow and live pass
false whatever the config says). A DRAFT id that fired and did not count is
dropped by its id at its row's place, and routing goes on as without it.
The fired set carries them once the Router gives them a threshold (phase B).

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
    open_offer: bool = False    # a priced Offer with no outcome (test fold, 03b)
    draft_on: bool = False      # DRAFT ids count: test Mode and config draft_questions


@dataclass(frozen=True)
class Decision:
    route: Route
    heat: int                   # 1..4: his level + 1, at most 4
    row: str                    # the table row that matched
    fired: frozenset[str]
    dropped: tuple[str, ...] = ()   # the rows an off flag removed, in walk order (R10)


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
    sell = "wants_content" in f or ("says_yes_to_offer" in f and facts.pending_offer) or facts.pending_tease
    tease = "tease_price" if "price" in f else "tease_decline" if "declines_buying" in f else ""
    haggle = "counter_offer" in f and (facts.open_offer or facts.pending_tease)
    # (row, its DRAFT id, Route, its flag, matched, the chat row this names as the first
    # naming drop; None names nothing)
    flagged = (("haggle", "counter_offer", "sell_now", facts.sell_on, haggle, "sell_off"),
               ("sell", None, "sell_now", facts.sell_on, bool(sell), "sell_off"),
               (tease, None, "tease", facts.sell_on, bool(tease), "tease_off"),
               ("offer_moment", "offer_moment", "sell_now", facts.sell_on, "offer_moment" in f, None),
               ("sexual_now", None, "sext", facts.sext_on, "sexual_now" in f, "sext_off"))
    dropped: list[str] = []
    end = "otherwise"
    for row, draft, route, on, match, off_row in flagged:
        if draft and draft in f and not facts.draft_on:
            # ASSUMPTION: a DRAFT id gated off is recorded under its question id
            # (`counter_offer`, the spec's API case), a row the sell flag drops under
            # its row name (`haggle`); offer_moment is both names, told apart by
            # draft_on on the row. Overturned if the owner wants a separate field.
            dropped.append(draft)       # fired, did not count
            continue
        if match and on:
            return Decision(route, heat, row, f, tuple(dropped))
        if match:
            end = off_row if end == "otherwise" and off_row else end
            dropped.append(row)
    return Decision("chat", heat, end, f, tuple(dropped))


def arm_of(account_id: str, fan_id: int) -> Arm:
    """The Fan's Arm on Creator `account_id`: sha256 over the salt, the account
    and the Fan (precedent: the buyer-list cleanup token), holdout below
    `HOLDOUT_PCT` of 100, else treatment."""
    raw = f"{_ARM_SALT}:{account_id}:{int(fan_id)}"
    bucket = int(hashlib.sha256(raw.encode()).hexdigest(), 16) % 100
    return "holdout" if bucket < HOLDOUT_PCT else "treatment"
