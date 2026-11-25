#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

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
from db.models import AccountAiConfig  # noqa: E402
from nudge_config_api import _BulkBody, _ConfigBody, put_nudge_config, put_nudge_config_bulk  # noqa: E402



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



_NUDGE_CFG = {
    "enabled": True, "delay_minutes": 0, "jitter_minutes": 0,
    "gap_minutes": 5, "quiet_hours": [0, 0], "require_welcomed": False,
    "max_per_tick": 25, "online_recent_minutes": 5,
    "min_hours_between_nudges": 12, "max_no_reply": 3, "active_convo_hours": 6,
    "nudge_line_text": True, "nudge_line_image": False,
}


async def _nudge_tab_save(aid: str, enabled: bool, rule_id: int | None) -> int:
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
    async with get_session() as s:
        s.add(NudgeState(account_id=aid, fan_id=1,
                         last_seen_online_at=datetime.utcnow() - timedelta(days=1)))
        s.add(WelcomeSent(account_id=aid, fan_id=fan,
                          sent_at=datetime.utcnow() - timedelta(days=2)))
    await _materialize_due_rules()
    assert len(await _jobs(aid, "nudge_online", "pending")) == 1, "ON must schedule the detector"
    res = await run_once(aid, "nudge_online")
    assert res.get("enqueued") == 1, res
    fires = await _jobs(aid, "nudge_online_fire", "pending")
    assert len(fires) == 1 and json.loads(fires[0].payload_json)["fan_id"] == fan, fires


async def case_nudge_online_config_off_stops_detector_and_queued_fire():
    on = "w_no_ctl"
    await _seed_account(on)
    fake = _use_fake(online=[5101])
    await _nudge_tab_save(on, True, None)
    await _warm_with_queued_fire(on, 5101)
    res = await run_once(on, "nudge_online_fire")
    assert res.get("sent") == 1 and len(fake.dms) == 1, (res, fake.dms)

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
    det = await run_once(aid, "nudge_online", payload={})
    assert det.get("enabled") is False and det.get("enqueued") == 0, det


async def case_nudge_online_put_syncs_rule():
    aid = "w_no_sync"
    await _seed_account(aid)
    rule = await create_rule(RuleCreate(account_id=aid, kind="nudge_online", name="Nudge online",
                                        every_seconds=60, payload={}, is_enabled=False))
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
    await update_rule(rid, RulePatch(is_enabled=False))

    await run_once(aid, "nudge_online_fire")
    assert fake.dms == [], f"nudge sent after the rule was switched off: {fake.dms}"



async def _saved(aid: str) -> dict:
    async with get_session() as s:
        return json.loads((await s.get(AccountAiConfig, aid)).nudge_config_json)


async def case_nudge_online_share_keeps_each_models_images():
    src, tgt, fresh = "w_share_src", "w_share_tgt", "w_share_new"
    for a in (src, tgt, fresh):
        await _seed_account(a)
    await put_nudge_config(_ConfigBody(account_id=tgt, config={**_NUDGE_CFG, "enabled": False, "slots": {
        "default": {"evening": {"text": ["old"], "image": [901]}},
        "friday": {"night": {"text": [], "image": [902]}},
    }}))
    shared = {**_NUDGE_CFG, "enabled": True, "nudge_line_image": True, "delay_minutes": 9, "slots": {
        "default": {"evening": {"text": ["eve {name}"], "image": [11]}, "night": {"text": ["n"], "image": [12]}},
    }}
    r = await put_nudge_config_bulk(_BulkBody(account_ids=[tgt, fresh], config=shared))
    assert r["count"] == 2 and r["enabled"] is True, r

    t = await _saved(tgt)
    assert t["delay_minutes"] == 9 and t["nudge_line_image"] is True, t
    assert t["slots"] == {
        "default": {"evening": {"text": ["eve {name}"], "image": [901]}, "night": {"text": ["n"], "image": []}},
        "friday": {"night": {"text": [], "image": [902]}},
    }, t["slots"]
    assert (await _saved(fresh))["slots"] == {
        "default": {"evening": {"text": ["eve {name}"], "image": []}, "night": {"text": ["n"], "image": []}},
    }
    for a in (tgt, fresh):
        async with get_session() as s:
            on = (await s.execute(select(AutomationRule.is_enabled).where(
                AutomationRule.account_id == a, AutomationRule.kind == "nudge_online"))).scalars().all()
        assert on == [True], (a, on)

    await put_nudge_config_bulk(_BulkBody(account_ids=[tgt], config={**shared, "enabled": False}))
    async with get_session() as s:
        on = (await s.execute(select(AutomationRule.is_enabled).where(
            AutomationRule.account_id == tgt, AutomationRule.kind == "nudge_online"))).scalars().all()
    assert on == [False], on

    r = await put_nudge_config_bulk(_BulkBody(account_ids=[tgt], config={"delay_minutes": 7}))
    async with get_session() as s:
        on = (await s.execute(select(AutomationRule.is_enabled).where(
            AutomationRule.account_id == tgt, AutomationRule.kind == "nudge_online"))).scalars().all()
    assert on == [False], ("no `enabled` sent: the parked rule stays parked", on)
    assert r["enabled"] is None and r["applied"] == [{"account_id": tgt, "rule": "unchanged"}], r
    assert (await _saved(tgt))["delay_minutes"] == 7



async def case_nudge_config_slots_shape_is_checked():
    from fastapi import HTTPException
    aid = "w_slots_shape"
    await _seed_account(aid)
    bad = [
        {"default": {"evening": {"text": "hey there"}}},
        {"default": {"evening": {"text": ["ok"], "image": ["abc"]}}},
        {"default": {"evening": {"text": ["ok"], "image": [True]}}},
        {"funday": {"evening": {"text": ["ok"]}}},
        {"default": {"brunch": {"text": ["ok"]}}},
        {"default": {"evening": "hey"}},
        {"default": ["evening"]},
        {"default": {"evening": {"text": [3]}}},
    ]
    for slots in bad:
        for call in (lambda: put_nudge_config(_ConfigBody(account_id=aid, config={"slots": slots})),
                     lambda: put_nudge_config_bulk(_BulkBody(account_ids=[aid], config={"slots": slots}))):
            try:
                await call()
                raise AssertionError(f"accepted {slots}")
            except HTTPException as e:
                assert e.status_code == 422, (slots, e.status_code)
    r = await put_nudge_config(_ConfigBody(account_id=aid, config={"slots": {
        "default": {"evening": {"text": ["hi {name}"], "image": ["901", 902], "x": 1}},
        "friday": {"night": {"image": [7]}}, "weekend": {"night": {"text": None, "image": None}}}}))
    assert r["config"]["slots"] == {
        "default": {"evening": {"text": ["hi {name}"], "image": [901, 902]}},
        "friday": {"night": {"text": [], "image": [7]}},
        "weekend": {"night": {"text": [], "image": []}}}, r["config"]["slots"]



async def case_nudge_config_legacy_null_slot_still_saves():
    aid = "w_slots_legacy_null"
    await _seed_account(aid)
    legacy = {"friday": None, "default": {"evening": {"text": ["hi"]}, "night": None}}
    want = {"default": {"evening": {"text": ["hi"], "image": []}}}
    r = await put_nudge_config(_ConfigBody(account_id=aid, config={"enabled": False, "slots": legacy}))
    assert r["config"]["slots"] == want, r["config"]
    assert r["config"]["enabled"] is False, r["config"]
    r = await put_nudge_config_bulk(_BulkBody(account_ids=[aid], config={"enabled": False, "slots": legacy}))
    assert (r["count"], r["enabled"]) == (1, False), r
    async with get_session() as s:
        stored = json.loads((await s.get(AccountAiConfig, aid)).nudge_config_json)
    assert stored["slots"] == want, stored

_harness.run()
