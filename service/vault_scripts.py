"""service/vault_scripts.py — recover the SCRIPT a vault batch was shot as.

A creator does not shoot media one item at a time. She shoots a *script*: a run
of clips that escalates, almost always along the same arc —

    clothed  →  stripping / lingerie  →  nude  →  touching  →  masturbation

Every item's rung on that ladder is already in the V2 describe fields
(`clothing_state`, `acts`, `penetration`), so scoring is pure arithmetic over
data we have: no LLM call, no OF traffic, instant re-run.

This module scores each item on that ladder (`escalation_score`), orders items
for sending (`send_sort_key`),
groups shoots by outfit and room into capped ladders (`collect_outfit_scripts`) and cuts purpose lanes
(`collect_purpose_folders`). `plan_ai_folders` turns both into a folder
proposal and `apply_ai_folders` writes it as internal `AI-` folders.

Nothing here mutates OF. `plan_ai_folders` is read-only; `apply_ai_folders`
writes only our own folder rows.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Callable, Iterable

from sqlalchemy import select

import vault_ai_brief
import vault_dupes
import vault_topic_folders
from db.engine import get_session
from db.models import VaultFolder, VaultFolderItem, VaultItem

log = logging.getLogger("of-relay.vault_scripts")

# Owner rule 2026-11-13: a script is a night's ladder — at least 10 pieces, at
# least 2 of them clips. A shoot that cannot fill that is not proposed.
MIN_SCRIPT_ITEMS = 10
MIN_SCRIPT_VIDEOS = 2


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
        # Every lane, price and copy reader below sees the least-harmful
        # reading of an item whose two passes disagree (`settled_reading`).
        fields = vault_ai_brief.settled_reading(
            vault_ai_brief.load_fields(fields_json))
        out.append({
            "media_id": int(mid), "kind": kind, "created_at": created,
            "duration_seconds": dur, "fields": fields, "describe_status": status,
            "score": escalation_score(fields),
        })
    return out


# ── Duplicates: one copy per folder ─────────────────────────────────
#
# Re-uploads are ~30% of a real vault (`vault_dupes`), and the describe sweep
# shares one answer across each duplicate set — so every copy reads the same,
# keys to the same outfit and passes the same lane tests. Left in, one folder
# holds the same photo two or three times. Each set is collapsed to ONE row
# before anything is grouped.
#
# The sets are the Duplicates screen's at its recommended threshold, from the
# hashes already stored (`rehash=False`): the preview stays read-only and
# instant, and an item not hashed yet simply is not a candidate.


async def _dupe_groups(account_id: str) -> list[list[int]]:
    """The account's duplicate sets, each as media ids oldest first (original,
    then copies). Any failure logs and returns [] — a plan without the collapse
    beats no plan."""
    try:
        res = await vault_dupes.find_duplicates(account_id, rehash=False)
    except Exception:  # noqa: BLE001
        log.exception("dupe scan failed account=%s — planning without collapse", account_id)
        return []
    return [[int(m["media_id"]) for m in (c["original"], *c["dupes"])]
            for c in res["clusters"]]


def collapse_dupes(rows: list[dict[str, Any]], groups: list[list[int]],
                   ) -> tuple[list[dict[str, Any]], list[int]]:
    """`rows` with each duplicate set down to its kept item, + the dropped ids.

    The kept item is the set's original (earliest upload — the copy the
    Duplicates screen never hides), unless it carries no reading and a later
    copy does: then the earliest copy that does, so a set is never lost to the
    one member the describe pass skipped. Rows keep their order."""
    by_id = {r["media_id"]: r for r in rows}
    drop: set[int] = set()
    for group in groups:
        present = [m for m in group if m in by_id]
        if len(present) < 2:
            continue
        keeper = next((m for m in present if by_id[m].get("fields")), present[0])
        drop.update(m for m in present if m != keeper)
    return [r for r in rows if r["media_id"] not in drop], sorted(drop)


async def _grouping_rows(account_id: str) -> tuple[list[dict[str, Any]], list[int]]:
    """The rows shoots and lanes are cut from (dupes collapsed) + dropped ids."""
    return collapse_dupes(await _load_rows(account_id), await _dupe_groups(account_id))


# ── Send order ──────────────────────────────────────────────────────
#
# `escalation_score` above answers "how far along the arc is this?" — one
# monotone number, deliberately coarse.
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
#  3. reveal tension — dressed → lingerie → mid-strip → fully_nude (Jev's
#     clothing-state `outfit` when the describe gave none). Chronological
#     within the strip, which is also how it was filmed. Note this is ORDER, not
#     value: `vault_ai_brief` correctly ranks the "almost" states as the highest
#     VALUE to sell, but they still come before full nudity in a night.
#  4. the act ladder — fine-grain within all of the above.
#  5. reveal — how many regions are bare (flags pass, else Jev), so a burst of
#     same-state frames still walks covered → bare.
#  6. media id — a stable last tie-break, so equal keys never reorder between runs.
#
# Anything we cannot place lands last, never in the opening slot.

_CLOTHING_PROGRESS: dict[str, int] = {
    "dressed": 0, "lingerie_on": 1, "partially_off": 2,
    "pulled_down": 3, "pulled_aside": 4, "fully_nude": 5,
}

_UNKNOWN = 99

# Jev `outfit` is a clothing STATE, not an outfit (it changes within a shoot, so
# it is never a grouping key). On `_CLOTHING_PROGRESS`'s scale it stands in for
# a missing describe `clothing_state`.
_JEV_OUTFIT_PROGRESS: dict[str, int] = {
    "everyday_clothes": 0, "sheet_or_towel": 1, "swimwear": 1,
    "lingerie_or_bodysuit": 1, "topless_with_bottoms": 3, "nude": 5,
}

# (flags-pass region, Jev bare answer) — the regions `reveal_strength` counts.
_REVEAL_REGIONS = (("breasts_vis", "breasts_bare"), ("vulva_vis", "crotch_bare"),
                   ("anus_vis", None))


def _jev_tag(fields: dict[str, Any], q: str) -> str:
    """Jev's answer to choice question `q` on a current `_jev`, else ''."""
    jev = vault_topic_folders.jev_of(fields)
    return _norm(vault_topic_folders._tag(jev, q)) if jev else ""


def reveal_strength(fields: dict[str, Any]) -> int:
    """How many regions (breasts / vulva / anus) are bare, 0-3: the flags pass,
    else Jev's bare answers. Orders items the rung, payoff, clothing and act
    axes leave tied — a topless frame after a covered one — instead of upload
    id."""
    jev = vault_topic_folders.jev_of(fields) or {}
    return sum(1 for flag, jkey in _REVEAL_REGIONS
               if (vault_ai_brief.is_bare(fields, flag) if vault_ai_brief.vis(fields, flag)
                   else bool(jkey and jev.get(jkey) == "y")))


def send_sort_key(fields: dict[str, Any], *, media_id: int = 0) -> tuple[int, ...]:
    """Sort key placing an item in SEND order — tease first, payoff last."""
    sell = vault_ai_brief.sellability(fields)

    rung = sell["rung"] if sell["rung"] is not None else _UNKNOWN
    closes = 1 if sell["stands_alone"] else 0
    clothing = _CLOTHING_PROGRESS.get(_norm(fields.get("clothing_state")))
    if clothing is None:
        clothing = _JEV_OUTFIT_PROGRESS.get(_jev_tag(fields, "outfit"), _UNKNOWN)
    act = escalation_score(fields)
    return (rung, closes, clothing, act if act is not None else _UNKNOWN,
            reveal_strength(fields), media_id)


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
        "clothing_state": sell["clothing"] or "unclear",
        "solo": sell["solo"],
        # The clip's raw progression in the describe pass's words; a disputed
        # item's prose is the half that may be wrong, so none of it is shown.
        "beats": [] if vault_ai_brief.is_disputed(fields)
        else [b for b in (fields.get("beats") or []) if str(b).strip()],
        "acts": vault_ai_brief.claimed_acts(fields),
    }


# ── Outfit scripts (what a script actually IS) ──────────────────────
#
# A script is a SHOOT: one outfit, worn across both stills and clips, escalating
# from covered to explicit, uploaded around the same time. Upload bursts are
# kind-PURE (photos in one go, clips in another), so the linking signal is the
# OUTFIT, already in the describe output as `clothing_items`. On the graded vault:
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

_GARMENT_CLASS_NAMES = frozenset(name for name, _ in _GARMENT_CLASSES)

# Two different shoots in the same colour must not merge just because the colour
# matches. 48h keeps a shoot whose stills and clips went up on consecutive
# nights together (the graded vault's pink set spans 26 hours) while separating a black
# set shot a week later.
DEFAULT_OUTFIT_WINDOW_HOURS = 48

# How many top shoots stay as their own script folder when the caller does not say.
DEFAULT_KEEP_SCRIPTS = 10


def short_outfit(outfit: str) -> str:
    """`pink lingerie_set` → `pink lingerie`. The outfit key is a machine key;
    this is what a human reads in a folder list."""
    return str(outfit).replace("_set", "").replace("_", " ").strip()


def _clothing_text(fields: dict[str, Any]) -> str:
    """The describe's clothing_items, lowercased and space-joined."""
    return " ".join(str(x).lower() for x in (fields.get("clothing_items") or []))


def outfit_colour(fields: dict[str, Any]) -> str:
    """The item's dominant garment colour, else its material. '' if unnamed."""
    if not isinstance(fields, dict):
        return ""
    text = _clothing_text(fields)
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
    text = _clothing_text(fields)
    for name, words in _GARMENT_CLASSES:
        if any(w in text for w in words):
            return name
    return ""


# `setting` values that name no place, so cannot stand in for a colour.
_NO_SETTING = frozenset({"", "other", "unclear", "unknown", "none"})


def outfit_key(fields: dict[str, Any]) -> str:
    """The outfit an item belongs to: `"<colour> <garment class>"`.

    A colour with no recognised garment class still keys on the colour alone,
    so a set is never dropped just because its wording is unusual.

    No colour (or material) named: `"<garment class> <setting>"` — a bra shot
    in the bedroom — so a set the model described without its colour still
    groups instead of vanishing. Both halves are required: a garment class
    alone, or a room alone, would pool unrelated outfits into one junk group.
    Empty string when neither key holds; those items are left out.
    """
    if not isinstance(fields, dict):
        return ""
    colour = outfit_colour(fields)
    kind = garment_class(fields)
    if colour:
        return f"{colour} {kind}".strip()
    setting = _norm(fields.get("setting"))
    if kind and setting not in _NO_SETTING:
        return f"{kind} {setting}"
    return ""


def _with_why(r: dict[str, Any]) -> dict[str, Any]:
    """`r` plus its `why` (send_order_reason of its fields)."""
    return {**r, "why": send_order_reason(r.get("fields") or {})}


_SUGGESTIVE = vault_ai_brief.EXPLICITNESS_LADDER.index("suggestive")
_EXPLICIT = vault_ai_brief.EXPLICITNESS_LADDER.index("explicit")


def earns_paid_rung(fields: dict[str, Any]) -> bool:
    """Owner rule 2026-11-13: explicit / hardcore in a script means her pussy is
    on show (flags pass; Jev only where the flags left it unanswered) or a real
    act is in frame. Live AE: 114 of 160 'explicit' items were a covered or
    out-of-frame crotch — a bare butt in a thong — and both passes agreed."""
    if vault_ai_brief.vis(fields, "vulva_vis"):
        bare = vault_ai_brief.is_bare(fields, "vulva_vis")
    else:
        bare = (vault_topic_folders.jev_of(fields) or {}).get("crotch_bare") == "y"
    return (bare or vault_ai_brief.genital_act_claimed(fields)
            or vault_ai_brief.sellability(fields)["stands_alone"])


def _with_script_why(r: dict[str, Any]) -> dict[str, Any]:
    """`_with_why`, with an unearned explicit / hardcore rung (`earns_paid_rung`)
    sent as suggestive. Scripts only; the price lanes keep their own rules."""
    out = _with_why(r)
    why = out["why"]
    if why["rung"] is not None and why["rung"] >= _EXPLICIT \
            and not earns_paid_rung(r.get("fields") or {}):
        out["why"] = {**why, "rung": _SUGGESTIVE, "tier": "suggestive",
                      "labelled": why["tier"]}
    return out


def _script_sort_key(r: dict[str, Any]) -> tuple[int, ...]:
    """`send_sort_key` with the script rung (`_with_script_why`) in front."""
    return (r["why"]["rung"], *send_sort_key(r["fields"], media_id=r["media_id"])[1:])


def _ordered_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`rows` in order, each stamped with its 1-based `manual_order`."""
    return [{**r, "manual_order": i + 1} for i, r in enumerate(rows)]


def _tally(items: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int], int]:
    """(kinds, tiers, closes_on_own) over enriched rows — the counts every
    shoot and lane carries."""
    kinds: dict[str, int] = {}
    tiers: dict[str, int] = {}
    for r in items:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        tiers[r["why"]["tier"]] = tiers.get(r["why"]["tier"], 0) + 1
    return kinds, tiers, sum(1 for r in items if r["why"]["closes"])


# Sendable-ladder sizes: a script folder is what an operator walks ONE fan
# through in a night, not the whole shoot. Live AE 2026-11-13: one script held
# 93 items. Per band, at most:
SCRIPT_OPENERS = 3    # non-closers on the script's lowest rung — the free hook
SCRIPT_MIDDLE = 4     # the build-up above it
SCRIPT_CLOSERS = 3    # items that close a sale on their own
SCRIPT_SIZE = SCRIPT_OPENERS + SCRIPT_MIDDLE + SCRIPT_CLOSERS

# Burst frames of one pose are near-identical: looser than the Duplicates
# screen's re-upload match (`vault_dupes.DEFAULT_THRESHOLD`, 2) — the "similar"
# band's top — and only ever applied inside one rung of one script.
NEAR_DUPE_THRESHOLD = 5


def item_room(fields: dict[str, Any]) -> str:
    """Where it was shot: Jev's `setting` on a current `_jev`, else the
    describe's `setting`. '' when neither names a place ('other' does not)."""
    room = _jev_tag(fields, "setting") or _norm(fields.get("setting"))
    return "" if room in _NO_SETTING else room


def split_by_room(items: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """[(room, items)] — one part per room. An item with no room joins the part
    holding the item nearest it in created_at (a tie → the largest part, by its
    roomed items). No room anywhere: one part, room ''. Item order is kept."""
    roomed: dict[str, list[dict[str, Any]]] = {}
    for r in items:
        room = item_room(r.get("fields") or {})
        if room:
            roomed.setdefault(room, []).append(r)
    if not roomed:
        return [("", list(items))]
    sizes = {room: len(rs) for room, rs in roomed.items()}

    def _gap(a: dict[str, Any], b: dict[str, Any]) -> float:
        if a["created_at"] is None or b["created_at"] is None:
            return 0.0
        return abs((a["created_at"] - b["created_at"]).total_seconds())

    home: dict[int, str] = {}
    for r in items:
        room = item_room(r.get("fields") or {})
        if not room:
            room = min(roomed, key=lambda k: (min(_gap(r, x) for x in roomed[k]), -sizes[k], k))
        home[r["media_id"]] = room
    return [(room, [r for r in items if home[r["media_id"]] == room]) for room in sorted(roomed)]


async def _fingerprints(account_id: str) -> dict[int, dict[str, Any]]:
    """Stored thumb hashes by media id (`vault_dupes.load_fingerprints`, no
    hashing). Any failure logs and returns {} — no near-dupe collapse."""
    try:
        items, _ = await vault_dupes.load_fingerprints(account_id)
    except Exception:  # noqa: BLE001
        log.exception("fingerprint load failed account=%s — no near-dupe collapse", account_id)
        return {}
    return {int(fp["media_id"]): fp for fp in items}


def _near(a: dict[str, Any] | None, b: dict[str, Any] | None, threshold: int) -> bool:
    """Same kind, within `threshold` on dhash AND ahash (clips: duration ±1s too),
    as `vault_dupes.cluster` compares."""
    if not a or not b or a["kind"] != b["kind"]:
        return False
    if a["kind"] == "video" and abs((a.get("duration") or 0) - (b.get("duration") or 0)) > \
            vault_dupes._VIDEO_DUR_TOLERANCE_S:
        return False
    if a["md5"] == b["md5"]:
        return True
    return (vault_dupes.hamming(a["dhash"], b["dhash"]) <= threshold
            and vault_dupes.hamming(a["ahash"], b["ahash"]) <= threshold)


def collapse_near_dupes(items: list[dict[str, Any]], prints: dict[int, dict[str, Any]],
                        threshold: int = NEAR_DUPE_THRESHOLD,
                        ) -> tuple[list[dict[str, Any]], list[int]]:
    """`items` (send order, enriched) minus burst frames near-identical to a kept
    item on the same rung, + the dropped ids. Items with a current Jev reading
    are kept first; then send order. Unhashed items are never dropped."""
    order = sorted(range(len(items)), key=lambda i: (
        vault_topic_folders.jev_of(items[i].get("fields")) is None, i))
    kept: list[int] = []
    dropped: list[int] = []
    for i in order:
        r = items[i]
        fp = prints.get(r["media_id"])
        if fp is not None and any(
                items[j]["why"]["rung"] == r["why"]["rung"]
                and _near(fp, prints.get(items[j]["media_id"]), threshold) for j in kept):
            dropped.append(r["media_id"])
            continue
        kept.append(i)
    return [items[i] for i in sorted(kept)], sorted(dropped)


def ladder_bands(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """{opener, middle, closer}: closers close on their own; openers are the
    other items on the lowest rung; middle is the rest. Order kept."""
    closers = [r for r in items if r["why"]["closes"]]
    rest = [r for r in items if not r["why"]["closes"]]
    low = min((r["why"]["rung"] for r in rest), default=None)
    return {"opener": [r for r in rest if r["why"]["rung"] == low],
            "middle": [r for r in rest if r["why"]["rung"] != low],
            "closer": closers}


def _traits(r: dict[str, Any], *, kind: bool = True) -> set[tuple[str, Any]]:
    why = r["why"]
    out = {("rung", why["rung"]), ("clothing", why["clothing_state"]),
           ("acts", tuple(why["payoff_acts"]))}
    if kind:
        out.add(("kind", r["kind"]))
    return out


def _pick_varied(pool: list[dict[str, Any]], k: int, *, kind: bool = True) -> list[dict[str, Any]]:
    """Up to `k` of `pool` (best first), each the least like those already
    picked (rung / clothing / payoff acts / kind); ties go to the better one."""
    pool = list(pool)
    chosen: list[dict[str, Any]] = []
    seen: set[tuple[str, Any]] = set()
    while pool and len(chosen) < k:
        i = min(range(len(pool)), key=lambda i: (len(_traits(pool[i], kind=kind) & seen), i))
        r = pool.pop(i)
        chosen.append(r)
        seen |= _traits(r, kind=kind)
    return chosen


def cap_ladder(items: list[dict[str, Any]], *, min_videos: int | None = None
               ) -> tuple[list[dict[str, Any]], list[int]]:
    """`items` (send order) cut to a sendable ladder — at most SCRIPT_OPENERS /
    SCRIPT_MIDDLE / SCRIPT_CLOSERS per band, varied; closers prefer clips, then
    the bigger payoff — in send order, + the overflow ids (not in the script)."""
    bands = ladder_bands(items)
    pos = {r["media_id"]: i for i, r in enumerate(items)}
    closers = sorted(bands["closer"], key=lambda r: (
        r["kind"] != "video", -(r.get("score") or 0), pos[r["media_id"]]))
    keep = {r["media_id"] for r in (
        _pick_varied(bands["opener"], SCRIPT_OPENERS)
        + _pick_varied(bands["middle"], SCRIPT_MIDDLE)
        + _pick_varied(closers, SCRIPT_CLOSERS, kind=False))}
    # A thin band leaves room: fill to SCRIPT_SIZE from what is left, varied.
    left = [r for r in items if r["media_id"] not in keep]
    keep |= {r["media_id"] for r in _pick_varied(left, SCRIPT_SIZE - len(keep))}
    # Too few clips: swap the latest-sent kept photo of a band for that band's
    # best left-out clip, until MIN_SCRIPT_VIDEOS or no swap is left.
    band_of = {r["media_id"]: b for b, rs in bands.items() for r in rs}
    want = MIN_SCRIPT_VIDEOS if min_videos is None else min_videos
    while sum(1 for r in items if r["media_id"] in keep and r["kind"] == "video") < want:
        swap = next(((v, p) for v in items if v["kind"] == "video" and v["media_id"] not in keep
                     for p in reversed(items) if p["kind"] == "photo" and p["media_id"] in keep
                     and band_of[p["media_id"]] == band_of[v["media_id"]]), None)
        if swap is None:
            swap = next(((v, p) for v in items if v["kind"] == "video" and v["media_id"] not in keep
                         for p in reversed(items) if p["kind"] == "photo" and p["media_id"] in keep
                         and not p["why"]["closes"]), None)
        if swap is None:
            break
        keep.discard(swap[1]["media_id"])
        keep.add(swap[0]["media_id"])
    return ([r for r in items if r["media_id"] in keep],
            [r["media_id"] for r in items if r["media_id"] not in keep])


def _band_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    return {k: len(v) for k, v in ladder_bands(items).items()}


# The plan's `rungs` indices, as an operator reads them.
_RUNG_WORDS = ("sfw", "suggestive", "explicit", "hardcore")


def _rung_word(r: int) -> str:
    return _RUNG_WORDS[r] if 0 <= r < len(_RUNG_WORDS) else f"rung {r}"


def _rungs_label(rungs: list[int]) -> str:
    """`suggestive → explicit` (contiguous) or `suggestive, hardcore` (a rung skipped)."""
    if len(rungs) > 1 and rungs[-1] - rungs[0] + 1 == len(rungs):
        return f"{_rung_word(rungs[0])} → {_rung_word(rungs[-1])}"
    return ", ".join(_rung_word(r) for r in rungs)


def _ladder_full(rungs: list[int]) -> bool:
    """Three or more rungs, none skipped."""
    return len(rungs) >= 3 and rungs[-1] - rungs[0] + 1 == len(rungs)


def script_health(s: dict[str, Any]) -> list[str]:
    """What an operator should know before sending this script — short phrases,
    worst first; [] when it is a clean full ladder."""
    out: list[str] = []
    if s.get("borrowed"):
        out.append("borrowed closer")
    elif not s["closes_on_own"]:
        out.append("no closer")
    kinds = s["kinds"]
    if set(kinds) == {"photo"}:
        out.append("photos only")
    elif set(kinds) == {"video"}:
        out.append("clips only")
    if not _ladder_full(s["rungs"]):
        out.append(_rungs_label(s["rungs"]))
    if s.get("capped_from"):
        out.append(f"capped from {s['capped_from']}")
    if s.get("near_dupes"):
        n = len(s["near_dupes"])
        out.append(f"{n} near-duplicate{'s' if n != 1 else ''} dropped")
    if s.get("unplaced"):
        out.append(f"{s['unplaced']} unrated at end")
    return out


def script_name(outfit: str, room: str, started: datetime | None) -> str:
    """`AI-<colour garment> · <room> · <Mon D>` (the part's start date). No
    counts: they would rename the folder on every rebuild."""
    shown_room = room.replace("_", " ")
    head = outfit.split(" ", 1)[0]
    # A colourless key is "<garment class> <describe setting>"; the room part
    # already names the place, so show the garment alone.
    label = short_outfit(head if head in _GARMENT_CLASS_NAMES else outfit)
    date = f"{started:%b} {started.day}" if started else ""
    return ai_folder_name(" · ".join(p for p in (label, shown_room, date) if p))


def _shoot(outfit: str, room: str, part: list[dict[str, Any]], prints: dict[int, dict[str, Any]],
           *, min_items: int, require_escalation: bool,
           min_videos: int) -> dict[str, Any] | None:
    """One room's part of an outfit segment as a script, or None when it is not
    one (too small, one rung). Placed items are near-dupe collapsed and capped;
    rung-less (unknown explicitness) rows ride after the ladder uncapped —
    lanes skip them too, so dropping them here would file them nowhere."""
    placed = sorted((r for r in part if r["why"]["rung"] is not None), key=_script_sort_key)
    unplaced = sorted((r for r in part if r["why"]["rung"] is None),
                      key=lambda r: r["media_id"])
    deduped, near = collapse_near_dupes(placed, prints)
    if len(deduped) < min_items:
        return None
    if require_escalation and len({r["why"]["rung"] for r in deduped}) < 2:
        return None
    ladder, overflow = cap_ladder(deduped, min_videos=min_videos)
    if len(ladder) < min_items or sum(1 for r in ladder if r["kind"] == "video") < min_videos:
        return None
    dated = [r["created_at"] for r in part if r["created_at"]]
    started = min(dated) if dated else None
    # Kinds / tiers describe the folder as filed (tail included); `size`,
    # `rungs` and `bands` describe the ladder.
    kinds, tiers, closes = _tally(ladder + unplaced)
    shoot = {
        "outfit": outfit, "room": room,
        "colour": outfit_colour(part[0].get("fields") or {}),
        "name": script_name(outfit, room, started),
        "size": len(ladder), "kinds": kinds, "tiers": tiers,
        "rungs": sorted({r["why"]["rung"] for r in ladder}),
        "bands": _band_counts(ladder),
        "mixed": len(kinds) > 1,
        "closes_on_own": closes,
        "started_at": started,
        "ended_at": max(dated) if dated else None,
        "capped_from": len(deduped) if overflow else None,
        "overflow": overflow, "near_dupes": near,
        "borrowed": None, "unplaced": len(unplaced),
        "items": _ordered_items(ladder + unplaced),
    }
    shoot["health"] = script_health(shoot)
    return shoot


async def collect_outfit_scripts(
    account_id: str, *, window_hours: int = DEFAULT_OUTFIT_WINDOW_HOURS,
    min_items: int | None = None, require_escalation: bool = True,
    min_videos: int | None = None,
    rows: list[dict[str, Any]] | None = None,
    prints: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Shoots, recovered by outfit, then room. Read-only.

    `rows` — the pool, as `_grouping_rows` returns it; loaded when omitted.
    `prints` — stored thumb hashes by media id (`_fingerprints`); loaded when
    omitted.

    An outfit is split where it goes quiet for `window_hours`, then by room
    (`split_by_room`): created_at is OF's upload time, and a bulk upload puts a
    whole day's shoots inside one second, so the gap alone never cuts them.
    Each part drops burst near-duplicates (`collapse_near_dupes`) and is capped
    to a sendable ladder (`cap_ladder`); what is cut is still in the vault and
    in the lanes.

    `require_escalation` drops parts that sit on ONE explicitness rung — a run
    of eight equally-suggestive stills in the same bra is a set, not a script,
    because there is nowhere to walk a fan to.

    Ranked best-first by `shoot_rank_key`.
    """
    # Resolved per call, not bound at import, so the constants stay the one knob.
    min_items = MIN_SCRIPT_ITEMS if min_items is None else min_items
    min_videos = MIN_SCRIPT_VIDEOS if min_videos is None else min_videos
    if rows is None:
        rows, _ = await _grouping_rows(account_id)
    if prints is None:
        prints = await _fingerprints(account_id)
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
            # A script opens on its free rungs; a disputed item is never sent
            # free, so it does not join a shoot unless it is priced (paid).
            enriched = [r for r in map(_with_script_why, seg) if not _unpriced_dispute(r)]
            kw = dict(min_items=min_items, require_escalation=require_escalation,
                      min_videos=min_videos)
            parts = [s for room, part in split_by_room(enriched)
                     if (s := _shoot(outfit, room, part, prints, **kw)) is not None]
            # No room fills a script on its own: the whole shoot, unsplit.
            if not parts and (whole := _shoot(outfit, "", enriched, prints, **kw)):
                parts = [whole]
            out.extend(parts)

    out.sort(key=shoot_rank_key)
    return out


# A shoot's paid depth stops counting past this many explicit/hardcore items: a
# 50-item set is not five times the script a 10-item one is.
_PAID_DEPTH_CAP = 10


def ladder_completeness(s: dict[str, Any]) -> tuple[int, int]:
    """(bands present of opener / middle / closer, rungs held minus rungs
    skipped) — {1, 3} scores below {1, 2} and {1, 2, 3}."""
    bands = s.get("bands") or {}
    present = sum(1 for b in ("opener", "middle", "closer") if bands.get(b))
    rungs = sorted(s["rungs"])
    skipped = (rungs[-1] - rungs[0] + 1 - len(rungs)) if rungs else 0
    return present, len(rungs) - skipped


def shoot_rank_key(s: dict[str, Any]) -> tuple:
    """Best script first. A shoot with nothing that closes on its own cannot land
    a sale, so it ranks below every one that can, whatever its size or media mix
    (live AE 2026-11-13: 5 of the old top 10 had no closer). Then the most
    complete ladder (`ladder_completeness`), then the deepest paid end
    (explicit + hardcore, capped), then stills AND clips, then biggest."""
    tiers = s.get("tiers") or {}
    paid = min(_PAID_DEPTH_CAP, tiers.get("explicit", 0) + tiers.get("hardcore", 0))
    bands, rungs = ladder_completeness(s)
    return (s["closes_on_own"] == 0, -bands, -rungs, -paid, not s["mixed"], -s["size"])


def _span_gap(r: dict[str, Any], s: dict[str, Any]) -> float:
    """Seconds from `r`'s upload to shoot `s`'s span (0 inside it)."""
    at, lo, hi = r["created_at"], s["started_at"], s["ended_at"]
    if at is None or lo is None or hi is None:
        return float("inf")
    if lo <= at <= hi:
        return 0.0
    return min(abs((at - lo).total_seconds()), abs((at - hi).total_seconds()))


def borrow_closers(kept: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    """Each kept script with no closer of its own borrows ONE closing item from
    outside every kept script: same outfit colour first, else same room; then
    a clip; then nearest in created_at. On the script's top rung or above, so it
    still sends last. Appended last, marked `borrowed`; counts, rungs and health
    recomputed. In rank order, so the best script borrows first. Mutates `kept`."""
    taken = {r["media_id"] for s in kept for r in s["items"]}
    pool = [r for r in map(_with_script_why, rows)
            if r["why"]["closes"] and r["why"]["rung"] is not None
            and not _unpriced_dispute(r) and r["media_id"] not in taken]
    for s in kept:
        if s["closes_on_own"] or not s["items"]:
            continue
        top = max(s["rungs"])

        def _match(r: dict[str, Any]) -> int | None:
            fields = r.get("fields") or {}
            if s["colour"] and outfit_colour(fields) == s["colour"]:
                return 0
            if s["room"] and item_room(fields) == s["room"]:
                return 1
            return None

        cands = [(m, r) for r in pool if r["media_id"] not in taken
                 and r["why"]["rung"] >= top and (m := _match(r)) is not None]
        if not cands:
            continue
        _, pick = min(cands, key=lambda c: (c[0], c[1]["kind"] != "video",
                                            _span_gap(c[1], s), c[1]["media_id"]))
        taken.add(pick["media_id"])
        ladder = [r for r in s["items"] if r["why"]["rung"] is not None]
        tail = [r for r in s["items"] if r["why"]["rung"] is None]
        ladder.append({**pick, "borrowed": True})
        items = ladder + tail
        kinds, tiers, closes = _tally(items)
        s.update(items=_ordered_items(items), size=len(ladder), kinds=kinds, tiers=tiers,
                 closes_on_own=closes, mixed=len(kinds) > 1,
                 rungs=sorted({r["why"]["rung"] for r in ladder}),
                 bands=_band_counts(ladder), borrowed=pick["media_id"])
        s["health"] = script_health(s)


# ── Purpose folders (what a weak shoot is still good for) ───────────
#
# Not every outfit group is a sellable shoot. the graded vault's `black top` (15 stills,
# ZERO closers) and `white top` (4 stills) have nothing to land a sale on — but
# they are perfectly good STORY material.
#
# So the vault gets re-cut by heat instead of by outfit, into the lanes an
# operator actually sends on, e.g.:
#
#   Stories        sfw → suggestive   safe enough to post publicly
#   Mass           suggestive only    the free hook on a broadcast
#
# The bands OVERLAP on `suggestive` deliberately, and that is the case the
# per-folder ordering was built for: a suggestive still belongs in both lanes and
# holds an independent position in each. One item, two folders, two orders.
# Nothing about that works if order lives on the item.
# Every folder this module proposes is prefixed so an operator can always tell
# at a glance which folders a human curated and which the pipeline generated —
# and can delete the whole generated set without touching their own work.
AI_FOLDER_PREFIX = "AI-"
# `VaultFolder.created_by` on every folder this module makes. Reuse and retire
# key on it, so an operator's folder is never reached even if named `AI-…`.
AI_FOLDER_CREATOR = "vault_ai_script"
_FOLDER_NAME_MAX = 120


def ai_folder_name(name: str) -> str:
    """`AI-<name>`, never double-prefixed on a re-run."""
    clean = str(name).strip()
    if clean.startswith(AI_FOLDER_PREFIX):
        return clean[:_FOLDER_NAME_MAX]
    return f"{AI_FOLDER_PREFIX}{clean}"[:_FOLDER_NAME_MAX]


def _unique_name(name: str, used: set[str]) -> str:
    """`name`, or `name 2`, `name 3`… — the first not yet `used`, still capped."""
    out, n = name, 1
    while out in used:
        n += 1
        tail = f" {n}"
        out = f"{name[:_FOLDER_NAME_MAX - len(tail)]}{tail}"
    return out


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
    """sfw/suggestive, and never an item the two passes disagree about: a free
    lane is where a wrong reading costs most (`vault_ai_brief.settled_reading`)."""
    return (why["tier"] in ("sfw", "suggestive")
            and not vault_ai_brief.is_disputed(fields))


def _lane_mass(why: dict, fields: dict, kind: str) -> bool:
    """Suggestive ONLY. The old suggestive→explicit band swallowed 92 of 103
    items and made every paid item free as well. Never a disputed item."""
    return (why["tier"] == "suggestive"
            and not vault_ai_brief.is_disputed(fields))


def _lane_covered_explicit(why: dict, fields: dict, kind: str) -> bool:
    """Tagged explicit, but nothing is actually on show — a top or underwear is
    still on, or the region is out of shot. The tier says "explicit" because of
    what the scene IS, not because of what is VISIBLE, so this material is safe
    on a mass send or a story even though the heat rung alone would rule it out.
    It is equally not a tease: there is no reveal in it to charge for.

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
    if vault_ai_brief.is_disputed(fields):
        return False          # a free lane never takes a disputed item
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


def _flag_lane_ok(why: dict, fields: dict, kind: str) -> bool:
    """A paid-tier still the flags pass has looked at — the entry test for both
    price lanes.

    An unflagged still is LEFT OUT, never guessed: without the flags `_is_nude`
    falls back to `clothing_state`, measured wrong on ~1 in 3 of the stills the
    $50 tier is built from. The vision daily cap usually stops the flags pass
    part-way, so the folders are built from what is checked and the rest join
    on a rebuild once it is (`flags_coverage` says how many are waiting). They
    still land in `explicit 1:1`, which asks nothing of the flags.
    """
    return (kind == "photo" and why["tier"] in _PAID_TIERS
            and vault_ai_brief.flags_known(fields))


def _lane_tease_10(why: dict, fields: dict, kind: str) -> bool:
    """$10 — a real reveal, but she is still a little hidden: breasts out,
    something still on, pussy not on show. Images only.

    Still COVERED is the whole point: fully nude is the $50 tier, never this
    one, however little is actually in frame. What remains is the middle band —
    breasts out with her pussy not visible and something still on.

    Content lanes may overlap freely, but the two PRICE tiers must not: an item
    cannot carry two prices.

    Flagged stills only (`_flag_lane_ok`).
    """
    if not _flag_lane_ok(why, fields, kind):
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

    Flagged stills only (`_flag_lane_ok`).
    """
    if not _flag_lane_ok(why, fields, kind):
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


def _unpriced_dispute(row: dict[str, Any]) -> bool:
    """A disputed item whose settled tier is free (sfw/suggestive): it may be
    neither sent free nor sold as explicit, so no folder takes it."""
    return (row["why"]["tier"] not in _PAID_TIERS
            and vault_ai_brief.is_disputed(row.get("fields") or {}))


def shelf_price(fields: dict, kind: str) -> int:
    """The tease price this item's (settled) reading puts on it: 50, 10 or 0."""
    fields = vault_ai_brief.settled_reading(fields) or {}
    why = send_order_reason(fields)
    if _lane_tease_50(why, fields, kind):
        return 50
    return 10 if _lane_tease_10(why, fields, kind) else 0


# (slug, display name, what it is for, predicate(why, fields, kind)). Lanes
# deliberately OVERLAP — a single item can serve several and holds an
# independent position in each.
# The display name is what becomes the FOLDER name, so it is kept short: these
# end up in a dropdown and (once mirrored) in the OF app, where
# "AI-$50 tease · images, fully nude or pussy visible" is unusable. The long
# form lives in `purpose`, which the preview shows underneath.
PURPOSE_LANES: tuple[tuple[str, str, str, Callable[[dict, dict, str], bool]], ...] = (
    ("stories", "stories",
     "sfw → suggestive — safe enough to post publicly", _lane_stories),
    ("mass", "mass",
     "suggestive only — mass messages and media", _lane_mass),
    ("covered_explicit", "safe explicit",
     "reads explicit, but nothing bare — each region out of shot or under "
     "named clothing, so it is safe to mass", _lane_covered_explicit),
    ("tease_10", "tease 10",
     "images — boobs out, pussy not on show, never fully nude (that is the $50)",
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
    solo: bool = False, unlaned: list[int] | None = None,
    rows: list[dict[str, Any]] | None = None,
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

    `unlaned`, when given, receives the disputed free-tier items no lane took
    (see the residual lane below).

    `rows` — the pool, as `_grouping_rows` returns it; loaded when omitted.

    Read-only; an item may legitimately appear in more than one lane.
    """
    if rows is None:
        rows, _ = await _grouping_rows(account_id)
    if media_ids is not None:
        wanted = {int(m) for m in media_ids}
        rows = [r for r in rows if r["media_id"] in wanted]

    enriched = [_with_why(r) for r in rows]

    def _folder(slug: str, name: str, purpose: str, picked: list[dict[str, Any]],
                *, solo_of: int | None = None) -> dict[str, Any]:
        """One lane. `solo_of` is the size of the lane this was cut FROM, and is
        what makes it a cut rather than a lane — every folder carries both keys
        so no consumer has to test for their presence."""
        picked.sort(key=lambda r: send_sort_key(r["fields"], media_id=r["media_id"]))
        kinds, tiers, closes = _tally(picked)
        return {
            "lane": slug, "name": ai_folder_name(name), "purpose": purpose,
            "size": len(picked), "kinds": kinds, "tiers": tiers,
            "closes_on_own": closes,
            "solo": solo_of is not None, "solo_of": solo_of,
            "items": _ordered_items(picked),
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

    # Nothing paid falls through. `stories` takes every undisputed sfw/suggestive
    # item, so an orphan is paid-tier (sold 1:1, `_RESIDUAL_LANE`) or a disputed
    # free-tier item: not free, and selling it as explicit 1:1 could pass off a
    # dressed photo, so it is foldered nowhere (still in the vault). The caller
    # gets those ids in `unlaned` so the plan can count them.
    rest = [r for r in enriched
            if r["media_id"] not in claimed and r["why"]["tier"] in _PAID_TIERS]
    if rest:
        out.append(_folder(*_RESIDUAL_LANE, rest))
    if unlaned is not None:
        unlaned.extend(sorted(r["media_id"] for r in enriched
                              if r["media_id"] not in claimed and _unpriced_dispute(r)))

    if solo:
        # Built whole before extending `out` — never appended to the list being
        # walked. A lane with nothing solo in it yields no cut.
        cuts = [c for c in map(_solo_cut, out) if c is not None]
        out.extend(cuts)
    return out


def collect_topic_folders(rows: list[dict[str, Any]], topics: Iterable[str], *,
                          split: bool = True) -> list[dict[str, Any]]:
    """One folder per ticked topic and price split (`vault_topic_folders`), in send order; `split` False: one per
    topic (`AI-<name>`, price None), the union of its splits. Photos and clips with a current `_jev`; additive — an item in a lane or script may also be here. Read-only."""
    out: list[dict[str, Any]] = []
    for (slug, price), picked in vault_topic_folders.assign(rows, topics, by_price=split).items():
        topic = vault_topic_folders.BY_SLUG[slug]
        picked = sorted((_with_why(r) for r in picked),
                        key=lambda r: send_sort_key(r["fields"], media_id=r["media_id"]))
        kinds, tiers, closes = _tally(picked)
        out.append({
            "topic": slug, "price": price,
            "name": ai_folder_name(vault_topic_folders.folder_name(topic, price)),
            "purpose": topic.description if price is None else f"{topic.description} — {price}",
            "kinds": kinds, "tiers": tiers, "closes_on_own": closes,
            "items": _ordered_items(picked),
        })
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

    `ready` is False when ANY still is missing them. Informational: the folders
    build anyway, and the `missing` stills are left out of the flag lanes
    (safe explicit, $10, $50) until checked — see `_flag_lane_ok`.
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
    account_id: str, *, keep: int = DEFAULT_KEEP_SCRIPTS,
    window_hours: int = DEFAULT_OUTFIT_WINDOW_HOURS,
    min_items: int | None = None,
    solo: bool = False,
    topics: Iterable[str] = (),
    split: bool = True,
) -> dict[str, Any]:
    """Every folder the pipeline proposes, scripts and lanes together.

    `keep` — how many of the top-ranked shoots stay as their own script folder.
    Lanes are always cut from the WHOLE vault, not just the shoots that were not
    kept: the explicit material a paid tease needs lives inside the good shoots,
    so restricting them to leftovers empties those lanes. An item belonging to
    both a script and a lane is the design.

    `solo` adds a `-solo` cut of each lane (see `collect_purpose_folders`).

    `topics` (slugs, `vault_topic_folders.SLUGS`; validate with `parse_topics`) adds one folder per ticked
    topic and price, cut from the photos' and clips' Jev v8 answers (`collect_topic_folders`). None ticked = no
    topic folders, and any built earlier are retired like every other AI- folder the plan no longer makes.
    `split` False makes one folder per topic (`AI-<name>`) instead; the split-named ones are then retired the same
    way.
    """
    topics = vault_topic_folders.parse_topics(topics)
    # Loaded and dupe-collapsed ONCE, for shoots, lanes and topics alike.
    rows, dupes_dropped = await _grouping_rows(account_id)
    shoots = await collect_outfit_scripts(
        account_id, window_hours=window_hours, min_items=min_items, rows=rows,
        prints=await _fingerprints(account_id))
    settled_unlaned: list[int] = []
    lanes = await collect_purpose_folders(account_id, solo=solo, unlaned=settled_unlaned,
                                          rows=rows)

    def _folder(group: dict[str, Any], source: str, purpose: str,
                **extra: Any) -> dict[str, Any]:
        """`group` is a shoot or a lane; its counts are carried, not recounted."""
        items = group["items"]
        return {
            "name": group["name"], "source": source, "purpose": purpose,
            "size": len(items), "kinds": group["kinds"], "tiers": group["tiers"],
            "closes_on_own": group["closes_on_own"],
            # Defaults, so EVERY folder answers "are you a solo cut" — a script
            # is not one. `extra` overrides for the lanes, which know.
            "solo": False, "solo_of": None,
            "items": [
                {"media_id": r["media_id"], "kind": r["kind"],
                 "manual_order": r["manual_order"], "score": r.get("score"),
                 "tier": r["why"]["tier"], "closes": r["why"]["closes"],
                 "clothing_state": r["why"]["clothing_state"],
                 **({"borrowed": True} if r.get("borrowed") else {})}
                for r in items
            ],
            **extra,
        }

    kept = shoots[:max(0, keep)]
    borrow_closers(kept, rows)
    folders = [
        _folder(s, "script", f"one shoot — {s['outfit']}",
                outfit=s["outfit"], mixed=s["mixed"], room=s["room"], health=s["health"])
        for s in kept
    ] + [
        _folder(f, "lane", f["purpose"], lane=f["lane"],
                solo=f["solo"], solo_of=f["solo_of"])
        for f in lanes
    ] + [
        _folder(f, "topic", f["purpose"], topic=f["topic"], price=f["price"])
        for f in collect_topic_folders(rows, topics, split=split)
    ]

    # Names unique across the plan: apply and the OF mirror both join on name.
    # Names carry the room and `<Mon D>`, so a clash is rare (one outfit, one
    # room, the same date a year apart); the suffix goes
    # by when each STARTED, not by rank, so a re-rank never swaps two folders'
    # contents on a re-run. Lanes come after and only move on a clash.
    by_start = sorted(range(len(kept)), key=lambda i: (
        kept[i]["started_at"] or datetime.min, kept[i]["items"][0]["media_id"]))
    used: set[str] = set()
    for i in [*by_start, *range(len(kept), len(folders))]:
        folders[i]["name"] = _unique_name(folders[i]["name"], used)
        used.add(folders[i]["name"])

    unique = {r["media_id"] for f in folders for r in f["items"]}

    # What Confirm would do to the folders already there — the same match
    # `apply_ai_folders` makes (`_assign_folders`), so the preview's counts are
    # the apply's. Retiring a folder bound to an OF list unlinks that list
    # (apply never deletes it on OF), which is why those are counted apart.
    async with get_session() as s:
        owned = await _owned_ai_folders(s, account_id)
        reuse, stale = _assign_folders([ai_folder_name(f["name"]) for f in folders], owned)
        for f, existing in zip(folders, reuse):
            f["change"] = "new" if existing is None else "keep"
        retired = [{"folder_id": f.id, "name": f.name, "of_list_id": f.of_list_id}
                   for f in stale]
    changes = {
        "create": sum(1 for f in folders if f["change"] == "new"),
        "keep": sum(1 for f in folders if f["change"] == "keep"),
        "retire": len(retired),
        "retire_on_of": sum(1 for r in retired if r["of_list_id"] is not None),
        "retired": retired,
    }

    # How much of this account has been through the cheap flags pass. The flag
    # lanes (safe explicit, $10, $50) take flagged stills only, so `missing` is
    # how many stills those folders are still waiting on. The UI says so; it
    # does not block the build.
    coverage = await flags_coverage(account_id)
    # Only when asked: it is a second full read of the vault, and it answers a
    # question nobody has posed unless the box is ticked.
    solo_cov = await solo_coverage(account_id) if solo else None
    # Topic folders read Jev only: whether it is on for the account, how many photos + clips carry it, and every
    # topic's size (ticked or not — the checklist shows them all).
    jev = {"enabled": True,  # Jev v8 is the default for every photo (#511)
           **vault_topic_folders.coverage(rows)}

    return {
        "account_id": account_id,
        "keep": keep,
        "solo": solo,
        "topics": topics,
        "split": split,
        "shoots_found": len(shoots),
        "flags": coverage,
        "solo_coverage": solo_cov,
        "jev": jev,
        "topic_catalogue": vault_topic_folders.catalogue(rows),
        "folders": folders,
        # Confirm's effect: `create` new / `keep` refreshed / `retire` soft-
        # deleted (`retire_on_of` of those bound to an OF list). `keep` here is
        # folders, not the shoot count above.
        "changes": changes,
        # Disputed free-tier items: never free, never sold as explicit, so in
        # no folder. Counted so "nothing dropped" stays checkable.
        "settled_unlaned": settled_unlaned,
        # Duplicate copies collapsed into their set's kept item: in no folder,
        # their keeper stands in for them.
        "dupes_collapsed": dupes_dropped,
        "summary": {
            "folders": len(folders),
            "scripts": sum(1 for f in folders if f["source"] == "script"),
            # `solo_cuts`, not `solo`: the plan's own `solo` is the bool that
            # was ASKED for, and one payload carrying both under one name is a
            # question waiting to be answered wrong.
            "lanes": sum(1 for f in folders
                         if f["source"] == "lane" and not f["solo"]),
            "solo_cuts": sum(1 for f in folders if f["solo"]),
            "topics": sum(1 for f in folders if f["source"] == "topic"),
            "unique_media": len(unique),
            "memberships": sum(f["size"] for f in folders),
            "settled_unlaned": len(settled_unlaned),
            "dupes_collapsed": len(dupes_dropped),
        },
    }


async def _owned_ai_folders(s, account_id: str) -> dict[str, list[VaultFolder]]:
    """Every live folder this module made, by name, oldest first per name."""
    owned: dict[str, list[VaultFolder]] = {}
    for folder in (await s.execute(
        select(VaultFolder).where(
            VaultFolder.account_id == account_id,
            VaultFolder.created_by == AI_FOLDER_CREATOR,
            VaultFolder.deleted_at.is_(None),
        ).order_by(VaultFolder.id)
    )).scalars().all():
        owned.setdefault(folder.name, []).append(folder)
    return owned


def _assign_folders(names: list[str], owned: dict[str, list[VaultFolder]],
                    ) -> tuple[list[VaultFolder | None], list[VaultFolder]]:
    """(per planned name the generated folder it reuses, or None = new; the
    generated folders left over, by id — the ones a rebuild retires).

    Each name takes at most one folder, the oldest of that name. Only AI-
    prefixed leftovers are retired: scoped hard, so an operator's own folder is
    never reached even if it collides on name. The preview and the apply both
    call this, so what the modal says is what Confirm does."""
    left = {name: list(rows) for name, rows in owned.items()}
    reuse = [left[n].pop(0) if left.get(n) else None for n in names]
    stale = sorted((f for rows in left.values() for f in rows
                    if f.name.startswith(AI_FOLDER_PREFIX)), key=lambda f: f.id)
    return reuse, stale


async def apply_ai_folders(account_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Create the planned folders and fill them, in send order.

    Re-runnable: a live folder this module made (`AI_FOLDER_CREATOR`) under the
    same name is REUSED and its membership rewritten, so pressing the button
    twice refreshes rather than piling up duplicates. A folder an operator made
    is never reused, even on a name clash; the generated one is made beside it.
    Names come from the plan as-is — `plan_ai_folders` keeps them unique.

    Internal folders only. No OF writes, nothing sent.
    """
    created: list[dict[str, Any]] = []
    specs = plan.get("folders") or []
    async with get_session() as s:
        # Each spec takes at most one live generated folder of its name;
        # whatever is left over is stale (`_assign_folders`, as the preview).
        names = [ai_folder_name(spec["name"]) for spec in specs]
        reuse, stale = _assign_folders(names, await _owned_ai_folders(s, account_id))

        for spec, name, existing in zip(specs, names, reuse):
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
                                     created_by=AI_FOLDER_CREATOR)
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
        retired: list[dict[str, Any]] = []
        for folder in stale:
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
