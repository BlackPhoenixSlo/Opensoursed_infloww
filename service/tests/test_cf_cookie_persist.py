#!/usr/bin/env python3
"""Cloudflare cookies from OF responses persist into the session file (S16).

The live curl session already keeps `__cf_bm` / `_cfuvid` / `cf_clearance`
from Set-Cookie, but the session file never got them: every client rebuilt
from disk (pool eviction, proxy edit, restart) replayed the capture-time
values, `__cf_bm` having a 30-minute TTL — a silent 403 source after idle.
Pins: a changed CF cookie is written back (value + expiry) through a fresh
0600 temp file and an atomic replace; an existing row is updated in place,
matched on name AND domain; an unchanged value and non-CF cookies cause no
write; a client not built from a file never writes; and the signing-rules
writer (sign_rules) goes through the same locked re-read, so neither
writer's change is lost to the other.

Run:  ./venv/bin/python service/tests/test_cf_cookie_persist.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from curl_cffi.requests import Cookies  # noqa: E402

from of_client import OFClient  # noqa: E402

_SESSION = {
    "headers": {"user_id": "8001", "x_bc": "bc", "x_of_rev": "rev", "user_agent": "ua"},
    "signing": {"rules": {"static_param": "s", "start": "1", "end": "2",
                          "checksum_indexes": [1], "checksum_constant": 1}},
    "cookies": [
        {"name": "sess", "value": "abc", "domain": ".onlyfans.com", "path": "/"},
        {"name": "__cf_bm", "value": "old", "domain": ".onlyfans.com", "path": "/"},
    ],
}


class _Resp:
    def __init__(self, _domain=".onlyfans.com", **cookies):
        self.cookies = Cookies()
        for name, value in cookies.items():
            self.cookies.set(name, value, domain=_domain)


def _session_file(mode: int = 0o600) -> Path:
    d = Path(tempfile.mkdtemp(prefix="cfcookie_")) / "8001"
    d.mkdir()
    p = d / "session_1.json"
    p.write_text(json.dumps(_SESSION))
    os.chmod(p, mode)
    return p


def _cookies(p: Path) -> dict:
    return {c["name"]: c["value"] for c in json.loads(p.read_text())["cookies"]}


def case_changed_cf_cookies_written_back():
    p = _session_file()
    client = OFClient.from_session_file(p, proxies=None)
    client._persist_cf_cookies(_Resp(__cf_bm="new", cf_clearance="clr", sess="rotated"))
    got = _cookies(p)
    assert got["__cf_bm"] == "new", got
    assert got["cf_clearance"] == "clr", got
    assert got["sess"] == "abc", "only Cloudflare's cookies are written back"
    assert sum(1 for c in json.loads(p.read_text())["cookies"] if c["name"] == "__cf_bm") == 1
    assert os.stat(p).st_mode & 0o777 == 0o600, oct(os.stat(p).st_mode)
    assert json.loads(p.read_text())["headers"]["user_id"] == "8001", "rest of the file kept"


def case_unchanged_value_does_not_write():
    p = _session_file()
    client = OFClient.from_session_file(p, proxies=None)
    mtime = os.stat(p).st_mtime_ns
    client._persist_cf_cookies(_Resp(__cf_bm="old"))   # what the file already holds
    client._persist_cf_cookies(_Resp(sess="x"))        # no CF cookie at all
    assert os.stat(p).st_mtime_ns == mtime, "no-op responses must not rewrite the file"
    client._persist_cf_cookies(_Resp(__cf_bm="v2"))
    mtime = os.stat(p).st_mtime_ns
    client._persist_cf_cookies(_Resp(__cf_bm="v2"))    # same value twice: one write
    assert os.stat(p).st_mtime_ns == mtime


def case_rebuilt_client_starts_warm():
    p = _session_file()
    OFClient.from_session_file(p, proxies=None)._persist_cf_cookies(_Resp(__cf_bm="fresh"))
    rebuilt = OFClient.from_session_file(p, proxies=None)
    assert rebuilt.http.cookies.get("__cf_bm", domain=".onlyfans.com") == "fresh"


def case_written_0600_via_temp_file_whatever_the_old_mode():
    p = _session_file(0o644)
    OFClient.from_session_file(p, proxies=None)._persist_cf_cookies(_Resp(__cf_bm="n"))
    assert os.stat(p).st_mode & 0o777 == 0o600, oct(os.stat(p).st_mode)
    assert sorted(os.listdir(p.parent)) == ["session_1.json"], "temp file left behind"


def case_cookies_match_on_name_and_domain():
    p = _session_file()
    client = OFClient.from_session_file(p, proxies=None)
    client._persist_cf_cookies(_Resp("cdn.example.net", __cf_bm="cdn"))
    rows = [c for c in json.loads(p.read_text())["cookies"] if c["name"] == "__cf_bm"]
    by_domain = {c["domain"]: c["value"] for c in rows}
    assert by_domain == {".onlyfans.com": "old", "cdn.example.net": "cdn"}, by_domain
    client._persist_cf_cookies(_Resp("onlyfans.com", __cf_bm="main"))  # host-only form
    rows = [c for c in json.loads(p.read_text())["cookies"] if c["name"] == "__cf_bm"]
    assert {c["domain"]: c["value"] for c in rows} == {
        ".onlyfans.com": "main", "cdn.example.net": "cdn"}, rows


def case_rules_writer_and_cookie_writer_keep_each_other():
    from of_client import update_session_file
    p = _session_file()
    client = OFClient.from_session_file(p, proxies=None)
    client._persist_cf_cookies(_Resp(__cf_bm="live"))

    def _set_rules(data):            # what sign_rules writes back
        data["signing"]["rules"]["checksum_constant"] = 42
    update_session_file(p, _set_rules)
    client._persist_cf_cookies(_Resp(cf_clearance="clr"))
    data = json.loads(p.read_text())
    assert data["signing"]["rules"]["checksum_constant"] == 42, "cookie write lost the rules"
    assert _cookies(p)["__cf_bm"] == "live" and _cookies(p)["cf_clearance"] == "clr"


def case_failed_write_leaves_old_file_and_no_temp():
    from of_client import update_session_file
    p = _session_file()
    before = p.read_text()

    def _unserializable(data):
        data["boom"] = object()       # json.dump fails mid-write
    try:
        update_session_file(p, _unserializable)
        raise AssertionError("an unserializable session must raise")
    except TypeError:
        pass
    assert p.read_text() == before, "a failed write must leave the old file"
    assert sorted(os.listdir(p.parent)) == ["session_1.json"], os.listdir(p.parent)


def case_client_without_file_never_writes():
    client = OFClient(_SESSION)
    client._persist_cf_cookies(_Resp(__cf_bm="x"))   # must neither raise nor write
    assert client.session_path is None


_harness.run()
