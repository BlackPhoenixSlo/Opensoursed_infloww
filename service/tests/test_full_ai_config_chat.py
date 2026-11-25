#!/usr/bin/env python3
from __future__ import annotations

import _harness

from _full_ai_fixtures import GIF_FITS
from _full_ai_chat_helpers import (
    A, NANO, OPENROUTER, OWNER_A, _GIF_TAG, _body, _chain_post, _direct, _post, _reply, _rows,
    _store_config,
)
from automations import full_ai_test
from automations.full_ai_config import DEFAULTS



CONFIG = "/admin/full-ai/config"


def _put_draft(draft: dict) -> int:
    rev = OWNER_A.get(CONFIG, params={"account_id": A}).json()["rev"]
    r = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": draft, "rev": rev})
    assert r.status_code == 200, r.text
    return r.json()["rev"]


def case_draft_turn_after_put_carries_its_rev():
    try:
        rev = _put_draft({**DEFAULTS, "writers": ["hermes-4-405b", "euryale-v2.3"]})
        assert rev >= 1, rev
        pair = "p-cfg-rev"
        ck, ck_w = _chain_post(_body(pair), {})
        dr, dr_w = _chain_post(_body(pair, side="draft"), {})
        assert (ck.json()["writer"], dr.json()["writer"]) == ("euryale-v2.3", "hermes-4-405b"), (
            ck.json(), dr.json())
        assert ([x["host"] for x in ck_w.requests], [x["host"] for x in dr_w.requests]) == (
            [NANO], [OPENROUTER])
        rows = _rows(A, pair)
        assert [(_reply(x)["side"], _reply(x)["config_rev"]) for x in rows] == [
            ("checkpoint", rev), ("draft", rev)], [_reply(x) for x in rows]
    finally:
        _store_config(A, {})


def case_draft_follows_its_side_only():
    try:
        pair, his = "p-cfg-style", "so what are you up to"
        raw = "omg hii. i was literally just thinking about u. what are u up to tonight? tell me everything"
        _put_draft({**DEFAULTS, "text_style": "formal"})
        ck, *_ = _post(OWNER_A, _body(pair, text=his), f"ok:{raw}")
        dr, *_ = _post(OWNER_A, _body(pair, text=his, side="draft"), f"ok:{raw}")
        fid = full_ai_test.test_fan_id(pair)
        assert ck.json()["parts"] == _direct(raw, fid, his, girl=True), ck.json()["parts"]
        assert dr.json()["parts"] == _direct(raw, fid, his, girl=False), dr.json()["parts"]
        assert ck.json()["parts"] != dr.json()["parts"]
        pair = "p-cfg-gif"
        _put_draft({**DEFAULTS, "gifs": True})
        line = f"ok:omg ur funny\nSTICKER: {_GIF_TAG}"
        ck, *_ = _post(OWNER_A, _body(pair), line, jev=(GIF_FITS, 1.0))
        dr, *_ = _post(OWNER_A, _body(pair, side="draft"), line, jev=(GIF_FITS, 1.0))
        assert ck.json()["parts"] and all(set(p) == {"text"} for p in ck.json()["parts"]), ck.json()
        assert set(dr.json()["parts"][-1]) == {"gif", "tag"}, dr.json()["parts"]
        assert dr.json()["parts"][-1]["tag"] == _GIF_TAG, dr.json()["parts"]
        pair = "p-cfg-speed"
        _put_draft({**DEFAULTS, "reply_speed": "0-15-60"})
        ck, *_ = _post(OWNER_A, _body(pair), "ok:mm hey")
        dr, *_ = _post(OWNER_A, _body(pair, side="draft"), "ok:mm hey")
        assert 0 <= ck.json()["wait_s"] <= 120, ck.json()["wait_s"]
        assert 120 < dr.json()["wait_s"] <= 3600, dr.json()["wait_s"]
    finally:
        _store_config(A, {})


if __name__ == "__main__":
    _harness.run()
