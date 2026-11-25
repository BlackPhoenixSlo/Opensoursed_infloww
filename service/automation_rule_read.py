from __future__ import annotations

import json

from sqlalchemy import select

from db.models import AutomationRule


async def rules_of_kind(s, account_id: str, kind: str) -> list[AutomationRule]:
    # Exact `kind` only, no legacy aliases: for kinds that were never renamed.
    return list((await s.execute(
        select(AutomationRule).where(
            AutomationRule.account_id == account_id,
            AutomationRule.kind == kind).order_by(AutomationRule.id)
    )).scalars())


def primary_rule(rules: list[AutomationRule]) -> AutomationRule | None:
    return next((r for r in rules if r.is_enabled), rules[0] if rules else None)


def rule_steps(rule: AutomationRule | None) -> dict:
    if rule is None or not rule.steps_json:
        return {}
    try:
        steps = json.loads(rule.steps_json)
    except Exception:
        return {}
    return steps if isinstance(steps, dict) else {}
