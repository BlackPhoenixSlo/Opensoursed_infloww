from __future__ import annotations

import re
from typing import Any, Collection, Mapping

import vault_ai_brief
import vault_jev_rules
from jsonsafe import load_json

JEV_KEY = vault_jev_rules.JEV_KEY
FLAGS_V = vault_ai_brief.FLAGS_VERSION
MODEL = "jev"
EXPLICITNESS = {"$100": "hardcore", "$50": "explicit", "$10": "explicit"}
_DRESSED = {"everyday_clothes": "dressed", "sheet_or_towel": "dressed", "lingerie_or_bodysuit": "lingerie_on",
            "swimwear": "lingerie_on", "topless_with_bottoms": "lingerie_on"}
_CLEARED = (*vault_ai_brief.OVER_KEYS.values(), "_flags_frames", "_flags_arc", "_flags_status", "_flags_failed_at",
            "_flags_error", "_flags_copied_from")
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
    return "covered" if (jev.get("state") or {}).get("crotch") in _WORN else "not_in_frame"


def reading(jev: Any) -> dict[str, Any] | None:
    bare = vault_jev_rules.bare_regions(jev)
    if bare is None:
        return None
    lane = vault_jev_rules.read_lane(jev)
    bare_b, bare_v, bare_a = bare["breasts_vis"], bare["vulva_vis"], bare["anus_vis"]
    outfit = str((jev.get("tags") or {}).get("outfit") or "")
    nude = outfit == "nude" and (bare_v or not bare_b)
    if nude:
        clothing, underwear = "fully_nude", False
    elif bare_b or bare_v or bare_a:
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
        "explicitness": EXPLICITNESS.get(lane) or ("explicit" if bare_b or bare_v else "suggestive"),
    }


def _words(name: str) -> set[str]:
    whole = {w for w in re.split(r"[\s,./]+", name.lower()) if w}
    return whole | {p for w in whole for p in w.split("-") if p}


def _covers(name: str) -> frozenset[str]:
    w = _words(name)
    if w & {"top", "tops"}:
        return _UPPER
    if w & {"bottom", "bottoms"}:
        return _LOWER
    out = (_UPPER if w & _TOP else frozenset()) | (_LOWER if w & _BOTTOM else frozenset())
    return out or (_UPPER | _LOWER if w & _ONE_PIECE else frozenset())


def garments(r: Mapping[str, Any], clothing_items: Any) -> dict[str, str]:
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


TIER_COLUMN = "explicitness_tier"


def column_tier(fields: Mapping[str, Any], cur: Any, locked: Collection[str]) -> Any:
    jev = fields.get(JEV_KEY)
    if TIER_COLUMN in locked or reading(jev) is None:
        return cur
    if jev.get("lane5") == "review" and vault_jev_rules.read_lane(jev) != "$100":
        return None
    return fields.get("explicitness")


def row_in_sync(ai_fields_json: Any, locked_fields_json: Any, *, tier: Any) -> bool:
    fields = load_json(ai_fields_json, {}) or {}
    locked = set(load_json(locked_fields_json, []) or [])
    return in_sync(fields, locked) and column_tier(fields, tier, locked) == tier


def in_sync(fields: Mapping[str, Any] | None, locked: Collection[str]) -> bool:
    f = dict(fields or {})
    if reading(f.get(JEV_KEY)) is None:
        return False
    want = apply(f, f[JEV_KEY], locked)
    f.pop("_flags_copied_from", None)
    return want == f
