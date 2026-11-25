#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import ast  # noqa: E402
from dataclasses import replace  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import get_args  # noqa: E402

from automations import wcfi_decide as d  # noqa: E402
from automations.wcfi_decide import Ask, ClosePpv, FanSnapshot, Skip, decide  # noqa: E402

OK = FanSnapshot(listed=False, mid_funnel=False, forced=False, his_turn=True,
                 handoff=False, has_fan_row=True, paused=False, muted_creator=False,
                 promo_spam=False, content_payer=False, gather_done=False,
                 fan_msg_n=3, max_fan_messages=10, closing_due=False)

ALL = [
    ({"listed": True}, Skip("listed")),
    ({"mid_funnel": True}, Skip("mid_funnel")),
    ({"his_turn": False}, Skip("not_turn")),
    ({"paused": True}, Skip("paused")),
    ({"muted_creator": True}, Skip("muted")),
    ({"promo_spam": True}, Skip("spam")),
    ({"content_payer": True}, Skip("spent")),
    ({"fan_msg_n": 10}, Skip("too_long")),
]


def case_one_row_per_reason() -> None:
    rows = [(kw, want) for kw, want in ALL] + [
        ({"fan_msg_n": 10, "closing_due": True}, ClosePpv()),
        ({"fan_msg_n": 50, "gather_done": True}, Ask()),
        ({"fan_msg_n": 9}, Ask()),
        ({}, Ask()),
    ]
    for kw, want in rows:
        got = decide(replace(OK, **kw))
        assert got == want, (kw, got, want)
    assert decide(replace(OK, promo_spam=True)).durable is False
    assert {r.reason for _, r in ALL if r.durable} == {"spent", "too_long"}


def case_precedence() -> None:
    tripped: dict = {}
    for kw, _ in ALL:
        tripped.update(kw)
    for kw, want in ALL:
        got = decide(replace(OK, **tripped))
        assert got == want, (sorted(tripped), got, want)
        for k in kw:
            tripped[k] = getattr(OK, k)
    assert decide(replace(OK, **tripped)) == Ask(), tripped


def case_forced_bypasses_only_soft_gates() -> None:
    hard = [({"listed": True}, "listed"), ({"his_turn": False}, "not_turn"),
            ({"paused": True}, "paused"), ({"muted_creator": True}, "muted")]
    for kw, reason in hard:
        assert decide(replace(OK, forced=True, **kw)) == Skip(reason), kw
    soft = [{"mid_funnel": True}, {"promo_spam": True}, {"content_payer": True},
            {"fan_msg_n": 10}, {"fan_msg_n": 10, "closing_due": True}]
    for kw in soft:
        assert decide(replace(OK, forced=True, **kw)) == Ask(), kw


def case_no_fan_row_skips_the_row_gates() -> None:
    for kw in ({"promo_spam": True}, {"content_payer": True}, {"fan_msg_n": 10}):
        assert decide(replace(OK, has_fan_row=False, **kw)) == Ask(), kw


def case_handoff_opens_the_turn_gate() -> None:
    assert decide(replace(OK, his_turn=False, handoff=True)) == Ask(handoff_admitted=True)
    assert decide(replace(OK, his_turn=False, handoff=True, listed=True)) == Skip("listed")
    assert decide(replace(OK, his_turn=False, handoff=True, paused=True)) == Skip("paused", True)


def case_handoff_admitted_per_reason() -> None:
    rows = [
        ({"listed": True}, "listed", False),
        ({"mid_funnel": True}, "mid_funnel", False),
        ({"paused": True}, "paused", True),
        ({"muted_creator": True}, "muted", True),
        ({"promo_spam": True}, "spam", True),
        ({"content_payer": True}, "spent", True),
        ({"fan_msg_n": 10}, "too_long", True),
        ({"fan_msg_n": 10, "closing_due": True}, ClosePpv, True),
        ({}, Ask, True),
        ({"forced": True, "mid_funnel": True}, Ask, True),
    ]
    for kw, want, adm in rows:
        v = decide(replace(OK, his_turn=False, handoff=True, **kw))
        assert (v.reason if isinstance(v, Skip) else type(v)) == want, (kw, v)
        assert v.handoff_admitted is adm, (kw, v)
    for kw, want in ALL:
        assert decide(replace(OK, **kw)).handoff_admitted is False, kw
    assert decide(replace(OK, his_turn=False)) == Skip("not_turn")


def case_stat_covers_every_reason() -> None:
    reasons = set(get_args(d.Reason))
    assert set(d.STAT) == reasons, set(d.STAT) ^ reasons
    assert d.DURABLE <= reasons
    assert {r.reason for _, r in ALL} == reasons
    assert set(d.STAT.values()) | {"turn_handoffs"} == set(d.COUNTERS)
    assert all(d.STAT[r] == "newly_skiplisted" for r in d.DURABLE)


def case_asked_topics() -> None:
    from types import SimpleNamespace as F
    rows = [
        (None, set()), ("", set()), ("[]", set()),
        ('["age", "job"]', {"age", "job"}), ('["age:2", "age:2"]', {"age:2"}),
        ("not json", set()), ("5", set()),
    ]
    for raw, want in rows:
        assert d.asked_topics(F(questions_asked=raw)) == want, (raw, want)


def case_msg_id_of() -> None:
    rows = [
        ({"id": 7, "text": "hi"}, 7), ({"success": True}, None),
        ({"id": 0}, 0), (None, None), ("ok", None),
    ]
    for result, want in rows:
        assert d.msg_id_of(result) == want, (result, d.msg_id_of(result))


def case_module_is_pure() -> None:
    tree = ast.parse(Path(d.__file__).read_text(encoding="utf-8"))
    mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert mods <= {"__future__", "dataclasses", "json", "typing"}, mods


_harness.run()
