#!/usr/bin/env python3
"""
fan_data — the per-fan profile rows behind Stats → Fan reports → User data
(`GET /admin/stats/per-fan-data`). Read-only on our DB.

  case_build_fan_data:
      one profiled fan + its fans row + transactions → one dict: name, nickname,
      fact-line bullets, spend = cleared + pending (chargebacks and NULL-fan
      rebills excluded), last_updated, note_on_of.
  case_limit_caps_profiles:
      `limit` caps the profiled fans read.
  case_build_rows_fallbacks:
      pure row building: fan_name / nickname / last_updated fall-backs.

Run: ./venv/bin/python service/tests/test_fan_data.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

from datetime import datetime  # noqa: E402

import fan_data  # noqa: E402 — module under test
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, FanProfile, Transaction  # noqa: E402


# ── Seed helpers ─────────────────────────────────────────────────────────

async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_fan(aid: str, fan_id: int, *, name: str = "Bob", **facts) -> None:
    async with get_session() as s:
        if await s.get(Fan, (aid, fan_id)) is None:
            s.add(Fan(account_id=aid, fan_id=fan_id, of_display_name=name,
                      of_username=name.lower(), **facts))


async def _seed_profile(aid: str, fan_id: int, **cols) -> None:
    async with get_session() as s:
        s.add(FanProfile(account_id=aid, fan_id=fan_id, **cols))


async def _seed_txn(aid: str, fan_id: int | None, cents: int, *,
                    status: str = "cleared", kind: str = "tip") -> None:
    async with get_session() as s:
        s.add(Transaction(
            account_id=aid, fan_id=fan_id, kind=kind, amount_cents=cents,
            status=status, occurred_at=datetime(2026, 6, 1, 12, 0, 0),
        ))


# ── The read ─────────────────────────────────────────────────────────────

async def case_build_fan_data():
    aid, fan = "acc_fd_build", 5001
    await _seed_account(aid)
    # Facts on the fans row → bullet_points is the useful-first fact line (NOT the
    # stored gen_info bullet_points "b1; b2").
    await _seed_fan(aid, fan, name="Bob", occupation="Dev", hobbies="gaming, hiking",
                    relationship_status="single", fetishes="feet",
                    recent_events='["new job", "puppy"]',
                    notes="Recent: new job; puppy")  # OF-mirror set → note_on_of "added"
    await _seed_profile(
        aid, fan, nickname="Bobby", short_bio="likes cars", bullet_points="b1; b2",
        q1="Q1?", q2="Q2?", q3="Q3?", tease1="T1", tease2="T2", tease3="T3",
        message_count_at_gen=42, last_generated_at=datetime(2026, 6, 2, 8, 0, 0),
    )
    # Two CLEARED ($30.00) + one PENDING ($99.99, counted: pending sales always
    # count) + a CHARGEDBACK row and a NULL-fan rebill (both excluded).
    await _seed_txn(aid, fan, 1000)
    await _seed_txn(aid, fan, 2000)
    await _seed_txn(aid, fan, 9999, status="pending")
    await _seed_txn(aid, fan, 7777, status="chargedback")
    await _seed_txn(aid, None, 5000)

    rows = await fan_data.build_fan_data(aid)
    assert len(rows) == 1, rows
    r = rows[0]
    assert r["account_id"] == aid, r
    assert r["fan_name"] == "Bob", r
    assert r["fan_id"] == fan and r["chat_id"] == fan, r
    assert r["nickname"] == "Bobby", r
    assert r["short_bio"] == "likes cars", r
    assert r["bullet_points"] == (
        "Recent: new job; puppy\nIntr: gaming, hiking\nJob: Dev\n"
        "Rel: single\nKinks: feet\nlikes cars"
    ), r["bullet_points"]
    assert (r["q1"], r["tease1"]) == ("Q1?", "T1"), r
    assert r["total_spend"] == 129.99, r          # dollars, cleared + pending
    assert r["message_count"] == 42, r
    assert r["last_updated"] == "2026-06-02T08:00:00", r
    assert r["note_on_of"] == "added", r


async def case_limit_caps_profiles():
    aid = "acc_fd_limit"
    await _seed_account(aid)
    for fid in (7001, 7002, 7003):
        await _seed_fan(aid, fid, name=f"F{fid}")
        await _seed_profile(aid, fid, nickname=f"N{fid}")
    rows = await fan_data.build_fan_data(aid, 2)
    assert [r["fan_id"] for r in rows] == [7001, 7002], rows


# ── Pure row-building: fall-backs (no DB) ─────────────────────────────────

def case_build_rows_fallbacks():
    # Profile A: a Fan row exists → fan_name from of_display_name, nickname from
    # profile, last_updated from last_generated_at.
    pa = FanProfile(account_id="a", fan_id=1, nickname="NickA",
                    short_bio="A bio", q1="qa", bullet_points="legacy A",
                    message_count_at_gen=7,
                    last_generated_at=datetime(2026, 1, 2, 3, 4, 5))
    # Fan A HAS facts → bullet_points is the fact line + bio, NOT the stored "legacy A".
    # notes set (OF mirror) → note_on_of "added".
    fa = Fan(account_id="a", fan_id=1, of_display_name="DisplayA",
             of_username="usera", occupation="Dev", hobbies="gym", notes="on OF")
    # Profile B: NO Fan row → fan_name falls back to original_name; nickname blank;
    # with no facts the bullet_points is just the short_bio (no messy raw-bullets).
    pb = FanProfile(account_id="a", fan_id=2, nickname=None, short_bio="B's bio",
                    original_name="OrigB", message_count_at_gen=0)
    # Profile C: NO Fan row, NO original_name → fan_name falls back to str(fid).
    pc = FanProfile(account_id="a", fan_id=3, nickname=None,
                    message_count_at_gen=0)

    rows = fan_data._build_rows([pa, pb, pc], {1: fa}, {1: 250, 2: 0})
    assert rows[0].fan_name == "DisplayA", rows[0].fan_name
    assert rows[0].nickname == "NickA", rows[0].nickname
    assert rows[0].last_updated == "2026-01-02T03:04:05", rows[0].last_updated
    assert rows[0].bullet_points == "Intr: gym\nJob: Dev\nA bio", rows[0].bullet_points
    assert rows[0].note_on_of == "added", rows[0].note_on_of      # fans.notes set
    assert rows[1].fan_name == "OrigB", rows[1].fan_name
    assert rows[1].bullet_points == "B's bio", rows[1].bullet_points  # bio only, no facts
    assert rows[2].note_on_of == "not added", rows[2].note_on_of  # no fan row → no OF note
    assert rows[2].fan_name == "3", rows[2].fan_name  # str(fan_id) last resort

    # Spend: 250c for A; B's explicit 0 and C's missing entry both read 0.
    assert [r.total_spend_cents for r in rows] == [250, 0, 0], rows
    # The endpoint's `columns` contract, positional.
    assert fan_data._HEADER == [
        "fan_name", "fan_id", "chat_id", "nickname", "short_bio", "bullet_points",
        "Q1", "Q2", "Q3", "Tease1", "Tease2", "Tease3",
        "total_spend", "message_count", "last_updated", "note_on_of",
    ], fan_data._HEADER


_harness.run(
    case_build_fan_data,
    case_limit_caps_profiles,
    case_build_rows_fallbacks,
)
