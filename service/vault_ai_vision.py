"""service/vault_ai_vision.py — the vision passes over the vault mirror.

Split out of `vault_ai_api` (routes unchanged): the cheap FLAGS pass
(`_flags_one`, `flags-all`) and the DESCRIBE pass (`_describe_one`, `describe`,
`describe-all`), plus the vision budget and the process-wide vision gate they
share. Pure decisions live in `vault_ai_vision_decide`.

Two routers, one per block, because `vault_ai_api` includes each at the spot the
block used to occupy — FastAPI matches routes in registration order. This module
never imports `vault_ai_api` (one-way dependency, no cycle).

Tests patch `vault_ai_vision._describe_one` / `_flags_one` /
`_DESCRIBE_CONCURRENCY` — the names are looked up HERE.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import func, select, update

import llm_client
import vault_ai_brief
import vault_ai_fix
import vault_frames
import vault_scripts
import vault_sweep
import vision  # shared frame download / shrink / refusal test
from auth import assert_account_owned
from db.engine import get_session
from db.models import VaultItem
from jsonsafe import load_json
from llm_client import LLMCapExceeded, LLMError
from vault_ai_vision_decide import (
    _DESCRIBABLE_KINDS, DescribeMode, _frames_for_duration, _ground_in_named_garment, _parse_describe,
    build_describe_update, build_flags_fields, describe_answer, describe_selection,
    live_describable, next_attempt,
)

# Same logger name as before the split, so log routing/filters are unchanged.
log = logging.getLogger("of-relay.vault_ai_api")

flags_router = APIRouter()
describe_router = APIRouter()


# ── Constants & prompts ─────────────────────────────────────────────

# Every describe/flags call goes to this provider, and the daily cap is held
# per-(account, provider) — so this one row IS the budget a vision sweep spends.
_VISION_PROVIDER = "deepinfra"


# Frames sampled from a CLIP for the flags pass.
#
# A clip changes state along its length — she can be dressed at 0:05 and nude at
# 1:30 — so a single frame answers the wrong question half the time. Four frames
# spread across the clip, each asked independently, then folded in code.
_FLAGS_VIDEO_FRAMES = 4


# Why a frameless item got no frames, as a `describe_status`.
#
# The two outcomes want OPPOSITE retry policies, and collapsing them is what made
# the 2026-08-04 incident invisible: every failure was stamped `blocked_drm`, so
# 1,777 items whose signatures had merely expired inherited the 7-day cool-off
# meant for clips OF genuinely cannot render, and the next sweep skipped them.
#   no_variant   → OF answered with a payload carrying nothing renderable.
#                  Asking again changes nothing. Cool off.
#   fetch_failed → we could not read bytes we have every reason to think exist.
#                  Retry on the very next sweep, no cool-off.
#   gone         → OF has deleted it. The still store already stamped
#                  `removed_at`, which every candidate query filters on, so this
#                  status is only ever read by whoever asked for THIS item.
# Unknown reasons fall to the retryable side: over-retrying costs a fetch,
# under-retrying costs a description nobody notices is missing.
_NO_IMAGE_STATUS = {"no_variant": "blocked_drm", "fetch_failed": "fetch_failed",
                    "gone": "gone"}


# ── Flags prompt (the cheap pass) ───────────────────────────────────
#
# `clothing_state` was wrong on ~1 in 3 of the items the $50 tier is built from:
# it reported `fully_nude` for shots where she still had panties on, and the
# error was invisible to every stored-data check because the enum, the garment
# list and the prose all agreed and all three were wrong.
#
# Two fixes, and this is the cheap one. Rather than re-running a full describe
# (2,788 tokens, ~16s/item) to recover two booleans the tier actually reads, ask
# ONLY for those booleans: ~350 tokens, ~3s/item — measured 5x faster and ~40x
# cheaper over the graded vault, about $0.001 for a 103-item vault.
#
# The image still has to keep its ASPECT RATIO. `files.thumb` is 300x300 and
# OF's stills are 3:4, so the thumb is a centre-CROP with the bottom of the
# frame missing — which is precisely where a waistband sits, and precisely why
# describe kept saying `fully_nude`. So we start from `preview` and downscale it
# ourselves: fewer pixels, whole picture. 448px on the long edge is the measured
# floor — 320px flips an item that 448 and 640 agree on, and 640 buys nothing.
# (the flag-run edge now lives with the resizer — vision.MAX_EDGE_DEFAULT)

# The prompt VERSION stamped onto every answer it produces.
#
# Bumped whenever the wording changes in a way that could move an answer. It
# exists because three separate times in one session a score was taken against
# a half-finished re-run and read as a result: v2 rows and v3 rows are
# indistinguishable once stored, so a partial sweep looks exactly like a
# finished one. With a stamp, `flags_all` can re-run only what is stale, and a
# scorer can refuse to report on a mixed vault.
#
#   1  two booleans, `pussy_covered` / `breasts_covered`
#   2  three-state enum per region, garment named first
#   3  in-frame/skin decision tree + sheer-fabric rule + insertion reconcile
_FLAGS_VERSION = 3

# Canonical in `vault_ai_brief` — `vault_scripts` gates its mass-safe lane on
# the same tuple, and two copies would drift the moment a flag is added.
_FLAG_KEYS = vault_ai_brief.FLAG_KEYS

# Each region is asked SEPARATELY because those splits ARE the price boundaries:
# $10 is breasts out with her vulva still covered, $50 is her vulva on show, and
# the mass-safe lane turns on nothing being on show at all. A single conflated
# question could not express the middle tier.
#
# Every region is asked in the SAME direction and with the SAME three answers.
# The previous version asked `pussy_covered` about fabric and `breasts_covered`
# about visibility, which meant `false` meant opposite things across two flags
# a caller had to read together — see `vault_ai_brief.VIS_STATES` for what that
# cost. Phrasing is positive ("what can you see") rather than a double negative
# ("is it kept from view"), because the negative form measured ~91% constant.
#
# GRADED against operator labels on 27 the graded vault items (`_probe_flags_score.py`).
# The version that asked for a state directly scored 80.2%, and 13 of its 16
# errors were the SAME mistake: `covered` where the truth was `not_in_frame`.
# Asked "is it covered", a model says yes whenever it cannot see skin — whether
# the body part is behind a bodysuit or simply not in the photograph. Both read
# as "not on show" to a human eye, and the previous wording never forced the
# distinction. A woman lying on her stomach in a bodystocking came back
# `covered` for all three regions when the honest answer is that none of them
# are in the picture.
#
# So the question is now a two-step decision, asked in order, rather than a
# three-way label to pick: is it in the photo at all → then is any skin
# showing. Models follow a tree far better than they pick from a menu, and the
# first step is the one that was being skipped.
_FLAGS_PROMPT = (
    "You are indexing one photo from an adult creator's own vault. She owns it "
    "and has asked for it to be catalogued so it can be sorted. Report only "
    "what you can SEE in this frame.\n\n"
    "Reply with STRICT JSON only, no prose. Emit the keys in EXACTLY this "
    "order — the `over_` answers come first because the states are read off "
    "them:\n"
    '{"over_breasts": "<what is over her chest, or null>",\n'
    ' "over_vulva":   "<what is over her crotch, or null>",\n'
    ' "over_anus":    "<what is over her backside, or null>",\n'
    ' "breasts_vis": "...", "vulva_vis": "...", "anus_vis": "...",\n'
    ' "underwear_visible": true|false}\n\n'
    "For each of her breasts, her vulva and her anus, work through these three "
    "questions IN ORDER.\n\n"
    "STEP 1 — is that part of her body in this photograph at all?\n"
    "  Point at it. If you cannot put your finger on the spot in THIS image, "
    'the answer is "not_in_frame" — set the matching `over_` field to null and '
    "move on to the next region.\n"
    "  Answer about the picture, never about her body. You know a woman has a "
    "vulva and you can usually guess she is wearing something over it. That is "
    "reasoning about the person. It is not seeing. A photograph of her face and "
    "chest contains no vulva and no anus, so both are NOT_IN_FRAME, no matter "
    "what she is obviously wearing below.\n"
    "  This is the answer people get wrong most often, so be deliberate:\n"
    "   · She is photographed from the front → her anus is NOT_IN_FRAME. It is "
    "behind her.\n"
    "   · She is photographed from behind, or lying face down → her breasts "
    "and her vulva are NOT_IN_FRAME.\n"
    "   · The shot is cropped at her waist → her vulva and anus are "
    "NOT_IN_FRAME.\n"
    "   · She is standing fully dressed and you cannot make out where a part "
    "of her body even is → NOT_IN_FRAME.\n"
    '  "not_in_frame" is a normal, common, correct answer. Most photos have at '
    "least one region that is simply not in them.\n\n"
    "STEP 2 — it IS in the photo. NAME what is over it, in the `over_` field.\n"
    "  Two or three words: \"white tank top\", \"black lace bra\", \"her right "
    'hand\", "the bedsheet". Use null only when you are looking at skin with '
    "nothing on it.\n"
    "  Name it BEFORE you judge how exposed she is. Saying what a woman is "
    "wearing is a far easier question than rating a photo, and the second "
    "answer falls out of the first.\n\n"
    "STEP 3 — now read the state off what you just named.\n"
    '  "covered" — you named something, and it hides that skin completely.\n'
    '  "bare"    — you can see skin, even a little. ANY of it counts: one '
    "nipple showing between her fingers, part of a breast beside her hand, a "
    "sliver of vulva beside a thong. Partly showing is showing.\n\n"
    "THE MISTAKE TO AVOID at step 2: clothing that shows the SHAPE of her body "
    'is still clothing. A tank top, t-shirt, bra, bodysuit or swimsuit is '
    '"covered" no matter how tight, how much cleavage, or how sexy the photo '
    "is.\n"
    "  Sheer fabric is fabric. Lace, mesh, fishnet and a bodystocking are "
    'CLOTHING, so skin seen THROUGH them is "covered" — the garment is on her. '
    '"bare" means there is no garment over that skin at all: pulled down, '
    "pulled aside, or never put on.\n\n"
    "IF SHE IS TOUCHING HERSELF, the skin she is touching is BARE. Underwear "
    "gets pulled aside for that. A hand between her legs, fingers or a toy "
    "inside her, her legs spread and held open, a clitoris being stroked — in "
    "every one of those her vulva is \"bare\", even if you can also see a thong "
    "somewhere in the frame. Do not name that thong as covering her: it has "
    "been moved out of the way, which is the entire reason you can see what you "
    "are looking at.\n\n"
    "Judge each region on its own. She is very often bare in one place and "
    "covered in another, and that difference is the whole point of this check. "
    "Never copy one garment into every `over_` field — a bra does not cover her "
    "vulva, a thong does not cover her breasts, and if you find yourself "
    "writing the same words three times, at least two of them are wrong. Do not "
    "let how explicit the picture FEELS decide anything: a picture can be very "
    "explicit with nothing actually on show, and a plain one can have "
    "everything on show.\n\n"
    "underwear_visible — is ANY garment visible anywhere on her body, worn or "
    "pushed aside or pulled down, however small? A waistband, a strap, a thong "
    "string, a band of lace at the hip or at the very bottom edge of the "
    "picture, stockings — all TRUE. Look at the edges of the frame before you "
    "answer FALSE.\n"
)


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


# ── Flags pass (one item) ───────────────────────────────────────────

async def _stamp_flags_failure(account_id: str, media_id: int, status: str,
                               detail: str = "") -> None:
    """Record WHY an item has no flags, in the item's own row.

    Flags have no status column and do not need one: `_flags_todo` decides from
    `flags_known()`, so a failed item is already retried by the next sweep. What
    was missing is any way to ASK. The pass returned `no_image` to a caller that
    logged it and moved on, so an operator looking at a described-but-unflagged
    row had nothing to read — the failure existed only in a log line that had
    long since rotated.

    Deliberately does NOT write `_flags_v`: that stamp is what marks flags
    CURRENT, and a failure must leave the item in the todo set."""
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
        if item is None:
            return
        fields = load_json(item.ai_fields_json, {}) or {}
        fields["_flags_status"] = status
        fields["_flags_failed_at"] = datetime.utcnow().isoformat()
        if detail:
            fields["_flags_error"] = detail[:200]
        else:
            fields.pop("_flags_error", None)
        item.ai_fields_json = json.dumps(fields, ensure_ascii=False, default=str)
        await s.commit()


async def _flags_one(account_id: str, media_id: int,
                     model: str = "qwen3-vl-30b") -> dict[str, Any]:
    """Ask the three booleans for one item and MERGE them into its existing
    `ai_fields_json`. Never rewrites the description, tags or taxonomy — this is
    an enrichment pass, so a cheap call can't damage an expensive one.

    Photos ask once. Clips ask `_FLAGS_VIDEO_FRAMES` times, one frame per call,
    and fold via `build_flags_fields`.
    """
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
    if item is None:
        return {"media_id": media_id, "ok": False, "status": "not_in_mirror"}
    if item.kind not in _DESCRIBABLE_KINDS:
        return {"media_id": media_id, "ok": False, "status": "not_flaggable"}

    is_video = item.kind == "video"
    raw = load_json(item.raw_json, {}) or {}
    want = _FLAGS_VIDEO_FRAMES if is_video else 1
    got = await vault_frames.collect(account_id, item, raw, want=want)
    if not got.images:
        status = _NO_IMAGE_STATUS.get(got.reason, "fetch_failed")
        await _stamp_flags_failure(account_id, media_id, status)
        return {"media_id": media_id, "ok": False, "status": status,
                "detail": got.detail or f"no frames ({status})"}

    per_frame: list[dict[str, Any]] = []
    cost = 0
    result = None
    for img in got.images:
        content = [{"type": "text", "text": _FLAGS_PROMPT},
                   {"type": "image_url", "image_url": {"url": vision.shrink_data_url(img)}}]
        try:
            result = await llm_client.chat(
                model=model, messages=[{"role": "user", "content": content}],
                purpose="describe_flags", account_id=account_id, temperature=0.1,
            )
        except LLMCapExceeded as e:
            if not per_frame:
                # Same sentence describe's refusals carry — both sweeps spend
                # the same budget, and an operator reading two different
                # explanations of one cap has to work out they are one thing.
                budget = await _vision_budget(account_id, model)
                return {"media_id": media_id, "ok": False, "status": "capped",
                        "detail": budget["blocked_reason"] or str(e)}
            break  # keep what we already read rather than losing the whole clip
        except llm_client.LLMKeyError:
            raise  # the key, not the item: the caller tells the owner (424 / sweep stop)
        except LLMError as e:
            if not per_frame:
                await _stamp_flags_failure(account_id, media_id, "error", str(e))
                return {"media_id": media_id, "ok": False, "status": "error",
                        "detail": str(e)[:300]}
            break
        cost += int(result.cost_cents or 0)
        parsed = _parse_describe(result.content)
        if any(k in parsed for k in _FLAG_KEYS):
            per_frame.append(_ground_in_named_garment(parsed))

    if not per_frame:
        raw_head = (result.content if result else "") or ""
        await _stamp_flags_failure(account_id, media_id, "unparsed", raw_head)
        return {"media_id": media_id, "ok": False, "status": "unparsed",
                "raw": raw_head[:200]}

    fields = build_flags_fields(
        load_json(item.ai_fields_json, {}) or {}, per_frame,
        locked=set(load_json(item.locked_fields_json, []) or []),
        is_video=is_video, model=model, version=_FLAGS_VERSION)

    async with get_session() as s:
        await s.execute(
            update(VaultItem)
            .where(VaultItem.account_id == account_id, VaultItem.media_id == media_id)
            .values(ai_fields_json=json.dumps(fields, ensure_ascii=False, default=str))
        )
        await s.commit()
    return {"media_id": media_id, "ok": True, "status": "flagged",
            **{k: fields.get(k) for k in _FLAG_KEYS},
            "frames": len(per_frame), "cost_millicents": cost}


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
    """Which items still need flags, NEWEST first — `created_at` is OF's own
    `createdAt`, so this is upload order, not mirror order.

    Matches the describe sweep's order. Flags are what the gated
    lanes actually read, so a describe that ran newest-first and a flags pass
    that ran oldest-first would leave the freshly-described items describable
    but still unusable — the two have to walk the vault the same way."""
    async with get_session() as s:
        q = (select(VaultItem.media_id, VaultItem.ai_fields_json)
             .where(live_describable(account_id)))
        if only:
            q = q.where(VaultItem.media_id.in_(only))
        rows = (await s.execute(
            q.order_by(VaultItem.created_at.desc(), VaultItem.media_id.desc())
        )).all()

    todo = []
    for mid, fj in rows:
        f = load_json(fj, {}) or {}
        # `flags_known`, not a key-presence test: a row carrying the superseded
        # boolean shape, or a region the model answered with something outside
        # the enum, has not really been flagged and must re-run. A row produced
        # by an OLDER prompt is stale for the same reason — its answers were
        # given to a different question.
        stale = int(f.get("_flags_v") or 0) < _FLAGS_VERSION
        if only or force or stale or not vault_ai_brief.flags_known(f):
            todo.append(int(mid))
    return todo[:limit] if limit else todo


async def _run_flags_all(account_id: str, todo: list[int]) -> None:
    """Background flags sweep. Resumable by construction: it only ever visits
    rows that are missing or stale, so a relay restart mid-sweep costs the items
    in flight and nothing else — pressing the button again picks up the rest."""
    try:
        c = await vault_sweep.run(
            todo, lambda mid: _flags_one(account_id, mid),
            concurrency=_FLAGS_CONCURRENCY, gate=_vision_gate,
            into=_flags_progress, key=account_id,
            label=f"flags_all account={account_id}")
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

    if (await _vision_budget(account_id))["key_missing"]:
        raise _vision_key_missing()
    todo = await _flags_todo(account_id, force=force, only=only, limit=limit)

    if only:
        done, failed, cost = 0, 0, 0
        for mid in todo:
            res = await _flags_one(account_id, mid)
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
    asyncio.create_task(_run_flags_all(account_id, todo))
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
                        frames: int | None = None) -> dict[str, Any]:
    """Describe one item.

    `prompt_version` picks the bake-off variant: "v2" (default — rich structured
    schema, the one in production) or "v1" (the original one-sentence prompt,
    ~4× cheaper, kept for bulk passes where only a rough tag is wanted).
    `frames` overrides the duration ladder; None = `_frames_for_duration`.
    """
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
    if item is None:
        raise HTTPException(status_code=404, detail={"error": "not_in_mirror", "media_id": media_id})
    raw = load_json(item.raw_json, {}) or {}
    want = int(frames) if frames else _frames_for_duration(item.duration_seconds)
    got = await vault_frames.collect(account_id, item, raw, want=want)
    if not got.images:
        status = _NO_IMAGE_STATUS.get(got.reason, "fetch_failed")
        async with get_session() as s:
            await s.execute(
                update(VaultItem)
                .where(VaultItem.account_id == account_id, VaultItem.media_id == media_id)
                .values(describe_status=status, describe_generated_at=datetime.utcnow())
            )
            await s.commit()
        # `detail` is what the sweep shows the operator as `first_error`. Without
        # it a whole vault failing on a frame bug reads as "1,777 could not be
        # described" and nothing else — a failure count with no cause is the same
        # shape as the missing-provider-key incident this row's status was added
        # for. `got.detail` carries the exception when `collect` swallowed one.
        return {"media_id": media_id, "ok": False, "status": status,
                "detail": got.detail or f"no frames ({status})"}

    prompt = _DESCRIBE_PROMPT if str(prompt_version) == "v1" else _DESCRIBE_PROMPT_V2
    content = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": u}} for u in got.images]

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
            async with get_session() as s:
                await s.execute(
                    update(VaultItem)
                    .where(VaultItem.account_id == account_id, VaultItem.media_id == media_id)
                    .values(describe_status="failed", describe_model=attempt_model,
                            describe_generated_at=datetime.utcnow())
                )
                await s.commit()
            return {"media_id": media_id, "ok": False, "status": "error",
                    "detail": str(e)[:300], "cost_millicents": cost}
        cost += int(result.cost_cents or 0)
        used_model = attempt_model
        if not vision.is_refusal(result.content):
            parsed = _parse_describe(result.content)
            if parsed.get("description") or parsed.get("tags"):
                data = parsed
        attempt_model = next_attempt(attempt_model, not data)

    # `data` is only ever `{}` or an answer that carries a description or tags.
    if not data:
        async with get_session() as s:
            await s.execute(
                update(VaultItem)
                .where(VaultItem.account_id == account_id, VaultItem.media_id == media_id)
                .values(describe_status="refused", describe_model=used_model,
                        describe_call_id=(result.call_id if result else None),
                        describe_generated_at=datetime.utcnow())
            )
            await s.commit()
        return {"media_id": media_id, "ok": False, "status": "refused",
                "raw": (result.content if result else "" or "")[:200],
                "cost_millicents": cost}

    locked = set(load_json(item.locked_fields_json, []))
    vals = build_describe_update(
        item.kind == "video", data,
        prev_ai=load_json(item.ai_fields_json, {}) or {}, locked=locked,
        overrides=load_json(item.operator_overrides_json, {}) or {},
        used_model=used_model, n_frames=len(got.images), pv=prompt_version,
        fixable=vault_ai_fix.FIXABLE,
        call_id=result.call_id if result else None, now=datetime.utcnow())

    async with get_session() as s:
        await s.execute(
            update(VaultItem)
            .where(VaultItem.account_id == account_id, VaultItem.media_id == media_id)
            .values(**vals)
        )
        await s.commit()
    return {
        "media_id": media_id, "ok": True, "status": "described",
        **describe_answer(data),
        "describe_model": used_model,
        "cost_millicents": cost,
        "images_sent": len(got.images),
    }


@describe_router.post("/admin/vault-ai/describe")
async def describe_one(payload: dict = Body(...)) -> dict[str, Any]:
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    try:
        media_id = int(payload.get("media_id"))
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": "media_id_required"})
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
    res = await _describe_one(
        account_id, media_id, model=model,
        prompt_version=str(payload.get("prompt_version") or "v2"),
        frames=payload.get("frames"),
    )
    # Flag it in the same breath, exactly as the sweep does. Describing ONE item
    # from the UI otherwise left it as the only row in the vault the gated lanes
    # could not read, and nothing on screen said so.
    if res.get("ok"):
        try:
            await _flags_one(account_id, media_id)
        except Exception:  # noqa: BLE001
            log.exception("flags after describe failed media=%s", media_id)
    return res


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
            stmt = select(VaultItem.media_id).where(
                describe_selection(account_id, mode, prompt_version))
            # NEWEST first, on OF's own `createdAt`. This sweep has no limit, so
            # in principle order only decides what finishes early — except it
            # can end early for two reasons that make it decide what happens at
            # all: the account's cap trips (`capped` breaks the chunk loop) or
            # the relay restarts mid-sweep. Both truncate the tail, and the tail
            # should be the 2018 uploads, not this week's shoot. Same order as
            # the 6h drip and `_flags_todo` so a vault is covered the same way
            # whichever one gets to it.
            stmt = stmt.order_by(VaultItem.created_at.desc(),
                                 VaultItem.media_id.desc())
            ids = [r[0] for r in (await s.execute(stmt)).all()]

        async def _describe_and_flag(mid: int) -> dict[str, Any]:
            res = await _describe_one(account_id, mid, model=model,
                                      prompt_version=prompt_version)
            # Flag it in the same breath. "Described" used to mean prose plus
            # `clothing_state` and nothing about what is actually on show, so a
            # freshly-described vault had no flags at all and every gated lane
            # was empty until someone remembered a second button. The flags pass
            # is ~3s and ~$0.00002 against describe's ~16s and ~$0.0086 — a fifth
            # of a percent — so making it conditional bought nothing but a way to
            # forget it.
            if res.get("ok"):
                try:
                    await _flags_one(account_id, mid)
                except Exception:  # noqa: BLE001
                    # Never let the cheap pass take down the expensive one: the
                    # description is already written and worth keeping.
                    log.exception("flags after describe failed media=%s", mid)
            return res

        c = await vault_sweep.run(
            ids, _describe_and_flag, concurrency=_DESCRIBE_CONCURRENCY,
            gate=_vision_gate, into=_describe_progress, key=account_id,
            label=f"describe_all account={account_id}")
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


@describe_router.post("/admin/vault-ai/describe-all")
async def describe_all(payload: dict = Body(...)) -> dict[str, Any]:
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    if account_id in _describe_running:
        raise HTTPException(status_code=409, detail={"error": "describe_already_running"})
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
    model = str(payload.get("model") or "qwen3-vl-30b")
    _assert_vision_model(model)  # a bad request is a 400 whatever the key/budget
    budget = await _vision_budget(account_id, model)
    if budget["key_missing"]:
        raise _vision_key_missing()
    if budget["capped"]:
        raise HTTPException(status_code=429,
                            detail={"error": "daily_cap_reached", **budget})
    force = bool(payload.get("force"))
    restage = bool(payload.get("restage"))
    mode: DescribeMode = "force" if force else ("restage" if restage else "undescribed")
    prompt_version = "v1" if str(payload.get("prompt_version")) == "v1" else "v2"
    _describe_running.add(account_id)
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
    pv = "v1" if str(prompt_version) == "v1" else "v2"
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
            "cap": budget}


@describe_router.get("/admin/vault-ai/describe-all/status")
async def describe_all_status(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    prog = _describe_progress.get(account_id)
    return {
        "account_id": account_id,
        "running": account_id in _describe_running,
        "progress": prog,
    }
