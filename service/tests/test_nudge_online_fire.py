#!/usr/bin/env python3
"""nudge_online_fire — characterisation of the delayed one-shot (pins today's
behaviour; the detector half lives in test_nudge_online.py).

  case_happy_sends_once_and_bumps_state:
      a still-online fan → exactly one send to HIM, one outbound row tagged
      `nudge_online`, and `_bump_after_send` observable on NudgeState:
      nudge_count +1, rotation idx advanced, slot written, pending cleared,
      no-reply streak +1; the lease is released; no LLM call.
  case_reply_since_last_nudge_resets_streak:
      a fan who replied after his last nudge (outside active_convo_hours)
      → sent, no-reply streak reset to 1.
  case_no_state_row_sends_nothing:
      no NudgeState row (nothing pending, never seen) → `offline`, no send,
      and no row is created by the clear.
  case_offline_clears_pending_and_sends_nothing:
      last seen online 30 min ago (> online_recent_minutes) with a job
      pending → `offline`, pending cleared, no send.
  case_rule_off_clears_pending_and_sends_nothing:
      a fire queued while the detector rule was on, run after it went off →
      `rule_disabled`, pending cleared, no send.
  case_no_id_send_result_still_counts_and_bumps:
      OF answers 200 with no message id → PINNED TODAY: counted `sent: 1`,
      NO outbound row written, NudgeState bumped as a real send, no
      quarantine/pause (see the report's open finding).
  case_send_error_clears_pending_and_does_not_raise:
      a send that raises → `skipped: error`, no crash, pending cleared,
      nudge_count untouched, no outbound row, lease released.

House style: plain asserts, no pytest; _harness temp DB; the real `run_once`
with a FakeOF on `ax._make_client`; `llm_client.chat` patched.

Run: ./venv/bin/python service/tests/test_nudge_online_fire.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import llm_client  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import nudge_online_fire  # noqa: E402,F401 — registers the kind
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AutomationRule, Fan, FanLease, Message, NudgeState,
)

KIND = "nudge_online_fire"
_SLOT_KEYS = ("morning_1", "morning_2", "afternoon_1", "afternoon_2", "evening", "night")
# One 3-line pool for every slot, so the rotation index is deterministic.
_SLOTS = {"default": {k: {"text": ["hey {name} a", "hey {name} b", "hey {name} c"],
                          "image": []} for k in _SLOT_KEYS}}
_CFG = {
    "enabled": True, "delay_minutes": 0, "jitter_minutes": 0, "gap_minutes": 5,
    "quiet_hours": [0, 0], "require_welcomed": False, "online_recent_minutes": 5,
    "min_hours_between_nudges": 12, "max_no_reply": 3, "active_convo_hours": 6,
    "nudge_line_text": True, "nudge_line_image": False, "repeat_mode": "new",
    "slots": _SLOTS,
}


class FakeOF:
    def __init__(self):
        self.user_id = "999"
        self.sent: list[tuple[int, str, list]] = []
        self._next_id = 8_100_000_000_000

    def send_message(self, chat_id, text, *, media_files=None, **kw) -> dict:
        self._next_id += 1
        self.sent.append((int(chat_id), text, list(media_files or [])))
        return {"id": self._next_id, "text": f"<p>{text}</p>",
                "createdAt": "2026-06-05T12:00:00+00:00"}


class NoIdOF(FakeOF):
    """OF answers 200 but echoes no message id."""

    def send_message(self, chat_id, text, *, media_files=None, **kw) -> dict:
        self.sent.append((int(chat_id), text, list(media_files or [])))
        return {"success": True}


class RaisingOF(FakeOF):
    def send_message(self, chat_id, text, *, media_files=None, **kw) -> dict:
        self.sent.append((int(chat_id), text, list(media_files or [])))
        raise RuntimeError("upstream exploded")


def _use(fake: FakeOF) -> FakeOF:
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _llm(calls: list):
    async def _chat(**kw):
        calls.append(kw)
        return SimpleNamespace(content="unused", call_id=1)
    llm_client.chat = _chat  # type: ignore[assignment]


async def _seed(aid: str, *, rule: bool = True) -> None:
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(AccountAiConfig(account_id=aid, utc_offset=0, nudge_config_json=json.dumps(_CFG)))
        if rule:
            s.add(AutomationRule(account_id=aid, name="Nudge online", kind="nudge_online",
                                 trigger_json=json.dumps({"every_seconds": 60}),
                                 steps_json="{}", is_enabled=True))


async def _seed_fan(aid: str, fan_id: int, **state) -> None:
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fan_id, real_name="Ed"))
        if state:
            s.add(NudgeState(account_id=aid, fan_id=fan_id, **state))


async def _state(aid: str, fan_id: int) -> NudgeState | None:
    async with get_session() as s:
        return await s.get(NudgeState, (aid, fan_id))


async def _outs(aid: str) -> list[Message]:
    async with get_session() as s:
        return list((await s.execute(select(Message).where(
            Message.account_id == aid, Message.direction == "out"))).scalars())


async def _lease(aid: str, fan_id: int) -> FanLease | None:
    async with get_session() as s:
        return await s.get(FanLease, (aid, fan_id))


def _online_state(**over):
    """A fan seen online just now, a fire job pending, nudged 2 days ago."""
    return {"last_seen_online_at": datetime.utcnow(), "pending_job_id": 55,
            "last_nudged_at": datetime.utcnow() - timedelta(days=2), "nudge_count": 2,
            "no_reply_streak": 1, "last_variation_idx": 0, "last_slot": "evening", **over}


# ── happy ─────────────────────────────────────────────────────────────

async def case_happy_sends_once_and_bumps_state():
    aid = "nf_happy"
    await _seed(aid)
    await _seed_fan(aid, 501, **_online_state())
    await _seed_fan(aid, 502, **_online_state(pending_job_id=56))
    calls: list = []
    _llm(calls)

    fake = _use(FakeOF())
    res = await run_once(aid, KIND, payload={"fan_id": 501})
    assert res["status"] == "ok" and res["sent"] == 1, res
    assert res["fan_id"] == 501 and res["variation_idx"] == 1, res
    assert res["image_attached"] == 0, res
    assert [(f, t) for f, t, _m in fake.sent] == [(501, "hey Ed b")], fake.sent
    st = await _state(aid, 501)
    assert st.pending_job_id is None, "pending cleared by _bump_after_send"
    assert (st.nudge_count, st.no_reply_streak, st.last_variation_idx) == (3, 2, 1), st
    assert st.last_slot == res["slot"] and st.last_slot in _SLOT_KEYS, (st.last_slot, res)
    assert datetime.utcnow() - st.last_nudged_at < timedelta(minutes=1), st.last_nudged_at
    outs = await _outs(aid)
    assert [(m.fan_id, m.automation_kind) for m in outs] == [(501, "nudge_online")], outs
    assert await _lease(aid, 501) is None, "lease released after the send"
    # The other fan was not touched by 501's fire.
    other = await _state(aid, 502)
    assert other.pending_job_id == 56 and other.nudge_count == 2, other
    assert calls == [], "the fire never calls the LLM"


async def case_reply_since_last_nudge_resets_streak():
    aid = "nf_streak"
    await _seed(aid)
    await _seed_fan(aid, 511, **_online_state(no_reply_streak=2))
    # Replied after his last nudge (2 days ago), but a day ago — outside active_convo_hours.
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=511, message_id=5110001, direction="in",
                      body="hey", created_at=datetime.utcnow() - timedelta(days=1)))
    fake = _use(FakeOF())
    res = await run_once(aid, KIND, payload={"fan_id": 511})
    assert res["sent"] == 1, res
    assert [f for f, _t, _m in fake.sent] == [511], fake.sent
    st = await _state(aid, 511)
    assert (st.nudge_count, st.no_reply_streak, st.pending_job_id) == (3, 1, None), st


# ── nothing pending / rule off ────────────────────────────────────────

async def case_no_state_row_sends_nothing():
    aid = "nf_nostate"
    await _seed(aid)
    await _seed_fan(aid, 601)          # Fan row, no NudgeState
    fake = _use(FakeOF())
    res = await run_once(aid, KIND, payload={"fan_id": 601})
    assert res["status"] == "ok" and res["sent"] == 0 and res["skipped"] == "offline", res
    assert fake.sent == [], fake.sent
    assert await _state(aid, 601) is None, "the clear is an UPDATE: no row created"
    assert await _outs(aid) == []


async def case_offline_clears_pending_and_sends_nothing():
    aid = "nf_offline"
    await _seed(aid)
    await _seed_fan(aid, 651, **_online_state(
        last_seen_online_at=datetime.utcnow() - timedelta(minutes=30), pending_job_id=65))
    fake = _use(FakeOF())
    res = await run_once(aid, KIND, payload={"fan_id": 651})
    assert res["sent"] == 0 and res["skipped"] == "offline", res
    assert fake.sent == [], fake.sent
    st = await _state(aid, 651)
    assert st.pending_job_id is None and st.nudge_count == 2, st


async def case_rule_off_clears_pending_and_sends_nothing():
    aid = "nf_rule_off"
    await _seed(aid, rule=False)
    await _seed_fan(aid, 701, **_online_state(pending_job_id=77))
    fake = _use(FakeOF())
    res = await run_once(aid, KIND, payload={"fan_id": 701})
    assert res["sent"] == 0 and res["skipped"] == "rule_disabled", res
    assert fake.sent == [], fake.sent
    st = await _state(aid, 701)
    assert st.pending_job_id is None and st.nudge_count == 2, st
    assert await _outs(aid) == []


# ── no-id send result ─────────────────────────────────────────────────

async def case_no_id_send_result_still_counts_and_bumps():
    aid = "nf_noid"
    await _seed(aid)
    await _seed_fan(aid, 801, **_online_state(pending_job_id=88))
    fake = _use(NoIdOF())
    res = await run_once(aid, KIND, payload={"fan_id": 801})
    # PINNED TODAY: no id is still counted as a send and bumps state.
    assert res["status"] == "ok" and res["sent"] == 1, res
    assert [f for f, _t, _m in fake.sent] == [801], fake.sent
    assert await _outs(aid) == [], "no id → no attribution row"
    st = await _state(aid, 801)
    assert (st.nudge_count, st.pending_job_id) == (3, None), st
    async with get_session() as s:
        fan = await s.get(Fan, (aid, 801))
    assert fan.automation_paused_until is None, "no quarantine/pause today"
    assert await _lease(aid, 801) is None


# ── send error ────────────────────────────────────────────────────────

async def case_send_error_clears_pending_and_does_not_raise():
    aid = "nf_err"
    await _seed(aid)
    await _seed_fan(aid, 901, **_online_state(pending_job_id=99))
    fake = _use(RaisingOF())
    res = await run_once(aid, KIND, payload={"fan_id": 901})
    assert res["status"] == "ok", res
    assert res["sent"] == 0 and res["skipped"] == "error", res
    assert "upstream exploded" in res["error"], res
    assert [f for f, _t, _m in fake.sent] == [901], "one attempt, never retried"
    st = await _state(aid, 901)
    assert st.pending_job_id is None and st.nudge_count == 2, st
    assert await _outs(aid) == []
    assert await _lease(aid, 901) is None, "lease released in finally"


_harness.run(
    case_happy_sends_once_and_bumps_state,
    case_reply_since_last_nudge_resets_streak,
    case_no_state_row_sends_nothing,
    case_offline_clears_pending_and_sends_nothing,
    case_rule_off_clears_pending_and_sends_nothing,
    case_no_id_send_result_still_counts_and_bumps,
    case_send_error_clears_pending_and_does_not_raise,
)
