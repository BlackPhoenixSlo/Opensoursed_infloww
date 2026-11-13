"""service/vault_ai_vision.py — the vision passes over the vault mirror.

Split out of `vault_ai_api` (routes unchanged): the FLAGS pass (`_jev_and_flag`,
`flags-all`) and the DESCRIBE pass (`_describe_one`, `describe`,
`describe-all`), plus the vision budget and the process-wide vision gate they
share. Pure decisions live in `vault_ai_vision_decide`.

Two routers, one per block, because `vault_ai_api` includes each at the spot the
block used to occupy — FastAPI matches routes in registration order. This module
never imports `vault_ai_api` (one-way dependency, no cycle).

Tests patch `vault_ai_vision._describe_one` /
`_DESCRIBE_CONCURRENCY` — the names are looked up HERE. The Jev v8 wiring
lives in `vault_jev_pass` (patch `vault_jev_pass.safe` / `plan`).

Jev v8 is the default for every PHOTO and CLIP — its pass stamps the item's
flags (`vault_jev_flags`) and feeds its describe (`vault_describe_jev`: photos
prose / v6; clips "vid", the V2 describe + Jev facts). An item Jev cannot read
(no NudeNet / key, capped, error, no frames) is skipped and retried by the next
sweep, never described or flagged without it. There is no qwen flags call
(D52/D54): photos and clips are the only describable kinds.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Mapping

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import func, select, update

import llm_client
import vault_ai_brief
import vault_ai_fix
import vault_ai_vision_decide  # module attr `with_jev`, looked up per call
import vault_describe_jev
import vault_dupes  # module attr `reuse_groups`, looked up per call
import vault_frames
import vault_jev_flags
import vault_jev_manual
import vault_jev_pass  # module attrs `safe` / `plan`, looked up per call
import vault_scripts
import vault_sweep
import vision  # shared frame download / shrink / refusal test
from auth import assert_account_owned
from db.engine import get_session
from db.models import VaultItem
from jsonsafe import load_json
from llm_client import LLMCapExceeded, LLMError
from vault_jev_rules import JEV_KINDS, ai_read as jev_ai_read
from vault_ai_vision_decide import (
    DescribeMode, _frames_for_duration, _parse_describe,
    COPY_MARK, FLAGS_COPY_MARK, JEV_KEY, ReusePlan, build_copy_update, build_describe_update,
    build_flags_copy, describe_answer, describe_selection, flags_current,
    live_describable, next_attempt, priority_order, prompt_variant, reuse_plan, reuse_state,
)

# Same logger name as before the split, so log routing/filters are unchanged.
log = logging.getLogger("of-relay.vault_ai_api")

flags_router = APIRouter()
describe_router = APIRouter()


# ── Constants & prompts ─────────────────────────────────────────────

# Every describe/flags call goes to this provider, and the daily cap is held
# per-(account, provider) — so this one row IS the budget a vision sweep spends.
_VISION_PROVIDER = "deepinfra"


# The flags version stamped on every row's flags (`vault_jev_flags` stamps it): defined, with its
# history, in `vault_ai_brief.FLAGS_VERSION`.
_FLAGS_VERSION = vault_ai_brief.FLAGS_VERSION


# ── Describe prompts (Qwen3-VL vision) ──────────────────────────────

# Proven prompt (service/_probe_vault_describe.py — 8/8 described, 0 refused, correct NSFW tags).
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


# ── V2 describe prompt (bake-off variant B, chosen 2026-07-21) ──────
#
# Measured over 12 real items x 3 variants (service/_probe_describe_v2.py):
# V2@9 frames on qwen3-vl-30b beat the V1 prompt decisively and cost $0.88 for a
# 2,309-item vault, with 235B kept in the harness for later. V1 above is left in
# place as the cheap baseline and as what the harness diffs against.
#
# The four changes over V1, each aimed at a measured failure:
#  1. Ownership/consent framing — V1 gave the model no reason not to sanitise,
#     which is how a clip with fingers inside became "touching her genitals".
#  2. An explicit anti-euphemism rule naming that exact failure mode.
#  3. `beats` — an ordered walk across the sampled frames, so a 2-minute clip
#     stops collapsing into one static sentence.
#  4. A CLOSED taxonomy instead of free tag soup. V1's free vocabulary let it
#     emit `nude` + `lingerie` + `topless` on the SAME item — 78% of the graded vault's rows
#     carry a contradiction like that, which is why nothing downstream could
#     order a script. `clothing_state` and `acts` are single-valued rungs, and
#     they are what service/vault_scripts.py scores.
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
    # `genitals_covered` is asked for and then DELETED by the flags pass, which
    # superseded it with the three-state `vulva_vis`. It stays because it is not
    # an output — it is the second half of a scaffold the model reasons through
    # before committing to a state. Deleting it as "unused" is a prompt change
    # wearing the costume of a cleanup; re-measure before touching it.
    #
    # What this scaffold used to do was WORSE than nothing. It asserted that a
    # visible garment rules out `fully_nude`, which is false: measured against an
    # operator's own labels on 10 explicit stills (2026-08-05), 6 items were
    # `fully_nude` WITH a garment visible — a nude woman in socks. Every model
    # answer that reported `underwear_visible=True` was wrong about the state
    # (0/8); every answer that reported False was right 19/22. The models were
    # resolving the contradiction by suppressing `underwear_visible` — a
    # `FLAG_KEY` the pricing tiers read. The rule poisoned the field it was
    # built on. Presence and coverage are now asked as the separate questions
    # they always were.
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


# ── Vision budget + process-wide gate ───────────────────────────────

# Process-wide ceiling on concurrent vision work across ALL accounts and BOTH
# sweeps (describe + flags). The per-sweep _DESCRIBE_CONCURRENCY/_FLAGS_CONCURRENCY
# bound ONE sweep; without a shared gate, kicking "Describe all" on 16 accounts
# fans out to 16×4 = 64 concurrent DeepInfra calls plus their ffmpeg/OF frame
# fetches and starves the relay threadpool (cost-audit finding: ReadTimeouts +
# 500s while sweeps run). Lazily created so it binds to the running event loop,
# not import time.
_VISION_GLOBAL_CONCURRENCY = 8
_vision_sema: "asyncio.Semaphore | None" = None


def _vision_gate() -> "asyncio.Semaphore":
    """The process-wide vision-concurrency gate (see _VISION_GLOBAL_CONCURRENCY).
    Every describe/flags sweep acquires this IN ADDITION to its per-sweep bound, so
    total concurrent vision work is capped no matter how many accounts sweep at once."""
    global _vision_sema
    if _vision_sema is None:  # single-threaded asyncio: check→set is atomic (no await)
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
    state = await llm_client.cap_state(account_id, _VISION_PROVIDER, model)
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
    """Refuse a model that is not cleared to be handed an image.

    These routes take a model id straight off the request body, and the model
    list an operator picks from is derived server-side from `llm_client.MODELS`
    — so every model registered for ANY purpose is offerable the moment it
    lands, including the text-only ones. The old check here tested membership,
    which answers "is this a model" and not "is this a model for this job".

    `vision_ok` is that second question. Answering it up front also keeps the
    failure cheap: a text model reaching `_describe_one` would first pull frames
    off OF and cut a clip with ffmpeg, then spend the LLM call, and only then
    find out.
    """
    mdl = llm_client.MODELS.get(model)
    if mdl is None:
        raise HTTPException(status_code=400,
                            detail={"error": "unknown_model", "model": model})
    if not mdl.vision_ok:
        raise HTTPException(status_code=400,
                            detail={"error": "model_not_vision", "model": model})


async def _write_item(account_id: str, media_id: int, **vals: Any) -> None:
    """UPDATE one vault_items row with `vals` and commit. A new `ai_fields_json`
    keeps the row's CURRENT `_jev` (`vault_jev_pass.keep_current`): the blob was
    built from a read taken before a describe / flags call, and a Jev pass from
    the other sweep may have landed meanwhile."""
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


# ── Flags: the Jev pass (photos and clips) ──────────────────────────

async def _kind(account_id: str, media_id: int) -> str | None:
    async with get_session() as s:
        return await s.scalar(select(VaultItem.kind).where(
            VaultItem.account_id == account_id, VaultItem.media_id == media_id))


async def _jev_and_flag(account_id: str, media_id: int, *, force: bool = False,
                        jev_sweep: vault_jev_pass.Sweep | None = None) -> dict[str, Any]:
    """The flags sweep's visit. A photo or clip: the Jev pass, which stamps its
    flags (nothing to pay for when `_jev` is AI-read (`ai_read`): its flags are re-stamped
    if they drifted). `force` never forces a paid Jev re-run. A Jev cap is that
    item's failure (`jev_capped`), not the sweep's stop (`capped`)."""
    kind = await _kind(account_id, media_id)
    if kind not in JEV_KINDS:   # no qwen flags call: a missing row / another kind is not flaggable
        return {"media_id": media_id, "ok": False,
                "status": "not_in_mirror" if kind is None else "not_flaggable"}
    jev = await vault_jev_pass.safe(account_id, media_id, sweep=jev_sweep)
    if jev is None:       # `_jev` already AI-read: its flags re-stamped if they drifted, nothing paid
        return {"media_id": media_id, "ok": True, "status": "flagged", "cost_millicents": 0}
    return vault_ai_vision_decide.with_jev(
        {"media_id": media_id, "ok": jev["ok"], "status": "flagged" if jev["ok"] else jev["status"],
         **({"detail": jev["detail"]} if jev.get("detail") else {})}, jev)


# ── Answer reuse across duplicates (both sweeps) ────────────────────
# A re-upload is the same picture: one vision call answers the whole set
# (`vault_dupes.reuse_groups` — the Duplicates screen's sets at threshold 2).
# Copies are free, are made the moment their source is written (a cap mid-sweep
# keeps them), carry the source's flags version (so the flags sweep leaves them
# alone) and are stamped `_copied_from` / `_flags_copied_from`, which is how a
# later re-describe / re-flag of the SWEEP re-copies them.
# Not covered (follow-ups):
#   * an operator fix (`vault_ai_fix`) on a source does not propagate;
#   * the single-item describe route and flags-all with `media_ids` write the
#     item only — its marked copies refresh on the next sweep that answers it;
#   * a copy whose set has two sources answered in one sweep may take either
#     one's answer (last write wins). Same picture, so accepted.
_COPY_SRC_COLS = ("ai_fields_json", "describe_model", "describe_call_id", "frames_sampled",
                  "tip_vault_flag", "tags", "explicitness_tier", "description",
                  "video_description", "search_text")


async def _reuse(account_id: str, order: list[int], *,
                 flags: bool) -> tuple[ReusePlan, dict[int, list[tuple[int, str]]]]:
    """This sweep's `ReusePlan` over `order`, and the index of rows earlier
    sweeps marked as copies ({source: [(copy, marker)]}). Never raises: no
    duplicates is the fallback for every failure. A photo is a source only on
    its current `_jev` (`reuse_state`)."""
    plan, index = ReusePlan({}, {}), {}
    try:
        groups = await vault_dupes.reuse_groups(account_id, frozenset(order))
        members = sorted({int(m) for g in groups for m in g})
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
            plan = reuse_plan(groups, order, done, bad)
            for mid, fj in (await s.execute(
                    select(VaultItem.media_id, VaultItem.ai_fields_json)
                    .where(live_describable(account_id),
                           VaultItem.ai_fields_json.like('%copied_from"%')))).all():
                f = load_json(fj, {}) or {}
                for marker in (COPY_MARK, FLAGS_COPY_MARK):
                    if f.get(marker):
                        index.setdefault(int(f[marker]), []).append((int(mid), marker))
    except Exception:  # noqa: BLE001
        log.exception("reuse plan failed account=%s — sweeping without reuse", account_id)
    if plan.copy_now or plan.followers:
        log.info("reuse account=%s flags=%s copy_now=%s followers=%s",
                 account_id, flags, len(plan.copy_now), len(plan.riders()))
    return plan, index


async def _copy_up_front(account_id: str, plan: ReusePlan, copy) -> list[dict[str, Any]]:
    """Make every `copy_now` copy BEFORE the walk: free, so outside the vision
    gate and safe from a cap trip. The results ride into `vault_sweep.run` as
    `settled`."""
    return [await _copy_safe(copy, account_id, src, dst)
            for dst, src in plan.copy_now.items()]


def _propagation(index: dict[int, list[tuple[int, str]]], src: int,
                 walked: set[int], *, flags_only: bool) -> list[tuple[int, str]]:
    """Earlier copies of `src` to refresh once it is re-answered: (copy, what to
    copy). Rows this sweep walks itself are left to it."""
    out = []
    for mid, marker in index.get(src, ()):
        if mid in walked:
            continue
        out.append((mid, "flags" if flags_only or marker == "_flags_copied_from"
                    else "describe"))
    return out


async def _copy_describe(account_id: str, src_id: int, dst_id: int) -> dict[str, Any]:
    """Give `dst_id` the describe + flags answer `src_id` carries. No call."""
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
    return {"media_id": dst_id, "ok": True, "status": "copied",
            "copied_from": src_id, "cost_millicents": 0}


async def _copy_flags(account_id: str, src_id: int, dst_id: int) -> dict[str, Any]:
    """Merge `src_id`'s current flags into `dst_id`. No call."""
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
    """A copy that raised is that copy's failure, not its source's."""
    try:
        return await copy(account_id, src_id, dst_id)
    except Exception as e:  # noqa: BLE001
        log.exception("copy %s -> %s failed account=%s", src_id, dst_id, account_id)
        return {"media_id": dst_id, "ok": False, "status": "error",
                "detail": f"{type(e).__name__}: {e}"[:200]}


async def _lead(account_id: str, mid: int, call, followers: list[int], copy,
                refresh: list[tuple[int, str]]) -> dict[str, Any]:
    """Run `mid`'s own (paid) visit; on success copy it to `followers` — counted
    as `extra` items of this visit — and refresh earlier copies (`refresh`,
    uncounted: they are outside this sweep's set). A failed leader's followers
    are counted failed and stay undescribed; the next sweep picks a different
    leader (`reuse_plan`'s `bad`). A capped one's are left uncounted, like
    every item a cap cuts off."""
    try:
        res = await call
    except llm_client.LLMKeyError:
        raise  # stops the sweep; its riders go uncounted like a cap's
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


# ── Flags sweep (background, same shape as describe-all) ────────────
# A whole-vault sweep CANNOT run inside its own request. 327 items × ~3.4s is
# ~18 minutes; the app's proxy drops the socket long before that and the browser
# is shown "Internal Server Error" — while the sweep carries on server-side,
# invisible, so every retry click starts ANOTHER concurrent sweep over the same
# rows. `describe-all` has always been a background task with a status endpoint;
# this was the odd one out.
_flags_running: set[str] = set()
_flags_progress: dict[str, dict[str, Any]] = {}
# Same bound as describe. The pass is IO-bound on one small VLM call per item,
# so 4 at a time turns ~18 minutes into ~5 without changing what is asked.
_FLAGS_CONCURRENCY = 4


async def _flags_todo(account_id: str, *, force: bool = False,
                      only: set[int] | None = None, limit: int = 0) -> list[int]:
    """Which items still need flags, in `priority_order` — the describe sweep's
    order. Flags are what the gated lanes actually read, so a describe and a
    flags pass that walked the vault differently would leave freshly-described
    items describable but still unusable."""
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
    for mid in priority_order((r[0], r[1], r[2]) for r in rows):
        r = by_id[mid]
        f = load_json(r[3], {}) or {}
        if r[4] in JEV_KINDS:
            # A photo's / clip's flags are its `_jev`'s: work when either is missing / stale.
            # Operator picks alone (no Jev reading yet) still need the scan.
            stale = not vault_jev_flags.row_in_sync(f, r[5], tier=r[6]) or not jev_ai_read(f)
        else:
            # `flags_known`, not a key-presence test: a row carrying the superseded
            # boolean shape, or a region the model answered with something outside
            # the enum, has not really been flagged and must re-run. A row produced
            # by an OLDER prompt is stale for the same reason — its answers were
            # given to a different question.
            stale = not flags_current(f, _FLAGS_VERSION)
        if only or force or stale:
            todo.append(int(mid))
    return todo[:limit] if limit else todo


async def _run_flags_all(account_id: str, todo: list[int], *, force: bool = False) -> None:
    """Background flags sweep. Resumable by construction: it only ever visits
    rows that are missing or stale, so a relay restart mid-sweep costs the items
    in flight and nothing else — pressing the button again picks up the rest.

    Duplicates (`_reuse`) cost one call per set: the rest copy its flags."""
    try:
        plan, index = await _reuse(account_id, todo, flags=True)
        walked = set(todo)
        settled = await _copy_up_front(account_id, plan, _copy_flags)
        jev_sweep = vault_jev_pass.Sweep()
        due = await vault_jev_pass.clips_due(account_id)   # clips that queue for the Jev video lane

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
    # Re-check a NAMED set instead of the whole vault. A prompt change is
    # cheap to evaluate on the couple of dozen items that have ever been wrong
    # and expensive to evaluate on all of them — and the ones that have been
    # wrong before are where a regression shows up first. Implies `force`,
    # since the caller is asking for these specifically.
    only = payload.get("media_ids")
    only = {int(m) for m in only} if isinstance(only, (list, tuple, set)) else None
    from vault_ai_api import assert_media_visible, assert_owner_scope
    if only:
        await assert_media_visible(account_id, *only)
    else:
        await assert_owner_scope(account_id)

    if (await _vision_budget(account_id))["key_missing"]:
        raise _vision_key_missing()
    todo = await _flags_todo(account_id, force=force, only=only, limit=limit)

    if only:
        done, failed, cost = 0, 0, 0
        jev_sweep = vault_jev_pass.Sweep()
        for mid in todo:
            # Jev only where `_jev` is missing / stale (else its flags re-stamped
            # if they drifted) — never a paid Jev re-run per probe.
            res = await _jev_and_flag(account_id, mid, force=True, jev_sweep=jev_sweep)
            if res.get("ok"):
                done += 1
                cost += int(res.get("cost_millicents") or 0)
            else:
                failed += 1
                if res.get("status") == "capped":
                    break
        return {"account_id": account_id, "candidates": len(todo),
                "flagged": done, "failed": failed, "cost_millicents": cost,
                "prompt_version": _FLAGS_VERSION,
                # A sweep that stopped early leaves the vault at MIXED versions,
                # which is the state that has repeatedly been mistaken for a
                # finished one. Say so in the result rather than leaving a caller
                # to infer it from `failed`.
                "complete": failed == 0 and done == len(todo)}

    # One sweep per account. Without this, a click on a button that appears to
    # have failed re-runs the whole vault alongside the run already going.
    if account_id in _flags_running:
        return {"account_id": account_id, "status": "running",
                "candidates": len(todo), "already": True,
                "prompt_version": _FLAGS_VERSION}
    _flags_running.add(account_id)
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


# ── Describe (one item) ─────────────────────────────────────────────
# The vision primitives live in `vision`. This module has one job: her VAULT.

async def _describe_one(account_id: str, media_id: int, model: str = "qwen3-vl-30b",
                        prompt_version: str = "v2",
                        frames: int | None = None,
                        jev_res: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Describe one item.

    `prompt_version` picks the bake-off variant: "v2" (default — rich structured
    schema, the one in production) or "v1" (the original one-sentence prompt,
    ~4× cheaper, kept for bulk passes where only a rough tag is wanted).
    `frames` overrides the duration ladder; None = `_frames_for_duration`.
    `jev_res`: the Jev pass that just ran on this photo (`_describe_and_flag`),
    whose failure status names a skip (a cap is not stamped on the row).
    """
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
    if item is None:
        raise HTTPException(status_code=404, detail={"error": "not_in_mirror", "media_id": media_id})
    # D51: a photo is described off its `_jev` (`vault_describe_jev`: prose @640
    # off the review lane, v6 JSON @960 on it) — or not at all: no feedable
    # `_jev` (Jev unavailable / failed / capped) is a skip, retried by the next
    # sweep. Nothing is written, so a described row keeps its describe. A clip:
    # "vid" (the V2 describe + Jev facts, its storyboard frames), same skip rule.
    prev_ai = load_json(item.ai_fields_json, {}) or {}
    path, jev = vault_describe_jev.route(kind=item.kind, fields=prev_ai)
    if path is None:
        j = prev_ai.get(JEV_KEY) if isinstance(prev_ai.get(JEV_KEY), dict) else {}
        if jev_res and not jev_res.get("ok"):
            why = jev_res.get("status")
        else:
            why = j.get("status") if j.get("status") not in (None, "ok") else "jev_missing"
        return {"media_id": media_id, "ok": False, "status": why,
                "detail": f"no Jev reading for this {item.kind} ({why}) — skipped, retried next sweep"}
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
        px = vault_describe_jev.PX.get(path)   # a clip: its 400px storyboard frames as they are
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

    data = vault_describe_jev.answer(path, data, jev)
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
    """Flag one item, then describe it — the single-item route and the
    describe-all sweep both, so a described item always has its flags (the
    gated lanes read them). A photo or clip gets the Jev pass FIRST
    (`vault_jev_pass.safe`), which stamps its flags; there is no qwen flags
    call (D52/D54). Its outcome and spend ride on the result (`with_jev`;
    `vault_sweep.run` sums `cost_millicents`); when it leaves the item without
    a reading, `_describe_one` skips the item with Jev's status.
    `_describe_one` / `vault_ai_vision_decide.with_jev` are looked up per
    call, so patches bite."""
    kind = await _kind(account_id, media_id)
    jev = await vault_jev_pass.safe(account_id, media_id, sweep=jev_sweep) if kind in JEV_KINDS else None
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
    # Flagged in the same breath, exactly as the sweep does. Describing ONE item
    # from the UI otherwise left it as the only row in the vault the gated lanes
    # could not read, and nothing on screen said so.
    return await _describe_and_flag(
        account_id, media_id, model=model,
        prompt_version=str(payload.get("prompt_version") or "v2"),
        frames=payload.get("frames"),
    )


# ── Describe ALL (background sweep, gen_info-style) ─────────────────
_describe_running: set[str] = set()
_describe_progress: dict[str, dict[str, Any]] = {}
# Items in flight for ONE sweep. Raised 4 → 8 on 2026-08-11, against measured
# prod numbers rather than a guess: describe latency is a straight line in OUTPUT
# tokens (~24 tok/s — 54 tokens ⇒ 3.0s, 324 ⇒ 13.4s, 512 ⇒ 21.8s), and input size
# barely moves it, so the v2 prompt's 24-field schema costs ~14s per item no
# matter how many frames it reads. That is provider wall-clock nobody can shorten
# from here; the only lever on THROUGHPUT is how many run at once. At 4 the best
# observed minutes hit exactly the ceiling that implies (~14 items/min, 3.75 of 4
# slots busy), i.e. the bound was binding.
#
# 8 does NOT raise the load the relay was measured safe at — _VISION_GLOBAL
# _CONCURRENCY above still caps total vision work at 8 across every sweep, and
# the still-fetch path has its own `vault_stills._MAX_INFLIGHT_FETCHES`. What
# changes is that ONE account's sweep can now use the whole global budget instead
# of a quarter of it. Two accounts sweeping at once still share 8 and each get
# what they got before — the global gate is the knob for that, and it was set by
# a cost-audit finding about ReadTimeouts, so raise it with numbers, not hope.
_DESCRIBE_CONCURRENCY = 8


async def _run_describe_all(account_id: str, mode: DescribeMode,
                            prompt_version: str = "v2",
                            model: str = "qwen3-vl-30b") -> None:
    """Background describe sweep over the rows `describe_selection(mode)` picks
    (the modes are documented there)."""
    try:
        async with get_session() as s:
            # The SAME clause the plan counts with, so the number on the button
            # is the set walked here.
            walked = {int(r[0]) for r in (await s.execute(select(VaultItem.media_id).where(
                describe_selection(account_id, mode, prompt_version)))).all()}
            rows = (await s.execute(
                select(VaultItem.media_id, VaultItem.created_at, VaultItem.of_folder_ids)
                .where(live_describable(account_id)))).all()
        # `priority_order`, the same walk as `_flags_todo`. This sweep has no
        # limit, so order only decides what finishes early — but it CAN end
        # early: the cap trips or the relay restarts, and both cut the tail.
        ids = [m for m in priority_order(rows) if m in walked]
        plan, index = await _reuse(account_id, ids, flags=False)
        settled = await _copy_up_front(account_id, plan, _copy_describe)
        jev_sweep = vault_jev_pass.Sweep()
        due = await vault_jev_pass.clips_due(account_id)   # clips that queue for the Jev video lane

        async def visit(mid: int) -> dict[str, Any]:
            return await _lead(
                account_id, mid,
                _describe_and_flag(account_id, mid, model=model,
                                   prompt_version=prompt_version, jev_sweep=jev_sweep),
                plan.followers.get(mid, []), _copy_describe,
                _propagation(index, mid, walked, flags_only=False))

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
        # Into the progress snapshot, not just the log. `running` goes False in
        # `finally` either way, so a sweep that DIED and a sweep that finished
        # were previously distinguishable only by counting — and a caller that
        # sees done<total has no way to know whether to wait or to press the
        # button again.
        log.exception("describe_all failed account=%s", account_id)
        _describe_progress[account_id] = {
            **_describe_progress.get(account_id, {}),
            "aborted": True, "error": f"{type(e).__name__}: {e}"[:200],
        }
    finally:
        _describe_running.discard(account_id)
        # keep last progress snapshot for the status endpoint to report "done"


async def _claim_describe(account_id: str, model: str) -> dict[str, Any]:
    """Claim the account's ONE describe sweep, or refuse; returns the budget.

    The claim is taken in the same step as the check, before any await. It used
    to come after the budget read, so a second press (a double click, two
    managers) passed the check while the first was still awaiting it: N presses,
    N sweeps, N x the spend. Every refusal after the claim releases it, or the
    account would 409 forever; a started sweep releases it in its `finally`.
    """
    if account_id in _describe_running:
        raise HTTPException(status_code=409, detail={"error": "describe_already_running"})
    _describe_running.add(account_id)
    try:
        # REFUSE to start over the daily cap.
        #
        # Nothing here was ever unsafe: `llm_client._reserve` refuses every call
        # over the cap and the sweep stops on the first one. It was DISHONEST. The
        # sweep ended, the button went straight back to "Describe all (1777)", and a
        # second press started another one — which pulled frames off OF and cut them
        # with ffmpeg for a batch of items, had every LLM call refused, and reported
        # the same 1777 still to do. Nothing on screen ever said "you are out of
        # budget today", so the only reading available was that describe is broken,
        # and the natural response to that is to press it again.
        _assert_vision_model(model)  # a bad request is a 400 whatever the key/budget
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


@describe_router.post("/admin/vault-ai/describe-all")
async def describe_all(payload: dict = Body(...)) -> dict[str, Any]:
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    from vault_ai_api import assert_owner_scope
    await assert_owner_scope(account_id)
    model = str(payload.get("model") or "qwen3-vl-30b")
    await _claim_describe(account_id, model)
    force = bool(payload.get("force"))
    restage = bool(payload.get("restage"))
    mode: DescribeMode = "force" if force else ("restage" if restage else "undescribed")
    prompt_version = prompt_variant(payload.get("prompt_version"))
    asyncio.create_task(_run_describe_all(account_id, mode,
                                          prompt_version=prompt_version,
                                          model=model))
    return {"account_id": account_id, "status": "running",
            "prompt_version": prompt_version, "model": model,
            "force": force, "restage": restage}


@describe_router.get("/admin/vault-ai/describe-all/plan")
async def describe_all_plan(
    account_id: str = Query(...),
    prompt_version: str = Query("v2"),
) -> dict[str, Any]:
    """What each sweep mode WOULD do, so the UI can show real counts (and a cost
    estimate) before the operator commits to a re-scan of the whole vault."""
    assert_account_owned(account_id)
    from vault_ai_api import assert_owner_scope
    await assert_owner_scope(account_id)
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
    return {"account_id": account_id, "prompt_version": pv,
            "total": int(total or 0),
            "undescribed": int(undescribed or 0),
            "restage": int(stale or 0),
            "cap": budget,
            "jev": await vault_jev_pass.plan(account_id)}


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
