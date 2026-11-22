"""Keep running rules heal — every Creator with a Kept campaign gets its live promo_reactivate rule

Owner 2026-11-21: Keep running is indefinite by default. Kept campaigns ticked before
PR #850 (the tick owns the rule) can have no `promo_reactivate` rule, or a disabled /
dry-run one, so nothing ever re-creates them. Data only: for each account with a
promo_campaigns row auto_reactivate = 1, exactly one enabled rule of the kind carrying
promotions_api.KEEP_RUNNING_STEPS and the hourly trigger (created, named "Keep promos
running", when missing); with several, the lowest id is kept on and the rest parked (their
pending jobs cancelled, as automation_rules_api.ensure_kind_rule parks). Accounts without a
Kept campaign are untouched. keep_warning rows are left alone. A pending job of a fixed
rule gets the live steps merged into its payload (it was queued with the old, maybe dry-run,
ones); its other keys stay.

Boxes upgrade through db.engine's init_db, which runs `heal` below once
(`data_migrations` marker `20261121_keep_running_rules_heal`); this file runs the same on
a manual `alembic upgrade head` (the marker is not set here). Idempotent. Downgrade: no-op.

Revision ID: 0129_keep_running_rules_heal
Revises: 0126_promo_preempt
Create Date: 2026-11-21
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0129_keep_running_rules_heal"
down_revision: str | Sequence[str] | None = "0126_promo_preempt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KIND = "promo_reactivate"
NAME = "Keep promos running"
# promotions_api.KEEP_RUNNING_STEPS / KEEP_RUNNING_EVERY_S (copied: a migration is frozen).
STEPS = json.dumps({"dry_run": False, "cooldown_minutes": 2, "max_reactivations": 0})
TRIGGER = json.dumps({"every_seconds": 3600})


def _live_jobs(conn, rule_id: int) -> None:
    """The rule's pending jobs get the live steps merged in; their own keys (a Re-check's
    `_recheck`, `_expiry_retries`, `_followup` …) stay."""
    jobs = conn.execute(sa.text(
        "SELECT id, payload_json FROM scheduled_jobs WHERE rule_id = :id AND status = 'pending'"),
        {"id": rule_id}).all()
    for job_id, raw in jobs:
        try:
            payload = json.loads(raw or "{}")
        except ValueError:
            payload = {}
        payload = {**(payload if isinstance(payload, dict) else {}), **json.loads(STEPS)}
        conn.execute(sa.text("UPDATE scheduled_jobs SET payload_json = :p WHERE id = :id"),
                     {"p": json.dumps(payload), "id": job_id})


def heal(conn) -> int:
    """Ensure the rule per Kept account (`conn`: a sync connection in a transaction).
    Returns the number of rules created or changed."""
    tables = set(sa.inspect(conn).get_table_names())
    if not {"promo_campaigns", "automation_rules"} <= tables:
        return 0
    accounts = conn.execute(sa.text(
        "SELECT DISTINCT account_id FROM promo_campaigns WHERE auto_reactivate = :on "
        "ORDER BY account_id"), {"on": True}).scalars().all()
    changed = 0
    for aid in accounts:
        rules = conn.execute(sa.text(
            "SELECT id, is_enabled, steps_json, trigger_json FROM automation_rules "
            "WHERE account_id = :a AND kind = :k ORDER BY id"), {"a": aid, "k": KIND}).all()
        if not rules:
            conn.execute(sa.text(
                "INSERT INTO automation_rules (account_id, name, kind, trigger_json, steps_json, "
                "is_enabled, created_at) VALUES (:a, :n, :k, :t, :s, :on, :now)"),
                {"a": aid, "n": NAME, "k": KIND, "t": TRIGGER, "s": STEPS, "on": True,
                 "now": datetime.utcnow()})
            changed += 1
            continue
        keep, rest = rules[0], rules[1:]
        if not (keep.is_enabled and keep.steps_json == STEPS and keep.trigger_json == TRIGGER):
            conn.execute(sa.text(
                "UPDATE automation_rules SET is_enabled = :on, steps_json = :s, trigger_json = :t "
                "WHERE id = :id"), {"on": True, "s": STEPS, "t": TRIGGER, "id": keep.id})
            if "scheduled_jobs" in tables:   # a job it already queued carries the old (dry-run) steps
                _live_jobs(conn, keep.id)
            changed += 1
        dupes = [r.id for r in rest if r.is_enabled]
        if dupes:
            ids = sa.bindparam("ids", expanding=True)
            conn.execute(sa.text("UPDATE automation_rules SET is_enabled = :off WHERE id IN :ids")
                         .bindparams(ids), {"off": False, "ids": dupes})
            if "scheduled_jobs" in tables:
                conn.execute(sa.text(
                    "UPDATE scheduled_jobs SET status = 'cancelled', last_error = 'rule switched off' "
                    "WHERE rule_id IN :ids AND status = 'pending'").bindparams(ids), {"ids": dupes})
            changed += len(dupes)
    return changed


def upgrade() -> None:
    heal(op.get_bind())


def downgrade() -> None:
    pass
