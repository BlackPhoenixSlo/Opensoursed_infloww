#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import os  # noqa: E402

os.environ.pop("W7_WEBHOOK_DISPATCH_DISABLED", None)

_harness.bootstrap()

import json  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import webhook_dispatch as wd  # noqa: E402
from db.engine import ensure_w7_rule_switches, get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AutomationRule, ScheduledJob,
)

ax.wake_supervisor = lambda: None



async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _put_webhook(aid: str, config: dict) -> None:
    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
        if row is None:
            s.add(AccountAiConfig(account_id=aid, webhook_config_json=json.dumps(config)))
        else:
            row.webhook_config_json = json.dumps(config)


async def _give_w7_switches(aid: str) -> int:
    async with get_session() as s:
        return await s.run_sync(lambda ss: ensure_w7_rule_switches(ss.connection(), aid))


async def _stored(aid: str, col: str) -> dict:
    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
    return json.loads(getattr(row, col) or "{}") if row is not None else {}


async def _jobs(aid: str, kind: str | None = None, status: str | None = "pending"):
    async with get_session() as s:
        q = select(ScheduledJob).where(ScheduledJob.account_id == aid)
        if kind:
            q = q.where(ScheduledJob.kind == kind)
        if status:
            q = q.where(ScheduledJob.status == status)
        return (await s.execute(q.order_by(ScheduledJob.id))).scalars().all()



async def case_webhook_put_persists_and_gates_dispatch():
    aid, fan = "wv_w7", 7101
    await _seed_account(aid)
    async with get_session() as s:
        s.add(AutomationRule(account_id=aid, name="info gather", kind="welcome_chatter_for_info",
                             trigger_json=json.dumps({"every_seconds": 60}),
                             steps_json="{}", is_enabled=True))
    await _put_webhook(aid, {"enabled": False})
    assert (await _stored(aid, "webhook_config_json"))["enabled"] is False
    await wd.on_inbound_message(aid, fan, 1)
    assert not await _jobs(aid), "OFF must enqueue nothing"

    await _put_webhook(aid, {"enabled": True})
    assert (await _stored(aid, "webhook_config_json"))["enabled"] is True
    await wd.on_inbound_message(aid, fan, 2)
    jobs = await _jobs(aid)
    assert len(jobs) == 1 and json.loads(jobs[0].payload_json).get("only_fan_ids") == [fan], \
        [(j.kind, j.payload_json) for j in jobs]

    await _put_webhook(aid, {"enabled": False})
    await wd.on_inbound_message(aid, fan + 1, 3)
    assert len(await _jobs(aid)) == 1, "OFF must not dispatch new inbound DMs"


async def case_webhook_env_kill_switch_beats_on():
    aid, fan = "wv_w7_kill", 7201
    await _seed_account(aid)
    await _put_webhook(aid, {"enabled": True})
    os.environ["W7_WEBHOOK_DISPATCH_DISABLED"] = "1"
    try:
        await wd.on_inbound_message(aid, fan, 1)
    finally:
        os.environ.pop("W7_WEBHOOK_DISPATCH_DISABLED", None)
    assert not await _jobs(aid), "kill switch must beat the per-account ON"


async def case_w7_does_not_wake_disabled_welcome_chatter():
    aid, fan = "wv_w7_rule_off", 7301
    await _seed_account(aid)
    async with get_session() as s:
        s.add(AutomationRule(account_id=aid, name="info gather", kind="welcome_chatter_for_info",
                             trigger_json=json.dumps({"every_seconds": 60}),
                             steps_json="{}", is_enabled=False))
    await _put_webhook(aid, {"enabled": True})
    await wd.on_inbound_message(aid, fan, 1)
    got = [j.kind for j in await _jobs(aid)]
    assert "welcome_chatter_for_info" not in got, \
        f"W7 woke welcome_chatter_for_info although its rule is OFF: {got}"


async def case_reply_instant_on_gives_a_new_account_its_switches():
    aid, fan = "wv_w7_new", 7401
    await _seed_account(aid)
    await _put_webhook(aid, {"enabled": True})
    await _give_w7_switches(aid)

    async def _rules(a):
        async with get_session() as s:
            return {(r.kind, r.is_enabled, r.trigger_json) for r in (await s.execute(
                select(AutomationRule).where(AutomationRule.account_id == a))).scalars()}

    assert await _rules(aid) == {("welcome_chatter_for_info", True, "{}"),
                                 ("reply_mass_funnel", True, "{}")}
    await wd.on_inbound_message(aid, fan, 1)
    jobs = await _jobs(aid)
    assert [j.kind for j in jobs] == ["welcome_chatter_for_info"], \
        [(j.kind, j.payload_json) for j in jobs]
    async with get_session() as s:
        for j in jobs:
            await s.delete(await s.get(ScheduledJob, j.id))
    await ax._materialize_due_rules()
    assert not await _jobs(aid), "a cadence-less switch must not sweep"

    off = "wv_w7_off_row"
    await _seed_account(off)
    async with get_session() as s:
        s.add(AutomationRule(account_id=off, name="info", kind="welcome_chatter_for_info",
                             trigger_json="{}", steps_json="{}", is_enabled=False))
    await _put_webhook(off, {"enabled": True})
    await _give_w7_switches(off)
    assert await _rules(off) == {("welcome_chatter_for_info", False, "{}"),
                                 ("reply_mass_funnel", True, "{}")}, "disabled row stays off"
    await wd.on_inbound_message(off, fan, 2)
    assert "welcome_chatter_for_info" not in [j.kind for j in await _jobs(off)]

async def case_w7_rule_backfill_keeps_reply_instant_accounts_answered_once():
    from sqlalchemy import create_engine, text
    import sys
    dbe = sys.modules["db.engine"]

    on_bare, on_off, off = "bf_on_bare", "bf_on_off", "bf_off"
    for aid in (on_bare, on_off, off):
        await _seed_account(aid)
    async with get_session() as s:
        for aid, enabled in ((on_bare, True), (on_off, True), (off, False)):
            s.add(AccountAiConfig(account_id=aid,
                                  webhook_config_json=json.dumps({"enabled": enabled})))
        s.add(AutomationRule(account_id=on_off, name="info", kind="welcome_chatter_for_info",
                             trigger_json="{}", steps_json="{}", is_enabled=False))

    sync = create_engine(dbe.DATABASE_URL.replace("+aiosqlite", ""))
    try:
        # never twice: an operator deleting the switch afterwards keeps it deleted
        assert dbe.backfill_w7_rules_once(sync) == 0
        with sync.begin() as c:
            c.execute(text("DELETE FROM data_migrations WHERE name = :n"),
                      {"n": dbe._W7_RULE_BACKFILL})
        assert dbe.backfill_w7_rules_once(sync) >= 3

        async def _rules(aid):
            async with get_session() as s:
                return {(r.kind, r.is_enabled, r.trigger_json) for r in (await s.execute(
                    select(AutomationRule).where(AutomationRule.account_id == aid))).scalars()}

        assert await _rules(on_bare) == {("welcome_chatter_for_info", True, "{}"),
                                         ("reply_mass_funnel", True, "{}")}
        assert await _rules(on_off) == {("welcome_chatter_for_info", False, "{}"),
                                        ("reply_mass_funnel", True, "{}")}, "disabled row stays off"
        assert await _rules(off) == set()
        assert await ax.enabled_rule_id(on_bare, "welcome_chatter_for_info") is not None

        async with get_session() as s:
            for r in (await s.execute(select(AutomationRule).where(
                    AutomationRule.account_id == on_bare))).scalars():
                await s.delete(r)
        assert dbe.backfill_w7_rules_once(sync) == 0
        assert await _rules(on_bare) == set()
    finally:
        sync.dispose()


_harness.run()
