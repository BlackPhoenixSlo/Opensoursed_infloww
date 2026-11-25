# MASTER ONLY by construction: the gate is a ROUTER dependency, so a route added here cannot forget it.
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select

import runtime_switches
from auth import _assert_admin_password, get_request_user, require_master
from automation_registry import canonical_kind
from db.engine import get_session
from db.models import Account, AccountAiConfig, AutomationRule, AutomationRun, ScheduledJob
from isotime import iso_plain

router = APIRouter(prefix="/admin/system", tags=["system-admin"],
                   dependencies=[Depends(require_master)])


_CONFIG_GATED: tuple[tuple[str, str, str, tuple[tuple[str, ...], ...], bool], ...] = (
    ("nudge_online", "Nudge online", "nudge_config_json", (("enabled",),), True),
    ("autoreply", "Autoreply", "autoreply_config_json", (("enabled",),), False),
)
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
            # Disagree = a rule fires on a config that says off, or the config says on and no enabled rule will schedule it; only once the operator touched it (a house-default-ON kind on an untouched account is no disagreement).
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

    return {"accounts": out_accounts, "mismatch_count": mismatches}


@router.get("/switches")
async def system_switches() -> dict[str, Any]:
    """Every runtime switch: env value, override, effective value and its source."""
    return {"switches": runtime_switches.describe_all(), "loaded": runtime_switches.loaded()}


@router.put("/switches/{name}")
async def set_system_switch(name: str, body: dict = Body(...)) -> dict[str, Any]:
    """Set (`value`) or clear (`value: null`) one switch's override."""
    _assert_admin_password(str(body.get("admin_password") or ""))
    if name not in runtime_switches.BY_NAME:
        raise HTTPException(status_code=404, detail=f"no runtime switch {name}")
    if "value" not in body:
        raise HTTPException(status_code=422, detail='send {"value": ...}; null clears the override')
    user = get_request_user()
    try:
        row = await runtime_switches.set_override(name, body["value"], by=user.username if user else None)
    except (ValueError, OverflowError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"switch": row}


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
                  "started_at": iso_plain(r.started_at), "completed_at": iso_plain(r.completed_at),
                  "stats_json": r.stats_json, "error_text": r.error_text} for r in runs],
        "jobs": [{"id": j.id, "account_id": j.account_id, "kind": j.kind, "status": j.status,
                  "run_at": iso_plain(j.run_at), "attempts": j.attempts, "rule_id": j.rule_id,
                  "last_error": j.last_error} for j in jobs],
    }
