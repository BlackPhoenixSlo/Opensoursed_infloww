#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import llm_client  # noqa: E402
import webhook_dispatch as wd  # noqa: E402
from automation_executor import acquire_fan_lease, run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    AccountAiConfig,
    AutomationRule,
    Fan,
    Message,
    ScheduledJob,
)



class FakeOF:

    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self._next_id = 9_000_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._next_id += 1
        self.sent.append((int(chat_id), text))
        return {"id": self._next_id, "text": f"<p>{text}</p>",
                "createdAt": "2026-06-04T12:30:00+00:00"}

    def set_fan_custom_name(self, user_id, name) -> dict:
        return {"success": True}

    def set_fan_note(self, user_id, note) -> dict:
        return {"success": True}

    def mark_chat_read(self, chat_id) -> dict:
        return {"success": True}


def _use_fake() -> FakeOF:
    fake = FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _patch_llm(reply: str = "heyy what are you up to tonight? 😏") -> None:
    async def _fake_chat(**kw):
        return SimpleNamespace(content=reply, call_id=1)
    llm_client.chat = _fake_chat  # type: ignore[attr-defined]



_T0 = datetime(2026, 6, 4, 12, 0, 0)


async def _seed_account(aid: str, *, webhook_enabled: bool = False) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        if webhook_enabled and await s.get(AccountAiConfig, aid) is None:
            s.add(AccountAiConfig(
                account_id=aid,
                webhook_config_json=json.dumps({"enabled": True}),
            ))
            s.add(AutomationRule(account_id=aid, name="info gather",
                                 kind="welcome_chatter_for_info",
                                 trigger_json=json.dumps({"every_seconds": 60}),
                                 steps_json="{}", is_enabled=True))


async def _seed_eligible_fan(aid: str, fan_id: int) -> None:
    async with get_session() as s:
        if await s.get(Fan, (aid, fan_id)) is None:
            s.add(Fan(account_id=aid, fan_id=fan_id,
                      of_display_name="Bob", lifetime_spend_cents=0))
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=fan_id * 10 + 1,
                      direction="out", body="hey babe", created_at=_T0))
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=fan_id * 10 + 2,
                      direction="in", body="hi! how are you", created_at=_T0 + timedelta(minutes=1)))


async def _pending_welcome_chatter_for_info(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid,
                ScheduledJob.kind == "welcome_chatter_for_info",
                ScheduledJob.status == "pending",
            )
        )).scalars().all())



async def case_real_webhook_then_sweep_one_send():
    aid, fan = "w7c_e2e", 7001
    await _seed_account(aid, webhook_enabled=True)
    await _seed_eligible_fan(aid, fan)
    fake = _use_fake()
    _patch_llm()

    orig_wake = ax.wake_supervisor
    ax.wake_supervisor = lambda: None  # type: ignore[assignment]
    try:
        await wd.on_inbound_message(aid, fan, message_id=999)
    finally:
        ax.wake_supervisor = orig_wake

    jobs = await _pending_welcome_chatter_for_info(aid)
    assert len(jobs) == 1, f"webhook must enqueue exactly one welcome_chatter_for_info job, got {len(jobs)}"
    payload = json.loads(jobs[0].payload_json or "{}")
    assert isinstance(payload.pop("_rule_id", None), int), ("tagged with its rule", payload)
    assert payload == {"only_fan_ids": [fan]}, ("fan-scoped, not a full sweep", payload)

    res1 = await run_once(aid, "welcome_chatter_for_info", payload=payload)
    assert res1["replies_sent"] == 1, res1
    assert await ax.fan_on_cooldown(aid, fan) is True, "a reply must rest the fan"

    res2 = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res2["replies_sent"] == 0, ("sweep must not double-reply a just-replied fan", res2)

    assert len(fake.sent) == 1, ("exactly one send across webhook + sweep", fake.sent)
    to, body = fake.sent[0]
    assert to == fan, fake.sent
# split_for_bubbles may drop a trailing emoji (seeded off the draft, stable per body)
    assert body in (
        "heyy what are you up to tonight? 😏",
        "heyy what are you up to tonight?",
    ), fake.sent


async def case_sweep_holds_lease_webhook_skips():
    aid = "w7c_lease"
    held, free = 7101, 7102
    await _seed_account(aid)
    await _seed_eligible_fan(aid, held)
    await _seed_eligible_fan(aid, free)
    fake = _use_fake()
    _patch_llm()

    assert await acquire_fan_lease(aid, held, "welcome_chatter_for_info", ttl_s=300) is True

    res = await run_once(aid, "welcome_chatter_for_info", payload={"only_fan_ids": [held, free]})
    assert res["skipped_locked"] == 1, ("leased fan must be skipped_locked", res)
    assert res["replies_sent"] == 1, res
    assert {c for c, _ in fake.sent} == {free}, ("leased fan must not be messaged", fake.sent)


async def case_webhook_then_sweep_one_send():
    aid, fan = "w7c_cooldown", 7201
    await _seed_account(aid)
    await _seed_eligible_fan(aid, fan)
    fake = _use_fake()
    _patch_llm()

    res1 = await run_once(aid, "welcome_chatter_for_info", payload={"only_fan_ids": [fan]})
    assert res1["replies_sent"] == 1, res1

    res2 = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res2["replies_sent"] == 0, ("cooldown must block the follow-on sweep", res2)

    assert len(fake.sent) == 1, ("exactly one send across both triggers", fake.sent)
    async with get_session() as s:
        out = (await s.execute(
            select(Message).where(
                Message.account_id == aid, Message.fan_id == fan,
                Message.direction == "out", Message.message_id >= 9_000_000_000_000,
            )
        )).scalars().all()
    assert len(out) == 1, ("one persisted reply", out)


_harness.run(
    case_real_webhook_then_sweep_one_send,
    case_sweep_holds_lease_webhook_skips,
    case_webhook_then_sweep_one_send,
)
