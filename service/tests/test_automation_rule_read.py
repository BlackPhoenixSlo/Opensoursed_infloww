#!/usr/bin/env python3
"""automation_rule_read — the per-kind rule read the config APIs share.

  case_rules_of_kind:  only the account's rows of the kind, oldest first; none → [].
  case_primary_rule:   none → None; disabled-only → first; an enabled row wins over
                       an older disabled one; two enabled → the oldest.
  case_rule_steps:     None rule / None / "" / bad JSON / non-dict JSON → {}; a dict reads back.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
from types import SimpleNamespace as Row  # noqa: E402

from automation_rule_read import primary_rule, rule_steps, rules_of_kind  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AutomationRule  # noqa: E402

KIND = "purchase_followup"


def case_rules_of_kind():
    async def go():
        async with get_session() as s:
            for aid in ("arr-a", "arr-b"):
                s.add(Account(id=aid))
            await s.flush()
            for aid, kind, name in [("arr-a", KIND, "first"), ("arr-a", "expiry_message", "other kind"),
                                    ("arr-b", KIND, "other account"), ("arr-a", KIND, "second")]:
                s.add(AutomationRule(account_id=aid, name=name, kind=kind,
                                     trigger_json="{}", steps_json="{}"))
        async with get_session() as s:
            got = [r.name for r in await rules_of_kind(s, "arr-a", KIND)]
            assert got == ["first", "second"], got
            assert await rules_of_kind(s, "arr-none", KIND) == []
    asyncio.run(go())


def case_primary_rule():
    off1, off2 = Row(id=1, is_enabled=False), Row(id=2, is_enabled=False)
    on3, on4 = Row(id=3, is_enabled=True), Row(id=4, is_enabled=True)
    for rules, want in [
        ([], None),
        ([off1, off2], off1),
        ([off1, on3], on3),
        ([on3, on4], on3),
        ([off1, on3, off2, on4], on3),
    ]:
        assert primary_rule(rules) is want, ([r.id for r in rules], want)


def case_rule_steps():
    assert rule_steps(None) == {}
    for raw, want in [(None, {}), ("", {}), ("not json", {}), ("[1,2]", {}),
                      ('"s"', {}), ("null", {}), ('{"a":1}', {"a": 1})]:
        assert rule_steps(Row(steps_json=raw)) == want, (raw, want)


if __name__ == "__main__":
    _harness.run()
