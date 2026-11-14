#!/usr/bin/env python3
"""test_full_ai_config_chat — Full AI Test chat: checkpoint and draft (phase 03a, ticket 37; split
from test_full_ai_test_chat.py).

Shared setup (seeded Agencies, owner clients, `_guarded`, `_post`, the Writer fakes) is
`_full_ai_chat_helpers.py`; every Turn runs inside `_guarded` as in test_full_ai_test_chat.py.

  case_draft_turn_after_put_carries_its_rev
  case_draft_follows_its_side_only

Run: ./venv/bin/python service/tests/test_full_ai_config_chat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_chat_helpers import (
    A, NANO, OPENROUTER, OWNER_A, _GIF_TAG, _body, _chain_post, _direct, _post, _reply, _rows,
    _store_config,
)
from automations import full_ai_test
from automations.full_ai_config import DEFAULTS


# ── Checkpoint and draft (ticket 37) ──────────────────────────────────

CONFIG = "/admin/full-ai/config"


def _put_draft(draft: dict) -> int:
    """`draft` stored as Creator A's draft through the config API, as the page stores it; the new rev."""
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
        # text_style formal: the draft's parts are the formal chain's, the checkpoint's the girl's.
        pair, his = "p-cfg-style", "so what are you up to"
        raw = "omg hii. i was literally just thinking about u. what are u up to tonight? tell me everything"
        _put_draft({**DEFAULTS, "text_style": "formal"})
        ck, *_ = _post(OWNER_A, _body(pair, text=his), f"ok:{raw}")
        dr, *_ = _post(OWNER_A, _body(pair, text=his, side="draft"), f"ok:{raw}")
        fid = full_ai_test.test_fan_id(pair)
        assert ck.json()["parts"] == _direct(raw, fid, his, girl=True), ck.json()["parts"]
        assert dr.json()["parts"] == _direct(raw, fid, his, girl=False), dr.json()["parts"]
        assert ck.json()["parts"] != dr.json()["parts"]
        # gifs on in the draft only: the same STICKER reply carries a gif part there alone.
        pair = "p-cfg-gif"
        _put_draft({**DEFAULTS, "gifs": True})
        line = f"ok:omg ur funny\nSTICKER: {_GIF_TAG}"
        ck, *_ = _post(OWNER_A, _body(pair), line)
        dr, *_ = _post(OWNER_A, _body(pair, side="draft"), line)
        assert ck.json()["parts"] and all(set(p) == {"text"} for p in ck.json()["parts"]), ck.json()
        assert set(dr.json()["parts"][-1]) == {"gif", "tag"}, dr.json()["parts"]
        assert dr.json()["parts"][-1]["tag"] == _GIF_TAG, dr.json()["parts"]
        # reply_speed "0-15-60" in the draft: its wait in that preset's 0-60 min, the checkpoint's in 0-2 min.
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
