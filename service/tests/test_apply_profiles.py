#!/usr/bin/env python3
"""
A03 — apply_profiles automation tests (library/one_section_of_automations/03_apply_profiles.md).

Acceptance: a fan with a generated profile gets `fans.applied_notes` /
`fans.applied_notes_at` populated in OUR DB and surfaced by the fans serializer
(the drawer) — with NO OF write and NO failed network call (OF has no native
nickname/notes endpoint; of_client.py ~L1509). of_client is never imported here,
which proves the automation is pure-DB.

  case_apply_acceptance:
      a fan_profiles row + fans-row facts → run_once("apply_profiles") →
      fans.applied_notes (the short-label fact note, useful-first) + applied_notes_at
      stamped + fan_profiles dedup columns set + an ok automation_runs row. The
      serializer exposes applied_notes (UI visibility). fans.generated_nickname is
      NOT written here — gen_info owns it.
  case_cooldown_and_force:
      a second run within 24h is skipped; force_ids bypasses the cooldown.
  case_notes_are_facts_not_qtease:
      the note is built from fans-row facts, never Q/Tease, and tracks the facts.
  case_note_order_and_drops:
      the note leads Recent → Intr → Job → Rel → Kinks with short labels and omits
      name/age/location (in the nickname) + lifetime spend (in the sheet).
  case_does_not_overwrite_gen_info_nickname:
      a gen_info-written fans.generated_nickname survives an apply_profiles run
      (single-writer): apply_profiles READS the nickname, never WRITES it.
  case_blacklist_skip:
      a globally-blacklisted fan is not touched.
  case_rule_schedules_apply_profiles:
      an automation_rules row (kind=apply_profiles) materializes a job that the
      supervisor tick consumes — scheduling needs NO executor edit.

Run: ./venv/bin/python service/tests/test_apply_profiles.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

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


# ── 🔴 Acceptance ────────────────────────────────────────────────────

async def case_apply_acceptance():
    aid, fan = "acc_ap_accept", 5001
    await _seed_account(aid)
    # Facts → the note; Q/Tease are present but must now be IGNORED (W2h). his_age +
    # home_city are seeded ON PURPOSE: they live in the nickname, so the note must
    # NOT echo them — only Recent/Intr/Job survive, most-useful-first.
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
    assert res["pushed_to_of"] is False, res  # NEVER pushed to OF

    note = "Recent: new job\nIntr: gaming\nJob: Dev"
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.applied_notes == note, f.applied_notes
        assert f.applied_notes_at is not None, "applied_notes_at stamped"
        # apply_profiles is NOT an author of generated_nickname — gen_info owns it.
        # The fan here has no gen_info-written nickname, so the column stays None.
        assert f.generated_nickname is None, f.generated_nickname

        prof = await s.get(FanProfile, (aid, fan))
        assert prof.applied_notes == note, prof.applied_notes
        assert prof.notes_applied_successfully is True, prof.notes_applied_successfully
        assert prof.last_applied_at is not None
        assert prof.last_applied_nickname == "Bob/Toronto/31/Dev", prof.last_applied_nickname
        assert prof.last_applied_notes == note, prof.last_applied_notes

        # automation_runs row ok with stats.
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid,
                                        AutomationRun.kind == "apply_profiles")
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "ok", runs
        stats = json.loads(runs[0].stats_json)
        assert stats["applied"] == 1, stats

        # UI visibility: the fans serializer exposes the applied note.
        d = fans_api._row_to_dict(f)
        assert d["applied_notes"] == note, d.get("applied_notes")
        assert d["applied_notes_at"] is not None, d.get("applied_notes_at")


# ── 24h cooldown + force_ids bypass ──────────────────────────────────

async def case_cooldown_and_force():
    aid, fan = "acc_ap_cooldown", 6001
    await _seed_account(aid)
    await _seed_fan(aid, fan)
    await _seed_profile(aid, fan, nickname="Al", q1="Q", tease1="T")

    r1 = await run_once(aid, "apply_profiles", payload={})
    assert r1["applied"] == 1, r1

    # Unchanged targets within 24h → cooldown skip.
    r2 = await run_once(aid, "apply_profiles", payload={})
    assert r2["applied"] == 0 and r2["skipped_cooldown"] == 1, r2

    # force_ids bypasses the cooldown.
    r3 = await run_once(aid, "apply_profiles", payload={"force_ids": [fan]})
    assert r3["applied"] == 1 and r3["skipped_cooldown"] == 0, r3

    # Cooldown EXPIRED (>24h ago) → applies again without force.
    async with get_session() as s:
        prof = await s.get(FanProfile, (aid, fan))
        prof.last_applied_at = datetime.utcnow() - timedelta(hours=25)
        await s.commit()
    r4 = await run_once(aid, "apply_profiles", payload={})
    assert r4["applied"] == 1 and r4["skipped_cooldown"] == 0, r4


# ── Sticky applied_notes (never re-randomises) ───────────────────────

async def case_notes_are_facts_not_qtease():
    """W2h: the note is a fact sheet from the fans row, NOT Q/Tease. Q/Tease present
    but no facts → empty note; add facts → the note becomes the fact sheet (it tracks
    the facts each run, so it is NOT frozen-sticky)."""
    aid, fan = "acc_ap_facts", 7001
    await _seed_account(aid)
    await _seed_fan(aid, fan)  # no facts yet
    await _seed_profile(aid, fan, nickname="Al", q1="ignored Q", tease1="ignored T")

    await run_once(aid, "apply_profiles", payload={})
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert (f.applied_notes or "") == "", f"Q/Tease must NOT be used: {f.applied_notes!r}"

    # Add facts → the note becomes the fact sheet. his_age is set too, but age now
    # lives in the nickname so it must NOT appear in the note.
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


# ── Note layout: useful-first order, short labels, no nickname/spend dupes ──

async def case_note_order_and_drops():
    """The note leads with Recent → Intr → Job → Rel → Kinks, uses the short
    labels, and OMITS name/age/location (in the nickname) + lifetime spend (in the
    sheet) so nothing is duplicated."""
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
    # Nothing already shown in the nickname / sheet leaks into the note.
    for banned in ("Garrett", "30", "Delta", "Canada", "age", "loc", "spend", "$"):
        assert banned not in note, f"{banned!r} must not be in the note: {note!r}"


# ── short_bio appended at the bottom; empty facts skipped ────────────

async def case_short_bio_and_skip_empties():
    """short_bio lands at the BOTTOM of the note, and facts that are empty produce
    NO line at all (no bare 'Job:'/'Rel:'). Only hobbies + a bio here → two lines."""
    aid, fan = "acc_ap_bio", 12001
    await _seed_account(aid)
    # Only hobbies populated; job/rel/kinks/recent all empty → must NOT appear.
    await _seed_fan(aid, fan, hobbies="gaming")
    await _seed_profile(aid, fan, nickname="Al", short_bio="A devoted Toronto fan")

    await run_once(aid, "apply_profiles", payload={})
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
    note = f.applied_notes or ""
    assert note == "Intr: gaming\nA devoted Toronto fan", note
    for banned in ("Job:", "Rel:", "Kinks:", "Recent:"):
        assert banned not in note, f"empty field {banned!r} must be skipped: {note!r}"


# ── gen_info is the SOLE author of generated_nickname ────────────────

async def case_does_not_overwrite_gen_info_nickname():
    """apply_profiles must READ the nickname, never WRITE fans.generated_nickname:
    gen_info owns it. Seed a fan whose fans row already carries a gen_info-written
    nickname AND a fan_profiles row with a DIFFERENT nickname — after a run the
    fans.generated_nickname must still be the gen_info value (not clobbered), even
    though the dedup column records what apply_profiles read."""
    aid, fan = "acc_ap_nick_owner", 10001
    await _seed_account(aid)
    await _seed_fan(aid, fan, his_age="40", occupation="Pilot")
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        f.generated_nickname = "GenInfo/Owned/Nick"  # written by gen_info
        await s.commit()
    # fan_profiles carries a stale/different nickname apply_profiles would clean.
    await _seed_profile(aid, fan, nickname="Stale//Different", q1="Q", tease1="T")

    res = await run_once(aid, "apply_profiles", payload={})
    assert res["applied"] == 1, res
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        # The gen_info nickname is untouched — apply_profiles did not overwrite it.
        assert f.generated_nickname == "GenInfo/Owned/Nick", f.generated_nickname
        assert "Job: Pilot" in (f.applied_notes or ""), f.applied_notes  # note from facts
        # apply_profiles still READ the (cleaned) nickname into the dedup column.
        prof = await s.get(FanProfile, (aid, fan))
        assert prof.last_applied_nickname == "Stale/Different", prof.last_applied_nickname


# ── Blacklist skip ───────────────────────────────────────────────────

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


# ── Scheduling via automation_rules (no executor edit) ───────────────

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
    await ax._join_inflight_runs()  # non-blocking drain spawns tasks
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.applied_notes is not None, "scheduled apply_profiles wrote the note"
        job = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == "apply_profiles")
        )).scalar_one()
        assert job.status == "done", job.status


# ── OF push (PUT /subscriptions/{id}) via a fake client ──────────────

async def case_push_to_of():
    """push_to_of=True sends nickname (displayName) + note (notice) to OF via
    of_client in SEPARATE calls. A non-subscriber 404 on the note must NOT block the
    nickname write. Driven with a fake client (no network)."""
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
            raise RuntimeError("404 Subscription not found")  # non-subscriber

    orig = _ap.OFClient
    _ap.OFClient = _FakeClient
    try:
        res = await run_once(aid, "apply_profiles", payload={"push_to_of": True})
    finally:
        _ap.OFClient = orig

    assert res["pushed_to_of"] is True, res
    assert res["pushed_nick"] == 1, res     # nickname pushed (works for any fan)
    assert res["pushed_note"] == 0, res     # note 404'd (non-subscriber) → skipped, not fatal
    assert res["errors"] == 0, res          # the note 404 did NOT fail the fan
    assert ("nick", fan, "Max/NYC") in calls, calls
    assert any(c[0] == "note" for c in calls), "note push was attempted separately"

    # Local mirror: ONLY the column that actually landed on OF is written. The
    # nickname pushed → custom_nickname mirrors it; the note 404'd → notes stays
    # blank (no phantom local note) so the UI matches OF.
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
