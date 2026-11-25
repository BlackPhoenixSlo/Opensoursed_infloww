#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import asyncio  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import vault_scripts  # noqa: E402

vault_scripts.MIN_SCRIPT_ITEMS = 3
vault_scripts.MIN_SCRIPT_VIDEOS = 0
from db.engine import get_session  # noqa: E402
from db.models import (Account, VaultFolder,
                       VaultFolderItem, VaultItem)  # noqa: E402
from vault_scripts import escalation_score  # noqa: E402

_AID_N = 0


def _next_account() -> str:
    global _AID_N
    _AID_N += 1
    return f"script{_AID_N}"


def _fields(clothing: str | None = None, acts: list[str] | None = None,
            penetration: str | None = None, explicitness: str | None = None
            ) -> dict:
    out: dict = {}
    if clothing is not None:
        out["clothing_state"] = clothing
    if acts is not None:
        out["acts"] = acts
    if penetration is not None:
        out["penetration"] = penetration
    if explicitness is not None:
        out["explicitness"] = explicitness
    return out



def case_ladder_orders_the_arc() -> None:
    arc = [
        ("dressed opener", _fields("dressed", ["posing"], "none", "sfw")),
        ("lingerie tease", _fields("lingerie_on", ["tease"], "none", "suggestive")),
        ("stripping", _fields("partially_off", ["strip"], "none", "suggestive")),
        ("nude posing", _fields("fully_nude", ["posing"], "none", "explicit")),
        ("rubbing", _fields("fully_nude", ["rubbing_clit"], "none", "explicit")),
        ("fingering", _fields("fully_nude", ["fingering"], "fingers", "explicit")),
        ("orgasm", _fields("fully_nude", ["masturbation_orgasm"], "fingers", "hardcore")),
    ]
    scores = [(name, escalation_score(f)) for name, f in arc]
    for (n_a, s_a), (n_b, s_b) in zip(scores, scores[1:]):
        assert s_a is not None and s_b is not None, f"unscoreable rung: {n_a}/{n_b}"
        assert s_a < s_b, f"ladder not monotone: {n_a}={s_a} !< {n_b}={s_b} ({scores})"


def case_highest_act_wins() -> None:
    opens_tame = escalation_score(_fields("fully_nude", ["tease", "toy_insertion"], "toy", "explicit"))
    tease_only = escalation_score(_fields("fully_nude", ["tease"], "none", "explicit"))
    insert_only = escalation_score(_fields("fully_nude", ["toy_insertion"], "toy", "explicit"))
    assert opens_tame == insert_only, (
        f"a clip that ENDS at insertion must score there, got {opens_tame} vs {insert_only}")
    assert opens_tame > tease_only, "adding an insertion beat must raise the score"


def case_penetration_scores_without_acts() -> None:
    bare = escalation_score(_fields("fully_nude", [], None, "explicit"))
    with_pen = escalation_score(_fields("fully_nude", [], "toy", "explicit"))
    assert bare is not None and with_pen is not None
    assert with_pen > bare, f"penetration must lift the score alone ({bare} → {with_pen})"


def case_unscoreable_is_none_not_zero() -> None:
    for f in ({}, {"clothing_state": "unclear", "acts": [], "penetration": "unclear"},
              {"acts": ["not_a_real_act"]}, {"description": "prose only"}):
        assert escalation_score(f) is None, f"expected None (not 0) for {f}"
    assert escalation_score(None) is None  # type: ignore[arg-type]
    assert escalation_score("nonsense") is None  # type: ignore[arg-type]


def case_missing_axis_does_not_shift_the_others() -> None:
    no_acts = escalation_score(_fields("fully_nude", None, None, "explicit"))
    with_tame_act = escalation_score(_fields("fully_nude", ["posing"], "none", "explicit"))
    assert no_acts == with_tame_act, (
        f"adding a LOW act changed a saturated score ({no_acts} → {with_tame_act})")
    assert no_acts is not None and no_acts > 50, (
        f"missing `acts` dragged a nude item to {no_acts}")


def case_act_alias_is_scored() -> None:
    assert (escalation_score(_fields("lingerie_on", ["stripping"]))
            == escalation_score(_fields("lingerie_on", ["strip"]))), "alias not mapped"
    assert (escalation_score(_fields("fully_nude", ["rubbing_breasts"]))
            == escalation_score(_fields("fully_nude", ["groping_own_breasts"])))
    assert escalation_score(_fields(None, ["lying_on_back"])) is None



async def _seed(aid: str, items: list[tuple]) -> None:
    async with get_session() as s:
        s.add(Account(id=aid))
        await s.commit()
    async with get_session() as s:
        for row in items:
            mid, minutes, fields = row[0], row[1], row[2]
            kind = row[3] if len(row) > 3 else "video"
            s.add(VaultItem(
                account_id=aid, media_id=mid, kind=kind,
                created_at=datetime(2026, 7, 1) + timedelta(minutes=minutes),
                tags="[]", describe_status="described",
                ai_fields_json=json.dumps(fields),
            ))
        await s.commit()


def case_buildup_sends_before_payoff_at_same_rung() -> None:
    tease = _fields("fully_nude", ["posing", "tease"], "none", "explicit")
    closes = _fields("fully_nude", ["fingering"], "fingers", "explicit")
    assert vault_scripts.send_sort_key(tease) < vault_scripts.send_sort_key(closes), (
        "build-up must send before a payoff at the same rung")
    assert vault_scripts.send_order_reason(tease)["closes"] is False
    assert vault_scripts.send_order_reason(closes)["closes"] is True


def case_rung_outranks_everything_below_it() -> None:
    suggestive_closer = _fields("lingerie_on", ["rubbing_clit"], "none", "suggestive")
    explicit_buildup = _fields("fully_nude", ["posing"], "none", "explicit")
    assert (vault_scripts.send_sort_key(suggestive_closer)
            < vault_scripts.send_sort_key(explicit_buildup)), "rung must dominate"


def case_send_order_reads_brief_not_a_second_taxonomy() -> None:
    import vault_ai_brief as brief
    act = sorted(brief._PAYOFF_ACTS)[0]
    assert vault_scripts.send_order_reason(_fields("fully_nude", [act]))["closes"] is True
    assert brief.EXPLICITNESS_LADDER == ("sfw", "suggestive", "explicit", "hardcore")


def _outfit(colour_items: list[str], acts: list[str], tier: str,
            clothing: str = "lingerie_on") -> dict:
    return {**_fields(clothing, acts, "none", tier), "clothing_items": colour_items}


def _shot(body: list[str], tier: str, clothing: str, garment: str = "white bra") -> dict:
    return {**_fields(clothing, ["posing"], "none", tier),
            "clothing_items": [garment], "body_focus": body}


def _flags(vulva: str = "not_in_frame", breasts: str = "not_in_frame",
           anus: str = "not_in_frame", *, underwear: bool = True,
           over_vulva: str = "", over_breasts: str = "", over_anus: str = "") -> dict:
    out = {"underwear_visible": underwear, "vulva_vis": vulva,
           "breasts_vis": breasts, "anus_vis": anus}
    for key, val in (("over_vulva", over_vulva), ("over_breasts", over_breasts),
                     ("over_anus", over_anus)):
        if val:
            out[key] = val
    return out


def _dressed(**kw) -> dict:
    return _flags(vulva="covered", breasts="covered",
                  over_vulva="black lace bodysuit",
                  over_breasts="black lace bodysuit", **kw)


def _turned_away(**kw) -> dict:
    return _flags(vulva="not_in_frame", breasts="not_in_frame",
                  anus="covered", **kw)


# Fully nude is never the $10 tier; a price may only rest on a flag that was actually answered.
def case_price_tiers_split_on_nudity_and_visibility() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1101, 0.0, _shot(["face"], "sfw", "dressed"), "photo"),
        (1102, 0.1, _shot(["breasts"], "suggestive", "lingerie_on"), "photo"),
        (1103, 0.2, {**_shot(["breasts", "nipples"], "explicit", "pulled_down"),
                     **_flags(breasts="bare")}, "photo"),
        (1104, 0.3, {**_shot(["breasts"], "explicit", "fully_nude"),
                     **_flags(breasts="bare", underwear=False)}, "photo"),
        (1105, 0.4, {**_shot(["pussy"], "explicit", "pulled_aside"),
                     **_flags(vulva="bare", breasts="covered")}, "photo"),
        (1106, 0.5, {**_shot(["full_body"], "explicit", "fully_nude"),
                     **_flags(breasts="bare", underwear=False)}, "photo"),
        (1107, 0.6, _shot(["breasts", "nipples"], "explicit", "pulled_down"), "photo"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    assert set(lanes) >= {"stories", "mass", "tease_10", "tease_50"}, list(lanes)
    assert {r["media_id"] for r in lanes["tease_10"]["items"]} == {1103}, \
        "$10 is breasts out with something still ON, and only when checked"
    assert {r["media_id"] for r in lanes["tease_50"]["items"]} == {1104, 1105, 1106}, \
        "fully nude / pussy visible / full-body all price at $50"
    assert not ({r["media_id"] for r in lanes["tease_10"]["items"]}
                & {r["media_id"] for r in lanes["tease_50"]["items"]}), \
        "an item cannot be both a $10 and a $50"
    assert all(f["name"].startswith("AI-") for f in lanes.values()), "missing AI- prefix"


def case_fifty_never_contains_lingerie_on() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1141, 0.0, {**_shot(["pussy", "breasts"], "explicit", "lingerie_on"),
                     **_flags(vulva="bare", breasts="bare",
                              over_vulva="black lace thong")}, "photo"),
        (1142, 0.1, {**_shot(["pussy"], "explicit", "fully_nude"),
                     **_flags(vulva="bare", underwear=False)}, "photo"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    fifty = {r["media_id"] for r in lanes["tease_50"]["items"]}
    assert fifty == {1142}, f"lingerie_on leaked into $50: {fifty}"


def case_pussy_and_breasts_are_asked_separately() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1161, 0.0, {**_shot(["breasts", "nipples", "pussy"], "explicit", "pulled_down"),
                     **_flags(vulva="covered", breasts="bare")}, "photo"),
        (1162, 0.1, {**_shot(["breasts", "pussy"], "explicit", "pulled_aside"),
                     **_flags(vulva="bare", breasts="covered")}, "photo"),
        (1163, 0.2, {**_shot(["pussy"], "explicit", "lingerie_on"),
                     **_flags(vulva="covered", breasts="covered")}, "photo"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    ten = {r["media_id"] for r in lanes.get("tease_10", {"items": []})["items"]}
    fifty = {r["media_id"] for r in lanes.get("tease_50", {"items": []})["items"]}
    assert ten == {1161}, f"boobs-out/pussy-covered must be the $10: {ten}"
    assert fifty == {1162}, f"only pussy-on-show is a $50: {fifty}"
    assert 1163 not in ten and 1163 not in fifty, "a covered pussy is not a reveal"


def case_underwear_flag_overrides_the_clothing_enum() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1151, 0.0, {**_shot(["breasts"], "explicit", "fully_nude"),
                     **_flags(breasts="bare", underwear=True)}, "photo"),
        (1152, 0.1, {**_shot(["breasts"], "explicit", "fully_nude"),
                     **_flags(breasts="bare", underwear=False)}, "photo"),
        (1153, 0.2, {**_shot(["pussy"], "explicit", "fully_nude"),
                     **_flags(vulva="covered", underwear=True)}, "photo"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    fifty = {r["media_id"] for r in lanes["tease_50"]["items"]}
    assert 1151 not in fifty, "flag said underwear visible; enum must not win"
    assert 1152 in fifty, "genuinely nude item lost from $50"
    assert 1153 not in fifty, "a covered vulva must never be a $50"


def case_mass_lane_is_suggestive_only() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1111, 0.0, _shot(["face"], "sfw", "dressed"), "photo"),
        (1112, 0.1, _shot(["breasts"], "suggestive", "lingerie_on"), "photo"),
        (1113, 0.2, _shot(["pussy"], "explicit", "fully_nude"), "photo"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    assert {r["media_id"] for r in lanes["mass"]["items"]} == {1112}, "not suggestive-only"
    assert "free_tease" not in lanes, "the suggestive→explicit lane must be gone"


def case_nothing_on_show_is_never_a_tease() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1171, 0.0, {**_shot(["breasts", "face"], "explicit", "lingerie_on"),
                     **_dressed()}, "photo"),
        (1172, 0.1, {**_shot(["ass", "back"], "explicit", "fully_nude"),
                     **_turned_away(underwear=False)}, "photo"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    safe = {r["media_id"] for r in lanes["covered_explicit"]["items"]}
    assert safe == {1171, 1172}, f"both belong in the mass-safe lane: {safe}"
    for tier in ("tease_10", "tease_50"):
        got = {r["media_id"] for r in lanes.get(tier, {"items": []})["items"]}
        assert not got & {1171, 1172}, f"{tier} charged for a non-reveal: {got}"


# The mass-safe lane needs positive evidence: absent flags must not read as nothing on show.
def case_unflagged_item_is_never_called_mass_safe() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1401, 0.0, {**_shot(["ass", "back"], "explicit", "fully_nude"),
                     **_turned_away(underwear=False)}, "photo"),
        (1402, 0.1, _shot(["ass", "back"], "explicit", "fully_nude"), "photo"),
        (1403, 0.2, {"explicitness": "explicit"}, "video"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    safe = {r["media_id"] for r in lanes.get("covered_explicit", {}).get("items", [])}
    assert safe == {1401}, f"an unflagged item was called mass-safe: {safe}"


def case_unflagged_stills_wait_out_of_the_price_lanes() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1451, 0.0, {**_shot(["breasts"], "explicit", "pulled_down"),
                     **_flags(breasts="bare")}, "photo"),
        (1452, 0.1, {**_shot(["full_body"], "explicit", "fully_nude"),
                     **_flags(vulva="bare", breasts="bare", underwear=False)}, "photo"),
        (1453, 0.2, {**_shot(["ass"], "explicit", "fully_nude"),
                     **_turned_away(underwear=False)}, "photo"),
        (1454, 0.3, _shot(["full_body", "pussy"], "explicit", "fully_nude"), "photo"),
        (1455, 0.4, _shot(["breasts"], "explicit", "fully_nude"), "photo"),
        (1456, 0.5, {**_shot(["breasts"], "explicit", "pulled_down"),
                     "breasts_vis": "bare"}, "photo"),
        (1457, 0.6, {**_shot(["pussy"], "explicit", "fully_nude"),
                     "vulva_vis": "bare", "breasts_vis": "bare"}, "photo"),
    ]))
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=0))
    lanes = {f["lane"]: {r["media_id"] for r in f["items"]}
             for f in plan["folders"] if f["source"] == "lane"}
    unchecked = {1454, 1455, 1456, 1457}
    assert lanes.get("tease_10") == {1451}, lanes
    assert lanes.get("tease_50") == {1452}, lanes
    assert lanes.get("covered_explicit") == {1453}, lanes
    assert lanes.get("explicit_rest", set()) >= unchecked, \
        f"unchecked paid stills fell out of every folder: {lanes}"
    assert plan["flags"]["missing"] == 4 and plan["flags"]["ready"] is False, plan["flags"]
    assert plan["summary"]["folders"] > 0, "a part-flagged vault must still plan"


def case_mass_safe_needs_to_know_what_is_in_frame() -> None:
    explicit = {"explicitness": "explicit"}
    anal = {**explicit, **_flags(anus="bare", underwear=False),
            "body_focus": ["ass", "anus", "fingers"]}
    turned_away = {**explicit, **_turned_away(underwear=False),
                   "body_focus": ["ass", "back", "legs"]}
    blind_dildo = {**explicit, **_flags(underwear=False),
                   "acts": ["toy_insertion"], "body_focus": None}

    for name, f in (("anal", anal), ("nothing visible but penetrating", blind_dildo)):
        assert not vault_scripts._lane_covered_explicit(
            vault_scripts.send_order_reason(f), f, "video"), f"{name} called mass-safe"
    assert vault_scripts._lane_covered_explicit(
        vault_scripts.send_order_reason(turned_away), turned_away, "photo"), \
        "a genuinely turned-away shot must still qualify"
    assert vault_scripts._shows_genitals(anal) is True


def case_a_named_garment_means_she_is_dressed() -> None:
    import vault_ai_brief as brief

    dressed = {**_flags(), "over_breasts": "pink tank top",
               "over_vulva": "white skirt", "underwear_visible": False}
    assert brief.wearing_something(dressed) is True
    assert vault_scripts._is_nude(dressed) is False, "a dressed selfie read as nude"
    assert vault_scripts._is_nude({**_flags(), "underwear_visible": False}) is True

    hand = {**_flags(underwear=False), "over_breasts": "her right hand",
            "over_vulva": "her left thigh"}
    assert brief.wearing_something(hand) is False
    assert vault_scripts._is_nude(hand) is True, "a hand-bra nude lost its price"
    thong = {**_flags(underwear=False), "over_breasts": "her right hand",
             "over_vulva": "black lace thong"}
    assert vault_scripts._is_nude(thong) is False, "a thong is not nude"
    for body in ("her hands", "the bedsheet", "her left thigh", "her own arm", "shadow"):
        assert not brief.is_clothing(body), f"{body!r} counted as clothing"
    for worn in ("black lace thong", "white tank top", "bodysuit", "a sheer kimono"):
        assert brief.is_clothing(worn), f"{worn!r} not counted as clothing"


def case_a_hand_over_her_breast_is_not_being_dressed() -> None:
    import vault_ai_brief as brief

    nude_hands = {"explicitness": "explicit", "clothing_state": "fully_nude",
                  **_flags(vulva="covered", breasts="covered", underwear=False,
                           over_vulva="her left thigh",
                           over_breasts="her right hand")}
    dressed = {"explicitness": "explicit", **_dressed()}
    unnamed = {"explicitness": "explicit",
               **_flags(vulva="covered", breasts="covered")}

    def safe(f: dict) -> bool:
        return vault_scripts._lane_covered_explicit(
            vault_scripts.send_order_reason(f), f, "photo")

    assert not safe(nude_hands), "a hand-bra nude was called safe to mass"
    assert safe(dressed), "a woman in a bodysuit must be mass-safe"
    assert safe({"explicitness": "explicit", **_turned_away(underwear=False)}), \
        "a shot from behind must be mass-safe — it is what the lane is FOR"
    topless_thong = {"explicitness": "explicit", "clothing_state": "fully_nude",
                     **_flags(vulva="covered", breasts="covered", anus="covered",
                              underwear=True, over_vulva="pink thong",
                              over_breasts="her hands")}
    assert not vault_scripts._is_nude(topless_thong), "fixture should read clothed"
    assert not safe(topless_thong), "topless-with-hands went to a mass send"
    assert not safe(unnamed), "an unexplained `covered` was treated as dressed"

    thong_on_breasts = {"explicitness": "explicit",
                        **_flags(vulva="covered", breasts="covered",
                                 over_vulva="pink thong",
                                 over_breasts="pink thong")}
    assert brief.garment_over(thong_on_breasts, "breasts_vis") == "", \
        "a thong was accepted as covering her breasts"
    assert brief.garment_over(thong_on_breasts, "vulva_vis") == "pink thong"
    assert not safe(thong_on_breasts), "a topless still reached the mass-safe lane"
    suit = {"explicitness": "explicit",
            **_flags(vulva="covered", breasts="covered",
                     over_vulva="black lace bodysuit",
                     over_breasts="black lace bodysuit")}
    assert safe(suit), "a bodysuit over both regions was rejected as duplication"

    assert vault_scripts._is_nude(nude_hands) is True


def case_not_in_frame_is_an_answer_not_a_silence() -> None:
    import vault_ai_brief as brief

    unseen = _flags(vulva="not_in_frame")
    bare = _flags(vulva="bare")
    assert brief.flags_known(unseen) and brief.flags_known(bare), \
        "both are fully answered rows"
    assert brief.vis(unseen, "vulva_vis") != brief.vis(bare, "vulva_vis"), \
        "the two states collapsed into one — this is the bug the enum removes"
    assert brief.is_bare(bare, "vulva_vis") is True
    assert brief.is_bare(unseen, "vulva_vis") is False


def case_partial_flags_do_not_count_as_checked() -> None:
    import vault_ai_brief as brief

    assert brief.flags_known(_flags()) is True
    assert brief.flags_known({"vulva_vis": "covered"}) is False
    assert brief.flags_known({}) is False
    for junk in ("no", True, "hidden", None, ""):
        assert brief.flags_known({**_flags(), "breasts_vis": junk}) is False, \
            f"{junk!r} accepted as a region state"
    assert brief.flags_known({"underwear_visible": False, "pussy_covered": True,
                              "breasts_covered": True}) is False


def case_clip_frames_fold_by_worst_not_by_all() -> None:
    import vault_ai_brief as brief

    assert brief.fold_vis(["covered", "not_in_frame", "covered"]) == "covered", \
        "a frame that saw nothing must not vote for exposure"
    assert brief.fold_vis(["covered", "bare", "covered"]) == "bare", \
        "one bare frame exposes the clip"
    assert brief.fold_vis(["not_in_frame"] * 4) == "not_in_frame"
    assert brief.fold_vis([]) == "", "no frames is unknown, not safe"
    assert brief.fold_vis(["junk", "bare"]) == "bare", "junk must not win"


def case_contradictions_score_only_answered_rows() -> None:
    import vault_ai_brief as brief

    dressed_but_bare = {"clothing_state": "dressed", "explicitness": "suggestive",
                        **_flags(breasts="bare")}
    assert "dressed_but_bare" in brief.contradictions(dressed_but_bare)
    nude_but_clothed = {"clothing_state": "fully_nude", "explicitness": "explicit",
                        **_flags(breasts="bare", underwear=True)}
    assert "nude_but_clothed" in brief.contradictions(nude_but_clothed)
    offscreen = {"clothing_state": "fully_nude", "explicitness": "explicit",
                 "penetration": "vaginal", **_flags(underwear=False)}
    assert "penetration_offscreen" in brief.contradictions(offscreen)

    consistent = {"clothing_state": "lingerie_on", "explicitness": "suggestive",
                  **_flags(vulva="covered", breasts="covered")}
    assert brief.contradictions(consistent) == []
    assert brief.contradictions({"clothing_state": "dressed"}) == []
    assert all(c in brief.CONTRADICTIONS
               for c in brief.contradictions(dressed_but_bare)), "undocumented code"


def case_turned_away_explicit_is_safe_to_mass() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1121, 0.0, {**_shot(["ass", "back"], "explicit", "fully_nude"),
                     **_turned_away(underwear=False)}, "photo"),
        (1122, 0.1, {**_shot(["pussy"], "explicit", "fully_nude"),
                     **_flags(vulva="bare", breasts="covered", underwear=False)}, "photo"),
        (1123, 0.2, {**_shot(["breasts"], "explicit", "fully_nude"),
                     **_flags(vulva="covered", breasts="bare", underwear=False)}, "photo"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    assert {r["media_id"] for r in lanes["covered_explicit"]["items"]} == {1121}, \
        "only the turned-away shot is safe"


def case_paid_tease_lanes_are_images_only() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1131, 0.0, {**_shot(["pussy"], "explicit", "fully_nude"),
                     **_flags(vulva="bare", underwear=False)}, "video"),
        (1132, 0.1, {**_shot(["pussy"], "explicit", "fully_nude"),
                     **_flags(vulva="bare", underwear=False)}, "photo"),
        (1133, 0.2, {**_shot(["breasts"], "explicit", "fully_nude"),
                     **_flags(breasts="bare", underwear=False)}, "video"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    assert {r["media_id"] for r in lanes["tease_50"]["items"]} == {1132}, "clip leaked in"
    assert "tease_10" not in lanes or not lanes["tease_10"]["items"], "clip leaked in"


def case_suggestive_item_sits_in_both_lanes_at_different_positions() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1201, 0.0, _outfit(["white top"], ["posing"], "sfw", "dressed"), "photo"),
        (1202, 0.1, _outfit(["white top"], ["posing"], "sfw", "dressed"), "photo"),
        (1203, 0.2, _outfit(["white top"], ["tease"], "suggestive"), "photo"),
        (1204, 0.3, _outfit(["white bra"], ["fingering"], "explicit", "fully_nude"), "photo"),
        (1205, 0.4, _outfit(["white bra"], ["rubbing_clit"], "explicit", "pulled_aside"), "photo"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    pos = {lane: {r["media_id"]: r["manual_order"] for r in f["items"]}
           for lane, f in lanes.items()}
    assert 1203 in pos["stories"] and 1203 in pos["mass"], "not in both lanes"
    assert pos["stories"][1203] == len(lanes["stories"]["items"]), \
        "the suggestive still must CLOSE the tamer lane"


def case_purpose_pool_can_be_restricted_to_leftovers() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1301, 0.0, _outfit(["white top"], ["posing"], "sfw", "dressed"), "photo"),
        (1302, 0.1, _outfit(["white top"], ["tease"], "suggestive"), "photo"),
        (1303, 0.2, _outfit(["white top"], ["tease"], "suggestive"), "photo"),
        (1304, 0.3, _outfit(["red bra"], ["fingering"], "explicit", "fully_nude"), "photo"),
    ]))
    lanes = asyncio.run(vault_scripts.collect_purpose_folders(
        aid, media_ids=[1301, 1302, 1303]))
    ids = {r["media_id"] for f in lanes for r in f["items"]}
    assert 1304 not in ids, "a kept shoot's media leaked into the leftover lanes"


def case_outfit_key_prefers_multiword_colour() -> None:
    assert vault_scripts.outfit_colour({"clothing_items": ["dark blue lace bra"]}) == "dark blue"
    assert vault_scripts.outfit_colour({"clothing_items": ["blue bra"]}) == "blue"


def case_outfit_key_falls_back_and_gives_up() -> None:
    assert vault_scripts.outfit_colour({"clothing_items": ["lace bodysuit"]}) == "lace"
    assert vault_scripts.outfit_key({"clothing_items": []}) == ""
    assert vault_scripts.outfit_key({}) == ""
    assert vault_scripts.outfit_key(None) == ""  # type: ignore[arg-type]


def case_same_colour_different_garment_is_a_different_set() -> None:
    body = {"clothing_items": ["black lace bodysuit", "fishnet stockings"]}
    bra = {"clothing_items": ["black lace bra", "black lace panties"]}
    top = {"clothing_items": ["black leather jacket", "black top"]}
    keys = {vault_scripts.outfit_key(f) for f in (body, bra, top)}
    assert keys == {"black bodysuit", "black lingerie_set", "black top"}, keys
    assert vault_scripts.garment_class(body) == "bodysuit", "hosiery outranked the set"


def case_undressing_does_not_split_a_script() -> None:
    on = {"clothing_items": ["pink lace bra"], "clothing_state": "lingerie_on"}
    aside = {"clothing_items": ["pink lace bra"], "clothing_state": "pulled_aside"}
    nude = {"clothing_items": ["pink lace bra"], "clothing_state": "fully_nude"}
    assert len({vault_scripts.outfit_key(f) for f in (on, aside, nude)}) == 1


def case_unrecognised_garment_still_keys_on_colour() -> None:
    assert vault_scripts.outfit_key({"clothing_items": ["red kimono thing"]}) == "red"


def case_outfit_joins_photos_and_videos_into_one_script() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (701, 0.0, _outfit(["pink lace bra"], ["posing"], "sfw", "dressed"), "photo"),
        (702, 0.1, _outfit(["pink lace bra"], ["tease"], "suggestive"), "photo"),
        (703, 0.2, _outfit(["pink lace panties"], ["tease"], "suggestive"), "photo"),
        (704, 300.0, _outfit(["pink lace thong"], ["rubbing_clit"], "explicit",
                             "pulled_aside"), "video"),
        (705, 300.1, _outfit(["pink thong"], ["fingering"], "explicit",
                             "fully_nude"), "video"),
    ]))

    scripts = asyncio.run(vault_scripts.collect_outfit_scripts(aid))
    assert len(scripts) == 1, f"outfit did not join the bursts: {scripts}"
    sc = scripts[0]
    assert sc["outfit"] == "pink lingerie_set", sc["outfit"]
    assert sc["mixed"] is True and sc["kinds"] == {"photo": 3, "video": 2}, sc["kinds"]
    assert [r["media_id"] for r in sc["items"]] == [701, 702, 703, 704, 705], sc["items"]


def case_same_colour_far_apart_is_two_shoots() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (801, 0.0, _outfit(["black lace bra"], ["posing"], "sfw", "dressed")),
        (802, 0.1, _outfit(["black lace bra"], ["tease"], "suggestive")),
        (803, 0.2, _outfit(["black lace bra"], ["fingering"], "explicit", "fully_nude")),
        (804, 30240.0, _outfit(["black lace bra"], ["posing"], "sfw", "dressed")),
        (805, 30240.1, _outfit(["black lace bra"], ["tease"], "suggestive")),
        (806, 30240.2, _outfit(["black lace bra"], ["fingering"], "explicit", "fully_nude")),
    ]))
    scripts = asyncio.run(vault_scripts.collect_outfit_scripts(aid))
    assert len(scripts) == 2, f"time window did not split the colour: {len(scripts)}"
    assert all(s["outfit"] == "black lingerie_set" for s in scripts)


def case_one_rung_group_is_a_set_not_a_script() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (901, 0.0, _outfit(["red satin bra"], ["posing"], "suggestive")),
        (902, 0.1, _outfit(["red satin bra"], ["posing"], "suggestive")),
        (903, 0.2, _outfit(["red satin bra"], ["tease"], "suggestive")),
    ]))
    assert asyncio.run(vault_scripts.collect_outfit_scripts(aid)) == []
    loose = asyncio.run(vault_scripts.collect_outfit_scripts(
        aid, require_escalation=False))
    assert len(loose) == 1, "the group still exists when escalation isn't required"


def case_mixed_media_scripts_rank_first() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1001, 0.0, _outfit(["white bra"], ["posing"], "sfw", "dressed"), "photo"),
        (1002, 0.1, _outfit(["white bra"], ["tease"], "suggestive"), "photo"),
        (1003, 0.2, _outfit(["white bra"], ["fingering"], "explicit",
                            "fully_nude"), "photo"),
        (1004, 1.0, _outfit(["green bra"], ["posing"], "sfw", "dressed"), "photo"),
        (1005, 1.1, _outfit(["green bra"], ["tease"], "suggestive"), "photo"),
        (1006, 1.2, _outfit(["green bra"], ["fingering"], "explicit",
                            "fully_nude"), "video"),
    ]))

    scripts = asyncio.run(vault_scripts.collect_outfit_scripts(aid))
    assert scripts[0]["outfit"] == "green lingerie_set", scripts[0]["outfit"]
    assert scripts[0]["mixed"] is True and scripts[1]["mixed"] is False


def case_a_shoot_that_closes_outranks_a_bigger_one_that_cannot() -> None:
    def shoot(name, *, closes, rungs, paid, mixed, size):
        return {"name": name, "closes_on_own": closes, "rungs": list(range(rungs)),
                "tiers": {"suggestive": size - paid, "explicit": paid},
                "mixed": mixed, "size": size}
    big_dead = shoot("big", closes=0, rungs=3, paid=20, mixed=True, size=90)
    small_closer = shoot("small", closes=1, rungs=2, paid=2, mixed=False, size=6)
    deep = shoot("deep", closes=1, rungs=2, paid=9, mixed=False, size=12)
    deeper_capped = shoot("capped", closes=1, rungs=2, paid=40, mixed=False, size=45)
    mixed_cap = shoot("mixedcap", closes=1, rungs=2, paid=10, mixed=True, size=20)
    wide = shoot("wide", closes=1, rungs=3, paid=1, mixed=False, size=5)
    got = sorted([big_dead, small_closer, deep, deeper_capped, mixed_cap, wide],
                 key=vault_scripts.shoot_rank_key)
    assert [s["name"] for s in got] == ["wide", "mixedcap", "capped", "deep", "small", "big"], \
        [s["name"] for s in got]


class _FakeOF:

    def __init__(self, fail_on: str | None = None) -> None:
        self.created: list[str] = []
        self.added: list[tuple[int, int]] = []
        self.fail_on = fail_on
        self._next = 900
        self.members: dict[int, list[int]] = {}
        self.responded = threading.Event()

    def create_vault_list(self, name: str) -> dict:
        if self.fail_on and self.fail_on in name:
            raise RuntimeError("OF said no")
        self.created.append(name)
        self._next += 1
        return {"id": self._next, "name": name}

    def add_media_to_vault_list(self, list_id: int, media_ids: list[int]) -> dict:
        self.added.append((int(list_id), len(media_ids)))
        have = self.members.setdefault(int(list_id), [])
        have.extend(int(m) for m in media_ids if int(m) not in have)
        return {"success": True}

    def vault_media(self, *, limit=100, offset=0, type="all", list_id=None, **kw) -> dict:
        if not self.responded.wait(timeout=10):
            raise AssertionError("read-back ran inside the request")
        ids = self.members.get(int(list_id), []) if list_id is not None else []
        return {"list": [{"id": m} for m in ids[offset:offset + limit]]}


async def _apply_with_of(aid: str, fake: _FakeOF, keep: int = 1,
                         mirror: bool = True) -> dict:
    import automation_executor as ax
    import vault_ai_api

    orig = ax._make_client
    ax._make_client = lambda *_a, **_k: fake
    before = asyncio.all_tasks()
    fake.responded.clear()
    payload = {"account_id": aid, "keep": keep, "confirm": True}
    if mirror:
        payload["mirror_to_of"] = True
    try:
        res = await vault_ai_api.apply_folder_plan(payload)
    finally:
        ax._make_client = orig
        fake.responded.set()
    await asyncio.wait_for(asyncio.gather(*(asyncio.all_tasks() - before)), timeout=10)
    return res


async def _of_list_ids(aid: str) -> dict[str, int | None]:
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultFolder.name, VaultFolder.of_list_id)
            .where(VaultFolder.account_id == aid, VaultFolder.deleted_at.is_(None))
        )).all()
    return {n: (int(v) if v is not None else None) for n, v in rows}


def case_apply_does_not_touch_of_unless_asked() -> None:
    aid = _next_account()
    _plan_seed(aid)
    fake = _FakeOF()
    asyncio.run(_apply_with_of(aid, fake, mirror=False))
    assert fake.created == [] and fake.added == [], "wrote to OF without mirror_to_of"
    assert all(v is None for v in asyncio.run(_of_list_ids(aid)).values())


def case_mirror_creates_of_lists_and_binds_them() -> None:
    aid = _next_account()
    _plan_seed(aid)
    fake = _FakeOF()
    res = asyncio.run(_apply_with_of(aid, fake))

    assert res["of_failed"] == 0, res
    assert res["of_mirrored"] == res["folders"], res
    assert all(n.startswith("AI-") for n in fake.created), fake.created
    bound = asyncio.run(_of_list_ids(aid))
    assert all(v is not None for v in bound.values()), bound
    assert sum(n for _, n in fake.added) == res["items"], "media count differs"


def case_mirror_rerun_reuses_the_same_of_list() -> None:
    aid = _next_account()
    _plan_seed(aid)
    fake = _FakeOF()
    asyncio.run(_apply_with_of(aid, fake))
    first_created = list(fake.created)

    asyncio.run(_apply_with_of(aid, fake))
    assert fake.created == first_created, f"created duplicate OF lists: {fake.created}"


def case_mirror_binds_membership_into_the_cache() -> None:
    aid = _next_account()
    _plan_seed(aid)
    fake = _FakeOF()
    res = asyncio.run(_apply_with_of(aid, fake))

    async def _picker_would_show(of_list_id: int) -> int:
        async with get_session() as s:
            rows = (await s.execute(
                select(VaultItem.of_folder_ids).where(VaultItem.account_id == aid)
            )).scalars().all()
        return sum(1 for r in rows if of_list_id in json.loads(r or "[]"))

    for made in res["created"]:
        lid = made["of_list_id"]
        shown = asyncio.run(_picker_would_show(lid))
        assert shown == len(fake.members[lid]), (
            f"{made['name']}: OF has {len(fake.members[lid])}, picker shows {shown}")
        assert shown > 0, f"{made['name']}: folder mirrored but invisible in the picker"


def case_mirror_membership_follows_of_not_the_plan() -> None:
    aid = _next_account()
    _plan_seed(aid)
    fake = _FakeOF()
    res = asyncio.run(_apply_with_of(aid, fake))
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    planned = {f["name"]: {int(i["media_id"]) for i in f["items"]}
               for f in plan["folders"]}
    lid = next(c["of_list_id"] for c in res["created"] if c["name"] == "AI-mass")

    stray = 2004
    assert stray not in planned["AI-mass"], planned["AI-mass"]
    assert stray not in fake.members[lid], fake.members[lid]
    fake.members[lid].append(stray)

    asyncio.run(_apply_with_of(aid, fake))

    async def _bound() -> set[int]:
        async with get_session() as s:
            rows = (await s.execute(
                select(VaultItem.media_id, VaultItem.of_folder_ids)
                .where(VaultItem.account_id == aid)
            )).all()
        return {int(m) for m, f in rows if lid in json.loads(f or "[]")}

    assert stray in asyncio.run(_bound()), "cache dropped an item OF still holds"


def case_of_failure_keeps_the_internal_folder() -> None:
    aid = _next_account()
    _plan_seed(aid)
    fake = _FakeOF(fail_on="stories")
    res = asyncio.run(_apply_with_of(aid, fake))

    assert res["of_failed"] == 1, res
    assert asyncio.run(_count_folders(aid)) == res["folders"], "internal folder lost"
    failed = [c for c in res["created"] if c.get("of_error")]
    assert failed and "stories" in failed[0]["name"], failed


async def _read_order(aid: str, folder_id: int) -> list[tuple[int, int]]:
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultFolderItem.media_id, VaultFolderItem.manual_order)
            .where(VaultFolderItem.account_id == aid,
                   VaultFolderItem.folder_id == folder_id)
            .order_by(VaultFolderItem.manual_order.asc())
        )).all()
    return [(int(m), int(o)) for m, o in rows]


def _plan_seed(aid: str) -> None:
    asyncio.run(_seed(aid, [
        (2001, 0.0, _shot(["face"], "sfw", "dressed", "pink lace bra"), "photo"),
        (2002, 0.1, _shot(["breasts"], "suggestive", "lingerie_on", "pink lace bra"), "photo"),
        (2003, 0.2, _shot(["breasts"], "explicit", "pulled_down", "pink lace bra"), "photo"),
        (2004, 0.3, _shot(["pussy"], "explicit", "fully_nude", "pink lace panties"), "photo"),
        (2005, 0.4, _shot(["pussy"], "explicit", "pulled_aside", "pink lace thong"), "video"),
    ]))


def case_plan_previews_without_creating_anything() -> None:
    aid = _next_account()
    _plan_seed(aid)
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    assert plan["summary"]["folders"] > 0, plan["summary"]
    assert all(f["name"].startswith("AI-") for f in plan["folders"])
    assert asyncio.run(_count_folders(aid)) == 0, "preview created a folder"


def case_apply_creates_folders_in_send_order() -> None:
    aid = _next_account()
    _plan_seed(aid)
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    res = asyncio.run(vault_scripts.apply_ai_folders(aid, plan))

    assert res["folders"] == plan["summary"]["folders"], res
    assert res["new"] == res["folders"] and res["reused"] == 0
    assert asyncio.run(_count_folders(aid)) == res["folders"]

    for spec, made in zip(plan["folders"], res["created"]):
        got = asyncio.run(_read_order(aid, made["folder_id"]))
        assert [m for m, _ in got] == [r["media_id"] for r in spec["items"]], \
            f"{made['name']}: order differs from the preview"
        assert [o for _, o in got] == list(range(1, len(got) + 1)), got


def case_apply_twice_refreshes_instead_of_duplicating() -> None:
    aid = _next_account()
    _plan_seed(aid)
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    first = asyncio.run(vault_scripts.apply_ai_folders(aid, plan))
    second = asyncio.run(vault_scripts.apply_ai_folders(aid, plan))

    assert second["reused"] == second["folders"] and second["new"] == 0, second
    assert asyncio.run(_count_folders(aid)) == first["folders"], "folders duplicated"
    made = second["created"][0]
    got = asyncio.run(_read_order(aid, made["folder_id"]))
    assert len(got) == made["items"], f"membership doubled: {len(got)} vs {made['items']}"


def case_rebuild_retires_folders_the_plan_no_longer_makes() -> None:
    aid = _next_account()
    _plan_seed(aid)

    async def _old_generation():
        async with get_session() as s:
            s.add(VaultFolder(account_id=aid, name="AI-old lane name",
                              created_by="vault_ai_script"))
            await s.commit()
    asyncio.run(_old_generation())

    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    res = asyncio.run(vault_scripts.apply_ai_folders(aid, plan))

    assert [r["name"] for r in res["retired"]] == ["AI-old lane name"], res["retired"]
    live = asyncio.run(_count_folders(aid))
    assert live == res["folders"], f"stale folder survived: {live} vs {res['folders']}"


def case_retire_never_touches_operator_folders() -> None:
    aid = _next_account()
    _plan_seed(aid)

    async def _theirs():
        async with get_session() as s:
            s.add(VaultFolder(account_id=aid, name="My favourites",
                              created_by="operator"))
            s.add(VaultFolder(account_id=aid, name="AI-mine actually",
                              created_by="operator"))
            await s.commit()
    asyncio.run(_theirs())

    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    res = asyncio.run(vault_scripts.apply_ai_folders(aid, plan))

    assert res["retired"] == [], f"retired an operator folder: {res['retired']}"
    assert asyncio.run(_count_folders(aid)) == res["folders"] + 2


def case_apply_leaves_an_operators_ai_named_folder_alone() -> None:
    aid = _next_account()
    _plan_seed(aid)
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    clash = plan["folders"][0]["name"]

    async def _theirs():
        async with get_session() as s:
            folder = VaultFolder(account_id=aid, name=clash, created_by="operator")
            s.add(folder)
            await s.flush()
            for i, mid in enumerate((9001, 9002, 9003), start=1):
                s.add(VaultFolderItem(account_id=aid, folder_id=folder.id,
                                      media_id=mid, manual_order=i))
            await s.commit()
            return folder.id
    fid = asyncio.run(_theirs())

    res = asyncio.run(vault_scripts.apply_ai_folders(aid, plan))

    got = asyncio.run(_read_order(aid, fid))
    assert got == [(9001, 1), (9002, 2), (9003, 3)], f"operator folder wiped: {got}"
    made = res["created"][0]
    assert made["folder_id"] != fid and not made["reused"], made
    assert asyncio.run(_count_folders(aid)) == res["folders"] + 1


def _split_shoot_seed(aid: str, *, later_bigger: bool = False, later: float = 30240.0) -> None:
    rows = [
        (801, 0.0, _outfit(["black lace bra"], ["posing"], "sfw", "dressed")),
        (802, 0.1, _outfit(["black lace bra"], ["tease"], "suggestive")),
        (803, 0.2, _outfit(["black lace bra"], ["fingering"], "explicit", "fully_nude")),
        (804, later, _outfit(["black lace bra"], ["posing"], "sfw", "dressed")),
        (805, later + 0.1, _outfit(["black lace bra"], ["tease"], "suggestive")),
        (806, later + 0.2, _outfit(["black lace bra"], ["fingering"], "explicit",
                                   "fully_nude")),
    ]
    if later_bigger:
        rows.append((807, later + 0.3, _outfit(["black lace bra"], ["tease"],
                                               "suggestive")))
    asyncio.run(_seed(aid, rows))


_A_YEAR_ON = 365 * 24 * 60.0


def _scripts(plan: dict) -> dict[str, set[int]]:
    return {f["name"]: {int(i["media_id"]) for i in f["items"]}
            for f in plan["folders"] if f["source"] == "script"}


def case_two_shoots_with_one_name_keep_their_own_items() -> None:
    aid = _next_account()
    _split_shoot_seed(aid, later=_A_YEAR_ON)
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=2))
    names = [f["name"] for f in plan["folders"]]
    assert len(names) == len(set(names)), f"plan repeats a name: {names}"

    bare = plan["folders"][0]["name"].removesuffix(" 2")
    scripts = _scripts(plan)
    assert scripts == {bare: {801, 802, 803}, f"{bare} 2": {804, 805, 806}}, scripts

    first = asyncio.run(vault_scripts.apply_ai_folders(aid, plan))
    made = {c["name"]: c["folder_id"] for c in first["created"]}
    a, b = made[bare], made[f"{bare} 2"]
    assert a != b, "two shoots landed in one folder"
    assert {m for m, _ in asyncio.run(_read_order(aid, a))} == {801, 802, 803}
    assert {m for m, _ in asyncio.run(_read_order(aid, b))} == {804, 805, 806}

    second = asyncio.run(vault_scripts.apply_ai_folders(aid, plan))
    again = {c["name"]: c["folder_id"] for c in second["created"]}
    assert again == made, second["created"]
    assert second["new"] == 0 and second["retired"] == [], second


def case_same_name_suffix_follows_start_not_rank() -> None:
    aid = _next_account()
    _split_shoot_seed(aid, later_bigger=True, later=_A_YEAR_ON)
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=2))
    first = plan["folders"][0]
    assert 807 in {i["media_id"] for i in first["items"]}, "later shoot not ranked first"

    bare = first["name"].removesuffix(" 2")
    scripts = _scripts(plan)
    assert scripts[bare] == {801, 802, 803}, scripts
    assert scripts[f"{bare} 2"] == {804, 805, 806, 807}, scripts


def case_mirror_keeps_two_same_named_shoots_apart() -> None:
    aid = _next_account()
    _split_shoot_seed(aid, later=_A_YEAR_ON)
    fake = _FakeOF()
    res = asyncio.run(_apply_with_of(aid, fake, keep=2))
    assert res["of_failed"] == 0, res

    got = {c["name"]: set(fake.members.get(c["of_list_id"], []))
           for c in res["created"]}
    assert all(got.values()), f"an OF list was pushed empty: {got}"
    scripts = [c["name"] for c in res["created"] if c["source"] == "script"]
    bare = min(scripts, key=len)
    assert got[bare] == {801, 802, 803}, got
    assert got[f"{bare} 2"] == {804, 805, 806}, got


async def _count_folders(aid: str) -> int:
    async with get_session() as s:
        return len((await s.execute(
            select(VaultFolder).where(VaultFolder.account_id == aid,
                                      VaultFolder.deleted_at.is_(None))
        )).scalars().all())


def case_explicit_clips_get_a_lane() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1301, 0.0, {**_shot(["pussy"], "explicit", "fully_nude"),
                     **_flags(vulva="bare", breasts="bare", underwear=False),
                     "acts": ["toy_insertion", "masturbation_orgasm"]}, "video"),
        (1302, 0.1, {**_shot(["pussy"], "hardcore", "pulled_aside"),
                     **_flags(vulva="bare", breasts="covered",
                              over_breasts="black lace bra")}, "video"),
        (1303, 0.2, {**_shot(["body"], "suggestive", "lingerie_on"),
                     **_flags(vulva="covered", breasts="covered",
                              over_vulva="black lace thong",
                              over_breasts="black lace bra")}, "video"),
        (1304, 0.3, {**_shot(["pussy"], "explicit", "fully_nude"),
                     **_flags(vulva="bare", breasts="bare", underwear=False)}, "photo"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    clips = {r["media_id"] for r in lanes["clips"]["items"]}
    assert clips == {1301, 1302}, f"clips lane is explicit VIDEO only: {clips}"
    assert lanes["clips"]["name"].startswith("AI-"), lanes["clips"]["name"]


def case_no_paid_item_is_left_out_of_every_lane() -> None:
    aid = _next_account()
    covered_but_explicit = {
        **_shot(["pussy"], "explicit", "pulled_aside"),
        **_flags(vulva="covered", breasts="covered", anus="covered",
                 over_vulva="black leather skirt", over_breasts="black leather top"),
        "acts": ["posing", "fingering"],
    }
    asyncio.run(_seed(aid, [
        (1401, 0.0, covered_but_explicit, "photo"),
        (1402, 0.1, {**_shot(["breasts"], "sfw", "dressed"),
                     **_flags(over_breasts="wool jumper")}, "photo"),
    ]))
    lanes = asyncio.run(vault_scripts.collect_purpose_folders(aid))
    placed = {r["media_id"] for f in lanes for r in f["items"]}
    assert placed == {1401, 1402}, f"an item fell through every lane: {placed}"

    by_lane = {f["lane"]: {r["media_id"] for r in f["items"]} for f in lanes}
    assert by_lane["explicit_rest"] == {1401}, by_lane
    assert 1401 not in by_lane.get("covered_explicit", set()), \
        "something IS happening in it — it is not mass-safe"
    assert 1402 in by_lane["stories"] and 1402 not in by_lane["explicit_rest"]


def _clip(mid: int, at: float, acts: list[str], **people) -> tuple:
    return (mid, at, {**_shot(["pussy"], "explicit", "fully_nude"),
                      **_flags(vulva="bare", breasts="bare", underwear=False),
                      "acts": acts, **people}, "video")


async def _apply_folders(aid: str, *, solo: bool) -> dict[str, int]:
    plan = await vault_scripts.plan_ai_folders(aid, keep=0, solo=solo)
    await vault_scripts.apply_ai_folders(aid, plan)
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultFolder.name, VaultFolder.id).where(
                VaultFolder.account_id == aid,
                VaultFolder.deleted_at.is_(None))
        )).all()
    return {str(n): int(i) for n, i in rows}


async def _folder_members(aid: str, folder_id: int) -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultFolderItem.media_id).where(
                VaultFolderItem.account_id == aid,
                VaultFolderItem.folder_id == folder_id))).all()
    return {int(m) for m, in rows}


def case_solo_cut_keeps_only_her() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        _clip(1501, 0.0, ["toy_insertion"], people_count=1, partner_visible=False),
        _clip(1502, 0.1, ["sex_doggy"], people_count=2, partner_visible=True),
        _clip(1503, 0.2, ["masturbation_orgasm"]),
        _clip(1504, 0.3, ["rubbing_clit"], people_count=1),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid, solo=True))}

    assert {r["media_id"] for r in lanes["clips"]["items"]} == {1501, 1502, 1503, 1504}, \
        "the solo cut must not change the lane it is cut from"
    solo = lanes["clips_solo"]
    assert {r["media_id"] for r in solo["items"]} == {1501, 1504}, \
        f"a partner clip or an unasked one got into a solo folder: {solo['items']}"
    assert solo["name"] == f"{lanes['clips']['name']}-solo", solo["name"]
    assert solo["name"].startswith("AI-") and solo["name"].count("AI-") == 1, solo["name"]
    assert solo["solo"] is True and solo["solo_of"] == 4, solo
    assert [r["manual_order"] for r in solo["items"]] == [1, 2], solo["items"]


def case_solo_is_off_unless_asked() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        _clip(1511, 0.0, ["toy_insertion"], people_count=1, partner_visible=False),
    ]))
    lanes = asyncio.run(vault_scripts.collect_purpose_folders(aid))
    assert all(not f["lane"].endswith("_solo") for f in lanes), \
        [f["lane"] for f in lanes]
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=0))
    assert plan["summary"]["solo_cuts"] == 0, plan["summary"]
    assert plan["solo_coverage"] is None, plan["solo_coverage"]
    assert all(f["solo"] is False and f["solo_of"] is None for f in plan["folders"]), \
        plan["folders"]


def case_a_partner_act_outranks_the_count() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        _clip(1521, 0.0, ["blowjob"], people_count=1, partner_visible=False),
        _clip(1522, 0.1, ["posing"], people_count=1, partner_visible=False,
              primary_folder="sex_with_partner"),
        _clip(1523, 0.2, ["posing"], people_count=1, partner_visible=False,
              penetration="penis"),
        _clip(1524, 0.3, ["toy_insertion"], people_count=1, partner_visible=False,
              penetration="toy"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid, solo=True))}
    got = {r["media_id"] for r in lanes["clips_solo"]["items"]}
    assert got == {1524}, f"one signal saying 'someone else' has to be enough: {got}"


def case_an_unasked_item_is_never_solo() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        _clip(1531, 0.0, ["toy_insertion"]),
        _clip(1532, 0.1, ["toy_insertion"], partner_visible=False),
    ]))
    assert not vault_scripts.is_solo({"acts": ["posing"]}), \
        "no evidence read as solo — the whole vault would be a solo folder"
    assert vault_scripts.is_solo({"partner_visible": False}), "asked, and answered"
    jev = {**_jev_photo(), "tags": {"people_count": "two_or_more"}}
    assert not vault_scripts.is_solo({"partner_visible": False, "_jev": jev}), "Jev's head count is a vote"

    cov = asyncio.run(vault_scripts.solo_coverage(aid))
    assert cov == {"described": 2, "known": 1, "unknown": 1, "solo": 1,
                   "ready": False}, cov
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=0, solo=True))
    assert plan["solo_coverage"] == cov, plan["solo_coverage"]
    assert plan["summary"]["solo_cuts"] == 1, plan["summary"]
    solo = [f for f in plan["folders"] if f["solo"]]
    assert {r["media_id"] for r in solo[0]["items"]} == {1532}, solo[0]["items"]


def case_solo_folders_are_created_and_retired_like_any_other() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        _clip(1541, 0.0, ["toy_insertion"], people_count=1, partner_visible=False),
        _clip(1542, 0.1, ["sex_doggy"], people_count=2, partner_visible=True),
    ]))

    with_solo = asyncio.run(_apply_folders(aid, solo=True))
    solo_names = [n for n in with_solo if n.endswith("-solo")]
    assert solo_names, with_solo
    assert asyncio.run(_folder_members(aid, with_solo[solo_names[0]])) == {1541}, \
        solo_names

    without = asyncio.run(_apply_folders(aid, solo=False))
    assert not [n for n in without if n.endswith("-solo")], without
    assert [n for n in without if not n.endswith("-solo")], \
        "retiring the solo cut must not take the lanes with it"


def case_disputed_items_read_the_least_harmful_way() -> None:
    aid = _next_account()
    agreed_mass = _shot(["face"], "suggestive", "lingerie_on")
    rows = {
        2001: {**_shot(["breasts"], "sfw", "pulled_down"),
               **_flags(breasts="bare", vulva="covered", over_vulva="denim shorts")},
        2002: {**_shot(["pussy"], "suggestive", "dressed"),
               **_flags(vulva="bare", breasts="covered", over_breasts="white tank top")},
        2003: {**_shot(["breasts"], "explicit", "fully_nude"),
               **_flags(breasts="bare", vulva="covered", over_vulva="black lace thong")},
        2004: {**_shot(["breasts"], "explicit", "fully_nude"), **_dressed()},
        2005: {**_shot(["face"], "suggestive", "lingerie_on"),
               **_flags(breasts="covered", over_breasts="black top", underwear=False)},
        2006: {**_fields("pulled_down", ["rubbing_clit"], "fingers", "explicit"),
               "clothing_items": ["white bra"], "beats": ["fingers inside her"],
               **_flags(breasts="covered", over_breasts="white bra")},
        2007: {**agreed_mass, **_dressed(), "beats": ["turns to camera"]},
    }
    asyncio.run(_seed(aid, [(m, i * 0.1, f, "photo") for i, (m, f) in enumerate(rows.items())]))
    lanes = {f["lane"]: {r["media_id"] for r in f["items"]} for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    free = lanes.get("stories", set()) | lanes.get("mass", set()) \
        | lanes.get("covered_explicit", set())
    assert free & set(rows) == {2007}, f"a disputed item is in a free lane: {free}"
    assert lanes.get("tease_10", set()) & set(rows) == {2001, 2003}, lanes.get("tease_10")
    assert lanes.get("tease_50", set()) & set(rows) == {2002}, lanes.get("tease_50")
    assert {2004, 2006} <= lanes["explicit_rest"], lanes["explicit_rest"]
    every = set().union(*lanes.values())
    assert set(rows) - every == {2005}, f"lane misses: {set(rows) - every}"
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid))
    assert plan["settled_unlaned"] == [2005], plan["settled_unlaned"]
    assert plan["summary"]["settled_unlaned"] == 1, plan["summary"]
    planned = {r["media_id"] for f in plan["folders"] for r in f["items"]}
    assert set(rows) == planned | set(plan["settled_unlaned"]), "an item was dropped"

    prices = {m: vault_scripts.shelf_price(f, "photo") for m, f in rows.items()}
    assert prices == {2001: 10, 2002: 50, 2003: 10, 2004: 0, 2005: 0, 2006: 0, 2007: 0}, prices

    why = {m: vault_scripts.send_order_reason(f) for m, f in rows.items()}
    assert why[2002]["clothing_state"] == "dressed" and why[2002]["tier"] == "explicit"
    assert why[2003]["clothing_state"] == "pulled_down"
    assert "nothing left" not in why[2003]["reveal"]
    assert why[2005]["clothing_state"] == "dressed"
    assert why[2006]["acts"] == [] and why[2006]["payoff_acts"] == [] \
        and why[2006]["closes"] is False, why[2006]
    assert why[2006]["beats"] == [] and why[2007]["beats"] == ["turns to camera"]
    assert rows[2003]["clothing_state"] == "fully_nude"


def case_disputed_item_never_opens_a_script() -> None:
    aid = _next_account()
    bra = ["pink lace bra"]
    asyncio.run(_seed(aid, [
        (2101, 0.0, _outfit(bra, ["posing"], "sfw", "dressed"), "photo"),
        (2102, 0.1, _outfit(bra, ["tease"], "suggestive"), "photo"),
        (2103, 0.2, {**_outfit(bra, ["tease"], "suggestive"),
                     **_flags(breasts="covered", over_breasts="pink top",
                              underwear=False)}, "photo"),
        (2104, 0.3, {**_outfit(bra, ["posing"], "explicit", "fully_nude"),
                     **_flags(breasts="bare", vulva="covered",
                              over_vulva="pink lace thong")}, "photo"),
        (2105, 0.4, _outfit(bra, ["fingering"], "explicit", "fully_nude"), "photo"),
    ]))
    scripts = asyncio.run(vault_scripts.collect_outfit_scripts(aid))
    assert len(scripts) == 1, scripts
    ids = [r["media_id"] for r in scripts[0]["items"]]
    assert 2103 not in ids, f"a disputed free-tier still is in a script: {ids}"
    assert set(ids) == {2101, 2102, 2105} and ids[0] == 2101, ids



async def _hash(aid: str, packed: dict[int, str]) -> None:
    import vault_dupes
    async with get_session() as s:
        for mid, h in packed.items():
            row = (await s.execute(select(VaultItem).where(
                VaultItem.account_id == aid, VaultItem.media_id == mid))).scalar_one()
            row.content_hash, row.content_hash_kind = h, vault_dupes.HASH_KIND
        await s.commit()


def case_a_duplicate_set_is_one_item_in_every_folder() -> None:
    import vault_dupes
    aid = _next_account()
    _plan_seed(aid)
    plan_rows = asyncio.run(vault_scripts._load_rows(aid))
    fields = {r["media_id"]: r["fields"] for r in plan_rows}
    asyncio.run(_seed_more(aid, [(2006, 5.0, fields[2003], "photo"),
                                 (2007, 5.1, fields[2005], "video")]))

    def _together(plan: dict, a: int, b: int) -> list[str]:
        return [f["name"] for f in plan["folders"]
                if {a, b} <= {r["media_id"] for r in f["items"]}]

    before = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    assert _together(before, 2003, 2006), "control: the copy should be foldered unhashed"

    asyncio.run(_hash(aid, {2003: vault_dupes.pack_hash("a" * 32, 0, 0),
                            2006: vault_dupes.pack_hash("a" * 32, 0, 0),
                            2005: vault_dupes.pack_hash("b" * 32, 1, 1),
                            2007: vault_dupes.pack_hash("b" * 32, 1, 1)}))
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    placed = {r["media_id"] for f in plan["folders"] for r in f["items"]}
    assert not _together(plan, 2003, 2006) and not _together(plan, 2005, 2007), plan["folders"]
    assert {2003, 2005} <= placed and not ({2006, 2007} & placed), placed
    assert plan["dupes_collapsed"] == [2006, 2007], plan["dupes_collapsed"]
    assert plan["summary"]["dupes_collapsed"] == 2


def case_collapse_keeps_the_original_unless_it_has_no_reading() -> None:
    d = "described"
    rows = [{"media_id": 1, "fields": {}}, {"media_id": 2, "fields": {"x": 1}, "describe_status": d},
            {"media_id": 3, "fields": {"x": 1}, "describe_status": d},
            {"media_id": 4, "fields": {"x": 1}, "describe_status": d},
            {"media_id": 5, "fields": {"x": 1}, "describe_status": d},
            {"media_id": 6, "fields": {"x": 1}, "describe_status": "failed"}]
    for name, groups, want_kept, want_drop in (
        ("original kept", [[2, 3]], [1, 2, 4, 5, 6], [3]),
        ("failed copy is passed over for the described one", [[1, 6, 4]], [2, 3, 4, 5], [1, 6]),
        ("unread original gives way to the first read copy", [[1, 2, 3]], [2, 4, 5, 6], [1, 3]),
        ("a set with one live member is no set", [[4, 99]], [1, 2, 3, 4, 5, 6], []),
        ("two sets", [[2, 3], [4, 5]], [1, 2, 4, 6], [3, 5]),
    ):
        kept, dropped = vault_scripts.collapse_dupes(rows, groups)
        assert [r["media_id"] for r in kept] == want_kept and dropped == want_drop, \
            (name, [r["media_id"] for r in kept], dropped)


async def _seed_more(aid: str, items: list[tuple]) -> None:
    async with get_session() as s:
        for mid, minutes, fields, kind in items:
            s.add(VaultItem(
                account_id=aid, media_id=mid, kind=kind,
                created_at=datetime(2026, 7, 1) + timedelta(minutes=minutes),
                tags="[]", describe_status="described", ai_fields_json=json.dumps(fields)))
        await s.commit()


def case_a_colourless_set_keys_on_garment_and_setting() -> None:
    key = vault_scripts.outfit_key
    assert key({"clothing_items": ["bra", "thong"], "setting": "bedroom"}) == "lingerie_set bedroom"
    assert key({"clothing_items": ["bra"], "setting": "Shower "}) == "lingerie_set shower"
    assert key({"clothing_items": ["bra"], "setting": "other"}) == "", "'other' names no place"
    assert key({"clothing_items": ["bra"]}) == "", "garment alone pools unrelated sets"
    assert key({"clothing_items": ["earrings"], "setting": "bedroom"}) == "", "room alone"
    assert key({"clothing_items": ["red bra"], "setting": "bedroom"}) == "red lingerie_set", \
        "a colour still wins"

    aid = _next_account()
    bra = {"clothing_items": ["bra", "thong"], "setting": "bedroom"}
    asyncio.run(_seed(aid, [
        (2201, 0.0, {**_outfit([], ["posing"], "sfw", "dressed"), **bra}, "photo"),
        (2202, 0.1, {**_outfit([], ["tease"], "suggestive"), **bra}, "photo"),
        (2203, 0.2, {**_outfit([], ["fingering"], "explicit", "fully_nude"), **bra}, "video"),
    ]))
    scripts = asyncio.run(vault_scripts.collect_outfit_scripts(aid))
    assert [s["name"] for s in scripts] == ["AI-lingerie · bedroom · Jul 1"], \
        "the room is named once, not twice"
    assert [r["media_id"] for r in scripts[0]["items"]] == [2201, 2202, 2203]


def case_keep_zero_builds_lanes_only() -> None:
    from fastapi import HTTPException

    import vault_ai_api
    aid = _next_account()
    _split_shoot_seed(aid)
    res = asyncio.run(_apply_with_of(aid, _FakeOF(), keep=0, mirror=False))
    assert not [c for c in res["created"] if c["source"] == "script"], res["created"]
    assert res["summary"]["scripts"] == 0, res["summary"]

    res = asyncio.run(vault_ai_api.apply_folder_plan({"account_id": aid, "confirm": True}))
    assert res["summary"]["scripts"] == 2, "absent keep must stay 2"
    try:
        asyncio.run(vault_ai_api.apply_folder_plan(
            {"account_id": aid, "confirm": True, "keep": "lots"}))
    except HTTPException as e:
        assert e.status_code == 400 and e.detail == {"error": "bad_keep"}, e.detail
    else:
        raise AssertionError("keep='lots' was accepted")


def case_preview_counts_what_confirm_will_create_keep_and_retire() -> None:
    aid = _next_account()
    _plan_seed(aid)
    first = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    assert first["changes"] == {"create": len(first["folders"]), "keep": 0, "retire": 0,
                                "retire_on_of": 0, "retired": []}, first["changes"]
    assert {f["change"] for f in first["folders"]} == {"new"}
    asyncio.run(vault_scripts.apply_ai_folders(aid, first))

    async def _old_generation():
        async with get_session() as s:
            s.add(VaultFolder(account_id=aid, name="AI-old on OF", of_list_id=777,
                              created_by="vault_ai_script"))
            s.add(VaultFolder(account_id=aid, name="AI-old local",
                              created_by="vault_ai_script"))
            s.add(VaultFolder(account_id=aid, name="AI-mine", created_by="operator"))
            await s.commit()
    asyncio.run(_old_generation())

    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=0))
    ch = plan["changes"]
    lanes = len(plan["folders"])
    assert (ch["create"], ch["keep"], ch["retire"], ch["retire_on_of"]) == (0, lanes, 3, 1), ch
    assert sorted(r["name"] for r in ch["retired"]) == sorted(
        ["AI-old on OF", "AI-old local", *[f["name"] for f in first["folders"]
                                          if f["source"] == "script"]]), ch["retired"]
    assert {f["change"] for f in plan["folders"]} == {"keep"}

    res = asyncio.run(vault_scripts.apply_ai_folders(aid, plan))
    assert (res["new"], res["reused"]) == (ch["create"], ch["keep"]), res
    assert res["retired"] == ch["retired"], (res["retired"], ch["retired"])



def _jev_photo(setting: str = "", **extra) -> dict:
    import vault_jev_rules
    return {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": "free", "state": {},
            "kind": "photo", "tags": {"setting": setting} if setting else {}, **extra}


def _bra(tier: str, acts: list[str], clothing: str = "lingerie_on", *, room: str = "",
         jev_room: str = "") -> dict:
    out = _outfit(["black lace bra"], acts, tier, clothing)
    if room:
        out["setting"] = room
    if jev_room:
        out["_jev"] = _jev_photo(jev_room)
    return out


def case_one_upload_second_splits_by_room() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (3001, 0.0, _bra("sfw", ["posing"], "dressed", room="bedroom"), "photo"),
        (3002, 0.0, _bra("suggestive", ["tease"], room="bedroom"), "photo"),
        (3003, 0.0, _bra("explicit", ["fingering"], "fully_nude", room="bedroom"), "video"),
        (3004, 0.0, _bra("suggestive", ["posing"], room="bedroom"), "photo"),
        (3011, 30.0, _bra("sfw", ["posing"], "dressed", room="bedroom", jev_room="bathroom"), "photo"),
        (3012, 30.0, _bra("suggestive", ["tease"], jev_room="bathroom"), "photo"),
        (3013, 31.0, _bra("explicit", ["fingering"], "fully_nude", room="other"), "video"),
        (3021, 0.0, _bra("suggestive", ["tease"]), "photo"),
        (3031, 200.0, _bra("explicit", ["fingering"], "fully_nude", room="kitchen"), "video"),
    ]))
    scripts = {s["name"]: s for s in asyncio.run(vault_scripts.collect_outfit_scripts(aid))}
    assert set(scripts) == {"AI-black lingerie · bedroom · Jul 1",
                            "AI-black lingerie · bathroom · Jul 1"}, list(scripts)
    ids = {n: {r["media_id"] for r in s["items"]} for n, s in scripts.items()}
    assert ids["AI-black lingerie · bedroom · Jul 1"] == {3001, 3002, 3003, 3004, 3021}, ids
    assert ids["AI-black lingerie · bathroom · Jul 1"] == {3011, 3012, 3013}, ids
    assert scripts["AI-black lingerie · bathroom · Jul 1"]["room"] == "bathroom"

    rows = [{"media_id": m, "created_at": datetime(2026, 7, 1), "fields": {}} for m in (1, 2)]
    assert vault_scripts.split_by_room(rows) == [("", rows)], "no room anywhere: one part"


def _ladder_seed(aid: str, base: int = 3100) -> None:
    rows = []
    for i in range(8):
        rows.append((base + i, 0.0, _bra("sfw", ["posing"], "dressed" if i < 6 else "lingerie_on",
                                         room="bedroom"), "photo"))
    for i in range(12):
        rows.append((base + 20 + i, 0.0, _bra("suggestive", ["tease"], room="bedroom"),
                     "photo" if i % 3 else "video"))
    for i in range(10):
        rows.append((base + 40 + i, 0.0, _bra("explicit", ["fingering"], "fully_nude", room="bedroom"),
                     "video" if i % 2 else "photo"))
    asyncio.run(_seed(aid, rows))


def case_a_big_shoot_is_capped_to_a_sendable_ladder() -> None:
    aid = _next_account()
    _ladder_seed(aid)
    (s,) = asyncio.run(vault_scripts.collect_outfit_scripts(aid))
    cap = (vault_scripts.SCRIPT_OPENERS, vault_scripts.SCRIPT_MIDDLE, vault_scripts.SCRIPT_CLOSERS)
    assert cap == (3, 4, 3), cap
    assert s["bands"] == {"opener": 3, "middle": 4, "closer": 3}, s["bands"]
    assert s["size"] == 10 and len(s["overflow"]) == 20 and s["capped_from"] == 30, s["size"]
    items = s["items"]
    closers = [r for r in items if r["why"]["closes"]]
    assert all(r["kind"] == "video" for r in closers), "closers prefer clips"
    openers = [r for r in items if r["why"]["rung"] == 0]
    assert len({r["why"]["clothing_state"] for r in openers}) == 2, "openers are varied"
    middle = [r for r in items if r["why"]["rung"] == 1]
    assert {r["kind"] for r in middle} == {"photo", "video"}, "middle is varied"
    keys = [vault_scripts.send_sort_key(r["fields"], media_id=r["media_id"]) for r in items]
    assert keys == sorted(keys), "the cap keeps send order"
    assert [r["manual_order"] for r in items] == list(range(1, 11))
    assert "capped from 30" in s["health"], s["health"]

    small = [{"media_id": i, "kind": "photo", "why": {"rung": i % 2, "closes": False,
              "clothing_state": "", "payoff_acts": []}} for i in range(5)]
    assert vault_scripts.cap_ladder(small) == (small, []), "a small script is not cut"


def case_burst_frames_collapse_inside_a_rung() -> None:
    import vault_dupes
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (3201, 0.0, _bra("sfw", ["posing"], "dressed"), "photo"),
        (3202, 0.0, _bra("suggestive", ["tease"]), "photo"),
        (3203, 0.0, {**_bra("suggestive", ["tease"]), "_jev": _jev_photo()}, "photo"),
        (3204, 0.0, _bra("suggestive", ["tease"]), "photo"),
        (3205, 0.0, _bra("explicit", ["fingering"], "fully_nude"), "photo"),
        (3206, 0.0, _bra("suggestive", ["tease"]), "photo"),
    ]))
    far = (1 << 64) - 1
    asyncio.run(_hash(aid, {3201: vault_dupes.pack_hash("1" * 32, far, far),
                            3202: vault_dupes.pack_hash("2" * 32, 0b1111, 0b1111),
                            3203: vault_dupes.pack_hash("3" * 32, 0, 0),
                            3204: vault_dupes.pack_hash("4" * 32, 0b11110000, 0),
                            3205: vault_dupes.pack_hash("5" * 32, 0b111 << 40, 0b111 << 40)}))
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    assert plan["dupes_collapsed"] == [], "control: none of these is a re-upload"
    (s,) = [f for f in plan["folders"] if f["source"] == "script"]
    got = [r["media_id"] for r in s["items"]]
    assert 3203 in got and 3202 not in got and 3204 not in got, got
    assert 3205 in got and 3206 in got, got
    assert "2 near-duplicates dropped" in s["health"], s["health"]


def case_reveal_breaks_a_tie_inside_a_rung() -> None:
    base = _bra("explicit", ["posing"], "fully_nude")
    covered = {**base, **_flags(breasts="covered", vulva="covered", over_breasts="hand",
                                over_vulva="hand")}
    breasts = {**base, **_flags(breasts="bare", vulva="covered", over_vulva="hand")}
    both = {**base, **_flags(breasts="bare", vulva="bare")}
    jev_breasts = {**base, "_jev": _jev_photo(breasts_bare="y")}
    key = vault_scripts.send_sort_key
    order = sorted([(both, 1), (breasts, 2), (covered, 3)], key=lambda p: key(p[0], media_id=p[1]))
    assert [m for _, m in order] == [3, 2, 1], order
    assert key(jev_breasts, media_id=1) > key(base, media_id=2), "Jev's bare answer counts"
    assert key(base, media_id=1) < key(base, media_id=2), "media id is the last tiebreak"
    clash = {**covered, "_jev": _jev_photo(breasts_bare="y")}
    assert vault_scripts.reveal_strength(clash) == 0, "flags pass outranks Jev"
    assert vault_scripts.reveal_strength(jev_breasts) == 1, "Jev fills an unflagged region"


def case_explicit_needs_her_pussy_on_show_or_an_act() -> None:
    butt = {**_bra("explicit", ["posing"], "fully_nude"),
            **_flags(vulva="covered", breasts="bare", over_vulva="thong")}
    bare = {**_bra("explicit", ["posing"], "fully_nude"), **_flags(vulva="bare")}
    act = {**_bra("hardcore", ["fingering"], "fully_nude"), **_flags(vulva="covered")}
    jev_only = {**_bra("explicit", ["posing"], "fully_nude"),
                "_jev": _jev_photo(crotch_bare="y")}
    jev_overruled = {**butt, "_jev": _jev_photo(crotch_bare="y")}
    e = vault_scripts.earns_paid_rung
    assert not e(butt) and e(bare) and e(act) and e(jev_only), "rule"
    assert not e(jev_overruled), "flags answer beats Jev"
    why = vault_scripts._with_script_why({"fields": butt, "media_id": 1})["why"]
    assert why["tier"] == "suggestive" and why["labelled"] == "explicit", why


def _big_shoot(aid: str, base: int, *, videos: int) -> list[tuple]:
    rows = []
    for i in range(12):
        tier, acts, clothing, extra = (
            ("suggestive", ["tease"], "lingerie_on", {}) if i < 4 else
            ("explicit", ["posing"], "fully_nude", _flags(vulva="bare")) if i < 8 else
            ("explicit", ["fingering"], "fully_nude", _flags(vulva="bare")))
        kind = "video" if i >= 8 and i - 8 < videos else "photo"
        rows.append((base + i, i * 0.01, {**_bra(tier, acts, clothing), **extra}, kind))
    return rows


def case_a_script_is_ten_pieces_with_two_clips() -> None:
    for videos, want in ((2, 1), (1, 0)):
        aid = _next_account()
        asyncio.run(_seed(aid, _big_shoot(aid, 3200, videos=videos)))
        got = asyncio.run(vault_scripts.collect_outfit_scripts(aid, min_items=10, min_videos=2))
        assert len(got) == want, (videos, got)
        if got:
            sc = got[0]
            assert sc["size"] == 10 and sc["kinds"].get("video", 0) >= 2, sc
    aid = _next_account()
    full = _big_shoot(aid, 3300, videos=4)
    nine = full[:7] + full[8:10]
    asyncio.run(_seed(aid, nine))
    assert asyncio.run(vault_scripts.collect_outfit_scripts(aid, min_items=10, min_videos=2)) == []


def case_a_thin_band_is_filled_to_ten() -> None:
    def it(mid, kind, rung, closes):
        return {"media_id": mid, "kind": kind, "score": 0,
                "why": {"rung": rung, "closes": closes, "clothing_state": "nude",
                        "payoff_acts": ["fingering"] if closes else []}}
    items = ([it(0, "photo", 0, False)] + [it(10 + i, "photo", 1, False) for i in range(8)]
             + [it(30 + i, "video", 2, True) for i in range(3)])
    kept, left = vault_scripts.cap_ladder(items, min_videos=0)
    assert len(kept) == vault_scripts.SCRIPT_SIZE == 10 and len(left) == 2, (kept, left)


def case_too_few_clips_swaps_a_photo_for_a_left_out_clip() -> None:
    def it(mid, kind, rung, closes):
        return {"media_id": mid, "kind": kind, "score": 0,
                "why": {"rung": rung, "closes": closes, "clothing_state": "nude",
                        "payoff_acts": ["fingering"] if closes else []}}
    items = ([it(i, "photo", 0, False) for i in range(3)]
             + [it(10 + i, "photo", 1, False) for i in range(4)]
             + [it(20, "video", 1, False), it(21, "video", 1, False)]
             + [it(30 + i, "photo", 2, True) for i in range(3)])
    one, _ = vault_scripts.cap_ladder(items, min_videos=0)
    assert sum(r["kind"] == "video" for r in one) == 1, "fixture: cap keeps one clip"
    kept, _ = vault_scripts.cap_ladder(items, min_videos=2)
    assert len(kept) == 10 and {20, 21} <= {r["media_id"] for r in kept}, kept
    assert all(r["media_id"] in {r["media_id"] for r in kept} for r in items[-3:]), "closers kept"


def case_a_room_too_small_falls_back_to_the_whole_shoot() -> None:
    aid = _next_account()
    rows = _big_shoot(aid, 3400, videos=2)
    rows = [(m, t, {**f, "setting": "bedroom" if i % 2 else "bathroom"}, k)
            for i, (m, t, f, k) in enumerate(rows)]
    asyncio.run(_seed(aid, rows))
    [sc] = asyncio.run(vault_scripts.collect_outfit_scripts(aid, min_items=10, min_videos=2))
    assert sc["room"] == "" and sc["size"] == 10, sc


def case_unrated_items_stay_in_their_script() -> None:
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (3101, 0.0, _bra("sfw", ["posing"], "dressed")),
        (3102, 0.1, _bra("suggestive", ["tease"])),
        (3103, 0.2, _bra("explicit", ["fingering"], "fully_nude")),
        (3104, 0.3, _bra("", ["posing"])),
    ]))
    [sc] = asyncio.run(vault_scripts.collect_outfit_scripts(aid))
    ids = [r["media_id"] for r in sc["items"]]
    assert ids == [3101, 3102, 3103, 3104], ids
    assert sc["size"] == 3 and sc["unplaced"] == 1, sc
    assert None not in sc["rungs"], sc["rungs"]
    assert "1 unrated at end" in sc["health"], sc["health"]


def case_a_skipped_rung_ranks_below_a_full_ladder() -> None:
    def shoot(name, rungs, bands, closes=1):
        return {"name": name, "closes_on_own": closes, "rungs": rungs,
                "bands": dict(zip(("opener", "middle", "closer"), bands)),
                "tiers": {"explicit": 2}, "mixed": True, "size": 9}
    got = sorted([
        shoot("skip", [1, 3], (1, 1, 1)),
        shoot("dead", [0, 1, 2, 3], (1, 1, 0), closes=0),
        shoot("two", [1, 2], (1, 1, 1)),
        shoot("full", [1, 2, 3], (1, 1, 1)),
        shoot("no-middle", [1, 2, 3], (1, 0, 1)),
    ], key=vault_scripts.shoot_rank_key)
    assert [s["name"] for s in got] == ["full", "two", "skip", "no-middle", "dead"], \
        [s["name"] for s in got]


def case_a_script_with_no_closer_borrows_one() -> None:
    aid = _next_account()
    _ladder_seed(aid)
    asyncio.run(_seed_more(aid, [
        (3301, 60.0, _bra("sfw", ["posing"], "dressed", room="bathroom"), "photo"),
        (3302, 60.0, _bra("suggestive", ["tease"], room="bathroom"), "photo"),
        (3303, 60.0, _bra("suggestive", ["posing"], room="bathroom"), "video"),
        (3304, 60.0, {**_outfit(["red silk robe"], ["fingering"], "explicit", "fully_nude"),
                      "setting": "bathroom"}, "video"),
    ]))
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=10))
    scripts = {f["room"]: f for f in plan["folders"] if f["source"] == "script"}
    bath, bed = scripts["bathroom"], scripts["bedroom"]
    last = bath["items"][-1]
    assert last.get("borrowed") is True and last["closes"] and last["kind"] == "video", last
    assert last["media_id"] in range(3140, 3150), "same colour first"
    assert last["media_id"] not in {r["media_id"] for r in bed["items"]}
    assert sum(1 for r in bath["items"] if r.get("borrowed")) == 1
    assert [r["manual_order"] for r in bath["items"]] == list(range(1, len(bath["items"]) + 1))
    assert bath["closes_on_own"] == 1 and bath["health"][0] == "borrowed closer", bath["health"]
    assert not any(r.get("borrowed") for r in bed["items"])

    lone = _next_account()
    asyncio.run(_seed(lone, [
        (3401, 0.0, _bra("sfw", ["posing"], "dressed"), "photo"),
        (3402, 0.0, _bra("suggestive", ["tease"]), "photo"),
        (3403, 0.0, _bra("suggestive", ["posing"]), "photo"),
    ]))
    (s,) = [f for f in asyncio.run(vault_scripts.plan_ai_folders(lone, keep=1))["folders"]
            if f["source"] == "script"]
    assert s["health"][0] == "no closer" and not any(r.get("borrowed") for r in s["items"]), s


def case_a_borrowed_closer_keeps_the_cap_and_skips_pruned_frames() -> None:
    aid = _next_account()
    rows = [(3501 + i, 0.0, _bra("sfw", ["posing"], "dressed", room="bedroom"), "photo") for i in range(3)]
    rows += [(3511 + i, 0.0, _bra("suggestive", ["tease"], room="bedroom"), "photo") for i in range(9)]
    rows += [(3591, 5.0, _bra("explicit", ["fingering"], "fully_nude", room="kitchen"), "photo"),
             (3592, 5.0, _bra("explicit", ["fingering"], "fully_nude", room="kitchen"), "photo")]
    asyncio.run(_seed(aid, rows))
    pool, _ = asyncio.run(vault_scripts._grouping_rows(aid))
    (s,) = asyncio.run(vault_scripts.collect_outfit_scripts(aid, rows=pool, prints={}))
    assert s["size"] == vault_scripts.SCRIPT_SIZE and not s["closes_on_own"], s["size"]
    s["near_dupes"] = [*s["near_dupes"], 3591]
    vault_scripts.borrow_closers([s], pool)
    assert s["borrowed"] == 3592, s["borrowed"]
    ladder = [r for r in s["items"] if r["why"]["rung"] is not None]
    assert len(ladder) == s["size"] == vault_scripts.SCRIPT_SIZE, (len(ladder), s["size"])
    assert ladder[-1]["media_id"] == 3592 and s["closes_on_own"] == 1
    assert len(s["overflow"]) == 3, s["overflow"]


def case_script_names_and_health() -> None:
    name = vault_scripts.script_name
    assert name("black lingerie_set", "bedroom", datetime(2026, 11, 3)) == \
        "AI-black lingerie · bedroom · Nov 3"
    assert name("black lingerie_set", "living_room", datetime(2026, 11, 3)) == \
        "AI-black lingerie · living room · Nov 3"
    assert name("black lingerie_set", "", None) == "AI-black lingerie"
    assert len(name("x" * 300, "bedroom", datetime(2026, 1, 1))) == vault_scripts._FOLDER_NAME_MAX

    health = vault_scripts.script_health
    def s(**kw):
        return {"closes_on_own": 1, "kinds": {"photo": 1, "video": 1}, "rungs": [0, 1, 2], **kw}
    for want, shoot in (
        ([], s()),
        (["no closer"], s(closes_on_own=0)),
        (["borrowed closer"], s(borrowed=9)),
        (["photos only", "suggestive → explicit"], s(kinds={"photo": 4}, rungs=[1, 2])),
        (["clips only", "suggestive, hardcore"], s(kinds={"video": 4}, rungs=[1, 3])),
        (["capped from 50", "1 near-duplicate dropped"], s(capped_from=50, near_dupes=[7])),
    ):
        assert health(shoot) == want, (want, health(shoot))


def case_renamed_scripts_reuse_on_rerun_and_retire_the_old_names() -> None:
    aid = _next_account()
    _plan_seed(aid)

    async def _old_name():
        async with get_session() as s:
            s.add(VaultFolder(account_id=aid, name="AI-pink lingerie",
                              created_by="vault_ai_script"))
            await s.commit()
    asyncio.run(_old_name())

    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    (script,) = [f for f in plan["folders"] if f["source"] == "script"]
    assert script["name"] == "AI-pink lingerie · Jul 1", script["name"]
    first = asyncio.run(vault_scripts.apply_ai_folders(aid, plan))
    assert [r["name"] for r in first["retired"]] == ["AI-pink lingerie"], first["retired"]

    again = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    assert all(f["change"] == "keep" for f in again["folders"]), again["changes"]
    second = asyncio.run(vault_scripts.apply_ai_folders(aid, again))
    assert second["new"] == 0 and second["retired"] == [], second


_harness.run(
    case_one_upload_second_splits_by_room,
    case_a_big_shoot_is_capped_to_a_sendable_ladder,
    case_burst_frames_collapse_inside_a_rung,
    case_reveal_breaks_a_tie_inside_a_rung,
    case_unrated_items_stay_in_their_script,
    case_explicit_needs_her_pussy_on_show_or_an_act,
    case_a_script_is_ten_pieces_with_two_clips,
    case_too_few_clips_swaps_a_photo_for_a_left_out_clip,
    case_a_thin_band_is_filled_to_ten,
    case_a_room_too_small_falls_back_to_the_whole_shoot,
    case_a_skipped_rung_ranks_below_a_full_ladder,
    case_a_script_with_no_closer_borrows_one,
    case_a_borrowed_closer_keeps_the_cap_and_skips_pruned_frames,
    case_script_names_and_health,
    case_renamed_scripts_reuse_on_rerun_and_retire_the_old_names,
    case_a_duplicate_set_is_one_item_in_every_folder,
    case_collapse_keeps_the_original_unless_it_has_no_reading,
    case_a_colourless_set_keys_on_garment_and_setting,
    case_keep_zero_builds_lanes_only,
    case_preview_counts_what_confirm_will_create_keep_and_retire,
    case_disputed_items_read_the_least_harmful_way,
    case_disputed_item_never_opens_a_script,
    case_ladder_orders_the_arc,
    case_highest_act_wins,
    case_penetration_scores_without_acts,
    case_unscoreable_is_none_not_zero,
    case_missing_axis_does_not_shift_the_others,
    case_act_alias_is_scored,
    case_buildup_sends_before_payoff_at_same_rung,
    case_rung_outranks_everything_below_it,
    case_send_order_reads_brief_not_a_second_taxonomy,
    case_price_tiers_split_on_nudity_and_visibility,
    case_fifty_never_contains_lingerie_on,
    case_pussy_and_breasts_are_asked_separately,
    case_underwear_flag_overrides_the_clothing_enum,
    case_mass_lane_is_suggestive_only,
    case_nothing_on_show_is_never_a_tease,
    case_unflagged_item_is_never_called_mass_safe,
    case_unflagged_stills_wait_out_of_the_price_lanes,
    case_mass_safe_needs_to_know_what_is_in_frame,
    case_partial_flags_do_not_count_as_checked,
    case_a_named_garment_means_she_is_dressed,
    case_a_hand_over_her_breast_is_not_being_dressed,
    case_not_in_frame_is_an_answer_not_a_silence,
    case_clip_frames_fold_by_worst_not_by_all,
    case_contradictions_score_only_answered_rows,
    case_turned_away_explicit_is_safe_to_mass,
    case_paid_tease_lanes_are_images_only,
    case_suggestive_item_sits_in_both_lanes_at_different_positions,
    case_purpose_pool_can_be_restricted_to_leftovers,
    case_outfit_key_prefers_multiword_colour,
    case_outfit_key_falls_back_and_gives_up,
    case_same_colour_different_garment_is_a_different_set,
    case_undressing_does_not_split_a_script,
    case_unrecognised_garment_still_keys_on_colour,
    case_outfit_joins_photos_and_videos_into_one_script,
    case_same_colour_far_apart_is_two_shoots,
    case_one_rung_group_is_a_set_not_a_script,
    case_mixed_media_scripts_rank_first,
    case_a_shoot_that_closes_outranks_a_bigger_one_that_cannot,
    case_plan_previews_without_creating_anything,
    case_apply_does_not_touch_of_unless_asked,
    case_mirror_creates_of_lists_and_binds_them,
    case_mirror_rerun_reuses_the_same_of_list,
    case_mirror_binds_membership_into_the_cache,
    case_mirror_membership_follows_of_not_the_plan,
    case_of_failure_keeps_the_internal_folder,
    case_apply_creates_folders_in_send_order,
    case_apply_twice_refreshes_instead_of_duplicating,
    case_rebuild_retires_folders_the_plan_no_longer_makes,
    case_retire_never_touches_operator_folders,
    case_apply_leaves_an_operators_ai_named_folder_alone,
    case_two_shoots_with_one_name_keep_their_own_items,
    case_same_name_suffix_follows_start_not_rank,
    case_mirror_keeps_two_same_named_shoots_apart,
    case_no_paid_item_is_left_out_of_every_lane,
    case_explicit_clips_get_a_lane,
    case_solo_cut_keeps_only_her,
    case_solo_is_off_unless_asked,
    case_a_partner_act_outranks_the_count,
    case_an_unasked_item_is_never_solo,
    case_solo_folders_are_created_and_retired_like_any_other,
)
