#!/usr/bin/env python3
"""
On/off WIRING for the nudge_online sender — the Settings tab's "Enabled" box,
followed through the real API handler into the persisted key, and from that key
into the runtime gate. Each case is one checkpoint: does OFF actually stop sends
(including a job that was already queued), and does ON actually schedule?

What each tab writes (app/components/settings/*):
  NudgeOnlineTab                 → PUT /admin/nudge-config {config.enabled}
                                   → account_ai_config.nudge_config_json.enabled
                                   THEN a second POST/PATCH of the rule.
Runtime gates:
  _materialize_due_rules  reads automation_rules.is_enabled (schedules, or not)
  nudge_online(+_fire)    read nudge_config_json.enabled (default True), never
                          the rule

  case_nudge_online_config_off_stops_detector_and_queued_fire:
      PUT enabled=false → the detector no-ops AND an already-queued fire job
      skips "disabled" (control account still sends).
  case_nudge_online_put_syncs_rule:
      [fixed] PUT /admin/nudge-config alone never touches the rule, so a half-
      failed tab save (PUT ok, rule PATCH fails) leaves the tab reading ON from
      the config while the rule stays OFF and nothing ever ticks.
  case_nudge_online_rule_off_stops_queued_fire:
      [fixed] the Automations/Ready-made toggle (PATCH is_enabled=false) stops the
      detector but a fire job already queued still sends — the fire gate reads
      only the config.

Run: ./venv/bin/python service/tests/test_wiring_nudges.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

# The route handlers are driven directly, not over HTTP, so there is no request
# principal for `assert_account_owned` to read and it fails closed (401). The
# documented escape hatch, used for its intended purpose (as test_ai_chatter.py).
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
from automation_executor import _materialize_due_rules, run_once  # noqa: E402
from automation_rules_api import RuleCreate, RulePatch, create_rule, update_rule  # noqa: E402
from automations import nudge_online, nudge_online_fire  # noqa: E402,F401
from db.engine import get_session  # noqa: E402
from db.models import Account, AutomationRule, NudgeState, ScheduledJob, WelcomeSent  # noqa: E402
from nudge_config_api import _ConfigBody, put_nudge_config  # noqa: E402


# ── Fake OF (no network): every surface the nudge senders touch ───────

class FakeOF:
    def __init__(self, online=()):
        self.user_id = "999"
        self._online = [int(x) for x in online]
        self.dms: list[tuple[int, str]] = []
        self._next = 8_000_000_000_000

    def iter_online_subscribers(self, *, type="active", page_size=20, max_fans=1000, **kw):
        return [{"id": i, "username": f"u{i}"} for i in self._online[:max_fans]]

    def send_message(self, chat_id, text, *, media_files=None, **kw):
        self._next += 1
        self.dms.append((int(chat_id), text))
        return {"id": self._next, "text": f"<p>{text}</p>",
                "createdAt": "2026-06-05T12:00:00+00:00"}


def _use_fake(online=()) -> FakeOF:
    fake = FakeOF(online)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _jobs(aid: str, kind: str, status: str | None = None) -> list[ScheduledJob]:
    async with get_session() as s:
        q = select(ScheduledJob).where(ScheduledJob.account_id == aid, ScheduledJob.kind == kind)
        if status:
            q = q.where(ScheduledJob.status == status)
        return list((await s.execute(q)).scalars())


async def _rule(rid: int) -> AutomationRule:
    async with get_session() as s:
        return await s.get(AutomationRule, rid)


# ── nudge_online: TWO stores — config.enabled (gate) + rule (cadence) ──

_NUDGE_CFG = {
    "enabled": True, "delay_minutes": 0, "jitter_minutes": 0,
    "gap_minutes": 5, "quiet_hours": [0, 0], "require_welcomed": False,
    "max_per_tick": 25, "online_recent_minutes": 5,
    "min_hours_between_nudges": 12, "max_no_reply": 3, "active_convo_hours": 6,
    "nudge_line_text": True, "nudge_line_image": False,
}


async def _nudge_tab_save(aid: str, enabled: bool, rule_id: int | None) -> int:
    """NudgeOnlineTab.save(): PUT the config (which syncs the detector rule
    server-side), THEN patch the rule it already knows about — or, on a first
    save, just refetch the one the PUT created (no client-side POST: that made a
    second 60s detector)."""
    await put_nudge_config(_ConfigBody(account_id=aid, config={**_NUDGE_CFG, "enabled": enabled}))
    if rule_id is None:
        async with get_session() as s:
            rid = (await s.execute(select(AutomationRule.id).where(
                AutomationRule.account_id == aid,
                AutomationRule.kind == "nudge_online"))).scalars().all()
        assert len(rid) == 1, f"PUT must leave exactly one nudge_online rule, got {rid}"
        return rid[0]
    await update_rule(rule_id, RulePatch(every_seconds=60, payload={}, is_enabled=enabled))
    return rule_id


async def _warm_with_queued_fire(aid: str, fan: int) -> None:
    """Warm the account, then let the materialized detector job enqueue ONE due
    nudge_online_fire job for `fan` (delay 0)."""
    async with get_session() as s:
        s.add(NudgeState(account_id=aid, fan_id=1,
                         last_seen_online_at=datetime.utcnow() - timedelta(days=1)))
        # PUT drops `require_welcomed` (not in _validate_config), so the default
        # welcomed-gate holds: give the fan an old welcome.
        s.add(WelcomeSent(account_id=aid, fan_id=fan,
                          sent_at=datetime.utcnow() - timedelta(days=2)))
    await _materialize_due_rules()
    assert len(await _jobs(aid, "nudge_online", "pending")) == 1, "ON must schedule the detector"
    res = await run_once(aid, "nudge_online")
    assert res.get("enqueued") == 1, res
    fires = await _jobs(aid, "nudge_online_fire", "pending")
    assert len(fires) == 1 and json.loads(fires[0].payload_json)["fan_id"] == fan, fires


async def case_nudge_online_config_off_stops_detector_and_queued_fire():
    # Control: ON end to end → the queued fire really sends.
    on = "w_no_ctl"
    await _seed_account(on)
    fake = _use_fake(online=[5101])
    await _nudge_tab_save(on, True, None)
    await _warm_with_queued_fire(on, 5101)
    res = await run_once(on, "nudge_online_fire")
    assert res.get("sent") == 1 and len(fake.dms) == 1, (res, fake.dms)

    # OFF via the tab while a fire job is already queued.
    aid = "w_no_off"
    await _seed_account(aid)
    fake = _use_fake(online=[5201])
    rid = await _nudge_tab_save(aid, True, None)
    await _warm_with_queued_fire(aid, 5201)
    await _nudge_tab_save(aid, False, rid)
    assert (await _rule(rid)).is_enabled is False

    res = await run_once(aid, "nudge_online_fire")
    assert res.get("sent") == 0 and res.get("skipped") == "disabled", res
    assert fake.dms == [], fake.dms
    # And the detector itself no-ops on the config flag (e.g. a Run-now press).
    det = await run_once(aid, "nudge_online", payload={})
    assert det.get("enabled") is False and det.get("enqueued") == 0, det


async def case_nudge_online_put_syncs_rule():
    aid = "w_no_sync"
    await _seed_account(aid)
    rule = await create_rule(RuleCreate(account_id=aid, kind="nudge_online", name="Nudge online",
                                        every_seconds=60, payload={}, is_enabled=False))
    # Tab save, turning ON — the PUT lands, the rule PATCH after it does not.
    await put_nudge_config(_ConfigBody(account_id=aid, config={**_NUDGE_CFG, "enabled": True}))
    assert (await _rule(rule["id"])).is_enabled is True, \
        "config says ON (and the tab shows ON) but the rule that runs the engine is OFF"
    await put_nudge_config(_ConfigBody(account_id=aid, config={**_NUDGE_CFG, "enabled": False}))
    assert (await _rule(rule["id"])).is_enabled is False


async def case_nudge_online_rule_off_stops_queued_fire():
    aid = "w_no_rule_off"
    await _seed_account(aid)
    fake = _use_fake(online=[5301])
    rid = await _nudge_tab_save(aid, True, None)
    await _warm_with_queued_fire(aid, 5301)
    # ReadyMadePanel.tsx:178 / AutomationsPanel.tsx:116 — rule only, config untouched.
    await update_rule(rid, RulePatch(is_enabled=False))

    await run_once(aid, "nudge_online_fire")
    assert fake.dms == [], f"nudge sent after the rule was switched off: {fake.dms}"


_harness.run()
