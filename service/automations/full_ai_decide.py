"""automations/full_ai_decide.py — Full AI Chat's Route table, pure.

`decide_turn(facts)` maps the Router's answers (the fired set and the
`intensity` Score, `_router_jev`) and the Pending tease to a Route, first
match, holding no rule of its own beyond them (ADR-0032): no counter, window,
cap, stamp, regex or earlier row. Stdlib plus `_router_jev`'s constants only
(pinned by test_full_ai_decide.py), so shadow, replay, test and live share one
table. The rows, in order (D42-D44, Opus a-c, R9, 03b ticket 47):

  promo -> no_send · says_under_18 -> no_send · complains_now -> make_right ·
  asks_if_ai -> ai_dare · stop -> chat (no sell, no hook) ·
  offer_details (`asks_offer_details`, gate `offer_details`) -> chat, unless acceptance or a
  discount ask below can run ·
  haggle: counter_offer (DRAFT) with an open Offer or a Pending tease -> sell_now ·
  sell: wants_content, says_yes_to_offer with a Pending offer or Pending
  tease, or a Pending tease -> sell_now ·
  tease_price (price) -> tease ·
  offer_moment (DRAFT) -> sell_now ·
  scene_offer (sext scene) -> sell_now ·
  sexual_now, or scene_on (sext scene) -> sext ·
  chat_tease (Chat tease) -> sell_now · otherwise -> chat.

Route flags (R10): an off flag drops its rows (sell flag: haggle, sell,
tease_price, offer_moment; sext flag: sexual_now) and the walk goes on, so a later
row still matches (wants_content + sexual_now with selling off is sext). The
Decision records the dropped rows in `dropped`. A walk that reaches
`otherwise` with a row dropped names the first naming drop: sell_off (haggle
or sell), tease_off (tease_price), sext_off; a dropped offer_moment names none
(he asked for nothing, so no sell-off line). Shadow passes every flag on, so
its table is unchanged. A Jev failure is chat at Heat 1 (row jev_failed),
never a no_send. `gif_fits` and `declines_buying` are never read (owner 2026-11-15: "broke"
routes nothing in any Mode; the Writer may joke about it).

DRAFT gate (ticket 47): counter_offer and offer_moment count only with
`draft_on` (test or live Mode with `draft_questions` enabled; Shadow
always passes false). A DRAFT id that fired and did not count is
dropped by its id at its row's place, and routing goes on as without it.
Test Mode's fired set carries them (`fired(answers, mode)`, ticket 47 B2).

Sext scene (`scene`: test or live Mode and config `sext_scene`, owner 2026-11-14): the sext row
also matches on `scene_on` alone (row `scene_on`); row `scene_offer` -> sell_now needs
`scene_offer` and (`sexual_now` or `scene_on`), the sell flag, and a drop names nothing
(as offer_moment). Without `scene` both ids are ignored, not recorded: they are never
asked then (`_router_jev._questions(mode, scene)`), so the table is the old one.
ADR-0032 named exception (owner-ordered "some save states for few messages"): the saved
scene state (`full_ai_scene`) feeds Jev's state (`scene`, `purchases`) and the Writer's
stage/heat floor only; it never enters this table, which stays pure over Jev's answers.

Chat tease (`chat_tease`: test or live Mode and config `chat_tease`, owner 2026-11-14): row `chat_tease`
-> sell_now on Jev's `chat_tease`, the last flagged row (after sext), so an ask, haggle, tease,
offer_moment, scene_offer and any sext Turn win and it only ever replaces a chat row; the sell
flag drops it and the drop names nothing (as offer_moment). Without the flag the id is ignored,
not recorded: it is never asked then (`_router_jev._questions(..., tease)`).

Offer details (`offer_details`: test / live Mode, spec phase-01-full-ai-offer-details A): row
`offer_details` -> chat on Jev's `asks_offer_details`, after the five rows above and before haggle,
sell (the Pending tease included, ADR-0037), tease_price and the rest. It yields only to a row that
can run: acceptance (says_yes_to_offer with a Pending offer or tease) or an explicit discount ask
(counter_offer under `draft_on` with an open Offer or Pending tease), both with selling on. A
different item or a draft-off discount ask is kept out by the Noul's own "no" wording. Off (Shadow,
and every Mode until the Writer branch lands) the id is ignored, never the row.

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
    open_offer: bool = False    # a priced Offer with no outcome (test fold, 03b)
    draft_on: bool = False      # DRAFT ids count: test or live Mode with draft_questions
    scene: bool = False         # sext scene ids count: test or live Mode and config sext_scene
    chat_tease: bool = False    # `chat_tease` counts: test or live Mode and config chat_tease
    offer_details: bool = False  # `asks_offer_details` counts: test / live Mode (`full_ai_turn._route`)


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
    if not facts.jev_ok:        # never a "no": an outage mutes no Fan
        return Decision("chat", 1, "jev_failed", f)
    heat = heat_of(facts.intensity)
    for q, route in _FIRST:
        if q in f:
            return Decision(route, heat, q, f)
    accept = "says_yes_to_offer" in f and (facts.pending_offer or facts.pending_tease)
    haggle = "counter_offer" in f and (facts.open_offer or facts.pending_tease)
    # Offer details (ADR-0037): above the Pending tease; yields only to acceptance or a discount ask
    # that can run (selling on).
    yields = facts.sell_on and (accept or (facts.draft_on and haggle))
    if facts.offer_details and "asks_offer_details" in f and not yields:
        return Decision("chat", heat, "offer_details", f)
    # The Pending tease is a named D32 exception (R9): state, not a Jev answer.
    sell = "wants_content" in f or accept or facts.pending_tease
    scene_on = facts.scene and "scene_on" in f
    scene_offer = facts.scene and "scene_offer" in f and ("sexual_now" in f or scene_on)
    sext_row = "sexual_now" if "sexual_now" in f or not scene_on else "scene_on"
    # (row, its DRAFT id, Route, its flag, matched, the chat row this names as the first
    # naming drop; None names nothing)
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
