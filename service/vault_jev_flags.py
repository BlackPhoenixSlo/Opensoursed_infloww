"""vault_jev_flags.py — a photo's or clip's flags, and the describe fields that must agree with them, off its `_jev`.

Jev v8 is the only flags pass for photos and clips (a clip's `_jev` is its max frame's, same shape). Every consumer
reads the qwen flags shape (`vault_ai_brief.FLAG_KEYS` + `_flags_v`: flags_current, the brief's settled_reading /
contradictions / is_disputed, vault_scripts' lanes, the pack picker, the OF folders), so `_jev` is mapped into exactly
that shape and stamped with it (`vault_jev_pass`). Pure (`row_in_sync` only parses the two JSON columns).

What is bare comes from the FINAL lane (`lane5`, after settle), so the price the consumers compute is Jev's:
  $100  something inserted: vulva bare (the anus when Jev saw the crotch NOT bare); breasts bare iff breasts_bare y
  $50   vulva bare; breasts bare iff breasts_bare y
  $10   breasts bare, vulva not
  free  nothing bare
A region not bare reads `not_in_frame` when Jev's state says it is out of the picture, else `covered` (the vulva
beside a bare anus: `covered` only when the state names a garment). Jev names no garment, so the `over_` keys (what
`vault_scripts` reads to tell clothing from a hand: `_is_nude`, `_decently_covered`) come from the describe's
`clothing_items` (`garments`); none until the photo is described. Shelf price (`vault_scripts.shelf_price`): $100 / $50 -> 50, $10 -> 10, free -> 0 (tested).

clothing_state / underwear_visible (one table, so the row never contradicts itself; `apply` writes them with the flags):
  vulva bare + nude outfit, or nothing bare + nude outfit   fully_nude, no underwear
  any other bare                                            `vault_ai_brief._CLOTHING_FOR` (settle's own table),
                                                            underwear on — on a $10 that is the "not nude" the
                                                            $10 rung needs (owner: topless with labia hidden is $10)
  nothing bare                                              the outfit (`_DRESSED`); underwear iff lingerie_on
explicitness by lane: $100 hardcore, $50 / $10 explicit, free suggestive (vault_scripts' mass lane is suggestive
only, and a Jev free photo is mass-sendable).
"""
from __future__ import annotations

import re
from typing import Any, Collection, Mapping

import vault_ai_brief
import vault_jev_rules
from jsonsafe import load_json

JEV_KEY = vault_jev_rules.JEV_KEY
FLAGS_V = vault_ai_brief.FLAGS_VERSION   # the flags version consumers require (one definition)
MODEL = "jev"        # `_flags_model` of a Jev-mapped row
EXPLICITNESS = {"$100": "hardcore", "$50": "explicit", "$10": "explicit"}
_LANES = (*vault_jev_rules.PAID, "free")
_DRESSED = {"everyday_clothes": "dressed", "sheet_or_towel": "dressed", "lingerie_or_bodysuit": "lingerie_on",
            "swimwear": "lingerie_on", "topless_with_bottoms": "lingerie_on"}
# keys a Jev mapping clears: qwen's garment names (re-named from clothing_items, `garments`), clip stamps, failure
# record, copy mark (its own answer now)
_CLEARED = (*vault_ai_brief.OVER_KEYS.values(), "_flags_frames", "_flags_arc", "_flags_status", "_flags_failed_at",
            "_flags_error", "_flags_copied_from")
# Garment words by what they cover (`_covers`): a top the breasts, a bottom the vulva + anus, a one-piece all
# three. "top" / "bottom(s)" name the half outright ("bikini top", "swimsuit bottoms"); a bare "bikini" is the
# bottom half (it never covers the breasts). Sheer legwear (tights, stockings) is not cover.
_ONE_PIECE = frozenset({"dress", "bodysuit", "swimsuit", "one-piece", "teddy", "romper", "jumpsuit", "onesie",
                        "leotard", "catsuit", "nightgown", "gown", "robe", "kimono", "towel", "lingerie"})
_TOP = frozenset({"bra", "bralette", "top", "tops", "tank", "cami", "camisole", "shirt", "t-shirt", "tshirt", "tee",
                  "blouse", "sweater", "sweatshirt", "hoodie", "jacket", "cardigan", "coat", "vest", "jersey",
                  "corset", "bustier", "halter", "tube", "crop", "chemise", "babydoll", "pasties"})
_BOTTOM = frozenset({"bottom", "bottoms", "thong", "panties", "panty", "knickers", "briefs", "g-string", "gstring",
                     "underwear", "boyshorts", "shorts", "hotpants", "skirt", "jeans", "pants", "trousers",
                     "leggings", "joggers", "sweatpants", "bikini"})
_UPPER, _LOWER = frozenset({"breasts_vis"}), frozenset({"vulva_vis", "anus_vis"})


_WORN = ("sheer_covered", "sexy_covered", "normal_covered")


def _hidden(jev: Mapping[str, Any], region: str) -> str:
    return "not_in_frame" if (jev.get("state") or {}).get(region) == "not_visible" else "covered"


def _vulva_beside_anus(jev: Mapping[str, Any]) -> str:
    """The vulva of a $100 Jev saw inserted with the crotch NOT bare (the anus is the bare one): `covered` only
    when Jev's state names a garment over it, else `not_in_frame` — the insertion is the reveal, and a vulva
    nobody saw covered must not read as clothed (which would drop the photo from the $50 shelf)."""
    return "covered" if (jev.get("state") or {}).get("crotch") in _WORN else "not_in_frame"


def reading(jev: Any) -> dict[str, Any] | None:
    """The flags + lane-critical describe fields for one `_jev`; None when it is not a current, settled reading."""
    lane = vault_jev_rules.read_lane(jev) if isinstance(jev, dict) else None   # a review clip: what it read
    if not vault_jev_rules.current({JEV_KEY: jev}) or lane not in _LANES:
        return None
    bare_b = lane == "$10" or (lane in ("$50", "$100") and jev.get("breasts_bare") == "y")
    bare_v = lane == "$50" or (lane == "$100" and jev.get("crotch_bare") != "n")
    bare_a = lane == "$100" and not bare_v
    outfit = str((jev.get("tags") or {}).get("outfit") or "")
    nude = outfit == "nude" and (bare_v or not bare_b)
    if nude:
        clothing, underwear = "fully_nude", False
    elif bare_b or bare_v or bare_a:   # a bare anus reads like a bare vulva: something pulled aside below
        clothing, underwear = vault_ai_brief._CLOTHING_FOR[(bare_b, bare_v or bare_a)], True
    else:
        clothing = _DRESSED.get(outfit, "unclear")
        underwear = clothing == "lingerie_on"
    return {
        "breasts_vis": "bare" if bare_b else _hidden(jev, "breasts"),
        "vulva_vis": "bare" if bare_v else _vulva_beside_anus(jev) if bare_a else _hidden(jev, "crotch"),
        "anus_vis": "bare" if bare_a else _hidden(jev, "butt"),
        "underwear_visible": underwear,
        "clothing_state": clothing,
        "genitals_covered": not bare_v and not nude,
        "explicitness": EXPLICITNESS.get(lane, "suggestive"),
    }


def _words(name: str) -> set[str]:
    """The item's words, hyphenated ones whole and split ("one-piece", "one", "piece")."""
    whole = {w for w in re.split(r"[\s,./]+", name.lower()) if w}
    return whole | {p for w in whole for p in w.split("-") if p}


def _covers(name: str) -> frozenset[str]:
    """The regions one garment can cover: "top" / "bottom(s)" decide outright, else its top / bottom words
    (both: a set, e.g. "bra and panties"), else a one-piece covers all three; nothing for a non-garment."""
    w = _words(name)
    if w & {"top", "tops"}:
        return _UPPER
    if w & {"bottom", "bottoms"}:
        return _LOWER
    out = (_UPPER if w & _TOP else frozenset()) | (_LOWER if w & _BOTTOM else frozenset())
    return out or (_UPPER | _LOWER if w & _ONE_PIECE else frozenset())


def garments(r: Mapping[str, Any], clothing_items: Any) -> dict[str, str]:
    """The `over_` garment names for one reading, from the describe's `clothing_items` (Jev names no garment): per
    region the reading calls `covered`, the first item that can cover it (`_covers`, and not one
    `vault_ai_brief.garment_over` would veto there). Nothing for a nude reading (a named garment on a `fully_nude`
    row is a contradiction) or before the photo is described."""
    if r.get("clothing_state") == "fully_nude" or not isinstance(clothing_items, list):
        return {}
    items = [str(x).strip() for x in clothing_items if isinstance(x, str) and x.strip()]
    out = {}
    for region, key in vault_ai_brief.OVER_KEYS.items():
        if r.get(region) != "covered":
            continue
        for name in items:
            if region in _covers(name) and vault_ai_brief.garment_over({key: name}, region) == name:
                out[key] = name
                break
    return out


def apply(prev: Mapping[str, Any], jev: Any, locked: Collection[str] = ()) -> dict[str, Any]:
    """`prev` (a row's ai_fields_json) with every field `reading` decides replaced by `jev`'s — the flags AND the
    describe's clothing_state / genitals_covered / explicitness, so a photo described before Jev (qwen's tiers) prices
    and gates off Jev's lane, never a stale tier beside Jev's flags (an operator-locked key keeps its value) — and its
    garment names by `garments` over `prev`'s `clothing_items`, stamped `_flags_v` / `_flags_model`. `prev`
    unchanged (a copy) when `jev` is not a current reading."""
    out = dict(prev)
    r = reading(jev)
    if r is None:
        return out
    for k, v in r.items():
        if k not in locked:
            out[k] = v
    for k in _CLEARED:
        if k not in locked:
            out.pop(k, None)
    for k, name in garments(r, prev.get("clothing_items")).items():
        if k not in locked:
            out[k] = name
    out["_flags_v"], out["_flags_model"] = FLAGS_V, MODEL
    return out


# The `vault_items` column the mapped `explicitness` also lands in, and its lock key
# (`vault_ai_vision_decide._COLUMN_LOCK`): folder picks (`assistant_draft`) and the admin read it.
TIER_COLUMN = "explicitness_tier"


def column_tier(fields: Mapping[str, Any], cur: Any, locked: Collection[str]) -> Any:
    """The `explicitness_tier` column a row should hold beside `fields` (already `apply`-mapped): their
    `explicitness` when they carry a current `_jev` reading, else `cur` (no reading, or the column operator-locked)."""
    if TIER_COLUMN in locked or reading(fields.get(JEV_KEY)) is None:
        return cur
    return fields.get("explicitness")


def row_in_sync(ai_fields_json: Any, locked_fields_json: Any, *, tier: Any) -> bool:
    """`in_sync` straight off a row's two JSON columns (text or already parsed), its locks included, AND its
    `explicitness_tier` column (`tier`) matching (`column_tier`) — the one way every caller (flags todo, reuse
    source, copy source, the Jev pass) asks, so they never disagree on a photo whose flags an operator locked or
    whose tier a pre-Jev describe left."""
    fields = load_json(ai_fields_json, {}) or {}
    locked = set(load_json(locked_fields_json, []) or [])
    return in_sync(fields, locked) and column_tier(fields, tier, locked) == tier


def in_sync(fields: Mapping[str, Any] | None, locked: Collection[str]) -> bool:
    """The row carries a current `_jev` and exactly its mapped fields (flags + lane fields), operator-locked keys kept (nothing for a
    sweep to do). A duplicate's `_flags_copied_from` mark is not drift: the copy carries its source's `_jev` and
    flags together. `locked` is required: a locked flag the mapper would overwrite reads as drift without it."""
    f = dict(fields or {})
    if reading(f.get(JEV_KEY)) is None:
        return False
    want = apply(f, f[JEV_KEY], locked)
    f.pop("_flags_copied_from", None)
    return want == f
