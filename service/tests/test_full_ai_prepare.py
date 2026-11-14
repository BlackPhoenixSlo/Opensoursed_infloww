#!/usr/bin/env python3
"""Prepare content (docs/spec/phase-03b-full-ai-selling-test-chat.md › full_ai_prepare): one
owner-pressed chain of harvest → describe + Jev flags → AI folders, only what is missing,
nothing written to OF.

The chain runs the REAL job coroutines (`vault_ai_api._run_collect`,
`vault_ai_vision._run_describe_all` / `_run_flags_all`, the folder-plan apply) on the
_harness temp DB. Fakes only at their edges, the house way: the OF client at
`ax._make_client` (it records every call, `test_vault_manual_collect_order.py`), the
stills/storyboard fetch, the vision frames + vision model call and the Jev pass
(`test_vault_ai_describe.py`); `llm_client.httpx.AsyncClient` raises, so nothing reaches
a real LLM.

  case_facts_harvested_table            never walked / hot-only collector run → not harvested;
                                        capped walk / collector walk → harvested; counts; AI- folder
  case_steps_for_table                  the pure decision table
  case_first_click_runs_missing_steps   harvest → describe → folders in order, each `done`
  case_second_click_skips_everything    all `skipped`, the fake client records 0 calls
  case_click_while_running_same_run     a second press returns the running run_id
  case_walk_error_fails_harvest         a raise mid-walk → harvest `failed` from the run's error; stops
  case_vision_cap_fails_describe        cap → describe `failed` with the budget sentence; folders runs
  case_ai_folder_exists_skips_folders   folders `skipped`, the apply never called, no OF folder write
  case_held_guard_is_busy               a running Collect → harvest `busy`, chain stops
  case_cap_mid_sweep_fails_describe     the cap trips during the sweep → the same budget sentence
  case_no_key_refuses_flags             described, unflagged, no vision key → failed, no Jev call (flags_all's rule)
  case_all_items_failed_fails_describe  every vision call errors → describe `failed` "2 of 2 items failed", not done
  case_turn_path_never_imports_prepare  import isolation (no-send scan)

Run: ./venv/bin/python service/tests/test_full_ai_prepare.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"   # feature logic here; the gate is test_role_enforcement's

import ast  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import full_ai_api  # noqa: E402
import full_ai_prepare as prep  # noqa: E402
import llm_client  # noqa: E402
import vault_ai_api  # noqa: E402
import vault_ai_vision  # noqa: E402
import vault_frames  # noqa: E402
import vault_jev_pass  # noqa: E402
import vault_runs  # noqa: E402
import vault_scripts  # noqa: E402
import vault_stills  # noqa: E402
from _jev_fixtures import video_jev  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (Account, AccountAiConfig, GrokDailyCost, VaultCacheRun,  # noqa: E402
                       VaultFolder, VaultFolderItem, VaultItem)

SERVICE = Path(__file__).resolve().parents[1]

# ── Edges ────────────────────────────────────────────────────────────

vault_ai_api._PAGE_SLEEP_S = 0.0
_tmp = Path(tempfile.mkdtemp(prefix="fap_"))
vault_stills.THUMB_DIR, vault_stills.IMAGE_DIR, vault_stills.POSTER_DIR = (
    _tmp / "thumbs", _tmp / "images", _tmp / "posters")
vault_stills.fetch_bytes_sync = lambda client, url: b"\xff\xd8\xff\xe0" + b"0" * 64
vault_frames.warm_one_sync = lambda client, url, dur: None


class _NoLLM:
    """`llm_client.httpx.AsyncClient`: any real LLM HTTP call is a failure."""

    def __init__(self, *_a, **_k):
        raise AssertionError("a real LLM HTTP call was attempted")


llm_client.httpx.AsyncClient = _NoLLM


async def _key_ok(account_id, provider, purpose=None) -> bool:
    return True


llm_client.llm_key_available = _key_ok


class FakeOF:
    """A vault of clips 1..n (newer = higher id). Records EVERY call, so a folder
    create / push (`_mirror_ai_folders_to_of`, `_push_folder_to_of`) shows up too."""

    def __init__(self, aid: str, n: int, fail_at_offset: int | None = None):
        self.aid, self.n, self.fail_at_offset = aid, n, fail_at_offset
        self.calls: list[tuple] = []

    def vault_lists(self, *, view, limit, offset, query=None):
        self.calls.append(("lists", offset))
        return {"list": [], "hasMore": False}

    def vault_media(self, *, limit, offset, type="all", list_id=None, sort="desc",
                    field="recent", query=None, before_publish_date=None):
        self.calls.append(("media", offset, sort))
        if offset == self.fail_at_offset:
            raise RuntimeError("OF 500 mid-walk (fake)")
        ids = list(range(1, self.n + 1))
        if sort == "desc":
            ids.reverse()
        return {"list": [self._item(i) for i in ids[offset:offset + limit]],
                "hasMore": offset + limit < len(ids)}

    def _item(self, i: int) -> dict:
        return {"id": i, "type": "video", "duration": 10,
                "createdAt": (datetime(2026, 1, 1) + timedelta(hours=i)).isoformat() + "+00:00",
                "files": {"thumb": {"url": f"https://cdn.example/{self.aid}/t{i}.jpg"},
                          "preview": {"url": f"https://cdn.example/{self.aid}/p{i}.jpg"}},
                "videoSources": {"240": f"https://cdn.example/{self.aid}/v{i}.mp4"},
                "listStates": []}

    def __getattr__(self, name):   # anything else (a folder create, a push) is recorded
        def _call(*a, **k):
            self.calls.append((name,))
            return {}
        return _call


_CLIENTS: dict[str, FakeOF] = {}
ax._make_client = lambda aid: _CLIENTS[aid]

# The vision edge: frames + the vision model call (as test_vault_ai_describe does) and
# the Jev pass, which stamps a current clip `_jev` and its flags.
_described: list[int] = []
_jevved: list[int] = []


async def _one_frame(*_a, **_k):
    return vault_frames.Collected(["data:image/jpeg;base64,AAAA"], "ok")


class _VisionResult:
    def __init__(self, parsed: dict):
        self.content, self.parsed, self.cost_cents, self.call_id = json.dumps(parsed), parsed, 0, 1


async def _vision(**kw):
    _described.append(1)
    return _VisionResult({"description": "a clip", "clothing_state": "lingerie_on",
                          "explicitness": "suggestive", "tags": ["bed"], "acts": ["posing"]})


async def _jev_one(account_id, media_id, *, sweep=None):
    _jevved.append(int(media_id))
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
        f = json.loads(item.ai_fields_json or "{}")
        f["_jev"] = video_jev()
        item.ai_fields_json = json.dumps(f)
        await s.commit()
    await vault_jev_pass._sync_flags(account_id, media_id)
    return {"media_id": media_id, "ok": True, "status": "ok", "cost_millicents": 0}


vault_frames.collect = _one_frame
llm_client.chat = _vision
vault_jev_pass.one = _jev_one

_applied: list[str] = []
_real_apply = vault_scripts.apply_ai_folders


async def _apply_spy(account_id, plan):
    _applied.append(account_id)
    return await _real_apply(account_id, plan)


vault_scripts.apply_ai_folders = _apply_spy

_planned: list[dict] = []
_real_plan = vault_scripts.plan_ai_folders


async def _plan_spy(account_id, **kw):
    _planned.append(kw)
    return await _real_plan(account_id, **kw)


vault_scripts.plan_ai_folders = _plan_spy


# ── Helpers ──────────────────────────────────────────────────────────

_N = 0


async def _account(*, cap_cents: int = 1000) -> str:
    global _N
    _N += 1
    aid = f"fap_{_N}"
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(AccountAiConfig(account_id=aid, daily_cost_cap_cents=cap_cents))
        await s.commit()
    return aid


async def _seed_vault(aid: str, ids: list[int], *, described: bool = False) -> None:
    """A walked vault (one finished manual Collect) of clips."""
    async with get_session() as s:
        s.add(VaultCacheRun(account_id=aid, status="done", phase="done", pages_done=1,
                            finished_at=datetime.utcnow()))
        for i in ids:
            s.add(VaultItem(account_id=aid, media_id=i, kind="video", tags="[]",
                            created_at=datetime(2026, 6, 1) + timedelta(minutes=i)))
        await s.commit()
    if described:
        for i in ids:
            await _jev_one(aid, i)
        await vault_ai_vision._run_describe_all(aid, "undescribed")


async def _settle(aid: str) -> dict:
    for _ in range(1000):
        st = await full_ai_api.prepare_content_status(account_id=aid)
        if st["finished_at"]:
            return st
        await asyncio.sleep(0.01)
    raise AssertionError(f"chain never finished: {st}")


def _states(run: dict) -> list[tuple[str, str]]:
    return [(s["name"], s["state"]) for s in run["steps"]]


def _reset_spies() -> None:
    _described.clear()
    _jevved.clear()
    _applied.clear()


# ── Facts + steps_for ────────────────────────────────────────────────

async def case_facts_harvested_table():
    async def _harvested(*runs: dict) -> bool:
        aid = await _account()
        async with get_session() as s:
            for r in runs:
                s.add(VaultCacheRun(account_id=aid, finished_at=datetime.utcnow(), **r))
            await s.commit()
        return (await prep.read_facts(aid))["harvested"]

    assert await _harvested() is False, "never harvested"
    assert await _harvested({"status": "done", "phase": "auto:done", "pages_done": 0}) is False, (
        "a hot-set-only collector refresh is not a harvest")
    assert await _harvested({"status": "error", "phase": "media", "pages_done": 3}) is False, "a failed walk"
    assert await _harvested({"status": "done", "phase": "done", "pages_done": 2,
                             "error": vault_runs.capped_error(2)}) is True, "a capped walk counts"
    assert await _harvested({"status": "done", "phase": "auto:done", "pages_done": 4}) is True, (
        "a collector run that walked pages")

    aid = await _account()
    await _seed_vault(aid, [1, 2, 3])
    async with get_session() as s:
        s.add(VaultFolder(account_id=aid, name="AI-gone", deleted_at=datetime.utcnow()))
        await s.commit()
    f = await prep.read_facts(aid)
    assert f == {"harvested": True, "undescribed": 3, "unflagged": 3, "ai_folders": False,
                 "feet_pack": False}, f
    async with get_session() as s:
        s.add(VaultFolder(account_id=aid, name="AI-free lane"))
        await s.commit()
    assert (await prep.read_facts(aid))["ai_folders"] is True


async def case_steps_for_table():
    def row(harvested, undescribed, unflagged, ai_folders, feet_pack=False):
        return [(s["name"], s["state"]) for s in prep.steps_for(
            {"harvested": harvested, "undescribed": undescribed, "unflagged": unflagged,
             "ai_folders": ai_folders, "feet_pack": feet_pack})]

    P, S = "pending", "skipped"
    table = [
        # never harvested: describe can't be judged on an empty mirror yet
        ((False, 0, 0, False), [("harvest", P), ("describe", P), ("folders", P), ("feet", P)]),
        ((True, 0, 0, False), [("harvest", S), ("describe", S), ("folders", P), ("feet", P)]),
        ((True, 5, 0, False), [("harvest", S), ("describe", P), ("folders", P), ("feet", P)]),
        ((True, 0, 2, False), [("harvest", S), ("describe", P), ("folders", P), ("feet", P)]),
        ((True, 0, 0, True), [("harvest", S), ("describe", S), ("folders", S), ("feet", P)]),
        ((False, 0, 0, True), [("harvest", P), ("describe", P), ("folders", S), ("feet", P)]),
        # a Feet pack already there is the operator's: never filed twice
        ((True, 0, 0, True, True), [("harvest", S), ("describe", S), ("folders", S), ("feet", S)]),
        ((True, 0, 0, False, True), [("harvest", S), ("describe", S), ("folders", P), ("feet", S)]),
    ]
    for facts, want in table:
        assert row(*facts) == want, (facts, row(*facts))
    steps = prep.steps_for({"harvested": True, "undescribed": 5, "unflagged": 2, "ai_folders": False,
                            "feet_pack": False})
    assert steps[1]["counts"] == {"undescribed": 5, "unflagged": 2}, steps[1]


def _feet_jev(lane5: str = "free", score: float = 0.9, detail: str = "socks", **body) -> dict:
    """A photo `_jev` as the Feet pack reads it (test_vault_pack_picker `_jev_blob`)."""
    return {"v": "v8+nn.10", "status": "ok", "lane5": lane5,
            **{"breasts_bare": "n", "crotch_bare": "n", "penetration": "n", **body},
            "feet_subject": score,
            "P": {"feet_focus": score, "soles_visible": 0.0, "bare_toes_visible": 0.0},
            "tags": {"feet_detail": detail, "feet_any": "y", "feet_focus": "y" if score >= 0.4 else "n"}}


async def case_feet_step_files_preselected_only():
    """The feet step = the picker's "File N preselected": confident photos on their rung, the possible
    ones, clips and non-feet left alone; then the pack exists and the step is skipped."""
    aid = await _account()
    rows = [
        (1, "photo", _feet_jev()),                                  # .9, socks, free  -> tease
        (2, "photo", _feet_jev(detail="bare")),                     # .9, bare, free   -> nude
        (3, "photo", _feet_jev(lane5="$50", crotch_bare="y")),      # .9, paid body    -> nude-body
        (4, "photo", _feet_jev(score=0.4)),                         # possible: stays in the picker
        (5, "photo", _feet_jev(breasts_bare="unsure")),             # confident, no safe rung: not filed
        (6, "video", _feet_jev()),                                  # a pack is photos only
        (7, "photo", None),                                         # Jev never saw it
    ]
    async with get_session() as s:
        for mid, kind, jev in rows:
            s.add(VaultItem(account_id=aid, media_id=mid, kind=kind, tags="[]",
                            ai_fields_json=json.dumps({"_jev": jev}) if jev else None,
                            created_at=datetime(2026, 6, 1)))
        await s.commit()
    assert (await prep.read_facts(aid))["feet_pack"] is False
    step = await prep._feet(aid, {})
    assert (step["name"], step["state"], step["counts"]) == ("feet", "done", {"filed": 3, "to_check": 1}), step
    async with get_session() as s:
        got = {(f.name, i.media_id) for f, i in (await s.execute(
            select(VaultFolder, VaultFolderItem).join(VaultFolderItem, VaultFolderItem.folder_id == VaultFolder.id)
            .where(VaultFolder.account_id == aid))).all()}
        made = {f.name: f.created_by for f in (await s.execute(
            select(VaultFolder).where(VaultFolder.account_id == aid))).scalars()}
    assert got == {("feet-tease", 1), ("feet-nude", 2), ("feet-nude-body", 3)}, got
    # the operator's folders (the AI- reaper never touches them), all three rungs
    assert made == {"feet-tease": "operator", "feet-nude": "operator", "feet-nude-body": "operator"}, made
    facts = await prep.read_facts(aid)
    assert facts["feet_pack"] is True
    assert prep.steps_for(facts)[3] == {"name": "feet", "state": "skipped", "detail": "Feet pack exists",
                                        "counts": {}}


# ── The chain ────────────────────────────────────────────────────────

async def case_first_click_runs_missing_steps():
    aid = await _account()
    of = _CLIENTS[aid] = FakeOF(aid, 3)
    _reset_spies()
    started = await full_ai_api.prepare_content_start({"account_id": aid})
    assert started["run_id"] and len(started["steps"]) == 4, started
    run = await _settle(aid)
    assert _states(run) == [("harvest", "done"), ("describe", "done"), ("folders", "done"), ("feet", "done")], run
    # clips only: no feet photo, so nothing filed and no feet-* folder made
    assert run["steps"][3]["counts"] == {"filed": 0, "to_check": 0}, run["steps"][3]
    assert run["run_id"] == started["run_id"] and run["started_at"], run
    # harvest walked the fake vault: folder list, then the newest page (OF: no more)
    assert of.calls[:2] == [("lists", 0), ("media", 0, "desc")], of.calls
    assert run["steps"][0]["counts"]["seen"] == 3, run["steps"][0]
    # describe + Jev ran on all three, then folders applied once
    assert sorted(_jevved) == [1, 2, 3] and len(_described) == 3, (_jevved, _described)
    assert run["steps"][1]["counts"]["described"] == 3, run["steps"][1]
    assert _applied == [aid], _applied
    # the folder step asks for the vault's own script count (10), as the Build AI folders modal does; a
    # literal 2 here once left prepare content with 2 script folders
    assert _planned[-1] == {"keep": vault_scripts.DEFAULT_KEEP_SCRIPTS, "solo": False, "topics": [],
                            "split": True} and _planned[-1]["keep"] == 10, _planned
    assert (await prep.read_facts(aid)) == {"harvested": True, "undescribed": 0, "unflagged": 0,
                                            "ai_folders": True, "feet_pack": False}
    # never mirrored: no OF call beyond the walk's reads
    assert {c[0] for c in of.calls} <= {"media", "lists"}, of.calls


async def case_second_click_skips_everything():
    aid = await _account()
    _CLIENTS[aid] = FakeOF(aid, 2)
    await full_ai_api.prepare_content_start({"account_id": aid})
    first = await _settle(aid)
    assert [s for _, s in _states(first)] == ["done"] * 4, first
    of = _CLIENTS[aid] = FakeOF(aid, 2)
    _reset_spies()
    again = await full_ai_api.prepare_content_start({"account_id": aid})
    assert again["run_id"] != first["run_id"], "a finished run is not re-returned"
    run = await _settle(aid)
    assert _states(run) == [("harvest", "skipped"), ("describe", "skipped"), ("folders", "skipped"),
                            ("feet", "done")], run   # no feet-* folder yet, so it looks again: filed 0
    assert of.calls == [], of.calls
    assert (_jevved, _described, _applied) == ([], [], []), (_jevved, _described, _applied)


async def case_click_while_running_same_run():
    aid = await _account()
    _CLIENTS[aid] = FakeOF(aid, 2)
    a = await full_ai_api.prepare_content_start({"account_id": aid})
    b = await full_ai_api.prepare_content_start({"account_id": aid})
    assert a["run_id"] == b["run_id"], (a, b)
    await _settle(aid)


async def case_walk_error_fails_harvest():
    aid = await _account()
    _CLIENTS[aid] = FakeOF(aid, 250, fail_at_offset=100)
    _reset_spies()
    await full_ai_api.prepare_content_start({"account_id": aid})
    run = await _settle(aid)
    async with get_session() as s:
        cr = (await s.execute(select(VaultCacheRun).where(VaultCacheRun.account_id == aid))).scalar_one()
    assert (cr.status, cr.error) == ("error", "OF 500 mid-walk (fake)"), (cr.status, cr.error)
    assert run["steps"][0]["state"] == "failed" and run["steps"][0]["detail"] == cr.error, run["steps"][0]
    assert [s["state"] for s in run["steps"][1:]] == ["skipped"] * 3, run
    assert (_jevved, _described, _applied) == ([], [], []), "the chain did not stop"
    assert aid not in vault_runs.manual_running


async def case_vision_cap_fails_describe():
    aid = await _account(cap_cents=100)   # $1.00 = 10,000 mc
    await _seed_vault(aid, [1, 2])
    async with get_session() as s:
        s.add(GrokDailyCost(day=datetime.utcnow().strftime("%Y-%m-%d"), account_id=aid,
                            provider="deepinfra", cost_cents=10_000, call_count=1,
                            is_capped=False, updated_at=datetime.utcnow()))
        await s.commit()
    _CLIENTS[aid] = FakeOF(aid, 2)
    _reset_spies()
    await full_ai_api.prepare_content_start({"account_id": aid})
    run = await _settle(aid)
    budget = await vault_ai_vision._vision_budget(aid)
    assert budget["blocked_reason"].startswith("Today's AI budget for this account is spent"), budget
    assert run["steps"][1]["state"] == "failed", run["steps"][1]
    assert run["steps"][1]["detail"] == budget["blocked_reason"], run["steps"][1]
    assert _described == [], "a capped describe still called the vision model"
    assert run["steps"][2]["state"] == "done" and _applied == [aid], (run["steps"][2], _applied)
    assert aid not in vault_ai_vision._describe_running


async def case_ai_folder_exists_skips_folders():
    aid = await _account()
    await _seed_vault(aid, [1, 2], described=True)
    async with get_session() as s:
        s.add(VaultFolder(account_id=aid, name="AI-free", created_by="ai"))
        await s.commit()
    of = _CLIENTS[aid] = FakeOF(aid, 2)
    _reset_spies()
    await full_ai_api.prepare_content_start({"account_id": aid})
    run = await _settle(aid)
    assert _states(run) == [("harvest", "skipped"), ("describe", "skipped"), ("folders", "skipped"),
                            ("feet", "done")], run   # no feet-* folder yet, so it looks again: filed 0
    assert _applied == [] and of.calls == [], (_applied, of.calls)


async def case_held_guard_is_busy():
    aid = await _account()
    _CLIENTS[aid] = FakeOF(aid, 2)
    vault_runs.manual_running.add(aid)   # a Collect press already sweeping
    _reset_spies()
    try:
        await full_ai_api.prepare_content_start({"account_id": aid})
        run = await _settle(aid)
    finally:
        vault_runs.manual_running.discard(aid)
    assert run["steps"][0]["state"] == "busy", run["steps"][0]
    assert [s["state"] for s in run["steps"][1:]] == ["skipped"] * 3, run
    assert _CLIENTS[aid].calls == [] and _applied == [], "the chain did not stop"


async def case_cap_mid_sweep_fails_describe():
    """The budget is fine at the claim; the first vision call spends it, so every later one is
    refused (`LLMCapExceeded`, what llm_client raises): the sweep stops `capped`."""
    aid = await _account(cap_cents=100)
    idle = await full_ai_api.prepare_content_status(account_id=aid)
    assert idle == {"run_id": None, "steps": [], "started_at": None, "finished_at": None}, idle
    await _seed_vault(aid, [1, 2, 3, 4])
    _CLIENTS[aid] = FakeOF(aid, 4)
    _reset_spies()
    spent: list[int] = []

    async def spend_then_refuse(**kw):
        if spent:
            raise llm_client.LLMCapExceeded(aid, 100, 10_100)
        spent.append(1)
        async with get_session() as s:
            s.add(GrokDailyCost(day=datetime.utcnow().strftime("%Y-%m-%d"), account_id=aid,
                                provider="deepinfra", cost_cents=10_000, call_count=1,
                                is_capped=False, updated_at=datetime.utcnow()))
            await s.commit()
        return await _vision(**kw)

    llm_client.chat = spend_then_refuse
    try:
        await full_ai_api.prepare_content_start({"account_id": aid})
        run = await _settle(aid)
    finally:
        llm_client.chat = _vision
    budget = await vault_ai_vision._vision_budget(aid)
    assert budget["blocked_reason"].startswith("Today's AI budget for this account is spent"), budget
    step = run["steps"][1]
    assert step["state"] == "failed" and step["detail"] == budget["blocked_reason"], step
    assert spent == [1] and step["counts"]["total"] == 4, step
    assert run["steps"][2]["state"] == "done" and _applied == [aid], (run["steps"][2], _applied)


async def case_no_key_refuses_flags():
    aid = await _account()
    await _seed_vault(aid, [1, 2], described=True)
    async with get_session() as s:
        item = await s.get(VaultItem, (aid, 1))
        f = json.loads(item.ai_fields_json or "{}")
        f.pop("_jev", None)
        item.ai_fields_json = json.dumps(f)
        await s.commit()
    facts = await prep.read_facts(aid)
    assert facts["undescribed"] == 0 and facts["unflagged"] >= 1, facts
    _CLIENTS[aid] = FakeOF(aid, 2)
    _reset_spies()

    async def no_key(account_id, provider, purpose=None) -> bool:
        return False

    llm_client.llm_key_available = no_key
    try:
        budget = await vault_ai_vision._vision_budget(aid)
        await full_ai_api.prepare_content_start({"account_id": aid})
        run = await _settle(aid)
    finally:
        llm_client.llm_key_available = _key_ok
    assert budget["key_missing"] and budget["blocked_reason"], budget
    step = run["steps"][1]
    assert step["state"] == "failed" and step["detail"] == budget["blocked_reason"], step
    assert _jevved == [] and aid not in vault_ai_vision._flags_running, _jevved
    assert run["steps"][2]["state"] == "done", run["steps"][2]


async def case_all_items_failed_fails_describe():
    """Every vision call errors: the sweep runs through recording each item failed, so describe is
    `failed` with the count, never a green `done`; folders still runs (as on a cap)."""
    aid = await _account()
    await _seed_vault(aid, [1, 2])
    _CLIENTS[aid] = FakeOF(aid, 2)
    _reset_spies()

    async def refuse(**kw):
        raise llm_client.LLMError("provider 500 (fake)")

    llm_client.chat = refuse
    try:
        await full_ai_api.prepare_content_start({"account_id": aid})
        run = await _settle(aid)
    finally:
        llm_client.chat = _vision
    step = run["steps"][1]
    assert step["state"] == "failed", step
    assert step["counts"] == {"described": 0, "failed": 2, "total": 2}, step
    assert step["detail"].startswith("2 of 2 items failed"), step
    assert run["steps"][2]["state"] == "done", run["steps"][2]
    # The pure rule: any failed item fails the step; a clean run is None.
    assert await prep._sweep_failure(aid, {"done": 3, "failed": 1, "total": 3, "error": "x"}) == "1 of 3 items failed: x"
    assert await prep._sweep_failure(aid, {"done": 3, "failed": 0, "total": 3}) is None
    # A stop reads the relay's own sentences (what is wrong + the fix), ahead of the failed count.
    stop = {"message": "Stopped: 25 items in a row failed.", "fix": "First error: 401. Fix it, then press again."}
    assert await prep._sweep_failure(aid, {"done": 25, "failed": 25, "total": 99, "stop": stop}) == \
        "Stopped: 25 items in a row failed. First error: 401. Fix it, then press again."


# ── Import isolation (no-send scan) ──────────────────────────────────

# The Turn path, the Sell executor and the Writer/LLM modules that exist today.
TURN_PATH = ["automations.full_ai_sell", "automations.full_ai_chat", "automations.full_ai_decide",
             "llm_client", "llm_providers", "llm_models"]
# Named by the spec (03a/03b) but not in this checkout yet (test transport, Turn
# pipeline, Writers): checked once they land, skipped while their file is missing.
TURN_PATH_PENDING = ["automations.full_ai_test", "automations.full_ai_turn",
                     "automations.full_ai_writers", "automations.full_ai_config",
                     "automations._info_jev"]


def _file(mod: str) -> Path | None:
    p = SERVICE.joinpath(*mod.split(".")).with_suffix(".py")
    if p.is_file():
        return p
    p = SERVICE.joinpath(*mod.split("."), "__init__.py")
    return p if p.is_file() else None


def _imports(src: str, mod: str) -> set[str]:
    """Every module `src` (module `mod`) imports, anywhere in it (lazy imports included)."""
    pkg = mod.split(".")[:-1]
    out: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:   # `from ..x import y` in a.b.c → a.x (level 1 = own package)
                base = ".".join(filter(None, [*pkg[:len(pkg) - node.level + 1], base]))
            out.add(base)
            out |= {".".join(filter(None, [base, a.name])) for a in node.names}
    return out


def importers(mods: list[str], target: str = "full_ai_prepare") -> list[str]:
    """The `mods` whose own source imports `target` (the house scan reads each module's
    own source, `test_full_ai_shadow.case_no_send_a_import_scan`; a transitive closure
    is meaningless here, since `server` imports every module). Missing files skipped."""
    return [m for m in mods if (p := _file(m)) is not None
            and target in _imports(p.read_text(encoding="utf-8"), m)]


async def case_turn_path_never_imports_prepare():
    missing = [m for m in TURN_PATH if _file(m) is None]
    assert missing == [], f"a scanned module moved: {missing}"
    assert importers(TURN_PATH + TURN_PATH_PENDING) == [], importers(TURN_PATH + TURN_PATH_PENDING)
    # The scan sees what it must: the API module imports it; so would a mutant, lazily or relatively.
    assert importers(["full_ai_api"]) == ["full_ai_api"]
    assert _imports("def f():\n    import full_ai_prepare\n", "automations.x") >= {"full_ai_prepare"}
    assert "full_ai_prepare" in _imports("from .. import full_ai_prepare\n", "automations.full_ai_turn")
    assert "full_ai_prepare" in _imports("from full_ai_prepare import start\n", "x")
    assert "full_ai_prepare" not in _imports("from . import full_ai_prepare\n", "automations.x")


CASES = [
    case_facts_harvested_table,
    case_steps_for_table,
    case_feet_step_files_preselected_only,
    case_first_click_runs_missing_steps,
    case_second_click_skips_everything,
    case_click_while_running_same_run,
    case_walk_error_fails_harvest,
    case_vision_cap_fails_describe,
    case_ai_folder_exists_skips_folders,
    case_held_guard_is_busy,
    case_cap_mid_sweep_fails_describe,
    case_no_key_refuses_flags,
    case_all_items_failed_fails_describe,
    case_turn_path_never_imports_prepare,
]


async def _main() -> None:
    for c in CASES:
        await c()
        print(f"ok  {c.__name__}")


if __name__ == "__main__":
    asyncio.run(_main())
    print(f"\n{len(CASES)}/{len(CASES)} passed")
