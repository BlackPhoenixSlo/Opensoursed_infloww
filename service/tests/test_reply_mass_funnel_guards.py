#!/usr/bin/env python3
"""
A11 reply_mass_funnel — guard characterisation (pins TODAY's behaviour).

reply_mass_funnel has no `force_ids` knob; its operator-explicit targeting is
`test_fan`, which (a) scopes the sweep to that one fan and (b) is exempt from the
include-only audience fence (`_audience_allows`). That is the gate pinned here.

  case_cap_stops_run_no_send:
      two due repliers on a generated (LLM) step; llm_client.chat raises
      LLMCapExceeded → the run ends `ok` with cap_hit=True, advanced=0,
      errors=0, the model is asked ONCE (the cap stops the sweep), nothing is
      sent, both states stay at step 0 pending, leases released, and the
      automation_runs row carries cap_hit.
  case_audience_fence_blocks_without_test_fan:
      control: enforce-mode audience whose include list is missing fails CLOSED
      → the replier is not enrolled, nothing sent, audience_skipped counted.
  case_test_fan_bypasses_audience_fence:
      the same fenced account with `test_fan=<target>` → the target is enrolled
      and advanced; a second replier on the same broadcast is not touched.

Run: ./venv/bin/python service/tests/test_reply_mass_funnel_guards.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import automations.reply_mass_funnel as a11  # noqa: E402 — module under test
import llm_client  # noqa: E402
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    AccountAiConfig,
    AutomationRun,
    FanLease,
    FunnelState,
    MassMessageFunnel,
    MassRun,
    Message,
)
from llm_client import LLMCapExceeded  # noqa: E402

a11._STEP_GAP_S = 0  # skip the human pause between bubbles (as the sibling does)

# Relative clock: discovery is bounded to young broadcasts (see sibling test).
T0 = datetime.utcnow().replace(microsecond=0) - timedelta(days=1)
T_REPLY = T0 + timedelta(minutes=5)
SEND_AT = (T0 + timedelta(hours=2)).isoformat() + "+00:00"

_STATIC = [{"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["m1"]},
           {"step": 2, "messages": ["m2"]}]
_GENERATED = [{"step": 1, "prompt": "tease him"}, {"step": 2, "messages": ["m2"]}]


class FakeOF:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self._next_id = 9_300_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._next_id += 1
        self.sent.append((int(chat_id), text))
        return {"id": self._next_id, "text": f"<p>{text}</p>", "createdAt": SEND_AT}


def _use_fake() -> FakeOF:
    fake = FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _patch_llm(*, cap: bool = False, calls: list | None = None) -> None:
    async def _chat(**kw):
        if calls is not None:
            calls.append(kw.get("fan_id"))
        if cap:
            raise LLMCapExceeded(kw.get("account_id"), 100, 200)
        return SimpleNamespace(content="generated 😏", call_id=1)
    llm_client.chat = _chat  # type: ignore[attr-defined]


async def _seed_broadcast(aid: str, steps: list[dict], repliers: list[int]) -> int:
    """Account + funnel + an ok mass_run, an opener to each replier, and his
    reply after it (discovery reads exactly these rows)."""
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        f = MassMessageFunnel(name=f"f_{aid}", opening_message="hi?",
                              media_indices="[]", steps_json=json.dumps(steps))
        s.add(f)
        await s.flush()
        mr = MassRun(account_id=aid, funnel_id=int(f.id), status="ok",
                     recipient_count=len(repliers), started_at=T0)
        s.add(mr)
        await s.flush()
        mr_id = int(mr.id)
        for fid in repliers:
            s.add(Message(account_id=aid, fan_id=fid, message_id=fid * 10 + 1,
                          direction="out", body="hi?", created_at=T0,
                          mass_run_id=mr_id))
            s.add(Message(account_id=aid, fan_id=fid, message_id=fid * 10 + 2,
                          direction="in", body="heyy", created_at=T_REPLY))
    return mr_id


async def _fence_closed(aid: str) -> None:
    """Enforce-mode include audience pointing at no list → fails CLOSED."""
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, audience_mode="enforce",
                              audience_list_id=None))


async def _state(mr: int, fid: int) -> FunnelState | None:
    async with get_session() as s:
        return await s.get(FunnelState, (mr, fid))


# ── Cases ─────────────────────────────────────────────────────────────

async def case_cap_stops_run_no_send():
    aid, a, b = "acc_rmfg_cap", 6101, 6102
    mr = await _seed_broadcast(aid, _GENERATED, [a, b])
    fake = _use_fake()
    calls: list = []
    _patch_llm(cap=True, calls=calls)

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["status"] == "ok", res
    assert res["cap_hit"] is True, res
    assert res["advanced"] == 0 and res["errors"] == 0, res
    assert res["discovered"] == 2, res
    assert len(calls) == 1 and calls[0] in (a, b), calls   # cap stops the sweep
    assert fake.sent == [], fake.sent

    for fid in (a, b):
        st = await _state(mr, fid)
        assert st is not None and st.current_step == 0 and st.status == "pending", st
    async with get_session() as s:
        assert await s.get(FanLease, (aid, a)) is None, "lease released on cap"
        assert await s.get(FanLease, (aid, b)) is None
        runs = (await s.execute(select(AutomationRun).where(
            AutomationRun.account_id == aid))).scalars().all()
    assert len(runs) == 1 and runs[0].status == "ok", runs
    assert json.loads(runs[0].stats_json)["cap_hit"] is True, runs[0].stats_json


async def case_audience_fence_blocks_without_test_fan():
    aid, a = "acc_rmfg_fence", 6201
    mr = await _seed_broadcast(aid, _STATIC, [a])
    await _fence_closed(aid)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["status"] == "ok", res
    assert res["audience_mode"] == "enforce", res
    assert res["discovered"] == 0 and res["advanced"] == 0, res
    assert res["audience_skipped"] >= 1, res
    assert fake.sent == [], fake.sent
    assert await _state(mr, a) is None, "outside fan not enrolled"


async def case_test_fan_bypasses_audience_fence():
    aid, target, other = "acc_rmfg_testfan", 6301, 6302
    mr = await _seed_broadcast(aid, _STATIC, [target, other])
    await _fence_closed(aid)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "reply_mass_funnel", payload={"test_fan": target})
    assert res["status"] == "ok", res
    assert res["discovered"] == 1 and res["advanced"] == 1, res
    assert fake.sent == [(target, "m1")], fake.sent          # only the target
    st = await _state(mr, target)
    assert st is not None and st.current_step == 1, st
    assert await _state(mr, other) is None, "non-target untouched"


_harness.run(
    case_cap_stops_run_no_send,
    case_audience_fence_blocks_without_test_fan,
    case_test_fan_bypasses_audience_fence,
)
