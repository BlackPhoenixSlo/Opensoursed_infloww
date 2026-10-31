#!/usr/bin/env python3
"""
Vault-AI describe — the `vault_ai_vision._describe_one` / `_flags_one` state
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
  case_flags_failure_is_written_down:
      the TAGGING pass shares the frame path, so it broke the same way and said
      nothing at all. It now records `_flags_status` on the row — WITHOUT
      `_flags_v`, so the item stays in the retry set.
  case_a_dead_collect_stops_claiming_it_is_running:
      a collect finalises its own row, so a restart mid-sweep strands `running`
      forever. One prod row said `running / warming` for three days while the
      status endpoint reported the sweep as still working.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_ai_describe.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod).
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

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from typing import Any  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import update  # noqa: E402

import llm_client  # noqa: E402
import llm_providers  # noqa: E402
import vault_ai_api  # noqa: E402 — collect status (_run_status / _running)
import vault_ai_vision  # noqa: E402 — _describe_one / _flags_one under test
import vault_ai_vision_decide  # noqa: E402 — the frame ladder
import vault_frames  # noqa: E402 — the frame-collection seam both of them call
from db.engine import get_session  # noqa: E402
from db.models import (Account, AccountAiConfig, GrokDailyCost,  # noqa: E402
                       VaultCacheRun, VaultItem)


# The describe path preflights `llm_key_available` per provider it would bill.
# These cases fake the model calls, so a key is always "present".
async def _fake_key_available(account_id, provider, purpose=None) -> bool:
    return True


llm_client.llm_key_available = _fake_key_available


# ── Fakes ────────────────────────────────────────────────────────────

class _FakeVisionResult:
    """Minimal `llm_client.LLMResult` shape the copy call + _describe_one read."""
    def __init__(self, content: str, parsed: Any = None, cost: int = 0, call_id: int = 1):
        self.content = content
        self.parsed = parsed
        self.cost_cents = cost      # MILLICENTS in this codebase
        self.call_id = call_id


# ── Seeders ──────────────────────────────────────────────────────────

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


async def _seed_items(aid: str, media_ids: list[int], *, kind: str = "photo") -> None:
    base = datetime(2026, 6, 1, 10, 0, 0)
    async with get_session() as s:
        for i, mid in enumerate(media_ids):
            s.add(VaultItem(account_id=aid, media_id=int(mid), kind=kind,
                            created_at=base + timedelta(minutes=i), tags="[]"))


async def _get(aid: str, media_id: int) -> VaultItem:
    async with get_session() as s:
        return await s.get(VaultItem, (aid, media_id))


# ── Cases ────────────────────────────────────────────────────────────

async def case_drm_state():
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [50], kind="video")

    async def _no_frames(*_a, **_k):
        # OF answered and offered no renderable variant → genuinely DRM-blocked
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
    # A refusal must NEVER leave a partial/blank description behind.
    assert not (it.description or "").strip(), it.description


async def case_frame_ladder_by_duration() -> None:
    """Frames scale with clip length instead of a flat constant.

    Measured 2026-07-21 over 6 long clips × 4 counts × 3 repeats, scored as
    coverage of the pooled union of all findings (3f 38% / 6f 49% / 9f 47% /
    12f 55%, mean beats 1.9 → 3.7). 3→6 is a real gain, 6→9 is inside
    run-to-run noise, 9→12 buys the beats a long clip needs. 12 is the ceiling
    (`storyboard._STORYBOARD_FRAMES`).
    """
    # The ladder itself is table-tested in test_vault_ai_vision_decide.
    # Never ask for more than the storyboard actually holds.
    import storyboard
    assert vault_ai_vision_decide._FRAME_LADDER_MAX <= storyboard._STORYBOARD_FRAMES, \
        (vault_ai_vision_decide._FRAME_LADDER_MAX, storyboard._STORYBOARD_FRAMES)

    # …and the ladder is what _describe_one actually asks _collect_images for.
    aid = _fresh_account()
    await _seed_account(aid)
    async with get_session() as s:
        s.add(VaultItem(account_id=aid, media_id=70, kind="video",
                        created_at=datetime(2026, 6, 1), tags="[]",
                        duration_seconds=900))
        await s.commit()

    seen: dict[str, Any] = {}

    async def _spy(_aid, _item, _raw, want=None):
        seen["want"] = want
        return vault_frames.Collected([], "no_variant")  # short-circuit; we only want `want`

    orig = vault_frames.collect
    vault_frames.collect = _spy
    try:
        await vault_ai_vision._describe_one(aid, 70)
    finally:
        vault_frames.collect = orig
    assert seen["want"] == 12, seen        # 15-minute clip → the ceiling


async def case_prompt_version_selects_variant() -> None:
    """A/B is a real switch: v1 sends the one-sentence prompt, v2 the structured
    one, and the row records WHICH produced it so a re-scan can find it."""
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
    assert sent[0] == vault_ai_vision._DESCRIBE_PROMPT, "v1 did not send the V1 prompt"
    assert sent[1] == vault_ai_vision._DESCRIBE_PROMPT_V2, "v2 did not send the V2 prompt"
    assert "one literal sentence" in sent[0]
    assert "pulled_aside" in sent[1]

    # The stamp is what the re-scan sweep selects on.
    v1_row = json.loads((await _get(aid, 80)).ai_fields_json)
    v2_row = json.loads((await _get(aid, 81)).ai_fields_json)
    assert v1_row["_prompt_version"] == "v1", v1_row
    assert v2_row["_prompt_version"] == "v2", v2_row


async def case_restage_selects_only_stale_rows() -> None:
    """The re-scan sweep picks up rows from the OTHER prompt version (and rows
    that predate the stamp), and leaves already-current rows alone — so an
    interrupted re-scan resumes rather than paying for the whole vault twice."""
    aid = _fresh_account()
    await _seed_account(aid)
    async with get_session() as s:
        for mid, blob in (
            (90, '{"_prompt_version": "v1"}'),   # stale → re-scan
            (91, '{"_prompt_version": "v2"}'),   # current → skip
            (92, None),                          # predates the stamp → re-scan
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
        await vault_ai_vision._run_describe_all(aid, "restage", prompt_version="v2")
    finally:
        vault_ai_vision._describe_one = orig
    assert sorted(described) == [90, 92], described


async def case_describe_also_flags():
    """REGRESSION — "described" used to mean prose plus `clothing_state` and
    NOTHING about what is actually on show, because the flags pass was a second
    button. A freshly-described vault therefore had no flags at all, and every
    lane gated on them (`AI-safe explicit`, both price tiers) was silently
    empty until somebody remembered. The two passes now run in one breath.

    Also pins the failure DIRECTION: the flags call is cheap (~3s, ~$0.00002)
    and the describe call is not (~16s, ~$0.0086), so a flags failure must
    never lose a description that has already been written and paid for.
    """
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [9001])

    flagged: list[int] = []
    described: list[int] = []
    o_desc, o_flags = vault_ai_vision._describe_one, vault_ai_vision._flags_one

    async def _desc(_aid, mid, **_k):
        described.append(int(mid))
        return {"media_id": mid, "ok": True, "status": "described"}

    async def _flags(_aid, mid, **_k):
        flagged.append(int(mid))
        return {"media_id": mid, "ok": True, "status": "flagged"}

    vault_ai_vision._describe_one = _desc
    vault_ai_vision._flags_one = _flags
    try:
        await vault_ai_vision._run_describe_all(aid, "force", prompt_version="v2")
        assert described == [9001], described
        assert flagged == [9001], f"describe did not flag what it described: {flagged}"

        # A flags failure must not take the description down with it.
        flagged.clear()
        described.clear()

        async def _boom(_aid, mid, **_k):
            flagged.append(int(mid))
            raise RuntimeError("provider down")

        vault_ai_vision._flags_one = _boom
        await vault_ai_vision._run_describe_all(aid, "force", prompt_version="v2")
        assert flagged == [9001], "the flags call was skipped"
        assert described == [9001], (
            "a cheap flags failure stopped the expensive describe sweep")
    finally:
        vault_ai_vision._describe_one, vault_ai_vision._flags_one = o_desc, o_flags


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
    o_desc, o_flags = vault_ai_vision._describe_one, vault_ai_vision._flags_one

    async def _desc(_aid, mid, **_k):
        seen.append(int(mid))
        if int(mid) == 3:
            raise RuntimeError("OF read blew up mid-collect")
        return {"media_id": mid, "ok": True, "status": "described"}

    async def _flags(_aid, mid, **_k):
        return {"media_id": mid, "ok": True, "status": "flagged"}

    vault_ai_vision._describe_one = _desc
    vault_ai_vision._flags_one = _flags
    try:
        await vault_ai_vision._run_describe_all(aid, "force", prompt_version="v2")
    finally:
        vault_ai_vision._describe_one, vault_ai_vision._flags_one = o_desc, o_flags

    assert sorted(seen) == [1, 2, 3, 4, 5], (
        f"one raising item ended the sweep — only {sorted(seen)} were attempted")
    prog = vault_ai_vision._describe_progress.get(aid) or {}
    assert not prog.get("aborted"), f"a survivable item aborted the sweep: {prog}"
    assert prog.get("done") == 5, prog
    assert prog.get("failed") == 1, f"the raise was not counted as a failure: {prog}"
    assert "RuntimeError" in (prog.get("error") or ""), (
        f"the reason it failed was swallowed: {prog}")


async def case_redescribe_keeps_flags_and_operator_fixes():
    """REGRESSION — `ai_fields_json` is ONE column written by three passes, and
    `_describe_one` wrote it WHOLE from the describe schema alone. So a re-scan
    silently deleted:

      * the exposure flags. The item came back with no `_flags_v`, every gated
        lane emptied, and the flags pass had to be run over the vault again —
        which is exactly what the operator reported.
      * the dispute corrections. `locked_fields_json` guarded four COLUMNS and
        nothing inside this blob, so a dispute they had settled reverted to the
        model's answer on the next re-scan. A lock that silently un-does itself
        is worse than no lock: there is no reason to look at the item again.

    Only the `vault_ai_fix.FIXABLE` half is restored, and the boundary matters:
    `edit_item` locks (description, tier, price) deliberately leave this blob as
    the model's RAW answer and win at read time through `effective_value`, so
    stamping those in here would erase the evidence that a re-run ever ran —
    `test_vault_ai_edit_lock.case_rerun_respects_lock` asserts exactly that.
    `vault_ai_fix` is the opposite: the lanes and `contradictions` read
    `ai_fields_json` directly, so its fixes have to live in it.
    """
    aid = _fresh_account()
    await _seed_account(aid)
    async with get_session() as s:
        s.add(VaultItem(
            account_id=aid, media_id=70, kind="photo",
            created_at=datetime(2026, 6, 1, 10, 0, 0), tags="[]",
            describe_status="described",
            ai_fields_json=json.dumps({
                "description": "old prose", "clothing_state": "fully_nude",
                # written by the FLAGS pass
                "vulva_vis": "covered", "breasts_vis": "bare",
                "anus_vis": "not_in_frame", "over_vulva": "black lace thong",
                "underwear_visible": True, "_flags_v": 3,
                "_flags_model": "qwen3-vl-30b",
                # settled by the OPERATOR on the disputes screen
                "explicitness": "suggestive",
            }),
            # `explicitness` is FIXABLE — a dispute fix, read straight out of
            # ai_fields_json, so it has to be restored INTO it. `description` is
            # not: it takes the edit_item read-time path, so the model's fresh
            # prose must still land in the blob (see the assert below).
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
    assert got["clothing_state"] == "lingerie_on", got
    for key, want in (("vulva_vis", "covered"), ("breasts_vis", "bare"),
                      ("anus_vis", "not_in_frame"),
                      ("over_vulva", "black lace thong"), ("_flags_v", 3)):
        assert got.get(key) == want, f"re-describe dropped the flags: {key}={got.get(key)!r}"
    assert got["explicitness"] == "suggestive", (
        "a locked dispute fix was reverted by the model")


async def case_describing_one_item_flags_it_too():
    """The sweep has flagged in the same breath for a while; the ONE-item button
    never did, so a hand-described item was the only row in the vault the gated
    lanes could not read — and nothing on screen said so."""
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [80])

    flagged: list[int] = []
    o_desc, o_flags = vault_ai_vision._describe_one, vault_ai_vision._flags_one

    async def _desc(_aid, mid, **_k):
        return {"media_id": mid, "ok": True, "status": "described"}

    async def _flags(_aid, mid, **_k):
        flagged.append(int(mid))
        return {"media_id": mid, "ok": True, "status": "flagged"}

    vault_ai_vision._describe_one = _desc
    vault_ai_vision._flags_one = _flags
    try:
        out = await vault_ai_vision.describe_one({"account_id": aid, "media_id": 80})
        assert out["ok"], out
        assert flagged == [80], f"the single-item describe did not flag it: {flagged}"

        # …and a flags failure must not lose the description that was paid for.
        async def _boom(_aid, mid, **_k):
            raise RuntimeError("provider down")

        vault_ai_vision._flags_one = _boom
        out2 = await vault_ai_vision.describe_one({"account_id": aid, "media_id": 80})
        assert out2["ok"], "a cheap flags failure sank an expensive describe"
    finally:
        vault_ai_vision._describe_one, vault_ai_vision._flags_one = o_desc, o_flags


async def case_describe_all_attempts_every_undescribed_item() -> None:
    """'Describe all' attempts EVERYTHING it is not already done with, including a
    clip blocked minutes ago. A blocked_drm cooldown belonged to the (since-
    deleted) recurring `describe_media` sweep — never to a button whose label
    quotes a count. Honouring it here made the button offer 1,777 items and
    attempt none of them, with nothing in the UI to say so."""
    aid = _fresh_account()
    await _seed_account(aid)
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(VaultItem(account_id=aid, media_id=10, kind="photo",
                        created_at=datetime(2026, 6, 1), tags="[]"))  # undescribed
        s.add(VaultItem(account_id=aid, media_id=11, kind="video",
                        created_at=datetime(2026, 6, 1), tags="[]",
                        describe_status="blocked_drm",
                        describe_generated_at=now - timedelta(hours=2)))  # just blocked
        s.add(VaultItem(account_id=aid, media_id=12, kind="photo",
                        created_at=datetime(2026, 6, 1), tags="[]",
                        describe_status="described",
                        describe_generated_at=now - timedelta(hours=2)))  # done → skip
        await s.commit()

    seen: list[int] = []

    async def _spy(_aid, mid, **_k):
        seen.append(int(mid))
        return {"media_id": mid, "ok": True, "status": "described"}

    orig = vault_ai_vision._describe_one
    vault_ai_vision._describe_one = _spy
    try:
        await vault_ai_vision._run_describe_all(aid, "undescribed", prompt_version="v2")
        assert sorted(seen) == [10, 11], (
            f"the button skipped work it counted: {seen}")
        # …and it is still the count the UI showed: `described` stays untouched.
        assert 12 not in seen, "a finished item was re-billed"
    finally:
        vault_ai_vision._describe_one = orig


async def case_fetch_failure_is_not_blocked_drm() -> None:
    """2026-08-04: 1,777 items whose OF signature had merely expired were stamped
    `blocked_drm`, which carries a 7-day cool-off meant for clips OF genuinely
    cannot render — so the sweep that would have fixed them skipped them. A
    transient failure must be stamped as one, and must be retried immediately."""
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [60], kind="photo")

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
    # And it says SOMETHING to the operator. `vault_sweep` shows the first
    # `detail` as the sweep's error, so a frameless return with none is a vault
    # that fails N of N times and reports no reason at all — the shape of the
    # missing-provider-key incident.
    assert out.get("detail"), f"a failure with no cause is not a report: {out}"

    # When `collect` swallowed an exception it says WHICH — `fetch_failed` alone
    # cannot tell an expired OF signature from a bug in the frame code.
    async def _blew_up(*_a, **_k):
        return vault_frames.Collected([], "fetch_failed", "TypeError: NoneType")

    vault_frames.collect = _blew_up
    try:
        out = await vault_ai_vision._describe_one(aid, 60)
    finally:
        vault_frames.collect = orig
    assert "TypeError" in out["detail"], out

    # …and the very next default sweep still offers it, cool-off untouched.
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
    """An audio file has no frame. Sweeping it is a guaranteed failure per pass,
    and the ones whose signature was still live had their MP3 bytes posted to a
    vision endpoint as an image. The plan's total must not count them either —
    it was quoting a number the sweep could never meet."""
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
        await vault_ai_vision._run_describe_all(aid, "force", prompt_version="v2")
    finally:
        vault_ai_vision._describe_one = orig
    assert seen == [80], f"audio must not be swept, got {seen}"

    plan = await vault_ai_vision.describe_all_plan(account_id=aid, prompt_version="v2")
    assert plan["total"] == 1, f"plan counted the audio row: {plan}"


async def case_flags_failure_is_written_down() -> None:
    """The TAGGING pass shares the fetch path, so it broke the same way — and
    said nothing at all: it returned `no_image` to a caller that logged it and
    moved on, leaving a described-but-unflagged row with no record of why. The
    marker must NOT claim the flags are current, or the retry stops."""
    aid = _fresh_account()
    await _seed_account(aid)
    await _seed_items(aid, [90], kind="photo")

    async def _cold(*_a, **_k):
        return vault_frames.Collected([], "fetch_failed")

    orig = vault_frames.collect
    vault_frames.collect = _cold
    try:
        out = await vault_ai_vision._flags_one(aid, 90)
    finally:
        vault_frames.collect = orig
    assert out["ok"] is False and out["status"] == "fetch_failed", out

    fields = json.loads((await _get(aid, 90)).ai_fields_json or "{}")
    assert fields.get("_flags_status") == "fetch_failed", fields
    assert "_flags_v" not in fields, "a failure must not mark flags current"
    assert 90 in await vault_ai_vision._flags_todo(aid), "failed item dropped out of todo"


async def case_a_dead_collect_stops_claiming_it_is_running() -> None:
    """A collect finalises its own row, so a relay restart mid-sweep leaves
    `running` behind with nothing left to ever clear it. One prod row said
    `running / warming` for three days — and that stall is why 1,046 clips were
    never warmed, while the status endpoint reported the sweep as still working.

    `_running` is process-local and is the only place a live sweep is tracked, so
    a row claiming to run for an account nobody is running is orphaned."""
    aid = _fresh_account()
    row = VaultCacheRun(account_id=aid, status="running", phase="warming")

    vault_ai_api._running.discard(aid)
    assert vault_ai_api._run_status(row, aid) == "interrupted", "the lie survived"

    vault_ai_api._running.add(aid)
    try:
        assert vault_ai_api._run_status(row, aid) == "running", (
            "a sweep that IS running must still say so")
    finally:
        vault_ai_api._running.discard(aid)

    # A finished run is never reinterpreted — only `running` can be orphaned.
    for done in ("done", "error"):
        row.status = done
        assert vault_ai_api._run_status(row, aid) == done, done


async def _spend_today(aid: str, millicents: int, *, provider: str = "deepinfra",
                       flagged: bool = False) -> None:
    """Put `millicents` on today's per-(account, provider) rollup — the row the
    cap is enforced against."""
    async with get_session() as s:
        s.add(GrokDailyCost(
            day=datetime.utcnow().strftime("%Y-%m-%d"), account_id=aid,
            provider=provider, cost_cents=int(millicents), call_count=1,
            is_capped=flagged, updated_at=datetime.utcnow()))
        await s.commit()


async def case_describe_all_refuses_to_start_over_the_cap() -> None:
    """Over the daily cap, pressing Describe all again started a whole sweep.

    Nothing about it was unsafe — `llm_client._reserve` refuses every call over
    the cap, so the sweep stopped on the first one. It was DISHONEST: it pulled
    frames off OF for a batch of items first, wrote nothing, and ended with the
    same count back on the button. Pressing it again did the same again, and
    nothing anywhere said "you are out of budget today".
    """
    aid = _fresh_account()
    await _seed_account(aid, cap_cents=100)  # $1.00 = 10,000 mc
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
            # The numbers have to be ON the refusal: "capped" without them is
            # the same dead end as no message at all.
            assert e.detail["spent_millicents"] == 10_000, e.detail
            assert e.detail["cap_millicents"] == 10_000, e.detail
            assert "$1.00" in e.detail["blocked_reason"], e.detail["blocked_reason"]
        assert started == [], f"a refused start still ran a sweep: {started}"
        assert aid not in vault_ai_vision._describe_running, (
            "the refusal left the account marked as running — nothing would "
            "ever clear it, and every later start would 409")
    finally:
        vault_ai_vision._run_describe_all = orig


async def case_one_item_describe_over_the_cap_fetches_nothing() -> None:
    """`Describe selected` is a client-side loop over the single-item endpoint.
    Over the cap every one of those calls was refused by `_reserve` — AFTER the
    frames had been pulled off OF and (for a clip) cut with ffmpeg. Fifty
    selected items bought fifty rounds of that and zero descriptions."""
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

        # SAME shape as the in-flight refusal, down to the sentence. The
        # pre-flight is an optimisation, not a second contract: a caller that
        # had to tell the two apart would have two cases to get right, and the
        # in-flight one is the path that shows an operator raw exception text
        # unless they are kept together. `_describe_one` is the real thing —
        # it collects frames, calls the model, and is refused by `_reserve`.
        assert "$1.00" in out["detail"], out["detail"]
        # The in-flight path resolves a key BEFORE it reserves (fail-closed per
        # Agency, 4cbd576b), and this account has no owner — so without a house
        # key it would refuse for the missing key and never reach `_reserve`.
        # Hand it one for this call only; the cap refusal still means no HTTP.
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
    """`is_capped` is set when a reservation is refused and never cleared, so
    an operator who RAISES the daily cap mid-day would still be locked out by a
    gate that read it. The gate reads what is spent against what is allowed;
    the flag is carried for display only.

    The plan endpoint carries the same state, so the button can go grey before
    it is pressed rather than after.
    """
    aid = _fresh_account()
    await _seed_account(aid, cap_cents=100)
    await _seed_items(aid, [93])
    await _spend_today(aid, 10_000, flagged=True)

    plan = await vault_ai_vision.describe_all_plan(account_id=aid)
    assert plan["cap"]["capped"] is True and plan["cap"]["flagged"] is True, plan["cap"]
    assert plan["cap"]["remaining_millicents"] == 0, plan["cap"]

    # Raise the cap: the money now fits, the stale flag must not veto it.
    async with get_session() as s:
        await s.execute(
            update(AccountAiConfig).where(AccountAiConfig.account_id == aid)
            .values(daily_cost_cap_cents=500))
        await s.commit()
    state = await llm_client.cap_state(aid, "deepinfra")
    assert state["capped"] is False, state
    assert state["flagged"] is True, "the day's cap-hit is still worth reporting"
    assert state["remaining_millicents"] == 40_000, state

    # Another provider's spend is another budget — the cap is per-(account,
    # provider), and reading the wrong row would refuse a describe because the
    # chat engines had a busy day.
    other = await llm_client.cap_state(aid, "deepseek")
    assert other["spent_millicents"] == 0, other


async def case_capped_means_no_call_on_the_model_fits() -> None:
    """With a model, `capped` is "no call on it fits", not spent >= cap: the
    last reservation that fit settles under the cap and the spend stays just
    below it while every call is refused. Less left than one reservation
    (no input, a full output) is capped; a refusal today with under two left
    is capped; a cap raised since is not. The vision routes read this one
    predicate, so a hopeless describe fetches nothing."""
    model = "qwen3-vl-30b"
    floor = llm_client._cost_millicents(model, 0, llm_client._ASSUMED_OUTPUT_TOKENS)
    assert 0 < floor < 10_000, floor

    async def _state(left: int, flagged: bool = False) -> dict:
        aid = _fresh_account()
        await _seed_account(aid, cap_cents=100)  # 10,000 mc
        await _spend_today(aid, 10_000 - left, flagged=flagged)
        return await llm_client.cap_state(aid, "deepinfra", model)

    assert (await _state(floor - 1))["capped"] is True                      # no room at all
    assert (await _state(floor + 1))["capped"] is False                     # still fits
    assert (await _state(2 * floor - 1, flagged=True))["capped"] is True    # refused, too little left
    assert (await _state(min(5 * floor, 10_000), flagged=True))["capped"] is False  # cap raised since
    no_model = await llm_client.cap_state(_fresh_account(), "deepinfra")
    assert no_model["capped"] is False, no_model

    aid = _fresh_account()
    await _seed_account(aid, cap_cents=100)
    await _seed_items(aid, [94])
    await _spend_today(aid, 10_000 - (floor - 1))   # spent < cap, yet nothing fits
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
    """A 30b refusal is paid for too. The sweep sums `cost_millicents`, so
    returning only the 235b call's cost under-reported every escalated item."""
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
    """A 30b refusal is paid for even when the 235b retry never answers: the
    cap trips (`capped`, and still NO row write — capped means try later) or
    the provider errors (`error`). Both must carry the 30b cost, or the sweep's
    sum under-reports exactly the items that escalated."""
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
    case_flags_failure_is_written_down,
    case_a_dead_collect_stops_claiming_it_is_running,
)
