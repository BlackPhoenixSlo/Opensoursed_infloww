#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import automations.welcome_chatter_for_info as ofc  # noqa: E402
from automations.welcome_chatter_for_info import (  # noqa: E402
    _BREATHER_VARIANTS, _Candidate, _build_messages,
)
from db.models import Fan  # noqa: E402

_ASK = "YOUR GOAL THIS MESSAGE"
_ANSWER_HIM = "he just asked you something"
_BREATHER = "don't ask anything"

_RETIRE_ALL_BUT_TWO = {"name:2", "age:2", "location:2", "job:2", "hobbies"}


def _need(messages: list[dict]) -> str:
    return "\n".join(m["content"] for m in messages if m.get("role") == "system") \
        or "\n".join(m["content"] for m in messages)


def _candidate(fan_id: int, msgs: list[tuple[str, str]]) -> _Candidate:
    c = _Candidate(fan_id)
    c.messages = msgs
    c.last_dir = msgs[-1][0] if msgs else "in"
    c.last_body = msgs[-1][1] if msgs else ""
    return c


class _FixedRandom:
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
    f = Fan(account_id="acc", fan_id=1)
    c = _candidate(1, [
        ("out", "where u from?"), ("in", "texas"),
        ("out", "what do u do?"), ("in", "chef"),
        ("out", "a chef? bet u cook fire?"), ("in", "haha yeah"),
    ])
    with _FixedRandom(0.99):
        msgs, presented = _build_messages("persona", f, c, set())
    need = _need(msgs)
    assert _BREATHER in need and _ASK not in need, need
    assert presented == [], ("a breather marks no topic", presented)


async def case_no_two_breathers_back_to_back():
    f = Fan(account_id="acc", fan_id=2)
    c = _candidate(2, [
        ("in", "hey"), ("out", "heyy"), ("in", "hows ur day going"),
    ])
    with _FixedRandom(0.0):
        msgs, _ = _build_messages("persona", f, c, set())
    need = _need(msgs)
    assert _ASK in need and _BREATHER not in need, need


async def case_fan_question_gets_answered():
    f = Fan(account_id="acc", fan_id=3)
    c = _candidate(3, [
        ("out", "heyy"),
        ("in", "where are u from?"),
    ])
    with _FixedRandom(0.99):
        msgs, presented = _build_messages("persona", f, c, set())
    need = _need(msgs)
    assert _ANSWER_HIM in need and _ASK not in need, need
    assert presented == [], presented


async def case_low_effort_message_leans_breather():
    f = Fan(account_id="acc", fan_id=4)
    c = _candidate(4, [
        ("in", "hey"), ("out", "what do u do for work?"), ("in", "lol idk"),
    ])
    with _FixedRandom(0.45):
        msgs, _ = _build_messages("persona", f, c, set())
    need = _need(msgs)
    assert _BREATHER in need, ("low-effort should lean breather at 0.45", need)


async def case_taper_winds_down_as_gaps_empty():
    f = Fan(account_id="acc", fan_id=5)
    c = _candidate(5, [
        ("in", "i work as a chef downtown"),
        ("out", "oh nice what got u into cooking?"),
        ("in", "my mom taught me when i was a kid"),
    ])
    with _FixedRandom(0.4):
        many_gaps, _ = _build_messages("persona", f, c, set())
        few_gaps, _ = _build_messages("persona", f, c, _RETIRE_ALL_BUT_TWO)
    assert _ASK in _need(many_gaps), ("fresh profile should still ask", _need(many_gaps))
    assert _BREATHER in _need(few_gaps), ("winding-down profile should breather", _need(few_gaps))


async def case_breather_variants_vary():
    f = Fan(account_id="acc", fan_id=6)
    c = _candidate(6, [
        ("out", "where u from?"), ("in", "texas"),
        ("out", "what do u do?"), ("in", "chef"),
        ("out", "a chef? bet u cook fire?"), ("in", "haha yeah"),
    ])
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
