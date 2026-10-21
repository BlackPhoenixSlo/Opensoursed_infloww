#!/usr/bin/env python3
"""
funnels_api — CRUD routes over `mass_message_funnels` (W8 FUNNEL-API lane).

Drives the route coroutines directly (no HTTP) against the temp DB. Funnels are
GLOBAL (no account scoping), so there's no owner gate to exercise here — the
focus is the step-shape validation + the DELETE-409 guard against orphaning a
live funnel_state.

Funnel TEXT is global; funnel MEDIA is per-account and lives in a separate table
(funnel_account_media — covered by test_funnel_account_media.py). So these CRUD
cases are TEXT-ONLY: a PPV step carries price/copy/locked_text but NO media_files
(the API no longer validates or requires step media).

  case_create_round_trip:
      create a funnel (opener + a reply step + a text-only PPV step) → it
      persists with the right step_count, lists in the summary, round-trips full.
  case_reject_step_missing_messages:
      a reply step with neither static `messages` nor `prompt`/`generate` → 422.
  case_reject_bad_intervals:
      a reply step with a non-positive `check_intervals_min` → 422.
  case_reject_unknown_step_type:
      a step with an unknown `type` → 422 (media is NO LONGER validated here).
  case_unique_name_conflict:
      a second funnel with the same name → 409.
  case_update_partial:
      PUT rewrites opening_message + steps, leaves untouched fields alone.
  case_delete_409_when_referenced:
      DELETE returns 409 while a mass_run references the funnel; succeeds once
      the reference is gone.

Run: ./venv/bin/python service/tests/test_funnels_api.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import funnels_api as api  # noqa: E402 — module under test
from funnels_api import (  # noqa: E402
    FunnelCreate, FunnelUpdate, create_funnel, delete_funnel, get_funnel,
    list_funnels, update_funnel,
)
from db.engine import get_session  # noqa: E402
from db.models import Account, MassRun  # noqa: E402


_REPLY_STEP = {
    "step": 1, "check_intervals_min": [2, 4, 10],
    "messages": ["bet you lose count once it starts", "or do you stay focused? c:"],
}
_PPV_STEP = {
    "step": 2, "type": "paid_ppv", "price": 24,
    "messages": ["open this and show me how obedient you are"],
}


# ── create → list → get ───────────────────────────────────────────────

async def case_create_round_trip():
    out = await create_funnel(FunnelCreate(
        name="strokes_test", description="warmup → PPV",
        opening_message="How many strokes? 😈",
        steps=[_REPLY_STEP, _PPV_STEP],
    ))
    assert out["id"] and out["name"] == "strokes_test", out
    assert out["step_count"] == 2, out
    assert out["opening_message"] == "How many strokes? 😈", out
    # full GET round-trips the parsed steps verbatim (text-only; media is
    # per-account and lives in funnel_account_media, not on the step).
    full = await get_funnel(out["id"])
    assert full["steps"][0]["messages"][0].startswith("bet you"), full
    assert full["steps"][1]["type"] == "paid_ppv", full
    assert "media_files" not in full["steps"][1], full

    listed = await list_funnels()
    row = next(f for f in listed["funnels"] if f["id"] == out["id"])
    assert row["step_count"] == 2 and "steps" not in row, ("summary is lean", row)


# ── validation: a reply step missing its text ─────────────────────────

async def case_reject_step_missing_messages():
    try:
        await create_funnel(FunnelCreate(
            name="bad_no_msg", opening_message="hi",
            steps=[{"step": 1, "check_intervals_min": [2, 4]}],  # no messages/prompt
        ))
        assert False, "expected 422 for a step with no messages/prompt"
    except HTTPException as e:
        assert e.status_code == 422, e

    # a generated step (prompt only) is fine — no static messages required.
    ok = await create_funnel(FunnelCreate(
        name="gen_ok", opening_message="hi",
        steps=[{"step": 1, "check_intervals_min": [2], "prompt": "tease them"}],
    ))
    assert ok["step_count"] == 1, ok


# ── validation: malformed intervals ───────────────────────────────────

async def case_reject_bad_intervals():
    for bad in ([2, -4, 10], [0], "soon", []):
        try:
            await create_funnel(FunnelCreate(
                name=f"bad_iv_{bad}", opening_message="hi",
                steps=[{"step": 1, "check_intervals_min": bad, "messages": ["m"]}],
            ))
            assert False, f"expected 422 for intervals={bad}"
        except HTTPException as e:
            assert e.status_code == 422, (bad, e)


# ── validation: unknown step type rejected; media NO LONGER validated ─

async def case_reject_unknown_step_type():
    # an unknown step `type` is rejected.
    try:
        await create_funnel(FunnelCreate(
            name="bad_type", opening_message="hi",
            steps=[{"step": 1, "type": "free_gift", "messages": ["m"]}],
        ))
        assert False, "expected 422 for unknown step type"
    except HTTPException as e:
        assert e.status_code == 422, e

    # Media is per-account now: a step that still carries `media_files` is NOT
    # rejected — it passes through untouched (back-compat) and the API ignores it.
    ok = await create_funnel(FunnelCreate(
        name="legacy_media_ok", opening_message="hi",
        steps=[{"step": 1, "type": "paid_ppv", "price": 5,
                "media_files": [999], "messages": ["m"]}],
    ))
    assert ok["step_count"] == 1, ok


# ── branching: `next` maps validate shape + target existence ──────────

async def case_next_branch_valid():
    """A well-formed `next` map (bought/ignored/default + a keyword map) whose
    targets all reference existing steps is accepted and round-trips verbatim."""
    out = await create_funnel(FunnelCreate(
        name="branch_ok", opening_message="hi",
        steps=[
            {"step": 1, "check_intervals_min": [2], "messages": ["s1"],
             "next": {"keyword": {"more": 3}, "ignored": 2, "default": 2}},
            {"step": 2, "check_intervals_min": [2], "messages": ["s2"]},
            {"step": 3, "type": "paid_ppv", "price": 20, "messages": ["s3"],
             "next": {"bought": 3}},
        ],
    ))
    assert out["step_count"] == 3, out
    full = await get_funnel(out["id"])
    assert full["steps"][0]["next"]["keyword"]["more"] == 3, full
    assert full["steps"][2]["next"]["bought"] == 3, full


async def case_reject_next_dangling_target():
    """A `next` target that names a step number with no matching step → 422 (a
    dangling route would strand a fan mid-storyline)."""
    for bad_next in (
        {"default": 9},               # no step 9
        {"bought": 4},                # no step 4
        {"keyword": {"more": 7}},     # keyword target missing
        {"ignored": 0},               # step numbers are >=1
    ):
        try:
            await create_funnel(FunnelCreate(
                name=f"dangling_{list(bad_next)[0]}_{list(bad_next.values())[0]}",
                opening_message="hi",
                steps=[
                    {"step": 1, "check_intervals_min": [2], "messages": ["s1"],
                     "next": bad_next},
                    {"step": 2, "check_intervals_min": [2], "messages": ["s2"]},
                ],
            ))
            assert False, f"expected 422 for dangling next={bad_next}"
        except HTTPException as e:
            assert e.status_code == 422, (bad_next, e)


async def case_reject_next_bad_shape():
    """Malformed `next` maps are rejected: not an object, an unknown key, a
    non-int target, or an empty/blank-keyword keyword map."""
    good_steps = [{"step": 2, "check_intervals_min": [2], "messages": ["s2"]}]
    for bad_next in (
        "step2",                       # not an object
        {"maybe": 2},                  # unknown key
        {"default": "2"},              # non-int target
        {"default": 1.5},              # fractional target
        {"keyword": {}},               # empty keyword map
        {"keyword": {"  ": 2}},        # blank keyword
        {"keyword": {"more": "2"}},    # non-int keyword target
    ):
        try:
            await create_funnel(FunnelCreate(
                name=f"badshape_{abs(hash(str(bad_next)))}",
                opening_message="hi",
                steps=[{"step": 1, "check_intervals_min": [2], "messages": ["s1"],
                        "next": bad_next}] + good_steps,
            ))
            assert False, f"expected 422 for next={bad_next!r}"
        except HTTPException as e:
            assert e.status_code == 422, (bad_next, e)


# ── unique name ───────────────────────────────────────────────────────

async def case_unique_name_conflict():
    await create_funnel(FunnelCreate(name="dup", opening_message="a"))
    try:
        await create_funnel(FunnelCreate(name="dup", opening_message="b"))
        assert False, "expected 409 for a duplicate name"
    except HTTPException as e:
        assert e.status_code == 409, e


# ── partial update ────────────────────────────────────────────────────

async def case_update_partial():
    created = await create_funnel(FunnelCreate(
        name="edit_me", description="orig", opening_message="old opener",
        steps=[_REPLY_STEP],
    ))
    fid = created["id"]

    patched = await update_funnel(fid, FunnelUpdate(
        opening_message="new opener", steps=[_REPLY_STEP, _PPV_STEP],
    ))
    assert patched["opening_message"] == "new opener", patched
    assert patched["step_count"] == 2, patched
    # untouched fields survive a partial PUT.
    assert patched["name"] == "edit_me" and patched["description"] == "orig", patched


# ── delete is blocked while a mass_run references the funnel ───────────

async def case_delete_409_when_referenced():
    created = await create_funnel(FunnelCreate(
        name="live_funnel", opening_message="hi", steps=[_REPLY_STEP],
    ))
    fid = created["id"]

    async with get_session() as s:
        if await s.get(Account, "acc_funnel") is None:
            s.add(Account(id="acc_funnel"))
        await s.flush()
        s.add(MassRun(account_id="acc_funnel", funnel_id=fid, status="ok"))

    # A live mass_run anchors funnel_state → delete is refused.
    try:
        await delete_funnel(fid)
        assert False, "expected 409 while a mass_run references the funnel"
    except HTTPException as e:
        assert e.status_code == 409, e

    # Drop the reference → the delete now goes through.
    async with get_session() as s:
        from sqlalchemy import delete as sa_delete
        await s.execute(sa_delete(MassRun).where(MassRun.funnel_id == fid))

    res = await delete_funnel(fid)
    assert res["deleted"] == fid, res
    try:
        await get_funnel(fid)
        assert False, "expected 404 after delete"
    except HTTPException as e:
        assert e.status_code == 404, e


_harness.run(
    case_create_round_trip,
    case_reject_step_missing_messages,
    case_reject_bad_intervals,
    case_reject_unknown_step_type,
    case_next_branch_valid,
    case_reject_next_dangling_target,
    case_reject_next_bad_shape,
    case_unique_name_conflict,
    case_update_partial,
    case_delete_409_when_referenced,
)
