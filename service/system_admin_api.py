"""service/system_admin_api.py — Settings → System: the master's ops back-office.

Read-only status for the deployment master (users.is_admin) and for an operator
agent checking on the box:

  GET /admin/system/automations   per account: every automation kind's rule
                                  state (is_enabled, rule ids, duplicates), its
                                  config-json `enabled` flag(s), and a mismatch
                                  flag when the two disagree; plus the env kill
                                  switches that override them process-wide.
  GET /admin/system/runs          recent automation_runs across ALL accounts
                                  (with error_text), plus failed ("error") /
                                  pending scheduled_jobs with last_error.

MASTER ONLY, by construction: the gate is a ROUTER dependency (the
tenant_keys_api pattern), so a route added here cannot forget it. A non-master
owner gets 403, nobody signed in gets 401 (`auth.require_master`). Chatter
sessions are refused earlier still by `chatters._CHATTER_BLOCKED_ADMIN_PREFIXES`.
Master's `account_ids` is every account (auth._master_account_ids), so the
account-isolation middleware lets an `account_id` filter through.
"""
from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from auth import require_master
from automation_registry import canonical_kind
from db.engine import get_session
from db.models import Account, AccountAiConfig, AutomationRule, AutomationRun, ScheduledJob

router = APIRouter(prefix="/admin/system", tags=["system-admin"],
                   dependencies=[Depends(require_master)])


# (kind, label, config column, [key paths that must ALL be true], absent-key default)
# Defaults mirror each automation's built-in config, so an account that never
# saved the blob reads the way the automation itself reads it.
_CONFIG_GATED: tuple[tuple[str, str, str, tuple[tuple[str, ...], ...], bool], ...] = (
    ("nudge_online", "Nudge online", "nudge_config_json", (("enabled",),), True),
    ("autoreply", "Autoreply", "autoreply_config_json", (("enabled",),), False),
)
# (env var, what it turns off, predicate matching the consumer's own read)
_KILL_SWITCHES: tuple[tuple[str, str, Any], ...] = (
    ("STYLE_FORCE_OFF", "Human texting style flags, every account", lambda v: bool(v)),  # _common
)


def _kill_switches() -> list[dict[str, Any]]:
    out = []
    for name, effect, pred in _KILL_SWITCHES:
        raw = os.environ.get(name, "")
        out.append({"env": name, "value": raw or None, "active": bool(pred(raw)), "effect": effect})
    return out


def _parse(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except Exception:
        return None
    return v if isinstance(v, dict) else None


def _dig(cfg: dict | None, path: tuple[str, ...]) -> Any:
    cur: Any = cfg
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _config_flag(cfg: dict | None, paths: tuple[tuple[str, ...], ...], default: bool) -> dict[str, Any]:
    flags = {}
    for p in paths:
        v = _dig(cfg, p)
        flags[".".join(p)] = default if v is None else bool(v)
    return {"enabled": all(flags.values()), "flags": flags, "stored": cfg is not None}


@router.get("/automations")
async def system_automations() -> dict[str, Any]:
    """Every account × automation kind: rule on/off vs config on/off."""
    async with get_session() as s:
        accounts = {a.id: a.nickname for a in (await s.execute(select(Account))).scalars()}
        rules = (await s.execute(select(AutomationRule).order_by(AutomationRule.id))).scalars().all()
        configs = {c.account_id: c for c in (await s.execute(select(AccountAiConfig))).scalars()}

    by_acct: dict[str, dict[str, list[AutomationRule]]] = {}
    for r in rules:
        by_acct.setdefault(r.account_id, {}).setdefault(canonical_kind(r.kind), []).append(r)
    ids = sorted(set(accounts) | set(by_acct) | set(configs))

    out_accounts = []
    mismatches = 0
    for aid in ids:
        cfg_row = configs.get(aid)
        acct_rules = by_acct.get(aid, {})
        rows: list[dict[str, Any]] = []

        def rule_part(kind: str) -> dict[str, Any]:
            rs = acct_rules.get(kind, [])
            return {
                "rule_ids": [r.id for r in rs],
                "rule_enabled": (any(r.is_enabled for r in rs) if rs else None),
                "rules_enabled_count": sum(1 for r in rs if r.is_enabled),
                "duplicate_rules": len(rs) > 1,
            }

        for kind, label, col, paths, default in _CONFIG_GATED:
            cfg = _config_flag(_parse(getattr(cfg_row, col, None) if cfg_row else None), paths, default)
            rp = rule_part(kind)
            rule_on = bool(rp["rule_enabled"])
            # Disagree = a rule fires on a config that says off, or the config
            # says on and no enabled rule will ever schedule it. Only once the
            # operator has touched it (config stored or a rule row exists): a
            # house-default-ON kind (nudge_online) on an account that
            # never saved either is not a disagreement anyone made.
            touched = cfg["stored"] or bool(rp["rule_ids"])
            mismatch = touched and rule_on != cfg["enabled"]
            rows.append({"kind": kind, "label": label, "source": "rule+config", **rp,
                         "config_column": col, "config_enabled": cfg["enabled"],
                         "config_flags": cfg["flags"], "config_stored": cfg["stored"],
                         "effective": rule_on and cfg["enabled"], "mismatch": mismatch})
        known = {k for k, *_ in _CONFIG_GATED}
        for kind in sorted(set(acct_rules) - known):
            rp = rule_part(kind)
            rows.append({"kind": kind, "label": kind, "source": "rule", **rp,
                         "config_column": None, "config_enabled": None, "config_flags": {},
                         "config_stored": False, "effective": bool(rp["rule_enabled"]),
                         "mismatch": False})
        mismatches += sum(1 for r in rows if r["mismatch"])
        out_accounts.append({"account_id": aid, "nickname": accounts.get(aid), "automations": rows})

    return {"accounts": out_accounts, "kill_switches": _kill_switches(),
            "mismatch_count": mismatches}


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


@router.get("/runs")
async def system_runs(
    limit: int = Query(100, ge=1, le=500),
    kind: str | None = Query(None),
    account_id: str | None = Query(None),
    status: str | None = Query(None),
) -> dict[str, Any]:
    """Recent automation_runs across every account (newest first), and the
    failed / pending scheduled_jobs with their last_error. `kind`, `account_id`
    and `status` filter both lists (a run status the job queue never uses, such
    as "ok", leaves `jobs` empty)."""
    async with get_session() as s:
        q = select(AutomationRun)
        if kind:
            q = q.where(AutomationRun.kind == kind)
        if account_id:
            q = q.where(AutomationRun.account_id == account_id)
        if status:
            q = q.where(AutomationRun.status == status)
        runs = (await s.execute(q.order_by(AutomationRun.started_at.desc(),
                                           AutomationRun.id.desc()).limit(limit))).scalars().all()

        # The executor marks a failed job "error" (automation_executor._mark_job);
        # "failed" is matched too so an older writer's rows are not hidden.
        job_statuses = ("error", "failed", "pending")
        if status:
            job_statuses = tuple(x for x in job_statuses if x == status)
        jq = select(ScheduledJob).where(ScheduledJob.status.in_(job_statuses))
        if kind:
            jq = jq.where(ScheduledJob.kind == kind)
        if account_id:
            jq = jq.where(ScheduledJob.account_id == account_id)
        jobs = (await s.execute(jq.order_by(ScheduledJob.run_at.desc(),
                                            ScheduledJob.id.desc()).limit(limit))).scalars().all()

    return {
        "runs": [{"id": r.id, "account_id": r.account_id, "kind": r.kind, "status": r.status,
                  "started_at": _iso(r.started_at), "completed_at": _iso(r.completed_at),
                  "stats_json": r.stats_json, "error_text": r.error_text} for r in runs],
        "jobs": [{"id": j.id, "account_id": j.account_id, "kind": j.kind, "status": j.status,
                  "run_at": _iso(j.run_at), "attempts": j.attempts, "rule_id": j.rule_id,
                  "last_error": j.last_error} for j in jobs],
    }
