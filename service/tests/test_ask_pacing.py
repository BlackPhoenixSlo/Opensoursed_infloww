#!/usr/bin/env python3
"""
welcome_chatter_for_info — ask/breather PACING tests.

The ask-vs-breather decision in `_build_messages` is no longer a memoryless coin:
it reads the recent turn pattern (`_recent_ask_pattern`) and the fan's last message
so the bot never interrogates, never stalls, answers a question instead of volleying
one back, and winds down from interview to banter as the gap list empties.

These exercise `_build_messages` directly (it's pure prompt construction — no DB,
no network) and assert WHICH instruction block lands in the system prompt:

  case_three_asks_in_a_row_forces_breather   (#1) 3 asking turns → forced breather.
  case_no_two_breathers_back_to_back          (#1) last turn was a breather → force ask.
  case_fan_question_gets_answered             (#2) fan ended on '?' → answer, don't volley.
  case_low_effort_message_leans_breather      (#2) ≤3-word fan msg → lean breather.
  case_taper_winds_down_as_gaps_empty         (#3) fewer gaps → higher breather rate.
  case_breather_variants_vary                 (#4) breather wording rotates.

Run: ./venv/bin/python service/tests/test_ask_pacing.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import automations.welcome_chatter_for_info as ofc  # noqa: E402
from automations.welcome_chatter_for_info import (  # noqa: E402
    _BREATHER_VARIANTS, _Candidate, _build_messages,
)
from db.models import Fan  # noqa: E402

# Distinguishing fragments of each need_block branch.
_ASK = "YOUR GOAL THIS MESSAGE"
_ANSWER_HIM = "he just asked you something"
_BREATHER = "don't ask anything"

# asked-keys that fully retire a gap (so we can dial the remaining-gap count down).
_RETIRE_ALL_BUT_TWO = {"name:2", "age:2", "location:2", "job:2", "hobbies"}


def _need(messages: list[dict]) -> str:
    """The system-prompt text from a _build_messages result (where need_block lives)."""
    return "\n".join(m["content"] for m in messages if m.get("role") == "system") \
        or "\n".join(m["content"] for m in messages)


def _candidate(fan_id: int, msgs: list[tuple[str, str]]) -> _Candidate:
    c = _Candidate(fan_id)
    c.messages = msgs
    c.last_dir = msgs[-1][0] if msgs else "in"
    c.last_body = msgs[-1][1] if msgs else ""
    return c


class _FixedRandom:
    """Patch ofc.random.random to a constant for the dice branches; random.choice
    (used by the breather-variant pick) keeps working off the real module."""
    def __init__(self, value: float):
        self.value = value
        self._orig = None

    def __enter__(self):
        self._orig = ofc.random.random
        ofc.random.random = lambda: self.value
        return self

    def __exit__(self, *exc):
        ofc.random.random = self._orig


async def case_three_asks_in_a_row_forces_breather():
    """#1 — three consecutive bot turns that each ended on a question is an
    interrogation; the next turn is forced to a breather no matter the dice."""
    f = Fan(account_id="acc", fan_id=1)  # bare → plenty of gaps to ask
    c = _candidate(1, [
        ("out", "where u from?"), ("in", "texas"),
        ("out", "what do u do?"), ("in", "chef"),
        ("out", "a chef? bet u cook fire?"), ("in", "haha yeah"),
    ])
    # Even with the dice pinned to "ask" (0.99 ≥ any breather_p), the streak wins.
    with _FixedRandom(0.99):
        msgs, presented = _build_messages("persona", f, c, set())
    need = _need(msgs)
    assert _BREATHER in need and _ASK not in need, need
    assert presented == [], ("a breather marks no topic", presented)


async def case_no_two_breathers_back_to_back():
    """#1 — the previous bot turn didn't ask (a breather); a second breather in a
    row reads robotic, so this turn is forced to ASK even on a breather-leaning dice."""
    f = Fan(account_id="acc", fan_id=2)
    c = _candidate(2, [
        ("in", "hey"), ("out", "heyy"), ("in", "hows ur day going"),
    ])
    with _FixedRandom(0.0):  # 0.0 would normally force a breather; the rule overrides
        msgs, _ = _build_messages("persona", f, c, set())
    need = _need(msgs)
    assert _ASK in need and _BREATHER not in need, need


async def case_fan_question_gets_answered():
    """#2 — the fan's last message ends on a '?'; answer it, don't fire a question
    back the same turn. Beats the no-two-breathers rule (answering isn't a stall)."""
    f = Fan(account_id="acc", fan_id=3)
    c = _candidate(3, [
        ("out", "heyy"),               # last bot turn = breather (would force ask)…
        ("in", "where are u from?"),   # …but he asked → answer him instead
    ])
    with _FixedRandom(0.99):
        msgs, presented = _build_messages("persona", f, c, set())
    need = _need(msgs)
    assert _ANSWER_HIM in need and _ASK not in need, need
    assert presented == [], presented


async def case_low_effort_message_leans_breather():
    """#2 — a ≤3-word low-effort reply uses a breather-leaning threshold (0.6), not
    the base rate. random=0.45 → base dice (0.33) would ASK, low-effort path breathers."""
    f = Fan(account_id="acc", fan_id=4)  # bare Fan → many gaps → base breather_p=0.33
    c = _candidate(4, [
        ("in", "hey"), ("out", "what do u do for work?"), ("in", "lol idk"),
    ])
    with _FixedRandom(0.45):
        msgs, _ = _build_messages("persona", f, c, set())
    need = _need(msgs)
    assert _BREATHER in need, ("low-effort should lean breather at 0.45", need)


async def case_taper_winds_down_as_gaps_empty():
    """#3 — with the dice fixed at 0.4, a near-empty profile (≤2 gaps, breather_p
    0.55) breathers while a fresh profile (>2 gaps, breather_p 0.33) still asks.
    Same context, only the remaining-gap count differs."""
    f = Fan(account_id="acc", fan_id=5)
    # last bot turn ASKED (no forced ask), fan gave a normal statement (not a Q,
    # not low-effort) → the decision falls through to the base dice.
    c = _candidate(5, [
        ("in", "i work as a chef downtown"),
        ("out", "oh nice what got u into cooking?"),
        ("in", "my mom taught me when i was a kid"),
    ])
    with _FixedRandom(0.4):
        many_gaps, _ = _build_messages("persona", f, c, set())        # >2 gaps
        few_gaps, _ = _build_messages("persona", f, c, _RETIRE_ALL_BUT_TWO)  # ≤2 gaps
    assert _ASK in _need(many_gaps), ("fresh profile should still ask", _need(many_gaps))
    assert _BREATHER in _need(few_gaps), ("winding-down profile should breather", _need(few_gaps))


async def case_breather_variants_vary():
    """#4 — a forced breather rotates its wording (no single canned 'don't ask'
    line), so no-question turns don't all look identical either."""
    f = Fan(account_id="acc", fan_id=6)
    c = _candidate(6, [
        ("out", "where u from?"), ("in", "texas"),
        ("out", "what do u do?"), ("in", "chef"),
        ("out", "a chef? bet u cook fire?"), ("in", "haha yeah"),
    ])  # 3-ask streak → always a breather; only the WORDING varies (random.choice)
    seen = set()
    for _ in range(80):
        msgs, _p = _build_messages("persona", f, c, set())
        need = _need(msgs)
        hit = [v for v in _BREATHER_VARIANTS if v in need]
        assert len(hit) == 1, ("exactly one breather variant per reply", hit)
        seen.add(hit[0])
    assert len(seen) >= 2, ("breather wording should vary over 80 runs", len(seen))


_harness.run(
    case_three_asks_in_a_row_forces_breather,
    case_no_two_breathers_back_to_back,
    case_fan_question_gets_answered,
    case_low_effort_message_leans_breather,
    case_taper_winds_down_as_gaps_empty,
    case_breather_variants_vary,
)
