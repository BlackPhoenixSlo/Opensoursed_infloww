#!/usr/bin/env python3
"""
A08 process_old_fans — guard characterisation (pins TODAY's behaviour).

process_old_fans has no LLM call or sender of its own: it flags the batch, then
composes gen_info (A02) + apply_profiles (A03) with `force_ids=<batch>`. So its
two guards live one hop down, and that is where these cases point:

  case_cap_recorded_no_crash:
      llm_client.chat raises LLMCapExceeded → gen_info counts it (`capped`=1,
      `generated`=0); the A08 run still ends `ok`, the fan is still flagged,
      no fan_profiles row, nothing touches OF, stats_json carries the cap.
  case_force_ids_bypasses_rerun_gate:
      a fan with 3 inbound msgs is below gen_info's re-run gate (_MIN_NEW_MSGS),
      so a plain gen_info sweep skips him (control). Through process_old_fans the
      forwarded force_ids bypasses that gate → profiled. Only the target is
      seeded (force_ids does not scope who else a sweep would pick); the OF push
      is exactly set_fan_custom_name + set_fan_note, both for the target.

Run: ./venv/bin/python service/tests/test_process_old_fans_guards.py   (exit 0 = pass)
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
from automations import gen_info  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AutomationRun, Fan, FanProfile, Message, SkipList  # noqa: E402
from llm_client import LLMCapExceeded  # noqa: E402

_PROFILE = {
    "nickname": "Sam//NYC//40//Lawyer", "short_bio": "40yo lawyer from NYC",
    "bullet_points": "- Age: 40", "original_name": "Sam", "real_name": "Sam",
    "his_age": "40", "home_country": "USA", "home_city": "NYC", "hobbies": "golf",
    "occupation": "Lawyer", "relationship_status": "single", "fetishes": "",
}


class FakeOF:
    """Records EVERY client call (method, args) — gen_info's best-effort OF
    nickname/notes push goes through here; nothing may hit the network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.sent: list[tuple[int, str]] = []

    def send_message(self, chat_id, text, **kw) -> dict:
        self.sent.append((int(chat_id), text))
        return {"id": 1, "text": text, "createdAt": "2026-06-01T12:00:00+00:00"}

    def __getattr__(self, name):
        def _rec(*a, **k):
            self.calls.append((name, a, k))
            return {}
        return _rec


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
        return SimpleNamespace(content=json.dumps(_PROFILE), parsed=dict(_PROFILE),
                               call_id=1)
    llm_client.chat = _chat  # type: ignore[attr-defined]


async def _seed(aid: str, fid: int, in_msgs: int) -> None:
    base = datetime(2026, 6, 1, 10, 0, 0)
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(Fan(account_id=aid, fan_id=fid, of_display_name="Sam", of_username="sam"))
        for i in range(in_msgs):
            s.add(Message(account_id=aid, fan_id=fid, message_id=fid * 1000 + i,
                          direction="in", body=f"<p>hey {i}</p>",
                          created_at=base + timedelta(minutes=i)))


# ── Cases ─────────────────────────────────────────────────────────────

async def case_cap_recorded_no_crash():
    aid, fid = "acc_pofg_cap", 9101
    await _seed(aid, fid, in_msgs=9)
    fake = _use_fake()
    llm_calls: list = []
    _patch_llm(cap=True, calls=llm_calls)

    res = await run_once(aid, "process_old_fans", payload={"fan_ids": [fid]})
    assert res["status"] == "ok", res
    assert llm_calls == [fid], llm_calls                       # it was asked, once
    assert res["flagged"] == 1 and res["processed"] == 1, res
    g = res["gen_info"]
    assert g and g["capped"] == 1 and g["generated"] == 0 and g["failed"] == 0, g
    assert res["apply_profiles"] is not None and res["apply_profiles"].get("applied", 0) == 0, \
        res["apply_profiles"]
    assert fake.sent == [] and fake.calls == [], (fake.sent, fake.calls)

    async with get_session() as s:
        assert await s.get(FanProfile, (aid, fid)) is None, "no profile on cap"
        sk = await s.get(SkipList, (aid, fid))
        assert sk is not None and sk.reason == "old_fan_pre_ai", sk
        runs = (await s.execute(select(AutomationRun).where(
            AutomationRun.account_id == aid,
            AutomationRun.kind == "process_old_fans"))).scalars().all()
    assert len(runs) == 1 and runs[0].status == "ok", runs
    assert json.loads(runs[0].stats_json)["gen_info"]["capped"] == 1, runs[0].stats_json


async def case_force_ids_bypasses_rerun_gate():
    aid, fid = "acc_pofg_force", 9201
    await _seed(aid, fid, in_msgs=3)        # below gen_info._MIN_NEW_MSGS (8)
    assert gen_info._MIN_NEW_MSGS > 3, gen_info._MIN_NEW_MSGS
    fake = _use_fake()
    llm_calls: list = []
    _patch_llm(calls=llm_calls)

    # Control: an un-forced gen_info sweep leaves this fan alone.
    plain = await gen_info.run(aid, {}, run_id=0)
    assert plain["candidates"] == 1 and plain["generated"] == 0, plain
    assert plain["skipped_fresh"] == 1 and llm_calls == [], (plain, llm_calls)

    res = await run_once(aid, "process_old_fans", payload={"fan_ids": [fid]})
    assert res["status"] == "ok", res
    assert res["gen_info"]["attempted"] == 1, res["gen_info"]
    assert res["gen_info"]["generated"] == 1, res["gen_info"]
    assert llm_calls == [fid], llm_calls
    assert fake.sent == [], fake.sent                         # no DM, ever
    # The OF profile push: (method, fan id = first positional) — only the target.
    assert [(name, a[0]) for name, a, _k in fake.calls] == \
        [("set_fan_custom_name", fid), ("set_fan_note", fid)], fake.calls

    async with get_session() as s:
        prof = await s.get(FanProfile, (aid, fid))
        assert prof is not None and prof.nickname, prof


_harness.run(
    case_cap_recorded_no_crash,
    case_force_ids_bypasses_rerun_gate,
)
