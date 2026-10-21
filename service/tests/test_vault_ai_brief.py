#!/usr/bin/env python3
"""
`vault_ai_brief` — `sellability()` and `load_fields()` over the describe
taxonomy. Durable regression suite (plain-assert, no pytest — repo convention).

Cases:
  case_solo_is_never_assumed:
      partner_visible / people_count > 1 rules solo out; an item that says
      nothing is unknown, never an assumed solo. Mis-framing this is a refund.
  case_stands_alone_vs_buildup:
      a payoff act ⇒ stands alone; no payoff act ⇒ build-up only.
  case_ladder_rung:
      explicitness maps to a rung index — the escalation order, and the order
      walked backwards for a re-sell.
  case_missing_fields_degrade:
      an empty/garbage ai_fields_json loads as {} instead of raising.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_ai_brief.py
Exit 0 = all cases passed. Pure functions — no DB, no network, no LLM.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import vault_ai_brief as B  # noqa: E402


async def case_solo_is_never_assumed() -> None:
    assert B.sellability({"people_count": 2, "partner_visible": True})["solo"] is False
    assert B.sellability({"people_count": 1, "partner_visible": False})["solo"] is True
    # people_count alone is enough to rule solo OUT even if partner_visible is
    # missing — the safe direction when the vision pass didn't say.
    assert B.sellability({"people_count": 3})["solo"] is False
    # …and an item that says nothing is `None` (unknown), never an assumed solo.
    assert B.sellability({})["solo"] is None


async def case_stands_alone_vs_buildup() -> None:
    payoff = B.sellability({"acts": ["tease", "fingering"], "explicitness": "hardcore"})
    assert payoff["stands_alone"] is True and payoff["payoff_acts"] == ["fingering"], payoff

    build = B.sellability({"acts": ["posing", "tease"], "explicitness": "suggestive"})
    assert build["stands_alone"] is False and build["payoff_acts"] == [], build


async def case_ladder_rung() -> None:
    assert B.sellability({"explicitness": "sfw"})["rung"] == 0
    assert B.sellability({"explicitness": "hardcore"})["rung"] == len(B.EXPLICITNESS_LADDER) - 1
    assert B.sellability({"explicitness": "suggestive"})["rung"] < \
        B.sellability({"explicitness": "explicit"})["rung"]
    # An unrecognised tier must not fake a position on the ladder.
    unknown = B.sellability({"explicitness": "spicy"})
    assert unknown["rung"] is None and unknown["tier"] == "spicy", unknown


async def case_missing_fields_degrade() -> None:
    # Garbage / empty blobs must not raise.
    assert B.load_fields(None) == {}
    assert B.load_fields("not json") == {}
    assert B.load_fields('["a","list"]') == {}


_harness.run(
    case_solo_is_never_assumed,
    case_stands_alone_vs_buildup,
    case_ladder_rung,
    case_missing_fields_degrade,
)
