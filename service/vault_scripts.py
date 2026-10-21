"""service/vault_scripts.py — recover the SCRIPT a vault batch was shot as.

A creator does not shoot media one item at a time. She shoots a *script*: a run
of clips that escalates, almost always along the same arc —

    clothed  →  stripping / lingerie  →  nude  →  touching  →  masturbation

and then uploads the whole run to OF in one go. Two facts make that arc
recoverable, and one fact makes it necessary:

  * Recoverable (1) — a batch is a tight burst in OF's own `createdAt`. On the graded vault
    166 of 249 consecutive gaps are under 10 seconds; day-long gaps separate the
    shoots. So a gap threshold splits the vault into candidate scripts with no
    vision work at all.
  * Recoverable (2) — every item's rung on the ladder is already in the V2
    describe fields (`clothing_state`, `acts`, `penetration`). Scoring is pure
    arithmetic over data we have: no LLM call, no OF traffic, instant re-run.
  * Necessary — the upload is frequently REVERSED. Phone galleries hand the
    picker newest-first, so the batch lands masturbation-first and the arc reads
    backwards. Sorting a folder by `createdAt` therefore shows the payoff before
    the tease, which is exactly backwards for selling it.

This module scores each item on that ladder (`escalation_score`), orders items
for sending (`send_sort_key`),
groups shoots by outfit (`collect_outfit_scripts`) and cuts purpose lanes
(`collect_purpose_folders`). `plan_ai_folders` turns both into a folder
proposal and `apply_ai_folders` writes it as internal `AI-` folders.

Nothing here mutates OF. `plan_ai_folders` is read-only; `apply_ai_folders`
writes only our own folder rows.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select

import vault_ai_brief
from db.engine import get_session
from db.models import VaultFolderItem, VaultItem

log = logging.getLogger("of-relay.vault_scripts")

# A group smaller than this is not a shoot. Two items are a pair, and a folder
# per pair is worse than no folder.
MIN_SCRIPT_ITEMS = 3


# ── The ladder ──────────────────────────────────────────────────────
#
# Four independent axes, each mapped onto the SAME 0-100 arc, and an item's
# score is the MAX over the axes that are present.
#
# Max, not a weighted blend. A blend has to re-normalise when an axis is
# missing, and re-normalising makes items with different field coverage
# incomparable: under the blend a nude item with no `acts` scored 90 while a
# nude item with a toy actually inserted scored 87, because introducing the
# (mid-rung) acts component diluted the two saturated ones. Ordering a script by
# that is worse than not ordering it. Max has no such coupling — an absent axis
# contributes nothing instead of silently reweighting its neighbours, and every
# axis can only ever push an item LATER in the arc, which is what "how far along
# is this" actually means.
#
# The axes fail in different ways, which is why all four are kept: `acts` is the
# strongest signal but is absent on stills, `clothing_state` is present almost
# everywhere but saturates mid-arc, `penetration` is narrow but decisive, and
# `explicitness` is coarse but essentially never missing.

# Clothing tops out at 60, NOT 100: being naked is the MIDDLE of the arc, not
# the end of it. A nude still must not outrank a clip where she is fingering
# herself, and capping the axis is what guarantees that.
_CLOTHING: dict[str, int] = {
    "dressed": 0,
    "lingerie_on": 25,
    "partially_off": 40,
    "pulled_down": 50,
    "pulled_aside": 55,   # underwear still on but she is exposed — later than
                          # pulled_down in the arc, which is why V2 splits them
    "fully_nude": 60,
}

# The rung each act sits on. Gaps are intentional: `fingering` (70) to
# `toy_insertion` (85) is a real escalation, `rubbing_clit` to `fingering` is a
# smaller one, and the ordering of these numbers IS the product decision.
_ACTS: dict[str, int] = {
    "none": 0,
    "talking_to_camera": 0,
    "posing": 5,
    "shower": 15,
    "bath": 15,
    "tease": 20,
    "strip": 30,
    "undress": 35,
    "ass_shaking": 40,
    "twerk": 40,
    "groping_own_breasts": 45,
    "spreading": 55,
    "rubbing_clit": 65,
    "fingering": 70,
    "toy_on_clit": 78,
    "toy_insertion": 85,
    "riding_toy": 88,
    "blowjob": 88,
    "handjob": 85,
    "sex_missionary": 90,
    "sex_doggy": 90,
    "sex_riding": 90,
    "masturbation_orgasm": 95,
    "squirt": 98,
    "cumshot": 98,
}

# The model does not always return the menu spelling. Observed on a real graded
# batches: `stripping` for strip, `rubbing_breasts` for groping_own_breasts.
# Unknown acts are ignored rather than guessed at, so drift silently costs
# signal — these are the spellings actually seen, not speculative synonyms.
_ACT_ALIASES: dict[str, str] = {
    "stripping": "strip",
    "undressing": "undress",
    "rubbing_breasts": "groping_own_breasts",
    "groping_breasts": "groping_own_breasts",
    "twerking": "twerk",
    "teasing": "tease",
    "posing_for_camera": "posing",
    "masturbation": "masturbation_orgasm",
    "orgasm": "masturbation_orgasm",
    "squirting": "squirt",
}

_PENETRATION: dict[str, int] = {
    "none": 0, "fingers": 70, "toy": 85, "penis": 95,
}

# Coarse, but the one axis the model essentially always fills in. `hardcore` is
# defined as penetration/cum/a partner act, so it legitimately sits late.
_EXPLICITNESS: dict[str, int] = {
    "sfw": 0, "suggestive": 25, "explicit": 55, "hardcore": 85,
}


def _norm(v: Any) -> str:
    return str(v or "").strip().lower()


def escalation_score(fields: dict[str, Any]) -> int | None:
    """Where this item sits on the clothed→masturbation ladder, 0-100.

    The max over every axis that is present (see the ladder note above).

    Returns None when the V2 fields carry no usable signal at all (every axis
    missing or "unclear"). None is NOT zero: an unscoreable item must not be
    sorted to the front of a script as though it were the tame opener.
    """
    if not isinstance(fields, dict):
        return None

    rungs: list[int] = []

    clothing = _CLOTHING.get(_norm(fields.get("clothing_state")))
    if clothing is not None:
        rungs.append(clothing)

    # An item's act rung is the HIGHEST act present. A clip that opens with a
    # tease and ends with insertion belongs at the insertion end of the script.
    acts = fields.get("acts")
    act_rungs = []
    for raw_act in acts or []:
        a = _norm(raw_act)
        a = _ACT_ALIASES.get(a, a)
        if a in _ACTS:
            act_rungs.append(_ACTS[a])
    if act_rungs:
        rungs.append(max(act_rungs))

    pen = _PENETRATION.get(_norm(fields.get("penetration")))
    if pen:
        rungs.append(pen)

    explicit = _EXPLICITNESS.get(_norm(fields.get("explicitness")))
    if explicit is None:
        explicit = _EXPLICITNESS.get(_norm(fields.get("explicitness_tier")))
    if explicit is not None:
        rungs.append(explicit)

    return max(rungs) if rungs else None


# ── Batching ────────────────────────────────────────────────────────

# ── Orientation ─────────────────────────────────────────────────────

# ── Planning ────────────────────────────────────────────────────────

async def _load_rows(account_id: str) -> list[dict[str, Any]]:
    async with get_session() as s:
        recs = (await s.execute(
            select(VaultItem.media_id, VaultItem.kind, VaultItem.created_at,
                   VaultItem.duration_seconds, VaultItem.ai_fields_json,
                   VaultItem.describe_status)
            .where(VaultItem.account_id == account_id,
                   VaultItem.removed_at.is_(None))
            .order_by(VaultItem.created_at.asc(), VaultItem.media_id.asc())
        )).all()

    out: list[dict[str, Any]] = []
    for mid, kind, created, dur, fields_json, status in recs:
        try:
            fields = json.loads(fields_json) if fields_json else {}
        except (TypeError, ValueError):
            fields = {}
        out.append({
            "media_id": int(mid), "kind": kind, "created_at": created,
            "duration_seconds": dur, "fields": fields, "describe_status": status,
            "score": escalation_score(fields),
        })
    return out


# ── Send order ──────────────────────────────────────────────────────
#
# `escalation_score` above answers "how far along the arc is this?", which is
# what DIRECTION detection needs: one monotone number Kendall tau can correlate
# against upload order. It is deliberately coarse.
#
# Deciding what to SEND FIRST is a different question, and a single 0-100 blob
# flattens distinctions that decide the sale. The key below is a tuple, and it
# reads its facts from `vault_ai_brief.sellability()` rather than re-deriving
# them — that module already owns the selling taxonomy (EXPLICITNESS_LADDER,
# _PAYOFF_ACTS, _REVEAL_TENSION), and a second parallel copy of it here would
# drift the moment either side is tuned.
#
# The axes, in priority order:
#
#  1. rung — sfw→suggestive→explicit→hardcore. "A night's sends walk it upward."
#     This is the coarse escalation and it dominates everything else.
#  2. build-up before payoff — an item WITHOUT a payoff act is a rung that tees
#     up the next send; one WITH a payoff can close on its own. Within a rung,
#     tease first and close last. This is the axis the old single score could
#     not express at all: a nude tease and a nude fingering clip both scored 60.
#  3. reveal tension — dressed → lingerie → mid-strip → fully_nude. Chronological
#     within the strip, which is also how it was filmed. Note this is ORDER, not
#     value: `vault_ai_brief` correctly ranks the "almost" states as the highest
#     VALUE to sell, but they still come before full nudity in a night.
#  4. the act ladder — fine-grain within all of the above.
#  5. media id — a stable tie-break, so equal keys never reorder between runs.
#
# Anything we cannot place lands last, never in the opening slot.

_CLOTHING_PROGRESS: dict[str, int] = {
    "dressed": 0, "lingerie_on": 1, "partially_off": 2,
    "pulled_down": 3, "pulled_aside": 4, "fully_nude": 5,
}

_UNKNOWN = 99


def send_sort_key(fields: dict[str, Any], *, media_id: int = 0) -> tuple[int, ...]:
    """Sort key placing an item in SEND order — tease first, payoff last."""
    sell = vault_ai_brief.sellability(fields)

    rung = sell["rung"] if sell["rung"] is not None else _UNKNOWN
    closes = 1 if sell["stands_alone"] else 0
    clothing = _CLOTHING_PROGRESS.get(
        _norm(fields.get("clothing_state")), _UNKNOWN)
    act = escalation_score(fields)
    return (rung, closes, clothing, act if act is not None else _UNKNOWN, media_id)


def send_order_reason(fields: dict[str, Any]) -> dict[str, Any]:
    """The human-readable 'why is it here' behind `send_sort_key`, for the
    review UI. Same facts, no second derivation."""
    sell = vault_ai_brief.sellability(fields)
    return {
        "tier": sell["tier"],
        "rung": sell["rung"],
        "closes": sell["stands_alone"],
        "payoff_acts": sell["payoff_acts"],
        "reveal": sell["reveal"],
        "clothing_state": _norm(fields.get("clothing_state")) or "unclear",
        "solo": sell["solo"],
        "beats": [b for b in (fields.get("beats") or []) if str(b).strip()],
        "acts": [str(a) for a in (fields.get("acts") or []) if str(a).strip()],
    }


# ── Outfit scripts (what a script actually IS) ──────────────────────
#
# The upload-burst grouping above finds "media pushed to OF in one sitting".
# That is NOT a script. Measured on the graded vault, bursts are kind-PURE — she uploads
# her photos in one go and her clips in another — so burst grouping splits every
# real shoot down the middle and can never produce the mix an operator means.
#
# A script is a SHOOT: one outfit, worn across both stills and clips, escalating
# from covered to explicit, uploaded around the same time. The linking signal is
# therefore the OUTFIT, and it is already in the describe output as
# `clothing_items`. Grouping by it re-joins what the burst split:
#
#   black : 46 items = 36 photos + 10 videos, sfw→suggestive→explicit
#   pink  : 19 items = 14 photos +  5 videos, sfw→suggestive→explicit
#
# Colour is the key, not the full garment string. The model writes free text and
# names the same set five ways — "pink lace bra", "pink lace panties", "pink
# lace thong", "pink thong", "pink satin" — so an exact-string match finds
# nothing while the colour is stable across all of them. Material is only a
# fallback for when no colour was named.
#
# Colour alone would merge two different black shoots weeks apart, so a group is
# also split wherever it goes quiet for longer than `window_hours`.

# Multi-word colours FIRST — "dark blue" must win before "blue" matches inside it.
_COLOURS: tuple[str, ...] = (
    "dark blue", "light blue", "navy", "burgundy", "pink", "black", "white",
    "red", "blue", "green", "purple", "beige", "grey", "gray", "yellow",
    "orange", "brown", "silver", "gold", "cream", "lilac",
)

_MATERIALS: tuple[str, ...] = (
    "lace", "leather", "fishnet", "satin", "silk", "mesh", "denim", "velvet",
    "cotton",
)

# Colour alone is too coarse. the graded vault's "black" group came back as 46 items and
# the operator's read was blunt: three different sets. It was — one 15:27 burst
# alone held a leather jacket, a fur-lined jacket, four distinct tops, three
# bodysuits and two bra sets, all black. A bulk archive dump of many outfits
# that merely share a colour is not a shoot.
#
# So the key is colour PLUS the kind of garment. Ordered most-identifying first,
# because an item usually lists several pieces and the most distinctive one names
# the set: "black lace bodysuit, fishnet stockings" is a bodysuit shoot, not a
# hosiery shoot.
#
# Note this deliberately does NOT split on how undressed she is — `clothing_state`
# already carries that, and a shoot is *supposed* to run dressed → undressed.
# What it splits is which OUTFIT she had on.
_GARMENT_CLASSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bodysuit", ("bodysuit", "teddy", "leotard", "one-piece", "onepiece",
                  "corset", "bustier")),
    ("dress", ("dress", "gown", "robe")),
    ("swim", ("bikini", "swimsuit", "swimwear")),
    ("lingerie_set", ("bra", "bralette", "panties", "thong", "underwear",
                      "knickers", "briefs", "lingerie")),
    ("top", ("top", "shirt", "blouse", "crop", "tank", "halter", "sweater")),
    ("bottoms", ("skirt", "shorts", "pants", "jeans", "leggings", "bottoms")),
    ("outerwear", ("jacket", "coat", "hoodie", "cardigan")),
    ("hosiery", ("stockings", "fishnet", "tights", "socks")),
)

# Two different shoots in the same colour must not merge just because the colour
# matches. 48h keeps a shoot whose stills and clips went up on consecutive
# nights together (the graded vault's pink set spans 26 hours) while separating a black
# set shot a week later.
DEFAULT_OUTFIT_WINDOW_HOURS = 48


def short_outfit(outfit: str) -> str:
    """`pink lingerie_set` → `pink lingerie`. The outfit key is a machine key;
    this is what a human reads in a folder list."""
    return str(outfit).replace("_set", "").replace("_", " ").strip()


def outfit_colour(fields: dict[str, Any]) -> str:
    """The item's dominant garment colour, else its material. '' if unnamed."""
    if not isinstance(fields, dict):
        return ""
    text = " ".join(str(x).lower() for x in (fields.get("clothing_items") or []))
    if not text.strip():
        return ""
    for colour in _COLOURS:
        # Word-boundary match so "blue" cannot fire inside "dark blue".
        if re.search(rf"\b{re.escape(colour)}\b", text):
            return colour
    for material in _MATERIALS:
        if material in text:
            return material
    return ""


def garment_class(fields: dict[str, Any]) -> str:
    """Which KIND of outfit this is — bodysuit / lingerie_set / top / …"""
    if not isinstance(fields, dict):
        return ""
    text = " ".join(str(x).lower() for x in (fields.get("clothing_items") or []))
    for name, words in _GARMENT_CLASSES:
        if any(w in text for w in words):
            return name
    return ""


def outfit_key(fields: dict[str, Any]) -> str:
    """The outfit an item belongs to: `"<colour> <garment class>"`.

    Empty string when the describe named no garment at all — those items cannot
    be attributed to a shoot and are left out rather than pooled into a junk
    group. A colour with no recognised garment class still keys on the colour
    alone, so a set is never dropped just because its wording is unusual.
    """
    colour = outfit_colour(fields)
    if not colour:
        return ""
    kind = garment_class(fields)
    return f"{colour} {kind}".strip()


async def collect_outfit_scripts(
    account_id: str, *, window_hours: int = DEFAULT_OUTFIT_WINDOW_HOURS,
    min_items: int = MIN_SCRIPT_ITEMS, require_escalation: bool = True,
) -> list[dict[str, Any]]:
    """Shoots, recovered by outfit. Read-only.

    `require_escalation` drops groups that sit on ONE explicitness rung — a run
    of eight equally-suggestive stills in the same bra is a set, not a script,
    because there is nowhere to walk a fan to.

    Ranked best-first: a mix of stills AND clips, spanning the most rungs, is
    what an operator can actually build a night out of.
    """
    rows = await _load_rows(account_id)
    window = window_hours * 3600

    by_outfit: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        key = outfit_key(r.get("fields") or {})
        if key:
            by_outfit.setdefault(key, []).append(r)

    out: list[dict[str, Any]] = []
    for outfit, items in by_outfit.items():
        items.sort(key=lambda r: (r["created_at"] or datetime.min, r["media_id"]))
        # Split the colour into separate shoots wherever it goes quiet.
        segments: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = [items[0]]
        for prev, item in zip(items, items[1:]):
            gap = ((item["created_at"] - prev["created_at"]).total_seconds()
                   if item["created_at"] and prev["created_at"] else 0)
            if gap > window:
                segments.append(current)
                current = []
            current.append(item)
        segments.append(current)

        for seg in segments:
            if len(seg) < min_items:
                continue
            enriched = [{**r, "why": send_order_reason(r.get("fields") or {})}
                        for r in seg]
            rungs = {r["why"]["rung"] for r in enriched if r["why"]["rung"] is not None}
            if require_escalation and len(rungs) < 2:
                continue

            placed = [r for r in enriched if r["why"]["rung"] is not None]
            unplaced = [r for r in enriched if r["why"]["rung"] is None]
            placed.sort(key=lambda r: send_sort_key(r["fields"], media_id=r["media_id"]))
            ordered = placed + unplaced

            kinds: dict[str, int] = {}
            tiers: dict[str, int] = {}
            for r in ordered:
                kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
                tiers[r["why"]["tier"]] = tiers.get(r["why"]["tier"], 0) + 1

            started = ordered[0]["created_at"]
            out.append({
                "outfit": outfit,
                "name": ai_folder_name(short_outfit(outfit)),
                "size": len(ordered), "kinds": kinds, "tiers": tiers,
                "rungs": sorted(rungs),
                "mixed": len(kinds) > 1,
                "closes_on_own": sum(1 for r in ordered if r["why"]["closes"]),
                "started_at": min(r["created_at"] for r in seg if r["created_at"]),
                "ended_at": max(r["created_at"] for r in seg if r["created_at"]),
                "items": [{**r, "manual_order": i + 1}
                          for i, r in enumerate(ordered)],
            })

    # Mixed media first, then widest escalation, then biggest.
    out.sort(key=lambda s: (not s["mixed"], -len(s["rungs"]), -s["size"]))
    return out


# ── Purpose folders (what a weak shoot is still good for) ───────────
#
# Not every outfit group is a sellable shoot. the graded vault's `black top` (15 stills,
# ZERO closers) and `white top` (4 stills) have nothing to land a sale on — but
# they are perfectly good STORY material, and the explicit tail of a weak group
# still works as a free teaser on a mass send.
#
# So the leftovers get re-cut by heat instead of by outfit, into the two lanes
# an operator actually sends on:
#
#   Stories        sfw → suggestive   safe enough to post publicly
#   Mass / teaser  suggestive → explicit  the free hook on a broadcast
#
# The bands OVERLAP on `suggestive` deliberately, and that is the case the
# per-folder ordering was built for: a suggestive still belongs in both lanes and
# holds a DIFFERENT position in each — near the top of Stories (it is the
# spiciest thing there) and at the bottom of Mass (it is the mildest thing
# there). One item, two folders, two orders. Nothing about that works if order
# lives on the item.
# Every folder this module proposes is prefixed so an operator can always tell
# at a glance which folders a human curated and which the pipeline generated —
# and can delete the whole generated set without touching their own work.
AI_FOLDER_PREFIX = "AI-"


def ai_folder_name(name: str) -> str:
    """`AI-<name>`, never double-prefixed on a re-run."""
    clean = str(name).strip()
    if clean.startswith(AI_FOLDER_PREFIX):
        return clean[:120]
    return f"{AI_FOLDER_PREFIX}{clean}"[:120]


# Tiers a paid tease can be cut from. Below explicit there is nothing to charge
# for; that material belongs in the free lanes.
_PAID_TIERS = ("explicit", "hardcore")


def _focus(fields: dict) -> set[str]:
    return {_norm(x) for x in (fields.get("body_focus") or []) if _norm(x)}


def _shows_genitals(fields: dict) -> bool:
    """Her vulva or anus is in frame AND bare.

    One signal now, not two. The flags pass answers "in frame and bare / in
    frame and covered / not in frame" directly, so this no longer has to
    triangulate visibility out of `body_focus` plus a fabric-only boolean —
    which is what let a dildo clip (`body_focus: None`) and an anal clip
    (`body_focus` without `pussy`) both read as showing nothing.
    """
    return (vault_ai_brief.is_bare(fields, "vulva_vis")
            or vault_ai_brief.is_bare(fields, "anus_vis"))


def _shows_breasts_bare(fields: dict) -> bool:
    """Her breasts are in frame with nothing over them — the $10 signal."""
    return vault_ai_brief.is_bare(fields, "breasts_vis")


def _is_nude(fields: dict) -> bool:
    """Is she actually wearing nothing?

    Prefers the cheap flags pass over `clothing_state`. The enum was measured
    wrong on ~1 in 3 of the items the $50 tier is built from — it reported
    `fully_nude` for shots with panties still on, and nothing in the stored row
    contradicted it. The flags are answered by looking, so they win outright.

    A NAMED garment settles it before `underwear_visible` is consulted, because
    that flag asks only about UNDERWEAR: a woman in a tank top and a skirt is
    wearing no underwear, so it answers False and she reads as nude. That is
    not a hypothetical — a street selfie in a leather jacket came back nude and
    padded a $100 row as explicit.
    """
    if vault_ai_brief.wearing_something(fields):
        return False
    seen = fields.get("underwear_visible")
    if isinstance(seen, bool):
        return not seen
    return _norm(fields.get("clothing_state")) == "fully_nude"


# ── Solo: nobody else in the frame ──────────────────────────────────
#
# `people_count` and `partner_visible` are V2 describe fields, so the model is
# asked this directly — but its answer is only one of the votes, because what
# is HAPPENING is evidence about who is there too. See `_partner_evidence`.

# Acts from `_V2_ACTS` that cannot happen alone.
_PARTNER_ACTS = frozenset({
    "blowjob", "handjob", "sex_missionary", "sex_doggy", "sex_riding", "cumshot",
})
# `primary_folder` values from `_V2_FOLDERS` that name a partner outright.
_PARTNER_FOLDERS = frozenset({"blowjob", "sex_with_partner"})


def _people_count(fields: dict) -> int | None:
    """`people_count` as an int, or None when the row does not carry one.
    `bool` is an `int` in Python and `people_count: true` is not a count."""
    count = fields.get("people_count")
    return count if isinstance(count, int) and not isinstance(count, bool) else None


def solo_known(fields: dict) -> bool:
    """Does this row carry an answer about who else is in it?

    Only the V2 describe prompt asks. A V1 row — or a V2 run where the model
    dropped the keys — answers neither, and `is_solo` refuses to guess for it.
    Callers surface the count so an operator who ticks Solo on a V1 vault is
    told why the folders came out empty, instead of reading it as breakage.
    """
    return (isinstance(fields.get("partner_visible"), bool)
            or _people_count(fields) is not None)


def _partner_evidence(fields: dict) -> bool:
    """Any ONE signal that someone else is in this item.

    A disjunction on purpose, and asked in the positive: one "someone else"
    outranks every "just her". The count alone is not enough — a model that has
    just described a partner act still returns `people_count: 1` often enough to
    matter, because it counts the person the clip is ABOUT.
    """
    count = _people_count(fields)
    if fields.get("partner_visible") is True:
        return True
    if count is not None and count > 1:
        return True
    if {_norm(a) for a in (fields.get("acts") or [])} & _PARTNER_ACTS:
        return True
    if _norm(fields.get("primary_folder")) in _PARTNER_FOLDERS:
        return True
    # A penis is only ever inserted BY someone. Fingers and toys are not
    # evidence either way, and are deliberately not read here.
    return _norm(fields.get("penetration")) == "penis"


def is_solo(fields: dict) -> bool:
    """Only the creator is in this item — nobody else, no partner act.

    Errs toward NOT solo in both of the ways it can be uncertain: a row nobody
    ever asked is not solo (`solo_known`), and a row with any partner evidence
    is not solo (`_partner_evidence`).

    The asymmetry is the point: this exists so an operator can point a fan at a
    folder and know what is in it. A missing item costs a smaller folder; a
    partner clip in a solo folder is the wrong thing sold under the wrong
    promise, which on this account has been an unsubscribe.
    """
    return solo_known(fields) and not _partner_evidence(fields)


def _has_payoff_act(fields: dict) -> bool:
    """Something is actually HAPPENING, not just being shown.

    Reads `vault_ai_brief._PAYOFF_ACTS` — the same set that decides whether a
    piece can close a sale on its own — plus any recorded `penetration`. Kept
    separate from every visibility test on purpose: it is the one signal about
    an item that does not depend on the flags pass being right.
    """
    acts = {_norm(a) for a in (fields.get("acts") or []) if _norm(a)}
    if acts & vault_ai_brief._PAYOFF_ACTS:
        return True
    pen = _norm(fields.get("penetration"))
    return bool(pen) and pen not in ("none", "unclear")


def _lane_stories(why: dict, fields: dict, kind: str) -> bool:
    return why["tier"] in ("sfw", "suggestive")


def _lane_mass(why: dict, fields: dict, kind: str) -> bool:
    """Suggestive ONLY. The old suggestive→explicit band swallowed 92 of 103
    items and made every paid item free as well."""
    return why["tier"] == "suggestive"


def _lane_covered_explicit(why: dict, fields: dict, kind: str) -> bool:
    """Tagged explicit, but nothing is actually on show — a top or underwear is
    still on, or she is turned away. The tier says "explicit" because of what the
    scene IS, not because of what is VISIBLE, so this material is safe on a mass
    send or a story even though the heat rung alone would rule it out. It is
    equally not a tease: there is no reveal in it to charge for.

    Gated on the two flags rather than on `body_focus` alone. The earlier version
    required `ass`/`back` in focus as a proxy for "turned away" and tested
    `_shows_breasts` (in frame) instead of `_shows_breasts_bare` (in frame AND
    uncovered) — so a shot with a top still on was thrown out of this lane for
    having breasts in the picture, and landed in no lane at all.

    REQUIRES the flags to exist. This is the only lane that asserts something is
    safe to put in front of everyone, and every other test here reads "no
    evidence of exposure" — which an UNFLAGGED item satisfies trivially. Before
    this guard, the graded vault's two unflagged clips (anal penetration; a dildo) sat in
    this folder, and on a V1-described vault all 472 members were rows with no
    `body_focus` at all. Absence of evidence is not evidence of absence, and for
    this lane specifically the default must be to exclude.

    The act guard below is deliberately NOT a flags check. This lane admitted
    the same two clips twice, through two different vacuous-truth holes, and
    both times the fix was a sharper reading of what is VISIBLE. A third hole in
    the same shape is likelier than not, so entry also turns on what is
    HAPPENING: a clip of penetration does not become mass-safe because a frame
    was framed tightly. Two independent reasons to exclude, so one being wrong
    is not enough to let it through.
    """
    if not vault_ai_brief.flags_known(fields):
        return False
    if _has_payoff_act(fields):
        return False
    if why["tier"] not in _PAID_TIERS:
        return False
    if vault_ai_brief.any_bare(fields):
        return False
    return _decently_covered(fields)


def _decently_covered(fields: dict) -> bool:
    """Nothing on show, and not merely because a hand happens to be in the way.

    `covered` deliberately lumps fabric together with a hand, a thigh and the
    bedsheet, because for "how much skin is on show" those are the same thing.
    For THIS lane they are not. Each region has to be out of shot, or behind
    something we can NAME as clothing.

    Two rules were tried and rejected against her actual vault, both of which
    read plausibly and both of which shipped topless material to a mass send:

      * "nothing bare" alone — admitted a fully-nude still whose only cover was
        her own hands.
      * "nothing bare AND she is wearing something" — admitted six stills of
        her topless with her hands over her breasts and a thong on. A thong is
        not what makes a topless shot decent, and `_is_nude` says nothing about
        which HALF of her is dressed.

    This rule under-includes on purpose: a shot of her face down in a thong,
    breasts behind her own arm, is genuinely safe and is excluded because the
    only thing over her breasts is an arm. That costs a smaller folder. The
    permissive versions cost a topless mass send, and those are not the same
    kind of mistake. If the folder needs those back, the flags pass has to be
    able to say she is turned AWAY — which it cannot, and which no rule over
    the current fields can infer.
    """
    for region in ("vulva_vis", "breasts_vis"):
        state = vault_ai_brief.vis(fields, region)
        if state == "not_in_frame":
            continue
        if state != "covered":
            return False
        if not vault_ai_brief.is_clothing(vault_ai_brief.garment_over(fields, region)):
            return False
    return True


def _lane_tease_10(why: dict, fields: dict, kind: str) -> bool:
    """$10 — a real reveal, but she is still a little hidden: breasts out, or
    nude with her pussy not in frame. Images only.

    Still COVERED is the whole point: fully nude is the $50 tier, never this
    one, however little is actually in frame. What remains is the middle band —
    breasts out with her pussy not visible and something still on.

    Content lanes may overlap freely, but the two PRICE tiers must not: an item
    cannot carry two prices.
    """
    if kind != "photo" or why["tier"] not in _PAID_TIERS:
        return False
    if _is_nude(fields):
        return False          # nude is a $50, not a $10
    if _lane_tease_50(why, fields, kind):
        return False
    return _shows_breasts_bare(fields) and not _shows_genitals(fields)


def _lane_tease_50(why: dict, fields: dict, kind: str) -> bool:
    """$50 — the full reveal: fully nude, pussy visible, or a full-body nude.
    Images only.

    Never `lingerie_on`. If she still has lingerie on it is not the full reveal
    whatever else the describe pass tagged — and that tag combination is usually
    a mislabel (panties pulled aside read as "lingerie on"), so trusting it
    would price a partial reveal at $50.
    """
    if kind != "photo" or why["tier"] not in _PAID_TIERS:
        return False
    if vault_ai_brief.vis(fields, "vulva_vis") == "covered":
        return False          # something over her vulva is never the full reveal
    if _norm(fields.get("clothing_state")) == "lingerie_on" and not _is_nude(fields):
        return False
    # Something has to be ON SHOW. Being nude is not by itself a reveal: a
    # fully-nude shot taken from behind exposes nothing, belongs in the
    # mass-safe lane, and has nothing in it to charge $50 for. Before this,
    # `_is_nude` alone admitted it and the same item was simultaneously free
    # and the most expensive thing in the vault.
    if not vault_ai_brief.any_bare(fields):
        return False
    return (_shows_genitals(fields)
            or "full_body" in _focus(fields)
            or _is_nude(fields))


def _lane_clips(why: dict, fields: dict, kind: str) -> bool:
    """Every explicit or hardcore CLIP.

    The two price lanes above are images-only on purpose — a clip is priced by
    what happens in it and how long it runs, not by how much is on show in a
    single frame — but nothing then picked the clips up, so an explicit video
    could match no lane at all. On her vault that was 21 clips, including the
    payoff ones: the most valuable material in the account was the material the
    folder system could not see.

    Deliberately wide. This is the pool a 1:1 PPV is chosen FROM, not a claim
    about price or about being safe to send to everyone — `safe explicit` is the
    only lane that asserts the latter, and it still applies its own tests.
    """
    return kind == "video" and why["tier"] in _PAID_TIERS


# (slug, display name, what it is for, predicate(why, fields, kind)). Lanes
# deliberately OVERLAP — a single item can serve several and holds an
# independent position in each.
# The display name is what becomes the FOLDER name, so it is kept short: these
# end up in a dropdown and (once mirrored) in the OF app, where
# "AI-$50 tease · images, fully nude or pussy visible" is unusable. The long
# form lives in `purpose`, which the preview shows underneath.
PURPOSE_LANES: tuple[tuple[str, str, str, Any], ...] = (
    ("stories", "stories",
     "sfw → suggestive — safe enough to post publicly", _lane_stories),
    ("mass", "mass",
     "suggestive only — mass messages and media", _lane_mass),
    ("covered_explicit", "safe explicit",
     "turned away — reads explicit but shows only her back or ass, so it is "
     "safe to mass", _lane_covered_explicit),
    ("tease_10", "tease 10",
     "images — boobs out or still covered, never fully nude (that is the $50)",
     _lane_tease_10),
    ("tease_50", "tease 50",
     "images — fully nude or pussy visible, never with lingerie still on",
     _lane_tease_50),
    ("clips", "clips",
     "explicit clips — the pool a 1:1 PPV is picked from", _lane_clips),
)

# Paid-tier items that matched NO lane above get their own. The five original
# lanes each answer a specific question ("is this safe to post", "is this a $50
# reveal"), and an item that answers no to all of them was simply dropped — 55
# of her 327, every one of them explicit or hardcore, i.e. the material worth
# selling. The commonest case is an explicit still that is nonetheless fully
# covered: `safe explicit` refuses it because something IS happening in it, and
# neither price lane wants it because there is no reveal to charge for.
#
# So it is not a dumping ground, it is a real category: explicit material to
# sell one-to-one rather than post or price off a shelf. Naming it also keeps
# the preview honest — "198 of 327 sorted" reads as a broken sorter, and the
# operator has no way to see which items fell through or why.
_RESIDUAL_LANE = ("explicit_rest", "explicit 1:1",
                  "explicit, but not mass-safe and not a clean $10/$50 reveal — "
                  "sell these in conversation")


async def collect_purpose_folders(
    account_id: str, *, media_ids: Iterable[int] | None = None,
    solo: bool = False,
) -> list[dict[str, Any]]:
    """Re-cut a pool of media into the send lanes, by heat rather than outfit.

    `media_ids` restricts the pool — pass the items of the shoots you did NOT
    keep, so strong scripts stay intact as shoots and only the leftovers get
    repurposed. Omit it to consider the whole vault.

    `solo` ADDS a `-solo` cut of every lane that has one: the same lane, keeping
    only the items nobody else is in (`is_solo`). It adds rather than filters
    because the two answer different questions — "what may I send here" and
    "what may I send here to a fan who only wants her" — and an operator who
    wants both should not have to rebuild the folders to switch.

    Read-only; an item may legitimately appear in more than one lane.
    """
    rows = await _load_rows(account_id)
    if media_ids is not None:
        wanted = {int(m) for m in media_ids}
        rows = [r for r in rows if r["media_id"] in wanted]

    enriched = [{**r, "why": send_order_reason(r.get("fields") or {})} for r in rows]

    def _folder(slug: str, name: str, purpose: str, picked: list[dict[str, Any]],
                *, solo_of: int | None = None) -> dict[str, Any]:
        """One lane. `solo_of` is the size of the lane this was cut FROM, and is
        what makes it a cut rather than a lane — every folder carries both keys
        so no consumer has to test for their presence."""
        picked.sort(key=lambda r: send_sort_key(r["fields"], media_id=r["media_id"]))
        kinds: dict[str, int] = {}
        tier_counts: dict[str, int] = {}
        for r in picked:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
            tier_counts[r["why"]["tier"]] = tier_counts.get(r["why"]["tier"], 0) + 1
        return {
            "lane": slug, "name": ai_folder_name(name), "purpose": purpose,
            "size": len(picked), "kinds": kinds, "tiers": tier_counts,
            "closes_on_own": sum(1 for r in picked if r["why"]["closes"]),
            "solo": solo_of is not None, "solo_of": solo_of,
            "items": [{**r, "manual_order": i + 1}
                      for i, r in enumerate(picked)],
        }

    def _solo_cut(lane: dict[str, Any]) -> dict[str, Any] | None:
        """`lane` keeping only the items nobody else is in, or None when that is
        nothing. Cut from the FINISHED lane rather than by re-running the
        predicates over a pre-filtered pool: a solo folder has to be a subset of
        the lane it is named after, or `AI-tease 10-solo` is a promise about a
        folder whose contents were never in `AI-tease 10`. An empty cut is
        dropped — mirrored to OF, it is a real empty list on her account."""
        picked = [r for r in lane["items"] if is_solo(r.get("fields") or {})]
        if not picked:
            return None
        return _folder(f"{lane['lane']}_solo", f"{lane['name']}-solo",
                       f"{lane['purpose']} — her alone, nobody else in frame",
                       picked, solo_of=lane["size"])

    out: list[dict[str, Any]] = []
    claimed: set[int] = set()
    for slug, name, purpose, matches in PURPOSE_LANES:
        picked = [r for r in enriched
                  if matches(r["why"], r.get("fields") or {}, r["kind"])]
        # No MIN_SCRIPT_ITEMS here: that floor exists because a 2-item SHOOT is
        # a pair, not a script. A lane is a bucket — two story-safe stills is a
        # perfectly good Stories folder, and suppressing it would silently hide
        # material the operator can post.
        if not picked:
            continue
        claimed.update(r["media_id"] for r in picked)
        out.append(_folder(slug, name, purpose, picked))

    # Nothing paid falls through. `stories` already takes every sfw/suggestive
    # item, so an orphan is always paid-tier — see `_RESIDUAL_LANE`.
    rest = [r for r in enriched
            if r["media_id"] not in claimed and r["why"]["tier"] in _PAID_TIERS]
    if rest:
        out.append(_folder(*_RESIDUAL_LANE, rest))

    if solo:
        # Built whole before extending `out` — never appended to the list being
        # walked. A lane with nothing solo in it yields no cut.
        cuts = [c for c in map(_solo_cut, out) if c is not None]
        out.extend(cuts)
    return out


# ── The whole plan: what the vault button previews and creates ──────
#
# One call so the UI previews EXACTLY what it will create. `apply_ai_folders`
# deliberately re-derives the plan server-side instead of trusting a posted list
# of media ids: the preview an operator looked at may be minutes old, and the
# vault can shift underneath it (a collect sweep, a duplicate hidden). Re-deriving
# means the worst case is "you got the current answer", not "you got a stale one
# written as fact".

async def flags_coverage(account_id: str) -> dict[str, Any]:
    """How many of the account's stills carry the exposure flags.

    `ready` is False when ANY still is missing them: the paid tiers silently
    fall back to `clothing_state` for those items, which is the unreliable
    signal the flags exist to replace.
    """
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem.ai_fields_json).where(
                VaultItem.account_id == account_id,
                VaultItem.removed_at.is_(None),
                VaultItem.kind == "photo")
        )).all()
    stills = len(rows)
    flagged = 0
    for (fj,) in rows:
        fields = vault_ai_brief.load_fields(fj)
        if vault_ai_brief.flags_known(fields):
            flagged += 1
    return {
        "stills": stills, "flagged": flagged,
        "missing": stills - flagged,
        "ready": stills > 0 and flagged == stills,
    }


async def solo_coverage(account_id: str) -> dict[str, Any]:
    """How many described items can be READ as solo or not, and how many are.

    `is_solo` refuses to call an item solo without the evidence, so on a vault
    described by the V1 prompt every `-solo` folder comes out empty — correctly,
    and unreadably. This is what the UI shows instead of nothing: N of M items
    have never been asked who else is in them, and a re-scan is what fixes it.
    """
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem.ai_fields_json).where(
                VaultItem.account_id == account_id,
                VaultItem.removed_at.is_(None),
                VaultItem.describe_status == "described")
        )).all()
    known = solo = 0
    for (fj,) in rows:
        fields = vault_ai_brief.load_fields(fj)
        if not solo_known(fields):
            continue
        known += 1
        if is_solo(fields):
            solo += 1
    described = len(rows)
    return {"described": described, "known": known,
            "unknown": described - known, "solo": solo,
            "ready": described > 0 and known == described}


async def plan_ai_folders(
    account_id: str, *, keep: int = 2,
    window_hours: int = DEFAULT_OUTFIT_WINDOW_HOURS,
    min_items: int = MIN_SCRIPT_ITEMS,
    solo: bool = False,
) -> dict[str, Any]:
    """Every folder the pipeline proposes, scripts and lanes together.

    `keep` — how many of the top-ranked shoots stay as their own script folder.
    Lanes are always cut from the WHOLE vault, not just the shoots that were not
    kept: the explicit material a paid tease needs lives inside the good shoots,
    so restricting them to leftovers empties those lanes. An item belonging to
    both a script and a lane is the design.

    `solo` adds a `-solo` cut of each lane (see `collect_purpose_folders`).
    """
    shoots = await collect_outfit_scripts(
        account_id, window_hours=window_hours, min_items=min_items)
    lanes = await collect_purpose_folders(account_id, solo=solo)

    def _folder(name: str, source: str, purpose: str,
                items: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        tiers: dict[str, int] = {}
        for r in items:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
            tiers[r["why"]["tier"]] = tiers.get(r["why"]["tier"], 0) + 1
        return {
            "name": name, "source": source, "purpose": purpose,
            "size": len(items), "kinds": kinds, "tiers": tiers,
            "closes_on_own": sum(1 for r in items if r["why"]["closes"]),
            # Defaults, so EVERY folder answers "are you a solo cut" — a script
            # is not one. `extra` overrides for the lanes, which know.
            "solo": False, "solo_of": None,
            "items": [
                {"media_id": r["media_id"], "kind": r["kind"],
                 "manual_order": r["manual_order"], "score": r.get("score"),
                 "tier": r["why"]["tier"], "closes": r["why"]["closes"],
                 "clothing_state": r["why"]["clothing_state"]}
                for r in items
            ],
            **extra,
        }

    folders = [
        _folder(s["name"], "script", f"one shoot — {s['outfit']}", s["items"],
                outfit=s["outfit"], mixed=s["mixed"])
        for s in shoots[:max(0, keep)]
    ] + [
        _folder(f["name"], "lane", f["purpose"], f["items"], lane=f["lane"],
                solo=f["solo"], solo_of=f["solo_of"])
        for f in lanes
    ]

    unique = {r["media_id"] for f in folders for r in f["items"]}

    # How much of this account has been through the cheap flags pass. Without
    # it `_is_nude()` falls back to `clothing_state`, which was measured wrong
    # on ~1 in 3 of the stills the $50 tier is built from — so the folders would
    # come out quietly wrong rather than visibly broken. The caller surfaces
    # this so an operator is never one click from that.
    coverage = await flags_coverage(account_id)
    # Only when asked: it is a second full read of the vault, and it answers a
    # question nobody has posed unless the box is ticked.
    solo_cov = await solo_coverage(account_id) if solo else None

    return {
        "account_id": account_id,
        "keep": keep,
        "solo": solo,
        "shoots_found": len(shoots),
        "flags": coverage,
        "solo_coverage": solo_cov,
        "folders": folders,
        "summary": {
            "folders": len(folders),
            "scripts": sum(1 for f in folders if f["source"] == "script"),
            # `solo_cuts`, not `solo`: the plan's own `solo` is the bool that
            # was ASKED for, and one payload carrying both under one name is a
            # question waiting to be answered wrong.
            "lanes": sum(1 for f in folders
                         if f["source"] == "lane" and not f["solo"]),
            "solo_cuts": sum(1 for f in folders if f["solo"]),
            "unique_media": len(unique),
            "memberships": sum(f["size"] for f in folders),
        },
    }


async def apply_ai_folders(account_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Create the planned folders and fill them, in send order.

    Re-runnable: a folder whose `AI-` name already exists is REUSED and its
    membership rewritten, so pressing the button twice refreshes rather than
    piling up duplicates. Only `AI-`-prefixed folders are ever touched — a
    folder an operator made by hand is never rewritten, even on a name clash.

    Internal folders only. No OF writes, nothing sent.
    """
    from db.models import VaultFolder  # lazy: keeps the import graph flat

    created: list[dict[str, Any]] = []
    async with get_session() as s:
        for spec in plan.get("folders") or []:
            name = ai_folder_name(spec["name"])
            existing = (await s.execute(
                select(VaultFolder).where(
                    VaultFolder.account_id == account_id,
                    VaultFolder.name == name,
                    VaultFolder.deleted_at.is_(None),
                )
            )).scalars().first()

            if existing is not None:
                folder_id = existing.id
                reused = True
                # Wipe only THIS folder's membership so the rewrite is clean;
                # the media itself and every other folder are untouched.
                await s.execute(
                    VaultFolderItem.__table__.delete().where(
                        (VaultFolderItem.account_id == account_id)
                        & (VaultFolderItem.folder_id == folder_id)
                    )
                )
            else:
                folder = VaultFolder(account_id=account_id, name=name,
                                     created_by="vault_ai_script")
                s.add(folder)
                await s.flush()
                folder_id = folder.id
                reused = False

            for entry in spec.get("items") or []:
                s.add(VaultFolderItem(
                    account_id=account_id, folder_id=folder_id,
                    media_id=int(entry["media_id"]),
                    manual_order=int(entry["manual_order"]),
                ))
            created.append({"folder_id": folder_id, "name": name,
                            "items": len(spec.get("items") or []),
                            "reused": reused, "source": spec.get("source")})

        # Retire generated folders the CURRENT plan no longer produces. Without
        # this, every rule or naming change leaves its output behind and the
        # folder list silently accumulates two generations of the same idea.
        #
        # Scoped hard: only rows this module created (`created_by`) AND carrying
        # the AI- prefix are ever retired, and only by soft-delete. An operator's
        # own folder cannot be reached by this even if it collides on name.
        wanted = {c["name"] for c in created}
        stale = (await s.execute(
            select(VaultFolder).where(
                VaultFolder.account_id == account_id,
                VaultFolder.created_by == "vault_ai_script",
                VaultFolder.deleted_at.is_(None),
            )
        )).scalars().all()
        retired: list[dict[str, Any]] = []
        for folder in stale:
            if folder.name in wanted or not folder.name.startswith(AI_FOLDER_PREFIX):
                continue
            folder.deleted_at = datetime.utcnow()
            retired.append({"folder_id": folder.id, "name": folder.name,
                            "of_list_id": folder.of_list_id})
        await s.commit()

    log.info("AI folders applied account=%s folders=%d items=%d retired=%d",
             account_id, len(created), sum(c["items"] for c in created), len(retired))
    return {
        "created": created,
        "folders": len(created),
        "new": sum(1 for c in created if not c["reused"]),
        "reused": sum(1 for c in created if c["reused"]),
        "items": sum(c["items"] for c in created),
        # Retired locally only. Any OF list these were mirrored to is left
        # alone: deleting a folder on her real account is not something a
        # rename in our rules should trigger.
        "retired": retired,
    }
