#!/usr/bin/env python3
"""push_notice: SSE frame -> notices, driven by fixtures/notice_cases.json (shared with the app
and desktop ports, design.md B3). Run: venv/bin/python -m pytest service/tests/test_push_notice.py -q"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # pytest: tests/ is a package
import _harness  # noqa: E402,F401  (first: temp DB)  (first: temp DB)

import json
from pathlib import Path

import push_decide as pd  # noqa: E402
import push_notice as pn  # noqa: E402
from types import SimpleNamespace as NS  # noqa: E402

_FX = Path(__file__).parent / "fixtures"
SHARED = json.loads((_FX / "notice_cases.json").read_text())["cases"]       # the app's table
CASES = json.loads((_FX / "notice_cases_relay.json").read_text())["cases"]  # relay-only extras

# lib/notifSettings DEFAULT_NOTIF_SETTINGS.toast; pushTypes = the keys on (enabled && osPing).
_DEFAULT_TOAST = {"message": False, "purchases": True, "tip": True, "subscribed": False,
                  "mentioned": False, "commented": False, "favorited": False}


def _row(n):
    return {"id": n.tag, "typeKey": n.type_key, "title": n.title, "body": n.body, "href": n.href}


def _pushed(c):
    """What the relay pushes for a case: notices_for, then should_push with pushTypes(settings)."""
    s = c.get("settings") or {}
    toast = {**_DEFAULT_TOAST, **(s.get("toast") or {})}
    on = s.get("enabled", True) and s.get("osPing", True)
    sub = NS(types=frozenset(k for k, v in toast.items() if v and on), platforms=s.get("platforms") or {})
    return [_row(n) for n in pn.notices_for(c["frame"])
            if pd.should_push(sub, n, frozenset({n.account_id}), "onlyfans", None)]


def test_shared_fixture_cases():
    bad = [c["name"] for c in SHARED if _pushed(c) != c["expect"]]
    assert not bad, f"mismatch: {bad}"
    assert len(SHARED) >= 15


def test_relay_extra_cases():
    bad = [c["name"] for c in CASES if [_row(n) for n in pn.notices_for(c["frame"])] != c["expect"]]
    assert not bad, f"mismatch: {bad}"
    unknown = next(c for c in CASES if c["name"] == "toast_unknown_type")
    assert _pushed({**unknown, "settings": {"toast": dict.fromkeys(_DEFAULT_TOAST, True)}}) == []


def test_no_account_or_agency_frame():
    dm = CASES[0]["frame"]
    assert pn.notices_for({k: v for k, v in dm.items() if k != "__account_id"}) == []
    assert pn.notices_for({**dm, "__agency": "a1"}) == []
    assert pn.notices_for({"chat_responded": {}, "__account_id": "1"}) == []


def test_body_cap_and_payload():
    long = {"api2_chat_message": {"id": 1, "fromUser": {"id": 9, "name": "T"}, "text": "x" * 500},
            "__account_id": "1"}
    n = pn.notices_for(long)[0]
    assert len(n.body) == pn.BODY_MAX and n.body.endswith("…")
    p = pn.payload(n)
    assert set(p) == {"v", "tag", "title", "body", "href", "type", "account_id", "icon"} and p["v"] == 1
    assert p["tag"] == "1:m1" and p["type"] == "message" and p["account_id"] == "1"
    like = pn.notices_for({"toasts": [{"id": 5, "type": "like", "text": "x"}], "__account_id": "1"})[0]
    assert (like.type_key, pn.payload(like)["type"]) == ("favorited", "like"), "type = the raw OF type"
    test = pn.Notice("test-1", "", "test", "T", "B", "/", "test")
    assert "account_id" not in pn.payload(test) and pn.payload(test)["tag"] == "test-1"
    assert len(json.dumps(p).encode()) < 3072
    big = pn.Notice("2", "1", "message", "T" * 500, "B" * 500, "/messages-pro/1/2?fanTab=" + "x" * 600, "message")
    q = pn.payload(big)
    assert len(q["title"]) == pn.TITLE_MAX and q["title"].endswith("…") and len(q["body"]) == pn.BODY_MAX
    assert q["href"] is None, "an over-long href is dropped, not cut"
    assert pn.payload(n)["href"] == n.href and pn.payload(n)["title"] == n.title
    assert pn.urgency(n) == "normal"
    tip = pn.notices_for(next(c for c in CASES if c["name"] == "tip_dm_5")["frame"])[0]
    assert pn.urgency(tip) == "high"


def test_fmt_price():
    assert [pn.fmt_price(c) for c in (700, 750, 123456, None)] == ["$7", "$7.50", "$1,234.56", "—"]


if __name__ == "__main__":
    import sys
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
