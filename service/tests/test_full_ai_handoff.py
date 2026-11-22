#!/usr/bin/env python3
"""test_full_ai_handoff — the Welcome handoff for a Fan Full AI Chat claims (spec 04b ticket 78).

`welcome_turn.enqueue_turn_handoff` over a temp DB; job rows read from `scheduled_jobs`. A Fan is
claimed by patching `full_ai_live.live_rule` (Mode live: the enabled rule's id; main: None for every
Creator). The job is `full_ai_live.enqueue`'s (W30 F10): its payload shape, due at the reply speed and
no sooner than the Welcome rest.

  case_claimed_wcfi_on            one `full_ai_chat` job {only_fan_ids, anchor, _rule_id, tries}, 165 s
                                  out (his DM is old: its reply-speed due has passed); no
                                  `welcome_chatter_for_info` job
  case_claimed_wcfi_off           the same one job (today: none)
  case_unclaimed_today            off the Fans list / `_live` false / Full AI rule off: today's row
                                  byte-for-byte, or none with Get to know fans off
  case_media_only_and_no_inbound  newest inbound media only: anchored on it; no inbound row: today's path
  case_hook_same_anchor_rule_off  the hook's pending job absorbs the handoff (one job, his anchor); rule
                                  off before the claim: cancelled with RULE_OFF_REASON through run_once
  case_claimed_ids_raises         a Full AI fault: today's path
  case_wcfi_handoff_cases_unedited  test_welcome_chatter_for_info.py matches origin/main

Run: ./venv/bin/python service/tests/test_full_ai_handoff.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import contextlib  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import automation_executor as ax  # noqa: E402
import webhook_dispatch as wd  # noqa: E402
from automations import full_ai_live  # noqa: E402
from automations import full_ai_owner_io as io  # noqa: E402
from automations import welcome_turn  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, AutomationRule, Message, ScheduledJob  # noqa: E402
from job_queue import RULE_OFF_REASON  # noqa: E402

KIND = "full_ai_chat"
WCFI = "welcome_chatter_for_info"
T0 = datetime(2026, 11, 15, 12, 0, 0)
_n = 0


class ListOF:
    """OF's `/lists/{id}/users` read only: {list_id: [fan ids]}."""

    def __init__(self, lists: dict[int, list[int]]):
        self.lists = lists

    def list_users_in(self, list_id, *, limit=20, offset=0):
        return [{"id": i} for i in self.lists.get(int(list_id), [])[offset:offset + limit]]


@contextlib.contextmanager
def _patch(mod, name, value):
    real = getattr(mod, name)
    setattr(mod, name, value)
    try:
        yield
    finally:
        setattr(mod, name, real)


def _live(on: bool = True):
    async def fake(account_id):
        return await ax.enabled_rule_id(account_id, KIND) if on else None
    return _patch(full_ai_live, "live_rule", fake)


async def _account(*, wcfi: bool, full_ai: bool = True, fans: dict | None = None) -> tuple[str, int]:
    """A fresh account: Get to know fans rule on/off, Full AI rule on/off, its Fans list. -> (aid, rule id)."""
    global _n
    _n += 1
    aid = f"acc-handoff-{_n}"
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(AutomationRule(account_id=aid, name=WCFI, kind=WCFI, trigger_json=json.dumps({"every_seconds": 300}),
                             steps_json="{}", is_enabled=wcfi))
        r = AutomationRule(account_id=aid, name="Full AI Chat", kind=KIND, trigger_json=json.dumps(
            {"every_seconds": 86400}), steps_json="{}", is_enabled=full_ai)
        s.add(r)
        if fans is not None:
            s.add(AccountAiConfig(account_id=aid, full_ai_config_json=json.dumps(
                {"checkpoint": {"fans": fans}, "rev": 1})))
        await s.flush()
        return aid, r.id


async def _msg(aid: str, fan: int, mid: int, direction: str, at: datetime, body: str = "hey", **kw) -> None:
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=mid, direction=direction, body=body,
                      created_at=at, **kw))


async def _jobs(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(ScheduledJob.account_id == aid)
                                     .order_by(ScheduledJob.id))).scalars().all())


def _today(fan: int) -> str:
    """Byte-for-byte the payload_json main's `enqueue_turn_handoff` writes."""
    return json.dumps({"only_fan_ids": [fan], "force_ids": [fan], "turn_handoff_ids": [fan]})


async def _handoff(aid: str, fan: int) -> tuple[str | None, datetime, datetime]:
    t0 = datetime.utcnow()
    kind = await welcome_turn.enqueue_turn_handoff(aid, fan)
    return kind, t0, datetime.utcnow()


def _due_165(job: ScheduledJob, t0: datetime, t1: datetime) -> None:
    pad = timedelta(seconds=welcome_turn.WELCOME_REST_S + welcome_turn.HANDOFF_DELAY_PAD_S)
    assert pad == timedelta(seconds=165), pad
    assert t0 + pad - timedelta(seconds=1) <= job.run_at <= t1 + pad + timedelta(seconds=1), (job.run_at, t0)


async def _assert_full_ai(aid: str, fan: int, rid: int, anchor: int) -> None:
    kind, t0, t1 = await _handoff(aid, fan)
    assert kind == KIND, kind
    (job,) = await _jobs(aid)
    assert job.kind == KIND and job.status == "pending", (job.kind, job.status)
    assert json.loads(job.payload_json) == {"only_fan_ids": [fan], "anchor": anchor, "_rule_id": rid,
                                            "tries": 0}, job.payload_json
    _due_165(job, t0, t1)


async def _assert_today(aid: str, fan: int, *, wcfi: bool) -> None:
    kind, t0, t1 = await _handoff(aid, fan)
    jobs = await _jobs(aid)
    if not wcfi:
        assert kind is None and jobs == [], (kind, jobs)
        return
    assert kind == WCFI, kind
    (job,) = jobs
    assert job.kind == WCFI and job.payload_json == _today(fan), (job.kind, job.payload_json)
    _due_165(job, t0, t1)


async def case_claimed_wcfi_on():
    aid, rid = await _account(wcfi=True)
    await _msg(aid, 11, 1001, "in", T0)
    await _msg(aid, 11, 1002, "out", T0 + timedelta(seconds=5), automation_kind="welcome")
    with _live():
        await _assert_full_ai(aid, 11, rid, 1001)


async def case_claimed_wcfi_off():
    aid, rid = await _account(wcfi=False)
    await _msg(aid, 12, 1101, "in", T0)
    with _live():
        await _assert_full_ai(aid, 12, rid, 1101)


async def case_unclaimed_today():
    fan = 13
    for wcfi in (True, False):
        # off the Fans list (an include list he is not on)
        aid, _ = await _account(wcfi=wcfi, fans={"include": [901], "exclude": []})
        await _msg(aid, fan, 1201, "in", T0)
        with _live(), _patch(ax, "_make_client", lambda account_id: ListOF({901: [77]})):
            await _assert_today(aid, fan, wcfi=wcfi)
        # `_live` false (main)
        aid, _ = await _account(wcfi=wcfi)
        await _msg(aid, fan, 1202, "in", T0)
        await _assert_today(aid, fan, wcfi=wcfi)
        # the Full AI rule off
        aid, _ = await _account(wcfi=wcfi, full_ai=False)
        await _msg(aid, fan, 1203, "in", T0)
        with _live():
            await _assert_today(aid, fan, wcfi=wcfi)
    # on the Fans list: claimed (the list read is real, not bypassed)
    aid, rid = await _account(wcfi=True, fans={"include": [901], "exclude": []})
    await _msg(aid, fan, 1204, "in", T0)
    with _live(), _patch(ax, "_make_client", lambda account_id: ListOF({901: [fan]})):
        await _assert_full_ai(aid, fan, rid, 1204)


async def case_media_only_and_no_inbound():
    aid, rid = await _account(wcfi=True)
    await _msg(aid, 14, 1301, "in", T0, body="hi there")
    await _msg(aid, 14, 1302, "in", T0 + timedelta(seconds=20), body="", media_ids="[55]", media_count=1)
    with _live():
        await _assert_full_ai(aid, 14, rid, 1302)
    for wcfi in (True, False):
        aid, _ = await _account(wcfi=wcfi)
        await _msg(aid, 15, 1401, "out", T0, automation_kind="welcome")
        with _live():
            await _assert_today(aid, 15, wcfi=wcfi)


async def case_hook_same_anchor_rule_off():
    aid, rid = await _account(wcfi=True)
    fan, mid = 16, 1501
    await _msg(aid, fan, mid, "in", T0)
    with _live():
        await wd._full_ai_hook(aid, fan, mid)
        assert await welcome_turn.enqueue_turn_handoff(aid, fan) == KIND
    (hook_job,) = await _jobs(aid)                          # his pending job absorbs the handoff
    assert hook_job.kind == KIND, hook_job.kind
    assert json.loads(hook_job.payload_json) == {
        "only_fan_ids": [fan], "anchor": mid, "_rule_id": rid, "tries": 0}, hook_job.payload_json
    async with get_session() as s:
        await s.execute(update(AutomationRule).where(AutomationRule.id == rid).values(is_enabled=False))
        await s.execute(update(ScheduledJob).where(ScheduledJob.account_id == aid)
                        .values(run_at=datetime.utcnow() - timedelta(seconds=1)))
    res = await ax.run_once(aid, KIND)
    assert res["status"] == "skipped" and res["reason"] == "rule_disabled", res
    for job in await _jobs(aid):
        assert (job.status, job.last_error) == ("cancelled", RULE_OFF_REASON), (job.id, job.status, job.last_error)


async def case_claimed_ids_raises():
    async def boom(account_id, fan_ids, *, client=None):
        raise RuntimeError("full ai read failed")
    for wcfi in (True, False):
        aid, _ = await _account(wcfi=wcfi)
        await _msg(aid, 17, 1601, "in", T0)
        with _live(), _patch(io, "claimed_ids", boom):
            await _assert_today(aid, 17, wcfi=wcfi)


def case_wcfi_handoff_cases_unedited():
    r = subprocess.run(["git", "diff", "--quiet", "origin/main", "--",
                        "service/tests/test_welcome_chatter_for_info.py"], cwd=_harness._REPO_ROOT)
    assert r.returncode == 0, "test_welcome_chatter_for_info.py differs from origin/main"


if __name__ == "__main__":
    _harness.run()
