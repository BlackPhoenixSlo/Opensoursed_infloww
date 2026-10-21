#!/usr/bin/env python3
"""
mass_detect — retro-tag OF-native mass blasts (per-fan rows, no mass_run_id).

  case_splits_separate_bursts:
      the same line sent to a burst, then again 10min later, becomes TWO
      MassRuns ("yooo sent twice as a mass" → two summary rows).
  case_one_burst_within_gap:
      sends spaced ≤ gap_seconds stay a single burst.
  case_min_recipients_floor:
      a body to fewer than min_recipients fans is left untouched (no run).
  case_skips_automation_kind:
      per-fan automation rows (automation_kind set) are never swept up.
  case_idempotent_rerun:
      a second sweep tags nothing new (only mass_run_id IS NULL rows).

Run: ./venv/bin/python service/tests/test_mass_detect.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Account, MassRun, Message  # noqa: E402
from mass_detect import detect_mass_bursts  # noqa: E402

_T0 = datetime(2026, 6, 12, 11, 0, 0)
_mid = [1000]  # monotonic message_id source across cases


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _send(aid: str, *, fan_id: int, body: str, at: datetime,
                automation_kind: str | None = None) -> None:
    _mid[0] += 1
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan_id, message_id=_mid[0],
            direction="out", body=body, created_at=at,
            automation_kind=automation_kind,
        ))


async def _runs(aid: str) -> list[MassRun]:
    async with get_session() as s:
        return list((await s.execute(
            select(MassRun).where(MassRun.account_id == aid)
        )).scalars().all())


async def _tagged_count(aid: str) -> int:
    async with get_session() as s:
        rows = (await s.execute(
            select(Message).where(
                Message.account_id == aid, Message.mass_run_id.is_not(None)
            )
        )).scalars().all()
        return len(rows)


# ── two bursts of the same line, 10min apart → two runs ───────────────
async def case_splits_separate_bursts():
    aid = "md_two"
    await _seed_account(aid)
    for i in range(6):  # burst 1: 6 fans within seconds
        await _send(aid, fan_id=100 + i, body="yooo", at=_T0 + timedelta(seconds=i))
    for i in range(6):  # burst 2: 6 fans, +10min (> 180s gap)
        await _send(aid, fan_id=200 + i, body="yooo", at=_T0 + timedelta(minutes=10, seconds=i))
    res = await detect_mass_bursts(account_ids=[aid], min_recipients=5)
    assert res["runs_created"] == 2, f"want 2 runs, got {res['runs_created']}"
    assert res["rows_tagged"] == 12, f"want 12 tagged, got {res['rows_tagged']}"
    assert len(await _runs(aid)) == 2
    for r in await _runs(aid):
        assert r.recipient_count == 6, f"each run = 6 fans, got {r.recipient_count}"


# ── sends ≤ gap stay one burst ────────────────────────────────────────
async def case_one_burst_within_gap():
    aid = "md_one"
    await _seed_account(aid)
    # 5 sends each 60s apart → max gap 60s ≤ 180s default → single burst.
    for i in range(5):
        await _send(aid, fan_id=300 + i, body="hey", at=_T0 + timedelta(seconds=60 * i))
    res = await detect_mass_bursts(account_ids=[aid], min_recipients=5)
    assert res["runs_created"] == 1, f"want 1 run, got {res['runs_created']}"


# ── below the floor → untouched ───────────────────────────────────────
async def case_min_recipients_floor():
    aid = "md_floor"
    await _seed_account(aid)
    for i in range(3):  # only 3 fans, floor is 5
        await _send(aid, fan_id=400 + i, body="sup", at=_T0 + timedelta(seconds=i))
    res = await detect_mass_bursts(account_ids=[aid], min_recipients=5)
    assert res["runs_created"] == 0, f"want 0 runs, got {res['runs_created']}"
    assert await _tagged_count(aid) == 0, "rows below floor must stay untagged"


# ── automation sends are never grouped ────────────────────────────────
async def case_skips_automation_kind():
    aid = "md_auto"
    await _seed_account(aid)
    for i in range(8):  # 8 identical welcome sends in a burst, but automation
        await _send(aid, fan_id=500 + i, body="welcome babe",
                    at=_T0 + timedelta(seconds=i), automation_kind="send_welcome")
    res = await detect_mass_bursts(account_ids=[aid], min_recipients=5)
    assert res["runs_created"] == 0, "automation_kind rows must be skipped"
    assert await _tagged_count(aid) == 0


# ── re-running tags nothing new ───────────────────────────────────────
async def case_idempotent_rerun():
    aid = "md_idem"
    await _seed_account(aid)
    for i in range(6):
        await _send(aid, fan_id=600 + i, body="blast", at=_T0 + timedelta(seconds=i))
    first = await detect_mass_bursts(account_ids=[aid], min_recipients=5)
    assert first["runs_created"] == 1
    second = await detect_mass_bursts(account_ids=[aid], min_recipients=5)
    assert second["runs_created"] == 0, "re-run must not re-tag already-grouped rows"
    assert len(await _runs(aid)) == 1, "no duplicate MassRun on re-run"


_harness.run(
    case_splits_separate_bursts,
    case_one_burst_within_gap,
    case_min_recipients_floor,
    case_skips_automation_kind,
    case_idempotent_rerun,
)
