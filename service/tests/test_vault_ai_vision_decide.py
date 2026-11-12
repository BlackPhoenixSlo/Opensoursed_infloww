#!/usr/bin/env python3
"""
vault_ai_vision_decide — table tests over the pure rules the vision passes hand
off (`vault_ai_vision` keeps the DB / frame / LLM side; test_vault_ai_describe
and test_vault_flags_sweep walk that on a DB).

  case_frames_for_duration_table:     the duration ladder.
  case_parse_describe_table:          JSON pulled out of prose, else {}.
  case_next_attempt_table:            30b → 235b ONCE, never past 235b.
  case_describe_selection_table:      the WHOLE where clause (live, describable,
                                      mode), run on a real SQLite table — the
                                      set the sweep walks = the plan's count;
                                      restage re-scans a photo / clip whose
                                      describe was not Jev-fed.
  case_describe_answer_table:         headline fields of an answer.
  case_build_describe_update_table:   locks, carried flags, operator fixes, stamps.
  case_describe_tier_follows_locked_explicitness: tier column = Jev's column_tier.

No DB of the app's, no OF, no LLM. Run: venv/bin/python service/tests/test_vault_ai_vision_decide.py
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import json  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import create_engine, insert, select  # noqa: E402

import vault_ai_vision_decide as d  # noqa: E402
import vault_describe_jev  # noqa: E402
from db.models import VaultItem  # noqa: E402

N = datetime(2026, 10, 30, 12, 0, 0)
FIXABLE = ("clothing_state", "vulva_vis", "acts")


def _table(rows, fn) -> None:
    """Run every row, collect every mismatch, fail once naming them all."""
    bad = [f"{rid}: {got!r} != {want!r}" for rid, args, want in rows if (got := fn(*args)) != want]
    assert not bad, "\n  " + "\n  ".join(bad)


def case_frames_for_duration_table():
    _table([
        ("None", (None,), 6), ("0s", (0,), 6), ("29s", (29,), 6), ("30s", (30,), 9),
        ("179s", (179,), 9), ("180s", (180,), d._FRAME_LADDER_MAX), ("17min", (1020,), 12),
    ], d._frames_for_duration)


def case_parse_describe_table():
    _table([
        ("None", (None,), {}), ("no braces", ("I can't help",), {}),
        ("fenced json", ('```json\n{"description": "x", "tags": ["a"]}\n```',),
         {"description": "x", "tags": ["a"]}),
        ("broken json", ('{"description": ',), {}),
    ], d._parse_describe)


def case_next_attempt_table():
    _table([
        ("30b answered: done", ("qwen3-vl-30b", False), None),
        ("30b refused: escalate to 235b", ("qwen3-vl-30b", True), "qwen3-vl-235b"),
        ("235b refused: stop (once)", ("qwen3-vl-235b", True), None),
        ("235b answered: done", ("qwen3-vl-235b", False), None),
    ], d.next_attempt)


def case_describe_selection_table():
    """Evaluate the WHOLE clause on a real SQLite table, the way both consumers
    do — account, removed_at and kind included, so no caller re-adds them."""
    eng = create_engine("sqlite://")
    VaultItem.__table__.create(eng)
    v2 = json.dumps({"_prompt_version": "v2"})
    v1 = json.dumps({"_prompt_version": "v1"})

    def fed(path):   # a v2-stamped describe row with its `_describe` meta, serialised as the product writes it
        meta = vault_describe_jev.meta(path, {"v": 8, "at": "2026-11-01"}, "qwen3-vl-235b")
        return json.dumps({"_prompt_version": "v2", "_jev": {"v": 8}, "_describe": meta}, ensure_ascii=False)
    rows = [  # media_id, describe_status, ai_fields_json, account, kind, removed
        (1, None, None, "a", "photo", False), (2, "described", v2, "a", "photo", False),
        (3, "described", v1, "a", "video", False), (4, "described", None, "a", "photo", False),
        (5, "blocked_drm", v2, "a", "video", False), (6, "refused", None, "a", "photo", False),
        (7, "described", json.dumps({"x": 1}), "a", "photo", False),
        (8, None, None, "b", "photo", False),      # other account: never
        (9, None, None, "a", "audio", False),      # no frame: never
        (10, None, None, "a", "photo", True),      # gone from OF: never
        (11, "described", fed("prose"), "a", "photo", False),   # Jev-fed: current under restage v2
        (12, "described", fed("vid"), "a", "video", False),
        (13, "described", fed("v6"), "a", "photo", False),
        (14, "described", fed("v2"), "a", "photo", False),      # v2 path: stale whatever its version
    ]
    with eng.begin() as c:
        c.execute(insert(VaultItem), [
            {"account_id": acc, "media_id": m, "kind": kind, "describe_status": st,
             "ai_fields_json": fj, "created_at": N, "removed_at": N if gone else None}
            for m, st, fj, acc, kind, gone in rows])

    def picked(where) -> list[int]:
        q = select(VaultItem.media_id).where(where).order_by(VaultItem.media_id)
        with eng.connect() as c:
            return [r[0] for r in c.execute(q)]

    _table([
        ("live describable base", (d.live_describable("a"),), [1, 2, 3, 4, 5, 6, 7, 11, 12, 13, 14]),
        ("force: every live describable row", (d.describe_selection("a", "force", "v2"),),
         [1, 2, 3, 4, 5, 6, 7, 11, 12, 13, 14]),
        ("undescribed: NULL + every non-described status (blocked_drm too)",
         (d.describe_selection("a", "undescribed", "v2"),), [1, 5, 6]),
        ("restage v2: undescribed + other/no stamp + photo/clip not Jev-fed (2, 14: v2-stamped)",
         (d.describe_selection("a", "restage", "v2"),), [1, 2, 3, 4, 5, 6, 7, 14]),
        ("restage v1: 3 too (a clip, not Jev-fed)", (d.describe_selection("a", "restage", "v1"),),
         [1, 2, 3, 4, 5, 6, 7, 11, 12, 13, 14]),
        ("other account", (d.describe_selection("b", "force", "v2"),), [8]),
    ], picked)
    try:
        d.describe_selection("a", "bogus", "v2")  # type: ignore[arg-type]
    except ValueError:
        pass
    else:
        raise AssertionError("unknown mode accepted")


def case_describe_answer_table():
    _table([
        ("empty", ({},), {"description": "", "tags": [], "explicitness_tier": None,
                         "nsfw": None, "sellable": None}),
        ("normalised", ({"description": "x", "tags": [" Nude ", "", "POV"] + ["t"] * 20,
                         "explicitness": "explicit", "nsfw": 1, "sellable": 0},),
         {"description": "x", "tags": ["nude", "pov"] + ["t"] * 10,
          "explicitness_tier": "explicit", "nsfw": True, "sellable": False}),
    ], d.describe_answer)


def case_build_describe_update_table():
    data = {"description": "she poses", "tags": ["Tease"], "explicitness": "suggestive",
            "sellable": True, "acts": ["posing"], "clothing_state": "dressed",
            "vulva_vis": "bare"}
    prev = {"vulva_vis": "covered", "over_vulva": "thong", "_flags_v": 3, "stale": 1}

    def build(is_video, locked=(), overrides=None, pv="v2"):
        vals = d.build_describe_update(
            is_video, data, prev_ai=prev, locked=set(locked), overrides=overrides or {},
            used_model="qwen3-vl-235b", n_frames=9, pv=pv, fixable=FIXABLE,
            call_id=42, now=N)
        return {**vals, "ai_fields_json": json.loads(vals["ai_fields_json"])}

    # flags are CARRIED from the previous blob (not the describe answer); the
    # rest of the previous blob ("stale") is not.
    ai = {**data, "_prompt_version": "v2", "_frames": 9,
          "vulva_vis": "covered", "over_vulva": "thong", "_flags_v": 3}
    stamps = {"describe_status": "described", "describe_model": "qwen3-vl-235b",
              "describe_call_id": 42, "describe_generated_at": N}
    model_cols = {"tip_vault_flag": True, "tags": '["tease"]',
                  "explicitness_tier": "suggestive",
                  "search_text": "she poses tease posing dressed"}
    photo = {**stamps, **model_cols, "frames_sampled": None,
             "description": "she poses", "ai_fields_json": ai}
    _table([
        ("photo: description column, no frame count", (False,), photo),
        ("video v1: video_description, frames, v1 stamp", (True, (), None, "v1"),
         {**stamps, **model_cols, "frames_sampled": 9, "video_description": "she poses",
          "ai_fields_json": {**ai, "_prompt_version": "v1"}}),
        ("every locked column left alone",
         (False, ["description", "tags", "explicitness_tier", "tip_vault_flag",
                  "search_text"]),
         {**stamps, "frames_sampled": None, "ai_fields_json": ai}),
        ("operator fix: only locked AND fixable; None deletes",
         (False, ["vulva_vis", "acts", "sellable"],
          {"vulva_vis": "bare", "acts": None, "clothing_state": "nude", "sellable": False}),
         # vulva_vis: locked+fixable wins over the carried flag; acts: None deletes;
         # clothing_state: fixable not locked -> model; sellable: locked not fixable -> model
         {**photo, "ai_fields_json": {**{k: v for k, v in ai.items() if k != "acts"},
                                      "vulva_vis": "bare"}}),
    ], build)


def case_describe_tier_follows_locked_explicitness():
    """Beside a current `_jev`, the tier column is `column_tier` of the written blob — an operator-locked
    `explicitness` (FIXABLE) included — so describe and the Jev pass never flip it between them."""
    import vault_jev_flags as jf
    import vault_jev_rules as rules
    assert "explicitness" in __import__("vault_ai_fix").FIXABLE
    jev = {"v": rules.VERSION, "status": "ok", "lane5": "$10", "lane": "$10", "settled": False,
           "breasts_bare": "y", "crotch_bare": "n", "penetration": "n", "tags": {"outfit": "nude"}, "state": {}}
    data = {"description": "d", "explicitness": "explicit"}

    def tier(prev, locked=(), overrides=None):
        vals = d.build_describe_update(
            False, data, prev_ai=prev, locked=set(locked), overrides=overrides or {},
            used_model="m", n_frames=1, pv="v2", fixable=("explicitness",), call_id=None, now=N)
        out = json.loads(vals["ai_fields_json"])
        if jf.TIER_COLUMN in vals and jf.reading(out.get(d.JEV_KEY)) is not None:
            assert vals[jf.TIER_COLUMN] == jf.column_tier(out, None, set(locked)), "describe and Jev disagree"
        return vals.get(jf.TIER_COLUMN, "<untouched>")

    _table([
        ("no reading: the model's tier", ({},), "explicit"),
        ("reading: the blob's explicitness", ({"_jev": jev},), "explicit"),
        ("reading + locked fix: the operator's", ({"_jev": jev}, ["explicitness"], {"explicitness": "suggestive"}),
         "suggestive"),
        ("column locked: untouched", ({"_jev": jev}, [jf.TIER_COLUMN]), "<untouched>"),
    ], tier)


_harness.run()
