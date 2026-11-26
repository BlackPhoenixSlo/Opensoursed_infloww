from __future__ import annotations

import _harness

import contextlib  # noqa: E402
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
DATA_GEN = 2


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ask(port: int, method: str, path: str, headers: dict | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={**({"Content-Type": "application/json"} if data else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _error(raw: bytes) -> str | None:
    try:
        detail = json.loads(raw).get("detail")
    except (ValueError, AttributeError):
        return None
    return detail.get("error") if isinstance(detail, dict) else None


@contextlib.contextmanager
def _two_cells():
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        placement = root / "placement.json"
        placement.write_text(json.dumps({
            "schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-26T10:00:00Z", "by": "fleet.py",
            "min_cell_proto": 1,
            "cells": {"s02": {"box": "b1", "epoch": 3, "relay": "x", "role": "data", "state": "live"},
                      "s03": {"box": "b1", "epoch": 1, "relay": "y", "role": "data", "state": "live"}},
            "accounts": {f"onlyfans:{NOVA_A}": "s02", f"onlyfans:{NOVA_B}": "s03"}}))
        procs, ports = [], {}
        try:
            for sid, aid, epoch in (("s02", NOVA_A, 3), ("s03", NOVA_B, 1)):
                work = root / sid
                (work / "home").mkdir(parents=True)
                db = work / "relay.db"
                if sid == "s02":
                    with contextlib.closing(sqlite3.connect(db)) as c, c:
                        c.execute("CREATE TABLE cell_meta (data_gen INTEGER NOT NULL DEFAULT 1, copy_epoch INTEGER,"
                                  " copy_version INTEGER, section_sha TEXT, applied_at TEXT, confirmed_at TEXT,"
                                  " grant_gen INTEGER)")
                        c.execute("INSERT INTO cell_meta (data_gen) VALUES (?)", (DATA_GEN,))
                port = ports[sid] = _port()
                env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(work / "home"),
                       "TMPDIR": str(work), "CHATTERLY_TEST_MODE": "1", "SHARE_TOKEN": "", "ALLOW_ANONYMOUS_ADMIN": "1",
                       "DATABASE_URL": f"sqlite+aiosqlite:///{db}", "CHATTERLY_DB_URL": f"sqlite:///{db}",
                       "SESSION_SECRET": "cell-test-session", "CHATTER_SESSION_SECRET": "cell-test-chatter",
                       "ADMIN_PASSWORD": "cell-test-admin", "VAPID_KEY_FILE": str(work / "vapid.pem"),
                       "OI_CELL_MAP": str(placement), "OI_CELL_ID": sid, "OI_CELL_ROLE": "data",
                       "OI_ACCOUNTS": f"onlyfans:{aid}", "OI_EPOCH": str(epoch)}
                log = open(work / "relay.log", "wb")
                procs.append((subprocess.Popen(["nice", "-n", "10", sys.executable, "-m", "uvicorn", "server:app",
                                                "--host", "127.0.0.1", "--port", str(port)],
                                               cwd=SERVICE, env=env, stdout=log, stderr=subprocess.STDOUT), log, work))
            deadline = time.monotonic() + 240
            for (p, _log, work), port in zip(procs, ports.values()):
                while True:
                    assert p.poll() is None, (work / "relay.log").read_text()[-3000:]
                    try:
                        if _ask(port, "GET", "/livez")[0] == 200:
                            break
                    except OSError:
                        pass
                    assert time.monotonic() < deadline, "relay never answered /livez"
                    time.sleep(0.5)
            yield ports
        finally:
            for p, log, _work in procs:
                p.terminate()
                try:
                    p.wait(30)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
                log.close()


def _not_owner(status, headers, raw, label):
    assert status == 409 and _error(raw) == "not_owner", (label, status, raw[:300])
    assert not {k.lower() for k in headers} & {"retry-after"}, (label, headers)


def case_two_relays() -> None:
    with _two_cells() as port:
        a, b = port["s02"], port["s03"]
        fans = "/admin/fans/{}/by-ids?ids=1"

        st, h, raw = _ask(a, "GET", fans.format(NOVA_A))
        assert st != 409 and _error(raw) is None, (st, raw[:300])
        assert h.get("x-cell-gen") == str(DATA_GEN), h
        _not_owner(*_ask(b, "GET", fans.format(NOVA_A)), "path account on the other Cell")
        _not_owner(*_ask(a, "GET", "/admin/chats/recent?account_id=" + NOVA_B), "chats/recent, foreign account")
        _not_owner(*_ask(a, "GET", "/api/of/v2/chats", {"X-Account-Id": NOVA_B}), "header account")

        st, _h, raw = _ask(a, "GET", f"/admin/screens/inbox?accounts={NOVA_A},{NOVA_B}")
        _not_owner(st, _h, raw, "bundle with one foreign member")
        assert json.loads(raw)["detail"]["accounts"] == [NOVA_B], raw
        st, _h, raw = _ask(a, "GET", f"/admin/screens/inbox?accounts={NOVA_A}")
        assert _error(raw) is None, (st, raw[:300])

        for expect in ("s03.3", "s02.1", "s02"):
            _not_owner(*_ask(a, "GET", fans.format(NOVA_A), {"X-Cell-Expect": expect}), f"expect {expect}")
        st, _h, raw = _ask(a, "GET", fans.format(NOVA_A), {"X-Cell-Expect": "s02.3"})
        assert _error(raw) is None, (st, raw[:300])
        st, _h, raw = _ask(b, "GET", fans.format(NOVA_B), {"X-Cell-Expect": "s03.1"})
        assert _error(raw) is None, (st, raw[:300])

        acct = f"/admin/accounts/{NOVA_A}"
        conflicts = [
            ("GET", fans.format(NOVA_A), {"X-Account-Id": NOVA_B}, None),
            ("GET", f"/api/of/v2/chats?account_id={NOVA_A}&account={NOVA_B}", None, None),
            ("GET", f"/api/of/v2/chats?account_id={NOVA_A}", {"X-Account-Id": NOVA_B}, None),
            ("PATCH", acct, None, {"account_id": NOVA_B, "nickname": "x"}),
        ]
        for method, path, headers, body in conflicts:
            st, _h, raw = _ask(a, method, path, headers, body)
            assert st == 400 and _error(raw) == "account_conflict", (path, headers, body, st, raw[:300])
        st, _h, raw = _ask(a, "GET", fans.format(NOVA_A), {"X-Account-Id": NOVA_A})
        assert _error(raw) is None, ("agreeing selectors", st, raw[:300])

        for gen in ("1", "0", "x"):
            st, _h, raw = _ask(a, "PATCH", acct, {"X-Cell-Gen": gen}, {"nickname": "x"})
            assert st == 409 and _error(raw) == "stale_cell_gen", (gen, st, raw[:300])
        for gen in (str(DATA_GEN), str(DATA_GEN + 1)):
            st, _h, raw = _ask(a, "PATCH", acct, {"X-Cell-Gen": gen}, {"nickname": "x"})
            assert _error(raw) != "stale_cell_gen", (gen, st, raw[:300])
        st, h, raw = _ask(a, "GET", fans.format(NOVA_A), {"X-Cell-Gen": "1"})
        assert _error(raw) is None and h.get("x-cell-gen") == str(DATA_GEN), ("old gen on a read", st, raw[:300])
        st, h, raw = _ask(b, "GET", fans.format(NOVA_B))
        assert h.get("x-cell-gen") == "1", ("fresh Cell starts at data_gen 1", h)

        st, h, _raw = _ask(a, "GET", "/livez")
        assert st == 200 and "x-cell-gen" not in {k.lower() for k in h}, ("no account, no X-Cell-Gen", h)


_harness.run()
