#!/usr/bin/env python3
"""test_full_ai_spacing — Spacing (phase 03d, ticket 59): the Sitting / Piece / Unasked fold and the
test question list. Pure: hand-built test rows, no DB, no Jev.

  case_spacing_fold          `full_ai_test.spacing_of(rows, now)` over the spec's table (spec ›
                             Contracts › Sitting / Piece / Unasked)
  case_spacing_questions     `_questions("test", scene, spacing)`: the Spacing variant replaces only
                             `offer_moment` and `scene_offer`, `scene_offer` only with the scene,
                             order unchanged; Shadow never changes
  case_flag_off_request_sha  the flag-off test request (questions + state key list) equals the sha
                             captured on origin/main 9718d06e3 before any 03d edit, both scenes
  case_question_versions     `question_version("test")` left its pre-03d value; Shadow's did not

Run: ./venv/bin/python service/tests/test_full_ai_spacing.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import hashlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_test as t  # noqa: E402

T0 = datetime(2026, 11, 14, 20, 0)
NO = "no piece yet"
KEYS = ("his_lines_since_last_piece", "pieces_this_sitting", "unasked_pieces_this_sitting")
# Captured on 9718d06e3 (its `_router_jev.py`, before any 03d edit) with `_flag_off_request`.
FLAG_OFF_TEST_REQUEST_SHA = {
    False: "06b04a892422a5bffe10ed28274d9c90471c73f3f31e29f321dd8899303a0f71",
    True: "30a0de07d24d5090c981c579f9f5475c69a8bd5f5e7b54d58fdf2ed7047d7abc",
}
PRE_03D_TEST_VERSION = "d6d23cee85f2"     # `question_version("test")` on 9718d06e3


def _row(minute: float, route_row: str = "otherwise", *, price=None, kind=None, his=("hey",),
         photo: bool = False, status: str = "sent"):
    """A session row as `send` leaves it, `minute` minutes after T0. `kind` sets the Offer columns
    (`tease` keeps price NULL); a failed / dropped row (`status`) has none, as `send` never ran."""
    offer = dict(offer_item_ref=None, offer_price_cents=None, offer_media_json=None)
    if kind:
        offer = dict(offer_item_ref=json.dumps({"ref": 1, "kind": kind}), offer_price_cents=price,
                     offer_media_json=json.dumps({"locked": [1], "previews": []}))
    reply = {"parts": [{"text": "mm"}]} if status == "sent" else {}
    if photo:
        reply["fan_photo"] = {"text": "", "desc": "a selfie"}
    return SimpleNamespace(created_at=T0 + timedelta(minutes=minute), route_row=route_row,
                           status=status, outcome=None, outcome_at=None,
                           jev_json=json.dumps({"state": {"fan_new_messages": list(his)}}),
                           reply_json=json.dumps(reply), **offer)


def _piece(minute: float, route_row: str = "offer_moment", price: int = 2000):
    return _row(minute, route_row, price=price, kind="offer")


def _want(lines, pieces: int, unasked: int) -> dict:
    return dict(zip(KEYS, (lines, pieces, unasked)))


def case_spacing_fold():
    m = timedelta(minutes=1)
    rows = [   # (label, rows, now minutes after T0, expected)
        ("empty session", [], 0, _want(NO, 0, 0)),
        ("chat only", [_row(0), _row(1)], 2, _want(NO, 0, 0)),
        ("piece then 0 rows", [_row(0), _piece(1)], 2, _want(1, 1, 1)),
        ("piece then 1 row", [_piece(1), _row(2)], 3, _want(2, 1, 1)),
        ("piece then 2 rows", [_piece(1), _row(2), _row(3)], 4, _want(3, 1, 1)),
        ("piece then 3 rows", [_piece(1), _row(2), _row(3), _row(4)], 5, _want(4, 1, 1)),
        ("free item is no piece", [_row(1, "make_right", price=0, kind="free")], 2, _want(NO, 0, 0)),
        ("tease row is no piece", [_row(1, "tease_price", kind="tease")], 2, _want(NO, 0, 0)),
        ("tease follow-through is an asked piece",
         [_row(1, "tease_price", kind="tease"), _piece(2, "sell")], 3, _want(1, 1, 0)),
        ("dropped row: no piece, his line counts",
         [_piece(1), _row(2, "offer_moment", status="no_send")], 3, _want(2, 1, 1)),
        ("failed row: his line counts", [_piece(1), _row(2, status="failed")], 3, _want(2, 1, 1)),
        ("haggle row is an asked piece and resets",
         [_piece(1), _row(2), _piece(3, "haggle")], 4, _want(1, 2, 1)),
        ("sell resets, counts a piece, not unasked",
         [_piece(1), _row(2), _row(3), _piece(4, "sell")], 5, _want(1, 2, 1)),
        ("3 unasked pieces",
         [_piece(1), _row(2), _piece(3, "scene_offer"), _row(4), _piece(5)], 6, _want(1, 3, 3)),
        ("a carried line counts once",
         [_piece(1), _row(2, his=("one", "two"))], 3, _want(2, 1, 1)),
        ("a fan photo counts as one line",
         [_piece(1), _row(2, his=(), photo=True)], 3, _want(2, 1, 1)),
        ("gap 119 min keeps the sitting", [_piece(0), _row(119)], 120, _want(2, 1, 1)),
        ("gap 121 min starts a new sitting", [_piece(0), _row(121)], 122, _want(NO, 0, 0)),
        ("gap 121 min: old pieces out, new ones in",
         [_piece(0), _piece(1), _row(122), _piece(123, "scene_offer")], 124, _want(1, 1, 1)),
        ("now 119 min after the last row", [_piece(0)], 119, _want(1, 1, 1)),
        ("now 121 min after the last row", [_piece(0), _row(1)], 122, _want(NO, 0, 0)),
    ]
    for label, rs, now, want in rows:
        got = t.spacing_of(rs, T0 + now * m)
        assert got == want, (label, got, want)
        assert list(got) == list(KEYS), (label, list(got))


def _wording(q) -> tuple:
    return q.instructions, dict(q.criteria) if isinstance(q.criteria, dict) else list(q.criteria)


def case_spacing_questions():
    assert rj.SPACING_STATE_KEYS == KEYS
    assert set(rj.TEST_SPACING) == {"offer_moment", "scene_offer"}
    # the spec's wording, spot-checked: both read the two counts
    for qid in rj.TEST_SPACING:
        crit = rj.TEST_SPACING[qid]["criteria"]
        assert "`his_lines_since_last_piece` is 3 or more or says no piece yet" in crit["true"], qid
        assert "(`unasked_pieces_this_sitting` is 3 or more)" in crit["false"], qid
        assert rj.TEST_SPACING[qid]["instructions"] == rj.TEST_NOULS[qid]["instructions"], qid
    for scene in (False, True):
        off = rj._questions("test", scene)
        assert rj._questions("test", scene, False).keys() == off.keys()
        on = rj._questions("test", scene, spacing=True)
        assert list(on) == list(off), (scene, list(on), list(off))      # order unchanged
        assert ("scene_offer" in on) is scene, scene
        for qid in on:
            if qid in rj.TEST_SPACING:
                v = rj.TEST_SPACING[qid]
                assert _wording(on[qid]) == (v["instructions"], v["criteria"]), (scene, qid)
                assert _wording(on[qid]) != _wording(off[qid]), (scene, qid)
                assert type(on[qid]).__name__ == "Noul", qid
            else:
                assert on[qid].model_dump() == off[qid].model_dump(), (scene, qid)
        shadow = rj._questions("shadow", scene, spacing=True)
        assert {q: v.model_dump() for q, v in shadow.items()} == \
            {q: v.model_dump() for q, v in rj._questions().items()}, scene


def _flag_off_request(scene: bool) -> str:
    """The flag-off test request: every test question as the SDK serializes it, in request order,
    plus the state's key list (`router.state` then, with the scene, `SCENE_STATE_KEYS`)."""
    d = {"questions": {q: v.model_dump(mode="json") for q, v in rj._questions("test", scene).items()},
         "state_keys": [*rj.state([], [], "", "", "").keys(), *(rj.SCENE_STATE_KEYS if scene else ())]}
    return hashlib.sha256(json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def case_flag_off_request_sha():
    for scene, sha in FLAG_OFF_TEST_REQUEST_SHA.items():
        assert _flag_off_request(scene) == sha, scene


def case_question_versions():
    assert rj.question_version() == rj.question_version("shadow") == rj.QUESTION_VERSION == "b3202b420ab0"
    base = rj.question_version("test")
    assert base != PRE_03D_TEST_VERSION, base
    real = rj.TEST_SPACING
    rj.TEST_SPACING = {**real, "offer_moment": {**real["offer_moment"], "instructions": "x"}}
    try:
        assert rj.question_version("test") != base
        assert rj.question_version() == "b3202b420ab0"
    finally:
        rj.TEST_SPACING = real
    real_keys = rj.SPACING_STATE_KEYS
    rj.SPACING_STATE_KEYS = KEYS[:2]
    try:
        assert rj.question_version("test") != base
        assert rj.question_version() == "b3202b420ab0"
    finally:
        rj.SPACING_STATE_KEYS = real_keys


_harness.run()
