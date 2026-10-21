#!/usr/bin/env python3
"""
On/off WIRING checkpoint for send_welcome, send_followup, welcome_chatter_for_info.

Each case drives the SAME route coroutine the UI hits, reads the persisted key
back, then runs the real supervisor pass (`_drain_due_jobs_once`) or the real
W7 dispatch (`webhook_dispatch.on_inbound_message`) and checks whether the
automation ran / was enqueued. The automation bodies are replaced by a recorder
in the registry, so "ran" means "the executor dispatched it" — nothing sends.

UI → API → key:
  send_welcome    BrainPanel.saveWelcome  → POST /admin/automation-rules (create)
                                           / PATCH /admin/automation-rules/{id}
  send_followup   BrainPanel.saveFollowup → same two routes
  welcome_chatter_for_info  ScriptsTab AutomationSwitchCard
                                         → POST /admin/automation-rules/switch
  key: automation_rules.is_enabled; runtime gate: _materialize_due_rules.

  case_send_welcome_patch_gates_materializer / case_send_followup_...:
      create (enabled) → PATCH off → persisted False → drain runs nothing;
      PATCH on → drain runs it once.
  case_info_switch_gates_periodic_sweep:
      switch on/off flips the row; the periodic sweep follows it.
  case_info_realtime_enqueues_when_rule_on:
      positive control — W7 inbound with the rule ON enqueues a fan-scoped job.
  case_info_realtime_does_not_enqueue_when_rule_off  (was a BUG, fixed):
      W7 gates on webhook_config_json.enabled only; `_classify_kind` returns
      welcome_chatter_for_info without ever reading its rule.
  case_info_queued_realtime_job_dropped_after_switch_off  (was a BUG, fixed):
      a real-time job queued while ON still runs after the switch goes OFF.
  case_send_welcome_queued_job_dropped_after_patch_off  (was a BUG, fixed):
      a materialized job still pending (in-flight lock / retry backoff) runs
      after the rule is PATCHed off — run_once never re-checks the rule.

Run: ./venv/bin/python service/tests/test_wiring_welcome.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

# The route coroutines are driven directly with no signed-in principal; the
# fail-closed gate's documented escape hatch (precedent: test_account_config_api).
os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import automation_registry as reg  # noqa: E402
import webhook_dispatch as wd  # noqa: E402
from automation_rules_api import (  # noqa: E402
    KindSwitch, RuleCreate, RulePatch, create_rule, switch_kind, update_rule,
)
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, AutomationRule, ScheduledJob  # noqa: E402

KINDS = ("send_welcome", "send_followup", "welcome_chatter_for_info")
INFO = "welcome_chatter_for_info"

# ── Recorder in place of the real automation bodies (no OF, no LLM) ─────
reg.load_automation_plugins()
CALLS: list[tuple[str, str, dict]] = []


def _recorder(kind: str):
    async def _run(account_id: str, payload: dict, *, run_id: int) -> dict:
        CALLS.append((account_id, kind, dict(payload or {})))
        return {"recorded": 1}
    return _run


for _k in KINDS:
    assert reg.get_automation(_k) is not None, f"{_k} not registered"
    reg._REGISTRY[_k] = _recorder(_k)


def _require(cond: bool, msg: str) -> None:
    """A PRECONDITION inside a case. SystemExit is not caught by
    `_harness.run`, so a broken setup aborts the suite loudly instead of being
    filed as an ordinary assertion failure."""
    if not cond:
        print(f"[FAIL] precondition: {msg}")
        sys.exit(1)


def _ran(aid: str, kind: str) -> list[dict]:
    return [p for a, k, p in CALLS if a == aid and k == kind]


# ── Helpers ──────────────────────────────────────────────────────────

async def _seed(aid: str, *, webhook: bool = False) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        if webhook and await s.get(AccountAiConfig, aid) is None:
            s.add(AccountAiConfig(account_id=aid,
                                  webhook_config_json=json.dumps({"enabled": True})))


async def _drain() -> None:
    """One real supervisor pass, then wait for the detached runs it spawned."""
    ax._run_sem = None
    ax._bulk_sem = None
    await ax._drain_due_jobs_once()
    if ax._inflight_tasks:
        await asyncio.gather(*list(ax._inflight_tasks))


async def _rules(aid: str, kind: str) -> list[AutomationRule]:
    async with get_session() as s:
        return list((await s.execute(
            select(AutomationRule).where(AutomationRule.account_id == aid,
                                         AutomationRule.kind == kind)
            .order_by(AutomationRule.id))).scalars())


async def _pending(aid: str, kind: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == kind,
                                       ScheduledJob.status == "pending"))).scalars())


async def _patch_gates_materializer(aid: str, kind: str, payload: dict) -> None:
    await _seed(aid)
    out = await create_rule(RuleCreate(account_id=aid, kind=kind, name=kind,
                                       every_seconds=300, payload=payload,
                                       is_enabled=True))
    rid = out["id"]
    assert (await _rules(aid, kind))[0].is_enabled is True

    # OFF (the panel's "Enabled" unticked + Save → PATCH is_enabled=false)
    out = await update_rule(rid, RulePatch(is_enabled=False))
    assert out["is_enabled"] is False
    assert (await _rules(aid, kind))[0].is_enabled is False, "OFF not persisted"
    await _drain()
    assert _ran(aid, kind) == [], f"{kind} ran while its rule is OFF"
    assert await _pending(aid, kind) == [], f"{kind} job enqueued while OFF"

    # ON
    await update_rule(rid, RulePatch(is_enabled=True))
    assert (await _rules(aid, kind))[0].is_enabled is True, "ON not persisted"
    await _drain()
    runs = _ran(aid, kind)
    assert len(runs) == 1, f"{kind} expected 1 run after ON, got {len(runs)}"
    for k, v in payload.items():
        assert runs[0].get(k) == v, f"rule payload {k} not carried to the run"


# ── Cases ────────────────────────────────────────────────────────────

async def case_send_welcome_patch_gates_materializer():
    await _patch_gates_materializer("wire_welcome", "send_welcome",
                                    {"question": "where u from?"})


async def case_send_followup_patch_gates_materializer():
    await _patch_gates_materializer("wire_followup", "send_followup",
                                    {"step_hours": [4, 24, 72], "with_image": True})


async def case_info_switch_gates_periodic_sweep():
    aid = "wire_info_sweep"
    await _seed(aid)
    await switch_kind(KindSwitch(account_id=aid, kind=INFO, enable=False))
    assert await _rules(aid, INFO) == [], "switch-off on no row must not create one"

    out = await switch_kind(KindSwitch(account_id=aid, kind=INFO, enable=True))
    assert out["action"] == "created"
    await switch_kind(KindSwitch(account_id=aid, kind=INFO, enable=False))
    rows = await _rules(aid, INFO)
    assert len(rows) == 1 and rows[0].is_enabled is False, "switch OFF not persisted"
    await _drain()
    assert _ran(aid, INFO) == [], "info sweep ran while switched OFF"

    await switch_kind(KindSwitch(account_id=aid, kind=INFO, enable=True))
    rows = await _rules(aid, INFO)
    assert len(rows) == 1 and rows[0].is_enabled is True, "switch ON not persisted / duplicated"
    await _drain()
    assert len(_ran(aid, INFO)) == 1, "info sweep did not run after switch ON"


async def case_info_realtime_enqueues_when_rule_on():
    aid, fan = "wire_info_rt_on", 7001
    await _seed(aid, webhook=True)
    await switch_kind(KindSwitch(account_id=aid, kind=INFO, enable=True))
    await wd.on_inbound_message(aid, fan, 1)
    jobs = await _pending(aid, INFO)
    assert len(jobs) == 1, f"expected 1 real-time job with rule ON, got {len(jobs)}"
    assert json.loads(jobs[0].payload_json).get("only_fan_ids") == [fan]


async def case_info_realtime_does_not_enqueue_when_rule_off():
    aid, fan = "wire_info_rt_off", 7002
    await _seed(aid, webhook=True)
    await switch_kind(KindSwitch(account_id=aid, kind=INFO, enable=True))
    await switch_kind(KindSwitch(account_id=aid, kind=INFO, enable=False))
    _require((await _rules(aid, INFO))[0].is_enabled is False, "switch OFF persisted")
    await wd.on_inbound_message(aid, fan, 1)
    assert await _pending(aid, INFO) == [], "real-time info job enqueued while switch is OFF"
    await _drain()
    assert _ran(aid, INFO) == [], "info ran for a real-time inbound while switch is OFF"


async def case_info_queued_realtime_job_dropped_after_switch_off():
    aid, fan = "wire_info_rt_queued", 7003
    await _seed(aid, webhook=True)
    await switch_kind(KindSwitch(account_id=aid, kind=INFO, enable=True))
    await wd.on_inbound_message(aid, fan, 1)
    _require(len(await _pending(aid, INFO)) == 1, "real-time job queued while ON")
    await switch_kind(KindSwitch(account_id=aid, kind=INFO, enable=False))
    _require((await _rules(aid, INFO))[0].is_enabled is False, "switch OFF persisted")
    await _drain()
    assert _ran(aid, INFO) == [], "queued real-time info job ran after switch OFF"


async def case_send_welcome_queued_job_dropped_after_patch_off():
    aid = "wire_welcome_queued"
    await _seed(aid)
    out = await create_rule(RuleCreate(account_id=aid, kind="send_welcome",
                                       name="w", every_seconds=300, is_enabled=True))
    _require(await ax._materialize_due_rules() >= 1, "rule materialized while ON")
    _require(len(await _pending(aid, "send_welcome")) == 1, "job queued while ON")
    await update_rule(out["id"], RulePatch(is_enabled=False))
    _require((await _rules(aid, "send_welcome"))[0].is_enabled is False, "PATCH off persisted")
    await _drain()
    assert _ran(aid, "send_welcome") == [], "pending send_welcome job ran after PATCH off"


_harness.run()
