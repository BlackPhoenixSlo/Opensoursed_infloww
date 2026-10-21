#!/usr/bin/env python3
"""
A08 — process_old_fans automation tests (library/one_section_of_automations/08_process_old_fans.md).

Acceptance: an old fan is profiled + applied (DB only, per A03's limits) OR added
to the skip_list. A08 composes A02 (gen_info) + A03 (apply_profiles) over a
payload-supplied id list, and flags every old fan out of the AI chatter
(skip_list reason="old_fan_pre_ai"). of_client is
never imported here — the whole path is pure DB.

  case_old_fan_profiled_and_applied:
      an old fan WITH chat history → run_once("process_old_fans", {fan_ids}) →
      flagged (skip_list) AND profiled (fan_profiles row) AND
      applied (fans.applied_notes). One ok automation_runs row for A08; the
      composed gen_info/apply_profiles stats ride in its stats_json.
  case_no_history_fan_only_flagged:
      an old fan with NO messages can't be profiled — it is still flagged into
      skip_list (the "or added to skip_list" half of acceptance).
  case_flag_only_skips_substeps:
      flag_only (the spec's --no-scrape) flips the DB flags without running
      gen_info/apply_profiles.
  case_username_resolution_and_idempotency:
      an @username row resolves via fans.of_username; a second run finds the fan
      already onboarded and runs no sub-steps.
  case_rule_schedules_process_old_fans:
      an automation_rules row (kind=process_old_fans) materializes a job the
      supervisor tick consumes — scheduling needs NO executor edit.

Run: ./venv/bin/python service/tests/test_process_old_fans.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402,F401 — registers scrape_chats + plugin loader
import llm_client  # noqa: E402
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    AutomationRule,
    AutomationRun,
    Fan,
    FanProfile,
    Message,
    ScheduledJob,
    SkipList,
)

# Canned Grok JSON (mirror of test_gen_info — the fake completion body).
_GROK_PROFILE = {
    "nickname": "Sam//NYC//40//Lawyer",
    "short_bio": "40yo lawyer from NYC, long-time sub",
    "bullet_points": "- Age: 40\n- Job: Lawyer",
    "Q1": "How's the big case going?",
    "Q2": "", "Q3": "",
    "Tease1": "Bet you look sharp in that suit...",
    "Tease2": "", "Tease3": "",
    "original_name": "Sam", "real_name": "Sam", "his_age": "40",
    "home_country": "USA", "home_city": "NYC", "hobbies": "golf",
    "occupation": "Lawyer", "relationship_status": "single", "fetishes": "",
}


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):  # noqa: A002
        return _FakeResponse({
            "choices": [{"message": {"content": json_dump(_GROK_PROFILE)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })


def json_dump(obj) -> str:
    return json.dumps(obj)


def _install_fake_llm() -> None:
    llm_client.httpx.AsyncClient = _FakeAsyncClient  # type: ignore[attr-defined]


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_fan(aid: str, fan_id: int, *, name: str = "Sam",
                    in_msgs: int = 0) -> None:
    base = datetime(2026, 6, 1, 10, 0, 0)
    async with get_session() as s:
        if await s.get(Fan, (aid, fan_id)) is None:
            s.add(Fan(account_id=aid, fan_id=fan_id, of_display_name=name,
                      of_username=name.lower()))
        for i in range(in_msgs):
            s.add(Message(
                account_id=aid, fan_id=fan_id, message_id=fan_id * 1000 + i,
                direction="in", body=f"<p>hey {i}</p>",
                created_at=base + timedelta(minutes=i),
            ))


# ── 🔴 Acceptance: profiled + applied ────────────────────────────────

async def case_old_fan_profiled_and_applied():
    aid, fan = "acc_pof_accept", 8001
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan(aid, fan, in_msgs=9)

    res = await run_once(aid, "process_old_fans", payload={"fan_ids": [fan]})
    assert res["status"] == "ok", res
    assert res["old_fans"] == 1 and res["flagged"] == 1, res
    assert res["processed"] == 1, res
    assert res["gen_info"] and res["gen_info"]["generated"] == 1, res["gen_info"]
    assert res["apply_profiles"] and res["apply_profiles"]["applied"] == 1, res["apply_profiles"]

    async with get_session() as s:
        # Flagged out of the AI chatter.
        sk = await s.get(SkipList, (aid, fan))
        assert sk is not None and sk.reason == "old_fan_pre_ai", sk
        f = await s.get(Fan, (aid, fan))

        # Profiled (A02) + applied (A03), DB only.
        prof = await s.get(FanProfile, (aid, fan))
        assert prof is not None and prof.nickname == "Sam/NYC/40/Lawyer", prof
        assert f.applied_notes and f.applied_notes_at is not None, f.applied_notes
        assert f.generated_nickname == "Sam/NYC/40/Lawyer", f.generated_nickname

        # Exactly one A08 automation_runs row; composed stats in its stats_json.
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid,
                                        AutomationRun.kind == "process_old_fans")
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "ok", runs
        stats = json.loads(runs[0].stats_json)
        assert stats["gen_info"]["generated"] == 1, stats
        assert stats["apply_profiles"]["applied"] == 1, stats


# ── No history → flagged only (the "or skip_list" half) ──────────────

async def case_no_history_fan_only_flagged():
    aid, fan = "acc_pof_nohist", 8101
    _install_fake_llm()
    await _seed_account(aid)
    # Fan exists but has zero messages — gen_info can't build a candidate.
    await _seed_fan(aid, fan, in_msgs=0)

    res = await run_once(aid, "process_old_fans", payload={"fan_ids": [fan]})
    assert res["status"] == "ok", res
    assert res["flagged"] == 1, res
    assert res["gen_info"]["generated"] == 0, res["gen_info"]

    async with get_session() as s:
        sk = await s.get(SkipList, (aid, fan))
        assert sk is not None and sk.reason == "old_fan_pre_ai", sk
        assert await s.get(FanProfile, (aid, fan)) is None, "no profile without history"


# ── flag_only (--no-scrape) ──────────────────────────────────────────

async def case_flag_only_skips_substeps():
    aid, fan = "acc_pof_flagonly", 8201
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan(aid, fan, in_msgs=9)

    res = await run_once(aid, "process_old_fans",
                         payload={"fan_ids": [fan], "flag_only": True})
    assert res["status"] == "ok", res
    assert res["flagged"] == 1 and res["flag_only"] is True, res
    assert res["gen_info"] is None and res["apply_profiles"] is None, res

    async with get_session() as s:
        assert await s.get(SkipList, (aid, fan)) is not None, "flagged"
        assert await s.get(FanProfile, (aid, fan)) is None, "no gen_info ran"


# ── Username resolution + idempotency ────────────────────────────────

async def case_username_resolution_and_idempotency():
    aid, fan = "acc_pof_uname", 8301
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan(aid, fan, name="Diego", in_msgs=8)

    # Sheet gives "@Diego" (mixed case, @-prefixed) + a junk name that can't resolve.
    res = await run_once(aid, "process_old_fans",
                         payload={"usernames": ["@Diego", "ghost_user"]})
    assert res["status"] == "ok", res
    assert res["old_fans"] == 1, res                 # only Diego resolved
    assert res["unresolved_usernames"] == 1, res     # ghost_user counted, not guessed
    assert res["processed"] == 1, res

    async with get_session() as s:
        assert await s.get(FanProfile, (aid, fan)) is not None, "Diego profiled"

    # Second run: already onboarded → no sub-steps, processed == 0.
    res2 = await run_once(aid, "process_old_fans",
                          payload={"usernames": ["@Diego"]})
    assert res2["status"] == "ok", res2
    assert res2["already_onboarded"] == 1 and res2["processed"] == 0, res2
    assert res2["gen_info"] is None, res2


# ── "Most recent N" source (no explicit id list) ─────────────────────

async def _seed_dated_fan(aid: str, fan_id: int, *, subscribed_at=None,
                          last_msg_at=None) -> None:
    async with get_session() as s:
        if await s.get(Fan, (aid, fan_id)) is None:
            s.add(Fan(account_id=aid, fan_id=fan_id,
                      of_display_name=f"f{fan_id}", of_username=f"f{fan_id}",
                      subscribed_at=subscribed_at,
                      last_message_received_at=last_msg_at))


async def _flagged_ids(aid: str) -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(
            select(SkipList.fan_id).where(
                SkipList.account_id == aid,
                SkipList.reason == "old_fan_pre_ai",
            )
        )).all()
    return {int(r[0]) for r in rows}


async def case_recent_by_subscribed():
    """recent_by="subscribed" (the default) takes the N most-recently-subscribed."""
    aid = "acc_pof_recent_sub"
    await _seed_account(aid)
    base = datetime(2026, 6, 1)
    await _seed_dated_fan(aid, 8501, subscribed_at=base - timedelta(days=3))
    await _seed_dated_fan(aid, 8502, subscribed_at=base - timedelta(days=2))
    await _seed_dated_fan(aid, 8503, subscribed_at=base - timedelta(days=1))

    # flag_only keeps the test about SELECTION (no gen_info/LLM needed).
    res = await run_once(aid, "process_old_fans",
                         payload={"recent_limit": 2, "flag_only": True})
    assert res["status"] == "ok", res
    assert res["old_fans"] == 2 and res["flagged"] == 2, res
    assert await _flagged_ids(aid) == {8502, 8503}, await _flagged_ids(aid)


async def case_recent_by_messaged():
    """recent_by="messaged" orders by last_message_received_at, NOT subscribed_at."""
    aid = "acc_pof_recent_msg"
    await _seed_account(aid)
    base = datetime(2026, 6, 1)
    # Subscribed order is the REVERSE of messaged order, so a wrong column shows.
    await _seed_dated_fan(aid, 8601, subscribed_at=base - timedelta(days=1),
                          last_msg_at=base - timedelta(days=3))
    await _seed_dated_fan(aid, 8602, subscribed_at=base - timedelta(days=2),
                          last_msg_at=base - timedelta(days=2))
    await _seed_dated_fan(aid, 8603, subscribed_at=base - timedelta(days=3),
                          last_msg_at=base - timedelta(days=1))

    res = await run_once(aid, "process_old_fans",
                         payload={"recent_limit": 2, "recent_by": "messaged",
                                  "flag_only": True})
    assert res["status"] == "ok", res
    # Newest last_message_received_at = {8603, 8602}; by-subscribed would be {8601, 8602}.
    assert await _flagged_ids(aid) == {8603, 8602}, await _flagged_ids(aid)


async def case_explicit_ids_win_over_recent():
    """An explicit fan_ids payload wins — recent_limit/recent_by are ignored."""
    aid = "acc_pof_recent_explicit"
    await _seed_account(aid)
    base = datetime(2026, 6, 1)
    await _seed_dated_fan(aid, 8701, subscribed_at=base - timedelta(days=3))
    await _seed_dated_fan(aid, 8702, subscribed_at=base - timedelta(days=2))
    await _seed_dated_fan(aid, 8703, subscribed_at=base - timedelta(days=1))

    res = await run_once(aid, "process_old_fans",
                         payload={"fan_ids": [8701], "recent_limit": 5,
                                  "recent_by": "subscribed", "flag_only": True})
    assert res["status"] == "ok", res
    assert res["old_fans"] == 1 and res["flagged"] == 1, res
    assert await _flagged_ids(aid) == {8701}, await _flagged_ids(aid)


# ── Scheduling needs no executor edit ────────────────────────────────

async def case_rule_schedules_process_old_fans():
    aid, fan = "acc_pof_rule", 8401
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan(aid, fan, in_msgs=8)
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="periodic process_old_fans",
            kind="process_old_fans",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({"fan_ids": [fan]}),  # the job payload
            is_enabled=True,
        ))

    n = await ax._materialize_due_rules()
    assert n >= 1, f"rule materialized a job, got {n}"
    await ax._drain_due_jobs_once()
    await ax._join_inflight_runs()  # non-blocking drain spawns tasks

    async with get_session() as s:
        job = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == "process_old_fans")
        )).scalar_one()
        assert job.status == "done", job.status
        assert await s.get(SkipList, (aid, fan)) is not None, "rule onboarded the fan"


_harness.run(
    case_old_fan_profiled_and_applied,
    case_no_history_fan_only_flagged,
    case_flag_only_skips_substeps,
    case_username_resolution_and_idempotency,
    case_recent_by_subscribed,
    case_recent_by_messaged,
    case_explicit_ids_win_over_recent,
    case_rule_schedules_process_old_fans,
)
