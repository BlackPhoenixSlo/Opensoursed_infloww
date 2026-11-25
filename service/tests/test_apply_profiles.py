#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402,F401 — registers scrape_chats + plugin loader
from automation_executor import run_once  # noqa: E402
import fans as fans_api  # noqa: E402 — serializer under test for UI visibility
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    AutomationRule,
    AutomationRun,
    Blacklist,
    Fan,
    FanProfile,
    ScheduledJob,
)


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_fan(aid: str, fan_id: int, *, name: str = "Bob", **facts) -> None:
    async with get_session() as s:
        if await s.get(Fan, (aid, fan_id)) is None:
            s.add(Fan(account_id=aid, fan_id=fan_id, of_display_name=name,
                      of_username=name.lower(), **facts))


async def _seed_profile(aid: str, fan_id: int, *, nickname: str | None,
                        q1: str | None = None, tease1: str | None = None,
                        applied_notes: str | None = None,
                        short_bio: str | None = None) -> None:
    async with get_session() as s:
        s.add(FanProfile(
            account_id=aid, fan_id=fan_id, nickname=nickname,
            q1=q1, tease1=tease1, applied_notes=applied_notes, short_bio=short_bio,
        ))



async def case_apply_acceptance():
    aid, fan = "acc_ap_accept", 5001
    await _seed_account(aid)
    await _seed_fan(aid, fan, his_age="31", occupation="Dev", home_city="Toronto",
                    hobbies="gaming", recent_events='["new job"]')
    await _seed_profile(
        aid, fan, nickname="Bob//Toronto//31//Dev",
        q1="What game are you hooked on?", tease1="Bet your setup is insane...",
    )

    res = await run_once(aid, "apply_profiles", payload={})
    assert res["status"] == "ok", res
    assert res["applied"] == 1, res
    assert res["profiles_seen"] == 1, res
    assert res["pushed_to_of"] is False, res

    note = "Recent: new job\nIntr: gaming\nJob: Dev"
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.applied_notes == note, f.applied_notes
        assert f.applied_notes_at is not None, "applied_notes_at stamped"
        assert f.generated_nickname is None, f.generated_nickname

        prof = await s.get(FanProfile, (aid, fan))
        assert prof.applied_notes == note, prof.applied_notes
        assert prof.notes_applied_successfully is True, prof.notes_applied_successfully
        assert prof.last_applied_at is not None
        assert prof.last_applied_nickname == "Bob/Toronto/31/Dev", prof.last_applied_nickname
        assert prof.last_applied_notes == note, prof.last_applied_notes

        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid,
                                        AutomationRun.kind == "apply_profiles")
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "ok", runs
        stats = json.loads(runs[0].stats_json)
        assert stats["applied"] == 1, stats

        d = fans_api._row_to_dict(f)
        assert d["applied_notes"] == note, d.get("applied_notes")
        assert d["applied_notes_at"] is not None, d.get("applied_notes_at")



async def case_cooldown_and_force():
    aid, fan = "acc_ap_cooldown", 6001
    await _seed_account(aid)
    await _seed_fan(aid, fan)
    await _seed_profile(aid, fan, nickname="Al", q1="Q", tease1="T")

    r1 = await run_once(aid, "apply_profiles", payload={})
    assert r1["applied"] == 1, r1

    r2 = await run_once(aid, "apply_profiles", payload={})
    assert r2["applied"] == 0 and r2["skipped_cooldown"] == 1, r2

    r3 = await run_once(aid, "apply_profiles", payload={"force_ids": [fan]})
    assert r3["applied"] == 1 and r3["skipped_cooldown"] == 0, r3

    async with get_session() as s:
        prof = await s.get(FanProfile, (aid, fan))
        prof.last_applied_at = datetime.utcnow() - timedelta(hours=25)
        await s.commit()
    r4 = await run_once(aid, "apply_profiles", payload={})
    assert r4["applied"] == 1 and r4["skipped_cooldown"] == 0, r4



async def case_notes_are_facts_not_qtease():
    aid, fan = "acc_ap_facts", 7001
    await _seed_account(aid)
    await _seed_fan(aid, fan)
    await _seed_profile(aid, fan, nickname="Al", q1="ignored Q", tease1="ignored T")

    await run_once(aid, "apply_profiles", payload={})
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert (f.applied_notes or "") == "", f"Q/Tease must NOT be used: {f.applied_notes!r}"

    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        f.his_age, f.occupation, f.hobbies = "29", "Nurse", "yoga"
        await s.commit()
    await run_once(aid, "apply_profiles", payload={"force_ids": [fan]})
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        note = f.applied_notes or ""
        assert "Intr: yoga" in note and "Job: Nurse" in note, note
        assert "29" not in note, f"age belongs in the nickname, not the note: {note!r}"



async def case_note_order_and_drops():
    aid, fan = "acc_ap_order", 11001
    await _seed_account(aid)
    await _seed_fan(
        aid, fan, name="Garrett", his_age="30", home_city="Delta",
        home_country="Canada", occupation="Dev", hobbies="gaming, hiking",
        relationship_status="single", fetishes="feet",
        recent_events='["new job", "got a puppy"]',
    )
    await _seed_profile(aid, fan, nickname="Garrett/Delta,Canada/30/Dev")

    await run_once(aid, "apply_profiles", payload={})
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
    note = f.applied_notes or ""
    assert note == (
        "Recent: new job; got a puppy\nIntr: gaming, hiking\nJob: Dev\n"
        "Rel: single\nKinks: feet"
    ), note
    for banned in ("Garrett", "30", "Delta", "Canada", "age", "loc", "spend", "$"):
        assert banned not in note, f"{banned!r} must not be in the note: {note!r}"



async def case_short_bio_and_skip_empties():
    aid, fan = "acc_ap_bio", 12001
    await _seed_account(aid)
    await _seed_fan(aid, fan, hobbies="gaming")
    await _seed_profile(aid, fan, nickname="Al", short_bio="A devoted Toronto fan")

    await run_once(aid, "apply_profiles", payload={})
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
    note = f.applied_notes or ""
    assert note == "Intr: gaming\nA devoted Toronto fan", note
    for banned in ("Job:", "Rel:", "Kinks:", "Recent:"):
        assert banned not in note, f"empty field {banned!r} must be skipped: {note!r}"



async def case_does_not_overwrite_gen_info_nickname():
    aid, fan = "acc_ap_nick_owner", 10001
    await _seed_account(aid)
    await _seed_fan(aid, fan, his_age="40", occupation="Pilot")
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        f.generated_nickname = "GenInfo/Owned/Nick"
        await s.commit()
    await _seed_profile(aid, fan, nickname="Stale//Different", q1="Q", tease1="T")

    res = await run_once(aid, "apply_profiles", payload={})
    assert res["applied"] == 1, res
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.generated_nickname == "GenInfo/Owned/Nick", f.generated_nickname
        assert "Job: Pilot" in (f.applied_notes or ""), f.applied_notes
        prof = await s.get(FanProfile, (aid, fan))
        assert prof.last_applied_nickname == "Stale/Different", prof.last_applied_nickname



async def case_blacklist_skip():
    aid, fan = "acc_ap_black", 8001
    await _seed_account(aid)
    await _seed_fan(aid, fan)
    await _seed_profile(aid, fan, nickname="Al", q1="Q", tease1="T")
    async with get_session() as s:
        s.add(Blacklist(fan_id=fan, reason="test"))

    res = await run_once(aid, "apply_profiles", payload={})
    assert res["applied"] == 0 and res["skipped_blacklist"] == 1, res
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.applied_notes is None, "blacklisted fan untouched"



async def case_rule_schedules_apply_profiles():
    aid, fan = "acc_ap_rule", 9001
    await _seed_account(aid)
    await _seed_fan(aid, fan, his_age="22", hobbies="chess")
    await _seed_profile(aid, fan, nickname="Al", q1="Q", tease1="T")
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="periodic apply_profiles", kind="apply_profiles",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({}),
            is_enabled=True,
        ))

    n = await ax._materialize_due_rules()
    assert n >= 1, f"rule materialized a job, got {n}"

    await ax._drain_due_jobs_once()
    await ax._join_inflight_runs()
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.applied_notes is not None, "scheduled apply_profiles wrote the note"
        job = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == "apply_profiles")
        )).scalar_one()
        assert job.status == "done", job.status



async def case_push_to_of():
    from automations import apply_profiles as _ap
    aid, fan = "acc_ap_push", 11001
    await _seed_account(aid)
    await _seed_fan(aid, fan, his_age="33", occupation="Pilot")
    await _seed_profile(aid, fan, nickname="Max//NYC")

    calls = []

    class _FakeClient:
        @classmethod
        def from_account(cls, account_id):
            return cls()

        def set_fan_custom_name(self, fan_id, name):
            calls.append(("nick", fan_id, name))

        def set_fan_note(self, fan_id, note):
            calls.append(("note", fan_id, note))
            raise RuntimeError("404 Subscription not found")

    orig = _ap.OFClient
    _ap.OFClient = _FakeClient
    try:
        res = await run_once(aid, "apply_profiles", payload={"push_to_of": True})
    finally:
        _ap.OFClient = orig

    assert res["pushed_to_of"] is True, res
    assert res["pushed_nick"] == 1, res
    assert res["pushed_note"] == 0, res
    assert res["errors"] == 0, res
    assert ("nick", fan, "Max/NYC") in calls, calls
    assert any(c[0] == "note" for c in calls), "note push was attempted separately"

    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.custom_nickname == "Max/NYC", f.custom_nickname
        assert (f.notes or "") == "", f"note 404'd → must not mirror locally: {f.notes!r}"


_harness.run(
    case_apply_acceptance,
    case_cooldown_and_force,
    case_notes_are_facts_not_qtease,
    case_note_order_and_drops,
    case_short_bio_and_skip_empties,
    case_does_not_overwrite_gen_info_nickname,
    case_blacklist_skip,
    case_rule_schedules_apply_profiles,
    case_push_to_of,
)
