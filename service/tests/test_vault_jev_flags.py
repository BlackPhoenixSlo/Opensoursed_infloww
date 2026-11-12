#!/usr/bin/env python3
"""
`vault_jev_flags`: a photo's flags (and the describe lane fields) read off its `_jev`, in the shape every consumer
reads. Plain-assert suite (repo convention), pure: no DB writes, no network.

Cases:
  reading table      lane5 (+ breasts_bare / crotch_bare / outfit / state) -> flags + clothing / underwear /
                     genitals_covered / explicitness; None for anything not a current, settled reading
  version            FLAGS_V == vault_ai_vision._FLAGS_VERSION (the version consumers require)
  apply / in_sync    flags replaced, qwen garment names + clip stamps + failure record cleared, operator locks
                     kept, `_flags_model` "jev"; a non-reading leaves the row alone; in_sync ignores a copy mark
  consumers          a Jev-mapped photo row (every golden describe blob + a lane x outfit x state grid) passes
                     flags_current / flags_known, has no contradictions (settled_reading is the row, never
                     disputed), and vault_scripts prices it at Jev's lane: shelf_price $100/$50 -> 50, $10 -> 10,
                     free -> 0 (mass lane), the two price lanes never both

Run: cd service/tests && PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_jev_flags.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import gzip  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

import vault_ai_brief  # noqa: E402
import vault_ai_vision  # noqa: E402
import vault_ai_vision_decide as decide  # noqa: E402
import vault_describe_jev as vdj  # noqa: E402
import vault_jev_flags as jf  # noqa: E402
import vault_jev_rules as rules  # noqa: E402
import vault_scripts  # noqa: E402

GOLD = json.load(gzip.open(Path(__file__).parent / "fixtures" / "vault_describe_jev" / "golden.json.gz", "rt"))
for _c in GOLD["cases"]:   # bench blobs predate the stored region states: empty = every hidden region covered
    _c["jev"].setdefault("state", {})
SHELF = {"$100": 50, "$50": 50, "$10": 10, "free": 0}


def _jev(lane5, bb="n", cb="n", outfit="lingerie_or_bodysuit", state=None, **kw) -> dict:
    """state None: a v8 blob whose region states name nothing (every hidden region reads covered)."""
    return {"v": rules.VERSION, "status": "ok", "lane5": lane5, "lane": lane5, "settled": False,
            "breasts_bare": bb, "crotch_bare": cb, "penetration": "y" if lane5 == "$100" else "n",
            "tags": {"outfit": outfit}, "state": state or {}, **kw}


def _flags(r: dict) -> tuple:
    return (r["breasts_vis"], r["vulva_vis"], r["anus_vis"], r["underwear_visible"], r["clothing_state"],
            r["genitals_covered"], r["explicitness"])


def case_reading_table():
    out = {"breasts": "not_visible", "crotch": "not_visible", "butt": "not_visible"}
    PD, PA, PO = (vault_ai_brief._CLOTHING_FOR[k] for k in ((True, False), (False, True), (True, True)))
    rows = [
        ("$10 topless", _jev("$10", "y", outfit="topless_with_bottoms"),
         ("bare", "covered", "covered", True, PD, True, "explicit")),
        ("$10, nude tag (labia hidden)", _jev("$10", "y", outfit="nude"),
         ("bare", "covered", "covered", True, PD, True, "explicit")),
        ("$50 vulva only", _jev("$50", "n", "y"), ("covered", "bare", "covered", True, PA, False, "explicit")),
        ("$50 both", _jev("$50", "y", "y"), ("bare", "bare", "covered", True, PO, False, "explicit")),
        ("$50 nude", _jev("$50", "y", "y", outfit="nude"),
         ("bare", "bare", "covered", False, "fully_nude", False, "explicit")),
        ("$100 vulva", _jev("$100", "y", "y", outfit="nude"),
         ("bare", "bare", "covered", False, "fully_nude", False, "hardcore")),
        ("$100 crotch unsure", _jev("$100", "n", "unsure"), ("covered", "bare", "covered", True, PA, False, "hardcore")),
        ("$100 anus (crotch not bare)", _jev("$100", "n", "n"),
         ("covered", "not_in_frame", "bare", True, PA, True, "hardcore")),
        ("$100 anus, thong on", _jev("$100", "n", "n", state={"crotch": "sexy_covered"}),
         ("covered", "covered", "bare", True, PA, True, "hardcore")),
        ("free lingerie", _jev("free"), ("covered", "covered", "covered", True, "lingerie_on", True, "suggestive")),
        ("free dressed, out of frame", _jev("free", outfit="everyday_clothes", state=out),
         ("not_in_frame", "not_in_frame", "not_in_frame", False, "dressed", True, "suggestive")),
        ("free nude from behind", _jev("free", outfit="nude"),
         ("covered", "covered", "covered", False, "fully_nude", False, "suggestive")),
        ("free, unknown outfit", _jev("free", outfit="?"),
         ("covered", "covered", "covered", False, "unclear", True, "suggestive")),
        ("free swimwear", _jev("free", outfit="swimwear"),
         ("covered", "covered", "covered", True, "lingerie_on", True, "suggestive")),
    ]
    bad = [(rid, _flags(jf.reading(j)), want) for rid, j, want in rows if _flags(jf.reading(j)) != want]
    assert not bad, bad
    for rid, j in [("errored", {**_jev("$10"), "status": "error"}), ("stale", {**_jev("$10"), "v": "v7"}),
                   ("no lane5", {k: v for k, v in _jev("$10").items() if k != "lane5"}),
                   ("review lane5", _jev("review")), ("None", None), ("junk", "x"),
                   ("refused", {"v": rules.VERSION, "status": "no_key"})]:
        assert jf.reading(j) is None, rid


def case_version():
    assert jf.FLAGS_V == vault_ai_vision._FLAGS_VERSION


def case_apply_and_in_sync():
    j = _jev("$10", "y")
    prev = {"description": "d", "breasts_vis": "covered", "vulva_vis": "covered", "anus_vis": "covered",
            "underwear_visible": True, "over_breasts": "red bra", "over_vulva": "thong", "_flags_v": 3,
            "_flags_model": "qwen3-vl-30b", "_flags_frames": 3, "_flags_status": "error", "_flags_error": "x",
            "_flags_copied_from": 9, "clothing_state": "lingerie_on", "_jev": j}
    got = jf.apply(prev, j)
    assert got["breasts_vis"] == "bare" and got["_flags_model"] == "jev" and got["_flags_v"] == jf.FLAGS_V
    assert not {"over_breasts", "over_vulva", "_flags_frames", "_flags_status", "_flags_error",
                "_flags_copied_from"} & set(got), got
    r = jf.reading(j)
    assert got["description"] == "d", "describe prose untouched"
    # the lane fields are the reading's too (a qwen-described photo's tier never sits beside Jev's flags)
    assert all(got[k] == r[k] for k in ("clothing_state", "genitals_covered", "explicitness")), got
    assert got["clothing_state"] != "lingerie_on" and got["explicitness"] == "explicit", got
    assert prev["over_breasts"] == "red bra", "apply mutated its input"
    assert jf.in_sync(got, ()) and not jf.in_sync(prev, ())
    assert jf.in_sync({**got, "_flags_copied_from": 7}, ()), "a dupe copy mark is not drift"
    assert not jf.in_sync({**got, "breasts_vis": "covered"}, ())
    assert not jf.in_sync({**got, "over_breasts": "bra"}, ())
    # an operator-locked flag keeps its value, and in_sync honours the lock
    locked = jf.apply(prev, j, locked={"breasts_vis", "over_breasts"})
    assert locked["breasts_vis"] == "covered" and locked["over_breasts"] == "red bra", locked
    assert jf.in_sync(locked, {"breasts_vis", "over_breasts"}) and not jf.in_sync(locked, ())
    # a lane field is drift like a flag (in_sync requires it), and a locked one stays the operator's
    assert not jf.in_sync({**got, "explicitness": "suggestive"}, ())
    lk = jf.apply({**prev, "explicitness": "softcore"}, j, locked={"explicitness"})
    assert lk["explicitness"] == "softcore" and jf.in_sync(lk, {"explicitness"}), lk
    # row_in_sync reads the locks off the row's own column (text or parsed), so no caller can drop them
    assert jf.row_in_sync(json.dumps(locked), json.dumps(["breasts_vis", "over_breasts"]))
    assert jf.row_in_sync(locked, ["breasts_vis", "over_breasts"]) and not jf.row_in_sync(json.dumps(locked), None)
    # a v8 blob without `state` (stored before the region states) is not current: no reading, the photo re-runs
    nostate = {k: v for k, v in j.items() if k != "state"}
    assert not rules.current({"_jev": nostate}) and jf.reading(nostate) is None
    assert not jf.in_sync({**jf.apply(prev, j), "_jev": nostate}, ())
    # not a reading: the row is left exactly as it was
    for bad in (None, {**j, "status": "error"}):
        assert jf.apply(prev, bad) == prev and jf.apply(prev, bad) is not prev
        assert not jf.in_sync({**prev, "_jev": bad}, ())


def case_garments_from_clothing_items():
    """Garment names (`over_`) come from the describe's clothing_items, only over a region the reading calls covered,
    only an item that can cover it; none for a nude reading or an undescribed photo."""
    dressed = jf.reading(_jev("free", outfit="everyday_clothes"))
    items = ["gold necklace", "white tank top", "blue jeans"]
    assert jf.garments(dressed, items) == {"over_breasts": "white tank top", "over_vulva": "blue jeans",
                                           "over_anus": "blue jeans"}
    assert jf.garments(dressed, None) == {} and jf.garments(dressed, []) == {}
    topless = jf.reading(_jev("$10", "y", outfit="topless_with_bottoms"))
    got = jf.garments(topless, ["black lace bra", "bikini top", "black thong"])
    assert got == {"over_vulva": "black thong", "over_anus": "black thong"}, got   # breasts bare: unnamed
    assert jf.garments(dressed, ["red bodysuit"])["over_breasts"] == "red bodysuit"
    assert jf.garments(dressed, ["pink string bra"]) == {"over_breasts": "pink string bra"}   # never over the vulva
    nude = jf.reading(_jev("free", outfit="nude"))
    assert jf.garments(nude, ["white tank top"]) == {}
    # apply names them; the row then reads as wearing something (vault_scripts._is_nude: a dressed photo is not nude)
    row = jf.apply({"clothing_items": items, "_jev": _jev("free", outfit="everyday_clothes")},
                   _jev("free", outfit="everyday_clothes"))
    assert row["over_breasts"] == "white tank top" and jf.in_sync(row, ()), row
    assert vault_ai_brief.wearing_something(row) and not vault_scripts._is_nude(row)
    assert not jf.in_sync({**row, "over_breasts": None}, ()), "a described photo missing its garment names is drift"
    # a locked garment name keeps its value
    lk = jf.apply({**row, "over_breasts": "green hoodie"}, row["_jev"], locked={"over_breasts"})
    assert lk["over_breasts"] == "green hoodie"
    # two-piece: each half covers its own region only, whatever the order; a bare "bikini" is the bottom half
    low = {"over_vulva": "black bikini bottom", "over_anus": "black bikini bottom"}
    for two in (["black bikini bottom", "black bikini top"], ["black bikini top", "black bikini bottom"]):
        assert jf.garments(dressed, two) == {"over_breasts": "black bikini top", **low}, two
    assert jf.garments(dressed, ["black bikini bottom"]) == low
    assert jf.garments(dressed, ["red bikini"]) == {"over_vulva": "red bikini", "over_anus": "red bikini"}
    assert set(jf.garments(dressed, ["swimsuit bottoms"])) == {"over_vulva", "over_anus"}
    assert set(jf.garments(dressed, ["black one-piece swimsuit"])) == {"over_breasts", "over_vulva", "over_anus"}
    assert set(jf.garments(dressed, ["red g-string"])) == {"over_vulva", "over_anus"}
    assert jf.garments(dressed, ["white crop top"]) == {"over_breasts": "white crop top"}


def case_stale_qwen_tiers_replaced():
    """A photo qwen described before Jev (describe-all `undescribed` never re-describes it): the Jev flags sync
    replaces its tier / clothing too, so a Jev $50 row never keeps qwen's `suggestive` (the mass lane) beside Jev's
    bare vulva."""
    old = {"description": "lace set", "explicitness": "suggestive", "clothing_state": "lingerie_on",
           "genitals_covered": True, "clothing_items": ["black lace bra", "black thong"], "underwear_visible": True,
           "_flags_v": 3, "_flags_model": "qwen3-vl-30b", **{k: "covered" for k in vault_ai_brief.VIS_REGIONS}}
    tier = lambda f: vault_ai_brief.sellability(f)["tier"]   # noqa: E731
    assert vault_scripts._lane_mass({"tier": tier(old)}, old, "photo"), "fixture: qwen's row is mass-lane"
    j = _jev("$50")
    row = jf.apply({**old, "_jev": j}, j)
    assert row["explicitness"] == "explicit" and row["genitals_covered"] is False and row["vulva_vis"] == "bare"
    assert tier(row) == "explicit" and not vault_scripts._lane_mass({"tier": tier(row)}, row, "photo")
    _consumers_ok(row, "$50", "stale qwen")
    assert not jf.in_sync({**row, "explicitness": "suggestive"}, ()), "a stale tier is drift: the sweep re-stamps"


def _consumers_ok(row: dict, lane5: str, rid) -> None:
    assert decide.flags_current(row, vault_ai_vision._FLAGS_VERSION), rid
    assert vault_ai_brief.flags_known(row), rid
    assert vault_ai_brief.contradictions(row) == [], (rid, vault_ai_brief.contradictions(row))
    assert vault_ai_brief.settled_reading(row) is row and not vault_ai_brief.is_disputed(row), rid
    assert vault_scripts.shelf_price(row, "photo") == SHELF[lane5], (rid, lane5, vault_scripts.shelf_price(row, "photo"))
    why = vault_scripts.send_order_reason(row)
    t10, t50 = (vault_scripts._lane_tease_10(why, row, "photo"), vault_scripts._lane_tease_50(why, row, "photo"))
    assert not (t10 and t50), rid
    if lane5 == "free":
        assert vault_scripts._lane_mass(why, row, "photo"), (rid, why)


def case_consumers_golden_describes():
    """Every golden describe blob (both paths), stamped by the Jev pass: the row the sweep leaves behind."""
    seen = set()
    for c in GOLD["cases"]:
        j = c["jev"]
        ans = (vdj.prose_answer if c["path"] == "prose" else vdj.v6_answer)(c["parsed"], j)
        row = jf.apply({**ans, "_jev": j}, j)
        _consumers_ok(row, j["lane5"], (c["key"], c["run"], c["path"]))
        seen.add((c["path"], j["lane5"]))
    assert {("prose", "$10"), ("prose", "$50"), ("prose", "$100"), ("prose", "free"), ("v6", "free")} <= seen, seen


def case_consumers_grid():
    """Every lane x bare answer x outfit x state, with the lane fields + acts describe would write."""
    states = (None, {"breasts": "not_visible", "crotch": "not_visible", "butt": "not_visible"},
              {"breasts": "sexy_covered", "crotch": "normal_covered", "butt": "bare"})
    outfits = ("nude", "lingerie_or_bodysuit", "topless_with_bottoms", "everyday_clothes", "swimwear",
               "sheet_or_towel", "?")
    wardrobes = ([], ["black lace bra", "black lace thong"], ["white tank top", "blue jeans"], ["red bodysuit"])
    n = 0
    for lane5, bb, cb, outfit, st, worn in itertools.product(SHELF, "yn", ("y", "n", "unsure"), outfits, states,
                                                             wardrobes):
        if lane5 == "$100" and cb == "n" and st and st.get("crotch") == "normal_covered":
            continue   # an insertion under a garment over the vulva is no shelf reveal (covered: tested above)
        j = _jev(lane5, bb, cb, outfit, st)
        r = jf.reading(j)
        describe = {**{k: r[k] for k in vdj.LANE_FIELDS}, "description": "x", "tags": [], "clothing_items": worn,
                    "acts": ["toy_insertion"] if lane5 == "$100" else ["posing"],
                    "penetration": "toy" if lane5 == "$100" else "none", "people_count": 1}
        _consumers_ok(jf.apply({**describe, "_jev": j}, j), lane5, (lane5, bb, cb, outfit, st, worn))
        n += 1
    assert n > 1600, n


_harness.run()
