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
import threading  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from pathlib import Path  # noqa: E402

SERVICE = Path(__file__).resolve().parents[1]
DRIVER = SERVICE.parent / "deploy/fleet/tests"
NOVA_A, NOVA_B = "900539700124344320", "900539700124344321"
KEYS = {"s02": "cell-s02-copy-credential-0123456789abcdef", "s03": "cell-s03-copy-credential-0123456789abcdef"}
TICK_S = 2.0
EVIDENCE = os.environ.get("CELL_NOTICES_EVIDENCE")


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


def _wait(pred, limit: float = 20.0) -> float:
    t0 = time.monotonic()
    while not pred():
        assert time.monotonic() - t0 < limit, "timed out"
        time.sleep(0.05)
    return time.monotonic() - t0


class Fleet:
    def __init__(self, root: Path, cells: bool = True):
        self.root, self.cells = root, cells
        self.placement = root / "placement.json"
        self.placement.write_text(json.dumps({
            "schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-28T10:00:00Z", "by": "fleet.py",
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
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(work / "home"), "TMPDIR": str(work),
               "CHATTERLY_TEST_MODE": "1", "SHARE_TOKEN": "", "ALLOW_ANONYMOUS_ADMIN": "0",
               "DATABASE_URL": f"sqlite+aiosqlite:///{db}", "CHATTERLY_DB_URL": f"sqlite:///{db}",
               "SESSION_SECRET": "cell-notices-session", "CHATTER_SESSION_SECRET": "cell-notices-chatter",
               "ADMIN_PASSWORD": "cell-notices-admin", "VAPID_KEY_FILE": str(work / "vapid.pem"),
               "PYTHONPATH": str(DRIVER)}
        if self.cells:
            env |= {"OI_CELL_MAP": str(self.placement), "OI_CELL_ID": sid, "OI_EPOCH": "1", **self.extra[sid]}
        return env

    def start(self, *sids: str) -> None:
        for sid in sids:
            log = open(self.log[sid], "ab")
            self.procs[sid] = (subprocess.Popen(
                ["nice", "-n", "10", sys.executable, "-m", "uvicorn", "cells_notice_app:app", "--host", "127.0.0.1",
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
def _fleet(*sids: str, cells: bool = True):
    with tempfile.TemporaryDirectory() as t:
        f = Fleet(Path(t), cells)
        try:
            f.start(*sids)
            yield f
        finally:
            f.stop_all()


def _cookie(h: dict) -> str:
    return h["set-cookie"].split(";", 1)[0]


def _owner(port: int, db: str) -> tuple[str, dict]:
    st, h, raw = _ask(port, "POST", "/auth/register", body={"username": "acmeowner", "password": "Owner-Pw-77"})
    assert st == 200, (st, raw[:300])
    owner = json.loads(raw)["user_id"]
    with contextlib.closing(sqlite3.connect(db, timeout=30)) as c, c:
        c.execute("INSERT INTO accounts (id, is_active_default) VALUES (?, 1), (?, 1)", (NOVA_A, NOVA_B))
        c.execute("INSERT INTO user_accounts (user_id, account_id, created_at) VALUES (?, ?, '2026'),"
                  " (?, ?, '2026')", (owner, NOVA_A, owner, NOVA_B))
    return owner, {"Cookie": _cookie(h)}


def _feed(port: int, who: dict) -> dict:
    st, _h, raw = _ask(port, "GET", "/admin/agency-notifications?limit=50", who)
    assert st == 200, (st, raw[:300])
    return json.loads(raw)


def _drive(port: int, act: str, aid: str) -> dict:
    st, _h, raw = _ask(port, "GET", f"/_drive/{act}/{aid}")
    assert st == 200, (act, st, raw[:300])
    return json.loads(raw)


class Stream:
    def __init__(self, port: int, who: dict):
        self.got: list[tuple[float, str]] = []
        req = urllib.request.Request(f"http://127.0.0.1:{port}/events?scope=all", headers=who)
        self.resp = urllib.request.urlopen(req, timeout=120)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        with contextlib.suppress(Exception):
            for line in self.resp:
                if b"agency_notifications" in line:
                    self.got.append((time.monotonic(), line.decode(errors="replace").strip()))

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.resp.close()


def _log(f: Fleet, sid: str) -> str:
    return f.log[sid].read_text(errors="replace")


def _save(name: str, doc: object) -> None:
    if EVIDENCE:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / name).write_text(json.dumps(doc, indent=2, default=str))


def case_data_cell_notices_reach_control_bell() -> None:
    with _fleet("s01", "s02", "s03") as f:
        ctl, s02, s03 = f.port["s01"], f.port["s02"], f.port["s03"]
        owner, who = _owner(ctl, f.db["s01"])
        for sid in ("s02", "s03"):
            _wait(lambda sid=sid: _q(f.db[sid], "SELECT COUNT(*) FROM user_accounts WHERE user_id = ?",
                                     (owner,)) == [(2,)], 60)
        st, h, raw = _ask(ctl, "POST", "/auth/actor", who)
        assert st == 200, (st, raw[:300])
        who = {"Cookie": f"{who['Cookie']}; {_cookie(h)}"}
        assert _feed(ctl, who) == {"notifications": [], "unread": 0, "pinned": []}
        sse = Stream(ctl, who)
        time.sleep(0.5)

        t0 = time.monotonic()
        a, b = _drive(s02, "dead", NOVA_A), _drive(s03, "dead", NOVA_B)
        assert a["result"] is True and b["result"] is True, (a, b)
        took = _wait(lambda: _feed(ctl, who)["unread"] == 2, 3 * TICK_S)
        feed = _feed(ctl, who)
        print(f"box1: two Cells' session_dead in Control bell after {took:.2f} s (tick {TICK_S} s); "
              f"SSE pushes {len(sse.got)}")
        _save("01-control-feed-after-session-dead.json", feed)
        assert sorted(n["account_id"] for n in feed["notifications"]) == [NOVA_A, NOVA_B], feed
        assert {n["kind"] for n in feed["notifications"]} == {"session_dead"}, feed
        _wait(lambda: any(t >= t0 for t, _ in sse.got), 3 * TICK_S)
        _save("01-control-sse.json", sse.got)

        ids = {n["account_id"]: n["id"] for n in feed["notifications"]}
        st, _h, raw = _ask(ctl, "POST", f"/admin/agency-notifications/{ids[NOVA_A]}/read", who)
        assert st == 200 and json.loads(raw) == {"unread": 1}, (st, raw)
        st, _h, raw = _ask(ctl, "POST", f"/admin/agency-notifications/{ids[NOVA_B]}/dismiss", who)
        assert st == 200 and json.loads(raw) == {"unread": 0}, (st, raw)
        assert [n["account_id"] for n in _feed(ctl, who)["notifications"]] == [NOVA_A]
        st, _h, raw = _ask(ctl, "POST", "/admin/agency-notifications/dismiss-all", who, {"up_to_id": ids[NOVA_A]})
        assert st == 200, (st, raw)
        assert _feed(ctl, who) == {"notifications": [], "unread": 0, "pinned": []}

        f.stop("s02")
        f.start("s02")
        time.sleep(3 * TICK_S)
        rows = _q(f.db["s01"], "SELECT account_id, dismissed_at IS NOT NULL FROM agency_notifications ORDER BY 1")
        assert rows == [(NOVA_A, 1), (NOVA_B, 1)], ("replay after a data Cell restart duplicated or revived", rows)
        assert _feed(ctl, who)["unread"] == 0
        print("box2/4: read, dismiss, dismiss-all stick on Control; s02 restart replay filed no duplicate")

        flag = _drive(s02, "flag", NOVA_A)
        assert flag["result"] == 1, flag
        _wait(lambda: len(_feed(ctl, who)["pinned"]) == 1, 3 * TICK_S)
        feed = _feed(ctl, who)
        _save("02-control-feed-pinned.json", feed)
        assert feed["unread"] == 1 and feed["pinned"][0]["account_id"] == NOVA_A, feed
        pin = feed["pinned"][0]["id"]
        st, _h, raw = _ask(ctl, "POST", f"/admin/agency-notifications/{pin}/read", who)
        assert st == 409, (st, raw)
        st, _h, raw = _ask(ctl, "POST", "/admin/agency-notifications/read-all", who)
        assert st == 200 and json.loads(raw) == {"unread": 1}, (st, raw)
        clear = _drive(s02, "clear", NOVA_A)
        assert clear["result"] == 1, clear
        took = _wait(lambda: _feed(ctl, who)["pinned"] == [], 3 * TICK_S)
        assert _feed(ctl, who)["unread"] == 0
        print(f"box2: pinned consent filed on s02 shows on Control, refuses read; cleared on s02 -> gone on "
              f"Control after {took:.2f} s")

        f.stop("s01")
        down = _drive(s03, "flag", NOVA_B)
        assert down["result"] == 1 and down["ms"] < 1000, ("producer blocked by a Control outage", down)
        _wait(lambda: "bell notices not delivered to Control" in _log(f, "s03"), 3 * TICK_S)
        f.start("s01")
        took = _wait(lambda: len(_feed(ctl, who)["pinned"]) == 1, 6 * TICK_S)
        feed = _feed(ctl, who)
        _save("03-control-feed-after-outage.json", feed)
        assert feed["pinned"][0]["account_id"] == NOVA_B, feed
        _wait(lambda: "bell notices reach Control again" in _log(f, "s03"), 3 * TICK_S)
        print(f"box3: Control down, s03 producer returned in {down['ms']} ms; notice reached Control "
              f"{took:.2f} s after it came back")

        dupes = _q(f.db["s01"], "SELECT agency_user_id, dedupe_key, COUNT(*) FROM agency_notifications"
                                " GROUP BY 1, 2 HAVING COUNT(*) > 1")
        assert dupes == [], dupes
        assert _q(f.db["s01"], "SELECT COUNT(*) FROM agency_notifications") == [(3,)]
        sse.close()


def case_control_refuses_strangers_and_foreign_creators() -> None:
    with _fleet("s01") as f:
        ctl = f.port["s01"]
        owner, _who = _owner(ctl, f.db["s01"])
        row = {"id": 1, "agency_user_id": owner, "kind": "session_dead", "text": "x", "platform": "onlyfans",
               "account_id": NOVA_B, "created_at": "2026-11-28T10:00:00"}
        st, _h, _raw = _ask(ctl, "POST", "/fleet/notices", {"Authorization": "Bearer nope"}, {"rows": [row]})
        assert st == 403
        s02 = {"Authorization": f"Bearer {KEYS['s02']}"}
        st, _h, raw = _ask(ctl, "POST", "/fleet/notices", s02,
                           {"rows": [row, {**row, "id": 2, "account_id": NOVA_A, "platform": "fansly"},
                                     {**row, "id": 3, "agency_user_id": "ghost", "account_id": NOVA_A}, "junk"],
                            "pinned": []})
        assert st == 200 and json.loads(raw) == {"filed": 0, "dropped": 0, "skipped": 4}, (st, raw)
        st, _h, raw = _ask(ctl, "POST", "/fleet/notices", s02, {"rows": [{**row, "account_id": NOVA_A}]})
        assert st == 200 and json.loads(raw)["filed"] == 1, (st, raw)
        assert _q(f.db["s01"], "SELECT account_id, dedupe_key FROM agency_notifications") == [
            (NOVA_A, "cell:s02:1:2026-11-28T10:00:00")]


def case_env_unset_bell_stays_local() -> None:
    with _fleet("s01", cells=False) as f:
        port = f.port["s01"]
        _owner_id, who = _owner(port, f.db["s01"])
        assert _ask(port, "POST", "/fleet/notices", body={"rows": []})[0] == 404
        assert _drive(port, "dead", NOVA_A)["result"] is True
        feed = _feed(port, who)
        assert feed["unread"] == 1 and feed["notifications"][0]["kind"] == "session_dead", feed
        assert "bell notices" not in _log(f, "s01")


_harness.run()
