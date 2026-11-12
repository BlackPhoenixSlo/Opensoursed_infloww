#!/usr/bin/env python3
"""
Build AI folders' opt-in "Topic folders (Jev)" (`vault_topic_folders` + `vault_scripts.plan_ai_folders(topics=)`).
Plain-assert, no pytest (repo convention).

Cases:
  case_every_topic_rule_matches_and_misses:
      each of the 18 non-feet topics takes its planted Jev answer and refuses a near miss.
  case_price_split_follows_lane5:
      a split topic lands in free / $10 / $50 / $100 by `lane5`; review or unknown → no folder.
  case_free_guard_keeps_bare_and_unsure_out_of_free:
      a lane5-free item with breasts / crotch / penetration "y" or "unsure" is in NO free split.
  case_paid_only_and_free_only_topics:
      toy play is never free; good morning and clean for promo are never paid.
  case_feet_rungs_are_the_pack_pickers_preselect:
      the `feet` topic makes AI-feet tease / nude / nude-body from `vault_pack_picker.jev_pick` (score .59 out,
      .6 in; the picker's constant read live); group "feet".
  case_feet_tease_free_guard:
      AI-feet tease never holds a y / unsure / missing body answer, even with the picker's tier rule off.
  case_stale_failed_and_video_jev_ignored:
      only a current, ok `_jev` on a photo counts.
  case_topics_whitelist:
      parse_topics de-dups, canonicalises order, takes a comma string or a list; unknown → ValueError;
      both routes answer 422.
  case_unticked_builds_no_topic_folders:
      no topics = the plan the build made before; the catalogue and Jev coverage still come back.
  case_preview_equals_apply_and_mirror:
      the apply (through the route, OF mirror on) creates exactly the previewed topic folders, same members
      and order, and pushes them to OF under the same names.
  case_untick_retires_topic_folders_and_preview_says_so:
      a later build without the topic shows its folders under `retired` and retires them.

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
             "multi_panel")
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
)
TOY_PLAY = ("toy_play", dict(toy="toy_touching_or_inserted"), dict(toy="toy_visible_not_in_use"))


def case_every_topic_rule_matches_and_misses() -> None:
    assert {s for s, _, _ in RULES} | {"toy_play", "feet"} == set(vt.SLUGS) and len(vt.SLUGS) == 19
    for slug, hit, miss in RULES:
        assert vt.split(_t(slug), jev("free", **hit)) == "free", slug
        assert vt.split(_t(slug), jev("free", **miss)) is None, slug
    slug, hit, miss = TOY_PLAY
    assert vt.split(_t(slug), jev("$50", **hit)) == "$50"
    assert vt.split(_t(slug), jev("$50", **miss)) is None
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
    # The guard only bites free: a paid item may of course be bare.
    assert vt.split(_t("bikini"), jev("$10", bb="y", outfit="swimwear")) == "$10"


def case_paid_only_and_free_only_topics() -> None:
    toy = dict(toy="toy_touching_or_inserted")
    assert vt.split(_t("toy_play"), jev("free", **toy)) is None
    for p in ("$10", "$50", "$100"):
        assert vt.split(_t("toy_play"), jev(p, **toy)) == p
    gm = dict(yes=("smiling", "looking_at_camera"), setting="bedroom")
    cp = dict(added_text="nothing_added")
    for p in ("$10", "$50", "$100"):
        assert vt.split(_t("good_morning"), jev(p, **gm)) is None
        assert vt.split(_t("clean_promo"), jev(p, **cp)) is None
    assert vt.split(_t("clean_promo"), jev("free", **cp)) == "free"


def feet(feet_subject: float, lane5: str = "free", detail: str = "socks", *, seen: str = "y", **body) -> dict:
    """A `_jev` with the feet answers the pack picker reads (feet_subject, feet_any, feet_detail)."""
    j = jev(lane5, **body)
    j["feet_subject"] = feet_subject
    j["P"].update(feet_focus=feet_subject)
    j["tags"].update(feet_any=seen, feet_detail=detail, feet_focus="y" if seen == "y" and feet_subject >= .4 else "n")
    return j


def case_feet_rungs_are_the_pack_pickers_preselect() -> None:
    """AI-feet: score >= FEET_PRESELECT_SCORE only (.59 out, .6 in), rung = `vault_pack_picker.jev_pick`'s."""
    import vault_pack_picker as vp
    t = _t("feet")
    assert (t.price, t.group) == ("rung", "feet") and vt.splits(t) == ("tease", "nude", "nude-body")
    assert [vt.folder_name(t, r) for r in vt.splits(t)] == ["feet tease", "feet nude", "feet nude-body"]
    assert vt.split(t, feet(.6)) == "tease" and vt.split(t, feet(.59)) is None
    assert vt.split(t, feet(.6, detail="bare")) == "nude"
    for lane5 in ("$10", "$50", "$100"):
        assert vt.split(t, feet(.9, lane5, bb="y")) == "nude-body", lane5
    assert vt.split(t, feet(.9, seen="n")) is None
    assert vt.split(t, feet(.9, detail="not_in_picture")) is None
    assert vt.split(t, feet(.9, "review")) is None
    feet_cat = vp.category("feet")
    for j in (feet(.6), feet(.59), feet(.9, detail="bare"), feet(.9, "$50"), feet(.9, bb="unsure")):
        assert vt.split(t, j) == vp.jev_pick(feet_cat, j)
    # The threshold is the pack picker's one constant, read at call time (never copied).
    real = vp.FEET_PRESELECT_SCORE
    vp.FEET_PRESELECT_SCORE = .5
    try:
        assert vt.split(t, feet(.55)) == "tease"
    finally:
        vp.FEET_PRESELECT_SCORE = real
    # Other topics never see the feet group.
    assert {x.group for x in vt.TOPICS if x.slug != "feet"} == {"topics"}


def case_feet_tease_free_guard() -> None:
    """AI-feet tease (the free preview rung): only lane5 free with breasts / crotch / penetration all "n". Its own
    `free_ok` check holds even if the pack picker's tier rule ever let one through."""
    import vault_pack_picker as vp
    t = _t("feet")
    for k in ("bb", "cb", "pen"):
        for v in ("y", "unsure", None):
            assert vt.split(t, feet(.95, **{k: v})) is None, (k, v)
            assert vt.split(t, feet(.95, detail="bare", **{k: v})) is None, (k, v)
    real = vp.jev_tier
    vp.jev_tier = lambda j: 0 if j.get("lane5") == "free" else real(j)   # the picker's guard off
    try:
        assert vp.jev_pick(vp.category("feet"), feet(.95, bb="unsure")) == "tease"
        assert vt.split(t, feet(.95, bb="unsure")) is None, "AI-feet tease must guard on its own"
    finally:
        vp.jev_tier = real


def _row(mid: int, j: dict | None, kind: str = "photo") -> dict:
    return {"media_id": mid, "kind": kind, "fields": {"_jev": j} if j is not None else {}}


def case_stale_failed_and_video_jev_ignored() -> None:
    hit = dict(outfit="swimwear")
    stale = {**jev(**hit), "v": "v7"}
    failed = {**jev(**hit), "status": "error"}
    rows = [_row(1, jev(**hit)), _row(2, stale), _row(3, failed), _row(4, jev(**hit), "video"), _row(5, None)]
    got = vt.assign(rows, ["bikini"])
    assert {k: [r["media_id"] for r in v] for k, v in got.items()} == {("bikini", "free"): [1]}
    assert vt.coverage(rows) == {"photos": 4, "with_jev": 1}
    cat = {c["slug"]: c["count"] for c in vt.catalogue(rows)}
    assert cat["bikini"] == 1 and sum(cat.values()) == 1 and len(cat) == 19


def case_topics_whitelist() -> None:
    assert vt.parse_topics(None) == [] and vt.parse_topics("") == [] and vt.parse_topics([]) == []
    assert vt.parse_topics("toy_play, heels_stockings,toy_play") == ["heels_stockings", "toy_play"]
    assert vt.parse_topics(["bikini", "spread"]) == ["spread", "bikini"]
    try:
        vt.parse_topics(["bikini", "toes", "nope"])
        raise AssertionError("unknown slug accepted")
    except ValueError as e:
        assert e.args[0] == ["nope", "toes"]
    aid = _aid()
    asyncio.run(_seed(aid, []))
    for call in (
        lambda: vault_of_folders.get_folder_plan(account_id=aid, keep=0, solo=False, topics="bikini,toes"),
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
    v[910] = feet(.95)                                        # AI-feet tease
    v[911] = feet(.6, detail="bare")                          # AI-feet nude (at the threshold)
    v[912] = feet(.9, "$50", cb="y")                          # AI-feet nude-body
    v[913] = feet(.59)                                        # below the threshold: nowhere
    v[914] = feet(.95, bb="unsure")                           # unsafe: never tease, nowhere
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
            s.add(VaultItem(account_id=aid, media_id=mid, kind="photo",
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
    assert plan["jev"] == {"enabled": True, "photos": len(_vault()), "with_jev": len(_vault()) - 1}, plan["jev"]
    cat = {c["slug"]: c["count"] for c in plan["topic_catalogue"]}
    assert set(cat) == set(vt.SLUGS)
    # split topics: 4 prices; free-only: 1; toy play: its $50 + toy tease's $50 / $100 are not toy play.
    assert cat["bikini"] == 4 and cat["good_morning"] == 1 and cat["clean_promo"] == 1 and cat["toy_play"] == 1, cat
    assert cat["feet"] == 3, cat
    assert {c["slug"]: c["group"] for c in plan["topic_catalogue"]}["feet"] == "feet"
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


async def _apply(aid: str, topics: list[str], fake: _FakeOF | None = None) -> dict:
    import automation_executor as ax
    orig = ax._make_client
    if fake is not None:
        ax._make_client = lambda *_a, **_k: fake
    before = asyncio.all_tasks()
    try:
        res = await vault_of_folders.apply_folder_plan(
            {"account_id": aid, "confirm": True, "keep": 0, "topics": topics, "mirror_to_of": fake is not None})
    finally:
        ax._make_client = orig
    await asyncio.wait_for(asyncio.gather(*(asyncio.all_tasks() - before)), timeout=10)
    return res


def case_preview_equals_apply_and_mirror() -> None:
    aid = _aid()
    v = _vault()
    asyncio.run(_seed(aid, list(v.items())))
    picked = ["bikini", "toy_play", "clean_promo", "feet"]
    plan = asyncio.run(vault_of_folders.get_folder_plan(account_id=aid, keep=0, solo=False,
                                                        topics="clean_promo,feet,toy_play,bikini"))
    tf = _topic_folders(plan)
    assert plan["topics"] == ["toy_play", "bikini", "clean_promo", "feet"]
    assert set(tf) == {"AI-bikini free", "AI-bikini $10", "AI-bikini $50", "AI-bikini $100",
                       "AI-toy play $50", "AI-clean for promo free",
                       "AI-feet tease", "AI-feet nude", "AI-feet nude-body"}, sorted(tf)
    assert (tf["AI-feet tease"], tf["AI-feet nude"], tf["AI-feet nude-body"]) == ([910], [911], [912]), tf
    every = {m for ids in tf.values() for m in ids}
    assert not every & {900, 901, 902, 913, 914}, "review / guarded / no-Jev / sub-threshold item in a topic folder"
    assert vt.free_ok(v[910]) and all(vt.free_ok(v[m]) for m in tf["AI-feet tease"])
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


_harness.run(
    case_every_topic_rule_matches_and_misses,
    case_price_split_follows_lane5,
    case_free_guard_keeps_bare_and_unsure_out_of_free,
    case_paid_only_and_free_only_topics,
    case_feet_rungs_are_the_pack_pickers_preselect,
    case_feet_tease_free_guard,
    case_stale_failed_and_video_jev_ignored,
    case_topics_whitelist,
    case_unticked_builds_no_topic_folders,
    case_preview_equals_apply_and_mirror,
    case_untick_retires_topic_folders_and_preview_says_so,
)
