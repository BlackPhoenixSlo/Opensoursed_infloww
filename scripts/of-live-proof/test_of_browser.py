import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from of_browser import (CaptureBrowser, CaptureBrowserStop, SessionDead, cookie_rows, fetch_problems,
                        hand_off_problems, identity_problem, load_session, probe_verdict, seed_items, seed_script,
                        session_leaks, session_secrets)
from proof_core import READS, critical_capture_refused
from proofs import ALL

CREATOR = "900000000000000001"
X_BC = "bc0123456789abcdef0123456789abcdef012345"
COOKIE = "sess-value-0123456789"
STORED = "stored-token-abcdefgh"


def _session_dir(tmp_path, local_storage=None):
    d = tmp_path / "accounts" / CREATOR
    d.mkdir(parents=True)
    (d / "session_20261120T000000Z.json").write_text(json.dumps({
        "headers": {"user_id": CREATOR, "x_bc": X_BC, "x_of_rev": "r", "user_agent": "UA/1"},
        "signing": {"static_param": "s"},
        "cookies": [{"name": "sess", "value": COOKIE, "domain": ".onlyfans.com", "path": "/"},
                    {"name": "auth_id", "value": CREATOR, "domain": ".onlyfans.com", "path": "/", "expires": -1}],
        "local_storage": {"someKey": STORED} if local_storage is None else local_storage}))
    (d / "latest.json").write_text(json.dumps({"session": "session_20261120T000000Z.json", "ts": "x"}))
    return d



def test_load_session_reads_the_current_session_file(tmp_path):
    s = load_session(_session_dir(tmp_path))
    assert (s["user_id"], s["x_bc"], s["user_agent"]) == (CREATOR, X_BC, "UA/1")
    assert [c["name"] for c in s["cookies"]] == ["sess", "auth_id"] and s["local_storage"] == {"someKey": STORED}


def test_seed_sets_bctokensha_to_x_bc_plus_every_stored_key(tmp_path):
    s = load_session(_session_dir(tmp_path))
    assert seed_items(s) == {"someKey": STORED, "bcTokenSha": X_BC}
    js = seed_script(seed_items(s), ("onlyfans.com", "127.0.0.1"))
    assert '"onlyfans.com"' in js and X_BC in js and "localStorage.getItem(k) === null" in js


def test_cookie_rows_live_keep_domain_and_drop_session_expiry_fake_bind_to_the_fake_origin(tmp_path):
    s = load_session(_session_dir(tmp_path))
    live = cookie_rows(s["cookies"], None)
    assert live[0]["domain"] == ".onlyfans.com" and "expires" not in live[1]
    assert cookie_rows(s["cookies"], "http://127.0.0.1:9") == [
        {"name": "sess", "value": COOKIE, "url": "http://127.0.0.1:9"},
        {"name": "auth_id", "value": CREATOR, "url": "http://127.0.0.1:9"}]


@pytest.mark.parametrize("status, body, want", [
    (200, {"id": CREATOR}, "ok"),
    (400, {"error": {"code": 301, "message": "Wrong user."}}, "dead"),
    (502, {"detail": {"upstream_status": 400, "upstream_body": '{"error":{"code":301,"message":"Wrong user."}}'}},
     "dead"),
    (200, {"id": "42"}, "fail"),
    (500, "boom", "fail"),
    (200, {"id": CREATOR, "name": "wrong user"}, "ok"),
    (400, {"error": {"code": 302, "message": "Wrong user."}}, "fail"),
    (502, "Wrong user", "fail"),
    (200, {"id": CREATOR, "code": 301}, "ok"),
])
def test_probe_verdict(status, body, want):
    assert probe_verdict(status, body, CREATOR)[0] == want


def test_identity_problem_names_another_creator_or_none():
    assert identity_problem({"id": int(CREATOR)}, CREATOR) is None
    assert "named '42'" in identity_problem({"id": "42"}, CREATOR)
    assert "no OnlyFans" in identity_problem(None, CREATOR)


def test_session_secrets_and_leaks_name_the_file_never_the_value(tmp_path):
    secrets = session_secrets(load_session(_session_dir(tmp_path)))
    assert set(secrets) == {X_BC, COOKIE, STORED}
    leaks = session_leaks({"wire.jsonl": f'{{"x": "{COOKIE}"}}', "report.md": "clean", "<run output>": X_BC}, secrets)
    assert leaks == ["wire.jsonl: holds a session value", "<run output>: holds a session value"]
    assert not any(v in " ".join(leaks) for v in secrets)


def _line(cls, verdict="refused"):
    return {"verdict": verdict, "class": cls, "reason": "r", "method": "POST", "path": "/api2/v2/lists"}


@pytest.mark.parametrize("expect, status, lines, ok", [
    ("sent", 200, [_line("allow", "allow")], True),
    ("sent", "aborted", [_line("unarmed")], False),
    ("sent", 200, [], False),
    ("critical", "aborted", [_line("critical")], True),
    ("critical", "aborted", [_line("unarmed")], False),
    ("unarmed", 200, [_line("allow", "allow")], False),
    ("capture_abort", "aborted", [_line("capture_abort")], True),
])
def test_fetch_problems(expect, status, lines, ok):
    assert (fetch_problems("POST", "/api2/v2/lists", expect, status, lines) == []) is ok


def test_hand_off_needs_an_aborted_navigation_and_no_write():
    nav = [{"url": "http://127.0.0.1:1/my/settings/account", "class": "oauth", "aborted": True}]
    assert hand_off_problems(nav, [{"method": "GET", "path": "/api2/v2/users/me", "verdict": "read"}]) == []
    assert hand_off_problems([], []) == ["OAuth hand-off: no navigation to OnlyFans's page was recorded and aborted"]
    assert hand_off_problems(nav, [{"method": "POST", "path": "/api2/v2/lists", "verdict": "allow"}]) == [
        "OAuth hand-off sent a write: POST /api2/v2/lists"]


def test_critical_capture_is_abort_only():
    assert critical_capture_refused(ALL["tracer.create-list"], abort=False) is None
    why = critical_capture_refused(ALL["drill.withdrawal"], abort=False)
    assert why and "POST /api2/v2/payouts/requests" in why and "--abort" in why
    assert critical_capture_refused(ALL["drill.withdrawal"], abort=True) is None



class _Stub(BaseHTTPRequestHandler):
    me_id = CREATOR
    hits: list = []

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("content-length") or 0))
        _Stub.hits.append(("POST", self.path))
        if self.path == "/api2/v2/redir":
            self.send_response(307)
            self.send_header("location", "/api2/v2/target")
            self.send_header("content-length", "0")
            self.end_headers()
            return
        self._json({"id": "777"})

    def do_GET(self):  # noqa: N802
        _Stub.hits.append(("GET", self.path))
        self._json({"id": _Stub.me_id})

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class _Guard:

    def __init__(self, allow=()):
        self.intents, self.dones, self.allow = [], [], set(allow)

    def intent(self, method, url, body):
        self.intents.append((method, url))
        read, ok = method in READS, urlsplit(url).path in self.allow
        return {"seq": len(self.intents), "verdict": "read" if read else "allow" if ok else "refused",
                "class": "read" if read else "allow" if ok else "unarmed", "reason": "", "capture": ""}

    def done(self, seq, status, of_id=None):
        self.dones.append((seq, status, of_id))


@pytest.fixture()
def stub():
    _Stub.me_id, _Stub.hits = CREATOR, []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _browser(pw, tmp_path, origin, guard, probe=None):
    return CaptureBrowser(pw, load_session(_session_dir(tmp_path)), guard, creator=CREATOR, fake_origin=origin,
                          fake_sign=lambda pq: {"x-of-rev": "stub"}, probe=probe,
                          launch_args=["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"])


def test_browser_seeds_before_load_and_passes_the_identity_check(pw, tmp_path, stub):
    guard, probes = _Guard(), []
    cb = _browser(pw, tmp_path, stub, guard, probe=lambda: probes.append(1) or (200, {"id": CREATOR}))
    try:
        assert cb.open() == {"seeded": True, "probe": 200, "me": CREATOR}
        assert cb.page.evaluate("window.__ofmSeedAtLoad") is True
        assert cb.page.evaluate("localStorage.getItem('someKey')") == STORED
        assert probes == [1] and guard.intents[0][0] == "GET" and guard.intents[0][1].endswith("/api2/v2/users/me")
        assert cb.send("POST", "/api2/v2/lists", {"name": "oi-proof-x"}) == "aborted"
        assert ("POST", "/api2/v2/lists") not in _Stub.hits and cb.exchanges[-1]["aborted"]
        assert all(k.lower() not in ("cookie", "x-bc") for x in cb.exchanges for k in (x.get("headers") or {}))
    finally:
        cb.close()


def test_browser_naming_another_creator_stops_before_any_step(pw, tmp_path, stub):
    _Stub.me_id = "42"
    guard = _Guard()
    cb = _browser(pw, tmp_path, stub, guard)
    try:
        with pytest.raises(CaptureBrowserStop, match="named '42'"):
            cb.open()
        assert [m for m, _ in guard.intents] == ["GET"]
    finally:
        cb.close()


def test_wrong_user_probe_marks_the_session_dead_once(pw, tmp_path, stub):
    probes = []
    cb = _browser(pw, tmp_path, stub, _Guard(),
                  probe=lambda: probes.append(1) or (400, {"error": {"code": 301, "message": "Wrong user."}}))
    try:
        with pytest.raises(SessionDead):
            cb.open()
        assert probes == [1]
    finally:
        cb.close()


def test_fake_mode_aborts_every_other_origin_before_the_guard(pw, tmp_path, stub):
    other = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    guard = _Guard()
    cb = _browser(pw, tmp_path, stub, guard, probe=lambda: (200, {"id": CREATOR}))
    try:
        cb.open()
        n, url = len(guard.intents), f"http://127.0.0.1:{other.server_address[1]}/x"
        assert cb.page.evaluate("(u) => fetch(u).then(() => 'sent', () => 'aborted')", url) == "aborted"
        assert len(guard.intents) == n and cb.offhost() and _Stub.hits == [("GET", "/api2/v2/users/me")]
    finally:
        cb.close()
        other.shutdown()


@pytest.mark.parametrize("allow_target", [False, True], ids=["target-refused", "target-allowed"])
def test_a_redirect_hop_is_decided_again_before_it_leaves(pw, tmp_path, stub, allow_target):
    guard = _Guard(allow={"/api2/v2/redir"} | ({"/api2/v2/target"} if allow_target else set()))
    cb = _browser(pw, tmp_path, stub, guard, probe=lambda: (200, {"id": CREATOR}))
    try:
        cb.open()
        status = cb.send("POST", "/api2/v2/redir", {"name": "oi-proof-x"})
        posts = [(m, urlsplit(u).path) for m, u in guard.intents if m == "POST"]
        assert posts == [("POST", "/api2/v2/redir"), ("POST", "/api2/v2/target")]
        if allow_target:
            assert status == 200 and ("POST", "/api2/v2/target") in _Stub.hits
            assert (2 + 1, 200, "777") in guard.dones and cb.raw[3]["body"] == {"id": "777"}
        else:
            assert status == "aborted" and ("POST", "/api2/v2/target") not in _Stub.hits
        assert ("POST", "/api2/v2/redir") in _Stub.hits and (2, 307, None) in guard.dones
        assert all("body" not in (x.get("response") or {}) for x in cb.exchanges)
    finally:
        cb.close()
