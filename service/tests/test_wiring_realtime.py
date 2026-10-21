#!/usr/bin/env python3
"""
On/off WIRING checkpoints — the W7 "Reply Instant" real-time webhook dispatch.

Each case writes the switch straight into the persisted column
(account_ai_config.webhook_config_json — the editor route is retired, so only the
stored config remains) → the runtime gate that reads it, and asserts OFF
dispatches nothing and ON dispatches.

  Formerly-known bug (now fixed — kept as a regression guard):
    • W7 ON wakes `welcome_chatter_for_info` for a plain fan even when that
      engine's rule is OFF, so the info-gather "off" switch is bypassed by every
      inbound DM while Reply Instant is on.

Run: ./venv/bin/python service/tests/test_wiring_realtime.py  (exit 0 = pass)
"""
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

ax.wake_supervisor = lambda: None  # no supervisor loop in tests


# ── helpers ──────────────────────────────────────────────────────────

async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _put_webhook(aid: str, config: dict) -> None:
    """Store the Reply Instant config the way the retired editor did."""
    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
        if row is None:
            s.add(AccountAiConfig(account_id=aid, webhook_config_json=json.dumps(config)))
        else:
            row.webhook_config_json = json.dumps(config)


async def _give_w7_switches(aid: str) -> int:
    """What the retired editor did on off → on (and the boot backfill still does):
    a cadence-less enabled rule for each gated kind with no rule row."""
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


# ── W7 Reply Instant ─────────────────────────────────────────────────

async def case_webhook_put_persists_and_gates_dispatch():
    aid, fan = "wv_w7", 7101
    await _seed_account(aid)
    # W7 only wakes the info-gather engine while its rule is ON (see the
    # rule-OFF case below) — this case is about the Reply Instant switch.
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

    # Flip OFF: no NEW dispatch. The job queued while ON stays pending — by
    # design it is a fan-scoped run of the ordinary chat engine (the same reply
    # the 30s sweep gives once Reply Instant is off), so it is not cancelled.
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
    """Default build: the info-gather / funnel switches are hidden, so Reply
    Instant ON gives a kind with NO rule a cadence-less enabled one
    (ensure_w7_rule_switches) — and the realtime path then enqueues. An existing
    disabled row stays off."""
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
    # Cadence-less: the materializer schedules no periodic sweep for it.
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
    """The one-time boot backfill (db.engine.backfill_w7_rules_once): an account
    with Reply Instant ON and NO rule of a gated kind gets an enabled, cadence-less
    one; an existing (even disabled) row is left alone; Reply Instant OFF gets
    nothing; and the marker stops it from ever running again."""
    from sqlalchemy import create_engine, text
    import sys
    dbe = sys.modules["db.engine"]  # `db.engine` the name is the AsyncEngine

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
        # Boot (harness bootstrap) already stamped it on this fresh DB → no-op.
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

        # Never twice: an operator deleting the switch afterwards keeps it deleted.
        async with get_session() as s:
            for r in (await s.execute(select(AutomationRule).where(
                    AutomationRule.account_id == on_bare))).scalars():
                await s.delete(r)
        assert dbe.backfill_w7_rules_once(sync) == 0
        assert await _rules(on_bare) == set()
    finally:
        sync.dispose()


_harness.run()
