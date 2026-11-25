#!/usr/bin/env python3
"""
Vault-AI describe — the `vault_ai_vision._describe_one` / `_jev_and_flag` state
machine and the "Describe all" sweep (`_run_describe_all`). Durable regression
suite (plain-assert, no pytest — repo convention). The recurring
`describe_media` automation that used to share this file was deleted (cleanup
Phase 6); only the operator-triggered paths remain.

Descriptions AUTO-APPLY (never a review item) and nothing here sends anything
(no fan lease, no OF send). The vision path and `llm_client.chat` are faked so
there's no network / no key spend.

Cases (selected):
  case_drm_state:
      `_describe_one` with no renderable frames ⇒ describe_status="blocked_drm".
  case_refusal_state:
      `_describe_one` whose vision model refuses on both the base + escalation
      model ⇒ describe_status="refused" (never a partial/blank description).
  case_escalation_failure_still_reports_the_paid_refusal:
      30b refuses (paid), 235b is capped / errors ⇒ the return still carries
      the 30b cost; capped still writes nothing.
  case_fetch_failure_is_not_blocked_drm:
      a frame-collection failure that was TRANSIENT ⇒ describe_status =
      "fetch_failed" and the next default sweep retries it at once. Recording it
      as "blocked_drm" (what every failure got before 2026-08-04) hands it the
      7-day un-renderable cool-off and the sweep that would fix it skips it.
  case_audio_is_never_a_describe_candidate:
      audio has no frame — it is not swept, and the plan's total does not count
      it. 591 audio rows were being swept per pass; the 45 with live signatures
      posted MP3 bytes to a vision endpoint.
  case_flags_failure_stays_in_todo:
      a photo's flags are its Jev pass's: a still it cannot fetch is that
      item's `fetch_failed` — no `_flags_v`, so the item stays in the retry set.
  case_a_dead_collect_stops_claiming_it_is_running:
      a collect finalises its own row, so a restart mid-sweep strands `running`
      forever. One prod row said `running / warming` for three days while the
      status endpoint reported the sweep as still working.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_ai_describe.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod).
"""
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from typing import Any  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import update  # noqa: E402

import llm_client  # noqa: E402
import llm_providers  # noqa: E402
import vault_ai_api  # noqa: E402 — collect status (_run_status)
import vault_runs  # noqa: E402 — manual_running
import vault_ai_vision  # noqa: E402 — _describe_one / _jev_and_flag under test
import vault_ai_vision_decide  # noqa: E402 — the frame ladder
import vault_frames  # noqa: E402 — the frame-collection seam both of them call
import vault_describe_jev  # noqa: E402
import vault_jev_pass  # noqa: E402 — the Jev pass (flags) describe runs first
from _jev_fixtures import video_jev  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (Account, AccountAiConfig, GrokDailyCost,  # noqa: E402
                       VaultCacheRun, VaultItem)


async def _fake_key_available(account_id, provider, purpose=None) -> bool:
    return True


llm_client.llm_key_available = _fake_key_available



class _FakeVisionResult:
    def __init__(self, content: str, parsed: Any = None, cost: int = 0, call_id: int = 1):
        self.content = content
        self.parsed = parsed
        self.cost_cents = cost
        self.call_id = call_id



_AID_N = 0


def _fresh_account() -> str:
    global _AID_N
    _AID_N += 1
    return f"acc_s5_{_AID_N}"


async def _seed_account(aid: str, *, cap_cents: int = 1000) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        if await s.get(AccountAiConfig, aid) is None:
            s.add(AccountAiConfig(account_id=aid, daily_cost_cap_cents=cap_cents))


async def _seed_items(aid: str, media_ids: list[int], *, kind: str = "video") -> None:
    base = datetime(2026, 6, 1, 10, 0, 0)
    async with get_session() as s:
        for i, mid in enumerate(media_ids):
            s.add(VaultItem(account_id=aid, media_id=int(mid), kind=kind,
                            created_at=base + timedelta(minutes=i), tags="[]",
                            ai_fields_json=json.dumps({"_jev": video_jev()}) if kind == "video" else None))


async def _get(aid: str, media_id: int) -> VaultItem:
    async with get_session() as s:
        return await s.get(VaultItem, (aid, media_id))



async def case_drm_state():
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [50], kind="video")

    async def _no_frames(*_a, **_k):
        return vault_frames.Collected([], "no_variant")

    orig = vault_frames.collect
    vault_frames.collect = _no_frames
    try:
        out = await vault_ai_vision._describe_one(aid, 50)
    finally:
        vault_frames.collect = orig
    assert out["ok"] is False and out["status"] == "blocked_drm", out
    assert (await _get(aid, 50)).describe_status == "blocked_drm", "state not persisted"


async def case_refusal_state():
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [60])

    async def _one_frame(*_a, **_k):
        return vault_frames.Collected(["data:image/jpeg;base64,AAAA"], "ok")

    async def _refuse(**_kwargs):
        return _FakeVisionResult(content="I can't help with that.", parsed=None)

    orig_imgs, orig_chat = vault_frames.collect, llm_client.chat
    vault_frames.collect = _one_frame
    llm_client.chat = _refuse
    try:
        out = await vault_ai_vision._describe_one(aid, 60)
    finally:
        vault_frames.collect = orig_imgs
        llm_client.chat = orig_chat
    assert out["ok"] is False and out["status"] == "refused", out
    it = await _get(aid, 60)
    assert it.describe_status == "refused", it.describe_status
    assert not (it.description or "").strip(), it.description


async def case_frame_ladder_by_duration() -> None:
    import storyboard
    assert vault_ai_vision_decide._FRAME_LADDER_MAX <= storyboard._STORYBOARD_FRAMES, \
        (vault_ai_vision_decide._FRAME_LADDER_MAX, storyboard._STORYBOARD_FRAMES)

    aid = _fresh_account()
    await _seed_account(aid)
    async with get_session() as s:
        s.add(VaultItem(account_id=aid, media_id=70, kind="video",
                        created_at=datetime(2026, 6, 1), tags="[]",
                        duration_seconds=900, ai_fields_json=json.dumps({"_jev": video_jev()})))
        await s.commit()

    seen: dict[str, Any] = {}

    async def _spy(_aid, _item, _raw, want=None):
        seen["want"] = want
        return vault_frames.Collected([], "no_variant")

    orig = vault_frames.collect
    vault_frames.collect = _spy
    try:
        await vault_ai_vision._describe_one(aid, 70)
    finally:
        vault_frames.collect = orig
    assert seen["want"] == 12, seen


async def case_prompt_version_selects_variant() -> None:
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [80, 81])

    sent: list[str] = []

    async def _one_frame(*_a, **_k):
        return vault_frames.Collected(["data:image/jpeg;base64,AAAA"], "ok")

    async def _capture(**kwargs):
        for m in kwargs.get("messages") or []:
            for part in m.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "text":
                    sent.append(part["text"])
        parsed = {"description": "a literal description", "tags": ["bed"],
                  "explicitness": "explicit", "acts": ["fingering"]}
        return _FakeVisionResult(content=json.dumps(parsed), parsed=parsed)

    orig_imgs, orig_chat = vault_frames.collect, llm_client.chat
    vault_frames.collect = _one_frame
    llm_client.chat = _capture
    try:
        await vault_ai_vision._describe_one(aid, 80, prompt_version="v1")
        await vault_ai_vision._describe_one(aid, 81, prompt_version="v2")
    finally:
        vault_frames.collect = orig_imgs
        llm_client.chat = orig_chat

    assert len(sent) == 2, sent
    want = vault_describe_jev.prompt_for("vid", video_jev(), vault_ai_vision._DESCRIBE_PROMPT_V2)
    assert sent[0] == sent[1] == want, "a clip was not sent the Jev-fed V2 prompt"
    assert "pulled_aside" in sent[1] and "one literal sentence" not in sent[0]

    v1_row = json.loads((await _get(aid, 80)).ai_fields_json)
    v2_row = json.loads((await _get(aid, 81)).ai_fields_json)
    assert v1_row["_prompt_version"] == "v1", v1_row
    assert v2_row["_prompt_version"] == "v2", v2_row


class _NoJevStop:

    def __enter__(self):
        self._o = vault_jev_pass.fatal

        async def _quiet(*_a, **_k):
            return None
        vault_jev_pass.fatal = _quiet
        return self

    def __exit__(self, *_e):
        vault_jev_pass.fatal = self._o


async def case_restage_selects_only_stale_rows() -> None:
    """The re-scan sweep picks up rows from the OTHER prompt version (and rows
    that predate the stamp, and photos whose describe was not Jev-fed), and
    leaves already-current rows alone — so an interrupted re-scan resumes
    rather than paying for the whole vault twice."""
    aid = _fresh_account()
    await _seed_account(aid)
    async with get_session() as s:
        for mid, blob in (
            (90, '{"_prompt_version": "v1"}'),   # stale → re-scan
            (91, '{"_prompt_version": "v2", "_describe": {"path": "prose"}}'),   # current, Jev-fed → skip
            (92, None),                          # predates the stamp → re-scan
            (93, '{"_prompt_version": "v2"}'),   # current version, not Jev-fed (pre-Jev photo) → re-scan
        ):
            s.add(VaultItem(account_id=aid, media_id=mid, kind="photo",
                            created_at=datetime(2026, 6, 1), tags="[]",
                            describe_status="described", ai_fields_json=blob))
        await s.commit()

    described: list[int] = []

    async def _spy(_aid, mid, **_k):
        described.append(int(mid))
        return {"media_id": mid, "ok": True, "status": "described"}

    orig = vault_ai_vision._describe_one
    vault_ai_vision._describe_one = _spy
    try:
        with _NoJevStop():
            await vault_ai_vision._run_describe_all(aid, "restage", prompt_version="v2")
    finally:
        vault_ai_vision._describe_one = orig
    assert sorted(described) == [90, 92, 93], described


async def case_describe_also_flags():
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [9001])

    flagged: list[int] = []
    described: list[int] = []
    o_desc, o_one = vault_ai_vision._describe_one, vault_jev_pass.one

    async def _desc(_aid, mid, **_k):
        described.append(int(mid))
        jr = _k.get("jev_res")
        if jr and not jr["ok"]:
            return {"media_id": mid, "ok": False, "status": jr["status"]}
        return {"media_id": mid, "ok": True, "status": "described", "cost_millicents": 70}

    async def _jev(_aid, mid, **_k):
        flagged.append(int(mid))
        return {"media_id": mid, "ok": True, "status": "ok", "lane5": "free", "cost_millicents": 3}

    vault_ai_vision._describe_one, vault_jev_pass.one = _desc, _jev
    try:
        await vault_ai_vision._run_describe_all(aid, "force", prompt_version="v2")
        assert described == [9001], described
        assert flagged == [9001], f"describe did not flag what it described: {flagged}"
        cost = vault_ai_vision._describe_progress[aid]["cost_millicents"]
        assert cost == 73, f"the sweep's cost dropped the Jev pass: {cost}"

        flagged.clear()
        described.clear()

        async def _boom(_aid, mid, **_k):
            flagged.append(int(mid))
            raise RuntimeError("provider down")

        vault_jev_pass.one = _boom
        await vault_ai_vision._run_describe_all(aid, "force", prompt_version="v2")
        assert flagged == [9001], "the Jev pass was skipped"
        assert described == [9001], "a raising Jev pass stopped the sweep"
        cost = vault_ai_vision._describe_progress[aid]["cost_millicents"]
        assert cost == 0, f"a failed Jev pass + skipped describe cost something: {cost}"
    finally:
        vault_ai_vision._describe_one, vault_jev_pass.one = o_desc, o_one


async def case_one_exploding_item_does_not_end_the_sweep():
    """REGRESSION — the describe call inside the sweep's `_one` was bare, and the
    `gather` under it took no `return_exceptions`. So ANY item that raised rather
    than returning a status — a media that vanished from the mirror mid-sweep, an
    OF read blowing up in the frame collector, SQLite refusing a connection —
    propagated out of the gather, hit the outer handler, and ended the whole pass.

    Measured on prod 2026-08-11 (account 800000334, 832 items outstanding): four
    bursts of full-speed work in one hour separated by 6/13/4/3-minute dead gaps,
    each burst opening with exactly `_DESCRIBE_CONCURRENCY` calls in the same
    second — the signature of a fresh sweep filling an empty semaphore, i.e. an
    operator pressing the button again. ~47% of that hour was spent stopped, and
    the relay was demonstrably alive throughout (other accounts' engines ran
    straight through the gaps).

    The item that raises stamps no row, so the only visible trace was a log line.
    Both halves are pinned here: every OTHER item is still attempted, and the
    failure is counted and reported rather than swallowed.
    """
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [1, 2, 3, 4, 5])

    seen: list[int] = []
    o_desc = vault_ai_vision._describe_one

    async def _desc(_aid, mid, **_k):
        seen.append(int(mid))
        if int(mid) == 3:
            raise RuntimeError("OF read blew up mid-collect")
        return {"media_id": mid, "ok": True, "status": "described"}

    vault_ai_vision._describe_one = _desc
    try:
        await vault_ai_vision._run_describe_all(aid, "force", prompt_version="v2")
    finally:
        vault_ai_vision._describe_one = o_desc

    assert sorted(seen) == [1, 2, 3, 4, 5], (
        f"one raising item ended the sweep — only {sorted(seen)} were attempted")
    prog = vault_ai_vision._describe_progress.get(aid) or {}
    assert not prog.get("aborted"), f"a survivable item aborted the sweep: {prog}"
    assert prog.get("done") == 5, prog
    assert prog.get("failed") == 1, f"the raise was not counted as a failure: {prog}"
    assert "RuntimeError" in (prog.get("error") or ""), (
        f"the reason it failed was swallowed: {prog}")


async def case_redescribe_keeps_flags_and_operator_fixes():
    aid = _fresh_account()
    await _seed_account(aid)
    async with get_session() as s:
        s.add(VaultItem(
            account_id=aid, media_id=70, kind="video",
            created_at=datetime(2026, 6, 1, 10, 0, 0), tags="[]",
            describe_status="described",
            ai_fields_json=json.dumps({
                "description": "old prose", "clothing_state": "fully_nude",
                "vulva_vis": "covered", "breasts_vis": "bare",
                "anus_vis": "not_in_frame", "over_vulva": "black lace thong",
                "underwear_visible": True, "_flags_v": 3,
                "_flags_model": "qwen3-vl-30b",
                "explicitness": "suggestive",
                "_jev": video_jev(),
            }),
            operator_overrides_json=json.dumps({"explicitness": "suggestive",
                                                "description": "operator prose"}),
            locked_fields_json=json.dumps(["explicitness", "description"]),
        ))
        await s.commit()

    async def _one_frame(*_a, **_k):
        return vault_frames.Collected(["data:image/jpeg;base64,AAAA"], "ok")

    fresh = {"description": "new prose", "clothing_state": "lingerie_on",
             "explicitness": "explicit", "tags": ["bed"], "acts": ["posing"]}

    async def _vision(**_kwargs):
        return _FakeVisionResult(content=json.dumps(fresh), parsed=fresh)

    orig_imgs, orig_chat = vault_frames.collect, llm_client.chat
    vault_frames.collect = _one_frame
    llm_client.chat = _vision
    try:
        out = await vault_ai_vision._describe_one(aid, 70)
    finally:
        vault_frames.collect = orig_imgs
        llm_client.chat = orig_chat
    assert out["ok"], out

    got = json.loads((await _get(aid, 70)).ai_fields_json)
    assert got["description"] == "new prose", (
        "an edit_item lock must NOT stamp itself into the blob — that would "
        "erase the evidence a re-run ever ran (case_rerun_respects_lock)")
    import vault_jev_flags
    assert got["clothing_state"] == vault_jev_flags.reading(video_jev())["clothing_state"], got
    for key, want in (("vulva_vis", "covered"), ("breasts_vis", "bare"),
                      ("anus_vis", "not_in_frame"),
                      ("over_vulva", "black lace thong"), ("_flags_v", 3)):
        assert got.get(key) == want, f"re-describe dropped the flags: {key}={got.get(key)!r}"
    assert got["explicitness"] == "suggestive", (
        "a locked dispute fix was reverted by the model")


async def case_describing_one_item_flags_it_too():
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [80])

    flagged: list[int] = []
    o_desc, o_one = vault_ai_vision._describe_one, vault_jev_pass.one

    async def _desc(_aid, mid, **_k):
        return {"media_id": mid, "ok": True, "status": "described", "cost_millicents": 70}

    async def _jev(_aid, mid, **_k):
        flagged.append(int(mid))
        return {"media_id": mid, "ok": True, "status": "ok", "lane5": "free", "cost_millicents": 3}

    vault_ai_vision._describe_one, vault_jev_pass.one = _desc, _jev
    try:
        out = await vault_ai_vision.describe_one({"account_id": aid, "media_id": 80})
        assert out["ok"], out
        assert flagged == [80], f"the single-item describe did not flag it: {flagged}"
        assert out["cost_millicents"] == 73, f"the Jev pass's cost went unreported: {out}"
        assert out["jev_status"] == "ok" and out["jev_cost_millicents"] == 3, out
    finally:
        vault_ai_vision._describe_one, vault_jev_pass.one = o_desc, o_one


async def case_describe_all_attempts_every_undescribed_item() -> None:
    aid = _fresh_account()
    await _seed_account(aid)
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(VaultItem(account_id=aid, media_id=10, kind="photo",
                        created_at=datetime(2026, 6, 1), tags="[]"))
        s.add(VaultItem(account_id=aid, media_id=11, kind="video",
                        created_at=datetime(2026, 6, 1), tags="[]",
                        describe_status="blocked_drm",
                        describe_generated_at=now - timedelta(hours=2)))
        s.add(VaultItem(account_id=aid, media_id=12, kind="photo",
                        created_at=datetime(2026, 6, 1), tags="[]",
                        describe_status="described",
                        describe_generated_at=now - timedelta(hours=2)))
        await s.commit()

    seen: list[int] = []

    async def _spy(_aid, mid, **_k):
        seen.append(int(mid))
        return {"media_id": mid, "ok": True, "status": "described"}

    orig = vault_ai_vision._describe_one
    vault_ai_vision._describe_one = _spy
    try:
        with _NoJevStop():
            await vault_ai_vision._run_describe_all(aid, "undescribed", prompt_version="v2")
        assert sorted(seen) == [10, 11], (
            f"the button skipped work it counted: {seen}")
        assert 12 not in seen, "a finished item was re-billed"
    finally:
        vault_ai_vision._describe_one = orig


async def case_fetch_failure_is_not_blocked_drm() -> None:
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [60])

    async def _cold(*_a, **_k):
        return vault_frames.Collected([], "fetch_failed")

    orig = vault_frames.collect
    vault_frames.collect = _cold
    try:
        out = await vault_ai_vision._describe_one(aid, 60)
    finally:
        vault_frames.collect = orig
    assert out["status"] == "fetch_failed", out
    row = await _get(aid, 60)
    assert row.describe_status == "fetch_failed", row.describe_status
    assert out.get("detail"), f"a failure with no cause is not a report: {out}"

    async def _blew_up(*_a, **_k):
        return vault_frames.Collected([], "fetch_failed", "TypeError: NoneType")

    vault_frames.collect = _blew_up
    try:
        out = await vault_ai_vision._describe_one(aid, 60)
    finally:
        vault_frames.collect = orig
    assert "TypeError" in out["detail"], out

    seen: list[int] = []

    async def _spy(_aid, mid, **_k):
        seen.append(int(mid))
        return {"media_id": mid, "ok": True, "status": "described"}

    orig_one = vault_ai_vision._describe_one
    vault_ai_vision._describe_one = _spy
    try:
        await vault_ai_vision._run_describe_all(aid, "undescribed", prompt_version="v2")
    finally:
        vault_ai_vision._describe_one = orig_one
    assert seen == [60], f"a transient failure must be retried at once, got {seen}"


async def case_audio_is_never_a_describe_candidate() -> None:
    aid = _fresh_account()
    await _seed_account(aid)
    async with get_session() as s:
        s.add(VaultItem(account_id=aid, media_id=80, kind="photo",
                        created_at=datetime(2026, 6, 1), tags="[]"))
        s.add(VaultItem(account_id=aid, media_id=81, kind="audio",
                        created_at=datetime(2026, 6, 1), tags="[]"))
        await s.commit()

    seen: list[int] = []

    async def _spy(_aid, mid, **_k):
        seen.append(int(mid))
        return {"media_id": mid, "ok": True, "status": "described"}

    orig = vault_ai_vision._describe_one
    vault_ai_vision._describe_one = _spy
    try:
        with _NoJevStop():
            await vault_ai_vision._run_describe_all(aid, "force", prompt_version="v2")
    finally:
        vault_ai_vision._describe_one = orig
    assert seen == [80], f"audio must not be swept, got {seen}"

    plan = await vault_ai_vision.describe_all_plan(account_id=aid, prompt_version="v2")
    assert plan["total"] == 1, f"plan counted the audio row: {plan}"


async def case_flags_failure_stays_in_todo() -> None:
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [90], kind="photo")

    async def _cold(*_a, **_k):
        return vault_frames.Collected([], "fetch_failed")

    async def _ready(account_id=None):
        return None

    o_c, o_p = vault_frames.collect, vault_jev_pass.vault_jev.preflight
    vault_frames.collect, vault_jev_pass.vault_jev.preflight = _cold, _ready
    try:
        out = await vault_ai_vision._jev_and_flag(aid, 90)
    finally:
        vault_frames.collect, vault_jev_pass.vault_jev.preflight = o_c, o_p
    assert out["ok"] is False and out["status"] == "fetch_failed", out

    fields = json.loads((await _get(aid, 90)).ai_fields_json or "{}")
    assert "_flags_v" not in fields, "a failure must not mark flags current"
    assert 90 in await vault_ai_vision._flags_todo(aid), "failed item dropped out of todo"


async def case_a_dead_collect_stops_claiming_it_is_running() -> None:
    aid = _fresh_account()
    row = VaultCacheRun(account_id=aid, status="running", phase="warming")

    vault_runs.manual_running.discard(aid)
    assert vault_ai_api._run_status(row, aid) == "interrupted", "the lie survived"

    vault_runs.manual_running.add(aid)
    try:
        assert vault_ai_api._run_status(row, aid) == "running", (
            "a sweep that IS running must still say so")
    finally:
        vault_runs.manual_running.discard(aid)

    for done in ("done", "error"):
        row.status = done
        assert vault_ai_api._run_status(row, aid) == done, done


async def _spend_today(aid: str, millicents: int, *, provider: str = "describe",
                       flagged: bool = False) -> None:
    async with get_session() as s:
        s.add(GrokDailyCost(
            day=datetime.utcnow().strftime("%Y-%m-%d"), account_id=aid,
            provider=provider, cost_cents=int(millicents), call_count=1,
            is_capped=flagged, updated_at=datetime.utcnow()))
        await s.commit()


async def case_describe_all_refuses_to_start_over_the_cap() -> None:
    aid = _fresh_account()
    await _seed_account(aid, cap_cents=100)
    await _seed_items(aid, [90, 91])
    await _spend_today(aid, 10_000)

    started: list[str] = []
    orig = vault_ai_vision._run_describe_all

    async def _spy(account_id, *a, **k):
        started.append(account_id)

    vault_ai_vision._run_describe_all = _spy
    try:
        try:
            await vault_ai_vision.describe_all({"account_id": aid})
            raise AssertionError("the sweep started with no budget to run on")
        except HTTPException as e:
            assert e.status_code == 429, e.status_code
            assert e.detail["error"] == "daily_cap_reached", e.detail
            assert e.detail["spent_millicents"] == 10_000, e.detail
            assert e.detail["cap_millicents"] == 10_000, e.detail
            assert "$1.00" in e.detail["blocked_reason"], e.detail["blocked_reason"]
        assert started == [], f"a refused start still ran a sweep: {started}"
        assert aid not in vault_ai_vision._describe_running, (
            "the refusal left the account marked as running — nothing would "
            "ever clear it, and every later start would 409")
    finally:
        vault_ai_vision._run_describe_all = orig


async def case_concurrent_describe_all_presses_start_one_sweep() -> None:
    import asyncio

    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [97])

    started: list[str] = []
    o_run, o_budget = vault_ai_vision._run_describe_all, vault_ai_vision._vision_budget

    async def _spy(account_id, *a, **k):
        started.append(account_id)

    async def _slow_budget(account_id, model="qwen3-vl-30b"):
        await asyncio.sleep(0.05)
        return await o_budget(account_id, model)

    vault_ai_vision._run_describe_all = _spy
    vault_ai_vision._vision_budget = _slow_budget
    try:
        got = await asyncio.gather(*(vault_ai_vision.describe_all({"account_id": aid}) for _ in range(2)),
                                   return_exceptions=True)
        await asyncio.sleep(0)
        ok = [g for g in got if isinstance(g, dict)]
        busy = [g for g in got if isinstance(g, HTTPException) and g.status_code == 409
                and g.detail == {"error": "describe_already_running"}]
        assert len(ok) == 1 and len(busy) == 1, got
        assert started == [aid], f"concurrent presses started {len(started)} sweeps"
    finally:
        vault_ai_vision._run_describe_all, vault_ai_vision._vision_budget = o_run, o_budget
        vault_ai_vision._describe_running.discard(aid)


async def case_one_item_describe_over_the_cap_fetches_nothing() -> None:
    aid = _fresh_account()
    await _seed_account(aid, cap_cents=100)
    await _seed_items(aid, [92])
    await _spend_today(aid, 10_000)

    collected: list[int] = []
    orig = vault_frames.collect

    async def _spy(_aid, item, _raw, want=1):
        collected.append(int(item.media_id))
        return vault_frames.Collected(["data:image/jpeg;base64,AAAA"], "ok")

    vault_frames.collect = _spy
    try:
        out = await vault_ai_vision.describe_one({"account_id": aid, "media_id": 92})
        assert out["status"] == "capped" and out["ok"] is False, out
        assert collected == [], f"it fetched frames anyway: {collected}"

        assert "$1.00" in out["detail"], out["detail"]
        key_env = llm_providers.PROVIDERS["deepinfra"].api_key_env
        prev_key = os.environ.get(key_env)
        os.environ[key_env] = "test-deepinfra-key"
        try:
            live = await vault_ai_vision._describe_one(aid, 92)
        finally:
            if prev_key is None:
                os.environ.pop(key_env, None)
            else:
                os.environ[key_env] = prev_key
        assert collected == [92], "the in-flight path must be the one that fetched"
        assert live["status"] == "capped" and live["ok"] is False, live
        assert live["detail"] == out["detail"], (live["detail"], out["detail"])
    finally:
        vault_frames.collect = orig


async def case_cap_state_reads_the_money_not_the_sticky_flag() -> None:
    aid = _fresh_account()
    await _seed_account(aid, cap_cents=100)
    await _seed_items(aid, [93])
    await _spend_today(aid, 10_000, flagged=True)

    plan = await vault_ai_vision.describe_all_plan(account_id=aid)
    assert plan["cap"]["capped"] is True and plan["cap"]["flagged"] is True, plan["cap"]
    assert plan["cap"]["remaining_millicents"] == 0, plan["cap"]

    async with get_session() as s:
        await s.execute(
            update(AccountAiConfig).where(AccountAiConfig.account_id == aid)
            .values(daily_cost_cap_cents=500))
        await s.commit()
    state = await llm_client.cap_state(aid, "describe")
    assert state["capped"] is False, state
    assert state["flagged"] is True, "the day's cap-hit is still worth reporting"
    assert state["remaining_millicents"] == 40_000, state

    other = await llm_client.cap_state(aid, "deepseek")
    assert other["spent_millicents"] == 0, other


async def case_capped_means_no_call_on_the_model_fits() -> None:
    model = "qwen3-vl-30b"
    floor = llm_client._cost_millicents(model, 0, llm_client._ASSUMED_OUTPUT_TOKENS)
    assert 0 < floor < 10_000, floor

    async def _state(left: int, flagged: bool = False) -> dict:
        aid = _fresh_account()
        await _seed_account(aid, cap_cents=100)
        await _spend_today(aid, 10_000 - left, flagged=flagged)
        return await llm_client.cap_state(aid, "describe", model)

    assert (await _state(floor - 1))["capped"] is True
    assert (await _state(floor + 1))["capped"] is False
    assert (await _state(2 * floor - 1, flagged=True))["capped"] is True
    assert (await _state(min(5 * floor, 10_000), flagged=True))["capped"] is False
    no_model = await llm_client.cap_state(_fresh_account(), "deepinfra")
    assert no_model["capped"] is False, no_model

    aid = _fresh_account()
    await _seed_account(aid, cap_cents=100)
    await _seed_items(aid, [94])
    await _spend_today(aid, 10_000 - (floor - 1))
    collected: list[int] = []
    orig = vault_frames.collect

    async def _spy(_aid, item, _raw, want=1):
        collected.append(int(item.media_id))
        return vault_frames.Collected(["data:image/jpeg;base64,AAAA"], "ok")

    vault_frames.collect = _spy
    try:
        out = await vault_ai_vision.describe_one({"account_id": aid, "media_id": 94})
    finally:
        vault_frames.collect = orig
    assert out["status"] == "capped" and collected == [], (out, collected)


async def case_escalation_cost_is_the_sum_of_both_attempts() -> None:
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [95])
    models: list[str] = []

    async def _one_frame(*_a, **_k):
        return vault_frames.Collected(["data:image/jpeg;base64,AAAA"], "ok")

    async def _refuse_then_answer(**kw):
        models.append(kw["model"])
        if len(models) == 1:
            return _FakeVisionResult(content="I can't help with that.", cost=7, call_id=1)
        return _FakeVisionResult(
            content=json.dumps({"description": "a selfie", "tags": ["selfie"]}),
            cost=11, call_id=2)

    orig_imgs, orig_chat = vault_frames.collect, llm_client.chat
    vault_frames.collect, llm_client.chat = _one_frame, _refuse_then_answer
    try:
        out = await vault_ai_vision._describe_one(aid, 95)
    finally:
        vault_frames.collect, llm_client.chat = orig_imgs, orig_chat
    assert models == ["qwen3-vl-30b", "qwen3-vl-235b"], models
    assert out["ok"] is True and out["describe_model"] == "qwen3-vl-235b", out
    assert out["cost_millicents"] == 7 + 11, out["cost_millicents"]
    assert (await _get(aid, 95)).describe_call_id == 2


async def case_escalation_failure_still_reports_the_paid_refusal() -> None:
    async def _one_frame(*_a, **_k):
        return vault_frames.Collected(["data:image/jpeg;base64,AAAA"], "ok")

    for status, boom in (("capped", llm_client.LLMCapExceeded("x", 100, 200)),
                         ("error", llm_client.LLMError("provider 502"))):
        aid = _fresh_account()
        await _seed_account(aid)
        await _seed_items(aid, [96])
        models: list[str] = []

        async def _refuse_then_raise(**kw):
            models.append(kw["model"])
            if len(models) == 1:
                return _FakeVisionResult(content="I can't help with that.", cost=7)
            raise boom

        orig_imgs, orig_chat = vault_frames.collect, llm_client.chat
        vault_frames.collect, llm_client.chat = _one_frame, _refuse_then_raise
        try:
            out = await vault_ai_vision._describe_one(aid, 96)
        finally:
            vault_frames.collect, llm_client.chat = orig_imgs, orig_chat
        assert models == ["qwen3-vl-30b", "qwen3-vl-235b"], (status, models)
        assert out["status"] == status and out["ok"] is False, out
        assert out.get("cost_millicents") == 7, (status, out)
        row = await _get(aid, 96)
        if status == "capped":
            assert row.describe_status is None and row.describe_model is None, (
                "capped wrote the row — the retry sweep would skip it")
        else:
            assert row.describe_status == "failed", row.describe_status


_harness.run(
    case_describe_all_refuses_to_start_over_the_cap,
    case_concurrent_describe_all_presses_start_one_sweep,
    case_capped_means_no_call_on_the_model_fits,
    case_one_item_describe_over_the_cap_fetches_nothing,
    case_cap_state_reads_the_money_not_the_sticky_flag,
    case_redescribe_keeps_flags_and_operator_fixes,
    case_describing_one_item_flags_it_too,
    case_drm_state,
    case_refusal_state,
    case_escalation_cost_is_the_sum_of_both_attempts,
    case_escalation_failure_still_reports_the_paid_refusal,
    case_frame_ladder_by_duration,
    case_prompt_version_selects_variant,
    case_restage_selects_only_stale_rows,
    case_describe_also_flags,
    case_one_exploding_item_does_not_end_the_sweep,
    case_describe_all_attempts_every_undescribed_item,
    case_fetch_failure_is_not_blocked_drm,
    case_audio_is_never_a_describe_candidate,
    case_flags_failure_stays_in_todo,
    case_a_dead_collect_stops_claiming_it_is_running,
)
