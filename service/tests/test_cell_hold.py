#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()
_harness.make_client()

import contextlib  # noqa: E402
import importlib.machinery  # noqa: E402
import importlib.util  # noqa: E402
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
from unittest.mock import patch  # noqa: E402

from _send_kill_cell import AID, SYNC_URL, FakeHttp, cells, client, err, post, raises, unknown_proxy  # noqa: E402
from _send_kill_hold import KIND, _executor, _fresh  # noqa: E402

import accounts  # noqa: E402

accounts.get_account = lambda aid: {"id": aid, "nickname": aid}
accounts.get_platform = lambda aid: "onlyfans"
SERVICE = Path(__file__).resolve().parents[1]
TOOL = SERVICE.parent / "deploy" / "fleet" / "bin" / "oi-cell-hold"
SECRET = "f" * 40
FANS = iter(range(76001, 77000))


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


async def _seed() -> None:
    from db.engine import get_session
    from db.models import Account
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID, nickname=AID))


def _tool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(TOOL), *args], capture_output=True, text=True, timeout=60)


def _load_tool():
    loader = importlib.machinery.SourceFileLoader("oi_cell_hold", str(TOOL))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


def _table(db: Path) -> bool:
    with contextlib.closing(sqlite3.connect(db)) as c:
        return c.execute("SELECT 1 FROM sqlite_master WHERE name='cell_holds'").fetchone() is not None


@contextlib.contextmanager
def _relay(work: Path, cells_on: bool):
    db = work / "data" / "chatterly.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    (work / "home").mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(work / "home"), "TMPDIR": str(work),
           "CHATTERLY_TEST_MODE": "1", "SHARE_TOKEN": "", "ALLOW_ANONYMOUS_ADMIN": "1",
           "DATABASE_URL": f"sqlite+aiosqlite:///{db}", "CHATTERLY_DB_URL": f"sqlite:///{db}",
           "SESSION_SECRET": "cell-test-session", "CHATTER_SESSION_SECRET": "cell-test-chatter",
           "ADMIN_PASSWORD": "cell-test-admin", "VAPID_KEY_FILE": str(work / "vapid.pem"), "FLEET_SECRET": SECRET}
    if cells_on:
        placement = work / "placement.json"
        placement.write_text(json.dumps({
            "schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-26T10:00:00Z", "by": "fleet.py",
            "min_cell_proto": 1, "cells": {"s02": {"box": "b1", "epoch": 1, "relay": "x", "role": "data",
                                                   "state": "live"}},
            "accounts": {f"onlyfans:{AID}": "s02"}}))
        env.update(OI_CELL_MAP=str(placement), OI_CELL_ID="s02", OI_CELL_ROLE="data",
                   OI_ACCOUNTS=f"onlyfans:{AID}", OI_EPOCH="1")
    port = _port()
    with open(work / "relay.log", "ab") as log:
        p = subprocess.Popen(["nice", "-n", "10", sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
                              "--port", str(port)], cwd=SERVICE, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 240
            while True:
                assert p.poll() is None, (work / "relay.log").read_text()[-3000:]
                with contextlib.suppress(OSError):
                    if _ask(port, "GET", "/livez")[0] == 200:
                        break
                assert time.monotonic() < deadline, "relay never answered /livez"
                time.sleep(0.5)
            yield port
        finally:
            p.terminate()
            try:
                p.wait(30)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


WRITES = (("POST", "/admin/s4s/requests/1/accept", {}, {}),
          ("POST", "/api/of/v2/promotions/1/finish", {"X-Account-Id": AID}, {}),
          ("POST", "/api/of/v2/chats/1/messages", {"X-Account-Id": AID}, {"text": "hi"}))
READ = ("GET", f"/admin/fans/{AID}/by-ids?ids=1")
BEARER = {"Authorization": f"Bearer {SECRET}"}


def _held(port: int) -> list[str | None]:
    return [_error(_ask(port, m, p, h, b)[2]) for m, p, h, b in WRITES]


def _drain(port: int) -> dict:
    st, _h, raw = _ask(port, "GET", "/api/cell/hold", BEARER)
    assert st == 200, (st, raw[:300])
    return json.loads(raw)


def case_box_tool_ddl_is_the_store_ddl():
    import cell_hold
    assert _load_tool().DDL == cell_hold.DDL


def case_relay_held_across_restart_then_cleared_while_stopped():
    with tempfile.TemporaryDirectory() as t:
        work = Path(t)
        with _relay(work, True) as port:
            assert _ask(port, "GET", "/api/cell/hold")[0] == 403
            assert _drain(port)["held"] is False
            assert "cell_held" not in _held(port), _held(port)
            out = _tool("set", str(work), "--why", "carve", "--blocks", "writes", "--op", "carve-1")
            assert out.returncode == 0 and "new=1" in out.stdout, (out.stdout, out.stderr)
            again = _tool("set", str(work), "--why", "carve", "--blocks", "writes", "--op", "carve-1")
            assert again.returncode == 0 and "new=0" in again.stdout, again.stdout
            clash = _tool("set", str(work), "--why", "carve", "--blocks", "automations", "--op", "carve-1")
            assert clash.returncode == 2, clash
            assert _held(port) == ["cell_held"] * 3, _held(port)
            st, _h, raw = _ask(port, *READ)
            assert st == 200 and _error(raw) is None, (st, raw[:300])
            d = _drain(port)
            assert (d["held"], d["op"], d["why"], d["blocks"]) == (True, "carve-1", "carve", "writes"), d
            assert (d["remote_login_jobs"], d["claimed_sends_inflight"], d["uncertain_sends"]) == (0, 0, 0), d
        with _relay(work, True) as port:
            assert _held(port) == ["cell_held"] * 3, "hold lost on restart"
            assert _drain(port)["held"] is True
        out = _tool("clear", str(work), "--op", "carve-1")
        assert out.returncode == 0 and "released=1" in out.stdout, (out.stdout, out.stderr)
        assert json.loads(_tool("show", str(work)).stdout) == []
        with _relay(work, True) as port:
            assert "cell_held" not in _held(port), _held(port)
            assert _drain(port)["held"] is False
    assert _tool("show", "/nonexistent/cell").returncode != 0


def case_env_unset_relay_has_no_route_no_table_no_hold():
    with tempfile.TemporaryDirectory() as t:
        work = Path(t)
        with _relay(work, False) as port:
            assert _ask(port, "GET", "/api/cell/hold", BEARER)[0] == 404
            got = _held(port)
            assert "cell_held" not in got, got
        assert not _table(work / "data" / "chatterly.db")


async def case_in_process_env_unset_never_reads_the_store():
    import cell_hold
    import vault_upload
    assert cell_hold._path is None
    await _seed()
    with cells(on=False), patch.object(cell_hold, "_connect", side_effect=AssertionError("store read")):
        http = FakeHttp()
        st, _ = await post(http, next(FANS), None)
        assert st == 200 and len(http.accepts) == 1, st
        vault_upload.sweep(lambda aid: None)


def _set_hold(op: str = "carve-1") -> None:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c, c:
        c.execute("INSERT INTO cell_holds (scope, why, blocks, op, set_by, set_at)"
                  " VALUES ('cell','carve','writes',?,'test','2026-11-26')", (op,))


def _clear() -> None:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c, c:
        c.execute("UPDATE cell_holds SET released_by='test', released_at='2026-11-26' WHERE released_at IS NULL")


def _drain_now() -> dict:
    import cell_hold
    import fleet_api
    with patch.object(fleet_api, "_SECRET", SECRET):
        return cell_hold.drain(authorization=f"Bearer {SECRET}")


async def case_in_process_every_writer_refused_and_drain_counts_fall():
    import cell_hold
    import cell_mode
    import proxies
    import remote_login
    import send_ops
    import vault_upload
    from _send_kill_cell import restart
    from of_client import OFClient
    with cells(), _executor(True) as ax, patch.object(proxies, "CELLS", True), \
            patch.object(OFClient, "_require_proxy", lambda self, where: None):
        restart()
        cell_mode.install_meta(SYNC_URL)
        await cell_hold.boot(SYNC_URL)
        _set_hold()

        http, _fan = _fresh()
        tick = await ax.run_once(AID, KIND, payload={"n": 0})
        assert (tick.get("status"), tick.get("reason"), tick.get("why")) == ("skipped", "cell_held", "carve"), tick
        assert not http.calls

        fan = next(FANS)
        op = send_ops.op_id("onlyfans", AID, "composer", str(fan), "held")
        try:
            send_ops.dispatch("onlyfans", AID, op, "composer", str(fan), "d", lambda: http.calls.append(1))
            raise AssertionError("manual dispatch went through a writes hold")
        except send_ops.SendRefused as e:
            assert err(e.detail) == "cell_held", e.detail
        assert not http.calls and send_ops.in_flight() == {"claimed": 0, "uncertain": 0}

        st, body = await post(FakeHttp(), next(FANS), "composer-held")
        assert (st, err(body)) == (409, "cell_held"), (st, body)

        for fn in (lambda: vault_upload.sweep(lambda aid: None),
                   lambda: remote_login.start_login(email="a@b.c", password="x", principal=None, platform="onlyfans",
                                                    backend=remote_login.BACKEND_BROWSERBASE)):
            try:
                fn()
                raise AssertionError("writer went through a writes hold")
            except cell_hold.CellHeld as e:
                assert e.status_code == 409 and e.detail["error"] == "cell_held", e.detail

        c = client(http)
        try:
            c._http_call("POST", f"https://onlyfans.com/api2/v2/chats/{fan}/mark-as-read")
            raise AssertionError("transport write outside a claim went through")
        except cell_hold.CellHeld:
            pass
        assert not http.calls

        _clear()
        seen: dict = {}

        def claimed_then_held():
            _set_hold("carve-2")
            seen["during"] = _drain_now()
            return c.send_message(fan, "claimed before the hold")

        op2 = send_ops.op_id("onlyfans", AID, "composer", str(fan), "claimed")
        send_ops.dispatch("onlyfans", AID, op2, "composer", str(fan), send_ops.digest("x"), claimed_then_held)
        assert len(http.accepts) == 1, "send claimed before the hold did not finish"
        assert seen["during"]["held"] is True and seen["during"]["claimed_sends_inflight"] == 1, seen
        assert _drain_now()["claimed_sends_inflight"] == 0
        _clear()

        op3 = send_ops.op_id("onlyfans", AID, "composer", str(fan), "unknown")
        bad = client(FakeHttp(raises(unknown_proxy())))
        with contextlib.suppress(Exception):
            send_ops.dispatch("onlyfans", AID, op3, "composer", str(fan), send_ops.digest("y"),
                              lambda: bad.send_message(fan, "unknown"))
        assert _drain_now()["uncertain_sends"] == 1, _drain_now()
        assert send_ops.resolve(AID, op3, False, "test")
        assert _drain_now()["uncertain_sends"] == 0

        job = remote_login.RemoteLoginJob(id="j-test", email="a@b.c", principal=None, created_at=time.time(),
                                          expires_at=time.time() + 60, platform="onlyfans")
        with remote_login._jobs_lock:
            remote_login._jobs[job.id] = job
        try:
            assert _drain_now()["remote_login_jobs"] == 1
            job.state = remote_login.STATE_DONE
            assert _drain_now()["remote_login_jobs"] == 0
        finally:
            with remote_login._jobs_lock:
                remote_login._jobs.pop(job.id, None)

        assert _drain_now()["held"] is False
        http, _fan = _fresh()
        tick = await ax.run_once(AID, KIND, payload={"n": 1})
        assert tick.get("status") == "ok" and len(http.accepts) == 1, tick


if __name__ == "__main__":
    _harness.run()
