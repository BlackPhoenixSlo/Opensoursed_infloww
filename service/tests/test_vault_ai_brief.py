#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import vault_ai_brief as B  # noqa: E402


async def case_solo_is_never_assumed() -> None:
    assert B.sellability({"people_count": 2, "partner_visible": True})["solo"] is False
    assert B.sellability({"people_count": 1, "partner_visible": False})["solo"] is True
    assert B.sellability({"people_count": 3})["solo"] is False
    assert B.sellability({})["solo"] is None


async def case_stands_alone_vs_buildup() -> None:
    payoff = B.sellability({"acts": ["tease", "fingering"], "explicitness": "hardcore"})
    assert payoff["stands_alone"] is True and payoff["payoff_acts"] == ["fingering"], payoff

    build = B.sellability({"acts": ["posing", "tease"], "explicitness": "suggestive"})
    assert build["stands_alone"] is False and build["payoff_acts"] == [], build


async def case_ladder_rung() -> None:
    assert B.sellability({"explicitness": "sfw"})["rung"] == 0
    assert B.sellability({"explicitness": "hardcore"})["rung"] == len(B.EXPLICITNESS_LADDER) - 1
    assert B.sellability({"explicitness": "suggestive"})["rung"] < \
        B.sellability({"explicitness": "explicit"})["rung"]
    unknown = B.sellability({"explicitness": "spicy"})
    assert unknown["rung"] is None and unknown["tier"] == "spicy", unknown


async def case_missing_fields_degrade() -> None:
    assert B.load_fields(None) == {}
    assert B.load_fields("not json") == {}
    assert B.load_fields('["a","list"]') == {}


def _flags(vulva="not_in_frame", breasts="not_in_frame", anus="not_in_frame",
           *, underwear=True, over_vulva="", over_breasts="") -> dict:
    out = {"underwear_visible": underwear, "vulva_vis": vulva,
           "breasts_vis": breasts, "anus_vis": anus}
    if over_vulva:
        out["over_vulva"] = over_vulva
    if over_breasts:
        out["over_breasts"] = over_breasts
    return out


_THONG_TOPLESS = {"explicitness": "explicit", "clothing_state": "fully_nude",
                  **_flags(vulva="covered", breasts="bare", over_vulva="black lace thong")}
_HAND_BRA = {"explicitness": "explicit", "clothing_state": "fully_nude",
             **_flags(vulva="covered", breasts="covered", over_vulva="black lace thong",
                      over_breasts="her right hand")}
_BLACK_TOP = {"explicitness": "suggestive", "clothing_state": "lingerie_on",
              **_flags(breasts="covered", over_breasts="black top", underwear=False)}
_OFFSCREEN = {"explicitness": "explicit", "clothing_state": "pulled_down",
              "penetration": "fingers", "acts": ["posing", "rubbing_clit", "fingering"],
              **_flags(breasts="bare", underwear=True, over_vulva="")}


async def case_settled_reading_table() -> None:
    rows = (
        ("nude_but_clothed: topless, thong on", _THONG_TOPLESS,
         ["nude_but_clothed"], {"clothing_state": "pulled_down"}),
        ("nude_but_clothed: a hand is not a garment", _HAND_BRA,
         ["nude_but_clothed"], {"clothing_state": "pulled_down"}),
        ("nude_but_clothed: garments over both", {**_HAND_BRA, "over_breasts": "black lace bra"},
         ["nude_but_clothed"], {"clothing_state": "lingerie_on"}),
        ("nude_but_clothed: nothing named, a garment seen",
         {**_THONG_TOPLESS, "over_vulva": "", "vulva_vis": "bare"},
         ["nude_but_clothed"], {"clothing_state": "partially_off"}),
        ("lingerie_but_nothing_on: nothing bare is dressed", _BLACK_TOP,
         ["lingerie_but_nothing_on"], {"clothing_state": "dressed"}),
        ("lingerie_but_nothing_on: topless, skirt on",
         {**_BLACK_TOP, "breasts_vis": "bare", "over_breasts": "",
          "vulva_vis": "covered", "over_vulva": "denim skirt"},
         ["lingerie_but_nothing_on"], {"clothing_state": "pulled_down"}),
        ("lingerie_but_nothing_on: both bare is never fully_nude",
         {**_BLACK_TOP, "breasts_vis": "bare", "over_breasts": "", "vulva_vis": "bare"},
         ["lingerie_but_nothing_on"], {"clothing_state": "partially_off"}),
        ("dressed_but_bare: suggestive lifts to explicit",
         {"explicitness": "suggestive", "clothing_state": "dressed", **_flags(breasts="bare")},
         ["dressed_but_bare"], {"explicitness": "explicit"}),
        ("dressed_but_bare: already explicit stays",
         {"explicitness": "hardcore", "clothing_state": "dressed", **_flags(vulva="bare")},
         ["dressed_but_bare"], {}),
        ("sfw_but_bare: lifts to explicit, clothing kept",
         {"explicitness": "sfw", "clothing_state": "pulled_down", **_flags(breasts="bare")},
         ["sfw_but_bare"], {"explicitness": "explicit"}),
        ("sfw + dressed + bare: both codes, one lift",
         {"explicitness": "sfw", "clothing_state": "dressed", **_flags(anus="bare")},
         ["dressed_but_bare", "sfw_but_bare"], {"explicitness": "explicit"}),
        ("penetration_offscreen: acts and penetration kept", _OFFSCREEN,
         ["penetration_offscreen"], {}),
    )
    for name, fields, codes, want in rows:
        before = dict(fields)
        got = B.settled_reading(fields)
        assert fields == before, f"{name}: input mutated"
        assert got[B.SETTLED_KEY] == codes, f"{name}: {got[B.SETTLED_KEY]} != {codes}"
        assert got == {**fields, **want, B.SETTLED_KEY: codes}, f"{name}: {got}"
        assert got.get("clothing_state") != "fully_nude", f"{name}: settled as fully nude"
        assert B.settled_reading(got) is got, f"{name}: not idempotent"
        assert B.is_disputed(got) and B.is_disputed(fields), name
        assert B.settled_codes(got) == codes, name
    clean = {"explicitness": "explicit", "clothing_state": "pulled_down", **_flags(breasts="bare")}
    assert B.settled_reading(clean) is clean and not B.is_disputed(clean)
    unflagged = {"explicitness": "sfw", "clothing_state": "dressed"}
    assert B.settled_reading(unflagged) is unflagged
    assert B.settled_reading(None) is None and B.settled_notes(None) == []


async def case_copy_claims_only_what_both_passes_agree_on() -> None:
    nude = B.sellability(_THONG_TOPLESS)
    assert nude["reveal"] == B._REVEAL_TENSION["pulled_down"], nude
    assert "nothing left" not in nude["reveal"] and nude["clothing"] == "pulled_down"

    covered = B.sellability({"explicitness": "sfw", "clothing_state": "pulled_down",
                             **_flags(breasts="bare")})
    assert covered["reveal"] == B._REVEAL_TENSION["dressed"], covered
    assert covered["tier"] == "explicit", "priced as the flags see it"

    off = B.sellability(_OFFSCREEN)
    assert off["payoff_acts"] == [] and off["stands_alone"] is False, off
    assert off["penetration"] == "", off
    assert B.claimed_acts(_OFFSCREEN) == ["posing"]
    seen = {**_OFFSCREEN, "vulva_vis": "bare"}
    assert B.sellability(seen)["payoff_acts"] == ["fingering", "rubbing_clit"]
    assert B.sellability(seen)["penetration"] == "fingers"

    notes = B.settled_notes(_THONG_TOPLESS)
    assert notes == ["clothing_state=fully_nude, yet a garment is visible → read as pulled_down",
                     "never in a free lane"], notes
    assert B.settled_notes(_OFFSCREEN)[0] == (
        f"{B.CONTRADICTIONS['penetration_offscreen']} → copy claims no genital act")


_harness.run(
    case_settled_reading_table,
    case_copy_claims_only_what_both_passes_agree_on,
    case_solo_is_never_assumed,
    case_stands_alone_vs_buildup,
    case_ladder_rung,
    case_missing_fields_degrade,
)
