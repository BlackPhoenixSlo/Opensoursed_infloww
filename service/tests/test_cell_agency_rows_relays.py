from __future__ import annotations

import _harness

import contextlib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
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
KEYS = {"s02": "cell-s02-copy-credential-0123456789abcdef", "s03": "cell-s03-copy-credential-0123456789abcdef"}
FLOOR_MSG, FLOOR_NAME = "employee_floor_pending", "(employee id floor)"
READ_ONLY = "agency_copy_read_only"


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


def _q(path: str, sql: str, args=()):
    with contextlib.closing(sqlite3.connect(path, timeout=30)) as db:
        return db.execute(sql, args).fetchall()


def _wait(pred, limit: float = 15.0) -> float:
    t0 = time.monotonic()
    while not pred():
        assert time.monotonic() - t0 < limit, "timed out"
        time.sleep(0.05)
    return time.monotonic() - t0


class Fleet:
    def __init__(self, root: Path):
        self.root = root
        self.placement = root / "placement.json"
        self.placement.write_text(json.dumps({
            "schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-26T10:00:00Z", "by": "fleet.py",
            "min_cell_proto": 1,
            "cells": {"s01": {"box": "b1", "epoch": 1, "relay": "x", "role": "control", "state": "live"},
                      "s02": {"box": "b1", "epoch": 1, "relay": "y", "role": "data", "state": "live"},
                      "s03": {"box": "b1", "epoch": 1, "relay": "z", "role": "data", "state": "live"}},
            "accounts": {f"onlyfans:{NOVA_A}": "s02", f"onlyfans:{NOVA_B}": "s03"}}))
        self.port = {sid: _port() for sid in ("s01", "s02", "s03")}
        self.db = {sid: str(root / sid / "relay.db") for sid in self.port}
        self.log = {sid: root / sid / "relay.log" for sid in self.port}
        self.procs: dict[str, tuple[subprocess.Popen, object]] = {}
        ctl = f"http://127.0.0.1:{self.port['s01']}"
        self.extra = {
            "s01": {"OI_CELL_ROLE": "control", "OI_ACCOUNTS": "", "OI_CELL_COPY_KEYS": ",".join(
                f"{c}:{hashlib.sha256(k.encode()).hexdigest()}" for c, k in KEYS.items())},
            "s02": {"OI_CELL_ROLE": "data", "OI_ACCOUNTS": f"onlyfans:{NOVA_A}", "OI_CELL_COPY_KEY": KEYS["s02"],
                    "OI_CELL_CONTROL_URL": ctl},
            "s03": {"OI_CELL_ROLE": "data", "OI_ACCOUNTS": f"onlyfans:{NOVA_B}", "OI_CELL_COPY_KEY": KEYS["s03"],
                    "OI_CELL_CONTROL_URL": ctl}}
        import actor_token
        pub = actor_token.new_key(root / "actor")
        self.extra["s01"]["OI_CELL_ACTOR_KEY_FILE"] = str(root / "actor/actor_ed25519.pem")
        for sid in ("s02", "s03"):
            self.extra[sid]["OI_CELL_ACTOR_PUBKEY"] = pub
        for sid in self.port:
            (root / sid / "home").mkdir(parents=True)

    def _env(self, sid: str) -> dict:
        work, db = self.root / sid, self.db[sid]
        return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(work / "home"), "TMPDIR": str(work),
                "CHATTERLY_TEST_MODE": "1", "SHARE_TOKEN": "", "ALLOW_ANONYMOUS_ADMIN": "1",
                "DATABASE_URL": f"sqlite+aiosqlite:///{db}", "CHATTERLY_DB_URL": f"sqlite:///{db}",
                "SESSION_SECRET": "cell-rows-session", "CHATTER_SESSION_SECRET": "cell-rows-chatter",
                "ADMIN_PASSWORD": "cell-rows-admin", "VAPID_KEY_FILE": str(work / "vapid.pem"),
                "OI_CELL_MAP": str(self.placement), "OI_CELL_ID": sid, "OI_EPOCH": "1", **self.extra[sid]}

    def start(self, *sids: str) -> None:
        for sid in sids:
            log = open(self.log[sid], "ab")
            self.procs[sid] = (subprocess.Popen(
                ["nice", "-n", "10", sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
                 "--port", str(self.port[sid])], cwd=SERVICE, env=self._env(sid),
                stdout=log, stderr=subprocess.STDOUT), log)
        deadline = time.monotonic() + 240
        for sid in sids:
            p = self.procs[sid][0]
            while True:
                assert p.poll() is None, self.log[sid].read_text()[-3000:]
                with contextlib.suppress(OSError):
                    if _ask(self.port[sid], "GET", "/livez")[0] == 200:
                        break
                assert time.monotonic() < deadline, f"{sid} never answered /livez"
                time.sleep(0.5)

    def stop(self, *sids: str) -> None:
        for sid in sids:
            p, log = self.procs.pop(sid)
            p.terminate()
            try:
                p.wait(30)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            log.close()

    def stop_all(self) -> None:
        self.stop(*list(self.procs))


@contextlib.contextmanager
def _fleet():
    with tempfile.TemporaryDirectory() as t:
        f = Fleet(Path(t))
        try:
            f.start("s01", "s02", "s03")
            yield f
        finally:
            f.stop_all()


def _cookie(h: dict) -> dict:
    return {"Cookie": h["set-cookie"].split(";", 1)[0]}


def _actor(ctl: int, session: dict) -> dict:
    st, h, raw = _ask(ctl, "POST", "/auth/actor", session)
    assert st == 200, ("mint oi_actor on control", st, raw[:300])
    return _cookie(h)


def _count(path: str) -> int:
    return _q(path, "SELECT COUNT(*) FROM employees")[0][0]


def _max(path: str) -> int:
    return _q(path, "SELECT COALESCE(MAX(id), 0) FROM employees")[0][0]


def _epoch(path: str) -> int:
    return _q(path, "SELECT copy_epoch FROM cell_meta")[0][0]


def _direct_insert_refused(path: str, msg: str) -> None:
    with contextlib.closing(sqlite3.connect(path, timeout=30)) as c:
        try:
            c.execute("INSERT INTO employees (display_name, is_active, created_at, user_id) VALUES"
                      " ('Direct', 1, '2026-11-26', NULL)")
            c.commit()
        except sqlite3.IntegrityError as e:
            assert msg in str(e), e
        else:
            raise AssertionError(f"direct Employee insert allowed on {path}")


def case_fresh_mirror_needs_no_cell_write_and_restore_floors_ids() -> None:
    with _fleet() as f:
        ctl, s02 = f.port["s01"], f.port["s02"]
        st, h, raw = _ask(ctl, "POST", "/auth/register", body={"username": "acmeowner", "password": "Owner-Pw-77"})
        assert st == 200, (st, raw[:300])
        owner, owner_c = json.loads(raw)["user_id"], _cookie(h)
        assert _q(f.db["s01"], "SELECT COUNT(*) FROM employees WHERE chatter_id = ? AND user_id = ?",
                  (f"owner:{owner}", owner)) == [(1,)], "owner Mirror Employee not created at register"
        assert _q(f.db["s01"], "SELECT 1 FROM user_settings WHERE user_id = ? AND tab = 'role-presets'", (owner,))
        with contextlib.closing(sqlite3.connect(f.db["s01"], timeout=30)) as c, c:
            c.execute("INSERT INTO accounts (id, is_active_default) VALUES (?, 1), (?, 1)", (NOVA_A, NOVA_B))
            c.execute("INSERT INTO user_accounts (user_id, account_id, created_at) VALUES (?, ?, '2026'),"
                      " (?, ?, '2026')", (owner, NOVA_A, owner, NOVA_B))
        st, _h, raw = _ask(ctl, "POST", "/admin/employees/login", owner_c,
                           {"username": "chatann", "password": "Chatter-Pw-77", "account_ids": [NOVA_A]})
        assert st == 200, (st, raw[:300])
        login = json.loads(raw)
        roles = json.loads(_q(f.db["s01"], "SELECT config_json FROM user_settings WHERE user_id = ? AND tab = 'roles'",
                              (owner,))[0][0])
        assert roles["assignments"][str(login["employee_id"])] == "chatter", roles
        st, h, raw = _ask(ctl, "POST", "/auth/sign-in", body={"username": "chatann", "password": "Chatter-Pw-77"})
        assert st == 200 and json.loads(raw)["kind"] == "chatter", (st, raw[:300])
        chat_c = _cookie(h)

        top = _max(f.db["s01"])
        for sid in ("s02", "s03"):
            _wait(lambda sid=sid: _max(f.db[sid]) == top and _q(
                f.db[sid], "SELECT 1 FROM chatter_account_access WHERE chatter_id = ?", (login["chatter_id"],)))
        owner_a, chat_a = _actor(ctl, owner_c), _actor(ctl, chat_c)
        st, _h, raw = _ask(ctl, "GET", "/chatter/me", chat_a)
        assert st == 200 and json.loads(raw)["chatter_id"] == login["chatter_id"], (st, raw)
        for path in ("/chatter/me/accounts", "/auth/cells", "/auth/2fa"):
            st, _h, raw = _ask(ctl, "GET", path, chat_a)
            assert st == 200, (path, st, raw)
        for path in ("/auth/sessions/revoke-others", "/auth/2fa/init", "/auth/actor"):
            st, h, raw = _ask(ctl, "POST", path, chat_a)
            assert st == 401 and "set-cookie" not in h, (path, st, raw)
        st, _h, raw = _ask(ctl, "POST", "/auth/2fa/init", chat_c)
        assert st == 200 and "enrol_token" in json.loads(raw), (st, raw)
        before, mark = _count(f.db["s02"]), f.log["s02"].stat().st_size
        st, _h, raw = _ask(s02, "GET", "/admin/employees", owner_a)
        assert st == 200, (st, raw[:300])
        assert {e["kind"] for e in json.loads(raw)["employees"]} == {"owner", "login"}, raw[:400]
        st, _h, raw = _ask(s02, "GET", f"/admin/sensitive-words?account_id={NOVA_A}", chat_a)
        assert st == 200, ("chatter on the data cell", st, raw[:300])
        st, _h, raw = _ask(s02, "GET", "/admin/settings/applied", {**chat_a, "X-Account-Id": NOVA_A})
        assert st == 200, ("chatter settings on the data cell", st, raw[:300])
        assert _count(f.db["s02"]) == before, "the data cell wrote an Employee"
        tail = f.log["s02"].read_bytes()[mark:].decode(errors="replace")
        assert READ_ONLY not in tail and "no Mirror Employee" not in tail, tail[-2000:]
        _direct_insert_refused(f.db["s02"], READ_ONLY)

        backup = str(f.root / "control-backup.db")
        with contextlib.closing(sqlite3.connect(f.db["s01"], timeout=30)) as src, \
                contextlib.closing(sqlite3.connect(backup)) as dst:
            src.backup(dst)
        st, _h, raw = _ask(ctl, "POST", "/admin/employees", owner_c, {"display_name": "Late1"})
        assert st == 200, (st, raw[:300])
        late1 = json.loads(raw)["id"]
        for sid in ("s02", "s03"):
            _wait(lambda sid=sid: _max(f.db[sid]) == late1)
        f.stop("s02")
        st, _h, raw = _ask(ctl, "POST", "/admin/employees", owner_c, {"display_name": "Late2"})
        assert st == 200, (st, raw[:300])
        late2 = json.loads(raw)["id"]
        _wait(lambda: _max(f.db["s03"]) == late2)
        assert late2 > late1 > top
        old_epoch = _epoch(f.db["s03"])

        f.stop("s01", "s03")
        for suffix in ("", "-wal", "-shm"):
            with contextlib.suppress(FileNotFoundError):
                os.remove(f.db["s01"] + suffix)
        shutil.copyfile(backup, f.db["s01"])
        out = subprocess.run(["nice", "-n", "10", sys.executable, "agency_copy.py", "--bump-epoch", f.db["s01"]],
                             cwd=SERVICE, capture_output=True, text=True, timeout=60)
        assert out.returncode == 0 and out.stdout.startswith("AGENCY-COPY-EPOCH "), (out.stdout, out.stderr)
        new_epoch = int(out.stdout.split()[1])
        assert new_epoch > old_epoch
        assert _max(f.db["s01"]) == top

        f.start("s01", "s02")
        _wait(lambda: _q(f.db["s01"], "SELECT max_emp FROM employee_floor_reports WHERE cell = 's02' AND epoch = ?",
                         (new_epoch,)) == [(late1,)])
        _wait(lambda: _epoch(f.db["s02"]) == new_epoch)
        n = _count(f.db["s01"])
        st, _h, raw = _ask(ctl, "POST", "/admin/employees", owner_c, {"display_name": "TooEarly"})
        assert st == 503 and json.loads(raw)["detail"]["error"] == FLOOR_MSG, (st, raw[:300])
        st, _h, raw = _ask(ctl, "POST", "/admin/employees/login", owner_c,
                           {"username": "chatbob", "password": "Chatter-Pw-77"})
        assert st == 503 and json.loads(raw)["detail"]["error"] == FLOOR_MSG, (st, raw[:300])
        assert _count(f.db["s01"]) == n and _q(f.db["s01"], "SELECT 1 FROM chatters WHERE username = 'chatbob'") == []
        _direct_insert_refused(f.db["s01"], FLOOR_MSG)

        f.start("s03")
        _wait(lambda: _q(f.db["s01"], "SELECT pending FROM employee_floor") == [(0,)])
        assert _q(f.db["s01"], "SELECT id, is_active, user_id FROM employees WHERE display_name = ?",
                  (FLOOR_NAME,)) == [(late2 + 1, 0, None)]
        st, _h, raw = _ask(ctl, "POST", "/admin/employees", owner_c, {"display_name": "AfterFloor"})
        assert st == 200, (st, raw[:300])
        fresh = json.loads(raw)["id"]
        print(f"restore drill: s02 reported {late1}, s03 reported {late2}; next Employee id {fresh}")
        assert fresh > late2, (fresh, late2)
        st, _h, raw = _ask(ctl, "GET", "/admin/employees", owner_c)
        assert st == 200 and FLOOR_NAME.encode() not in raw, raw[:400]
        for sid in ("s02", "s03"):
            _wait(lambda sid=sid: _epoch(f.db[sid]) == new_epoch and _max(f.db[sid]) == fresh)


_harness.run()
