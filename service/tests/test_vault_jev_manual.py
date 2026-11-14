#!/usr/bin/env python3
"""
`vault_jev_manual`: an operator's Jev picks over a `_jev` (no scan, or a scanned reading), and the write paths that
lay them (the edit route, `vault_jev_pass._stamp`, the duplicate copy). Plain-assert suite (repo convention).

Cases:
  contract       every lane, photo + video, from NO scan: a blob that is current, reads (flags), prices
                 (`jev_tier`) and is in sync once mapped, but is no AI read (`ai_read`: not fed to a describe)
  scan due       a no-scan item with picks is still selected for Jev (flags todo, clip lane, `one`); the scan fills
                 every unpicked field, picks win; a scanned item + picks is not re-selected; picks alone never a
                 duplicate's source
  ranking        breasts / crotch / penetration picks rank the lane; an unknown verdict keeps a no-scan item manual
  scanned        picks over a golden reading: lane override coerces verdicts, butt never moves the lane, a clip's
                 review cleared by an override and kept by a ranked lane; clearing restores the reading; idempotent
  feet           any feet yes -> feet_any y, feet_subject 1.0, feet_detail in the picture (pack picker gate)
  brief          a described row overridden free -> $50: no contradiction, not disputed
  stamp          a fresh `merge` keeps the picks (`_stamp` re-lays them from the overrides)
  patch          picks persisted, a no-scan item gets a blob, bad option 400, cleared key removed, vis locks dropped
  copy           a copy carries the source's reading under its OWN picks (none: the source's blob as is)
  ts options     the popup's option list is the server's

Run: cd service/tests && PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_jev_manual.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import json  # noqa: E402
from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import vault_ai_api as api  # noqa: E402
import vault_ai_brief  # noqa: E402
import vault_ai_vision  # noqa: E402
import vault_ai_vision_decide as decide  # noqa: E402
import vault_describe_jev as vdj  # noqa: E402
import vault_frames  # noqa: E402
import vault_jev  # noqa: E402
import vault_jev_flags as jf  # noqa: E402
import vault_jev_manual as m  # noqa: E402
import vault_jev_pass  # noqa: E402
import vault_jev_rules as rules  # noqa: E402
import vault_pack_picker as pp  # noqa: E402
from _jev_fixtures import photo_jev, video_jev  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultItem  # noqa: E402

J = rules.JEV_KEY
TIER = {"free": 0, "$10": 10, "$50": 50, "$100": 100}
def scanned(kind: str, lane5: str) -> dict:
    return video_jev(lane5) if kind == "video" else photo_jev(lane5)


def _usable(j: dict, kind: str, lane5: str) -> None:
    f = {J: j}
    assert rules.current(f), j
    assert jf.reading(j) is not None, j
    if j.get("made") == m.MANUAL:   # picks alone: usable, but no Jev reading — the sweeps still scan it
        assert not rules.ai_read(f) and not vdj.feedable(j) and vdj.route(kind=kind, fields=f) == (None, None), j
    else:
        assert rules.ai_read(f) and vdj.feedable(j), j
        assert vdj.route(kind=kind, fields=f)[0] is not None, (kind, j)
    assert pp.jev_tier(j) == TIER[lane5], (lane5, pp.jev_tier(j), j)
    mapped = jf.apply(f, j)
    assert jf.in_sync(mapped, set()), mapped
    assert not vault_ai_brief.is_disputed(mapped), vault_ai_brief.contradictions(mapped)


def case_contract_every_lane_no_scan():
    for kind in rules.JEV_KINDS:
        for lane in m.LANES:
            j = m.overlay(None, {"lane": lane}, kind, at="2026-11-13T00:00:00")
            assert j["lane5"] == lane and j["status"] == "ok" and j["made"] == m.MANUAL, j
            assert set(j["C"]) == set(rules.FACT_CHOICES), j["C"]
            _usable(j, kind, lane)
            if kind == "video":
                assert j["kind"] == "video" and j["vv"] == rules.VIDEO_VERSION and j["frames"] == [], j
        # body picks rank a lane too
        for picks, lane in (({"breasts": "bare"}, "$10"), ({"crotch": "bare"}, "$50"),
                            ({"penetration": "y"}, "$100"),
                            ({"breasts": "sexy_covered", "crotch": "normal_covered", "penetration": "n"}, "free")):
            j = m.overlay(None, picks, kind)
            assert j["lane5"] == lane, (picks, j)
            _usable(j, kind, lane)
        assert m.overlay(None, {"breasts": "sexy_covered", "crotch": "hidden_not_worn", "penetration": "n"},
                         kind)["lane"] == "implied"


def case_no_lane_is_manual_not_current():
    j = m.overlay(None, {"outfit": "nude", "feet_focus": "y"}, "photo")
    assert j["status"] == m.MANUAL and "lane5" not in j and not rules.current({J: j}), j
    assert jf.reading(j) is None and vdj.route(kind="photo", fields={J: j}) == (None, None)
    assert j["C"]["outfit"]["nude"] == 1.0 and j["tags"]["outfit"] == "nude", j
    # breasts covered alone: crotch / penetration unknown -> no lane
    assert m.overlay(None, {"breasts": "normal_covered"}, "photo")["status"] == m.MANUAL
    # the sweep reads it later: the reading replaces the skeleton, the picks stay laid over it
    read = photo_jev("free")
    j2 = m.overlay(read, {"outfit": "nude", "feet_focus": "y"}, "photo")
    assert j2["status"] == "ok" and j2["tags"]["outfit"] == "nude" and "made" not in j2, j2
    assert m.overlay(None, {}, "photo") is None and m.overlay(j, {}, "photo") is None


def case_check_options_from_jev():
    assert m.options("breasts") == tuple(vault_jev.Q["breasts_state_a"]["criteria"])
    assert m.options("feet_detail") == tuple(vault_jev.Q["feet_detail_a"]["criteria"])
    assert set(m.options("butt")) == {"bare", "sexy_covered", "normal_covered", "sheer_covered", "hidden_not_worn",
                                      "not_visible"}
    assert m.check({"breasts": "bare", "lane": None, "watermark": "n"}) == {"breasts": "bare", "lane": None,
                                                                            "watermark": "n"}
    for bad in ({"breasts": "covered"}, {"lane": "$20"}, {"watermark": "yes"}, {"nope": "y"}, ["breasts"]):
        try:
            m.check(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def case_ts_options_match():
    """The popup's option list (`app/components/vault/jevPicks.ts`) is `vault_jev_manual.options`, key for key."""
    import re
    src = (Path(__file__).resolve().parents[2] / "app" / "components" / "vault" / "jevPicks.ts").read_text()
    consts = {"STATES": m.options("breasts"), "YN": m.YES_NO}
    body = src[src.index("JEV_OPTIONS = {"):src.index("} as const satisfies")]
    got = {}
    for k, v in re.findall(r"^\s*(\w+): (\[[^\]]*\]|\w+),", body, re.M):
        got[k] = tuple(consts[v]) if v in consts else tuple(re.findall(r'"([^"]+)"', v))
    assert set(got) == set(m.KEYS), set(got) ^ set(m.KEYS)
    for k in m.KEYS:
        assert set(got[k]) == set(m.options(k)), (k, got[k], m.options(k))


def case_scanned_override_rank_butt_clear():
    for kind in rules.JEV_KINDS:
        read = scanned(kind, "free")
        j = m.overlay(read, {"lane": "$50"}, kind)
        assert j["lane5"] == "$50" and j["crotch_bare"] == "y" and j["op"] == ["lane"], j
        assert j["ai"] == {"lane": "free"} and j["at"] == read["at"], j
        _usable(j, kind, "$50")
        free = m.overlay(scanned(kind, "$10"), {"lane": "free"}, kind)
        assert (free["breasts_bare"], free["crotch_bare"], free["penetration"]) == ("n", "n", "n"), free
        _usable(free, kind, "free")
        # butt never moves the lane
        b = m.overlay(read, {"butt": "bare"}, kind)
        assert b["lane5"] == read["lane5"] and b["state"]["butt"] == "bare" and b["tags"]["butt_bare"] == "y", b
        # clearing every pick gives the reading back; laying twice is laying once
        assert m.overlay(j, {}, kind) == read
        assert m.overlay(m.overlay(read, {"lane": "$50", "outfit": "nude"}, kind), {"lane": "$50"}, kind) == j
        assert m.overlay(j, {"lane": "$50"}, kind) == j
    # a clip whose reading may be too low: an override clears it, a ranked lane keeps it unknown-priced
    rv = video_jev("free", review="no_720")
    assert rv["lane5"] == "review"
    o = m.overlay(rv, {"lane": "$10"}, "video")
    assert o["lane5"] == "$10" and o["review"] is None and "read_lane5" not in o, o
    _usable(o, "video", "$10")
    r = m.overlay(rv, {"crotch": "bare"}, "video")
    assert r["lane5"] == "review" and r["read_lane5"] == "$50" and r["review"] == "no_720", r
    assert pp.jev_tier(r) is None and jf.reading(r)["vulva_vis"] == "bare"
    assert m.overlay(r, {}, "video") == rv


def case_feet_invariant():
    for base in (None, photo_jev("free")):
        j = m.overlay(base, {"lane": "free", "wears_socks": "y"}, "photo")
        t = j["tags"]
        assert t["feet_any"] == "y" and t["feet_detail"] != "not_in_picture" and j["feet_subject"] == 1.0, j
        assert base is not None or t["feet_detail"] == "socks", t
        assert t["wears_socks"] == "y" and j["P"]["wears_socks"] == 1.0
        d = m.overlay(base, {"lane": "free", "feet_detail": "heels"}, "photo")["tags"]
        assert d["feet_any"] == "y" and d["feet_detail5"] == "shoes", d
        n = m.overlay(base, {"lane": "free", "feet_detail": "not_in_picture"}, "photo")["tags"]
        assert n["feet_any"] == "n", n


def case_brief_free_to_50_not_disputed():
    read = photo_jev("free")
    row = jf.apply({"description": "d", "acts": ["posing"], "penetration": "none",
                    "clothing_items": ["bra", "panties"], J: read}, read)
    assert not vault_ai_brief.contradictions(row), vault_ai_brief.contradictions(row)
    j = m.overlay(read, {"lane": "$50"}, "photo")
    row2 = jf.apply({**row, J: j}, j)
    assert row2["vulva_vis"] == "bare" and row2["explicitness"] == "explicit", row2
    assert vault_ai_brief.contradictions(row2) == [] and not vault_ai_brief.is_disputed(row2), row2


_N = 0


async def _seed(*, kind="photo", ai=None, overrides=None, locked=None, tier=None) -> tuple[str, int]:
    global _N
    _N += 1
    aid = f"acc_jevm_{_N}"
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(VaultItem(account_id=aid, media_id=1, kind=kind, created_at=datetime(2026, 11, 1),
                        ai_fields_json=json.dumps(ai or {}), explicitness_tier=tier,
                        operator_overrides_json=json.dumps(overrides) if overrides else None,
                        locked_fields_json=json.dumps(locked) if locked else None))
        await s.commit()
    return aid, 1


async def _row(aid: str) -> VaultItem:
    async with get_session() as s:
        return await s.get(VaultItem, (aid, 1))


async def case_stamp_keeps_picks_after_merge():
    for kind in rules.JEV_KINDS:
        picks = {"lane": "$100", "outfit": "nude"}
        aid, mid = await _seed(kind=kind, ai={J: m.overlay(None, {"outfit": "nude"}, kind)},
                               overrides={m.PICKS_KEY: picks})
        fresh = scanned(kind, "free")
        await vault_jev_pass._stamp(aid, mid, vault_jev.JevResult(ok=True, status="ok", blob=fresh))
        it = await _row(aid)
        f = json.loads(it.ai_fields_json)
        j = f[J]
        assert j["lane5"] == "$100" and j["tags"]["outfit"] == "nude" and j["op"] == ["lane", "outfit"], j
        assert "made" not in j and j["at"] == fresh["at"], j
        assert f["explicitness"] == "hardcore" and it.explicitness_tier == "hardcore", (f, it.explicitness_tier)
        assert jf.row_in_sync(it.ai_fields_json, it.locked_fields_json, tier=it.explicitness_tier)
        # a failed re-read keeps the picks too, and the picked lane keeps it a reading
        await vault_jev_pass._stamp(aid, mid, vault_jev.JevResult(ok=False, status="error", detail="x"))
        it = await _row(aid)
        j = json.loads(it.ai_fields_json)[J]
        assert j["status"] == "ok" and j["lane5"] == "$100" and j["op"] == ["lane", "outfit"], j
        assert jf.row_in_sync(it.ai_fields_json, it.locked_fields_json, tier=it.explicitness_tier)


async def case_hold_keeps_picks():
    aid, mid = await _seed(kind="video", ai={J: m.overlay(video_jev("free"), {"lane": "$50"}, "video")},
                           overrides={m.PICKS_KEY: {"lane": "$50"}})
    await vault_jev_pass._hold(aid, mid, 1, "brief", terminal=False)
    j = json.loads((await _row(aid)).ai_fields_json)[J]
    assert j["status"] == "ok" and j["lane5"] == "$50" and j["op"] == ["lane"] and not j["review"], j
    # no lane known: the hold stands (retried)
    aid, mid = await _seed(kind="video", ai={J: m.overlay(video_jev("free"), {"outfit": "nude"}, "video")},
                           overrides={m.PICKS_KEY: {"outfit": "nude"}})
    await vault_jev_pass._hold(aid, mid, 1, "brief", terminal=False)
    j = json.loads((await _row(aid)).ai_fields_json)[J]
    assert j["status"] == "fetch_failed" and j["lane5"] == "review" and j["tags"]["outfit"] == "nude", j


async def _patch(aid, fields):
    return await api.edit_item(1, {"account_id": aid, "fields": fields})


async def case_patch_picks():
    # no scan: a lane builds a blob, the flags + tier follow
    aid, _ = await _seed(locked=["breasts_vis", "explicitness_tier", "description"],
                         overrides={"breasts_vis": "covered", "explicitness_tier": "suggestive"}, tier="suggestive")
    res = await _patch(aid, {"jev": {"lane": "$10", "watermark": "y"}})
    it = await _row(aid)
    ov = json.loads(it.operator_overrides_json)
    assert ov[m.PICKS_KEY] == {"lane": "$10", "watermark": "y"}, ov
    assert "breasts_vis" not in ov and "explicitness_tier" not in ov, ov
    locked = set(json.loads(it.locked_fields_json))
    assert locked == {"description"}, locked
    f = json.loads(it.ai_fields_json)
    assert f[J]["lane5"] == "$10" and f["breasts_vis"] == "bare" and it.explicitness_tier == "explicit", f
    assert res["item"]["jev_picks"] == {"lane": "$10", "watermark": "y"}, res["item"]
    assert res["item"]["fields"][J]["lane5"] == "$10"
    assert jf.row_in_sync(it.ai_fields_json, it.locked_fields_json, tier=it.explicitness_tier)
    # a cleared key is removed; a non-body pick leaves the locks alone
    await _patch(aid, {"jev": {"lane": None}})
    it = await _row(aid)
    assert json.loads(it.operator_overrides_json)[m.PICKS_KEY] == {"watermark": "y"}
    j = json.loads(it.ai_fields_json)[J]
    assert j["status"] == m.MANUAL and not rules.current({J: j}), j
    await _patch(aid, {"jev": {"watermark": None}})
    it = await _row(aid)
    assert m.PICKS_KEY not in json.loads(it.operator_overrides_json)
    assert J not in json.loads(it.ai_fields_json)
    # review #5: taking back a reading the picks alone made leaves the tier unknown too
    assert (await _row(aid)).explicitness_tier is None
    # review #4: a tier set in the same edit as a lane stays the operator's, locked
    aid2, _ = await _seed(ai={J: photo_jev("free")})
    await _patch(aid2, {"jev": {"lane": "$50"}, "explicitness_tier": "graphic"})
    it2 = await _row(aid2)
    assert it2.explicitness_tier == "graphic" and "explicitness_tier" in json.loads(it2.locked_fields_json)
    assert json.loads(it2.operator_overrides_json)["explicitness_tier"] == "graphic"
    # bad option / key -> 400, nothing written
    for bad in ({"jev": {"breasts": "covered"}}, {"jev": {"lane": "review"}}, {"jev": "x"}):
        try:
            await _patch(aid, bad)
        except HTTPException as e:
            assert e.status_code == 400, e
            continue
        raise AssertionError(bad)
    # scanned item: a body pick re-ranks and drops the vis locks
    aid, _ = await _seed(ai={J: photo_jev("free")}, locked=["vulva_vis"], overrides={"vulva_vis": "covered"})
    await _patch(aid, {"jev": {"crotch": "bare"}})
    it = await _row(aid)
    f = json.loads(it.ai_fields_json)
    assert f[J]["lane5"] == "$50" and f["vulva_vis"] == "bare", f
    assert "vulva_vis" not in json.loads(it.locked_fields_json or "[]")
    assert it.explicitness_tier == "explicit"


def case_failed_reading_lane_pick_is_current():
    """Review #3: a failed re-read (fields kept) + a lane pick maps; clearing gives the failed blob back."""
    for st in ("error", "fetch_failed"):
        failed = {**photo_jev("free"), "status": st, "error": "x"}
        j = m.overlay(failed, {"lane": "$100"}, "photo")
        _usable(j, "photo", "$100")
        assert m.overlay(j, {}, "photo") == failed
        ranked = m.overlay(failed, {"crotch": "bare"}, "photo")
        assert ranked["status"] == "ok" and ranked["lane5"] == "$50", ranked
        assert m.overlay(failed, {"outfit": "nude"}, "photo")["status"] == st


def case_copy_keeps_own_picks():
    """A copy carries the source's reading (its `at`, so a copied describe matches) under its OWN picks; a copy
    with none takes the source's blob as is; a source without a good answer leaves the copy's own."""
    src = {J: photo_jev("$10")}
    own = m.overlay(photo_jev("free"), {"lane": "$50"}, "photo")
    got = decide.jev_for_copy(src, {J: own}, {"lane": "$50"})
    assert got["lane5"] == "$50" and got["at"] == src[J]["at"] and got["ai"] == {"lane": "$10"}, got
    manual = m.overlay(None, {"outfit": "nude"}, "photo")
    got = decide.jev_for_copy(src, {J: manual}, {"outfit": "nude"})
    assert got["status"] == "ok" and got["lane5"] == "$10" and got["tags"]["outfit"] == "nude", got
    assert vdj.feedable(got) and "made" not in got
    # review #2: a copy without picks holds the source's AI reading, not its picks
    picked_src = {J: m.overlay(photo_jev("$10"), {"lane": "$100"}, "photo")}
    bare = decide.jev_for_copy(picked_src, {J: manual})
    assert bare == photo_jev("$10") and "op" not in bare and "undo" not in bare, bare
    assert m.overlay(bare, {"outfit": "nude"}, "photo")["lane5"] == "$10"
    assert decide.jev_for_copy({J: {"status": "error"}}, {J: own}, {"lane": "$50"}) is own
    # through the copy builders: the flags follow the copy's picks
    f = decide.build_flags_copy({J: manual}, jf.apply({**src}, src[J]), locked=set(), src_id=7,
                                picks={"lane": "free"})
    assert f[J]["lane5"] == "free" and f["breasts_vis"] != "bare", f
    # review #1: the describe copy re-maps flags + tier from the copy's picked `_jev`
    s_ai = jf.apply({"description": "d", "clothing_items": ["bra"], J: src[J]}, src[J])
    srow = {"ai_fields_json": json.dumps(s_ai), "explicitness_tier": "explicit", "describe_model": "x",
            "description": "d", "tags": "[]"}
    v = decide.build_copy_update(srow, prev_ai={}, locked=set(), overrides={m.PICKS_KEY: {"lane": "$100"}},
                                 fixable=(), src_id=7, now=datetime(2026, 11, 13))
    ai = json.loads(v["ai_fields_json"])
    assert ai[J]["lane5"] == "$100" and ai["anus_vis"] == "bare" and v["explicitness_tier"] == "hardcore", ai
    assert jf.row_in_sync(v["ai_fields_json"], "[]", tier=v["explicitness_tier"])
    v = decide.build_copy_update(srow, prev_ai={}, locked={"explicitness_tier"},
                                 overrides={m.PICKS_KEY: {"lane": "$100"}}, fixable=(), src_id=7,
                                 now=datetime(2026, 11, 13))
    assert "explicitness_tier" not in v, v


class _FakeScan:
    """`vault_jev_pass.one`'s seams: ready, a still / clip frames, and a Jev reading of `blob` (calls counted)."""

    def __init__(self, blob: dict):
        self.blob, self.calls = blob, 0

    def __enter__(self):
        self.saved = (vault_jev.preflight, vault_jev.run, vault_jev.run_video,
                      vault_frames.collect, vault_frames.collect_jev_video)

        async def _ready(*_a, **_k):
            return None

        async def _run(*_a, **_k):
            self.calls += 1
            return vault_jev.JevResult(ok=True, status="ok", blob=json.loads(json.dumps(self.blob)))

        async def _still(*_a, **_k):
            return SimpleNamespace(images=["data:image/jpeg;base64,AAAA"], reason="ok", detail="")

        async def _clip(*_a, **_k):
            return vault_frames.JevFrames(frames=[b"x"], reason="ok", src="720")

        vault_jev.preflight, vault_jev.run, vault_jev.run_video = _ready, _run, _run
        vault_frames.collect, vault_frames.collect_jev_video = _still, _clip
        return self

    def __exit__(self, *_):
        (vault_jev.preflight, vault_jev.run, vault_jev.run_video,
         vault_frames.collect, vault_frames.collect_jev_video) = self.saved


async def _due(aid: str, kind: str) -> bool:
    todo = 1 in await vault_ai_vision._flags_todo(aid)
    if kind == "video":
        assert (1 in await vault_jev_pass.clips_due(aid)) == todo
    return todo


async def case_scan_due_fills_unpicked():
    """Owner: picks alone still get the Jev scan; it fills every field not picked, the picks win."""
    for kind in rules.JEV_KINDS:
        picks = {"lane": "$100", "outfit": "nude"}
        aid, mid = await _seed(kind=kind)
        await _patch(aid, {"jev": picks})
        it = await _row(aid)
        f = json.loads(it.ai_fields_json)
        manual = f[J]
        assert manual["made"] == m.MANUAL and rules.current(f) and not rules.ai_read(f), manual
        assert it.explicitness_tier == "hardcore" and pp.jev_tier(manual) == 100   # consumers use it meanwhile
        assert await _due(aid, kind)
        fresh = scanned(kind, "free")
        unpicked = {k: v for k, v in fresh["tags"].items() if k not in manual["tags"]}
        assert unpicked and fresh["tags"].get("outfit") != "nude", fresh["tags"]
        with _FakeScan(fresh) as scan:
            res = await vault_jev_pass.one(aid, mid)
            assert res is not None and res["ok"] and scan.calls == 1, res
            it = await _row(aid)
            f = json.loads(it.ai_fields_json)
            j = f[J]
            assert rules.ai_read(f) and "made" not in j and j["at"] == fresh["at"], j
            assert j["lane5"] == "$100" and j["tags"]["outfit"] == "nude" and j["op"] == ["lane", "outfit"], j
            assert {k: j["tags"][k] for k in unpicked} == unpicked, j["tags"]
            assert j["ai"]["lane"] == fresh["lane5"] and j["C"]["setting"] == fresh["C"]["setting"], j
            assert it.explicitness_tier == "hardcore" and vdj.feedable(j)
            assert jf.row_in_sync(it.ai_fields_json, it.locked_fields_json, tier=it.explicitness_tier)
            # read now: not selected again, no second call
            assert not await _due(aid, kind)
            assert await vault_jev_pass.one(aid, mid) is None and scan.calls == 1


async def case_scanned_then_picked_not_rescanned():
    for kind in rules.JEV_KINDS:
        aid, mid = await _seed(kind=kind)
        await vault_jev_pass._stamp(aid, mid, vault_jev.JevResult(ok=True, status="ok", blob=scanned(kind, "$10")))
        await _patch(aid, {"jev": {"lane": "free", "watermark": "y"}})
        j = json.loads((await _row(aid)).ai_fields_json)[J]
        assert j["lane5"] == "free" and "made" not in j and rules.ai_read({J: j}), j
        assert not await _due(aid, kind)
        with _FakeScan(scanned(kind, "$50")) as scan:
            assert await vault_jev_pass.one(aid, mid) is None and scan.calls == 0


def case_picks_alone_not_a_reuse_source():
    rows = []
    for mid, jev in ((1, m.overlay(None, {"lane": "$50"}, "photo")), (2, photo_jev("$50"))):
        f = jf.apply({J: jev}, jev)
        rows.append((mid, "described", f, "photo", None, jf.column_tier(f, None, set())))
    done, _ = decide.reuse_state(rows, flags=True, flags_version=vault_ai_vision._FLAGS_VERSION)
    assert done == {2}, done


_harness.run()
