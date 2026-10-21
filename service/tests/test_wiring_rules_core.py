#!/usr/bin/env python3
"""The generic on/off checkpoint every rule-based automation shares.

`automation_rules.is_enabled` is the one switch for gen_info, apply_profiles,
customs_watch, send_mass_message, reply_mass_funnel (and every
other rule kind): the automations never read their own rule, so whether a kind
runs is decided entirely by

  • the write routes — POST/PATCH /admin/automation-rules and
    POST /admin/automation-rules/switch (automation_rules_api.py), and
  • the executor — `_materialize_due_rules` (only enabled rules mint jobs) and
    the claim path `run_once` → `_claim_due_job` (automation_executor.py).

Pinned here: OFF → the materializer mints nothing; ON → the very next tick
schedules; the switch parks every duplicate and never creates a second row;
PATCH is ownership-gated (owner of another Agency 403, a linked chatter may
toggle — by design, chatters.py `_CHATTER_BLOCKED_ADMIN_PREFIXES` leaves the
rules routes to the per-account gate).

Formerly-known bugs, now fixed and kept as regression guards:
  • a job already materialised while the rule was ON still runs after the
    rule is switched OFF or deleted (no cancel on OFF, no re-check at claim);
  • customs_watch.watch_flags reads `.limit(1)` with no ORDER BY, so with a
    parked duplicate beside the live row the live tip dispatcher reads "off".

Run: ./venv/bin/python service/tests/test_wiring_rules_core.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import automation_executor as ax  # noqa: E402
from automation_registry import load_automation_plugins, register  # noqa: E402
from db.engine import get_session  # noqa: E402
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402
from db.models import AutomationRule, ScheduledJob  # noqa: E402

IDS = fx.seed_two_agencies()
# An install from before role enforcement was on by default: its logins hold Admin.
asyncio.run(seed_pre_enforcement_install())
ACC_A = IDS["creator_a"]
ACC_B = IDS["creator_b"]

OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
CHATTER_A = fx.login_chatter("chatter_a")
CHATTER_B = fx.login_chatter("chatter_b")

# The generic kinds this suite covers (all registered plugin kinds).
GENERIC_KINDS = ("customs_watch", "gen_info", "apply_profiles",
                 "send_mass_message", "reply_mass_funnel")

# ── A recording probe kind: lets the execution cases observe whether a job ran
#    without touching OF or an LLM. Registered after the real plugins load.
load_automation_plugins()
PROBE = "wiring_probe"
CALLS: list[tuple[str, dict]] = []


@register(PROBE)
async def _probe(account_id: str, payload: dict, *, run_id: int) -> dict:
    CALLS.append((account_id, payload))
    return {"probed": 1}


# ── helpers ─────────────────────────────────────────────────────────────

async def _add_rule(account_id: str, kind: str, *, enabled: bool,
                    every: int = 1, steps: dict | None = None) -> int:
    async with get_session() as s:
        r = AutomationRule(account_id=account_id, name=f"{kind} t", kind=kind,
                           trigger_json=json.dumps({"every_seconds": every}),
                           steps_json=json.dumps(steps or {}), is_enabled=enabled)
        s.add(r)
        await s.flush()
        return r.id


async def _jobs(account_id: str, kind: str | None = None,
                status: tuple[str, ...] = ("pending", "running")) -> list[ScheduledJob]:
    async with get_session() as s:
        q = select(ScheduledJob).where(ScheduledJob.account_id == account_id,
                                       ScheduledJob.status.in_(status))
        if kind is not None:
            q = q.where(ScheduledJob.kind == kind)
        return list((await s.execute(q)).scalars())


async def _retire(account_id: str) -> None:
    """Park every rule and settle every job of `account_id`, so a later case's
    materializer/drain never picks up this case's real-kind rows."""
    async with get_session() as s:
        await s.execute(update(AutomationRule)
                        .where(AutomationRule.account_id == account_id)
                        .values(is_enabled=False))
        await s.execute(update(ScheduledJob)
                        .where(ScheduledJob.account_id == account_id,
                               ScheduledJob.status.in_(("pending", "running")))
                        .values(status="done"))


async def _rule(rule_id: int) -> AutomationRule | None:
    async with get_session() as s:
        return await s.get(AutomationRule, rule_id)


def _patch(client, rule_id: int, body: dict):
    return client.patch(f"/admin/automation-rules/{rule_id}", json=body)


# ── OFF → nothing materialises; ON (via PATCH) → the next tick schedules ─

def case_off_materializes_nothing_on_schedules_next_tick():
    rule_ids = {k: asyncio.run(_add_rule(ACC_A, k, enabled=False)) for k in GENERIC_KINDS}

    asyncio.run(ax._materialize_due_rules())
    assert asyncio.run(_jobs(ACC_A)) == [], "an OFF rule must mint no job"

    for kind, rid in rule_ids.items():
        r = _patch(OWNER_A, rid, {"is_enabled": True})
        assert r.status_code == 200 and r.json()["is_enabled"] is True, (kind, r.text)

    asyncio.run(ax._materialize_due_rules())
    jobs = asyncio.run(_jobs(ACC_A))
    by_kind = {j.kind: j for j in jobs}
    assert sorted(by_kind) == sorted(GENERIC_KINDS), f"one job per kind, got {sorted(by_kind)}"
    assert len(jobs) == len(GENERIC_KINDS), "exactly one job per enabled rule"
    for kind, rid in rule_ids.items():
        assert by_kind[kind].rule_id == rid, (kind, by_kind[kind].rule_id, rid)

    # Back OFF: the next tick (after the pending jobs settle) mints nothing more.
    for rid in rule_ids.values():
        assert _patch(OWNER_A, rid, {"is_enabled": False}).status_code == 200
    asyncio.run(_retire(ACC_A))
    asyncio.run(ax._materialize_due_rules())
    assert asyncio.run(_jobs(ACC_A)) == [], "switched back OFF → no new jobs"


# ── The probe kind end to end: ON runs, OFF doesn't ──────────────────────

def case_off_rule_never_runs_on_rule_runs_on_drain():
    CALLS.clear()
    rid = asyncio.run(_add_rule(ACC_A, PROBE, enabled=False, steps={"tag": "x"}))

    async def _tick():
        await ax._drain_due_jobs_once()
        await ax._join_inflight_runs()

    asyncio.run(_tick())
    assert CALLS == [], f"OFF rule executed: {CALLS}"

    assert _patch(OWNER_A, rid, {"is_enabled": True}).status_code == 200
    asyncio.run(_tick())
    assert CALLS == [(ACC_A, {"tag": "x"})], f"ON rule must run on the next tick: {CALLS}"
    asyncio.run(_retire(ACC_A))


# ── BUG: a job materialised while ON still runs after OFF / delete ──────

def case_pending_job_does_not_run_after_rule_switched_off():
    CALLS.clear()
    rid = asyncio.run(_add_rule(ACC_A, PROBE, enabled=True))
    asyncio.run(ax._materialize_due_rules())
    assert len(asyncio.run(_jobs(ACC_A, PROBE))) == 1, "precondition: one pending job"
    try:
        assert _patch(OWNER_A, rid, {"is_enabled": False}).status_code == 200
        asyncio.run(ax.run_once(ACC_A, PROBE))
        assert CALLS == [], f"switched-OFF rule's pending job executed: {CALLS}"
    finally:
        asyncio.run(_retire(ACC_A))


def case_pending_job_does_not_run_after_rule_deleted():
    CALLS.clear()
    rid = asyncio.run(_add_rule(ACC_A, PROBE, enabled=True))
    asyncio.run(ax._materialize_due_rules())
    assert len(asyncio.run(_jobs(ACC_A, PROBE))) == 1, "precondition: one pending job"
    try:
        assert OWNER_A.delete(f"/admin/automation-rules/{rid}").status_code == 200
        asyncio.run(ax.run_once(ACC_A, PROBE))
        assert CALLS == [], f"deleted rule's pending job executed: {CALLS}"
    finally:
        asyncio.run(_retire(ACC_A))


def case_manual_oneshot_without_rule_still_runs():
    """Guard for the fix above: a job with NO rule_id (Run-now-less one-shots —
    the composer's send_mass_message, fans.py's gen_info refresh) must keep
    running even while a parked rule of the same kind exists."""
    CALLS.clear()
    asyncio.run(_add_rule(ACC_A, PROBE, enabled=False))
    asyncio.run(ax.enqueue_job(ACC_A, PROBE, payload={"one": 1}))
    asyncio.run(ax.run_once(ACC_A, PROBE))
    assert CALLS == [(ACC_A, {"one": 1})], CALLS
    asyncio.run(_retire(ACC_A))


# ── The switch: parks EVERY duplicate, wakes one, never creates a second ─

def case_switch_parks_all_duplicates_and_never_duplicates():
    a = asyncio.run(_add_rule(ACC_B, "apply_profiles", enabled=True))
    b = asyncio.run(_add_rule(ACC_B, "apply_profiles", enabled=True))

    r = OWNER_B.post("/admin/automation-rules/switch",
                     json={"account_id": ACC_B, "kind": "apply_profiles", "enable": False})
    assert r.status_code == 200 and r.json()["action"] == "parked", r.text
    assert not asyncio.run(_rule(a)).is_enabled and not asyncio.run(_rule(b)).is_enabled
    asyncio.run(ax._materialize_due_rules())
    assert asyncio.run(_jobs(ACC_B, "apply_profiles")) == [], "parked kind minted a job"

    r = OWNER_B.post("/admin/automation-rules/switch",
                     json={"account_id": ACC_B, "kind": "apply_profiles", "enable": True})
    assert r.status_code == 200 and r.json()["action"] == "updated", r.text
    assert asyncio.run(_rule(a)).is_enabled, "the first row wakes"
    assert not asyncio.run(_rule(b)).is_enabled, "the duplicate stays parked"

    async def _count():
        async with get_session() as s:
            return len(list((await s.execute(select(AutomationRule.id).where(
                AutomationRule.account_id == ACC_B,
                AutomationRule.kind == "apply_profiles"))).scalars()))
    assert asyncio.run(_count()) == 2, "switch ON must not mint a third row"

    asyncio.run(ax._materialize_due_rules())
    jobs = asyncio.run(_jobs(ACC_B, "apply_profiles"))
    assert len(jobs) == 1 and jobs[0].rule_id == a, [(j.id, j.rule_id) for j in jobs]

    # Foreign account → 403 before any write.
    r = OWNER_A.post("/admin/automation-rules/switch",
                     json={"account_id": ACC_B, "kind": "apply_profiles", "enable": False})
    assert r.status_code == 403, r.text
    assert asyncio.run(_rule(a)).is_enabled
    asyncio.run(_retire(ACC_B))


# ── PATCH ownership: owner of another Agency 403; linked chatter allowed ─

def case_patch_is_ownership_gated():
    rid = asyncio.run(_add_rule(ACC_A, "gen_info", enabled=False, every=86400))

    assert _patch(OWNER_B, rid, {"is_enabled": True}).status_code == 403
    assert _patch(CHATTER_B, rid, {"is_enabled": True}).status_code == 403
    assert not asyncio.run(_rule(rid)).is_enabled, "a refused PATCH wrote anyway"

    # By design: rules routes are not owner-only (chatters.py), the per-account
    # gate applies; a chatter linked to the owning Agency may toggle.
    r = _patch(CHATTER_A, rid, {"is_enabled": True})
    assert r.status_code == 200 and r.json()["is_enabled"] is True, r.text
    asyncio.run(_retire(ACC_A))


# ── BUG: customs_watch reads an arbitrary row when duplicates exist ──────

def case_customs_watch_flags_prefer_enabled_row():
    from automations.customs_watch import watch_flags
    acc = ACC_B   # a seeded account: automation_rules.account_id is a real FK
    asyncio.run(_add_rule(acc, "customs_watch", enabled=False, steps={"min_cents": 111}))
    asyncio.run(_add_rule(acc, "customs_watch", enabled=True, steps={"min_cents": 222}))
    try:
        on, payload = asyncio.run(watch_flags(acc))
        assert on is True, "an enabled customs_watch rule exists, flags read OFF"
        assert payload.get("min_cents") == 222, payload
    finally:
        asyncio.run(_retire(acc))


_harness.run()
