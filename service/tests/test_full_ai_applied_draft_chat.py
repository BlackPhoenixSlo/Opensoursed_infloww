#!/usr/bin/env python3
from __future__ import annotations

import _harness

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
        assert [(_reply(x)["side"], _reply(x)["config_rev"]) for x in rows] == [
            ("draft", new_rev), ("checkpoint", new_rev)], [_reply(x) for x in rows]
        assert all(x.mode == "test" for x in rows), [x.mode for x in rows]
        assert 0 <= ck.json()["wait_s"] <= 120, ck.json()["wait_s"]
        assert 120 < dr.json()["wait_s"] <= 3600, dr.json()["wait_s"]
    finally:
        _store_config(A, {})


if __name__ == "__main__":
    _harness.run()
