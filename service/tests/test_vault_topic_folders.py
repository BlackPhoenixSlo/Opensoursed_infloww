#!/usr/bin/env python3
"""
Build AI folders' opt-in "Topic folders (Jev)" (`vault_topic_folders` + `vault_scripts.plan_ai_folders(topics=)`).
Plain-assert, no pytest (repo convention).

Cases:
  case_every_topic_rule_matches_and_misses:
      each of the 27 topics takes its planted Jev answer (+ describe acts for the act topics, aliases
      included) and refuses a near miss.
  case_price_split_follows_lane5:
      a split topic lands in free / $10 / $50 / $100 by `lane5`; review or unknown → no folder.
  case_explicit_ladder:
      explicit topics (toy play, masturbation, blowjob, sex): lane $10 → $50, $50 → $100, $100 → $150, free → none.
  case_videos_land_and_review_clips_never_free:
      a clip's current `_jev` lands like a photo's on its read lane; a review clip only on its paid read lane, never
      free (a review photo nowhere).
  case_free_guard_keeps_bare_and_unsure_out_of_free:
      a lane5-free item with breasts / crotch / penetration "y" or "unsure" is in NO free split.
  case_paid_only_and_free_only_topics:
      explicit topics are never free; good morning, clean for promo and clothed tease are never paid.
  case_stale_failed_and_old_video_jev_ignored:
      only a current, ok `_jev` counts (a clip's also needs its VIDEO_VERSION + frames); coverage counts items.
  case_topics_whitelist:
      parse_topics de-dups, canonicalises order, takes a comma string or a list; unknown → ValueError;
      both routes answer 422. `feet` is unknown: feet live in the Feet pack only (owner 2026-11-13).
  case_unticked_builds_no_topic_folders:
      no topics = the plan the build made before; the catalogue and Jev coverage still come back; no
      `feet_preview`, no feet entry.
  case_preview_equals_apply_and_mirror:
      the apply (through the route, OF mirror on) creates exactly the previewed topic folders, same members
      and order, and pushes them to OF under the same names.
  case_untick_retires_topic_folders_and_preview_says_so:
      a later build without the topic shows its folders under `retired` and retires them.
  case_split_off_one_folder_per_topic_and_retire:
      split off: one `AI-<name>` per topic, the union of its splits, through the GET and the apply;
      flipping it retires the other naming's folders (both ways).

Run: venv/bin/python service/tests/test_vault_topic_folders.py
Temp DB bound by _harness (never prod). No OF, no network, no LLM.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

import vault_jev_rules  # noqa: E402
import vault_of_folders  # noqa: E402
import vault_scripts  # noqa: E402
import vault_topic_folders as vt  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, VaultFolder, VaultFolderItem, VaultItem  # noqa: E402

_N = 0


def _aid() -> str:
    global _N
    _N += 1
    return f"topics{_N}"


# Neutral answers: nothing any topic reads says yes.
_BASE_TAGS = {"people_count": "one", "added_text": "caption_text", "toy": "no_toy", "outfit": "lingerie_or_bodysuit",
              "setting": "living_room", "pose": "standing", "framing": "most_of_body", "face_visible": "full_face",
              "facing": "toward_camera"}


def jev(lane5: str = "free", *, bb: str = "n", cb: str = "n", pen: str = "n", yes: tuple = (), **tags) -> dict:
    """A stored `_jev` (vault_jev_rules.blob shape): `yes` Noul tags "y" (P .95), every other read one "n"
    (P .05); `tags` override the Choice argmaxes."""
    nouls = ("wears_heels", "wears_stockings_or_fishnets", "butt_focus", "butt_bare", "breasts_focus",
             "see_through", "nipple_through_fabric", "legs_spread", "mirror_selfie", "smiling", "looking_at_camera",
             "feet_in_water", "mouth_tease", "tongue_out", "watermark", "censor_edit", "phone_visible",
             "multi_panel", "topless", "self_touch")
    t = {**_BASE_TAGS, **tags, **{q: ("y" if q in yes else "n") for q in nouls}}
    return {"v": vault_jev_rules.VERSION, "status": "ok", "state": {}, "lane5": lane5, "lane": lane5,
            "breasts_bare": bb, "crotch_bare": cb, "penetration": pen,
            "tags": t, "P": {q: (.95 if q in yes else .05) for q in nouls}}


def _t(slug: str):
    return vt.BY_SLUG[slug]


# (slug, matching jev kwargs, near-miss jev kwargs)
RULES = (
    ("heels_stockings", dict(yes=("wears_heels",)), dict()),
    ("butt_tease", dict(yes=("butt_focus",)), dict(yes=("butt_focus", "butt_bare"))),
    ("butt_bare", dict(yes=("butt_bare", "butt_focus")), dict(yes=("butt_bare",))),
    ("boobs_closeup", dict(yes=("breasts_focus",), framing="body_part_close_up"), dict(yes=("breasts_focus",))),
    ("see_through", dict(yes=("nipple_through_fabric",)), dict()),
    ("spread", dict(yes=("legs_spread",)), dict()),
    ("bent_over", dict(pose="all_fours_or_bent_over"), dict(pose="kneeling")),
    ("toy_tease", dict(toy="toy_visible_not_in_use"), dict(toy="toy_touching_or_inserted")),
    ("with_partner", dict(people_count="two_or_more"), dict()),
    ("faceless", dict(face_visible="no_face"), dict(face_visible="partial_face")),
    ("mirror_selfies", dict(yes=("mirror_selfie",)), dict()),
    ("good_morning", dict(yes=("smiling", "looking_at_camera"), setting="bedroom"),
     dict(yes=("smiling",), setting="bedroom")),
    ("bikini", dict(outfit="swimwear"), dict()),
    ("shower_bath", dict(yes=("feet_in_water",)), dict()),
    ("outdoors_car", dict(setting="car"), dict(setting="gym")),
    ("lips_tongue", dict(yes=("tongue_out",)), dict()),
    ("clean_promo", dict(added_text="nothing_added"), dict(added_text="nothing_added", yes=("watermark",))),
    ("nude", dict(outfit="nude"), dict(outfit="swimwear")),
    ("clothed_tease", dict(outfit="everyday_clothes"), dict(outfit="nude")),
    ("gym_yoga", dict(setting="gym"), dict(setting="bedroom")),
)
# Body topics: bare by definition, so checked on a paid lane ($10).
BODY_RULES = (
    ("tits", dict(bb="y", yes=("topless",)), dict(bb="unsure", yes=("topless", "breasts_focus"))),
    ("pussy", dict(cb="y"), dict(cb="unsure")),
)
TOY_PLAY = ("toy_play", dict(toy="toy_touching_or_inserted"), dict(toy="toy_visible_not_in_use"))
# Explicit topics: (slug, [(jev kwargs, describe fields) that hit], [... that miss]).
EXPLICIT_RULES = (
    ("toy_play", [(TOY_PLAY[1], {})], [(TOY_PLAY[2], {})]),
    ("masturbation",
     [({}, {"acts": ["fingering"]}), ({}, {"acts": ["Masturbation"]}), ({}, {"acts": ["rubbing_clit", "posing"]}),
      (dict(cb="y", yes=("self_touch",)), {}), (dict(pen="y"), {})],
     [({}, {"acts": ["posing", "tease"]}), (dict(cb="n", yes=("self_touch",)), {}),
      (dict(pen="y", toy="toy_touching_or_inserted"), {}), ({}, {"acts": "fingering"}),
      ({}, {"acts": ["fingering", "sex_doggy"]}), (dict(pen="y"), {"primary_folder": "sex_with_partner"}),
      (dict(pen="y", people_count="two_or_more"), {})]),
    ("blowjob", [({}, {"acts": ["blowjob"]}), ({}, {"acts": ["handjob"]}), ({}, {"primary_folder": "blowjob"})],
     [({}, {"acts": ["cumshot"]}), ({}, {"primary_folder": "posing"})]),
    ("sex", [({}, {"acts": ["sex_doggy"]}), ({}, {"penetration": "penis"}),
             ({}, {"primary_folder": "sex_with_partner"})],
     [({}, {"penetration": "toy"}), ({}, {"acts": ["blowjob"]}), (dict(people_count="two_or_more"), {})]),
)
# Act topics on the split ladder: (slug, hit fields, miss fields).
ACT_RULES = (
    ("dance_strip", {"acts": ["twerking"]}, {"acts": ["posing"]}),
)


def case_every_topic_rule_matches_and_misses() -> None:
    named = ({s for s, _, _ in RULES} | {s for s, _, _ in BODY_RULES} | {s for s, _, _ in EXPLICIT_RULES}
             | {s for s, _, _ in ACT_RULES})
    assert named == set(vt.SLUGS) and len(vt.SLUGS) == 27, sorted(set(vt.SLUGS) ^ named)
    for slug, hit, miss in RULES:
        assert vt.split(_t(slug), jev("free", **hit)) == "free", slug
        assert vt.split(_t(slug), jev("free", **miss)) is None, slug
    for slug, hit, miss in BODY_RULES:
        assert vt.split(_t(slug), jev("$10", **hit)) == "$10", slug
        assert vt.split(_t(slug), jev("$10", **miss)) is None, slug
        assert vt.split(_t(slug), jev("free", **hit)) is None, slug    # bare: never free
    for slug, hits, misses in EXPLICIT_RULES:
        for kw, f in hits:
            assert vt.split(_t(slug), jev("$50", **kw), f) == "$100", (slug, kw, f)
        for kw, f in misses:
            assert vt.split(_t(slug), jev("$50", **kw), f) is None, (slug, kw, f)
    for slug, hit, miss in ACT_RULES:
        assert vt.split(_t(slug), jev("free"), hit) == "free", slug
        assert vt.split(_t(slug), jev("free"), miss) is None, slug
        assert vt.split(_t(slug), jev("free")) is None, slug             # no describe fields: no acts
    assert vt.split(_t("dance_strip"), jev("$10"), {"acts": ["stripping"]}) == "$10"
    assert vt.split(_t("tits"), jev("$10", bb="y", yes=("breasts_focus",))) == "$10"
    assert vt.split(_t("tits"), jev("$10", bb="n", yes=("topless",))) is None
    # `acts` normalises the describe drift (aliases, case, spaces).
    assert vt.acts({"acts": ["Twerking", " squirting "]}) == {"twerk", "squirt"} and vt.acts({}) == set()
    # The second branch of the or-rules.
    assert vt.split(_t("heels_stockings"), jev(yes=("wears_stockings_or_fishnets",))) == "free"
    assert vt.split(_t("see_through"), jev(yes=("see_through",))) == "free"
    assert vt.split(_t("shower_bath"), jev(setting="bathroom")) == "free"
    assert vt.split(_t("lips_tongue"), jev(yes=("mouth_tease",))) == "free"
    assert vt.split(_t("good_morning"), jev(yes=("smiling", "looking_at_camera"), outfit="everyday_clothes")) == "free"
    assert vt.split(_t("boobs_closeup"), jev(yes=("breasts_focus",), framing="face_and_chest")) == "free"
    assert vt.split(_t("butt_bare"), jev(yes=("butt_bare",), pose="all_fours_or_bent_over")) == "free"
    for q in ("censor_edit", "phone_visible", "multi_panel"):
        assert vt.split(_t("clean_promo"), jev(added_text="nothing_added", yes=(q,))) is None, q
    # A missing y/n tag falls back to P at the calibrated cut (mirror_selfie .9).
    j = jev()
    del j["tags"]["mirror_selfie"]
    j["P"]["mirror_selfie"] = .85
    assert vt.split(_t("mirror_selfies"), j) is None
    j["P"]["mirror_selfie"] = .92
    assert vt.split(_t("mirror_selfies"), j) == "free"


def case_price_split_follows_lane5() -> None:
    t = _t("bikini")
    for lane5 in ("free", "$10", "$50", "$100"):
        assert vt.split(t, jev(lane5, outfit="swimwear")) == lane5, lane5
    for lane5 in ("review", "", None, "lingerie"):
        assert vt.split(t, jev(lane5, outfit="swimwear")) is None, lane5
    assert vt.folder_name(t, "$10") == "bikini $10"


def case_free_guard_keeps_bare_and_unsure_out_of_free() -> None:
    for k in ("bb", "cb", "pen"):
        for v in ("y", "unsure", None):
            j = jev("free", outfit="swimwear", **{k: v})
            assert not vt.free_ok(j)
            assert vt.split(_t("bikini"), j) is None, (k, v)
            g = jev("free", yes=("smiling", "looking_at_camera"), setting="bedroom", **{k: v})
            assert vt.split(_t("good_morning"), g) is None, (k, v)
    # An explicit act the bare answers missed (a clip's describe) still never goes free.
    g = jev("free", yes=("smiling", "looking_at_camera"), setting="bedroom")
    assert vt.split(_t("good_morning"), g) == "free"
    for f in ({"acts": ["sex_doggy"]}, {"acts": ["blowjob"]}, {"acts": ["fingering"]}, {"primary_folder": "blowjob"}):
        assert vt.split(_t("good_morning"), g, f) is None, f
        assert vt.split(_t("good_morning"), dict(g, lane5="$10"), f) is None, f   # free-only topic
    assert vt.split(_t("good_morning"), jev("free", yes=("smiling", "looking_at_camera"), setting="bedroom",
                                              toy="toy_touching_or_inserted")) is None
    # The guard only bites free: a paid item may of course be bare.
    assert vt.split(_t("bikini"), jev("$10", bb="y", outfit="swimwear")) == "$10"


def case_explicit_ladder() -> None:
    assert {t.slug for t in vt.TOPICS if t.price == "explicit"} == {"toy_play", "masturbation", "blowjob", "sex"}
    assert not any(t.price == "paid" for t in vt.TOPICS)
    for slug, hits, _ in EXPLICIT_RULES:
        t = _t(slug)
        assert vt.splits(t) == ("$50", "$100", "$150"), slug
        kw, f = hits[0]
        got = {lane: vt.split(t, jev(lane, **kw), f) for lane in ("free", "$10", "$50", "$100", "review")}
        assert got == {"free": None, "$10": "$50", "$50": "$100", "$100": "$150", "review": None}, (slug, got)
        assert vt.folder_name(t, "$150") == f"{t.name} $150"
    # Free with a plain free_ok body is still not free for an explicit topic.
    assert vt.split(_t("blowjob"), jev("free"), {"acts": ["blowjob"]}) is None


def case_paid_only_and_free_only_topics() -> None:
    toy = dict(toy="toy_touching_or_inserted")
    assert vt.split(_t("toy_play"), jev("free", **toy)) is None
    gm = dict(yes=("smiling", "looking_at_camera"), setting="bedroom")
    cp = dict(added_text="nothing_added")
    ct = dict(outfit="swimwear")
    for p in ("$10", "$50", "$100"):
        assert vt.split(_t("good_morning"), jev(p, **gm)) is None
        assert vt.split(_t("clean_promo"), jev(p, **cp)) is None
        assert vt.split(_t("clothed_tease"), jev(p, **ct)) is None
    assert vt.split(_t("clean_promo"), jev("free", **cp)) == "free"
    assert vt.split(_t("clothed_tease"), jev("free", **ct)) == "free"
    assert vt.split(_t("clothed_tease"), jev("free", bb="unsure", **ct)) is None


def feet(feet_subject: float, lane5: str = "free", detail: str = "socks", *, seen: str = "y", **body) -> dict:
    """A `_jev` with the feet answers the pack picker reads (feet_subject, feet_any, feet_detail): never a topic."""
    j = jev(lane5, **body)
    j["feet_subject"] = feet_subject
    j["P"].update(feet_focus=feet_subject)
    j["tags"].update(feet_any=seen, feet_detail=detail, feet_focus="y" if seen == "y" and feet_subject >= .4 else "n")
    return j


def _row(mid: int, j: dict | None, kind: str = "photo") -> dict:
    return {"media_id": mid, "kind": kind, "fields": {"_jev": j} if j is not None else {}}


def vid(lane5: str = "free", read: str | None = None, **kw) -> dict:
    """A clip's current `_jev` (`vault_jev_rules.video_blob` shape): photo-shaped + kind video, vv, frames; a review
    clip keeps its own lane as `read_lane5`."""
    j = {**jev(lane5, **kw), "kind": "video", "vv": vault_jev_rules.VIDEO_VERSION, "frames": [], "review": None}
    if read is not None:
        j.update(read_lane5=read, review="few_frames")
    return j


def case_stale_failed_and_old_video_jev_ignored() -> None:
    hit = dict(outfit="swimwear")
    stale = {**jev(**hit), "v": "v7"}
    failed = {**jev(**hit), "status": "error"}
    old_clip = {**vid(**hit), "vv": "jv0"}
    flat_clip = {**jev(**hit), "kind": "video"}            # no vv / frames: not a current video blob
    rows = [_row(1, jev(**hit)), _row(2, stale), _row(3, failed), _row(4, old_clip, "video"),
            _row(5, flat_clip, "video"), _row(6, None), _row(7, vid(**hit), "video"), _row(8, jev(**hit), "audio")]
    got = vt.assign(rows, ["bikini"])
    assert {k: [r["media_id"] for r in v] for k, v in got.items()} == {("bikini", "free"): [1, 7]}
    assert vt.coverage(rows) == {"items": 7, "with_jev": 2}
    cat = {c["slug"]: c["count"] for c in vt.catalogue(rows)}
    assert cat["bikini"] == 2 and len(cat) == 27


def case_videos_land_and_review_clips_never_free() -> None:
    b = _t("bikini")
    toy = _t("toy_play")
    tc = dict(toy="toy_touching_or_inserted")
    for lane5 in ("free", "$10", "$50", "$100"):
        assert vt.split(b, vid(lane5, outfit="swimwear")) == lane5, lane5
    # A review clip: its paid read lane, never free (even with a free_ok body); explicit maps its read lane.
    assert vt.split(b, vid("review", "free", outfit="swimwear")) is None
    assert vt.split(_t("clean_promo"), vid("review", "free", added_text="nothing_added")) is None
    assert vt.split(b, vid("review", "$10", outfit="swimwear")) == "$10"
    assert vt.split(b, vid("review", "$50", outfit="swimwear")) == "$50"
    assert vt.split(toy, vid("review", "$50", **tc)) == "$100"
    assert vt.split(toy, vid("review", "free", **tc)) is None
    assert vt.split(b, vid("review", None, outfit="swimwear")) is None       # no read lane: unknown
    # A review PHOTO (no read lane) stays nowhere, whatever read_lane5 it carries.
    assert vt.split(b, {**jev("review", outfit="swimwear"), "read_lane5": "$10"}) is None
    # Clip act topics read the describe acts beside the blob.
    assert vt.split(_t("dance_strip"), vid("free"), {"acts": ["twerk"]}) == "free"
    rows = [_row(3, vid("review", "$10", outfit="swimwear"), "video"),
            _row(4, vid("review", "free", outfit="swimwear"), "video")]
    got = {k: [r["media_id"] for r in v] for k, v in vt.assign(rows, ["bikini"]).items()}
    assert got == {("bikini", "$10"): [3]}, got


def case_topics_whitelist() -> None:
    assert vt.parse_topics(None) == [] and vt.parse_topics("") == [] and vt.parse_topics([]) == []
    assert vt.parse_topics("toy_play, heels_stockings,toy_play") == ["heels_stockings", "toy_play"]
    assert vt.parse_topics(["bikini", "spread"]) == ["spread", "bikini"]
    # No feet topic: feet live in the Feet pack only (owner 2026-11-13).
    assert "feet" not in vt.SLUGS and all(t.price != "rung" for t in vt.TOPICS)
    for raw, unknown in ((["bikini", "toes", "nope"], ["nope", "toes"]), (["bikini", "feet"], ["feet"]),
                         ("feet,spread", ["feet"])):
        try:
            vt.parse_topics(raw)
            raise AssertionError("unknown slug accepted")
        except ValueError as e:
            assert e.args[0] == unknown, (raw, e.args)
    aid = _aid()
    asyncio.run(_seed(aid, []))
    for call in (
        lambda: vault_of_folders.get_folder_plan(account_id=aid, keep=0, solo=False, topics="bikini,toes"),
        lambda: vault_of_folders.get_folder_plan(account_id=aid, keep=0, solo=False, topics="bikini,feet"),
        lambda: vault_of_folders.apply_folder_plan({"account_id": aid, "confirm": True, "keep": 0,
                                                    "topics": ["feet"]}),
        lambda: vault_of_folders.apply_folder_plan({"account_id": aid, "confirm": True, "keep": 0,
                                                    "topics": ["feet_tease"]}),
        lambda: vault_of_folders.apply_folder_plan({"account_id": aid, "confirm": True, "keep": 0,
                                                    "topics": {"bikini": 1}}),
    ):
        try:
            asyncio.run(call())
            raise AssertionError("no 422")
        except HTTPException as e:
            assert e.status_code == 422, e.status_code


# ── End to end ──────────────────────────────────────────────────────

# media_id → _jev: every topic's planted hit at one price, plus the cases a price split must handle.
def _vault() -> dict[int, dict | None]:
    v: dict[int, dict | None] = {}
    mid = 100
    for slug, hit, _ in RULES:
        for lane5 in ("free", "$10", "$50", "$100"):
            mid += 1
            v[mid] = jev(lane5, **hit)
    mid += 1
    v[mid] = jev("$50", **TOY_PLAY[1])
    v[900] = jev("review", outfit="swimwear")                 # review: nowhere
    v[901] = jev("free", bb="unsure", outfit="swimwear")       # guarded: nowhere
    v[902] = None                                             # no Jev
    v[920] = vid("$10", outfit="swimwear")                    # clip: AI-bikini $10
    v[921] = vid("review", "free", outfit="swimwear")         # review clip read free: nowhere
    v[922] = vid("review", "$50", outfit="swimwear")          # review clip read $50: AI-bikini $50
    v[923] = {**feet(.95), "kind": "video", "vv": vault_jev_rules.VIDEO_VERSION, "frames": []}  # feet clip: nowhere
    # Feet photos: the Feet pack's, never a topic folder.
    v[910] = feet(.95)
    v[911] = feet(.6, detail="bare")
    v[912] = feet(.9, "$50", cb="y")
    v[913] = feet(.59)
    v[914] = feet(.95, bb="unsure")
    return v


async def _seed(aid: str, items: list[tuple[int, dict | None]]) -> None:
    async with get_session() as s:
        s.add(Account(id=aid))
        await s.commit()
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid))
        for k, (mid, j) in enumerate(items):
            fields = {"clothing_state": "lingerie_on", "explicitness": "suggestive"}
            if j is not None:
                fields["_jev"] = j
            kind = (j or {}).get("kind") or "photo"
            s.add(VaultItem(account_id=aid, media_id=mid, kind=kind,
                            created_at=datetime(2026, 7, 1) + timedelta(minutes=k), tags="[]",
                            describe_status="described", ai_fields_json=json.dumps(fields)))
        await s.commit()


def _topic_folders(plan: dict) -> dict[str, list[int]]:
    return {f["name"]: [i["media_id"] for i in f["items"]] for f in plan["folders"] if f["source"] == "topic"}


async def _db_folders(aid: str) -> dict[str, list[int]]:
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultFolder.name, VaultFolderItem.media_id)
            .join(VaultFolderItem, VaultFolderItem.folder_id == VaultFolder.id)
            .where(VaultFolder.account_id == aid, VaultFolder.deleted_at.is_(None))
            .order_by(VaultFolder.name, VaultFolderItem.manual_order))).all()
    out: dict[str, list[int]] = {}
    for n, m in rows:
        out.setdefault(n, []).append(int(m))
    return out


def case_unticked_builds_no_topic_folders() -> None:
    aid = _aid()
    asyncio.run(_seed(aid, list(_vault().items())))
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=0))
    assert plan["topics"] == [] and _topic_folders(plan) == {} and plan["summary"]["topics"] == 0
    assert plan["jev"] == {"enabled": True, "items": len(_vault()), "with_jev": len(_vault()) - 1}, plan["jev"]
    cat = {c["slug"]: c["count"] for c in plan["topic_catalogue"]}
    assert set(cat) == set(vt.SLUGS)
    # split topics: 4 prices (+ the clip and the $50 review clip); free-only: 1; toy play: its $50 + toy tease's
    # $50 / $100 are not toy play.
    assert cat["bikini"] == 6 and cat["good_morning"] == 1 and cat["clean_promo"] == 1 and cat["toy_play"] == 1, cat
    assert "feet" not in cat and "feet_preview" not in plan
    assert all(set(c) == {"slug", "name", "description", "price", "count"} for c in plan["topic_catalogue"])
    bare = _aid()  # no Jev answers yet: usable count is 0 (Jev is on for everyone since #511)
    asyncio.run(_seed(bare, [(1, None)]))
    assert asyncio.run(vault_scripts.plan_ai_folders(bare, keep=0))["jev"]["with_jev"] == 0


class _FakeOF:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.members: dict[int, list[int]] = {}
        self._next = 500

    def create_vault_list(self, name: str) -> dict:
        self.created.append(name)
        self._next += 1
        return {"id": self._next, "name": name}

    def add_media_to_vault_list(self, list_id: int, media_ids: list[int]) -> dict:
        self.members.setdefault(int(list_id), []).extend(int(m) for m in media_ids)
        return {"success": True}

    def vault_media(self, *, limit=100, offset=0, list_id=None, **kw) -> dict:
        ids = self.members.get(int(list_id), []) if list_id is not None else []
        return {"list": [{"id": m} for m in ids[offset:offset + limit]]}


async def _apply(aid: str, topics: list[str], fake: _FakeOF | None = None, *, split: bool = True) -> dict:
    import automation_executor as ax
    orig = ax._make_client
    if fake is not None:
        ax._make_client = lambda *_a, **_k: fake
    before = asyncio.all_tasks()
    try:
        res = await vault_of_folders.apply_folder_plan(
            {"account_id": aid, "confirm": True, "keep": 0, "topics": topics, "mirror_to_of": fake is not None,
             "split": split})
    finally:
        ax._make_client = orig
    await asyncio.wait_for(asyncio.gather(*(asyncio.all_tasks() - before)), timeout=10)
    return res


def case_preview_equals_apply_and_mirror() -> None:
    aid = _aid()
    v = _vault()
    asyncio.run(_seed(aid, list(v.items())))
    picked = ["bikini", "toy_play", "clean_promo"]
    plan = asyncio.run(vault_of_folders.get_folder_plan(account_id=aid, keep=0, solo=False,
                                                        topics="clean_promo,toy_play,bikini"))
    tf = _topic_folders(plan)
    assert plan["topics"] == ["toy_play", "bikini", "clean_promo"]
    assert set(tf) == {"AI-bikini free", "AI-bikini $10", "AI-bikini $50", "AI-bikini $100",
                       "AI-toy play $100", "AI-clean for promo free"}, sorted(tf)
    assert 920 in tf["AI-bikini $10"] and 922 in tf["AI-bikini $50"], tf
    every = {m for ids in tf.values() for m in ids}
    assert not every & {900, 901, 902, 921, 910, 911, 912, 913, 914, 923}, \
        "review / guarded / no-Jev / review-free clip / feet photo or clip in a topic folder"
    for name, ids in tf.items():
        if name.endswith(" free"):
            assert all(vt.free_ok(v[m]) for m in ids), name
    fake = _FakeOF()
    res = asyncio.run(_apply(aid, picked, fake))
    db = asyncio.run(_db_folders(aid))
    assert {n: db.get(n) for n in tf} == tf, "apply != preview"
    assert res["summary"] == plan["summary"]
    assert set(tf) <= set(fake.created), sorted(set(tf) - set(fake.created))
    by_name = {c["name"]: c for c in res["created"]}
    for n, ids in tf.items():
        assert sorted(fake.members[by_name[n]["of_list_id"]]) == sorted(ids), n
    again = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=0, topics=picked))
    assert again["changes"]["create"] == 0 and again["changes"]["retire"] == 0, again["changes"]


def case_untick_retires_topic_folders_and_preview_says_so() -> None:
    aid = _aid()
    asyncio.run(_seed(aid, list(_vault().items())))
    asyncio.run(_apply(aid, ["bikini", "spread"]))
    plan = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=0, topics=["spread"]))
    retired = sorted(r["name"] for r in plan["changes"]["retired"])
    assert retired == ["AI-bikini $10", "AI-bikini $100", "AI-bikini $50", "AI-bikini free"], retired
    asyncio.run(_apply(aid, ["spread"]))
    live = asyncio.run(_db_folders(aid))
    assert not any(n.startswith("AI-bikini") for n in live) and "AI-spread free" in live
    asyncio.run(_apply(aid, []))
    assert not any(n.startswith(("AI-bikini", "AI-spread")) for n in asyncio.run(_db_folders(aid)))


def case_split_off_one_folder_per_topic_and_retire() -> None:
    rows = [_row(1, jev("free", outfit="swimwear")), _row(2, jev("$50", outfit="swimwear")),
            _row(3, jev("$10", outfit="swimwear"))]
    got = {k: [r["media_id"] for r in v] for k, v in vt.assign(rows, ["bikini"], by_price=False).items()}
    # The union in send order: free, $10, $50.
    assert got == {("bikini", None): [1, 3, 2]}, got
    assert vt.folder_name(_t("bikini"), None) == "bikini" and vt.folder_name(_t("toy_play"), None) == "toy play"

    aid = _aid()
    v = _vault()
    asyncio.run(_seed(aid, list(v.items())))
    picked = ["bikini", "toy_play"]
    split_plan = asyncio.run(vault_of_folders.get_folder_plan(account_id=aid, keep=0, solo=False,
                                                              topics=",".join(picked), split=True))
    one = asyncio.run(vault_of_folders.get_folder_plan(account_id=aid, keep=0, solo=False,
                                                       topics=",".join(picked), split=False))
    assert one["split"] is False and split_plan["split"] is True
    tf = _topic_folders(one)
    assert set(tf) == {"AI-bikini", "AI-toy play"}, sorted(tf)
    by_split = _topic_folders(split_plan)
    for name in ("bikini", "toy play"):
        union = {m for n, ids in by_split.items() if n.startswith(f"AI-{name} ") for m in ids}
        assert set(tf[f"AI-{name}"]) == union and len(tf[f"AI-{name}"]) == len(union), name
    assert {f["price"] for f in one["folders"] if f["source"] == "topic"} == {None}
    # Built split, then rebuilt unsplit: the preview names every split folder as retired, the apply retires them.
    asyncio.run(_apply(aid, picked))
    flip = asyncio.run(vault_scripts.plan_ai_folders(aid, keep=0, topics=picked, split=False))
    retired = {r["name"] for r in flip["changes"]["retired"]}
    assert retired == set(by_split), sorted(retired ^ set(by_split))
    asyncio.run(_apply(aid, picked, split=False))
    live = asyncio.run(_db_folders(aid))
    topic_live = {n for n in live if n.startswith(("AI-bikini", "AI-toy play"))}
    assert topic_live == set(tf), sorted(topic_live)
    assert {n: live[n] for n in tf} == tf, "apply != preview (unsplit)"
    # And back: the unsplit ones retire.
    asyncio.run(_apply(aid, picked, split=True))
    live = asyncio.run(_db_folders(aid))
    topic_live = {n for n in live if n.startswith(("AI-bikini", "AI-toy play"))}
    assert topic_live == set(by_split), sorted(topic_live)


_harness.run(
    case_every_topic_rule_matches_and_misses,
    case_price_split_follows_lane5,
    case_free_guard_keeps_bare_and_unsure_out_of_free,
    case_explicit_ladder,
    case_paid_only_and_free_only_topics,
    case_stale_failed_and_old_video_jev_ignored,
    case_videos_land_and_review_clips_never_free,
    case_topics_whitelist,
    case_unticked_builds_no_topic_folders,
    case_preview_equals_apply_and_mirror,
    case_untick_retires_topic_folders_and_preview_says_so,
    case_split_off_one_folder_per_topic_and_retire,
)
