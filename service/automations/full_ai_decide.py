from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Literal

Route = Literal["chat", "sext", "sell_now", "tease", "make_right", "ai_dare", "no_send"]

Arm = Literal["treatment", "holdout"]

HOLDOUT_PCT = 20
# Re-salting or moving HOLDOUT_PCT reshuffles Arms: any change needs a new SALT_VER.
SALT_VER = 1
_ARM_SALT = "full_ai_chat:arm:v1"

_FIRST: tuple[tuple[str, Route], ...] = (
    ("promo", "no_send"), ("says_under_18", "no_send"), ("complains_now", "make_right"),
    ("asks_if_ai", "ai_dare"), ("stop", "chat"))


@dataclass(frozen=True)
class Facts:
    fired: frozenset[str]
    intensity: float
    pending_offer: bool
    pending_tease: bool
    jev_ok: bool
    sell_on: bool = True
    sext_on: bool = True
    open_offer: bool = False
    draft_on: bool = False
    scene: bool = False
    chat_tease: bool = False
    offer_details: bool = False


@dataclass(frozen=True)
class Decision:
    route: Route
    heat: int
    row: str
    fired: frozenset[str]
    dropped: tuple[str, ...] = ()


def heat_of(intensity: float) -> int:
    return min(4, max(0, math.floor(intensity + 0.5)) + 1)


def decide_turn(facts: Facts) -> Decision:
    f = facts.fired
    if not facts.jev_ok:  # never a "no": an outage mutes no Fan
        return Decision("chat", 1, "jev_failed", f)
    heat = heat_of(facts.intensity)
    for q, route in _FIRST:
        if q in f:
            return Decision(route, heat, q, f)
    accept = "says_yes_to_offer" in f and (facts.pending_offer or facts.pending_tease)
    haggle = "counter_offer" in f and (facts.open_offer or facts.pending_tease)
    yields = facts.sell_on and (accept or (facts.draft_on and haggle))
    if facts.offer_details and "asks_offer_details" in f and not yields:
        return Decision("chat", heat, "offer_details", f)
    sell = "wants_content" in f or accept or facts.pending_tease
    scene_on = facts.scene and "scene_on" in f
    scene_offer = facts.scene and "scene_offer" in f and ("sexual_now" in f or scene_on)
    sext_row = "sexual_now" if "sexual_now" in f or not scene_on else "scene_on"
    flagged = (("haggle", "counter_offer", "sell_now", facts.sell_on, haggle, "sell_off"),
               ("sell", None, "sell_now", facts.sell_on, bool(sell), "sell_off"),
               ("tease_price", None, "tease", facts.sell_on, "price" in f, "tease_off"),
               ("offer_moment", "offer_moment", "sell_now", facts.sell_on, "offer_moment" in f, None),
               ("scene_offer", None, "sell_now", facts.sell_on, scene_offer, None),
               (sext_row, None, "sext", facts.sext_on, "sexual_now" in f or scene_on, "sext_off"),
               ("chat_tease", None, "sell_now", facts.sell_on, facts.chat_tease and "chat_tease" in f, None))
    dropped: list[str] = []
    end = "otherwise"
    for row, draft, route, on, match, off_row in flagged:
        if draft and draft in f and not facts.draft_on:
            dropped.append(draft)
            continue
        if match and on:
            return Decision(route, heat, row, f, tuple(dropped))
        if match:
            end = off_row if end == "otherwise" and off_row else end
            dropped.append(row)
    return Decision("chat", heat, end, f, tuple(dropped))


def arm_of(account_id: str, fan_id: int) -> Arm:
    raw = f"{_ARM_SALT}:{account_id}:{int(fan_id)}"
    bucket = int(hashlib.sha256(raw.encode()).hexdigest(), 16) % 100
    return "holdout" if bucket < HOLDOUT_PCT else "treatment"
