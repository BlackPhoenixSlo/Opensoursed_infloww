#!/usr/bin/env python3
"""
Vault ordering and AI folders (`vault_scripts`) — the escalation ladder, the
send order, and the outfit / purpose folders built from them. Durable
regression suite (plain-assert, no pytest — repo convention).

A creator shoots an escalating run (clothed → lingerie → nude → touching →
masturbation). `escalation_score` / `send_sort_key` put any set of items in the
order to send them (tease first, payoff last), and the AI-folder planner groups
the vault into outfits and price lanes in that order. (The upload-burst
clustering / orientation pass and its `script_seq` writer were deleted in
cleanup Phase 6.)

Cases:
  case_ladder_orders_the_arc:
      the ladder is monotone across the real arc — dressed/posing < lingerie
      tease < nude posing < fingering < orgasm. This ordering IS the product
      decision, so it gets pinned rather than left to the weights.
  case_highest_act_wins:
      a clip that opens with a tease and ends with insertion scores at the
      INSERTION end. A clip belongs where it finishes, not where it starts.
  case_penetration_scores_without_acts:
      `penetration` alone lifts an item even when `acts` came back empty, so a
      partially-parsed row still lands in the back half.
  case_unscoreable_is_none_not_zero:
      an item with no usable V2 fields scores None, NOT 0 — zero would sort it
      to the front of the script as though it were the tame opener.
  case_missing_axis_does_not_shift_the_others:
      an absent axis contributes nothing and never reweights its neighbours —
      the defect that killed the original weighted blend.
  case_act_alias_is_scored:
      the model's menu-adjacent spellings ('stripping', 'rubbing_breasts') score
      as the menu term; a genuinely unknown act still scores nothing.
  case_buildup_sends_before_payoff_at_same_rung:
      the distinction the single 0-100 score could NOT express — a nude tease
      and a nude fingering clip both scored 60; `stands_alone` separates them.
  case_rung_outranks_everything_below_it:
      the explicitness ladder dominates: a suggestive closer still sends before
      an explicit build-up.
  case_send_order_reads_brief_not_a_second_taxonomy:
      ordering consumes vault_ai_brief's payoff set and ladder, so the selling
      taxonomy cannot drift into two copies.
  case_price_tiers_split_on_nudity_and_visibility:
      both tiers are explicit, so heat does not separate them. $50 = fully nude
      or pussy visible; $10 = breasts out with something still ON. Fully nude is
      NEVER a $10. Pins the AI- prefix and tier exclusivity too.
  case_fifty_never_contains_lingerie_on:
      lingerie_on + explicit is usually a mislabel, so $50 refuses it outright
      rather than pricing a partial reveal as a full one.
  case_pussy_and_breasts_are_asked_separately:
      the split IS the price boundary — she is often covered in one place and
      bare in the other. $10 = boobs out / pussy covered; $50 = pussy on show;
      a pussy behind a thong is neither.
  case_underwear_flag_overrides_the_clothing_enum:
      `clothing_state` was wrong on ~1 in 3 of the $50 items (fully_nude with
      panties on). The cheap flags pass answers directly, so when
      `underwear_visible` exists it beats the enum.
  case_mass_lane_is_suggestive_only:
      the old suggestive→explicit band swallowed 92 of 103 items and made every
      paid item free as well; mass is suggestive ONLY.
  case_nothing_on_show_is_never_a_tease:
      a top still on, or turned away, means no reveal to charge for — those go
      to the mass/story lane and must not fall out of every lane, which is what
      the old ass/back proxy did to them.
  case_unflagged_item_is_never_called_mass_safe:
      the mass-safe lane requires POSITIVE evidence. Absence of flags used to
      read as "nothing on show" — that is how the graded vault's penetration and dildo
      clips, and all 472 Ava members, got into the mass-safe folder.
  case_mass_safe_needs_to_know_what_is_in_frame:
      a SECOND vacuous-truth hole — the old `pussy_covered` answered FABRIC not
      visibility, so with body_focus empty every "nothing shown" test passed for
      free. Both the graded vault clips survived the flags fix this way. The enum states
      "not in frame" outright; `acts` is the independent second lock.
  case_a_named_garment_beats_the_state_the_model_chose:
      asking for a state directly failed in BOTH polarities. Naming the garment
      is an easier question the same model answers correctly, so the name
      overrules the state — and a named garment also means she is dressed,
      which `underwear_visible` alone could not tell (tank top + skirt = no
      underwear = "nude").
  case_a_hand_over_her_breast_is_not_being_dressed:
      `covered` lumps fabric with a hand because for "how much skin is on show"
      they are the same. For the mass-safe lane they are not — a nude with her
      hands over her breasts is still a nude.
  case_insertion_cannot_happen_through_fabric:
      what is HAPPENING overrules what the flags thought they saw. Fingers do
      not go through a thong. Narrow on purpose — rubbing and groping happen
      over underwear, so firing on them would invent exposure.
  case_not_in_frame_is_an_answer_not_a_silence:
      why the shape changed at all — under booleans, "cannot see it" and "it is
      bare" were the same stored value, so no lane could tell safety from
      ignorance.
  case_partial_flags_do_not_count_as_checked:
      every region must be present AND be a state the vocabulary defines; half
      an answer is not one, and the superseded boolean shape is not one either.
  case_clip_frames_fold_by_worst_not_by_all:
      the `all()` fold let a frame that saw nothing vote for exposure — 20 of 21
      the graded vault clips folded to "uncovered". Regions fold by MAX exposure.
  case_contradictions_score_only_answered_rows:
      the free quality metric: describe and flags look at the same image, so
      where they disagree one is provably wrong. Must not fire on incomplete
      rows or it measures coverage instead of correctness.
  case_turned_away_explicit_is_safe_to_mass:
      tagged explicit for what the scene IS, but only her back/ass is in frame
      — nothing on show, so it is mass-safe.
  case_paid_tease_lanes_are_images_only:
      the paid tiers are stills; clips never leak in.
  case_suggestive_item_sits_in_both_lanes_at_different_positions:
      THE multi-folder case end to end — a suggestive still CLOSES the tamer
      lane and OPENS the spicier one. Impossible if order lived on the item.
  case_purpose_pool_can_be_restricted_to_leftovers:
      a kept shoot's media never leaks into the leftover lanes.
  case_outfit_key_prefers_multiword_colour:
      'dark blue' wins before 'blue' matches inside it.
  case_outfit_key_falls_back_and_gives_up:
      material is the fallback; an unnamed garment yields NO outfit rather than
      pooling every unattributable item into one junk group.
  case_same_colour_different_garment_is_a_different_set:
      the operator's complaint — one 'black' group was three sets. A bodysuit,
      a bra set and a top are different outfits even in one colour.
  case_undressing_does_not_split_a_script:
      a shoot RUNS dressed → undressed, so the outfit key must not split on
      clothing_state or every real script fragments.
  case_unrecognised_garment_still_keys_on_colour:
      an unusual garment wording still groups by colour rather than vanishing.
  case_outfit_joins_photos_and_videos_into_one_script:
      THE point — upload bursts are kind-pure, so burst grouping splits a shoot
      down the middle; the outfit re-joins the stills and the clips.
  case_same_colour_far_apart_is_two_shoots:
      the same colour three weeks later is a different shoot.
  case_one_rung_group_is_a_set_not_a_script:
      eight equally-suggestive stills in one bra is a set, not a script.
  case_mixed_media_scripts_rank_first:
      a shoot with both stills and clips outranks a photo-only one.
  case_apply_does_not_touch_of_unless_asked:
      the OF write is opt-in — `confirm` alone never reaches her account.
  case_mirror_creates_of_lists_and_binds_them:
      mirroring creates one OF vault list per folder and binds of_list_id.
  case_mirror_rerun_reuses_the_same_of_list:
      a second run ADDS to the bound list rather than creating a duplicate list
      of the same name on her account.
  case_of_failure_keeps_the_internal_folder:
      an OF error never rolls back the internal folder — local-without-OF is
      recoverable, losing the grouping is not.
  case_plan_previews_without_creating_anything:
      the preview the vault button shows creates ZERO folders.
  case_apply_creates_folders_in_send_order:
      confirming creates exactly the previewed folders, each filled 1..n in the
      order the preview showed.
  case_apply_twice_refreshes_instead_of_duplicating:
      pressing the button again REUSES the AI- folders and rewrites membership
      rather than piling up a second set.
  case_rebuild_retires_folders_the_plan_no_longer_makes:
      a previous generation's folders are soft-deleted on rebuild, so a rules or
      naming change does not leave two versions of the same idea behind.
  case_retire_never_touches_operator_folders:
      only rows this module created AND carrying the AI- prefix are retired —
      an operator folder is safe even if they named it AI- themselves.
  case_apply_never_rewrites_a_hand_made_folder:
      a folder the operator made is never touched — only AI- folders.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_scripts.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod). No OF, no
network, no LLM — scoring is pure arithmetic over already-stored fields.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import vault_scripts  # noqa: E402
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
    """A V2 describe payload with only the fields a case cares about."""
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


# ── The ladder ──────────────────────────────────────────────────────

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
    """An absent axis must contribute nothing — never reweight its neighbours.

    The original blend re-normalised over the axes present, which made items
    with different field coverage incomparable: a nude item with no `acts`
    outscored one with a toy inserted. Max has no such coupling.
    """
    no_acts = escalation_score(_fields("fully_nude", None, None, "explicit"))
    with_tame_act = escalation_score(_fields("fully_nude", ["posing"], "none", "explicit"))
    assert no_acts == with_tame_act, (
        f"adding a LOW act changed a saturated score ({no_acts} → {with_tame_act})")
    assert no_acts is not None and no_acts > 50, (
        f"missing `acts` dragged a nude item to {no_acts}")


def case_act_alias_is_scored() -> None:
    # The model returns menu-adjacent spellings on real batches; an unknown act
    # is dropped silently, so drift costs signal rather than announcing itself.
    assert (escalation_score(_fields("lingerie_on", ["stripping"]))
            == escalation_score(_fields("lingerie_on", ["strip"]))), "alias not mapped"
    assert (escalation_score(_fields("fully_nude", ["rubbing_breasts"]))
            == escalation_score(_fields("fully_nude", ["groping_own_breasts"])))
    # An act we have never seen must not crash or invent a rung.
    assert escalation_score(_fields(None, ["lying_on_back"])) is None


# ── End to end ──────────────────────────────────────────────────────

async def _seed(aid: str, items: list[tuple]) -> None:
    """items = [(media_id, minutes_offset, v2_fields[, kind])] in UPLOAD order.

    `kind` defaults to "video". It matters for the outfit cases: real upload
    bursts are kind-PURE, so a case about joining stills to clips has to seed
    both or it proves nothing.
    """
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
    """The distinction the single 0-100 score could NOT express.

    A nude tease and a nude fingering clip both score 60 on the escalation
    ladder, so the old key ordered them arbitrarily. `stands_alone` from
    vault_ai_brief separates them: a clip with no payoff act is a rung that tees
    up the next send, so it goes first; one that can close goes last.
    """
    tease = _fields("fully_nude", ["posing", "tease"], "none", "explicit")
    closes = _fields("fully_nude", ["fingering"], "fingers", "explicit")
    assert vault_scripts.send_sort_key(tease) < vault_scripts.send_sort_key(closes), (
        "build-up must send before a payoff at the same rung")
    assert vault_scripts.send_order_reason(tease)["closes"] is False
    assert vault_scripts.send_order_reason(closes)["closes"] is True


def case_rung_outranks_everything_below_it() -> None:
    """sfw→suggestive→explicit→hardcore is the night's escalation and dominates:
    a suggestive clip that CLOSES still sends before an explicit build-up."""
    suggestive_closer = _fields("lingerie_on", ["rubbing_clit"], "none", "suggestive")
    explicit_buildup = _fields("fully_nude", ["posing"], "none", "explicit")
    assert (vault_scripts.send_sort_key(suggestive_closer)
            < vault_scripts.send_sort_key(explicit_buildup)), "rung must dominate"


def case_send_order_reads_brief_not_a_second_taxonomy() -> None:
    """Ordering consumes vault_ai_brief so the two cannot drift. If the brief's
    payoff set changes, the order changes with it — no parallel copy here."""
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
    """A COMPLETE flags answer. Complete on purpose: a partial one is not an
    answer at all (`flags_known`), so a test that seeded three of four keys
    would be exercising the unflagged path while looking like it tested a
    flagged item.

    `over_*` is what the model NAMED as covering that region. It is optional in
    the schema but load-bearing in the lanes: `covered` alone does not say
    whether she is dressed or has a hand in the way.
    """
    out = {"underwear_visible": underwear, "vulva_vis": vulva,
           "breasts_vis": breasts, "anus_vis": anus}
    for key, val in (("over_vulva", over_vulva), ("over_breasts", over_breasts),
                     ("over_anus", over_anus)):
        if val:
            out[key] = val
    return out


def _dressed(**kw) -> dict:
    """Covered by actual clothing — the shape that IS mass-safe."""
    return _flags(vulva="covered", breasts="covered",
                  over_vulva="black lace bodysuit",
                  over_breasts="black lace bodysuit", **kw)


def _turned_away(**kw) -> dict:
    """Shot from behind: her front is not what the camera is looking at, so it
    is `not_in_frame` rather than `covered` — being turned away is not
    something covering her."""
    return _flags(vulva="not_in_frame", breasts="not_in_frame",
                  anus="covered", **kw)


def case_price_tiers_split_on_nudity_and_visibility() -> None:
    """Both tiers are explicit, so heat does not separate them. $50 is the full
    reveal — fully nude, or her pussy visible. $10 is the middle band: breasts
    out with something still on. Fully nude is NEVER a $10."""
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1101, 0.0, _shot(["face"], "sfw", "dressed"), "photo"),
        (1102, 0.1, _shot(["breasts"], "suggestive", "lingerie_on"), "photo"),
        # explicit, breasts out, pussy NOT in frame -> $10
        (1103, 0.2, {**_shot(["breasts", "nipples"], "explicit", "pulled_down"),
                     **_flags(breasts="bare")}, "photo"),
        # explicit, FULLY NUDE, pussy not in frame -> $50, never $10
        (1104, 0.3, {**_shot(["breasts"], "explicit", "fully_nude"),
                     **_flags(breasts="bare", underwear=False)}, "photo"),
        # explicit, pussy visible -> $50
        (1105, 0.4, {**_shot(["pussy"], "explicit", "pulled_aside"),
                     **_flags(vulva="bare", breasts="covered")}, "photo"),
        # explicit, full body nude -> $50
        (1106, 0.5, {**_shot(["full_body"], "explicit", "fully_nude"),
                     **_flags(breasts="bare", underwear=False)}, "photo"),
        # Explicit with breasts IN FRAME but never actually looked at. Under the
        # old shape this priced at $10: `body_focus` said breasts, and a missing
        # `breasts_covered` read as "not covered" — so a bra-on shot was sold as
        # a reveal. A price may only rest on a flag that was answered.
        (1107, 0.6, _shot(["breasts", "nipples"], "explicit", "pulled_down"), "photo"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    assert set(lanes) >= {"stories", "mass", "tease_10", "tease_50"}, list(lanes)
    assert {r["media_id"] for r in lanes["tease_10"]["items"]} == {1103}, \
        "$10 is breasts out with something still ON, and only when checked"
    assert {r["media_id"] for r in lanes["tease_50"]["items"]} == {1104, 1105, 1106}, \
        "fully nude / pussy visible / full-body all price at $50"
    # Content lanes may overlap; two PRICES for one item may not.
    assert not ({r["media_id"] for r in lanes["tease_10"]["items"]}
                & {r["media_id"] for r in lanes["tease_50"]["items"]}), \
        "an item cannot be both a $10 and a $50"
    assert all(f["name"].startswith("AI-") for f in lanes.values()), "missing AI- prefix"


def case_fifty_never_contains_lingerie_on() -> None:
    """`lingerie_on` + explicit is usually a mislabel (panties pulled aside read
    as lingerie on). Trusting it would price a partial reveal as a full one, so
    the $50 tier refuses the combination outright."""
    aid = _next_account()
    asyncio.run(_seed(aid, [
        # Both flagged: the paid tiers only price what was actually looked at.
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
    """The split IS the price boundary. One conflated `genitals_covered` could
    not express the middle tier: she is very often covered in one place and bare
    in the other, and that difference is what $10 vs $50 means."""
    aid = _next_account()
    asyncio.run(_seed(aid, [
        # Boobs out, pussy still behind fabric -> the $10 band.
        (1161, 0.0, {**_shot(["breasts", "nipples", "pussy"], "explicit", "pulled_down"),
                     **_flags(vulva="covered", breasts="bare")}, "photo"),
        # Pussy on show -> $50, regardless of the breasts.
        (1162, 0.1, {**_shot(["breasts", "pussy"], "explicit", "pulled_aside"),
                     **_flags(vulva="bare", breasts="covered")}, "photo"),
        # Pussy in frame but behind a thong -> neither tier calls it a reveal.
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
    """`clothing_state` was measured wrong on ~1 in 3 of the items the $50 tier
    is built from — `fully_nude` on shots with panties still on, with nothing in
    the row to contradict it. The cheap flags pass answers that directly, so
    when `underwear_visible` exists it wins outright."""
    aid = _next_account()
    asyncio.run(_seed(aid, [
        # The exact failure: enum says nude, the flag says she is not.
        (1151, 0.0, {**_shot(["breasts"], "explicit", "fully_nude"),
                     **_flags(breasts="bare", underwear=True)}, "photo"),
        # Genuinely nude, flag agrees.
        (1152, 0.1, {**_shot(["breasts"], "explicit", "fully_nude"),
                     **_flags(breasts="bare", underwear=False)}, "photo"),
        # Something over her vulva is never the full reveal, whatever else shows.
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
    """The old suggestive→explicit band swallowed 92 of 103 items and made every
    paid item free as well."""
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
    """A top still on, or turned away, means there is no reveal to charge for.
    Those belong in the mass/story lane, never in a paid tease — and they must
    not fall out of every lane either, which is what the old `ass`/`back` proxy
    did to them."""
    aid = _next_account()
    asyncio.run(_seed(aid, [
        # Top on: breasts in frame but covered, pussy covered.
        (1171, 0.0, {**_shot(["breasts", "face"], "explicit", "lingerie_on"),
                     **_dressed()}, "photo"),
        # Turned away: her front is not in the picture at all.
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


def case_unflagged_item_is_never_called_mass_safe() -> None:
    """The lane that claims something is safe to put in front of everyone must
    require POSITIVE evidence. Every other test in it reads "no evidence of
    exposure", which an unflagged item satisfies trivially — that is how
    the graded vault's anal-penetration clip and dildo clip landed in the mass-safe
    folder, and how all 472 members on V1-described Ava got there.
    """
    aid = _next_account()
    asyncio.run(_seed(aid, [
        # Flagged and genuinely turned away → safe.
        (1401, 0.0, {**_shot(["ass", "back"], "explicit", "fully_nude"),
                     **_turned_away(underwear=False)}, "photo"),
        # NEVER looked at by the flags pass → must NOT be called safe.
        (1402, 0.1, _shot(["ass", "back"], "explicit", "fully_nude"), "photo"),
        # A clip with nothing recorded at all — the a real graded shape.
        (1403, 0.2, {"explicitness": "explicit"}, "video"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    safe = {r["media_id"] for r in lanes.get("covered_explicit", {}).get("items", [])}
    assert safe == {1401}, f"an unflagged item was called mass-safe: {safe}"


def case_mass_safe_needs_to_know_what_is_in_frame() -> None:
    """The lane went vacuously true TWICE, in two different ways, and the
    v1 flags could not express the difference that would have stopped either.

    `pussy_covered` asked about FABRIC, so "out of frame" and "bare" both came
    back False; `body_focus` was the only in-frame signal and it was absent on
    the dildo clip and lacked `pussy` on the anal one. Both read as "nothing on
    show". The enum states that difference outright, so the two shapes below
    are now distinguishable — `not_in_frame` is an answer, not a silence.
    """
    explicit = {"explicitness": "explicit"}
    anal = {**explicit, **_flags(anus="bare", underwear=False),
            "body_focus": ["ass", "anus", "fingers"]}
    turned_away = {**explicit, **_turned_away(underwear=False),
                   "body_focus": ["ass", "back", "legs"]}
    # The shape a THIRD hole would take: the flags see nothing anywhere, so
    # every visibility test passes for free — exactly how the first two got in.
    # `acts` is what stops it, and `acts` does not depend on the flags being
    # right about anything.
    blind_dildo = {**explicit, **_flags(underwear=False),
                   "acts": ["toy_insertion"], "body_focus": None}

    for name, f in (("anal", anal), ("nothing visible but penetrating", blind_dildo)):
        assert not vault_scripts._lane_covered_explicit(
            vault_scripts.send_order_reason(f), f, "video"), f"{name} called mass-safe"
    assert vault_scripts._lane_covered_explicit(
        vault_scripts.send_order_reason(turned_away), turned_away, "photo"), \
        "a genuinely turned-away shot must still qualify"
    # `anus` counts as genital exposure wherever exposure is read.
    assert vault_scripts._shows_genitals(anal) is True


def case_a_named_garment_beats_the_state_the_model_chose() -> None:
    """Asking for a state directly failed in BOTH polarities: `covered` pulled
    toward false on anything racy, and `bare` came back on a white tank top and
    a black halter. Naming the garment is an easier question and the same model
    answers it correctly — its own prose said "wearing a white tank top" about a
    photo it then called bare. So the name overrules the state.
    """
    import vault_ai_api as api
    import vault_ai_brief as brief

    tank = api._ground_in_named_garment(
        {"breasts_vis": "bare", "over_breasts": "white tank top",
         "vulva_vis": "not_in_frame"})
    assert tank["breasts_vis"] == "covered", "a named garment did not win"
    # `not_in_frame` is NOT overridden — a garment can be named on a body part
    # that is genuinely out of shot, and calling that "covered" would claim we
    # saw something we did not.
    assert tank["vulva_vis"] == "not_in_frame"
    # Genuinely bare: nothing named, so nothing to override.
    for nothing in (None, "", "none", "nothing", "null", "bare skin"):
        got = api._ground_in_named_garment(
            {"breasts_vis": "bare", "over_breasts": nothing})
        assert got["breasts_vis"] == "bare", f"{nothing!r} read as a garment"

    # And a named garment means she is dressed, whatever `underwear_visible`
    # says — that flag asks only about UNDERWEAR, so a tank top and a skirt
    # answer False and a fully-dressed street selfie came back nude.
    dressed = {**_flags(), "over_breasts": "pink tank top",
               "over_vulva": "white skirt", "underwear_visible": False}
    assert brief.wearing_something(dressed) is True
    assert vault_scripts._is_nude(dressed) is False, "a dressed selfie read as nude"
    assert vault_scripts._is_nude({**_flags(), "underwear_visible": False}) is True

    # A hand is not a garment. She is still nude behind her own hand, and a
    # hand-bra nude sells at the full price — but she is NOT nude behind a
    # thong. `covered` treats the two alike because for "what is on show" they
    # are alike; nudity must not, because for "what is she wearing" they are
    # opposites. Both shapes are a real graded rows.
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
    """`covered` deliberately lumps fabric with a hand, a thigh and the bedding,
    because for "how much skin is on show" they are the same thing. For the
    mass-safe lane they are not: a woman lying fully nude with her hands over
    her breasts has nothing technically exposed and is still a nude. Sending
    that to a whole list is the exact mistake the folder exists to prevent.
    """
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
    # REGRESSION, from her real vault. "Wearing something" is NOT the test:
    # six stills of her topless with her hands over her breasts and a thong on
    # passed a `not _is_nude(...)` rule and went to the mass-safe folder. A
    # thong is not what makes a topless shot decent, and nudity says nothing
    # about which HALF of her is dressed.
    topless_thong = {"explicitness": "explicit", "clothing_state": "fully_nude",
                     **_flags(vulva="covered", breasts="covered", anus="covered",
                              underwear=True, over_vulva="pink thong",
                              over_breasts="her hands")}
    assert not vault_scripts._is_nude(topless_thong), "fixture should read clothed"
    assert not safe(topless_thong), "topless-with-hands went to a mass send"
    # Covered by something the model would not name: this is the one lane where
    # "we cannot tell you what is covering her" has to read as a no.
    assert not safe(unnamed), "an unexplained `covered` was treated as dressed"

    # REGRESSION, also from her real vault: the model fills every `over_` slot
    # with the one garment it can see. # is "fully nude except for
    # pink underwear" — topless — and came back with "pink thong" over her
    # BREASTS, which passed as clothing. A thong cannot cover breasts.
    thong_on_breasts = {"explicitness": "explicit",
                        **_flags(vulva="covered", breasts="covered",
                                 over_vulva="pink thong",
                                 over_breasts="pink thong")}
    assert brief.garment_over(thong_on_breasts, "breasts_vis") == "", \
        "a thong was accepted as covering her breasts"
    assert brief.garment_over(thong_on_breasts, "vulva_vis") == "pink thong"
    assert not safe(thong_on_breasts), "a topless still reached the mass-safe lane"
    # A one-piece garment legitimately covers both, so duplication itself is
    # not the signal — only an impossible pairing is.
    suit = {"explicitness": "explicit",
            **_flags(vulva="covered", breasts="covered",
                     over_vulva="black lace bodysuit",
                     over_breasts="black lace bodysuit")}
    assert safe(suit), "a bodysuit over both regions was rejected as duplication"

    # ...and she is still NUDE behind her own hand, so the price tier keeps her.
    assert vault_scripts._is_nude(nude_hands) is True


def case_insertion_cannot_happen_through_fabric() -> None:
    """REGRESSION, from the operator's second grading pass. The flags pass
    looks at one frame, names the garment nearest the action and calls the
    region covered — producing, verbatim on her vault: "A hand is inserting two
    fingers into the vagina" with `vulva_vis: covered, over_vulva: 'pink lace
    thong'`. Fingers do not go through a thong.

    Four of fourteen corrections were this shape, all on the most explicit and
    therefore most valuable items, and all four had been priced at nothing.
    """
    import vault_ai_api as api

    fingering = {"acts": ["fingering"], "penetration": "fingers"}
    got = api._reconcile_with_acts(
        fingering, {"vulva_vis": "covered", "over_vulva": "pink lace thong"})
    assert got["vulva_vis"] == "bare", "insertion left the vulva covered"
    assert "over_vulva" not in got, "the disproven garment stayed named"

    # Anal only when the row actually says so.
    anal = {"acts": ["fingering"], "penetration": "fingers",
            "body_focus": ["ass", "anus"]}
    assert api._reconcile_with_acts(anal, {"anus_vis": "covered"})["anus_vis"] == "bare"

    # NARROW ON PURPOSE. Rubbing and groping happen over underwear constantly;
    # firing on them would manufacture exposure instead of detecting it, and
    # this rule gates both money and mass sends.
    for tame in (["rubbing_clit"], ["groping_own_breasts"], ["posing"], []):
        got = api._reconcile_with_acts(
            {"acts": tame}, {"vulva_vis": "covered", "over_vulva": "black thong"})
        assert got["vulva_vis"] == "covered", f"{tame} invented exposure"
    # An already-bare or out-of-shot region is never touched.
    assert api._reconcile_with_acts(
        fingering, {"vulva_vis": "not_in_frame"})["vulva_vis"] == "not_in_frame"


def case_not_in_frame_is_an_answer_not_a_silence() -> None:
    """The whole reason the shape changed. Under the booleans, "I cannot see
    that part of her" and "that part of her is bare" were the same stored
    value, so a lane could not tell being safe from having no evidence."""
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
    """Half an answer is not an answer — every region must be present AND be a
    state the vocabulary defines."""
    import vault_ai_brief as brief

    assert brief.flags_known(_flags()) is True
    assert brief.flags_known({"vulva_vis": "covered"}) is False
    assert brief.flags_known({}) is False
    # A region answered with something outside the enum ("no", a stray bool, a
    # hallucinated word) has not been answered.
    for junk in ("no", True, "hidden", None, ""):
        assert brief.flags_known({**_flags(), "breasts_vis": junk}) is False, \
            f"{junk!r} accepted as a region state"
    # The superseded boolean shape must not read as flagged either, or every
    # row written before this change would silently keep its old lane.
    assert brief.flags_known({"underwear_visible": False, "pussy_covered": True,
                              "breasts_covered": True}) is False


def case_clip_frames_fold_by_worst_not_by_all() -> None:
    """`all()` over "covered" booleans collapsed: a frame that simply could not
    see the region answered False, identically to a frame where she was bare,
    so any tightly-framed shot marked the whole clip uncovered. 20 of 21
    the graded vault clips folded that way, which is no signal at all."""
    import vault_ai_brief as brief

    assert brief.fold_vis(["covered", "not_in_frame", "covered"]) == "covered", \
        "a frame that saw nothing must not vote for exposure"
    assert brief.fold_vis(["covered", "bare", "covered"]) == "bare", \
        "one bare frame exposes the clip"
    assert brief.fold_vis(["not_in_frame"] * 4) == "not_in_frame"
    assert brief.fold_vis([]) == "", "no frames is unknown, not safe"
    assert brief.fold_vis(["junk", "bare"]) == "bare", "junk must not win"


def case_contradictions_score_only_answered_rows() -> None:
    """The free quality metric. It has to fire on real disagreement and stay
    silent on rows that are merely incomplete, or it measures coverage instead
    of correctness and every unflagged vault looks broken."""
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
    # Unflagged: nothing to disagree WITH, so it must score clean.
    assert brief.contradictions({"clothing_state": "dressed"}) == []
    assert all(c in brief.CONTRADICTIONS
               for c in brief.contradictions(dressed_but_bare)), "undocumented code"


def case_turned_away_explicit_is_safe_to_mass() -> None:
    """Tagged explicit because of what the scene IS, but she is turned away and
    only her back/ass is in frame — nothing is actually on show."""
    aid = _next_account()
    asyncio.run(_seed(aid, [
        # All three carry the FULL flag set — an item the pass never looked at
        # is excluded from this lane by design (see
        # case_unflagged_item_is_never_called_mass_safe).
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
    """THE multi-folder case, end to end. A suggestive still is the spiciest
    thing in Stories and the mildest thing in Mass, so it must hold a different
    position in each — impossible if order lived on the item."""
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
    """'dark blue' must win before 'blue' matches inside it, or two different
    sets collapse into one."""
    assert vault_scripts.outfit_colour({"clothing_items": ["dark blue lace bra"]}) == "dark blue"
    assert vault_scripts.outfit_colour({"clothing_items": ["blue bra"]}) == "blue"


def case_outfit_key_falls_back_and_gives_up() -> None:
    assert vault_scripts.outfit_colour({"clothing_items": ["lace bodysuit"]}) == "lace"
    # Nothing named → no outfit. Must NOT pool into a junk group.
    assert vault_scripts.outfit_key({"clothing_items": []}) == ""
    assert vault_scripts.outfit_key({}) == ""
    assert vault_scripts.outfit_key(None) == ""  # type: ignore[arg-type]


def case_same_colour_different_garment_is_a_different_set() -> None:
    """The operator's complaint: one 'black' group was three sets. A bodysuit,
    a bra set and a top are different outfits even in the same colour."""
    body = {"clothing_items": ["black lace bodysuit", "fishnet stockings"]}
    bra = {"clothing_items": ["black lace bra", "black lace panties"]}
    top = {"clothing_items": ["black leather jacket", "black top"]}
    keys = {vault_scripts.outfit_key(f) for f in (body, bra, top)}
    assert keys == {"black bodysuit", "black lingerie_set", "black top"}, keys
    # Most-identifying garment wins when several are listed.
    assert vault_scripts.garment_class(body) == "bodysuit", "hosiery outranked the set"


def case_undressing_does_not_split_a_script() -> None:
    """A shoot is SUPPOSED to run dressed → undressed. `clothing_state` carries
    that; the outfit key must not split on it or every real script fragments."""
    on = {"clothing_items": ["pink lace bra"], "clothing_state": "lingerie_on"}
    aside = {"clothing_items": ["pink lace bra"], "clothing_state": "pulled_aside"}
    nude = {"clothing_items": ["pink lace bra"], "clothing_state": "fully_nude"}
    assert len({vault_scripts.outfit_key(f) for f in (on, aside, nude)}) == 1


def case_unrecognised_garment_still_keys_on_colour() -> None:
    """A set is never dropped just because its wording is unusual."""
    assert vault_scripts.outfit_key({"clothing_items": ["red kimono thing"]}) == "red"


def case_outfit_joins_photos_and_videos_into_one_script() -> None:
    """THE point: upload bursts are kind-pure, so burst grouping splits a shoot
    down the middle. The outfit re-joins the stills and the clips."""
    aid = _next_account()
    asyncio.run(_seed(aid, [
        # Photo burst — one sitting.
        (701, 0.0, _outfit(["pink lace bra"], ["posing"], "sfw", "dressed"), "photo"),
        (702, 0.1, _outfit(["pink lace bra"], ["tease"], "suggestive"), "photo"),
        (703, 0.2, _outfit(["pink lace panties"], ["tease"], "suggestive"), "photo"),
        # Clip burst hours later, SAME outfit — a different burst entirely.
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
        # Same colour, three weeks later — a different shoot.
        (804, 30240.0, _outfit(["black lace bra"], ["posing"], "sfw", "dressed")),
        (805, 30240.1, _outfit(["black lace bra"], ["tease"], "suggestive")),
        (806, 30240.2, _outfit(["black lace bra"], ["fingering"], "explicit", "fully_nude")),
    ]))
    scripts = asyncio.run(vault_scripts.collect_outfit_scripts(aid))
    assert len(scripts) == 2, f"time window did not split the colour: {len(scripts)}"
    assert all(s["outfit"] == "black lingerie_set" for s in scripts)


def case_one_rung_group_is_a_set_not_a_script() -> None:
    """Eight equally-suggestive stills in the same bra is a set: there is
    nowhere to walk a fan to, so it is not proposed as a script."""
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


class _FakeOF:
    """Records the OF vault-list calls. `fail_on` makes that folder name raise,
    so partial-failure handling is observable."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.created: list[str] = []
        self.added: list[tuple[int, int]] = []   # (list_id, n_media)
        self.fail_on = fail_on
        self._next = 900
        # Real membership per list. OF's add is APPEND-ONLY, so the fake keeps
        # a union too — that is what makes the read-back meaningful.
        self.members: dict[int, list[int]] = {}

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
        """Read one list back, paginated like OF's."""
        ids = self.members.get(int(list_id), []) if list_id is not None else []
        return {"list": [{"id": m} for m in ids[offset:offset + limit]]}


async def _apply_with_of(aid: str, fake: _FakeOF, keep: int = 1) -> dict:
    """Call the endpoint with the OF client faked at the _make_client seam."""
    import automation_executor as ax
    import vault_ai_api

    orig = ax._make_client
    ax._make_client = lambda *_a, **_k: fake
    try:
        return await vault_ai_api.apply_folder_plan(
            {"account_id": aid, "keep": keep, "confirm": True, "mirror_to_of": True})
    finally:
        ax._make_client = orig


async def _of_list_ids(aid: str) -> dict[str, int | None]:
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultFolder.name, VaultFolder.of_list_id)
            .where(VaultFolder.account_id == aid, VaultFolder.deleted_at.is_(None))
        )).all()
    return {n: (int(v) if v is not None else None) for n, v in rows}


def case_apply_does_not_touch_of_unless_asked() -> None:
    """The OF write is opt-in. `confirm` alone must never reach her account."""
    aid = _next_account()
    _plan_seed(aid)
    fake = _FakeOF()

    async def _run():
        import automation_executor as ax
        import vault_ai_api
        orig = ax._make_client
        ax._make_client = lambda *_a, **_k: fake
        try:
            return await vault_ai_api.apply_folder_plan(
                {"account_id": aid, "keep": 1, "confirm": True})
        finally:
            ax._make_client = orig

    asyncio.run(_run())
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
    # every folder bound to the OF list it created
    bound = asyncio.run(_of_list_ids(aid))
    assert all(v is not None for v in bound.values()), bound
    assert sum(n for _, n in fake.added) == res["items"], "media count differs"


def case_mirror_rerun_reuses_the_same_of_list() -> None:
    """A second run must ADD to the bound list, never create a duplicate list
    of the same name on her account."""
    aid = _next_account()
    _plan_seed(aid)
    fake = _FakeOF()
    asyncio.run(_apply_with_of(aid, fake))
    first_created = list(fake.created)

    asyncio.run(_apply_with_of(aid, fake))
    assert fake.created == first_created, f"created duplicate OF lists: {fake.created}"


@_harness.xfail("picker cache does not carry OF list membership — "
                "OF has 5, grid shows 0; never ran until the run() guard landed; "
                "flaps run-to-run (XPASS 2/6 serial runs 10-30)",
                strict=False)
def case_mirror_binds_membership_into_the_cache() -> None:
    """The picker resolves an OF folder by scanning each cached item's
    `of_folder_ids`, and that column is written ONLY by a full collect. So a
    mirrored folder used to exist on OF while no cached item claimed to be in
    it: the dropdown counted 4 (from OF) and the grid showed 0 (from cache).
    Mirroring must bind membership itself."""
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


@_harness.xfail("cache drops items OF still holds — same root cause as "
                "case_mirror_binds_membership_into_the_cache; flaps run-to-run",
                strict=False)
def case_mirror_membership_follows_of_not_the_plan() -> None:
    """OF's add is append-only, so a list carries the union of every generation
    of the rules that has run. The cache must agree with OF — otherwise the grid
    hides items the operator can plainly see in her real vault."""
    aid = _next_account()
    _plan_seed(aid)
    fake = _FakeOF()
    res = asyncio.run(_apply_with_of(aid, fake))
    lid = res["created"][0]["of_list_id"]

    # a stray from an older ruleset, still on OF but not in the current plan
    stray = 2001
    if stray not in fake.members[lid]:
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
    """A folder that exists locally but not on OF is recoverable; losing the
    grouping is not. So an OF error must never roll the internal folder back."""
    aid = _next_account()
    _plan_seed(aid)
    fake = _FakeOF(fail_on="stories")
    res = asyncio.run(_apply_with_of(aid, fake))

    assert res["of_failed"] == 1, res
    assert asyncio.run(_count_folders(aid)) == res["folders"], "internal folder lost"
    failed = [c for c in res["created"] if c.get("of_error")]
    assert failed and "stories" in failed[0]["name"], failed


async def _read_order(aid: str, folder_id: int) -> list[tuple[int, int]]:
    """Read a folder's membership WITHOUT touching it. `_folder_order` re-orders
    before reading, so it cannot be used to inspect what apply actually wrote."""
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

    # Every created folder carries manual_order 1..n in the planned order.
    for spec, made in zip(plan["folders"], res["created"]):
        got = asyncio.run(_read_order(aid, made["folder_id"]))
        assert [m for m, _ in got] == [r["media_id"] for r in spec["items"]], \
            f"{made['name']}: order differs from the preview"
        assert [o for _, o in got] == list(range(1, len(got) + 1)), got


def case_apply_twice_refreshes_instead_of_duplicating() -> None:
    """Pressing the button again must not pile up a second set of folders."""
    aid = _next_account()
    _plan_seed(aid)
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    first = asyncio.run(vault_scripts.apply_ai_folders(aid, plan))
    second = asyncio.run(vault_scripts.apply_ai_folders(aid, plan))

    assert second["reused"] == second["folders"] and second["new"] == 0, second
    assert asyncio.run(_count_folders(aid)) == first["folders"], "folders duplicated"
    # Membership rewritten, not appended.
    made = second["created"][0]
    got = asyncio.run(_read_order(aid, made["folder_id"]))
    assert len(got) == made["items"], f"membership doubled: {len(got)} vs {made['items']}"


def case_rebuild_retires_folders_the_plan_no_longer_makes() -> None:
    """When the rules or names change, the previous generation's folders must
    not linger — otherwise the list silently holds two versions of one idea."""
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
    """Only rows this module created AND carrying the AI- prefix are retired."""
    aid = _next_account()
    _plan_seed(aid)

    async def _theirs():
        async with get_session() as s:
            s.add(VaultFolder(account_id=aid, name="My favourites",
                              created_by="operator"))
            # even an AI-named folder is safe if the operator made it
            s.add(VaultFolder(account_id=aid, name="AI-mine actually",
                              created_by="operator"))
            await s.commit()
    asyncio.run(_theirs())

    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    res = asyncio.run(vault_scripts.apply_ai_folders(aid, plan))

    assert res["retired"] == [], f"retired an operator folder: {res['retired']}"
    assert asyncio.run(_count_folders(aid)) == res["folders"] + 2


def case_apply_never_rewrites_a_hand_made_folder() -> None:
    """A folder the operator made themselves is never touched, even if the plan
    wants a folder of a colliding name — only `AI-` folders are rewritten."""
    aid = _next_account()
    _plan_seed(aid)

    async def _hand_made():
        async with get_session() as s:
            s.add(Account(id=f"{aid}_x"))  # unrelated, keeps the seed honest
            folder = VaultFolder(account_id=aid, name="My favourites",
                                 created_by="operator")
            s.add(folder)
            await s.flush()
            s.add(VaultFolderItem(account_id=aid, folder_id=folder.id,
                                  media_id=2001, manual_order=7))
            await s.commit()
            return folder.id
    fid = asyncio.run(_hand_made())

    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=1))
    asyncio.run(vault_scripts.apply_ai_folders(aid, plan))

    got = asyncio.run(_read_order(aid, fid))
    assert got == [(2001, 7)], f"hand-made folder was rewritten: {got}"


async def _count_folders(aid: str) -> int:
    async with get_session() as s:
        return len((await s.execute(
            select(VaultFolder).where(VaultFolder.account_id == aid,
                                      VaultFolder.deleted_at.is_(None))
        )).scalars().all())


def case_explicit_clips_get_a_lane() -> None:
    """The two price lanes are images-only by design, and nothing then picked
    the CLIPS up. On the operator's vault that was 21 explicit clips — including
    the payoff ones — matching no lane at all: the most valuable material in the
    account was the material the folder system could not see."""
    aid = _next_account()
    asyncio.run(_seed(aid, [
        (1301, 0.0, {**_shot(["pussy"], "explicit", "fully_nude"),
                     **_flags(vulva="bare", breasts="bare", underwear=False),
                     "acts": ["toy_insertion", "masturbation_orgasm"]}, "video"),
        (1302, 0.1, {**_shot(["pussy"], "hardcore", "pulled_aside"),
                     **_flags(vulva="bare", breasts="covered",
                              over_breasts="black lace bra")}, "video"),
        # A suggestive clip is not PPV material — it belongs to the free lanes.
        (1303, 0.2, {**_shot(["body"], "suggestive", "lingerie_on"),
                     **_flags(vulva="covered", breasts="covered",
                              over_vulva="black lace thong",
                              over_breasts="black lace bra")}, "video"),
        # A still stays out: a photo is priced by the $10/$50 ladder.
        (1304, 0.3, {**_shot(["pussy"], "explicit", "fully_nude"),
                     **_flags(vulva="bare", breasts="bare", underwear=False)}, "photo"),
    ]))
    lanes = {f["lane"]: f for f in asyncio.run(
        vault_scripts.collect_purpose_folders(aid))}
    clips = {r["media_id"] for r in lanes["clips"]["items"]}
    assert clips == {1301, 1302}, f"clips lane is explicit VIDEO only: {clips}"
    assert lanes["clips"]["name"].startswith("AI-"), lanes["clips"]["name"]


def case_no_paid_item_is_left_out_of_every_lane() -> None:
    """The complaint behind this: the plan sorted 272 of 327 items and dropped
    55 without saying so — every one of them explicit or hardcore.

    The five original lanes each answer a specific question, and an item that
    answers no to all of them was simply lost. The commonest shape is right
    here: explicit, but fully covered. `safe explicit` refuses it because
    something IS happening in it; neither price lane wants it because there is
    no reveal to charge for.
    """
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
    # The residual is paid-tier only. An sfw item is already served by `stories`,
    # so a residual that swept it up would be a dumping ground rather than a
    # category.
    assert 1402 in by_lane["stories"] and 1402 not in by_lane["explicit_rest"]


def _clip(mid: int, at: float, acts: list[str], **people) -> tuple:
    """An explicit clip — the `clips` lane takes every one of them, so a case
    about SOLO is not also a case about which lane the item lands in."""
    return (mid, at, {**_shot(["pussy"], "explicit", "fully_nude"),
                      **_flags(vulva="bare", breasts="bare", underwear=False),
                      "acts": acts, **people}, "video")


async def _apply_folders(aid: str, *, solo: bool) -> dict[str, int]:
    """Plan → apply, then the live generated folders as {name: folder_id}."""
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
    """Ticking Solo adds `AI-<lane>-solo`: the same lane, minus everyone else.

    It ADDS rather than filters. The two folders answer different questions —
    "what may I send here" and "what may I send here to a fan who only wants
    her" — and an operator who wants both should not have to rebuild to switch.
    """
    aid = _next_account()
    asyncio.run(_seed(aid, [
        _clip(1501, 0.0, ["toy_insertion"], people_count=1, partner_visible=False),
        _clip(1502, 0.1, ["sex_doggy"], people_count=2, partner_visible=True),
        # Described by V1 — nobody ever asked who is in it. Not solo: see
        # case_an_unasked_item_is_never_solo.
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
    # Named after the lane, prefixed exactly once — the name is what an operator
    # reads in the OF app to know what is in it.
    assert solo["name"] == f"{lanes['clips']['name']}-solo", solo["name"]
    assert solo["name"].startswith("AI-") and solo["name"].count("AI-") == 1, solo["name"]
    assert solo["solo"] is True and solo["solo_of"] == 4, solo
    # Contiguous send order of its own: a subset that kept the lane's numbering
    # would open on whatever position its first member held there.
    assert [r["manual_order"] for r in solo["items"]] == [1, 2], solo["items"]


def case_solo_is_off_unless_asked() -> None:
    """No `-solo` folder exists until the box is ticked. The plan is what
    `apply_ai_folders` retires against, so a solo cut appearing by default would
    mean every account grows a second set of folders on the next rebuild."""
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
    # Every folder answers the question, so no consumer has to test for the key.
    assert all(f["solo"] is False and f["solo_of"] is None for f in plan["folders"]), \
        plan["folders"]


def case_a_partner_act_outranks_the_count() -> None:
    """`people_count: 1` on a clip whose own `acts` say two people is the
    model counting the person the clip is ABOUT. An act that cannot be done
    alone IS a second person, whatever the count says — and a partner clip in a
    solo folder is the wrong thing sold under the wrong promise."""
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
    """Only the V2 describe prompt asks who else is in frame. A row that was
    never asked is not solo — the folder has to be right in the direction it
    fires — and the coverage count is what tells the operator why an empty
    `-solo` folder is not breakage."""
    aid = _next_account()
    asyncio.run(_seed(aid, [
        _clip(1531, 0.0, ["toy_insertion"]),                       # V1: unasked
        _clip(1532, 0.1, ["toy_insertion"], partner_visible=False),  # asked
    ]))
    assert not vault_scripts.is_solo({"acts": ["posing"]}), \
        "no evidence read as solo — the whole vault would be a solo folder"
    assert vault_scripts.is_solo({"partner_visible": False}), "asked, and answered"

    cov = asyncio.run(vault_scripts.solo_coverage(aid))
    assert cov == {"described": 2, "known": 1, "unknown": 1, "solo": 1,
                   "ready": False}, cov
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=0, solo=True))
    assert plan["solo_coverage"] == cov, plan["solo_coverage"]
    assert plan["summary"]["solo_cuts"] == 1, plan["summary"]
    solo = [f for f in plan["folders"] if f["solo"]]
    assert {r["media_id"] for r in solo[0]["items"]} == {1532}, solo[0]["items"]


def case_solo_folders_are_created_and_retired_like_any_other() -> None:
    """A solo cut is a folder like the rest: applying creates it, and applying
    WITHOUT the box retires it. `apply_ai_folders` retires generated folders the
    current plan no longer makes, so the flag has to reach the apply call — a
    preview with Solo on, applied with it off, would create the lanes and delete
    every solo folder in the same breath."""
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


_harness.run(
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
    case_mass_safe_needs_to_know_what_is_in_frame,
    case_partial_flags_do_not_count_as_checked,
    case_a_named_garment_beats_the_state_the_model_chose,
    case_a_hand_over_her_breast_is_not_being_dressed,
    case_insertion_cannot_happen_through_fabric,
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
    case_apply_never_rewrites_a_hand_made_folder,
    case_no_paid_item_is_left_out_of_every_lane,
    case_explicit_clips_get_a_lane,
    case_solo_cut_keeps_only_her,
    case_solo_is_off_unless_asked,
    case_a_partner_act_outranks_the_count,
    case_an_unasked_item_is_never_solo,
    case_solo_folders_are_created_and_retired_like_any_other,
)
