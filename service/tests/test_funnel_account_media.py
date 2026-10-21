#!/usr/bin/env python3
"""
funnel_account_media — per-(funnel, account) MEDIA binding (CRUD + resolution).

A funnel's TEXT is global (mass_message_funnels); its MEDIA is per-account because
OnlyFans vault ids don't carry between models. This covers the /admin/funnels/
{id}/media/{account} routes (funnels_api.py) and the send-time opener resolution
(send_mass_message._opener_media). The per-account PPV STEP resolution at send
time is covered in test_reply_mass_funnel.py (case_ppv_media_is_per_account).

  case_empty_default:
      GET for a (funnel, account) with no row → empty opener + steps_media.
  case_put_round_trip:
      PUT opener + steps_media → persists, clamps previews to the media set,
      drops empty step entries, and round-trips via GET.
  case_put_upsert_overwrites:
      a second PUT replaces the prior binding (idempotent upsert).
  case_reject_bad_media:
      non-vault ids / a non-digit step key → 422.
  case_funnel_must_exist:
      GET/PUT for an unknown funnel id → 404.
  case_delete_clears:
      DELETE removes the row; GET then returns the empty default again.
  case_opener_resolution:
      send_mass_message._opener_media returns the model's bound opener media.

Run: ./venv/bin/python service/tests/test_funnel_account_media.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

from fastapi import HTTPException  # noqa: E402

import automations.send_mass_message as a10  # noqa: E402
from funnels_api import (  # noqa: E402
    FunnelCreate, FunnelMediaBody, create_funnel, delete_funnel_media,
    get_funnel_media, put_funnel_media,
)
from db.engine import get_session  # noqa: E402
from db.models import Account  # noqa: E402

AID = "acc_media"


async def _seed_account(aid: str = AID) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _new_funnel(name: str) -> int:
    out = await create_funnel(FunnelCreate(
        name=name, opening_message="How many strokes? 😈",
        steps=[{"step": 1, "check_intervals_min": [2], "messages": ["m"]},
               {"step": 2, "type": "paid_ppv", "price": 24, "messages": ["open"]}],
    ))
    return int(out["id"])


# ── empty default ─────────────────────────────────────────────────────

async def case_empty_default():
    await _seed_account()
    fid = await _new_funnel("media_empty")
    got = await get_funnel_media(fid, AID)
    assert got["opening_media_ids"] == [] and got["steps_media"] == {}, got


# ── put → get round-trip (with preview clamp + empty-entry drop) ──────

async def case_put_round_trip():
    await _seed_account()
    fid = await _new_funnel("media_rt")
    saved = await put_funnel_media(fid, AID, FunnelMediaBody(
        opening_media_ids=[101, "102"],
        steps_media={
            "2": {"media_files": [201, 202], "previews": [201, 999]},  # 999 not in set
            "5": {"media_files": [], "previews": []},                   # empty → dropped
        },
    ))
    assert saved["opening_media_ids"] == [101, 102], saved
    assert saved["steps_media"]["2"]["media_files"] == [201, 202], saved
    # preview clamped to the media set (999 dropped).
    assert saved["steps_media"]["2"]["previews"] == [201], saved
    assert "5" not in saved["steps_media"], ("empty step entry dropped", saved)

    got = await get_funnel_media(fid, AID)
    assert got["opening_media_ids"] == [101, 102], got
    assert got["steps_media"]["2"]["media_files"] == [201, 202], got


# ── upsert overwrites ─────────────────────────────────────────────────

async def case_put_upsert_overwrites():
    await _seed_account()
    fid = await _new_funnel("media_upsert")
    await put_funnel_media(fid, AID, FunnelMediaBody(opening_media_ids=[1, 2]))
    saved = await put_funnel_media(fid, AID, FunnelMediaBody(
        opening_media_ids=[9], steps_media={"2": {"media_files": [7]}}))
    assert saved["opening_media_ids"] == [9], saved
    assert saved["steps_media"]["2"]["media_files"] == [7], saved


# ── validation ────────────────────────────────────────────────────────

async def case_reject_bad_media():
    await _seed_account()
    fid = await _new_funnel("media_bad")
    for body in (
        FunnelMediaBody(opening_media_ids=[1.5]),
        FunnelMediaBody(opening_media_ids=["x"]),
        FunnelMediaBody(steps_media={"2": {"media_files": ["nope"]}}),
        FunnelMediaBody(steps_media={"two": {"media_files": [1]}}),  # non-digit key
    ):
        try:
            await put_funnel_media(fid, AID, body)
            assert False, f"expected 422 for {body!r}"
        except HTTPException as e:
            assert e.status_code == 422, (body, e)


# ── funnel must exist ─────────────────────────────────────────────────

async def case_funnel_must_exist():
    await _seed_account()
    try:
        await get_funnel_media(999999, AID)
        assert False, "expected 404 for unknown funnel"
    except HTTPException as e:
        assert e.status_code == 404, e
    try:
        await put_funnel_media(999999, AID, FunnelMediaBody(opening_media_ids=[1]))
        assert False, "expected 404 for unknown funnel on PUT"
    except HTTPException as e:
        assert e.status_code == 404, e


# ── delete clears ─────────────────────────────────────────────────────

async def case_delete_clears():
    await _seed_account()
    fid = await _new_funnel("media_del")
    await put_funnel_media(fid, AID, FunnelMediaBody(opening_media_ids=[1, 2, 3]))
    res = await delete_funnel_media(fid, AID)
    assert res["cleared"] is True, res
    got = await get_funnel_media(fid, AID)
    assert got["opening_media_ids"] == [] and got["steps_media"] == {}, got


# ── send-time opener resolution ───────────────────────────────────────

async def case_opener_resolution():
    await _seed_account()
    fid = await _new_funnel("media_opener")
    # No binding → no opener media.
    media, previews = await a10._opener_media(fid, AID)
    assert media == [] and previews == [], (media, previews)
    # Bound → that model's opener vault ids.
    await put_funnel_media(fid, AID, FunnelMediaBody(opening_media_ids=[501, 502]))
    media, _ = await a10._opener_media(fid, AID)
    assert media == [501, 502], media
    # A different model sees its OWN (absent) binding, not this one's.
    media2, _ = await a10._opener_media(fid, "acc_other")
    assert media2 == [], media2


_harness.run(
    case_empty_default,
    case_put_round_trip,
    case_put_upsert_overwrites,
    case_reject_bad_media,
    case_funnel_must_exist,
    case_delete_clears,
    case_opener_resolution,
)
