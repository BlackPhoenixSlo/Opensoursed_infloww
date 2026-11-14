#!/usr/bin/env python3
"""test_full_ai_applied_draft_chat — an assistant Apply reaches the draft Test chat window (phase
03c, ticket 57; spec › Testing Decisions › Assistant round trip, last step).

"reply slower" through Do mode (model faked at the wire, OF at `client_pool.get`), Apply = the
page's rev-checked draft PUT, then one Test chat Turn per side through 03a's test-turn route under
`_guarded`: the draft side's row carries the new rev and `side: "draft"` and waits on 0-15-60; the
checkpoint side's row carries `side: "checkpoint"`, the same stored rev (one counter for the whole
config, as `test_full_ai_config_chat.py` pins) and waits on the checkpoint's 0-2m. Temp DB only.
ASSUMPTION: the ticket's "checkpoint's rev" read as that stored rev: the server keeps no per-side rev, so which
config the checkpoint side ran on is proven by its wait range instead (overturned by a per-side rev in the row).

  case_apply_then_one_turn_per_side

Run: ./venv/bin/python service/tests/test_full_ai_applied_draft_chat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import copy  # noqa: E402
import json  # noqa: E402

from _full_ai_chat_helpers import (  # noqa: E402
    A, DEEPSEEK, OWNER_A, _agency_keys, _body, _guarded, _of_fake, _post, _reply, _rows, _store_config,
)
from _full_ai_fixtures import FakeWriterHTTP  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402

CONFIG = "/admin/full-ai/config"
SEED = {"checkpoint": {**DEFAULTS}, "previous": None, "draft": {**DEFAULTS}, "rev": 4}


def case_apply_then_one_turn_per_side():
    _store_config(A, copy.deepcopy(SEED))
    try:
        intent = {"flow": "full_ai_config", "config": {"set": {"reply_speed": "0-15-60"}},
                  "assumptions": [], "unresolved": []}
        fake_w = FakeWriterHTTP({DEEPSEEK: "ok:" + json.dumps(intent)})
        with _agency_keys({"deepseek": "test-deepseek-agency-key"}), _guarded(), fake_w.on(), _of_fake() as of:
            r = OWNER_A.post("/admin/assistant/draft", json={"request": "reply slower", "account_id": A})
        assert r.status_code == 200, r.text
        # Do mode makes the existing lists read only; nothing else reaches OF.
        assert set(of.calls) <= {f"get:{A}", "get_lists"} and "get_lists" in of.calls, of.calls
        slots = r.json()["slots"]
        assert (slots["rev"], slots["after"]["reply_speed"]) == (4, "0-15-60"), slots
        r = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": slots["after"], "rev": slots["rev"]})
        assert r.status_code == 200, r.text
        new_rev = r.json()["rev"]
        assert new_rev == 5 and r.json()["checkpoint"]["reply_speed"] == "0-2m", r.json()

        pair = "p-applied-draft"
        ck, *_ = _post(OWNER_A, _body(pair), "ok:mm hey")
        dr, *_ = _post(OWNER_A, _body(pair, side="draft"), "ok:mm hey")
        assert (ck.status_code, dr.status_code) == (200, 200), (ck.text, dr.text)
        rows = sorted(_rows(A, pair), key=lambda x: x.id, reverse=True)[:2]
        # The ticket's side-effect query: newest two test rows, (side, config_rev).
        assert [(_reply(x)["side"], _reply(x)["config_rev"]) for x in rows] == [
            ("draft", new_rev), ("checkpoint", new_rev)], [_reply(x) for x in rows]
        assert all(x.mode == "test" for x in rows), [x.mode for x in rows]
        # Each side ran on its own config: the draft's 0-15-60 wait, the checkpoint's 0-2m one.
        assert 0 <= ck.json()["wait_s"] <= 120, ck.json()["wait_s"]
        assert 120 < dr.json()["wait_s"] <= 3600, dr.json()["wait_s"]
    finally:
        _store_config(A, {})


if __name__ == "__main__":
    _harness.run()
