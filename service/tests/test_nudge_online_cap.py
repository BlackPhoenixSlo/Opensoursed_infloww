#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import automation_executor as ax  # noqa: E402
import llm_client  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import nudge_online  # noqa: E402 — module under test (registers)
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AutomationRule, NudgeState,
)
from llm_client import LLMCapExceeded  # noqa: E402

KIND = "nudge_online"
_CFG = {
    "enabled": True, "delay_minutes": 0, "jitter_minutes": 0, "gap_minutes": 5,
    "quiet_hours": [0, 0], "require_welcomed": False, "max_per_tick": 25,
    "online_recent_minutes": 5, "min_hours_between_nudges": 12, "max_no_reply": 3,
    "active_convo_hours": 6, "nudge_line_text": True, "nudge_line_image": False,
}


class FakeOF:
    def __init__(self, online: list[dict]):
        self.user_id = "999"
        self._online = online
        self.sent: list = []

    def iter_online_subscribers(self, *, type: str = "active", page_size: int = 20,
                                max_fans: int = 1000) -> list[dict]:
        return list(self._online[:max_fans])

    def send_message(self, chat_id, text, **kw) -> dict:
        self.sent.append((int(chat_id), text))
        return {"id": 1, "text": text}


def _use(online: list[dict]) -> FakeOF:
    fake = FakeOF(online)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _capped(aid: str) -> list:
    calls: list = []

    async def _chat(**kw):
        calls.append(kw)
        raise LLMCapExceeded(aid, 100, 200)
    llm_client.chat = _chat  # type: ignore[assignment]
    return calls


async def _seed(aid: str) -> None:
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(AccountAiConfig(account_id=aid, utc_offset=0, nudge_config_json=json.dumps(_CFG)))
        s.add(AutomationRule(account_id=aid, name="Nudge online", kind=KIND,
                             trigger_json=json.dumps({"every_seconds": 60}),
                             steps_json="{}", is_enabled=True))


async def _warm(aid: str) -> None:
    async with get_session() as s:
        s.add(NudgeState(account_id=aid, fan_id=1,
                         last_seen_online_at=datetime.utcnow() - timedelta(days=1)))


async def _tick(aid: str, payload: dict) -> int:
    res = await run_once(aid, KIND, payload=payload)
    assert res["status"] == "ok", res
    return res["enqueued"]


async def _preview(aid: str) -> int:
    cfg = await nudge_online._load_nudge_config(aid)
    prev = await nudge_online.preview_compose(aid, cfg, hour=20)
    assert [m["kind"] for m in prev["messages"]] == ["nudge"] and prev["messages"][0]["text"], prev
    return len(prev["messages"])


async def case_no_llm_on_any_nudge_path():
    rows = [
        ("warmup tick", False, [{"id": 3201}, {"id": 3202}], lambda a: _tick(a, {}), 0),
        ("newly-online tick", True, [{"id": 3101, "name": "Ann"}], lambda a: _tick(a, {}), 1),
        ("test_fan tick", False, [{"id": 3301}, {"id": 3302}],
         lambda a: _tick(a, {"test_fan": 3301}), 1),
        ("preview", False, [], _preview, 1),
    ]
    for i, (label, warmed, online, path, exp_out) in enumerate(rows):
        aid = f"nc_{i}"
        await _seed(aid)
        if warmed:
            await _warm(aid)
        fake = _use(online)
        calls = _capped(aid)
        out = await path(aid)
        assert out == exp_out, f"[{label}] output {out}, expected {exp_out}"
        assert calls == [], f"[{label}] LLM called: {calls}"
        assert fake.sent == [], f"[{label}] sent: {fake.sent}"


_harness.run(case_no_llm_on_any_nudge_path)
