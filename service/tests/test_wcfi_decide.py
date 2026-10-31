#!/usr/bin/env python3
"""
wcfi_decide.decide(FanSnapshot) -> Skip(reason) | ClosePpv | Ask, each with
handoff_admitted: the welcome_chatter_for_info per-fan eligibility gates (run() is the
shell) as tables.

  case_one_row_per_reason              every Skip reason, its durability, ClosePpv, Ask
  case_precedence                      with every gate tripped, peel them off one at a
                                       time: listed > mid_funnel > not_turn > paused >
                                       muted > spam > spent > too_long/ClosePpv > Ask
  case_forced_bypasses_only_soft_gates force_ids opens mid_funnel/spam/spent/too_long,
                                       never listed / not_turn / paused / muted
  case_no_fan_row_skips_the_row_gates  no Fan row → spam/spent/too_long never apply
  case_handoff_opens_the_turn_gate     a welcome handoff counts as his turn
  case_handoff_admitted_per_reason     handoff_admitted iff past listed/mid_funnel w/ handoff
  case_stat_covers_every_reason        STAT maps every Reason to a stats key; DURABLE ⊂ Reason
  case_module_is_pure                  stdlib only (no DB import)

Run: ./venv/bin/python service/tests/test_wcfi_decide.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import ast  # noqa: E402
from dataclasses import replace  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import get_args  # noqa: E402

from automations import wcfi_decide as d  # noqa: E402
from automations.wcfi_decide import Ask, ClosePpv, FanSnapshot, Skip, decide  # noqa: E402

# An eligible fan: his turn, a Fan row, nothing tripped, under the cutoff.
OK = FanSnapshot(listed=False, mid_funnel=False, forced=False, his_turn=True,
                 handoff=False, has_fan_row=True, paused=False, muted_creator=False,
                 promo_spam=False, content_payer=False, gather_done=False,
                 fan_msg_n=3, max_fan_messages=10, closing_due=False)

# Every gate tripped at once, in precedence order (each tuple: the override that
# trips it, the verdict it yields).
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
        ({"fan_msg_n": 10, "closing_due": True}, ClosePpv()),   # cutoff + closing PPV due
        ({"fan_msg_n": 50, "gather_done": True}, Ask()),         # gather done: cutoff off
        ({"fan_msg_n": 9}, Ask()),                               # one under the cutoff
        ({}, Ask()),
    ]
    for kw, want in rows:
        got = decide(replace(OK, **kw))
        assert got == want, (kw, got, want)
    # spam is the one reversible row-gate; spent / too_long persist
    assert decide(replace(OK, promo_spam=True)).durable is False
    assert {r.reason for _, r in ALL if r.durable} == {"spent", "too_long"}


def case_precedence() -> None:
    tripped: dict = {}
    for kw, _ in ALL:
        tripped.update(kw)
    for kw, want in ALL:
        got = decide(replace(OK, **tripped))
        assert got == want, (sorted(tripped), got, want)
        for k in kw:                           # clear this gate → the next one answers
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
    # …but not the gates around it
    assert decide(replace(OK, his_turn=False, handoff=True, listed=True)) == Skip("listed")
    assert decide(replace(OK, his_turn=False, handoff=True, paused=True)) == Skip("paused", True)


def case_handoff_admitted_per_reason() -> None:
    # (overrides, reason or verdict type, handoff_admitted) — handoff on, his_turn off
    rows = [
        ({"listed": True}, "listed", False),            # dropped before the turn gate
        ({"mid_funnel": True}, "mid_funnel", False),    # ditto
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
    # no handoff → never admitted, whatever the verdict
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


def case_module_is_pure() -> None:
    tree = ast.parse(Path(d.__file__).read_text(encoding="utf-8"))
    mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert mods <= {"__future__", "dataclasses", "typing"}, mods


_harness.run()
