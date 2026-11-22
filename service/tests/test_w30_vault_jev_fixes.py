#!/usr/bin/env python3
"""W30 Vault Jev/Describe review fixes (rwl W30-vault-jev-describe, J ids = REVIEW-FINDINGS F ids).
Plain-assert, no pytest (repo convention). Temp DB bound by _harness; no OF, TypeSafe, NudeNet or LLM network
(every external call is a stub).

Run: ./venv/bin/python service/tests/test_w30_vault_jev_fixes.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
from copy import deepcopy  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

import full_ai_prepare  # noqa: E402
from automations import full_ai_sell  # noqa: E402
import llm_client  # noqa: E402
import tenant_keys  # noqa: E402
import vault_ai_api as api  # noqa: E402
import vault_ai_brief as brief  # noqa: E402
import vault_ai_vision as vision  # noqa: E402
import vault_describe_jev as describe  # noqa: E402
import vault_frames  # noqa: E402
import vault_jev as jev  # noqa: E402
import vault_jev_flags as flags  # noqa: E402
import vault_jev_pass  # noqa: E402
import vault_jev_manual  # noqa: E402
import vault_jev_rules as rules  # noqa: E402
import vault_pack_picker  # noqa: E402
import script_fill_decide  # noqa: E402
import vault_runs  # noqa: E402
import vault_scripts  # noqa: E402
import vault_stills  # noqa: E402
import vault_sweep  # noqa: E402
import vault_topic_folders as topics  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, GrokCall, GrokDailyCost, VaultCacheRun, VaultItem  # noqa: E402
from _jev_fixtures import _golden, photo_jev, video_jev  # noqa: E402
from vault_collect_plan import CollectPlan  # noqa: E402


def _jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64)).save(buf, "JPEG")
    return buf.getvalue()


@contextlib.contextmanager
def _patched(*triples):
    """`patch.object` for each (obj, name, value), undone together."""
    with contextlib.ExitStack() as stack:
        for obj, name, value in triples:
            stack.enter_context(patch.object(obj, name, value))
        yield


def _record(image):
    return deepcopy(next(g["rec"] for g in _golden() if g["img"] == image))


def _photo(record, derived, scores):
    passes = [p for p, key in (("1", "resp"), ("2", "resp2"), ("L", "respL")) if key in record]
    return rules.blob(derived, scores, passes=passes, tok=1, px=[800, 1200],
                      at="2026-11-12T00:00:00", answers=rules.overlay(record, derived))


def case_F1a_free_photo_flags_keep_bare_regions():
    rec = _record("set2/orig/2.jpg")
    # The lower crop sends a topless reading to review, then low NudeNet scores settle it free.
    for key in ("vulva_visible_a", "vulva_visible_b"):
        rec["respL"]["answers"][key]["noul"] = 0.4
    derived = rules.final(rec, {})
    assert (derived["lane5"], derived["settled"], derived["breasts_bare"]) == ("free", "nn.10", "y")
    topless = _photo(rec, derived, {})
    # Exercise the mapper's independent crotch answer using the same stored shape.
    bare_crotch = {**topless, "breasts_bare": "n", "crotch_bare": "y"}
    observed = []
    for blob, region in ((topless, "breasts_vis"), (bare_crotch, "vulva_vis")):
        mapped = flags.reading(blob)
        observed.append((mapped[region], mapped["explicitness"], brief.free_vetoed(mapped)))
    assert observed == [("bare", "explicit", True)] * 2


def case_F1b_uncertain_frame_excludes_new_and_stored_clips_from_free():
    clean = _record("set2/orig/46.jpg")
    uncertain = _record("set2/orig/118.jpg")
    # The clean frame still answers "n" but ranks higher on severity.
    for key in ("penetration", "penetration_b"):
        clean["resp"]["answers"][key]["noul"] = 0.55
    recs = [clean, uncertain]
    scores = [{}, {}]
    clean_read, uncertain_read = [rules.final(rec, nn) for rec, nn in zip(recs, scores)]
    assert clean_read["lane5"] == uncertain_read["lane5"] == "free"
    assert (clean_read["breasts_bare"], uncertain_read["breasts_bare"]) == ("n", "unsure")
    assert rules.sev(clean_read) > rules.sev(uncertain_read)
    px = [1280, 720]
    packed = [
        {"px": px, "lane5": "free", "nn": [0, 0],
         **{p: rules.pack(rec[key]["answers"], rules.ORDER[p])
            for p, key in (("1", "resp"), ("2", "resp2")) if key in rec}}
        for rec in recs
    ]
    frames, top = rules.video_final(recs, scores)
    fresh = rules.video_blob(frames, top, recs, scores, frames=packed, passes=["1", "2"],
                             tok=1, px=[px, px], at="2026-11-12T00:00:00", src="720",
                             review=None, nbytes=1)
    # Old jv1 blobs contain the winning frame's body answers and all packed frame answers.
    stored = dict(_photo(clean, clean_read, {}), kind="video", vv="jv1", frame=0,
                  frames=packed, src="720", review=None, bytes=1)
    assert rules.current({"_jev": stored})
    rows = [{"kind": "video", "media_id": i, "fields": {"_jev": blob}}
            for i, blob in enumerate((fresh, stored), start=1)]
    free = topics.assign(rows, ["clothed_tease"]).get(("clothed_tease", "free"), [])
    assert (fresh["breasts_bare"], [row["media_id"] for row in free]) == ("unsure", []), "fresh=1, stored=2"


def case_F21_held_legacy_clip_is_ineligible_for_mass():
    legacy = {"description": "She poses by the window.", "explicitness": "suggestive"}
    assert not brief.flags_known(legacy)
    assert vault_scripts._lane_mass({"tier": "suggestive"}, legacy, "video")
    held = vault_jev_pass.held_blob(None, 3, "stub frame fetch failed", "2026-11-12T00:00:00", terminal=True)
    fields = brief.settled_reading({**legacy, "_jev": held})
    assert not vault_scripts._lane_mass({"tier": fields["explicitness"]}, fields, "video")


def case_F22_empty_scrub_fails_and_preserves_previous_description():
    aid, mid = "w30-f22", 1
    prior = "She poses by the window."
    blob = photo_jev()
    answer = {"description": "Her nipples are visible."}
    assert describe.route(kind="photo", fields={"_jev": blob})[0] == "prose"
    assert describe.answered("prose", answer)
    assert describe.prose_answer(answer, blob)["description"] == ""
    chat = AsyncMock(return_value=SimpleNamespace(content=json.dumps(answer), cost_cents=5, call_id=1))
    collected = AsyncMock(return_value=vault_frames.Collected([vision.vision.img_data_url(_jpeg())], "ok"))

    async def run():
        async with get_session() as s:
            s.add(Account(id=aid))
            s.add(VaultItem(account_id=aid, media_id=mid, kind="photo", created_at=datetime(2026, 1, 1),
                            describe_status="described", description=prior,
                            ai_fields_json=json.dumps({"_jev": blob, "description": prior})))
        result = await vision._describe_one(aid, mid)
        async with get_session() as s:
            return result, await s.get(VaultItem, (aid, mid))

    with _patched((llm_client, "chat", chat), (vault_frames, "collect", collected)):
        result, item = asyncio.run(run())
    chat.assert_awaited()
    observed = (result["ok"], result["status"], item.describe_status == "described",
                item.description, json.loads(item.ai_fields_json)["description"])
    assert observed == (False, "refused", False, prior, prior)   # R3: a Terminal failure, not a retried error


def case_R3_scrub_empty_item_is_not_repaid_every_sweep():
    """A scrub-emptied describe (F22) is a terminal failure: the Describe target sweep skips it, so its DeepInfra
    call is not re-bought every sweep; the prior description stays."""
    aid, mid = "w30-r3", 1
    prior = "She poses by the window."
    blob = photo_jev()
    chat = AsyncMock(return_value=SimpleNamespace(content=json.dumps({"description": "Her nipples are visible."}),
                                                  cost_cents=5, call_id=1))
    collected = AsyncMock(return_value=vault_frames.Collected([vision.vision.img_data_url(_jpeg())], "ok"))

    async def run():
        async with get_session() as s:
            s.add(Account(id=aid))
            s.add(VaultItem(account_id=aid, media_id=mid, kind="photo", created_at=datetime(2026, 1, 1),
                            describe_status="described", description=prior,
                            ai_fields_json=json.dumps({"_jev": blob, "description": prior}), tags="[]"))
        first = await vision._describe_one(aid, mid)
        vision._describe_running.add(aid)
        await vision._run_describe_all(aid, "undescribed", target=100)
        async with get_session() as s:
            return first, await s.get(VaultItem, (aid, mid))

    with _patched((llm_client, "chat", chat), (vault_frames, "collect", collected),
                  (vault_jev_pass, "safe", AsyncMock(return_value=None))):
        first, item = asyncio.run(run())
    assert not first["ok"] and chat.await_count == 1, (first, chat.await_count)
    assert item.description == prior and item.describe_status != "described", item.describe_status


def case_F2_interrupted_collect_does_not_count_as_a_walk():
    client = SimpleNamespace(
        vault_lists=lambda **kw: {"list": [], "hasMore": False},
        vault_media=lambda **kw: {"list": [{"id": 2, "type": "photo"}], "hasMore": True},
    )

    async def run():
        observed = {}
        for decision in ("stop", "timeout"):
            aid = f"w30-f2-{decision}"
            since = datetime.utcnow()
            async with get_session() as s:
                s.add(Account(id=aid))
            run_id = await api.claim_collect(aid)
            await api._run_collect(aid, run_id, pause_every=1)
            async with get_session() as s:
                row = await s.get(VaultCacheRun, run_id)
                assert row.finished_at and row.total_seen == 1 and row.error.startswith("stopped"), row.error
                recent_walk = await vault_runs.walked_since(s, aid, since)
            observed[decision] = (recent_walk, (await full_ai_prepare.read_facts(aid))["harvested"])
        return observed

    with _patched((api.ax, "_make_client", lambda aid: client), (api, "_PAGE_SLEEP_S", 0),
                  (api, "_ask_to_continue", AsyncMock(side_effect=["stop", "timeout"]))):
        observed = asyncio.run(run())
    assert observed == {"stop": (False, False), "timeout": (False, False)}, observed


def case_F3_offset_shift_cannot_mark_incomplete_coverage_walked():
    plan = CollectPlan([], max_pages=30)
    live = list(range(1, 1201))
    seen = set()
    while (step := plan.next()) is not None:
        ordered = live[::-1] if step.kind == "desc" else live
        end = step.offset + plan.page
        page = ordered[step.offset:end]
        seen.update(page)
        plan.feed(step, page, end < len(live))
        if plan.all_pages == 1:
            live.remove(1200)  # A consumed item disappears, shifting the next descending offset.

    missing = set(live) - seen
    assert not (plan.walked and missing), f"walked=True with live IDs unseen: {sorted(missing)}"


def case_R2_gap_walk_is_not_a_walk():
    """A Collect that ended with OF's list shifted under it (a `vault_collect_plan` gap) may have missed items: it
    satisfies neither the collector's weekly schedule (`walked_since`) nor Full AI's `harvested`, and says so — also
    when it then hit the page cap (the gap wins: W30 C4)."""
    for n, max_pages in ((250, api._MAX_PAGES), (1000, 3)):
        _gap_walk(n, max_pages)
    assert "not counted as a walk" in vault_runs.GAP_ERROR, vault_runs.GAP_ERROR


def _gap_walk(n: int, max_pages: int) -> None:
    live = list(range(1, n + 1))
    calls = []

    def vault_media(**kw):
        calls.append(kw)
        order = live[::-1] if kw["sort"] == "desc" else live
        page = order[kw["offset"]:kw["offset"] + kw["limit"]]
        if len(calls) == 1:
            del live[-2:]   # two newest removed after page 1: the desc cursor's next page skips past one
        return {"list": [{"id": i, "type": "photo"} for i in page],
                "hasMore": kw["offset"] + kw["limit"] < len(order)}
    client = SimpleNamespace(vault_lists=lambda **kw: {"list": [], "hasMore": False}, vault_media=vault_media)

    async def run():
        aid = f"w30-r2-{max_pages}"
        since = datetime.utcnow()
        async with get_session() as s:
            s.add(Account(id=aid))
        run_id = await api.claim_collect(aid)
        await api._run_collect(aid, run_id, pause_every=0)
        async with get_session() as s:
            row = await s.get(VaultCacheRun, run_id)
            walk = await vault_runs.walked_since(s, aid, since)
        return row, walk, (await full_ai_prepare.read_facts(aid))["harvested"]

    with _patched((api.ax, "_make_client", lambda aid: client), (api, "_PAGE_SLEEP_S", 0),
                  (api, "_MAX_PAGES", max_pages)):
        row, walk, harvested = asyncio.run(run())
    assert row.status == "done" and row.error == vault_runs.GAP_ERROR, (n, row.status, row.phase, row.error)
    assert (walk, harvested) == (False, False), (n, row.phase, walk, harvested)


def case_F8_detector_failure_settles_completed_provider_usage():
    aid = "w30-f8"
    response = _record("set2/orig/46.jpg")["resp"]
    completed = []

    async def ask(*args, **kwargs):
        completed.append(response["usage"]["input_tokens"])
        return response

    async def detector_error(data):
        raise RuntimeError("stub detector inference failed")


    async def run():
        async with get_session() as s:
            s.add(Account(id=aid))
            s.add(AccountAiConfig(account_id=aid, daily_cost_cap_cents=1000))
        result = await jev.run(aid, _jpeg())
        async with get_session() as s:
            calls = (await s.scalars(select(GrokCall).where(GrokCall.account_id == aid))).all()
            daily = (await s.scalars(select(GrokDailyCost).where(GrokDailyCost.account_id == aid))).all()
        return result, calls, daily

    with _patched((tenant_keys, "typesafe_key_for", AsyncMock(return_value="test-key")),
                  (jev, "nudenet_ready", AsyncMock(return_value=(True, ""))), (jev, "nudenet_scores", detector_error),
                  (jev, "_ask", ask)):
        result, calls, daily = asyncio.run(run())
    assert not result["ok"] and "stub detector inference failed" in result["detail"], result
    # Detector-first may skip TypeSafe. If TypeSafe answered, the failed run still owes its usage.
    tokens = sum(completed)
    cost = jev.cost_millicents(tokens)
    observed = (sum(call.tokens_in or 0 for call in calls), sum(call.cost_cents or 0 for call in calls),
                sum(row.cost_cents for row in daily))
    assert observed == (tokens, cost, cost)

def case_F4_resign_failure_counts_and_gave_up_clip_is_neutral():
    """A failed re-sign (OF did not answer) is a brief failure the retry cap counts; a deleted one is not. A clip
    the Jev pass gave up on: its own status (not current), the flags visit is no success, Describe's skip says so."""
    item = SimpleNamespace(media_id=1, duration_seconds=10)

    async def fetch(reason):
        with _patched((vault_frames.ax, "_make_client", lambda aid: object()),
                      (vault_stills, "resolve_fresh", AsyncMock(return_value=vault_stills.Fresh(None, reason)))):
            return await vault_frames.collect_jev_video("w30-f4", item)

    assert asyncio.run(fetch("fetch_failed")).transient
    assert not asyncio.run(fetch("gone")).transient
    aid, mid = "w30-f4", 2
    held = vault_jev_pass.held_blob(None, 3, "stub frame fetch failed", "2026-11-12T00:00:00", terminal=True)

    async def run():
        async with get_session() as s:
            s.add(Account(id=aid))
            s.add(VaultItem(account_id=aid, media_id=mid, kind="video", created_at=datetime(2026, 1, 1),
                            ai_fields_json=json.dumps({"_jev": held})))
        flag = await vision._jev_and_flag(aid, mid, jev_sweep=vault_jev_pass.Sweep())
        desc = await vision._describe_one(aid, mid)
        return flag, desc, await vision._flags_todo(aid)

    flag, desc, todo = asyncio.run(run())
    assert not rules.current({"_jev": held}) and rules.gave_up({"_jev": held})
    assert (flag["ok"], flag["status"]) == (False, rules.GAVE_UP), flag
    assert desc["status"] == rules.GAVE_UP and "retried" not in desc["detail"].replace("not retried", ""), desc
    assert flag["status"] in vault_sweep.NEUTRAL and mid not in todo

def case_F5_scrub_failure_leaves_no_part_and_generic_failure_counts():
    """A store that cannot take the 400px scrub (ENOSPC): no `.part` left, the error raised for
    `_jev_frames_sync` to log (best-effort). Anything raising inside a clip's collect is a brief failure the
    retry cap counts (`transient`), never an uncounted re-download every sweep."""
    import errno
    import shutil
    import tempfile
    from pathlib import Path
    import storyboard

    def full(a, b):
        Path(b).write_bytes(b"x")   # a partial copy landed
        raise OSError(errno.ENOSPC, "No space left on device")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "0.jpg").write_bytes(_jpeg())
        try:
            with _patched((shutil, "copyfile", full)):
                vault_frames._publish_scrub(tmp, "w30f5scrub0")
        except OSError:
            pass
        else:
            raise AssertionError("ENOSPC swallowed by _publish_scrub")
    assert not list((storyboard._STORYBOARD_DIR / "w30f5scrub0").glob(".*.part"))

    async def boom(*a, **k):
        raise PermissionError("EACCES stub")

    with _patched((vault_frames, "_collect_jev_video", boom)):
        got = asyncio.run(vault_frames.collect_jev_video("w30-f5", SimpleNamespace(media_id=1)))
    assert got.transient and not got.frames and "EACCES" in got.detail, got

def case_F6_jev_cap_skips_do_not_trip_the_breaker():
    """A sweep whose Jev cap tripped: every later unread item is `jev_capped` (no fetch, no call). More than
    BREAK_AFTER of them in a row is no "items in a row failed" stop; the sweep walks on (items Jev already read
    still describe) and names the cap as its first error."""
    n = vault_sweep.BREAK_AFTER + 5

    async def visit(mid):
        return {"ok": False, "status": "jev_capped", "detail": vault_jev_pass.CAP_SKIP}

    async def run():
        return await vault_sweep.run(list(range(n)), visit, concurrency=4, gate=lambda: asyncio.Semaphore(4),
                                     into={}, key="w30-f6", label="w30-f6")

    res = asyncio.run(run())
    assert (res.stop, res.done, res.failed, res.error) == (None, n, n, vault_jev_pass.CAP_SKIP), res



def case_R5_cap_notice_survives_an_earlier_failure():
    """The Jev cap is named on its own line (`notice`) even when another failure came first (`error`). W30 R5."""
    async def visit(mid):
        if mid == 0:
            return {"ok": False, "status": "error", "detail": "frame decode failed"}
        return {"ok": False, "status": "jev_capped", "detail": "no Jev reading (jev_capped)",
                "notice": vault_jev_pass.CAP_SKIP}

    async def run():
        into: dict = {}
        await vault_sweep.run([0, 1, 2], visit, concurrency=1, gate=lambda: asyncio.Semaphore(1),
                              into=into, key="w30-r5", label="w30-r5")
        return into["w30-r5"]

    prog = asyncio.run(run())
    assert prog["error"] == "frame decode failed" and prog["notice"] == vault_jev_pass.CAP_SKIP, prog

# W30 C1 — every free entry point over one fixture table. Script lanes: every PURPOSE_LANES slug that sends free
# (its purpose says mass or public), not hand-named.
_FREE_SLUGS = {slug for slug, _, purpose, _ in vault_scripts.PURPOSE_LANES if "mass" in purpose or "public" in purpose}
_STALE = {"description": "lace set", "explicitness": "suggestive", "clothing_state": "lingerie_on",
          "genitals_covered": True, "clothing_items": ["black lace bra", "black thong"], "underwear_visible": True,
          "_flags_v": brief.FLAGS_VERSION, "_flags_model": "qwen3-vl-30b",
          **{k: "covered" for k in brief.VIS_REGIONS}}


def _restamp(j: dict) -> dict:
    """`_STALE` re-stamped from `j` (the Jev pass's `vault_jev_flags.apply`)."""
    return flags.apply({**_STALE, "_jev": j}, j)


def _c1_rows() -> dict[str, tuple[str, dict]]:
    """name → (kind, ai_fields). `_STALE` flags are a pre-F1a / pre-Jev covered stamp; `_restamp` re-stamps."""
    y_photo = {**photo_jev("free"), "breasts_bare": "y"}
    unsure_photo = {**photo_jev("free"), "breasts_bare": "unsure"}
    # Stored clips without the `body` stamp (pre-F1b): the winning frame's answers, every frame packed.
    px = [1280, 720]

    def packed(rec):
        return {"px": px, "lane5": "free", "nn": [0, 0],
                **{p: rules.pack(rec[k]["answers"], rules.ORDER[p])
                   for p, k in (("1", "resp"), ("2", "resp2"), ("L", "respL")) if k in rec}}

    clean = _record("set2/orig/46.jpg")
    for key in ("penetration", "penetration_b"):
        clean["resp"]["answers"][key]["noul"] = 0.55
    clean_read = rules.final(clean, {})
    topless = _record("set2/orig/2.jpg")
    for key in ("vulva_visible_a", "vulva_visible_b"):
        topless["respL"]["answers"][key]["noul"] = 0.4
    assert rules.final(topless, {})["breasts_bare"] == "y"

    def stored(frames):
        return dict(_photo(clean, clean_read, {}), kind="video", vv=rules.VIDEO_VERSION, frame=0, frames=frames,
                    src="720", review=None, bytes=1)

    clip_y = stored([packed(clean), packed(topless)])
    clip_unsure = stored([packed(clean), packed(_record("set2/orig/118.jpg"))])
    clip_bad = stored([packed(clean), {"px": px, "lane5": "free", "nn": [0, 0], "1": "junk"}])
    op_pick = {**y_photo, "op": ["lane"]}
    held = vault_jev_pass.held_blob({"v": rules.VERSION, "status": "ok", "lane5": "free", "breasts_bare": "n"},
                                    1, "stub", "2026-11-12T00:00:00", terminal=False)
    gave_up = vault_jev_pass.held_blob(None, 3, "stub", "2026-11-12T00:00:00", terminal=True)
    clean_photo = photo_jev("free")
    return {
        "control: clean free photo": ("photo", _restamp(clean_photo)),
        "photo firm-y, stale covered flags": ("photo", {**_STALE, "_jev": y_photo}),
        "photo firm-y, re-stamped": ("photo", _restamp(y_photo)),
        "clip no body stamp, a y frame": ("video", _restamp(clip_y)),
        "clip no body stamp, a y frame, stale flags": ("video", {**_STALE, "_jev": clip_y}),
        "clip undecodable frame": ("video", _restamp(clip_bad)),
        "clip undecodable frame, stale flags": ("video", {**_STALE, "_jev": clip_bad}),
        "D42 clip unsure frame": ("video", _restamp(clip_unsure)),
        "D42 photo unsure": ("photo", _restamp(unsure_photo)),
        "legacy held clip": ("video", {**_STALE, "_jev": held}),
        "gave-up clip": ("video", {**_STALE, "_jev": gave_up}),
        "operator lane pick, y photo": ("photo", _restamp(op_pick)),
        "D1 paid $10 photo, stale suggestive flags": ("photo", {**_STALE, "_jev": photo_jev("$10")}),
        "D1 paid $50 clip, stale suggestive flags": ("video", {**_STALE, "_jev": video_jev("$50")}),
    }


def _c1_outcomes(rows: dict[str, tuple[str, dict]]) -> dict[str, tuple]:
    """name → (free script slugs admitting, topic free split, pack free rung, not-nude listing, Full AI sell free,
    Fill free)."""
    ids = {name: 9100 + i for i, name in enumerate(rows)}

    async def listing():
        aid = "w30-c1"
        now = datetime.utcnow()
        async with get_session() as s:
            s.add(Account(id=aid))
            for name, (kind, f) in rows.items():
                s.add(VaultItem(account_id=aid, media_id=ids[name], kind=kind, raw_json=json.dumps({"id": ids[name]}),
                                created_at=now, updated_at=now, last_seen_run_id=1, search_text="c1table", tags="[]",
                                of_folder_ids="[]", ai_fields_json=json.dumps(f)))
        with _patched((api, "assert_account_owned", lambda aid: None),
                      (api, "allowed_folder_ids_for_chatter", AsyncMock(return_value=None))):
            out = await api.local_items(account_id=aid, type="all", query="c1table", sort="newest",
                                        internal_folder_id=None, of_folder_id=None, tags=None, not_nude=True,
                                        limit=500, offset=0)
        return {r["id"] for r in out["list"]}

    shown = asyncio.run(listing())
    out = {}
    for name, (kind, f) in rows.items():
        why = vault_scripts._with_why({"media_id": ids[name], "kind": kind, "fields": f})["why"]
        lanes = {slug for slug, _, _, ok in vault_scripts.PURPOSE_LANES if slug in _FREE_SLUGS and ok(why, f, kind)}
        jev = topics.jev_of(f)
        topic = jev is not None and any(topics.split(t, jev, f) == "free" for t in topics.TOPICS)
        out[name] = (lanes, topic, vault_pack_picker.free_ok(f) is True, ids[name] in shown,
                     full_ai_sell._free_safe({"fields": f}),
                     script_fill_decide._free_safe({"kind": kind, "fields": f}, 0))
    return out


def case_C1_free_entry_points_table():
    """A firm Jev bare reading behind stale covered flags, or a clip whose stored frames do not decode, is refused by
    every free entry point (a `jev_bare_unflagged` dispute: Stories / Mass via `is_disputed`; topic / rung /
    not-nude via `free_vetoed`; Full AI sell and Fill via `free_ok`). Owner D42: an "unsure" clip frame or photo
    answer may ride the script lanes (Mass); `free_ok` refuses it. An operator lane pick on a y photo keeps the
    script lanes (the pick wins in the mapper); `body_free` still reads its own "y" (not free elsewhere). W30 C1.
    D1: a paid Jev lane beside a stale sfw / suggestive stamp (no paid-lane exemption) is refused everywhere too."""
    assert {"stories", "mass"} <= _FREE_SLUGS and "tease_10" not in _FREE_SLUGS, _FREE_SLUGS
    rows = _c1_rows()
    got = _c1_outcomes(rows)
    no = (set(), False, False, False, False, False)
    script_only = ({"stories", "mass"}, False, False, False, False, False)
    want = {
        "control: clean free photo": ({"stories", "mass"}, True, True, True, True, True),
        "photo firm-y, stale covered flags": no,
        "photo firm-y, re-stamped": no,
        "clip no body stamp, a y frame": no,
        "clip no body stamp, a y frame, stale flags": no,
        "clip undecodable frame": no,
        "clip undecodable frame, stale flags": no,
        "D42 clip unsure frame": ({"stories", "mass"}, False, False, False, False, False),
        "D42 photo unsure": script_only,
        "legacy held clip": no,
        "gave-up clip": no,
        "operator lane pick, y photo": script_only,
        "D1 paid $10 photo, stale suggestive flags": no,
        "D1 paid $50 clip, stale suggestive flags": no,
    }
    bad = {k: (got[k], want[k]) for k in want if got[k] != want[k]}
    assert not bad, bad
    for name in ("photo firm-y, stale covered flags", "clip undecodable frame", "clip undecodable frame, stale flags",
                 "clip no body stamp, a y frame, stale flags", "D1 paid $10 photo, stale suggestive flags",
                 "D1 paid $50 clip, stale suggestive flags"):
        assert "jev_bare_unflagged" in brief.contradictions(rows[name][1]), name


def case_D4_contradictions_derive_body_once():
    """A stored free clip's `body` re-derives every packed frame: `_contradictions` derives it once per call, for the
    bare regions and the undecodable check alike. W30 D4."""
    rows = _c1_rows()
    real, calls = rules.body, []

    def counted(jev):
        calls.append(1)
        return real(jev)
    for name in ("clip no body stamp, a y frame, stale flags", "clip undecodable frame", "D1 paid $10 photo, stale "
                 "suggestive flags"):
        calls.clear()
        with _patched((rules, "body", counted)):
            codes = brief._contradictions(rows[name][1])
        assert "jev_bare_unflagged" in codes and len(calls) == 1, (name, codes, len(calls))


def case_D3_settled_note_names_the_fix_per_cause():
    """The `jev_bare_unflagged` note says what clears it: frames that do not decode wait on a Jev re-read (a flags
    re-stamp off the same frames changes nothing); stale flags / tier on the sweep's re-stamp. W30 D3."""
    rows = _c1_rows()
    for name, how in (("clip undecodable frame", "never free until Jev re-reads it"),
                      ("clip undecodable frame, stale flags", "never free until Jev re-reads it"),
                      ("photo firm-y, stale covered flags", "never free until the flags re-stamp from Jev"),
                      ("D1 paid $10 photo, stale suggestive flags", "never free until the flags re-stamp from Jev")):
        notes = [n for n in brief.settled_notes(rows[name][1]) if n.startswith(brief.CONTRADICTIONS["jev_bare_unflagged"])]
        assert notes == [f"{brief.CONTRADICTIONS['jev_bare_unflagged']} → {how}"], (name, notes)


def case_C2_retry_state_survives_picks_and_failed_rereads():
    """A clip's retry state (`retries` + `failed_at`, a gave-up mark) outlives an operator pick and a failed
    re-read: a lane pick on a hold in backoff keeps the backoff; a lane pick on a gave-up clip builds a manual blob
    (priced, never `ai_read`), still given up — the flags visit says so, not `flagged`; a failed single-item re-read
    of a gave-up clip leaves it given up; a poster-only fetch that failed briefly counts toward the cap. W30 C2."""
    now = datetime.utcnow()
    soon = vault_jev_pass.held_blob(None, 1, "stub", now.isoformat(), terminal=False)
    picked = vault_jev_manual.overlay(soon, {"lane": "free"}, "video")
    assert not vault_jev_pass.sweep_due({"_jev": picked}, now), picked
    later = now + timedelta(seconds=vault_jev_pass.RETRY_BACKOFF_S + 1)
    assert vault_jev_pass.sweep_due({"_jev": picked}, later), "backoff over: due again"

    gone = vault_jev_pass.held_blob(None, 3, "stub", now.isoformat(), terminal=True)
    gone_picked = vault_jev_manual.overlay(gone, {"lane": "free"}, "video")
    assert rules.current({"_jev": gone_picked}) and not rules.ai_read({"_jev": gone_picked}), gone_picked
    assert rules.retries_spent({"_jev": gone_picked}) and not vault_jev_pass.sweep_due({"_jev": gone_picked}, later)
    for status in ("no_key", "error"):
        merged = jev.merge({"_jev": gone}, {"ok": False, "status": status, "detail": "stub"}, now)
        assert not vault_jev_pass.sweep_due(merged, later), (status, merged["_jev"])

    aid, mid = "w30-c2", 1

    async def flag_visit():
        async with get_session() as s:
            s.add(Account(id=aid))
            s.add(VaultItem(account_id=aid, media_id=mid, kind="video", created_at=datetime(2026, 1, 1),
                            ai_fields_json=json.dumps({"_jev": gone_picked})))
        return await vision._jev_and_flag(aid, mid, jev_sweep=vault_jev_pass.Sweep())

    flag = asyncio.run(flag_visit())
    assert flag["status"] == rules.GAVE_UP and flag["status"] in vault_sweep.NEUTRAL, flag

    async def posters_fail():
        fresh = vault_stills.Fresh({"duration": 10, "videoSources": {}, "files": {}}, "ok")
        with _patched((vault_frames.ax, "_make_client", lambda aid: object()),
                      (vault_stills, "resolve_fresh", AsyncMock(return_value=fresh)),
                      (vault_frames, "_poster_stills",
                       AsyncMock(return_value=vault_frames.Collected([], "fetch_failed", "poster 503 (stub)")))):
            return await vault_frames.collect_jev_video(aid, SimpleNamespace(media_id=2, duration_seconds=10))

    got = asyncio.run(posters_fail())
    assert got.reason == "fetch_failed" and got.transient, got


def case_C5_item_tombstoned_after_selection_is_not_paid():
    """An item OF deleted after a sweep selected it (#948 tombstone, `removed_at`) is not read at visit time: the
    Jev pass is `gone` (neutral) with no fetch or call, Describe returns `gone` before any cached frame or paid call, the description stays.
    W30 C5."""
    aid = "w30-c5"
    prior = "She poses by the window."
    chat = AsyncMock(return_value=SimpleNamespace(content=json.dumps({"description": "new"}), cost_cents=5, call_id=1))
    collected = AsyncMock(return_value=vault_frames.Collected([vision.vision.img_data_url(_jpeg())], "ok"))
    jev_run = AsyncMock()

    async def run():
        async with get_session() as s:
            s.add(Account(id=aid))
            for mid, kind, f in ((1, "video", {"_jev": video_jev(), "description": prior}),
                                 (2, "photo", {"description": prior})):
                s.add(VaultItem(account_id=aid, media_id=mid, kind=kind, created_at=datetime(2026, 1, 1),
                                removed_at=datetime(2026, 11, 20), describe_status="described", description=prior,
                                ai_fields_json=json.dumps(f), tags="[]"))
        desc = await vision._describe_one(aid, 1)
        jev_res = await vault_jev_pass.one(aid, 2, sweep=vault_jev_pass.Sweep())
        async with get_session() as s:
            return desc, jev_res, await s.get(VaultItem, (aid, 1))

    with _patched((llm_client, "chat", chat), (vault_frames, "collect", collected), (jev, "run", jev_run),
                  (jev, "preflight", AsyncMock(return_value=None))):
        desc, jev_res, item = asyncio.run(run())
    assert (desc["ok"], desc["status"]) == (False, "gone"), desc
    assert jev_res["status"] == "gone" and jev_res["status"] in vault_sweep.NEUTRAL, jev_res
    assert not jev_run.await_count and not chat.await_count and not collected.await_count
    assert item.description == prior, item.description


_harness.run()
