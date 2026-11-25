#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import llm_client  # noqa: E402
import vault_ai_vision  # noqa: E402
import vault_jev_flags  # noqa: E402
import vault_jev_pass  # noqa: E402
from _jev_fixtures import video_jev  # noqa: E402


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
    return {"underwear_visible": False, "vulva_vis": "not_in_frame",
            "breasts_vis": "covered", "anus_vis": "not_in_frame",
            "over_breasts": "black top", "_flags_v": v}


def _synced() -> dict:
    j = video_jev()
    return vault_jev_flags.apply({"_jev": j}, j)


async def _seed(aid: str, rows: list[tuple[int, dict | None]],
                kind: str = "video") -> None:
    base = datetime(2026, 7, 1, 12, 0, 0)
    async with get_session() as s:
        s.add(Account(id=aid))
        for i, (mid, fields) in enumerate(rows):
            s.add(VaultItem(account_id=aid, media_id=mid, kind=kind, tags="[]",
                            created_at=base + timedelta(seconds=i),
                            ai_fields_json=json.dumps(fields) if fields else None,
                            explicitness_tier=(fields or {}).get("explicitness")))
        await s.commit()


class _Gate:

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
            fields.update(_synced())
            item.ai_fields_json = json.dumps(fields)
            item.explicitness_tier = fields["explicitness"]
            await s.commit()
        return {"media_id": media_id, "ok": True, "status": "ok", "lane5": "free",
                "cost_millicents": 1}


async def _drain(aid: str) -> None:
    for _ in range(200):
        if aid not in vault_ai_vision._flags_running:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("sweep never finished")



async def case_post_returns_before_the_sweep_finishes():
    aid = _next_account()
    await _seed(aid, [(i, None) for i in range(600, 610)])
    gate = _Gate(hold=True)
    orig, vault_jev_pass.safe = vault_jev_pass.safe, gate
    try:
        out = await asyncio.wait_for(
            vault_ai_vision.flags_all({"account_id": aid}), timeout=1.0)
        assert out["status"] == "running", out
        assert out["candidates"] == 10, out
        assert out["already"] is False, out
        await asyncio.sleep(0.05)
        assert len(gate.calls) < 10, (
            "the endpoint waited for the sweep it was supposed to hand off")
        gate.release.set()
        await _drain(aid)
        assert sorted(gate.calls) == list(range(600, 610)), gate.calls
    finally:
        gate.release.set()
        vault_jev_pass.safe = orig


async def case_second_click_does_not_start_a_second_sweep():
    aid = _next_account()
    await _seed(aid, [(i, None) for i in range(620, 626)])
    gate = _Gate(hold=True)
    orig, vault_jev_pass.safe = vault_jev_pass.safe, gate
    try:
        first = await vault_ai_vision.flags_all({"account_id": aid})
        second = await vault_ai_vision.flags_all({"account_id": aid})
        third = await vault_ai_vision.flags_all({"account_id": aid})
        assert first["already"] is False, first
        assert second["already"] is True and third["already"] is True, (second, third)
        gate.release.set()
        await _drain(aid)
        assert sorted(gate.calls) == list(range(620, 626)), gate.calls
    finally:
        gate.release.set()
        vault_jev_pass.safe = orig


async def case_status_reports_progress_and_db_coverage():
    aid = _next_account()
    await _seed(aid, [(i, None) for i in range(640, 644)], kind="photo")
    gate = _Gate(hold=True)
    orig, vault_jev_pass.safe = vault_jev_pass.safe, gate
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
        assert done["coverage"]["ready"] is True, done["coverage"]
        vault_ai_vision._flags_progress.pop(aid, None)
        after_restart = await vault_ai_vision.flags_all_status(account_id=aid)
        assert after_restart["progress"] is None
        assert after_restart["coverage"]["flagged"] == 4, after_restart["coverage"]
    finally:
        gate.release.set()
        vault_jev_pass.safe = orig


async def case_todo_skips_current_and_keeps_stale():
    aid = _next_account()
    await _seed(aid, [
        (660, _synced()),
        (661, _flagged()),
        (662, None),
        (663, {**_synced(), "vulva_vis": "bare"}),
    ])
    await _seed(aid2 := _next_account(), [(664, _synced())])
    async with get_session() as s:
        (await s.get(VaultItem, (aid2, 664))).explicitness_tier = "sfw"
        await s.commit()
    assert await vault_ai_vision._flags_todo(aid2) == [664]
    todo = await vault_ai_vision._flags_todo(aid)
    assert todo == [663, 662, 661], todo
    assert await vault_ai_vision._flags_todo(aid, force=True) == [663, 662, 661, 660]
    assert await vault_ai_vision._flags_todo(aid, limit=2) == [663, 662]
    assert await vault_ai_vision._flags_todo(aid, only={660}) == [660]


async def case_named_ids_stay_inline():
    aid = _next_account()
    await _seed(aid, [(670, None), (671, None)])
    gate = _Gate()
    orig, vault_jev_pass.safe = vault_jev_pass.safe, gate
    try:
        out = await vault_ai_vision.flags_all({"account_id": aid, "media_ids": [670]})
        assert out["flagged"] == 1 and out["failed"] == 0, out
        assert out["complete"] is True, out
        assert "status" not in out, "a named set must not be handed off"
        assert gate.calls == [670], gate.calls
        assert aid not in vault_ai_vision._flags_running
    finally:
        vault_jev_pass.safe = orig


async def case_flags_need_no_deepinfra_key():
    aid = _next_account()
    await _seed(aid, [(680, None)])
    gate = _Gate()
    orig, vault_jev_pass.safe = vault_jev_pass.safe, gate

    async def no_key(*_a, **_k) -> bool:
        return False
    llm_client.llm_key_available = no_key
    try:
        out = await vault_ai_vision.flags_all({"account_id": aid, "media_ids": [680]})
        assert out["flagged"] == 1 and gate.calls == [680], out
    finally:
        vault_jev_pass.safe = orig
        llm_client.llm_key_available = _key_present


async def case_a_failing_item_does_not_stop_the_sweep():
    aid = _next_account()
    await _seed(aid, [(i, None) for i in range(680, 685)])
    gate = _Gate(fail={682})
    orig, vault_jev_pass.safe = vault_jev_pass.safe, gate
    try:
        await vault_ai_vision.flags_all({"account_id": aid})
        await _drain(aid)
        assert sorted(gate.calls) == list(range(680, 685)), gate.calls
        prog = vault_ai_vision._flags_progress[aid]
        assert prog["done"] == 5 and prog["failed"] == 1, prog
        assert prog["error"] == "provider down", prog
        assert await vault_ai_vision._flags_todo(aid) == [682]
    finally:
        vault_jev_pass.safe = orig


async def case_done_counts_visits_so_a_finished_pass_reads_as_finished():
    aid = _next_account()
    ids = list(range(690, 695))
    await _seed(aid, [(i, None) for i in ids])
    gate = _Gate(fail={692})
    orig, vault_jev_pass.safe = vault_jev_pass.safe, gate
    vault_ai_vision._flags_running.add(aid)
    try:
        await vault_ai_vision._run_flags_all(aid, ids)
    finally:
        vault_jev_pass.safe = orig
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
    case_flags_need_no_deepinfra_key,
    case_a_failing_item_does_not_stop_the_sweep,
    case_done_counts_visits_so_a_finished_pass_reads_as_finished,
)
