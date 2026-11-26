from __future__ import annotations

import _harness

import contextlib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import socket  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from pathlib import Path  # noqa: E402

SERVICE = Path(__file__).resolve().parents[1]
NOVA_A, NOVA_B = "900539700124344320", "900539700124344321"
KEY = "cell-s02-copy-credential-0123456789abcdef"
OWNER_PW = "Plaintext-Owner-Pw-77"


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
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _env(work: Path, sid: str, role: str, placement: Path, extra: dict) -> dict:
    db = work / "relay.db"
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(work / "home"), "TMPDIR": str(work),
            "CHATTERLY_TEST_MODE": "1", "SHARE_TOKEN": "", "ALLOW_ANONYMOUS_ADMIN": "1",
            "DATABASE_URL": f"sqlite+aiosqlite:///{db}", "CHATTERLY_DB_URL": f"sqlite:///{db}",
            "SESSION_SECRET": "cell-copy-session", "CHATTER_SESSION_SECRET": "cell-copy-chatter",
            "ADMIN_PASSWORD": "cell-copy-admin", "VAPID_KEY_FILE": str(work / "vapid.pem"),
            "OI_CELL_MAP": str(placement), "OI_CELL_ID": sid, "OI_CELL_ROLE": role, "OI_EPOCH": "1", **extra}


@contextlib.contextmanager
def _control_and_cell():
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        placement = root / "placement.json"
        placement.write_text(json.dumps({
            "schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-26T10:00:00Z", "by": "fleet.py",
            "min_cell_proto": 1,
            "cells": {"s01": {"box": "b1", "epoch": 1, "relay": "x", "role": "control", "state": "live"},
                      "s02": {"box": "b1", "epoch": 1, "relay": "y", "role": "data", "state": "live"}},
            "accounts": {f"onlyfans:{NOVA_A}": "s02"}}))
        ports = {"s01": _port(), "s02": _port()}
        extra = {
            "s01": {"OI_ACCOUNTS": "", "OI_CELL_COPY_KEYS": f"s02:{hashlib.sha256(KEY.encode()).hexdigest()}"},
            "s02": {"OI_ACCOUNTS": f"onlyfans:{NOVA_A}", "OI_CELL_COPY_KEY": KEY,
                    "OI_CELL_CONTROL_URL": f"http://127.0.0.1:{ports['s01']}"}}
        procs = []
        try:
            for sid, role in (("s01", "control"), ("s02", "data")):
                work = root / sid
                (work / "home").mkdir(parents=True)
                log = open(work / "relay.log", "wb")
                procs.append((subprocess.Popen(
                    ["nice", "-n", "10", sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
                     "--port", str(ports[sid])], cwd=SERVICE, env=_env(work, sid, role, placement, extra[sid]),
                    stdout=log, stderr=subprocess.STDOUT), log, work))
            deadline = time.monotonic() + 240
            for (p, _log, work), port in zip(procs, ports.values()):
                while True:
                    assert p.poll() is None, (work / "relay.log").read_text()[-3000:]
                    with contextlib.suppress(OSError):
                        if _ask(port, "GET", "/livez")[0] == 200:
                            break
                    assert time.monotonic() < deadline, "relay never answered /livez"
                    time.sleep(0.5)
            yield ports, {sid: str(root / sid / "relay.db") for sid in ports}, {sid: root / sid / "relay.log"
                                                                                  for sid in ports}
        finally:
            for p, log, _work in procs:
                p.terminate()
                try:
                    p.wait(30)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
                log.close()


def _q(path: str, sql: str, args=()):
    with contextlib.closing(sqlite3.connect(path, timeout=30)) as db:
        return db.execute(sql, args).fetchall()


def _wait(pred, limit: float = 10.0) -> float:
    t0 = time.monotonic()
    while not pred():
        assert time.monotonic() - t0 < limit, "timed out"
        time.sleep(0.02)
    return time.monotonic() - t0


def case_copy_over_two_relays() -> None:
    with _control_and_cell() as (port, db, _logs):
        ctl, cell = port["s01"], port["s02"]
        st, h, raw = _ask(ctl, "POST", "/auth/register", body={"username": "acmeowner", "password": OWNER_PW})
        assert st == 200, (st, raw[:300])
        cookie = {"Cookie": h["set-cookie"].split(";", 1)[0]}
        owner = json.loads(raw)["user_id"]
        with contextlib.closing(sqlite3.connect(db["s01"], timeout=30)) as c, c:
            c.execute("INSERT INTO accounts (id, is_active_default) VALUES (?, 1), (?, 1)", (NOVA_A, NOVA_B))
        st, _h, raw = _ask(ctl, "POST", "/admin/employees", cookie, {"display_name": "Ann"})
        assert st == 200, (st, raw[:300])
        emp = json.loads(raw)["id"]
        _wait(lambda: _q(db["s02"], "SELECT 1 FROM employees WHERE id = ?", (emp,)))

        st, _h, raw = _ask(ctl, "GET", "/fleet/agency-copy?since=0.0&hold=0", {"Authorization": f"Bearer {KEY}"})
        assert st == 200, (st, raw[:300])
        for needle in (OWNER_PW.encode(), b"password", b"totp"):
            assert needle not in raw, needle
        doc = json.loads(raw)
        assert doc["format"] == 1 and {"epoch", "version", "grant_gen"} <= doc.keys(), doc.keys()
        assert [r["username"] for r in doc["sections"]["users"]["rows"]] == ["acmeowner"]
        for creds in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Bearer {KEY}x"}):
            assert _ask(ctl, "GET", "/fleet/agency-copy?since=0.0&hold=0", creds)[0] == 403, creds
        assert _ask(cell, "GET", "/fleet/agency-copy?since=0.0&hold=0",
                    {"Authorization": f"Bearer {KEY}"})[0] == 404, "a data cell must not publish the copy"

        gen0 = _q(db["s02"], "SELECT grant_gen FROM cell_meta")[0][0]
        t0 = time.monotonic()
        st, _h, raw = _ask(ctl, "PUT", f"/admin/employees/{emp}/access", cookie, {"account_ids": [NOVA_B]})
        assert st == 200, (st, raw[:300])
        took = time.monotonic() - t0 + _wait(lambda: _q(
            db["s02"], "SELECT account_id FROM employee_account_access WHERE employee_id = ?", (emp,)) == [(NOVA_B,)])
        print(f"grant change on control visible on the data cell after {took * 1000:.0f} ms")
        assert took < 1.5, took
        ctl_gen = _q(db["s01"], "SELECT grant_gen FROM agency_copy_version")[0][0]
        _wait(lambda: _q(db["s02"], "SELECT grant_gen FROM cell_meta")[0][0] == ctl_gen)
        assert ctl_gen > gen0
        assert _q(db["s02"], "SELECT password FROM users WHERE id = ?", (owner,)) == [("!",)]

        with contextlib.closing(sqlite3.connect(db["s02"], timeout=30)) as c:
            for sql in ("UPDATE users SET username = 'evil'", "DELETE FROM employee_account_access",
                        "INSERT INTO blacklist (fan_id, added_at) VALUES (1, '2026')"):
                try:
                    c.execute(sql)
                    c.commit()
                except sqlite3.IntegrityError as e:
                    assert "agency_copy_read_only:" in str(e), e
                else:
                    raise AssertionError(f"data cell allowed {sql}")
            c.execute("UPDATE users SET last_seen_at = '2026-11-26 00:00:00'")
            c.commit()
        st, _h, raw = _ask(cell, "PATCH", f"/admin/employees/{emp}", None, {"display_name": "Local"})
        assert st == 403 and b"agency_write_on_data_cell" in raw, ("copied-table write via the data cell's API",
                                                                   st, raw[:300])
        assert _q(db["s02"], "SELECT display_name FROM employees WHERE id = ?", (emp,)) == [("Ann",)]
        assert _q(db["s01"], "SELECT name FROM sqlite_master WHERE name LIKE 'cell_copy_ro_%'") == []
        assert _q(db["s02"], "SELECT name FROM sqlite_master WHERE name LIKE 'cell_copy_v_%'") == []


_harness.run()
