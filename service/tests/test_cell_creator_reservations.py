from __future__ import annotations

import os

os.environ.pop("OI_CELL_MAP", None)

import _harness  # noqa: E402

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import socket  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
from pathlib import Path  # noqa: E402

from slop.lib.browserbase import paste_curl, signing  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "service"
LAUNCHER = ROOT / "scripts" / "demo-shots" / "relay_guarded.py"
NEW, PEND, NOPROXY, HELD, TAKE, STRAY, FANSLY, DOWN = (str(900539700124344400 + i) for i in range(8))
OWNED_S02 = (NEW, PEND, NOPROXY, HELD, TAKE, FANSLY, DOWN)
KEYS = {"s02": "cell-s02-reservation-credential-0123456789", "s03": "cell-s03-reservation-credential-0123456789"}
GOOD_REV, MISSING_REV = "rsv-rev", "rsv-missing-rev"
FLEET = "cell-fleet-handoff-credential-0123456789"
HANDOFF_KEY = "control-only-handoff-credential-0123456789"
HANDOFF = "/api/cell/reservations/handoff"


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ask(port: int, method: str, path: str, headers: dict | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={**({"Content-Type": "application/json"} if data else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _detail(raw: bytes):
    try:
        return json.loads(raw).get("detail")
    except (ValueError, AttributeError):
        return None


def _q(path: Path, sql: str, args=()):
    with contextlib.closing(sqlite3.connect(path, timeout=30)) as db:
        return db.execute(sql, args).fetchall()


@contextlib.contextmanager
def _chunk_server():
    chunk = signing("0", GOOD_REV, 0)["chunk"].encode()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def do_GET(self):  # noqa: N802
            ok = self.path == f"/static/prod/f/{GOOD_REV}/2313.js"
            self.send_response(200 if ok else 404)
            self.send_header("Content-Length", str(len(chunk) if ok else 0))
            self.end_headers()
            if ok:
                self.wfile.write(chunk)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


class _Relay:
    def __init__(self, root: Path, sid: str, role: str, placement: Path, origin: str, extra: dict, port: int):
        self.sid, self.work, self.port = sid, root / sid, port
        (self.work / "home").mkdir(parents=True)
        self.db = self.work / "relay.db"
        self.accounts = self.work / "sessions" / "accounts"
        self.proxies = self.work / "proxies.json"
        self.log_path = self.work / "relay.log"
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.work / "home"),
                    "TMPDIR": str(self.work), "CHATTERLY_TEST_MODE": "1", "SHARE_TOKEN": "",
                    "ALLOW_ANONYMOUS_ADMIN": "1", "DATABASE_URL": f"sqlite+aiosqlite:///{self.db}",
                    "CHATTERLY_DB_URL": f"sqlite:///{self.db}", "SESSION_SECRET": "cell-rsv-session",
                    "CHATTER_SESSION_SECRET": "cell-rsv-chatter", "ADMIN_PASSWORD": "cell-rsv-admin",
                    "VAPID_KEY_FILE": str(self.work / "vapid.pem"), "OF_API_ORIGIN": origin,
                    "DEMO_SHOTS_TMP": str(self.work), "DEMO_SHOTS_ROOT": str(ROOT),
                    "DEMO_SHOTS_RELAY_PORT": str(self.port), "OI_CELL_MAP": str(placement), "OI_CELL_ID": sid,
                    "OI_CELL_ROLE": role, "OI_EPOCH": "1", **extra}
        self.proc = None

    def start(self) -> None:
        self.log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(["nice", "-n", "10", sys.executable, str(LAUNCHER)], cwd=SERVICE, env=self.env,
                                     stdout=self.log, stderr=subprocess.STDOUT)

    def wait_up(self, deadline: float) -> None:
        while True:
            assert self.proc.poll() is None, self.log_path.read_text()[-3000:]
            with contextlib.suppress(OSError):
                if _ask(self.port, "GET", "/livez")[0] == 200:
                    return
            assert time.monotonic() < deadline, f"{self.sid} never answered /livez"
            time.sleep(0.5)

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.log.close()
        self.proc = None

    def text(self) -> str:
        return self.log_path.read_text(errors="replace")

    def bind(self, *aids: str) -> None:
        self.proxies.write_text(json.dumps({"proxies": [{
            "label": "dead-loopback", "scheme": "http", "host": "127.0.0.1", "port": _port(),
            "assigned_account_ids": list(aids)}]}))

    def bootstrap(self, aid: str, rev: str = GOOD_REV, headers: dict | None = None):
        return _ask(self.port, "POST", "/admin/session/bootstrap", headers,
                    body={"mode": "paste-curl", "curl": paste_curl(aid, rev), "make_active": False})


@contextlib.contextmanager
def _cells():
    with tempfile.TemporaryDirectory() as t, _chunk_server() as origin:
        root = Path(t)
        placement = root / "placement.json"
        placement.write_text(json.dumps({
            "schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-26T10:00:00Z", "by": "fleet.py",
            "min_cell_proto": 1,
            "cells": {"s01": {"box": "b1", "epoch": 1, "relay": "x", "role": "control", "state": "live"},
                      "s02": {"box": "b1", "epoch": 1, "relay": "y", "role": "data", "state": "live"},
                      "s03": {"box": "b1", "epoch": 1, "relay": "z", "role": "data", "state": "live"}},
            "accounts": {f"onlyfans:{a}": "s02" for a in OWNED_S02}}))
        import actor_token

        pub = actor_token.new_key(root / "actor")
        ctl_port = _port()
        digests = ",".join(f"{c}:{hashlib.sha256(k.encode()).hexdigest()}" for c, k in KEYS.items())
        relays = {
            "s01": _Relay(root, "s01", "control", placement, origin, {"OI_ACCOUNTS": "", "OI_CELL_COPY_KEYS": digests,
                                                                     "FLEET_SECRET": FLEET,
                                                                     "OI_CELL_ACTOR_KEY_FILE": str(root / "actor/actor_ed25519.pem"),
                                                                     "OI_CELL_HANDOFF_KEYS": hashlib.sha256(
                                                                         HANDOFF_KEY.encode()).hexdigest()},
                          ctl_port),
            "s02": _Relay(root, "s02", "data", placement, origin, {
                "OI_ACCOUNTS": ",".join(f"onlyfans:{a}" for a in OWNED_S02), "OI_CELL_COPY_KEY": KEYS["s02"],
                "OI_CELL_ACTOR_PUBKEY": pub, "OI_CELL_CONTROL_URL": f"http://127.0.0.1:{ctl_port}"}, _port()),
            "s03": _Relay(root, "s03", "data", placement, origin, {
                "OI_ACCOUNTS": f"onlyfans:{NEW}", "OI_CELL_COPY_KEY": KEYS["s03"],
                "OI_CELL_ACTOR_PUBKEY": pub, "OI_CELL_CONTROL_URL": f"http://127.0.0.1:{ctl_port}"}, _port())}
        relays["s02"].bind(NEW, TAKE)
        try:
            for r in relays.values():
                r.start()
            deadline = time.monotonic() + 240
            for r in relays.values():
                r.wait_up(deadline)
            for sid in ("s02", "s03"):
                while not _copied(relays[sid].db):
                    assert time.monotonic() < deadline, f"{sid} never applied an Agency copy"
                    time.sleep(0.2)
            yield relays
        finally:
            for r in relays.values():
                r.stop()


def _copied(db: Path) -> bool:
    try:
        return bool(_q(db, "SELECT 1 FROM cell_meta WHERE copy_version > 0"))
    except sqlite3.Error:
        return False


def _row(ctl: _Relay, aid: str):
    rows = _q(ctl.db, "SELECT platform, cell, state, expires_at FROM creator_reservations WHERE account_id = ?", (aid,))
    return rows[0] if rows else None


def _all(db: Path):
    return _q(db, "SELECT * FROM creator_reservations ORDER BY account_id")


def _handoff_on_relay(ctl: _Relay, s02: _Relay) -> None:
    handoff = {"Authorization": f"Bearer {HANDOFF_KEY}"}
    body = {"op": "carve-7", "from_cell": "s02", "to_cell": "s04",
            "accounts": [f"onlyfans:{NEW}", f"onlyfans:{TAKE}"], "expect_placement_gen": 1}
    assert _ask(s02.port, "POST", HANDOFF, handoff, body)[0] == 404, "a data cell must not take a hand-off"
    for creds in ({}, {"Authorization": f"Bearer {FLEET}"}, {"Authorization": f"Bearer {KEYS['s02']}"}):
        assert _ask(ctl.port, "POST", HANDOFF, creds, body)[0] == 403, creds
    for bad in ({"expect_placement_gen": "1"}, {"accounts": [NEW]}, {"accounts": []}, {"op": ""},
                {"accounts": [f"onlyfans:{NEW}", f"onlyfans:{NEW}"]}, {"accounts": [f"myspace:{NEW}"]},
                {"to_cell": "s02"}, {"accounts": [int(NEW)]}):
        assert _ask(ctl.port, "POST", HANDOFF, handoff, {**body, **bad})[0] == 422, bad

    before = _all(ctl.db)
    st, raw = _ask(ctl.port, "POST", HANDOFF, handoff, {**body, "accounts": [*body["accounts"], f"onlyfans:{HELD}"]})
    assert st == 409 and _detail(raw) == {"error": "not_held_by_source", "account": f"onlyfans:{HELD}",
                                          "platform": "fansly", "cell": "s02", "state": "active"}, (st, raw)
    st, raw = _ask(ctl.port, "POST", HANDOFF, handoff, {**body, "expect_placement_gen": 2})
    assert st == 409 and _detail(raw) == {"error": "placement_gen_mismatch", "expected": 2, "have": 1}, (st, raw)
    assert _all(ctl.db) == before, "a refused hand-off changed a reservation"

    payload = json.dumps(body).encode()
    with socket.create_connection(("127.0.0.1", ctl.port), timeout=10) as sock:
        sock.sendall(f"POST {HANDOFF} HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {HANDOFF_KEY}\r\n"
                     f"Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n\r\n".encode() + payload)
    deadline = time.monotonic() + 30
    while _row(ctl, NEW)[1] != "s04" or _row(ctl, TAKE)[1] != "s04":
        assert time.monotonic() < deadline, "the hand-off whose reply was dropped never committed"
        time.sleep(0.2)
    after = _all(ctl.db)
    st, raw = _ask(ctl.port, "POST", HANDOFF, handoff, body)
    assert st == 200 and json.loads(raw) == {"op": "carve-7", "to_cell": "s04", "status": "already_applied",
                                             "accounts": sorted(body["accounts"])}, (st, raw)
    st, raw = _ask(ctl.port, "POST", HANDOFF, handoff, {**body, "accounts": [f"onlyfans:{NEW}"]})
    assert st == 409 and _detail(raw) == {"error": "op_batch_mismatch", "op": "carve-7"}, (st, raw)
    assert _all(ctl.db) == after
    assert "Cells: reservation hand-off carve-7 s02 -> s04 (200)" in ctl.text()


def case_reservations_over_three_relays() -> None:
    with _cells() as cells:
        ctl, s02, s03 = cells["s01"], cells["s02"], cells["s03"]
        assert _ask(s02.port, "POST", "/fleet/reservations", body={})[0] == 404, "a data cell must not take reservations"
        for creds in ({}, {"Authorization": "Bearer wrong"}):
            st, _raw = _ask(ctl.port, "POST", "/fleet/reservations", creds,
                            {"creator_id": STRAY, "platform": "onlyfans", "state": "pending"})
            assert st == 403, (creds, st)
        st, _raw = _ask(ctl.port, "POST", "/fleet/reservations", {"Authorization": f"Bearer {KEYS['s02']}"},
                        {"creator_id": int(STRAY), "platform": "onlyfans", "state": "pending"})
        assert st == 422, ("ids stay strings", st)
        assert _row(ctl, STRAY) is None

        t0 = time.time()
        st, raw = s02.bootstrap(PEND, rev=MISSING_REV)
        assert st == 500, (st, raw[:300])
        platform, cell, state, expires = _row(ctl, PEND)
        assert (platform, cell, state) == ("onlyfans", "s02", "pending"), _row(ctl, PEND)
        assert t0 + 14 * 60 < expires < time.time() + 16 * 60, expires
        assert not (s02.accounts / PEND).exists(), "the reservation is taken before any session write"

        owner_req = urllib.request.Request(
            f"http://127.0.0.1:{ctl.port}/auth/register",
            data=json.dumps({"username": "reservationowner", "password": "reservation-owner-123"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(owner_req, timeout=20) as response:
            owner = json.load(response)["user_id"]
            cookie = response.headers["Set-Cookie"].split(";", 1)[0]
        deadline = time.monotonic() + 30
        while not _q(s02.db, "SELECT id FROM users WHERE id = ?", (owner,)):
            assert time.monotonic() < deadline, "data Cell never copied the owner"
            time.sleep(0.2)

        mint = urllib.request.Request(f"http://127.0.0.1:{ctl.port}/auth/actor", method="POST",
                                      headers={"Cookie": cookie})
        with urllib.request.urlopen(mint, timeout=20) as response:
            actor = response.headers["Set-Cookie"].split(";", 1)[0]
        assert actor.startswith("oi_actor=")
        st, raw = s02.bootstrap(NEW, headers={"Cookie": actor})
        assert st == 200, (st, raw[:500])
        assert not _q(s02.db, "SELECT * FROM user_accounts WHERE user_id = ? AND account_id = ?", (owner, NEW))
        assert "bootstrap sync+link failed" not in s02.text()
        assert s02.text().count("bootstrap owner grants come from Control") == 1
        assert json.loads(raw)["account_id"] == NEW
        assert _row(ctl, NEW) == ("onlyfans", "s02", "active", None), _row(ctl, NEW)
        st, raw = s02.bootstrap(NEW)
        assert st == 200 and _row(ctl, NEW) == ("onlyfans", "s02", "active", None), (st, raw[:300])

        st, raw = s03.bootstrap(NEW)
        assert st == 409 and _detail(raw) == {"error": "not_owner", "account_id": NEW}, (st, raw)
        assert not (s03.accounts / NEW).exists(), "a refused admission wrote an account dir"
        assert not s03.proxies.exists() or NEW not in s03.proxies.read_text(), "a refused admission bound a proxy"
        assert _row(ctl, NEW)[1] == "s02"

        with contextlib.closing(sqlite3.connect(ctl.db)) as db, db:
            cols = "creator_reservations (account_id, platform, cell, state, expires_at)"
            db.execute(f"INSERT INTO {cols} VALUES (?, 'fansly', 's02', 'active', NULL)", (HELD,))
            db.execute(f"INSERT INTO {cols} VALUES (?, 'onlyfans', 's03', 'pending', ?)",
                       (TAKE, time.time() - 1))
        st, raw = s02.bootstrap(HELD)
        assert st == 409 and "already a fansly Creator" in str(_detail(raw)), (st, raw)
        assert not (s02.accounts / HELD).exists()
        st, raw = s02.bootstrap(TAKE)
        assert st == 200, (st, raw[:300])
        assert _row(ctl, TAKE) == ("onlyfans", "s02", "active", None), "an expired pending is taken over"

        st, raw = s02.bootstrap(STRAY)
        assert st == 409 and _detail(raw) == {"error": "not_owner", "account_id": STRAY}, (st, raw)
        assert _row(ctl, STRAY) is None and not (s02.accounts / STRAY).exists()

        st, raw = _ask(s02.port, "POST", "/admin/session/fansly",
                       body={"token": "t", "accountId": FANSLY, "user_agent": "ua"})
        assert st == 403 and _detail(raw)["error"] == "cell_scope_closed", (st, raw)
        assert _row(ctl, FANSLY) is None and not (s02.accounts / FANSLY).exists()

        st, raw = s02.bootstrap(NOPROXY)
        assert st == 409 and _detail(raw) == {"error": "no_proxy_refused", "account_id": NOPROXY}, (st, raw)
        assert _row(ctl, NOPROXY)[2] == "active", "the session was written, so the reservation is active"
        st, raw = _ask(s02.port, "GET", "/api/of/v2/users/me", {"X-Account-Id": NOPROXY})
        assert st == 409 and _detail(raw) == {"error": "no_proxy_refused", "account_id": NOPROXY}, (st, raw)
        assert f"no_proxy_refused account={NOPROXY} at=client" in s02.text()

        assert f"account={NEW} at=" not in s02.text()
        s02.proxies.write_text(json.dumps({"proxies": []}))
        st, raw = _ask(s02.port, "GET", "/api/of/v2/users/me", {"X-Account-Id": NEW})
        assert st == 409 and _detail(raw) == {"error": "no_proxy_refused", "account_id": NEW}, (st, raw)
        log = s02.text()
        assert f"no_proxy_refused account={NEW} at=call" in log, log[-2000:]
        assert f"no_proxy_refused account={NEW} at=client" not in log, "the cached client was rebuilt"

        _handoff_on_relay(ctl, s02)

        ctl.stop()
        st, raw = s02.bootstrap(DOWN)
        assert st == 503 and (_detail(raw) or {}).get("error") == "control_unreachable", (st, raw)
        assert not (s02.accounts / DOWN).exists()


def case_handoff_on_a_control_sqlite() -> None:
    import creator_reservations as cr

    a, b, c, d, e, f, g = (str(900539700124344500 + i) for i in range(7))
    now = 1_800_000_000.0
    with tempfile.TemporaryDirectory() as t:
        db = Path(t) / "control.db"
        with contextlib.closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("CREATE TABLE creator_reservations (account_id TEXT PRIMARY KEY, platform TEXT NOT NULL,"
                         " cell TEXT NOT NULL, state TEXT CHECK (state IN ('pending','active')), expires_at REAL)")
            conn.executemany("INSERT INTO creator_reservations VALUES (?, ?, ?, ?, ?)", [
                (a, "onlyfans", "s02", "active", None), (b, "onlyfans", "s02", "active", None),
                (c, "onlyfans", "s02", "active", None), (d, "onlyfans", "s02", "pending", now + 60),
                (e, "onlyfans", "s03", "active", None), (f, "onlyfans", "s02", "pending", now - 1)])
        cr.install(f"sqlite:///{db}")
        cr.install(f"sqlite:///{db}")
        assert _all(db)[0] == (a, "onlyfans", "s02", "active", None, None, None), "existing rows keep their holder"

        def go(op, accounts, frm="s02", to="s04", expect=5, have=5):
            return cr.handoff(str(db), op, frm, to, [("onlyfans", x) if isinstance(x, str) else x for x in accounts],
                              expect, have)

        start = _all(db)
        refusals = [
            ([a, e, b], e, ("onlyfans", "s03", "active")),
            ([a, g], g, (None, None, None)),
            ([a, d], d, ("onlyfans", "s02", "pending")),
            ([a, f], f, ("onlyfans", "s02", "pending")),
            ([a, ("fansly", b)], b, ("onlyfans", "s02", "active")),
        ]
        for accounts, named, (platform, cell, state) in refusals:
            plat = "fansly" if named == b else "onlyfans"
            assert go("op-1", accounts) == (409, {"error": "not_held_by_source", "account": f"{plat}:{named}",
                                                  "platform": platform, "cell": cell, "state": state}), accounts
        assert go("op-1", [a, b], expect=5, have=6) == (
            409, {"error": "placement_gen_mismatch", "expected": 5, "have": 6})
        assert go("op-1", [a, b], have=None)[1]["error"] == "placement_gen_mismatch"
        assert _all(db) == start, "a refused hand-off changed a reservation"

        ok = {"op": "op-1", "to_cell": "s04", "accounts": sorted(f"onlyfans:{x}" for x in (a, b, c))}
        assert go("op-1", [c, a, b]) == (200, {**ok, "status": "applied"})
        moved = {r[0]: r for r in _all(db)}
        assert all(moved[x][1:5] == ("onlyfans", "s04", "active", None) and moved[x][5] == "op-1" and moved[x][6]
                   for x in (a, b, c)), moved
        assert {x: moved[x] for x in (d, e, f)} == {r[0]: r for r in start if r[0] in (d, e, f)}
        committed = _all(db)

        assert go("op-1", [a, b, c]) == (200, {**ok, "status": "already_applied"})
        assert go("op-1", [a, b, c], have=7) == (200, {**ok, "status": "already_applied"}), "replay after Placement moved on"
        for accounts, frm, to, expect in (([a, b], "s02", "s04", 5), ([a, b, c, d], "s02", "s04", 5),
                                          ([a, b, c], "s03", "s04", 5), ([a, b, c], "s02", "s05", 5),
                                          ([a, b, c], "s02", "s04", 4)):
            assert go("op-1", accounts, frm, to, expect) == (409, {"error": "op_batch_mismatch", "op": "op-1"}), \
                (accounts, frm, to, expect)
        assert go("op-2", [a]) == (409, {"error": "not_held_by_source", "account": f"onlyfans:{a}",
                                         "platform": "onlyfans", "cell": "s04", "state": "active"}), \
            "a moved Creator is no longer the source's"
        assert _all(db) == committed, "a replay or refusal wrote twice"
        assert go("op-3", [a], frm="s04", to="s06")[0] == 200
        assert go("op-1", [a, b, c]) == (200, {**ok, "status": "already_applied"})

        assert cr.reserve(str(db), "s06", "onlyfans", a, "active", now=now)[0] == 200
        assert cr.reserve(str(db), "s02", "onlyfans", b, "active", now=now)[1]["error"] == "lives_in_cell"


def case_handoff_needs_a_full_fleet_secret() -> None:
    import fleet_api

    saved = fleet_api._SECRET
    try:
        for secret, token, want in (("", "", False), ("x" * 31, "x" * 31, False), (FLEET, "", False),
                                    (FLEET, FLEET[:-1], False), (FLEET, FLEET, True)):
            fleet_api._SECRET = secret
            assert fleet_api.secret_ok(token) is want, (len(secret), len(token))
    finally:
        fleet_api._SECRET = saved


def _session(tmp: Path, aid: str) -> Path:
    s = signing(aid, GOOD_REV, 0)
    path = tmp / aid / "latest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"headers": {"user_id": aid, "x_bc": s["x_bc"], "x_of_rev": GOOD_REV,
                                            "user_agent": "ua"}, "signing": {"rules": s["rules"]}, "cookies": []}))
    return path


@contextlib.contextmanager
def _in_process(cells: bool):
    import accounts
    import of_ws
    import proxies
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        saved = (proxies.REGISTRY_PATH, proxies.CELLS, accounts.ACCOUNTS_DIR, of_ws.websockets.connect)
        proxies.REGISTRY_PATH, proxies.CELLS, accounts.ACCOUNTS_DIR = tmp / "proxies.json", cells, tmp / "accounts"
        calls: list[dict] = []

        def connect(*a, **kw):
            calls.append(kw)
            raise ConnectionRefusedError("test: no socket")
        of_ws.websockets.connect = connect
        try:
            yield tmp, calls
        finally:
            proxies.REGISTRY_PATH, proxies.CELLS, accounts.ACCOUNTS_DIR, of_ws.websockets.connect = saved


def _bind(tmp: Path, *aids: str) -> None:
    (tmp / "proxies.json").write_text(json.dumps({"proxies": [{
        "label": "dead-loopback", "scheme": "http", "host": "127.0.0.1", "port": _port(),
        "assigned_account_ids": list(aids)}]}))


async def _first_refusal(ws) -> str:
    import proxies
    try:
        async for _ in ws.events():
            pass
    except proxies.NoProxyRefused as e:
        return e.where
    return "not refused"


def case_ws_and_cached_client_refused_in_cell_mode() -> None:
    from of_client import OFClient
    from of_ws import OFWebSocket
    import proxies

    def ws(source, auth=True):
        w = OFWebSocket(source, account_id=None)
        if auth:
            def refresh(_c):
                w._ws_url, w._token = "ws://127.0.0.1:9/", "tok"
            w._refresh_auth = refresh
        return w

    with _in_process(cells=True) as (tmp, calls):
        aid = NOPROXY
        path = _session(tmp, aid)
        assert asyncio.run(_first_refusal(ws(lambda: OFClient.from_session_file(path)))) == "client"

        _bind(tmp, aid)
        cached = OFClient.from_session_file(path)
        assert cached.proxy_url
        (tmp / "proxies.json").write_text(json.dumps({"proxies": []}))
        assert asyncio.run(_first_refusal(ws(lambda: cached))) == "ws"
        assert asyncio.run(_first_refusal(ws(lambda: cached, auth=False))) == "call", "me() is a REST call"
        for call in (lambda: cached._http_call("GET", "http://127.0.0.1:9/api2/v2/users/me"),
                     lambda: cached._proxy_retry(lambda: "sent", what="upload")):
            try:
                call()
            except proxies.NoProxyRefused:
                pass
            else:
                raise AssertionError("cached client reached the platform with its proxy removed")

        _bind(tmp, aid)
        direct = OFClient.from_session_file(path)
        direct.proxy_url = None
        assert asyncio.run(_first_refusal(ws(lambda: direct))) == "ws"
        assert calls == [], "the socket was opened"


def case_ws_opens_with_session_proxy() -> None:
    from of_client import OFClient
    from of_ws import OFWebSocket
    import proxies

    with _in_process(cells=True) as (tmp, _calls):
        path = _session(tmp, NOPROXY)
        proxies.REGISTRY_PATH.write_text(json.dumps({"proxies": [{
            "label": "session-bound", "scheme": "http", "host": "127.0.0.1", "port": _port(),
            "assigned_session": path.name}]}))
        client = OFClient.from_session_file(path)
        ws = OFWebSocket(lambda: client)

        def refresh(_client):
            ws._ws_url, ws._token = "ws://127.0.0.1:9/", "tok"

        class Socket:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                pass

            async def send(self, _msg):
                pass

            async def recv(self):
                return '{"connected": true}'

        def connect(_url, **kwargs):
            assert kwargs["proxy"] == client.proxy_url
            return Socket()

        ws._refresh_auth = refresh
        import of_ws
        of_ws.websockets.connect = connect

        async def first():
            async with contextlib.aclosing(ws.events()) as stream:
                assert await anext(stream) == {"connected": True}

        asyncio.run(asyncio.wait_for(first(), 3))


def case_non_onlyfans_refused_at_admission() -> None:
    import accounts
    from fastapi import HTTPException

    saved = (accounts._CELLS, os.environ.get("OI_ACCOUNTS"))
    accounts._CELLS, os.environ["OI_ACCOUNTS"] = True, f"onlyfans:{FANSLY}"
    try:
        accounts.ensure_platform(FANSLY, "fansly")
    except HTTPException as e:
        assert e.status_code == 409 and e.detail == {"error": "platform_not_admitted", "platform": "fansly",
                                                     "account_id": FANSLY}, e.detail
    else:
        raise AssertionError("a Fansly Creator was admitted to a Cell")
    finally:
        accounts._CELLS = saved[0]
        if saved[1] is None:
            os.environ.pop("OI_ACCOUNTS", None)
        else:
            os.environ["OI_ACCOUNTS"] = saved[1]


def case_env_unset_behaves_as_main() -> None:
    import accounts
    import httpx
    from of_client import OFClient
    from of_ws import OFWebSocket
    import proxies

    assert not accounts._CELLS and not proxies.CELLS
    with _in_process(cells=False) as (tmp, calls):
        real_post = httpx.post
        httpx.post = lambda *a, **k: (_ for _ in ()).throw(AssertionError("control called with env unset"))
        try:
            assert accounts.ensure_platform(STRAY, "onlyfans") is None
            assert accounts.ensure_platform(FANSLY, "fansly") is None
        finally:
            httpx.post = real_post
        assert not (tmp / "accounts").exists()

        client = OFClient.from_session_file(_session(tmp, NOPROXY))
        assert client.proxy_url is None
        assert client._proxy_retry(lambda: "sent", what="upload") == "sent"

        w = OFWebSocket(lambda: client, account_id=NOPROXY)

        def refresh(_c):
            w._ws_url, w._token = "ws://127.0.0.1:9/", "tok"
            if calls:
                w.stop()
        w._refresh_auth = refresh

        async def drive():
            async def stopper():
                while not calls:
                    await asyncio.sleep(0.01)
                w.stop()
            task = asyncio.create_task(stopper())
            async for _ in w.events():
                pass
            await task
        asyncio.run(asyncio.wait_for(drive(), 20))
        assert calls and calls[0]["proxy"] is None, calls

    import server
    paths = {getattr(r, "path", None) for r in server.app.routes}
    assert "/fleet/reservations" not in paths and HANDOFF not in paths
    assert proxies.NoProxyRefused not in server.app.exception_handlers


def case_handoff_requires_control_only_key() -> None:
    import creator_reservations as reservations
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    with contextlib.ExitStack() as patches:
        import fleet_api

        fleet_key = "fleet-shared-credential-1234567890"
        handoff_key = "control-only-credential-1234567890"
        copy_key = "cell-copy-credential-1234567890"
        patches.enter_context(patch.object(fleet_api, "_SECRET", fleet_key))
        patches.enter_context(patch.dict(os.environ, {"FLEET_SECRET": fleet_key}))
        patches.enter_context(patch.dict(os.environ, {"OI_CELL_COPY_KEYS": f"s02:{hashlib.sha256(copy_key.encode()).hexdigest()}"}))
        app = FastAPI()
        app.include_router(reservations.router)
        client = TestClient(app)
        body = {"op": "", "from_cell": "s02", "to_cell": "s03", "accounts": [], "expect_placement_gen": 1}

        def post(key):
            return client.post("/api/cell/reservations/handoff", json=body,
                               headers={"Authorization": f"Bearer {key}"}).status_code

        assert post(fleet_key) == 403
        assert post(handoff_key) == 403
        patches.enter_context(patch.dict(os.environ, {"OI_CELL_HANDOFF_KEYS": hashlib.sha256(handoff_key.encode()).hexdigest()}))
        assert post(copy_key) == 403
        assert post(handoff_key) == 422
        digests = ",".join(hashlib.sha256(k.encode()).hexdigest() for k in (fleet_key, copy_key, handoff_key))
        patches.enter_context(patch.dict(os.environ, {"OI_CELL_HANDOFF_KEYS": digests}))
        assert post(fleet_key) == 403
        assert post(copy_key) == 403


def case_handoff_receipt_survives_later_move() -> None:
    import creator_reservations as reservations

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        path = str(tmp_path / "control.db")
        reservations.install(f"sqlite:///{path}")
        ids = [("onlyfans", "001"), ("onlyfans", "002")]
        for platform, account in ids:
            assert reservations.reserve(path, "source", platform, account, "active")[0] == 200
        assert reservations.handoff(path, "first", "source", "middle", ids, 1, 1)[0] == 200
        assert reservations.handoff(path, "second", "middle", "end", ids[:1], 2, 2)[0] == 200
        status, reply = reservations.handoff(path, "first", "source", "middle", ids, 1, 2)
        assert (status, reply["status"]) == (200, "already_applied")
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE creator_handoff_ops")
        reservations.install(f"sqlite:///{path}")
        status, reply = reservations.handoff(path, "first", "source", "middle", ids, 1, 2)
        assert (status, reply["status"]) == (200, "already_applied")


def case_reservation_route_checks_exact_placement_and_platform() -> None:
    import creator_reservations as reservations
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    with contextlib.ExitStack() as patches, tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        placement = tmp_path / "placement.json"
        placement.write_text(json.dumps({"accounts": {
            "onlyfans:001": "s02", "onlyfans:002": "s03", "fansly:001": "s02",
        }}))
        patches.enter_context(patch.dict(os.environ, {"OI_CELL_MAP": str(placement)}))
        key = "test-copy-key"
        patches.enter_context(patch.dict(os.environ, {"OI_CELL_COPY_KEYS": f"s02:{hashlib.sha256(key.encode()).hexdigest()}"}))

        path = str(tmp_path / "control.db")
        url = f"sqlite:///{path}"
        patches.enter_context(patch("db.engine.sync_database_url", return_value=url))
        reservations.install(url)
        app = FastAPI()
        app.include_router(reservations.router)

        def post(platform, account):
            return TestClient(app).post("/fleet/reservations", headers={"Authorization": f"Bearer {key}"},
                                        json={"creator_id": account, "platform": platform, "state": "active"})

        for platform, account, error in (("onlyfans", "002", "not_owner"), ("onlyfans", "1", "not_owner"),
                                          ("fansly", "001", "platform_not_admitted")):
            reply = post(platform, account)
            assert reply.status_code == 403
            assert reply.json()["detail"]["error"] == error
        assert post("onlyfans", "001").status_code == 200
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT account_id, cell FROM creator_reservations").fetchall() == [("001", "s02")]


def case_activation_reasserts_healthy_creators_while_one_is_unreadable() -> None:
    import creator_reservations as reservations
    from unittest.mock import patch

    with contextlib.ExitStack() as patches, tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        import accounts
        import httpx

        patches.enter_context(patch.object(accounts, "ACCOUNTS_DIR", tmp_path / "accounts"))
        for aid in ("001", "002", "003"):
            directory = accounts.ACCOUNTS_DIR / aid
            directory.mkdir(parents=True)
            (directory / "session.json").write_text("{}")
            (directory / "latest.json").write_text('{"session":"session.json"}')
        patches.enter_context(patch.dict(os.environ, {"OI_ACCOUNTS": "onlyfans:001,onlyfans:002"}))
        patches.enter_context(patch.dict(os.environ, {"OI_CELL_CONTROL_URL": "http://127.0.0.1:1"}))
        broken = accounts.ACCOUNTS_DIR / "001" / "latest.json"
        broken.write_bytes(b"\xff")
        calls = []
        done, repaired = threading.Event(), threading.Event()

        def send(_url, *, json, **_kwargs):
            account = json["creator_id"]
            calls.append((account, json["state"]))
            if account == "002" and calls.count(("002", "active")) == 1:
                return httpx.Response(503)
            if account == "002":
                done.set()
            if account == "001":
                repaired.set()
            return httpx.Response(200, json={"state": "active"})

        patches.enter_context(patch.object(httpx, "post", send))

        async def exercise():
            task = asyncio.create_task(reservations.retry_activations())
            try:
                assert await asyncio.to_thread(done.wait, 4), "unreadable Creator blocked healthy activation"
                fixed = broken.with_suffix(".tmp")
                fixed.write_text('{"session":"session.json"}')
                fixed.replace(broken)
                assert await asyncio.to_thread(repaired.wait, 4)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        asyncio.run(exercise())
        assert calls.count(("001", "active")) == 1
        assert calls.count(("002", "active")) == 2
        assert len(calls) == 3


def case_cached_client_rechecks_proxy_after_backoff() -> None:
    from unittest.mock import patch

    import of_client
    import proxies

    with _in_process(cells=True) as (tmp, _):
        _bind(tmp, NOPROXY)
        client = of_client.OFClient.from_session_file(_session(tmp, NOPROXY))
        calls = []

        def send():
            calls.append("attempt")
            if len(calls) == 1:
                raise of_client.requests.exceptions.ProxyError("temporary failure")

        def unbind(_pause):
            (tmp / "proxies.json").write_text(json.dumps({"proxies": []}))

        with patch.object(of_client.time, "sleep", unbind):
            try:
                client._proxy_retry(send, what="upload")
            except proxies.NoProxyRefused:
                pass
            else:
                raise AssertionError("retried with an unbound proxy")
        assert calls == ["attempt"]


_harness.run()
