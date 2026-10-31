"""service/automation_rule_read.py — read a per-kind automation rule's config.

The kinds that keep their whole config in one AutomationRule of their kind
(purchase_followup, the lifecycle Triggers) read it the same way: every row of
the kind oldest first, the row the sweep runs (`primary_rule`), and its steps
as a dict (`rule_steps`, {} when unreadable).
"""
from __future__ import annotations

import json

from sqlalchemy import select

from db.models import AutomationRule


async def rules_of_kind(s, account_id: str, kind: str) -> list[AutomationRule]:
    """Every row of the kind, oldest first. Exact `kind` only, no legacy aliases
    (automation_registry.kind_family): for kinds that were never renamed."""
    return list((await s.execute(
        select(AutomationRule).where(
            AutomationRule.account_id == account_id,
            AutomationRule.kind == kind).order_by(AutomationRule.id)
    )).scalars())


def primary_rule(rules: list[AutomationRule]) -> AutomationRule | None:
    """The row the sweep runs: the first switched on, else the first."""
    return next((r for r in rules if r.is_enabled), rules[0] if rules else None)


def rule_steps(rule: AutomationRule | None) -> dict:
    """The rule's steps as a dict; {} for no rule, empty, bad or non-object JSON."""
    if rule is None or not rule.steps_json:
        return {}
    try:
        steps = json.loads(rule.steps_json)
    except Exception:
        return {}
    return steps if isinstance(steps, dict) else {}
