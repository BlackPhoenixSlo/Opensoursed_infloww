#!/usr/bin/env python3
"""test_full_ai_offer_details_route — ticket 01 (A): the Router's `asks_offer_details` Noul and Route
row `offer_details` (spec docs/spec/phase-01-full-ai-offer-details.md › A), pure, plain assert.

  case_existing_rows_unchanged       gate on, Noul absent: every existing row keeps its Decision
  case_protected_rows_win            each `_FIRST` row + the Noul: the `_FIRST` row wins
  case_pending_tease_is_answered     Noul + Pending tease -> chat, row offer_details
  case_yields_only_to_a_row_that_runs  + says_yes with a Pending offer / tease -> sell; + counter_offer
                                     (draft on) with an Open Offer / Pending tease -> haggle; sell off ->
                                     offer_details; counter_offer with draft off -> offer_details
  case_beats_content_price_sext      + wants_content / price / sexual_now -> offer_details
  case_gate_off_never_the_row        `offer_details` False (Shadow, A alone): every fired set decides as
                                     without the Noul, never the row
  case_pre_offer_price_ask           price, Noul absent, no Offer -> tease_price ("how much for a vid?")
  case_narrow_row                    banter, fresh ask, acceptance, haggle, stop, complaint keep routes
  case_questions_by_mode             test + live ask it, Shadow never; `fired(.., "shadow")` never
                                     yields it; threshold 0.6, its measurement noted at its definition;
                                     Shadow digest pinned, test digest moves
  case_wording                       NEW-165 wording, scoped to `fan_new_messages`; logged in docs/prompts

Run: ./venv/bin/python service/tests/test_full_ai_offer_details_route.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from itertools import product  # noqa: E402
from pathlib import Path  # noqa: E402

from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_decide as fd  # noqa: E402

Q = "asks_offer_details"
ROOT = Path(__file__).resolve().parents[2]
# Shadow's `question_version()` (spec A: unchanged by this ticket).
SHADOW_VERSION = "14f5d4f6222f"
FIRST = ("promo", "says_under_18", "complains_now", "asks_if_ai", "stop")
FIRST_ROUTE = {"promo": "no_send", "says_under_18": "no_send", "complains_now": "make_right",
               "asks_if_ai": "ai_dare", "stop": "chat"}
# The full-Mode facts a test / live Turn passes, plus the gate C turns on.
ON = {"offer_details": True}


def _facts(fired=(), *, intensity=1.0, pending_offer=False, pending_tease=False, jev_ok=True, **flags):
    return fd.Facts(fired=frozenset(fired), intensity=intensity, pending_offer=pending_offer,
                    pending_tease=pending_tease, jev_ok=jev_ok, **flags)


def _d(fired=(), **kw) -> tuple[str, str]:
    d = fd.decide_turn(_facts(fired, **kw))
    return d.route, d.row


# Every existing row, with its facts and the Decision it has on the base commit (the module
# docstring's order): (fired, facts, (route, row)).
EXISTING = (
    (("promo",), {}, ("no_send", "promo")),
    (("says_under_18",), {}, ("no_send", "says_under_18")),
    (("complains_now",), {}, ("make_right", "complains_now")),
    (("asks_if_ai",), {}, ("ai_dare", "asks_if_ai")),
    (("stop",), {}, ("chat", "stop")),
    (("counter_offer",), {"draft_on": True, "open_offer": True}, ("sell_now", "haggle")),
    (("counter_offer",), {"draft_on": True, "pending_tease": True}, ("sell_now", "haggle")),
    (("wants_content",), {}, ("sell_now", "sell")),
    (("says_yes_to_offer",), {"pending_offer": True}, ("sell_now", "sell")),
    ((), {"pending_tease": True}, ("sell_now", "sell")),
    (("price",), {}, ("tease", "tease_price")),
    (("offer_moment",), {"draft_on": True}, ("sell_now", "offer_moment")),
    (("scene_offer", "sexual_now"), {"scene": True}, ("sell_now", "scene_offer")),
    (("sexual_now",), {}, ("sext", "sexual_now")),
    (("scene_on",), {"scene": True}, ("sext", "scene_on")),
    (("chat_tease",), {"chat_tease": True}, ("sell_now", "chat_tease")),
    ((), {}, ("chat", "otherwise")),
    (("wants_content",), {"sell_on": False}, ("chat", "sell_off")),
    (("price",), {"sell_on": False}, ("chat", "tease_off")),
    (("sexual_now",), {"sext_on": False}, ("chat", "sext_off")),
)


def case_existing_rows_unchanged():
    for fired, kw, want in EXISTING:
        for gate in (True, False):
            assert _d(fired, offer_details=gate, **kw) == want, (fired, kw, gate)
    # jev_failed: chat, Heat 1, whatever fired.
    for gate in (True, False):
        d = fd.decide_turn(_facts({Q, "promo"}, intensity=3.0, jev_ok=False, offer_details=gate))
        assert (d.route, d.heat, d.row) == ("chat", 1, "jev_failed"), (gate, d)


def case_protected_rows_win():
    for q in FIRST:
        for kw in ({}, {"pending_tease": True}, {"open_offer": True, "draft_on": True}):
            assert _d({q, Q}, **ON, **kw) == (FIRST_ROUTE[q], q), (q, kw)


def case_pending_tease_is_answered():
    d = fd.decide_turn(_facts({Q}, intensity=2.0, pending_tease=True, **ON))
    assert (d.route, d.heat, d.row, d.fired, d.dropped) == ("chat", 3, "offer_details", frozenset({Q}), ()), d
    # Without the Noul the Pending tease still sells.
    assert _d((), pending_tease=True, **ON) == ("sell_now", "sell")


def case_yields_only_to_a_row_that_runs():
    rows = [
        # Acceptance: says_yes_to_offer with a Pending offer or tease.
        (({Q, "says_yes_to_offer"}, {"pending_offer": True}), ("sell_now", "sell")),
        (({Q, "says_yes_to_offer"}, {"pending_tease": True}), ("sell_now", "sell")),
        # A yes with nothing pending is no acceptance: the question is answered.
        (({Q, "says_yes_to_offer"}, {}), ("chat", "offer_details")),
        # Explicit discount ask: counter_offer under draft questions with an Open Offer or tease.
        (({Q, "counter_offer"}, {"draft_on": True, "open_offer": True}), ("sell_now", "haggle")),
        (({Q, "counter_offer"}, {"draft_on": True, "pending_tease": True}), ("sell_now", "haggle")),
        # Draft questions off, or no Offer to haggle over: answered (the Noul's "no" carries it).
        (({Q, "counter_offer"}, {"draft_on": False, "open_offer": True}), ("chat", "offer_details")),
        (({Q, "counter_offer"}, {"draft_on": True}), ("chat", "offer_details")),
        # Selling off: neither row can run, so the question is answered.
        (({Q, "says_yes_to_offer"}, {"pending_offer": True, "sell_on": False}), ("chat", "offer_details")),
        (({Q, "says_yes_to_offer"}, {"pending_tease": True, "sell_on": False}), ("chat", "offer_details")),
        (({Q, "counter_offer"}, {"draft_on": True, "open_offer": True, "sell_on": False}),
         ("chat", "offer_details")),
        (({Q}, {"pending_tease": True, "sell_on": False}), ("chat", "offer_details")),
    ]
    for (fired, kw), want in rows:
        assert _d(fired, **ON, **kw) == want, (sorted(fired), kw, _d(fired, **ON, **kw))


def case_beats_content_price_sext():
    for other in ("wants_content", "price", "sexual_now", "offer_moment", "chat_tease", "scene_on"):
        for kw in ({}, {"open_offer": True}, {"pending_offer": True},
                   {"draft_on": True, "scene": True, "chat_tease": True}):
            assert _d({Q, other}, **ON, **kw) == ("chat", "offer_details"), (other, kw)
    assert _d({Q}, **ON) == ("chat", "offer_details")
    assert _d({Q, "wants_content", "price", "sexual_now"}, open_offer=True, **ON) == ("chat", "offer_details")


def case_gate_off_never_the_row():
    ids = ("wants_content", "says_yes_to_offer", "price", "sexual_now", "counter_offer", "offer_moment",
           "scene_on", "scene_offer", "chat_tease", "stop")
    for bits in product((False, True), repeat=len(ids) + 9):
        base = frozenset(q for q, b in zip(ids, bits) if b)
        po, pt, oo, sell_on, sext_on, draft_on, scene, tease, ok = bits[len(ids):]
        kw = dict(pending_offer=po, pending_tease=pt, open_offer=oo, sell_on=sell_on, sext_on=sext_on,
                  draft_on=draft_on, scene=scene, chat_tease=tease, jev_ok=ok)
        d = fd.decide_turn(_facts(base | {Q}, **kw))     # `offer_details` defaults off
        assert d.row != "offer_details", (sorted(base), kw)
        without = fd.decide_turn(_facts(base, **kw))
        assert (d.route, d.heat, d.row, d.dropped) == (without.route, without.heat, without.row,
                                                       without.dropped), (sorted(base), kw, d, without)
    assert fd.Facts.__dataclass_fields__["offer_details"].default is False


def case_pre_offer_price_ask():
    """"how much for a vid?" with nothing offered: `price` fires, the Noul's "no" keeps it absent."""
    assert _d({"price"}, **ON) == ("tease", "tease_price")
    assert _d({"price", "wants_content"}, **ON) == ("sell_now", "sell")


def case_narrow_row():
    rows = [
        ((), {}, ("chat", "otherwise")),                                           # banter
        (("wants_content",), {"open_offer": True}, ("sell_now", "sell")),         # fresh content ask
        (("says_yes_to_offer",), {"pending_offer": True}, ("sell_now", "sell")),  # acceptance
        (("counter_offer",), {"draft_on": True, "open_offer": True}, ("sell_now", "haggle")),
        (("stop",), {"pending_tease": True}, ("chat", "stop")),
        (("complains_now",), {"open_offer": True}, ("make_right", "complains_now")),
    ]
    for fired, kw, want in rows:
        assert _d(fired, **ON, **kw) == want, (fired, kw)


def case_questions_by_mode():
    for mode in ("test", "live"):
        for scene, tease in product((False, True), repeat=2):
            q = rj._questions(mode, scene=scene, tease=tease)
            assert Q in q and type(q[Q]).__name__ == "Noul", (mode, scene, tease)
            assert q[Q].instructions == rj.TEST_NOULS[Q]["instructions"]
    for scene, tease in product((False, True), repeat=2):
        assert Q not in rj._questions("shadow", scene=scene, tease=tease)
    assert Q not in rj.DRAFT | rj.SCENE | rj.TEASE
    assert rj.TEST_THRESHOLDS[Q] == 0.6
    answers = {**dict.fromkeys(rj.THRESHOLDS, 0.0), Q: 0.6}
    assert Q in rj.fired(answers, "test") and Q in rj.fired(answers, "live")
    assert Q not in rj.fired({**answers, Q: 0.59}, "test")
    assert Q not in rj.fired({**answers, Q: 1.0}, "shadow")
    # The 0.6 is stated as measured (the F replay probe) where it is set.
    src = (ROOT / "service" / "automations" / "_router_jev.py").read_text(encoding="utf-8")
    head = src[:src.index("TEST_THRESHOLDS: dict[str, float] =")]
    note = head[head.rindex("\n\n"):]
    assert Q in note and "measured 2026-11-17" in note, note
    # Shadow's digest stays; test / live move with the Noul.
    assert rj.question_version() == rj.question_version("shadow") == rj.QUESTION_VERSION == SHADOW_VERSION
    base = rj.question_version("test")
    real = rj.TEST_NOULS
    rj.TEST_NOULS = {k: v for k, v in real.items() if k != Q}
    try:
        assert rj.question_version("test") != base
        assert rj.question_version() == SHADOW_VERSION
    finally:
        rj.TEST_NOULS = real
    assert rj.question_version("live") == base


# The shipped wording (probed on the F replay 2026-11-17; the spec's first draft was replaced), logged as NEW-165.
INSTRUCTIONS = ("In `fan_new_messages`, is a factual question about content she already offered or sent "
                "him the only thing the fan wants: what is in it, whether it is a photo or a video, how "
                "many, how long, how much it was, which one, or whether it is the same as before?")
YES = ("He only asks what is in something she sent or offered, its type, count, length or price, "
       "which one she means, or whether it matches an earlier one, even when he is short or annoyed")
NO = ("He asks for something new, different, more or else, even when he also asks about the one "
      "already offered; asks the price of something she has not offered yet; asks for a lower "
      "price or a deal; says yes, buys or says no; only reacts with a short word such as ok, nice "
      "or lol; or chats, flirts or sexts without asking about something already offered")


def case_wording():
    got = rj.TEST_NOULS[Q]
    assert got["instructions"] == INSTRUCTIONS, got["instructions"]
    assert got["criteria"] == {"true": YES, "false": NO}, got["criteria"]
    assert "thread" not in got["instructions"] and "`thread`" not in YES + NO
    readme = (ROOT / "docs" / "prompts" / "README.md").read_text(encoding="utf-8")
    assert "| NEW-165 |" in readme and Q in readme.split("| NEW-165 |", 1)[1].split("\n", 1)[0]
    doc = (ROOT / "docs" / "prompts" / "new" / "current-repo.md").read_text(encoding="utf-8")
    assert "### NEW-165" in doc
    entry = doc.split("### NEW-165", 1)[1].split("\n### ", 1)[0]
    for text in (INSTRUCTIONS, YES, NO):
        assert text in entry, text


if __name__ == "__main__":
    _harness.run()
