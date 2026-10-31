#!/usr/bin/env python3
"""
The whole-vault flags sweep (`vault_ai_vision.flags_all` + `_run_flags_all`).
Durable regression suite (plain-assert, no pytest — repo convention).

WHY THIS EXISTS. The sweep used to run inline in its own POST. A vault of 327
items at ~3.4s each is ~18 minutes, so the app's proxy dropped the socket and
the operator was shown "Internal Server Error" — for a sweep that was
SUCCEEDING. The relay never logged a 500; the evidence was in the app container
(`Failed to proxy .../flags-all  Error: socket hang up`, ECONNRESET). Three
things followed from that one shape:

  * the request looked failed while the work carried on invisibly;
  * the coroutine survives client disconnect, so every retry click added
    ANOTHER concurrent sweep over the same rows;
  * with the flags incomplete, the three lanes that need them stay starved, so
    the folder plan sorted 198 of 327 items and the SORTER got blamed.

Cases:
  case_post_returns_before_the_sweep_finishes:
      the endpoint answers while the sweep is still running. This is the bug.
  case_second_click_does_not_start_a_second_sweep:
      one sweep per account, so a button that appears to have failed cannot
      multiply the work (and the spend) behind it.
  case_status_reports_progress_and_db_coverage:
      progress is this process's counter and dies with a restart; coverage is
      read from the DB, so a UI reconnecting after a redeploy still sees where
      the vault stands.
  case_todo_skips_current_and_keeps_stale:
      resumability. The sweep only ever visits missing/stale rows, so a restart
      costs the items in flight and nothing else.
  case_named_ids_stay_inline:
      the grading probe passes explicit media_ids and wants the ANSWERS in the
      response, not a job id.
  case_a_failing_item_does_not_stop_the_sweep:
      one bad item must not strand the other 300.
  case_done_counts_visits_so_a_finished_pass_reads_as_finished:
      `done` counts VISITS, so done==total means "this pass is over" — the one
      question the counter is ever asked. Owned by `vault_sweep.run`.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_flags_sweep.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod). No OF, no
network, no LLM.
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

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import llm_client  # noqa: E402
import vault_ai_vision  # noqa: E402


# flags-all pre-flights the vision key (a missing one is the typed 424, pinned
# in test_api_key_errors). These cases fake the vision pass, so a key is present.
async def _key_present(*_a, **_k) -> bool:
    return True


llm_client.llm_key_available = _key_present
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultItem  # noqa: E402

_N = 0


def _next_account() -> str:
    global _N
    _N += 1
    return f"flagsweep{_N}"


def _flagged(v: int = vault_ai_vision._FLAGS_VERSION) -> dict:
    """A COMPLETE flags answer at version `v` — `flags_known` needs every
    region, so a partial one would exercise the unflagged path while looking
    like a flagged item."""
    return {"underwear_visible": False, "vulva_vis": "not_in_frame",
            "breasts_vis": "covered", "anus_vis": "not_in_frame",
            "over_breasts": "black top", "_flags_v": v}


async def _seed(aid: str, rows: list[tuple[int, dict | None]],
                kind: str = "photo") -> None:
    base = datetime(2026, 7, 1, 12, 0, 0)
    async with get_session() as s:
        s.add(Account(id=aid))
        for i, (mid, fields) in enumerate(rows):
            s.add(VaultItem(account_id=aid, media_id=mid, kind=kind, tags="[]",
                            created_at=base + timedelta(seconds=i),
                            ai_fields_json=json.dumps(fields) if fields else None))
        await s.commit()


class _Gate:
    """Stand-in for `_flags_one` that can be held open, so a case can observe
    the sweep WHILE it runs rather than only after."""

    def __init__(self, *, hold: bool = False, fail: set[int] | None = None) -> None:
        self.calls: list[int] = []
        self.release = asyncio.Event()
        self.hold = hold
        self.fail = fail or set()

    async def __call__(self, account_id: str, media_id: int, **_k) -> dict:
        self.calls.append(int(media_id))
        if self.hold:
            await self.release.wait()
        if int(media_id) in self.fail:
            return {"media_id": media_id, "ok": False, "status": "error",
                    "detail": "provider down"}
        async with get_session() as s:
            item = await s.get(VaultItem, (account_id, media_id))
            fields = json.loads(item.ai_fields_json) if item.ai_fields_json else {}
            fields.update(_flagged())
            item.ai_fields_json = json.dumps(fields)
            await s.commit()
        return {"media_id": media_id, "ok": True, "status": "flagged",
                "cost_millicents": 1}


async def _drain(aid: str) -> None:
    """Let the background task finish before the next case reuses the module."""
    for _ in range(200):
        if aid not in vault_ai_vision._flags_running:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("sweep never finished")


# ── Cases ────────────────────────────────────────────────────────────

async def case_post_returns_before_the_sweep_finishes():
    aid = _next_account()
    await _seed(aid, [(i, None) for i in range(600, 610)])
    gate = _Gate(hold=True)
    orig, vault_ai_vision._flags_one = vault_ai_vision._flags_one, gate
    try:
        out = await asyncio.wait_for(
            vault_ai_vision.flags_all({"account_id": aid}), timeout=1.0)
        assert out["status"] == "running", out
        assert out["candidates"] == 10, out
        assert out["already"] is False, out
        # The work has NOT been done yet — that is the whole point.
        await asyncio.sleep(0.05)
        assert len(gate.calls) < 10, (
            "the endpoint waited for the sweep it was supposed to hand off")
        gate.release.set()
        await _drain(aid)
        assert sorted(gate.calls) == list(range(600, 610)), gate.calls
    finally:
        gate.release.set()
        vault_ai_vision._flags_one = orig


async def case_second_click_does_not_start_a_second_sweep():
    aid = _next_account()
    await _seed(aid, [(i, None) for i in range(620, 626)])
    gate = _Gate(hold=True)
    orig, vault_ai_vision._flags_one = vault_ai_vision._flags_one, gate
    try:
        first = await vault_ai_vision.flags_all({"account_id": aid})
        second = await vault_ai_vision.flags_all({"account_id": aid})
        third = await vault_ai_vision.flags_all({"account_id": aid})
        assert first["already"] is False, first
        assert second["already"] is True and third["already"] is True, (second, third)
        gate.release.set()
        await _drain(aid)
        # Each item flagged exactly once. Before the guard, three clicks meant
        # three concurrent sweeps over the same rows — triple the spend.
        assert sorted(gate.calls) == list(range(620, 626)), gate.calls
    finally:
        gate.release.set()
        vault_ai_vision._flags_one = orig


async def case_status_reports_progress_and_db_coverage():
    aid = _next_account()
    await _seed(aid, [(i, None) for i in range(640, 644)])
    gate = _Gate(hold=True)
    orig, vault_ai_vision._flags_one = vault_ai_vision._flags_one, gate
    try:
        idle = await vault_ai_vision.flags_all_status(account_id=aid)
        assert idle["running"] is False, idle
        assert idle["coverage"] == {"stills": 4, "flagged": 0, "missing": 4,
                                    "ready": False}, idle["coverage"]

        await vault_ai_vision.flags_all({"account_id": aid})
        await asyncio.sleep(0.05)
        mid = await vault_ai_vision.flags_all_status(account_id=aid)
        assert mid["running"] is True, mid
        assert mid["progress"]["total"] == 4, mid["progress"]

        gate.release.set()
        await _drain(aid)
        done = await vault_ai_vision.flags_all_status(account_id=aid)
        assert done["running"] is False, done
        assert done["progress"]["done"] == 4 and done["progress"]["failed"] == 0, done
        # Coverage is the DURABLE half — it survives the process losing its counter.
        assert done["coverage"]["ready"] is True, done["coverage"]
        vault_ai_vision._flags_progress.pop(aid, None)
        after_restart = await vault_ai_vision.flags_all_status(account_id=aid)
        assert after_restart["progress"] is None
        assert after_restart["coverage"]["flagged"] == 4, after_restart["coverage"]
    finally:
        gate.release.set()
        vault_ai_vision._flags_one = orig


async def case_todo_skips_current_and_keeps_stale():
    aid = _next_account()
    await _seed(aid, [
        (660, _flagged()),                              # current — skip
        (661, _flagged(vault_ai_vision._FLAGS_VERSION - 1)),        # older prompt — redo
        (662, None),                                    # never flagged — do
        (663, {"vulva_vis": "bare", "_flags_v": vault_ai_vision._FLAGS_VERSION}),  # partial — redo
    ])
    # NEWEST-first (_seed stamps created_at ascending, so 663 is the most
    # recent). The order is asserted, not just the membership, because `limit`
    # makes it decide WHICH items a bounded pass covers at all.
    todo = await vault_ai_vision._flags_todo(aid)
    assert todo == [663, 662, 661], todo
    assert await vault_ai_vision._flags_todo(aid, force=True) == [663, 662, 661, 660]
    assert await vault_ai_vision._flags_todo(aid, limit=2) == [663, 662]
    # A named set is taken as given — the caller is asking for these.
    assert await vault_ai_vision._flags_todo(aid, only={660}) == [660]


async def case_named_ids_stay_inline():
    aid = _next_account()
    await _seed(aid, [(670, None), (671, None)])
    gate = _Gate()
    orig, vault_ai_vision._flags_one = vault_ai_vision._flags_one, gate
    try:
        out = await vault_ai_vision.flags_all({"account_id": aid, "media_ids": [670]})
        # Answers in the response, not a job id — the grading probe reads these.
        assert out["flagged"] == 1 and out["failed"] == 0, out
        assert out["complete"] is True, out
        assert "status" not in out, "a named set must not be handed off"
        assert gate.calls == [670], gate.calls
        assert aid not in vault_ai_vision._flags_running
    finally:
        vault_ai_vision._flags_one = orig


async def case_a_failing_item_does_not_stop_the_sweep():
    aid = _next_account()
    await _seed(aid, [(i, None) for i in range(680, 685)])
    gate = _Gate(fail={682})
    orig, vault_ai_vision._flags_one = vault_ai_vision._flags_one, gate
    try:
        await vault_ai_vision.flags_all({"account_id": aid})
        await _drain(aid)
        assert sorted(gate.calls) == list(range(680, 685)), gate.calls
        prog = vault_ai_vision._flags_progress[aid]
        assert prog["done"] == 5 and prog["failed"] == 1, prog
        assert prog["error"] == "provider down", prog
        # The one bad row is exactly what a re-run picks up.
        assert await vault_ai_vision._flags_todo(aid) == [682]
    finally:
        vault_ai_vision._flags_one = orig


async def case_done_counts_visits_so_a_finished_pass_reads_as_finished():
    """`done` is items VISITED, not items that succeeded.

    The two vault sweeps used to disagree about this — describe counted visits,
    flags counted successes — while ONE frontend type and ONE set of formatters
    rendered both as "done/total". So a flags pass that finished with 13 failures
    parked at 487/500 forever and read as a sweep that had stalled. Now both go
    through `vault_sweep.run`, which owns the definition; `failed` carries the
    rest.

    Calls `_run_flags_all` directly rather than the POST, because every case in
    this file that goes through the route is 401 until the test harness grows a
    session (pre-existing, see the module note).
    """
    aid = _next_account()
    ids = list(range(690, 695))
    await _seed(aid, [(i, None) for i in ids])
    gate = _Gate(fail={692})
    orig, vault_ai_vision._flags_one = vault_ai_vision._flags_one, gate
    vault_ai_vision._flags_running.add(aid)
    try:
        await vault_ai_vision._run_flags_all(aid, ids)
    finally:
        vault_ai_vision._flags_one = orig
    prog = vault_ai_vision._flags_progress[aid]
    assert prog["total"] == 5, prog
    assert prog["done"] == 5, f"a pass that finished must read as finished: {prog}"
    assert prog["failed"] == 1, prog
    assert prog["error"] == "provider down", prog
    assert prog["cost_millicents"] == 4, f"four successes at 1mc each: {prog}"
    assert aid not in vault_ai_vision._flags_running, "the sweep never cleared its slot"


_harness.run(
    case_post_returns_before_the_sweep_finishes,
    case_second_click_does_not_start_a_second_sweep,
    case_status_reports_progress_and_db_coverage,
    case_todo_skips_current_and_keeps_stale,
    case_named_ids_stay_inline,
    case_a_failing_item_does_not_stop_the_sweep,
    case_done_counts_visits_so_a_finished_pass_reads_as_finished,
)
