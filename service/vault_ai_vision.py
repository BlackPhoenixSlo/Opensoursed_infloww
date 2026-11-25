from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Collection, Mapping

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import and_, case, func, or_, select, update

import llm_client
import vault_ai_brief
import vault_ai_fix
import vault_ai_vision_decide
import vault_cache
import vault_describe_jev
import vault_dupes
import vault_frames
import vault_jev_flags
import vault_jev_manual
import vault_jev_pass
import vault_jev_rules
import vault_scripts
import vault_sweep
import vision
from auth import assert_account_owned
from db.engine import get_session
from db.models import VaultItem
from jsonsafe import load_json
from llm_client import LLMCapExceeded, LLMError
from vault_jev_rules import JEV_KINDS, ai_read as jev_ai_read
from vault_ai_vision_decide import (
    DescribeMode, _frames_for_duration, _parse_describe,
    COPY_MARK, FLAGS_COPY_MARK, JEV_KEY, ReusePlan, build_copy_update, build_describe_update,
    build_flags_copy, coverage, describe_answer, describe_selection, flags_current, is_terminal,
    lead_plan, live_describable, next_attempt, priority_order, prompt_variant, rail_folder_ids, reuse_plan,
    reuse_state,
)

log = logging.getLogger("of-relay.vault_ai_api")

flags_router = APIRouter()
describe_router = APIRouter()



# Every describe call goes to this provider (its key); the spend lands on the
# account's own vault-describe budget row (`llm_client.DESCRIBE_BUDGET`).
_VISION_PROVIDER = "deepinfra"


_FLAGS_VERSION = vault_ai_brief.FLAGS_VERSION



_DESCRIBE_PROMPT = (
    "You are tagging an OnlyFans creator's vault media so it can be searched and "
    "sold. Look at the image and return STRICT JSON only, no prose:\n"
    '{"description": "<one literal sentence>", '
    '"tags": ["<lowercase tags>"], '
    '"explicitness": "sfw|suggestive|explicit|hardcore", '
    '"nsfw": true|false, "sellable": true|false}\n'
    "Choose tags from (and beyond) this vocabulary where they apply: face, portrait, "
    "nude, topless, lingerie, bikini, outfit, ass, booty, boobs, pussy, toy, dildo, "
    "masturbation, fingering, sex, blowjob, cum, tease, shower, bath, feet, pov, solo, "
    "selfie, mirror, bed, closeup. Be literal and specific about what is actually shown. "
    "For a video the images are sampled frames — describe the overall clip."
)


_V2_SCHEMA = """{
  "description":      "<2-4 literal sentences — see RULES>",
  "beats":            ["<what happens first>", "<then>", "..."],
  "acts":             ["<from ACTS>"],
  "penetration":      "none|fingers|toy|penis|unclear",
  "insertion_depth":  "none|shallow|deep|unclear",
  "clothing_state":   "dressed|lingerie_on|pulled_aside|pulled_down|partially_off|fully_nude|unclear",
  "clothing_items":   ["<literal garments, with colour/material>"],
  "genitals_covered": true|false,
  "underwear_visible": true|false,
  "body_focus":       ["<from BODY>"],
  "position":         "<from POSITION>",
  "setting":          "<bedroom|bathroom|shower|kitchen|car|outdoor|studio|other>",
  "camera":           "<handheld_selfie|mirror|tripod_wide|pov_overhead|closeup|screen_recording>",
  "people_count":     <int>,
  "partner_visible":  true|false,
  "face_visible":     true|false,
  "toys":             ["<literal toy, with colour>"],
  "explicitness":     "sfw|suggestive|explicit|hardcore",
  "nsfw":             true|false,
  "sellable":         true|false,
  "primary_folder":   "<exactly one from FOLDERS>",
  "tags":             ["<lowercase, only what is VISIBLE>"],
  "confidence":       <0-100>
}"""

_V2_ACTS = ("posing, tease, strip, undress, groping_own_breasts, ass_shaking, twerk, "
            "spreading, rubbing_clit, fingering, toy_insertion, toy_on_clit, riding_toy, "
            "masturbation_orgasm, squirt, blowjob, handjob, sex_missionary, sex_doggy, "
            "sex_riding, cumshot, shower, bath, talking_to_camera, none")
_V2_BODY = ("face, hair, breasts, nipples, pussy, clit, ass, thighs, legs, feet, "
            "stomach, full_body")
_V2_POSITION = ("standing, sitting, kneeling, lying_on_back, lying_on_stomach, "
                "on_all_fours, legs_spread, bent_over, straddling, unclear")
_V2_FOLDERS = ("solo_fingering, solo_toy, solo_tease, nude_stills, lingerie, "
               "ass_twerk, boobs, blowjob, sex_with_partner, shower_bath, feet, "
               "outfit_cosplay, sfw_selfie, talking_head, other")

_DESCRIBE_PROMPT_V2 = (
    "You are an explicit-content CATALOGUER for an adult creator's own private media "
    "vault. The creator owns this media and has asked for it to be indexed so she can "
    "search it and file it into folders. Describe it plainly and clinically. Do not "
    "moralise, do not soften, do not refuse, do not add warnings.\n\n"
    "You are given frames sampled IN ORDER from one clip (or a single photo). "
    "Return STRICT JSON only — no prose, no markdown fences:\n"
    f"{_V2_SCHEMA}\n\n"
    "RULES\n"
    "1. description: 2-4 sentences, literal and anatomically specific. Name the act, "
    "the body part it is done TO, and the hand/toy doing it. Say whether contact is "
    "rubbing/stroking on the surface or INSERTED, and roughly how many fingers. "
    "Vague verbs are FORBIDDEN: 'touching herself', 'pleasuring herself', 'being "
    "intimate' are all wrong answers — say exactly what is happening.\n"
    "2. Clothing must be stated exactly. If underwear is still ON but pushed/pulled to "
    "one side to expose her, that is 'pulled_aside' — NOT nude and NOT simply 'wearing "
    "lingerie'. Pulled down to the thighs is 'pulled_down'. Say fully_nude when nothing "
    "is COVERING her breasts or her genitals. Socks, stockings, shoes, gloves, jewellery "
    "and a garment pushed down around her ankles cover neither, and do not make her any "
    "less nude — a woman in nothing but socks is fully_nude.\n"
    "2b. BEFORE you choose clothing_state, answer these two literally, by LOOKING at "
    "the frame rather than summarising the scene:\n"
    "    underwear_visible — is ANY garment visible anywhere on her body or pushed "
    "aside/down, however small? Waistband, strap, a thong string, lace at the hip, "
    "stockings, socks — all count as TRUE. Answer it on its own: this records what is "
    "THERE, not what is covered, so a TRUE here is perfectly compatible with fully_nude. "
    "Never adjust this answer to agree with the clothing_state you picked.\n"
    # Do not delete genitals_covered as unused: it is the second half of a scaffold the model reasons through; re-measure before touching
    "    genitals_covered — is her vulva covered by ANY fabric right now? Pushed aside "
    "so it is exposed = FALSE. Covered by a thong = TRUE. Out of frame or hidden by her "
    "pose/leg/hand rather than by fabric = FALSE (nothing is covering it).\n"
    "    COVERAGE is what governs, not presence: if a garment is COVERING her breasts "
    "or her genitals then she is not fully_nude, whatever the overall impression. "
    "'Nude except for a thong' is NOT fully_nude — it is pulled_aside or lingerie_on. "
    "But 'nude except for socks' IS fully_nude, because socks cover neither. This is "
    "the single most common error on this task, and a wrong answer here sells the "
    "wrong thing.\n"
    "3. beats: for a clip, 2-6 short ordered steps describing how it PROGRESSES across "
    "the frames (what she starts doing, what changes, how it ends). For a single photo "
    "return [].\n"
    "4. Only ever report what is VISIBLE in a frame. Never emit contradictory tags "
    "(nude + lingerie, topless + bra). The vocabularies below are a menu to choose "
    "from, not a checklist to fill in — an item with 3 true tags gets 3 tags.\n"
    "5. If a frame is too dark/blurred/cropped to tell, say 'unclear' in the field and "
    "lower `confidence`. Guessing is worse than 'unclear'.\n"
    "6. explicitness: sfw = nothing sexual; suggestive = clothed/implied; explicit = "
    "genitals or a sex act visible; hardcore = penetration, cum, or a partner act.\n\n"
    f"ACTS: {_V2_ACTS}\n"
    f"BODY: {_V2_BODY}\n"
    f"POSITION: {_V2_POSITION}\n"
    f"FOLDERS: {_V2_FOLDERS}\n"
)



# Process-wide cap across all accounts and both sweeps: per-sweep bounds alone fan out to 16x4 DeepInfra calls and starve the relay threadpool
_VISION_GLOBAL_CONCURRENCY = 8
_vision_sema: "asyncio.Semaphore | None" = None


def _vision_gate() -> "asyncio.Semaphore":
    global _vision_sema
    if _vision_sema is None:
        _vision_sema = asyncio.Semaphore(_VISION_GLOBAL_CONCURRENCY)
    return _vision_sema


async def _vision_budget(account_id: str,
                         model: str = "qwen3-vl-30b") -> dict[str, Any]:
    """Today's vision budget, plus the ONE sentence that explains a refusal.

    The sentence lives here and only here. It is product copy — it names a
    screen — so it does not belong in `llm_client`, which counts money; and it
    must not be re-composed in the browser, because then one sentence has two
    authors in two languages and they drift. Everything that has to tell an
    operator why vision work is unavailable — both sweeps, the single-item
    button, and the plan the buttons are drawn from — reads `blocked_reason`,
    which is empty exactly when nothing is blocking.
    """
    # `capped` is "no call on `model` fits" (llm_client.cap_state).
    state = await llm_client.cap_state(account_id, llm_client.DESCRIBE_BUDGET, model)
    reason = ""
    # No vision key: nothing can be described at all, so it outranks the cap.
    # The sentence is the same one the 424 carries (`key_error_payload`).
    key_missing = not await llm_client.llm_key_available(
        account_id, _VISION_PROVIDER, "describe_media")
    if key_missing:
        p = llm_client.key_error_payload(_vision_key_missing())
        reason = f"{p['message']} {p['fix']}"
    elif state["capped"]:
        reason = (f"Today's AI budget for this account is spent — "
                  f"${state['spent_millicents'] / 10000:.2f} of "
                  f"${state['cap_millicents'] / 10000:.2f}. It resets at "
                  f"midnight UTC — or ask the operator to raise the account's "
                  f"daily AI cap.")
    return {**state, "blocked_reason": reason, "key_missing": key_missing}


def _vision_key_missing() -> "llm_client.LLMKeyError":
    """The refusal a vision route raises before any frame is pulled when the
    account has no DeepInfra key — server.py answers it as the typed 424."""
    return llm_client.LLMKeyError("missing", _VISION_PROVIDER, "describe_media")


def _assert_vision_model(model: str) -> None:
    mdl = llm_client.MODELS.get(model)
    if mdl is None:
        raise HTTPException(status_code=400,
                            detail={"error": "unknown_model", "model": model})
    if not mdl.vision_ok:
        raise HTTPException(status_code=400,
                            detail={"error": "model_not_vision", "model": model})


async def _write_item(account_id: str, media_id: int, **vals: Any) -> None:
    async with get_session() as s:
        if "ai_fields_json" in vals:
            cur = (await s.execute(select(VaultItem.ai_fields_json, VaultItem.locked_fields_json).where(
                VaultItem.account_id == account_id, VaultItem.media_id == media_id).with_for_update())).first()
            if cur is not None:
                vals["ai_fields_json"] = vault_jev_pass.keep_current(
                    cur[0], vals["ai_fields_json"], set(load_json(cur[1], []) or []))
        await s.execute(
            update(VaultItem)
            .where(VaultItem.account_id == account_id, VaultItem.media_id == media_id)
            .values(**vals)
        )
        await s.commit()
    if vals.get("describe_status") == "described":
        from vault_standard_folders import after_analysis
        await after_analysis(account_id, media_id)



async def _kind(account_id: str, media_id: int) -> str | None:
    async with get_session() as s:
        return await s.scalar(select(VaultItem.kind).where(
            VaultItem.account_id == account_id, VaultItem.media_id == media_id))


async def _jev_and_flag(account_id: str, media_id: int, *, force: bool = False,
                        jev_sweep: vault_jev_pass.Sweep | None = None) -> dict[str, Any]:
    kind = await _kind(account_id, media_id)
    if kind not in JEV_KINDS:
        return {"media_id": media_id, "ok": False,
                "status": "not_in_mirror" if kind is None else "not_flaggable"}
    jev = await vault_jev_pass.checked(account_id, media_id, sweep=jev_sweep)
    if jev is None:
        return {"media_id": media_id, "ok": True, "status": "flagged", "cost_millicents": 0}
    return vault_ai_vision_decide.with_jev(
        {"media_id": media_id, "ok": jev["ok"], "status": "flagged" if jev["ok"] else jev["status"],
         **({"detail": jev["detail"]} if jev.get("detail") else {})}, jev)


_COPY_SRC_COLS = ("ai_fields_json", "describe_model", "describe_call_id", "frames_sampled",
                  "tip_vault_flag", "tags", "explicitness_tier", "description",
                  "video_description", "search_text")


async def _reuse(account_id: str, order: list[int], *, flags: bool,
                 leads: bool = False) -> tuple[ReusePlan, dict[int, list[tuple[int, str]]]]:
    plan, index = ReusePlan({}, {}), {}
    try:
        groups = await vault_dupes.reuse_groups(account_id, frozenset(order))
        set_of = {int(m): i for i, g in enumerate(groups) for m in g}
        members = sorted(set_of)
        rows = []
        async with get_session() as s:
            for i in range(0, len(members), 500):
                for mid, st, fj, kind, lj, tier in (await s.execute(
                        select(VaultItem.media_id, VaultItem.describe_status,
                               VaultItem.ai_fields_json, VaultItem.kind, VaultItem.locked_fields_json,
                               VaultItem.explicitness_tier)
                        .where(live_describable(account_id),
                               VaultItem.media_id.in_(members[i:i + 500])))).all():
                    rows.append((mid, st, load_json(fj, {}) or {}, kind, lj, tier))
            done, bad = reuse_state(rows, flags=flags, flags_version=_FLAGS_VERSION)
            plan = lead_plan(groups, order) if leads else reuse_plan(groups, order, done, bad)
            for mid, fj in (await s.execute(
                    select(VaultItem.media_id, VaultItem.ai_fields_json)
                    .where(live_describable(account_id),
                           VaultItem.ai_fields_json.like('%copied_from"%')))).all():
                f = load_json(fj, {}) or {}
                for marker in (COPY_MARK, FLAGS_COPY_MARK):
                    src = f.get(marker)
                    if src and int(mid) in set_of and set_of.get(int(src)) == set_of[int(mid)]:
                        index.setdefault(int(src), []).append((int(mid), marker))
    except Exception:  # noqa: BLE001
        log.exception("reuse plan failed account=%s — sweeping without reuse", account_id)
    if plan.copy_now or plan.followers:
        log.info("reuse account=%s flags=%s copy_now=%s followers=%s",
                 account_id, flags, len(plan.copy_now), len(plan.riders()))
    return plan, index


async def _copy_up_front(account_id: str, plan: ReusePlan, copy) -> list[dict[str, Any]]:
    return [await _copy_safe(copy, account_id, src, dst)
            for dst, src in plan.copy_now.items()]


def _propagation(index: dict[int, list[tuple[int, str]]], src: int,
                 walked: set[int], *, flags_only: bool,
                 skip: Collection[int] = ()) -> list[tuple[int, str]]:
    out = []
    for mid, marker in index.get(src, ()):
        if mid in walked or mid in skip:
            continue
        out.append((mid, "flags" if flags_only or marker == "_flags_copied_from"
                    else "describe"))
    return out


async def _copy_describe(account_id: str, src_id: int, dst_id: int) -> dict[str, Any]:
    async with get_session() as s:
        src = await s.get(VaultItem, (account_id, src_id))
        dst = await s.get(VaultItem, (account_id, dst_id))
        if src is None or dst is None:
            return {"media_id": dst_id, "ok": False, "status": "not_in_mirror"}
        if src.describe_status != "described":
            return {"media_id": dst_id, "ok": False, "status": "source_undescribed",
                    "detail": f"duplicate of {src_id}, which is not described"}
        if not vault_describe_jev.reusable(load_json(src.ai_fields_json, {}) or {}, src.kind):
            return {"media_id": dst_id, "ok": False, "status": "source_stale",
                    "detail": f"duplicate of {src_id}, whose describe was not fed the Jev reading it holds"}
        vals = build_copy_update(
            {c: getattr(src, c) for c in _COPY_SRC_COLS},
            prev_ai=load_json(dst.ai_fields_json, {}) or {},
            locked=set(load_json(dst.locked_fields_json, []) or []),
            overrides=load_json(dst.operator_overrides_json, {}) or {},
            fixable=vault_ai_fix.FIXABLE, src_id=src_id, now=datetime.utcnow())
        for k, v in vals.items():
            setattr(dst, k, v)
        await s.commit()
    from vault_standard_folders import after_analysis
    await after_analysis(account_id, dst_id)
    return {"media_id": dst_id, "ok": True, "status": "copied",
            "copied_from": src_id, "cost_millicents": 0}


async def _copy_flags(account_id: str, src_id: int, dst_id: int) -> dict[str, Any]:
    async with get_session() as s:
        src = await s.get(VaultItem, (account_id, src_id))
        dst = await s.get(VaultItem, (account_id, dst_id))
        if src is None or dst is None:
            return {"media_id": dst_id, "ok": False, "status": "not_in_mirror"}
        src_ai = load_json(src.ai_fields_json, {}) or {}
        if not flags_current(src_ai, _FLAGS_VERSION) or (
                src.kind in JEV_KINDS and not (jev_ai_read(src_ai) and vault_jev_flags.row_in_sync(
                    src_ai, src.locked_fields_json, tier=src.explicitness_tier))):
            return {"media_id": dst_id, "ok": False, "status": "source_unflagged",
                    "detail": f"duplicate of {src_id}, which has no current flags"}
        dst_locked = set(load_json(dst.locked_fields_json, []) or [])
        fields = build_flags_copy(load_json(dst.ai_fields_json, {}) or {}, src_ai, locked=dst_locked, src_id=src_id,
                                  picks=vault_jev_manual.stored(dst.operator_overrides_json))
        dst.ai_fields_json = json.dumps(fields, ensure_ascii=False, default=str)
        dst.explicitness_tier = vault_jev_flags.column_tier(fields, dst.explicitness_tier, dst_locked)
        await s.commit()
    return {"media_id": dst_id, "ok": True, "status": "flags_copied",
            "copied_from": src_id, "cost_millicents": 0}


async def _copy_safe(copy, account_id: str, src_id: int, dst_id: int) -> dict[str, Any]:
    try:
        return await copy(account_id, src_id, dst_id)
    except Exception as e:  # noqa: BLE001
        log.exception("copy %s -> %s failed account=%s", src_id, dst_id, account_id)
        return {"media_id": dst_id, "ok": False, "status": "error",
                "detail": f"{type(e).__name__}: {e}"[:200]}


async def _lead(account_id: str, mid: int, call, followers: list[int], copy,
                refresh: list[tuple[int, str]]) -> dict[str, Any]:
    try:
        res = await call
    except (llm_client.LLMKeyError, vault_sweep.SweepStop):
        raise
    except Exception as e:  # noqa: BLE001 — counted here so the riders are too
        log.exception("visit raised media=%s account=%s", mid, account_id)
        res = {"media_id": mid, "ok": False, "status": "error",
               "detail": f"{type(e).__name__}: {e}"[:200]}
    if not res.get("ok"):
        if res.get("status") == "capped" or not followers:
            return res
        return {**res, "extra": [
            {"media_id": f, "ok": False, "status": "source_failed",
             "detail": f"duplicate of {mid}, which failed ({res.get('status')})"}
            for f in followers]}
    extra = [await _copy_safe(copy, account_id, mid, f) for f in followers]
    for dst, what in refresh:
        r = await _copy_safe(_copy_describe if what == "describe" else _copy_flags,
                             account_id, mid, dst)
        if not r.get("ok"):
            log.warning("re-copy %s -> %s failed: %s", mid, dst, r.get("status"))
    return {**res, "extra": extra} if extra else res


_flags_running: set[str] = set()
_flags_progress: dict[str, dict[str, Any]] = {}
_FLAGS_CONCURRENCY = 4


async def _rail_order(account_id: str) -> list[int]:
    from vault_collect import LISTS_MAX_PAGES, LISTS_PAGE
    pages = []
    for i in range(LISTS_MAX_PAGES):
        page = await vault_cache.get(account_id, vault_cache.vault_lists_cache_key(
            view="main", limit=LISTS_PAGE, offset=i * LISTS_PAGE))
        if not isinstance(page, dict):
            break
        pages.append(page)
        if not page.get("hasMore") or not page.get("list"):
            break
    return rail_folder_ids(pages)


async def _flags_todo(account_id: str, *, force: bool = False,
                      only: set[int] | None = None, limit: int = 0) -> list[int]:
    async with get_session() as s:
        q = (select(VaultItem.media_id, VaultItem.created_at,
                    VaultItem.of_folder_ids, VaultItem.ai_fields_json, VaultItem.kind,
                    VaultItem.locked_fields_json, VaultItem.explicitness_tier)
             .where(live_describable(account_id)))
        if only:
            q = q.where(VaultItem.media_id.in_(only))
        rows = (await s.execute(q)).all()
    by_id = {int(r[0]): r for r in rows}

    todo = []
    now = datetime.utcnow()
    for mid in priority_order(((r[0], r[1], r[2]) for r in rows),
                              await _rail_order(account_id)):
        r = by_id[mid]
        f = load_json(r[3], {}) or {}
        stale = (vault_jev_pass.sweep_due(f, now)
                 or (jev_ai_read(f) and not vault_jev_flags.row_in_sync(f, r[5], tier=r[6])))
        if only or force or stale:
            todo.append(int(mid))
    return todo[:limit] if limit else todo


async def _run_flags_all(account_id: str, todo: list[int], *, force: bool = False) -> None:
    try:
        plan, index = await _reuse(account_id, todo, flags=True)
        walked = set(todo)
        settled = await _copy_up_front(account_id, plan, _copy_flags)
        jev_sweep = vault_jev_pass.Sweep()
        due = await vault_jev_pass.clips_due(account_id)

        async def visit(mid: int) -> dict[str, Any]:
            return await _lead(account_id, mid,
                               _jev_and_flag(account_id, mid, force=force, jev_sweep=jev_sweep),
                               plan.followers.get(mid, []), _copy_flags,
                               _propagation(index, mid, walked, flags_only=True))

        skip = plan.riders() | set(plan.copy_now)
        c = await vault_sweep.run(
            [m for m in todo if m not in skip], visit,
            concurrency=_FLAGS_CONCURRENCY, gate=_vision_gate,
            into=_flags_progress, key=account_id,
            label=f"flags_all account={account_id}",
            extra_total=len(plan.riders()), settled=settled,
            hold=lambda mid: vault_jev_pass.clip_lane(due, mid, jev_sweep))
        if c.failed:
            log.warning("flags_all account=%s visited=%s/%s FAILED=%s capped=%s first_error=%s",
                        account_id, c.done, c.total, c.failed, c.capped, c.error)
        else:
            log.info("flags_all done account=%s visited=%s/%s cost_mc=%s",
                     account_id, c.done, c.total, c.cost_millicents)
    except Exception:  # noqa: BLE001
        log.exception("flags_all failed account=%s", account_id)
    finally:
        _flags_running.discard(account_id)


@flags_router.post("/admin/vault-ai/flags-all")
async def flags_all(payload: dict = Body(...)) -> dict[str, Any]:
    """Run the cheap flags pass over an account's photos AND clips.

    Enrichment only: merges the three booleans into each row's existing
    `ai_fields_json` and touches nothing else. Skips items that already carry
    all of them unless `force`.

    Clips are included because the flags gate `AI-safe explicit`, the one folder
    that claims something is safe to mass-send. While clips went unflagged they
    fell into it by default — on the graded vault that meant a penetration clip and a
    dildo clip in the mass-safe folder.

    A whole-vault sweep returns `{"status": "running"}` immediately and reports
    through `/flags-all/status`. A NAMED `media_ids` set stays inline: it is a
    handful of items, and the caller (the grading probe) wants the answers back
    in the response.
    """
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    force = bool(payload.get("force"))
    limit = int(payload.get("limit") or 0)
    only = payload.get("media_ids")
    only = {int(m) for m in only} if isinstance(only, (list, tuple, set)) else None
    from vault_ai_api import assert_media_visible, assert_owner_scope
    if only:
        await assert_media_visible(account_id, *only)
    else:
        await assert_owner_scope(account_id)

    todo = await _flags_todo(account_id, force=force, only=only, limit=limit)

    if only:
        done, failed, cost = 0, 0, 0
        stop = None
        jev_sweep = vault_jev_pass.Sweep()
        plan, _index = await _reuse(account_id, todo, flags=True, leads=True)
        for mid in todo:
            try:
                res = await _lead(account_id, mid,
                                  _jev_and_flag(account_id, mid, force=True, jev_sweep=jev_sweep),
                                  plan.followers.get(mid, []), _copy_flags, [])
            except vault_sweep.SweepStop as e:
                failed += 1
                stop = e.payload()
                break
            if res.get("ok"):
                done += 1
                cost += int(res.get("cost_millicents") or 0)
            else:
                failed += 1
        return {"account_id": account_id, "candidates": len(todo),
                "flagged": done, "failed": failed, "cost_millicents": cost,
                "prompt_version": _FLAGS_VERSION, "stop": stop,
                "complete": failed == 0 and done == len(todo)}

    if not claim_flags(account_id):
        return {"account_id": account_id, "status": "running",
                "candidates": len(todo), "already": True,
                "prompt_version": _FLAGS_VERSION}
    asyncio.create_task(_run_flags_all(account_id, todo, force=force))
    return {"account_id": account_id, "status": "running",
            "candidates": len(todo), "already": False,
            "prompt_version": _FLAGS_VERSION}


@flags_router.get("/admin/vault-ai/flags-all/status")
async def flags_all_status(account_id: str = Query(...)) -> dict[str, Any]:
    """Progress of the background sweep, plus coverage read from the DB.

    Two numbers on purpose. `progress` is this process's live counter and dies
    with a restart; `coverage` is the durable truth, so a UI that reconnects
    after a redeploy still shows where the vault actually stands instead of
    starting over at nothing.
    """
    assert_account_owned(account_id)
    from vault_ai_api import assert_owner_scope
    await assert_owner_scope(account_id)
    return {
        "account_id": account_id,
        "running": account_id in _flags_running,
        "progress": _flags_progress.get(account_id),
        "coverage": await vault_scripts.flags_coverage(account_id),
    }



async def _describe_one(account_id: str, media_id: int, model: str = "qwen3-vl-30b",
                        prompt_version: str = "v2",
                        frames: int | None = None,
                        jev_res: Mapping[str, Any] | None = None) -> dict[str, Any]:
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
    if item is None:
        raise HTTPException(status_code=404, detail={"error": "not_in_mirror", "media_id": media_id})
    # OF deleted it after a sweep picked it: no cached frame, no paid call
    if item.removed_at is not None:
        return {"media_id": media_id, "ok": False, "status": "gone",
                "detail": "removed from OF since the sweep picked it — not described"}
    prev_ai = load_json(item.ai_fields_json, {}) or {}
    path, jev = vault_describe_jev.route(kind=item.kind, fields=prev_ai)
    if path is None:
        j = prev_ai.get(JEV_KEY) if isinstance(prev_ai.get(JEV_KEY), dict) else {}
        if jev_res and not jev_res.get("ok"):
            why = jev_res.get("status")
        else:
            why = j.get("status") if j.get("status") not in (None, "ok") else "jev_missing"
        if reason := vault_jev_rules.stop_reason(prev_ai):
            return {"media_id": media_id, "ok": False, "status": reason,
                    "detail": vault_jev_rules.STOP_DETAILS[reason]}
        return {"media_id": media_id, "ok": False, "status": why,
                "detail": f"no Jev reading for this {item.kind} ({why}) — skipped, retried by a later sweep"}
    raw = load_json(item.raw_json, {}) or {}
    want = int(frames) if frames else _frames_for_duration(item.duration_seconds)
    got = await vault_frames.collect(account_id, item, raw, want=want)
    if not got.images:
        status = vault_frames.NO_IMAGE_STATUS.get(got.reason, "fetch_failed")
        await _write_item(account_id, media_id, describe_status=status,
                          describe_generated_at=datetime.utcnow())
        # `detail` is what the sweep shows the operator as `first_error`. Without
        # it a whole vault failing on a frame bug reads as "1,777 could not be
        # described" and nothing else — a failure count with no cause is the same
        # shape as the missing-provider-key incident this row's status was added
        # for. `got.detail` carries the exception when `collect` swallowed one.
        return {"media_id": media_id, "ok": False, "status": status,
                "detail": got.detail or f"no frames ({status})"}

    images = list(got.images)
    if jev is not None:
        px = vault_describe_jev.PX.get(path)
        if px:
            images = [await asyncio.to_thread(vision.shrink_data_url, u, px) for u in images]
        prompt = vault_describe_jev.prompt_for(path, jev, _DESCRIBE_PROMPT_V2)
    else:
        prompt = _DESCRIBE_PROMPT if prompt_variant(prompt_version) == "v1" else _DESCRIBE_PROMPT_V2
    content = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": u}} for u in images]

    # Try 30b; on refusal/blank escalate ONCE to 235b (`next_attempt`).
    # Every attempt that answered was paid for, so the cost is their SUM — a
    # refused 30b call followed by a 235b answer used to report only the 235b.
    result = None
    used_model = model
    data: dict[str, Any] = {}
    cost = 0
    attempt_model: str | None = model
    while attempt_model:
        try:
            result = await llm_client.chat(
                model=attempt_model,
                messages=[{"role": "user", "content": content}],
                purpose="describe_media",
                account_id=account_id,
                temperature=0.1,
            )
        except LLMCapExceeded as e:
            # Deliberately leaves describe_status alone: "capped" means try again
            # later, and stamping a status would make the retry sweep skip it.
            # `detail` is what an operator reads, both here and in the sweep's
            # first_error, so it carries the same sentence the pre-flight
            # refusal does rather than the exception's own developer text.
            # `cost` is non-zero when a paid 30b refusal came before this.
            budget = await _vision_budget(account_id, attempt_model)
            return {"media_id": media_id, "ok": False, "status": "capped",
                    "detail": budget["blocked_reason"] or str(e),
                    "cost_millicents": cost}
        except llm_client.LLMKeyError:
            # The key, not the item: leave describe_status alone (like capped)
            # so the item is retried once a key is added, and let the caller
            # tell the owner — a 424 on the route, a stop in the sweep.
            raise
        except LLMError as e:
            # RECORD the failure. Leaving the status NULL made a failed item
            # indistinguishable from one never attempted — a missing
            # DEEPINFRA_API_KEY failed all 327 items of a vault while the UI
            # reported "done 327/327" and the row stayed blank.
            await _write_item(account_id, media_id, describe_status="failed",
                              describe_model=attempt_model,
                              describe_generated_at=datetime.utcnow())
            return {"media_id": media_id, "ok": False, "status": "error",
                    "detail": str(e)[:300], "cost_millicents": cost}
        cost += int(result.cost_cents or 0)
        used_model = attempt_model
        if not vision.is_refusal(result.content):
            parsed = _parse_describe(result.content)
            if vault_describe_jev.answered(path, parsed):
                data = parsed
        attempt_model = next_attempt(attempt_model, not data)

    # `data` is only ever `{}` or an answer that carries a description or tags.
    if not data:
        await _write_item(account_id, media_id, describe_status="refused",
                          describe_model=used_model,
                          describe_call_id=(result.call_id if result else None),
                          describe_generated_at=datetime.utcnow())
        return {"media_id": media_id, "ok": False, "status": "refused",
                "raw": (result.content if result else "" or "")[:200],
                "cost_millicents": cost}

    had_prose = bool(str(data.get("description") or "").strip())
    data = vault_describe_jev.answer(path, data, jev)
    if had_prose and not str(data.get("description") or "").strip():
        await _write_item(account_id, media_id, describe_status="refused", describe_model=used_model,
                          describe_call_id=(result.call_id if result else None),
                          describe_generated_at=datetime.utcnow())
        return {"media_id": media_id, "ok": False, "status": "refused",
                "detail": "every sentence of the description contradicted the Jev reading; prior kept",
                "cost_millicents": cost}
    data = {**data, vault_describe_jev.DESCRIBE_KEY: vault_describe_jev.meta(path, jev, used_model)}

    locked = set(load_json(item.locked_fields_json, []))
    vals = build_describe_update(
        item.kind == "video", data,
        prev_ai=prev_ai, locked=locked,
        overrides=load_json(item.operator_overrides_json, {}) or {},
        used_model=used_model, n_frames=len(got.images), pv=prompt_version,
        fixable=vault_ai_fix.FIXABLE,
        call_id=result.call_id if result else None, now=datetime.utcnow())

    await _write_item(account_id, media_id, **vals)
    return {
        "media_id": media_id, "ok": True, "status": "described",
        **describe_answer(data),
        "describe_model": used_model,
        "cost_millicents": cost,
        "images_sent": len(got.images),
    }


async def _describe_and_flag(account_id: str, media_id: int, *,
                             jev_sweep: vault_jev_pass.Sweep | None = None,
                             **describe_kw: Any) -> dict[str, Any]:
    kind = await _kind(account_id, media_id)
    jev = await vault_jev_pass.checked(account_id, media_id, sweep=jev_sweep) if kind in JEV_KINDS else None
    res = await _describe_one(account_id, media_id, jev_res=jev, **describe_kw)
    return vault_ai_vision_decide.with_jev(res, jev)


@describe_router.post("/admin/vault-ai/describe")
async def describe_one(payload: dict = Body(...)) -> dict[str, Any]:
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    try:
        media_id = int(payload.get("media_id"))
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": "media_id_required"})
    from vault_ai_api import assert_media_visible
    await assert_media_visible(account_id, media_id)
    # Over the cap the LLM call is refused anyway, but only AFTER the frames
    # have been pulled off OF and (for a clip) cut with ffmpeg. Answering here
    # keeps a hopeless click cheap, and keeps "Describe selected" from grinding
    # through fifty items' worth of fetches to write nothing. Same shape the
    # in-flight refusal returns, so a caller has one case to handle.
    model = str(payload.get("model") or "qwen3-vl-30b")
    _assert_vision_model(model)  # this route validated NOTHING before
    budget = await _vision_budget(account_id, model)
    if budget["key_missing"]:
        raise _vision_key_missing()
    if budget["capped"]:
        return {"media_id": media_id, "ok": False, "status": "capped",
                "detail": budget["blocked_reason"]}
    plan, _index = await _reuse(account_id, [media_id], flags=False, leads=True)
    res = await _lead(
        account_id, media_id,
        _describe_and_flag(account_id, media_id, model=model,
                           prompt_version=str(payload.get("prompt_version") or "v2"),
                           frames=payload.get("frames")),
        plan.followers.get(media_id, []), _copy_describe, [])
    if res.get("extra"):
        from vault_ai_api import visible_ids
        seen = await visible_ids(account_id, [e["media_id"] for e in res["extra"]])
        res = {**res, "extra": [e for e in res["extra"] if e["media_id"] in seen]}
    return res


_describe_running: set[str] = set()
_describe_progress: dict[str, dict[str, Any]] = {}
# Describe latency is ~24 tok/s of output (~14 s/item), so throughput only scales with parallelism; the global gate still caps total at 8
_DESCRIBE_CONCURRENCY = 8


async def _run_describe_all(account_id: str, mode: DescribeMode,
                            prompt_version: str = "v2",
                            model: str = "qwen3-vl-30b", limit: int = 0,
                            target: int = 0) -> None:
    """Background describe sweep over the rows `describe_selection(mode)` picks
    (the modes are documented there); `limit` > 0 walks only the first `limit`
    of them in priority order. `target` > 0 (mode "undescribed"): the Describe
    target — Terminal failures are skipped (walked and copied to never) and the
    walk is cut to `coverage`'s remaining, then to `limit`."""
    try:
        async with get_session() as s:
            walked = {int(r[0]) for r in (await s.execute(select(VaultItem.media_id).where(
                describe_selection(account_id, mode, prompt_version)))).all()}
            rows = (await s.execute(
                select(VaultItem.media_id, VaultItem.created_at, VaultItem.of_folder_ids)
                .where(live_describable(account_id)))).all()
        terminal: set[int] = set()
        remaining = 0
        if target > 0:
            cov_rows = await _coverage_rows(account_id)
            terminal = {mid for mid, st, f in cov_rows if is_terminal(st, f)}
            remaining = coverage(((st, f) for _m, st, f in cov_rows), target)["remaining"]
        ids = [m for m in priority_order(rows, await _rail_order(account_id))
               if m in walked and m not in terminal]
        if target > 0:
            ids = ids[:remaining]
            walked = set(ids)
        if limit > 0:
            ids = ids[:limit]
            walked = set(ids)
        plan, index = await _reuse(account_id, ids, flags=False)
        settled = await _copy_up_front(account_id, plan, _copy_describe)
        jev_sweep = vault_jev_pass.Sweep()
        due = await vault_jev_pass.clips_due(account_id)

        async def visit(mid: int) -> dict[str, Any]:
            return await _lead(
                account_id, mid,
                _describe_and_flag(account_id, mid, model=model,
                                   prompt_version=prompt_version, jev_sweep=jev_sweep),
                plan.followers.get(mid, []), _copy_describe,
                _propagation(index, mid, walked, flags_only=False, skip=terminal))

        skip = plan.riders() | set(plan.copy_now)
        c = await vault_sweep.run(
            [m for m in ids if m not in skip], visit,
            concurrency=_DESCRIBE_CONCURRENCY,
            gate=_vision_gate, into=_describe_progress, key=account_id,
            label=f"describe_all account={account_id}",
            extra_total=len(plan.riders()), settled=settled,
            hold=lambda mid: vault_jev_pass.clip_lane(due, mid, jev_sweep))
        try:
            q = await vault_ai_fix.review_queue(account_id, limit=1,
                                                version=_FLAGS_VERSION,
                                                only_iffy=True)
            _describe_progress[account_id] = {
                **_describe_progress.get(account_id, {}), "needs_review": q["iffy"]}
        except Exception:  # noqa: BLE001
            log.exception("review count after describe failed account=%s", account_id)
        if c.failed:
            log.warning("describe_all account=%s done=%s/%s FAILED=%s capped=%s first_error=%s",
                        account_id, c.done, c.total, c.failed, c.capped, c.error)
        else:
            log.info("describe_all done account=%s done=%s/%s capped=%s",
                     account_id, c.done, c.total, c.capped)
    except Exception as e:  # noqa: BLE001
        log.exception("describe_all failed account=%s", account_id)
        _describe_progress[account_id] = {
            **_describe_progress.get(account_id, {}),
            "aborted": True, "error": f"{type(e).__name__}: {e}"[:200],
        }
    finally:
        _describe_running.discard(account_id)


def claim_flags(account_id: str) -> bool:
    if account_id in _flags_running:
        return False
    _flags_running.add(account_id)
    return True


async def _claim_describe(account_id: str, model: str) -> dict[str, Any]:
    if account_id in _describe_running:
        raise HTTPException(status_code=409, detail={"error": "describe_already_running"})
    _describe_running.add(account_id)
    try:
        _assert_vision_model(model)
        budget = await _vision_budget(account_id, model)
        if budget["key_missing"]:
            raise _vision_key_missing()
        if budget["capped"]:
            raise HTTPException(status_code=429,
                                detail={"error": "daily_cap_reached", **budget})
    except BaseException:
        _describe_running.discard(account_id)
        raise
    return budget


DESCRIBE_MAX_DEFAULT = 2000


def _limit_of(raw: Any, target: int) -> int:
    if raw == "all":
        return 0
    if raw is None:
        return 0 if target else DESCRIBE_MAX_DEFAULT
    if isinstance(raw, str) and raw.strip().isdecimal():
        try:
            raw = int(raw.strip())
        except ValueError:
            raw = None
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 1:
        return raw
    raise HTTPException(status_code=400, detail={"error": "bad_limit"})


def _target_of(raw: Any) -> int:
    if raw is None:
        return 0
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 1:
        return raw
    raise HTTPException(status_code=400, detail={"error": "bad_target"})


async def _coverage_rows(account_id: str) -> list[tuple[int, str | None, dict[str, Any] | None]]:
    terminal_candidate = and_(
        VaultItem.describe_status.isnot("described"),
        or_(*(VaultItem.ai_fields_json.contains(marker) for marker in vault_jev_rules.TERMINAL_MARKERS)),
    )
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem.media_id, VaultItem.describe_status,
                   case((terminal_candidate, VaultItem.ai_fields_json), else_=None))
            .where(live_describable(account_id)))).all()
    return [(int(m), st, load_json(fj, {}) if fj else None) for m, st, fj in rows]


async def describe_coverage(account_id: str, target: int) -> dict[str, int]:
    return coverage(((st, f) for _m, st, f in await _coverage_rows(account_id)), target)


@describe_router.post("/admin/vault-ai/describe-all")
async def describe_all(payload: dict = Body(...)) -> dict[str, Any]:
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    from vault_ai_api import assert_owner_scope
    await assert_owner_scope(account_id)
    model = str(payload.get("model") or "qwen3-vl-30b")
    force = bool(payload.get("force"))
    restage = bool(payload.get("restage"))
    target = _target_of(payload.get("target"))
    limit = _limit_of(payload.get("limit"), target)
    if target and (force or restage):
        raise HTTPException(status_code=400, detail={"error": "target_needs_undescribed"})
    _assert_vision_model(model)
    if target:
        remaining = (await describe_coverage(account_id, target))["remaining"]
        if remaining == 0:
            return {"account_id": account_id, "status": "done",
                    "target": target, "target_remaining": 0}
    await _claim_describe(account_id, model)
    mode: DescribeMode = "force" if force else ("restage" if restage else "undescribed")
    prompt_version = prompt_variant(payload.get("prompt_version"))
    asyncio.create_task(_run_describe_all(account_id, mode,
                                          prompt_version=prompt_version,
                                          model=model, limit=limit, target=target))
    out = {"account_id": account_id, "status": "running",
           "prompt_version": prompt_version, "model": model,
           "force": force, "restage": restage, "limit": limit}
    if target:
        out.update(target=target, target_remaining=remaining)
    return out


@describe_router.get("/admin/vault-ai/describe-all/plan")
async def describe_all_plan(
    account_id: str = Query(...),
    prompt_version: str = Query("v2"),
    target: str | None = None,
) -> dict[str, Any]:
    """What each sweep mode WOULD do, so the UI can show real counts (and a cost
    estimate) before the operator commits to a re-scan of the whole vault.
    `?target=` adds `target_remaining` (what a target sweep walks) and the
    `coverage` counts."""
    assert_account_owned(account_id)
    from vault_ai_api import assert_owner_scope
    await assert_owner_scope(account_id)
    goal = _target_of(int(target) if target is not None and target.strip().isdecimal() else target)
    pv = prompt_variant(prompt_version)
    async with get_session() as s:
        def _count(mode: DescribeMode):
            return (select(func.count()).select_from(VaultItem)
                    .where(describe_selection(account_id, mode, pv)))
        total = await s.scalar(_count("force"))
        undescribed = await s.scalar(_count("undescribed"))
        stale = await s.scalar(_count("restage"))
    # Carried so the button can go grey BEFORE it is pressed, with the reason
    # already on it. The POST refuses over the cap either way, but a disabled
    # button that says why is the difference between "out of budget until
    # midnight" and "broken".
    budget = await _vision_budget(account_id)
    out = {"account_id": account_id, "prompt_version": pv,
           "total": int(total or 0),
           "undescribed": int(undescribed or 0),
           "restage": int(stale or 0),
           "cap": budget,
           "jev": await vault_jev_pass.plan(account_id)}
    if goal:
        cov = await describe_coverage(account_id, goal)
        out.update(target=goal, target_remaining=cov["remaining"], coverage=cov)
    return out


@describe_router.get("/admin/vault-ai/describe-all/status")
async def describe_all_status(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    from vault_ai_api import assert_owner_scope
    await assert_owner_scope(account_id)
    prog = _describe_progress.get(account_id)
    return {
        "account_id": account_id,
        "running": account_id in _describe_running,
        "progress": prog,
    }
