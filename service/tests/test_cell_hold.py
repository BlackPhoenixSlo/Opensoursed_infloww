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
from types import SimpleNamespace  # noqa: E402
from unittest.mock import patch  # noqa: E402

from _send_kill_cell import AID, SYNC_URL, FakeHttp, Resp, cells, client, post, raises, unknown_proxy  # noqa: E402
from _send_kill_hold import KIND, _executor, _fresh  # noqa: E402

import accounts  # noqa: E402

accounts.get_account = lambda aid: {"id": aid, "nickname": aid}
accounts.get_platform = lambda aid: "onlyfans"
SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE.parent / "fansly"))
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
def _relay(work: Path, cells_on: bool, share_token: str = ""):
    db = work / "data" / "chatterly.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    (work / "home").mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(work / "home"), "TMPDIR": str(work),
           "CHATTERLY_TEST_MODE": "1", "SHARE_TOKEN": share_token, "ALLOW_ANONYMOUS_ADMIN": "1",
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
    command = ["-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)]
    if not cells_on:
        command = ["-c", "import sys, uvicorn, server; assert 'cell_hold' not in sys.modules; "
                   "uvicorn.run(server.app, port=int(sys.argv[1]))", str(port)]
    with open(work / "relay.log", "ab") as log:
        p = subprocess.Popen(["nice", "-n", "10", sys.executable, *command], cwd=SERVICE, env=env, stdout=log, stderr=subprocess.STDOUT)
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
            for method, path, headers, body in WRITES:
                status, _, raw = _ask(port, method, path, headers, body)
                assert (status, json.loads(raw)["detail"]) == (
                    409, {"error": "cell_held", "why": "carve", "op": "carve-1"},
                )
            st, _h, raw = _ask(port, *READ)
            assert st == 200 and _error(raw) is None, (st, raw[:300])
            d = _drain(port)
            assert (d["held"], d["op"], d["why"], d["blocks"]) == (True, "carve-1", "carve", "writes"), d
            assert all(d[k] == 0 for k in ("remote_login_jobs", "claimed_sends_inflight", "uncertain_sends", "writes_inflight")), d
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


def case_fleet_drain_bypasses_share_gate_only_with_fleet_bearer():
    with tempfile.TemporaryDirectory() as t, _relay(Path(t), True, "private-share-token") as port:
        assert _ask(port, "GET", "/api/cell/hold")[0] == 403
        assert _drain(port)["held"] is False
        assert _ask(port, "GET", "/admin/system/runs", BEARER)[0] == 401


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


async def case_env_unset_unconfirmed_response_matches_base():
    from fastapi.responses import JSONResponse
    from unconfirmed_sends_api import list_unconfirmed_sends
    import auth

    token = auth._request_user.set(auth.AuthedUser("u_hold", "hold_owner", frozenset({AID})))
    try:
        with cells(on=False), patch.dict(sys.modules):
            sys.modules.pop("cell_hold", None)
            response = await list_unconfirmed_sends(account_id=AID)
            assert JSONResponse(response).body == b'{"rows":[]}'
            assert "restore_holds" not in response and "cell_hold" not in sys.modules
    finally:
        auth._request_user.reset(token)


def _set_hold(op: str = "carve-1") -> None:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c, c:
        c.execute("INSERT INTO cell_holds (scope, why, blocks, op, set_by, set_at)"
                  " VALUES ('cell','carve','writes',?,'test','2026-11-26')", (op,))


def _clear() -> None:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c, c:
        c.execute("UPDATE cell_holds SET released_by='test', released_at='2026-11-26' WHERE released_at IS NULL")


@contextlib.asynccontextmanager
async def held_cell(*, set_hold: bool = True):
    import cell_hold
    import cell_mode
    from _send_kill_cell import restart

    with cells():
        restart()
        cell_mode.install_meta(SYNC_URL)
        await cell_hold.boot(SYNC_URL)
        if set_hold:
            _set_hold()
        try:
            yield
        finally:
            _clear()


async def _drain_now() -> dict:
    import cell_hold
    import fleet_api
    with patch.object(fleet_api, "_SECRET", SECRET):
        from starlette.requests import Request
        return await cell_hold.drain(Request({"type": "http", "client": ("127.0.0.1", 1), "headers": []}),
                                     authorization=f"Bearer {SECRET}")


async def case_parked_anchor_replay():
    from datetime import datetime
    from sqlalchemy import select
    from db.engine import get_session
    from db.models import ScheduledJob
    import job_queue
    import run_decide
    import send_ops

    await _seed()
    with cells(), _executor(True) as ax:
        jid = await job_queue.enqueue_job(AID, "scheduled_send", op_anchor="parked-replay")
        assert await job_queue.enqueue_job(AID, "scheduled_send", op_anchor="parked-replay") == jid
        await ax.park_restore([AID], datetime.utcnow())
        try:
            await job_queue.enqueue_job(AID, "scheduled_send", op_anchor="parked-replay")
        except send_ops.SendRefused as e:
            assert (e.status_code, e.detail) == (409, {
                "error": "restore_parked", "job_id": jid, "reason": run_decide.RESTORE_REASON,
            })
        else:
            raise AssertionError("parked anchor accepted")
        async with get_session() as s:
            rows = (await s.scalars(select(ScheduledJob).where(
                ScheduledJob.payload_json.contains("parked-replay"),
            ))).all()
            assert [(j.id, j.status, j.last_error) for j in rows] == [(jid, "error", run_decide.RESTORE_REASON)]


async def case_restore_leaves_housekeeping_pending():
    from datetime import datetime
    from db.engine import get_session
    from db.models import ScheduledJob

    await _seed()
    with cells(), _executor(True) as ax:
        async with get_session() as s:
            job = ScheduledJob(account_id=AID, kind="housekeeping", payload_json="{}", run_at=datetime.utcnow())
            s.add(job)
            await s.flush()
            jid = job.id
        await ax.park_restore([AID], datetime.utcnow())
        async with get_session() as s:
            job = await s.get(ScheduledJob, jid)
            assert (job.status, job.last_error) == ("pending", None)


async def case_claim_checks_hold_after_opening_db():
    import cell_hold
    import send_ops

    async with held_cell(set_hold=False):
        connect = send_ops._connect

        def connect_after_hold():
            _set_hold()
            return connect()

        with patch.object(send_ops, "_connect", connect_after_hold):
            try:
                send_ops.begin("onlyfans", AID, "hold-race", "composer", "1", "digest")
            except cell_hold.CellHeld as e:
                assert e.hold.op == "carve-1"
            else:
                raise AssertionError("claim admitted after the hold committed")
        assert send_ops.in_flight()["claimed"] == 0


async def case_partial_automation_waits_and_replays_per_recipient():
    from datetime import datetime
    import send_ops
    from _send_kill_hold import _jobs
    from db.engine import get_session
    from db.models import ScheduledJob
    from job_queue import send_anchor
    from of_write import of_write_paced

    http = FakeHttp()
    c = client(http)
    fans = [next(FANS), next(FANS)]

    def wire(fan):
        out = c.send_message(fan, "scheduled")
        if fan == fans[0]:
            _set_hold()
        return out

    async def run(aid, payload, run_id=None):
        for fan in fans:
            await of_write_paced(aid, lambda: send_ops.automated_sync(
                aid, "scheduled_send", fan, send_anchor(payload), lambda: wire(fan)),
                min_gap_s=0, send_purpose="manual")

    async with held_cell(set_hold=False):
        with _executor(True) as ax, patch.object(ax, "get_automation", return_value=run):
            await _seed()
            async with get_session() as s:
                job = ScheduledJob(account_id=AID, kind="scheduled_send", payload_json="{}", run_at=datetime.utcnow())
                s.add(job)
                await s.flush()
                jid = job.id
            try:
                tick = await ax.run_once(AID, "scheduled_send")
                assert tick.get("reason") == "cell_held", tick
                assert _jobs([jid])[jid] == ("pending", None)
                assert len(http.accepts) == 1
            finally:
                _clear()
            tick = await ax.run_once(AID, "scheduled_send")
            assert tick.get("status") == "ok", tick
            assert _jobs([jid])[jid] == ("done", None)
            assert len(http.accepts) == 2


async def case_retry_rechecks_the_hold_and_counts_the_wire_attempt():
    import cell_hold
    import proxies
    import send_ops

    seen = []

    def first_attempt(fake, url, body):
        seen.append(cell_hold._writes_inflight)
        _set_hold()
        raise unknown_proxy()

    async with held_cell(set_hold=False):
        with patch.object(proxies, "CELLS", True):
            http = FakeHttp(first_attempt)
            c = client(http)
            c.require_proxy = lambda where: None
            try:
                c._http_call("POST", "https://onlyfans.com/api2/v2/chats/1/mark-as-read")
            except cell_hold.CellHeld as e:
                assert send_ops.refusal_reason(e) == "cell_held"
            else:
                raise AssertionError("retry reached the wire during the hold")
            assert len(http.calls) == 1 and seen == [1] and cell_hold._writes_inflight == 0


async def case_request_and_wire_share_a_drain_counter():
    import cell_hold
    from cell_mode import CellGenHeader

    async def app(scope, receive, send):
        assert cell_hold._writes_inflight == 1
        assert cell_hold.wire_write(lambda: cell_hold._writes_inflight) == 2
        raise ValueError("request failed")

    async with held_cell(set_hold=False):
        try:
            await CellGenHeader(app)({"type": "http", "method": "POST"}, None, None)
        except ValueError:
            assert cell_hold._writes_inflight == 0
        else:
            raise AssertionError("middleware swallowed the error")


async def case_planner_and_direct_run_share_one_hold_note():
    from datetime import datetime
    from sqlalchemy import select
    from db.engine import get_session
    from db.models import AutomationRun, ScheduledJob

    async with held_cell(set_hold=False):
        with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c, c:
            c.execute("INSERT INTO cell_holds (scope, platform, account, why, blocks, op, set_by, set_at)"
                      " VALUES ('creator','onlyfans',?,'restore','automations','restore-1','test','2026-11-26')", (AID,))
        _set_hold()
        with _executor(True) as ax:
            async with get_session() as s:
                s.add(ScheduledJob(account_id=AID, kind=KIND, run_at=datetime.utcnow(), payload_json="{}"))
            notes = {}
            assert all(p[0] != AID for p in await ax._due_job_pairs(notes))
            assert notes[AID][1].why == "carve"
            query = select(AutomationRun).where(AutomationRun.account_id == AID, ax._is_hold_note(AutomationRun))
            async with get_session() as s:
                before = len((await s.scalars(query)).all())
            tick = await ax.run_once(AID, KIND, payload={"n": 0})
            assert tick.get("why") == "carve"
            async with get_session() as s:
                rows = (await s.scalars(query.order_by(AutomationRun.id))).all()
                assert len(rows) == before + 1
                rows[-1].stats_json = json.dumps(json.loads(rows[-1].stats_json), sort_keys=True, separators=(",", ":"))
            await ax._record_hold_notes(notes)
            async with get_session() as s:
                assert len((await s.scalars(query)).all()) == before + 1


async def case_login_registers_before_checking_hold():
    import cell_hold
    import remote_login

    register = remote_login._register

    def register_after_hold(job):
        _set_hold()
        register(job)

    async with held_cell(set_hold=False):
        with patch.object(remote_login, "_register", register_after_hold), \
                patch.object(remote_login, "bb_env") as config, patch.object(remote_login.threading, "Thread") as thread:
            try:
                remote_login.start_login(email="hold@test.invalid", password="x", principal=None,
                                         backend=remote_login.BACKEND_BROWSERBASE, platform="onlyfans")
            except cell_hold.CellHeld:
                pass
            else:
                raise AssertionError("login admitted after the hold committed")
            assert remote_login.running() == 0
            thread.assert_not_called()
            config.assert_not_called()


def case_first_install_at_later_generation_holds():
    import cell_hold
    import cell_mode

    with tempfile.TemporaryDirectory() as t, cells(), patch.object(cell_hold, "_path"), \
            patch.object(cell_mode, "_data_gen"):
        db = Path(t) / "migration.db"
        with contextlib.closing(sqlite3.connect(db)) as c, c:
            c.execute("CREATE TABLE cell_meta (data_gen INTEGER)")
            c.execute("INSERT INTO cell_meta VALUES (7)")
        url = f"sqlite:///{db}"
        cell_mode.install_meta(url)
        assert cell_hold.install(url) == [("onlyfans", AID)]
        assert [h.op for h in cell_hold.holds()] == ["data_gen 1->7"]


async def case_drain_rejects_non_loopback_peer():
    import cell_hold
    import fleet_api
    from starlette.requests import Request

    with patch.object(fleet_api, "_SECRET", SECRET):
        req = Request({"type": "http", "client": ("192.0.2.1", 1)})
        result = await cell_hold.drain(req, authorization=f"Bearer {SECRET}")
    assert result.status_code == 403
    with tempfile.TemporaryDirectory() as t, _relay(Path(t), True) as port:
        assert _ask(port, "GET", "/api/cell/hold", {**BEARER, "X-Forwarded-For": "127.0.0.1"})[0] == 403


def case_fresh_cell_features_include_restore_release():
    with patch.object(sys, "path", [str(SERVICE.parent / "scripts"), *sys.path]):
        import cell_features

    scope, kinds = cell_features.load()
    fresh, _ = cell_features.draft(scope, kinds, None)
    assert "POST /admin/cell-holds/release" in fresh["features"]["Automation rules"]["routes"]


async def case_in_process_every_writer_refused_and_drain_counts_fall():
    import cell_hold
    import proxies
    import remote_login
    import send_ops
    import vault_upload
    from of_client import OFClient
    async with held_cell():
        with _executor(True) as ax, patch.object(proxies, "CELLS", True), \
                patch.object(OFClient, "require_proxy", lambda self, where: None):

            http, _fan = _fresh()
            tick = await ax.run_once(AID, KIND, payload={"n": 0})
            assert (tick.get("status"), tick.get("reason"), tick.get("why")) == ("skipped", "cell_held", "carve"), tick
            assert not http.calls

            fan = next(FANS)
            op = send_ops.op_id("onlyfans", AID, "composer", str(fan), "held")
            try:
                send_ops.dispatch("onlyfans", AID, op, "composer", str(fan), "d", lambda: http.calls.append(1))
                raise AssertionError("manual dispatch went through a writes hold")
            except cell_hold.CellHeld as e:
                assert e.hold.op == "carve-1"
            assert not http.calls and send_ops.in_flight() == {"claimed": 0, "uncertain": 0}

            composer = FakeHttp()
            try:
                await post(composer, next(FANS), "composer-held")
                raise AssertionError("composer route claimed through a writes hold")
            except cell_hold.CellHeld as e:
                r = await cell_hold.refused(None, e)
                assert (r.status_code, json.loads(r.body)["detail"]["error"]) == (409, "cell_held"), r.body
            assert not composer.calls

            for fn in (lambda: vault_upload.sweep(lambda aid: None),
                       lambda: remote_login.start_login(email="a@b.c", password="x", principal=None, platform="onlyfans",
                                                        backend=remote_login.BACKEND_BROWSERBASE)):
                try:
                    fn()
                    raise AssertionError("writer went through a writes hold")
                except cell_hold.CellHeld as e:
                    assert e.hold.why == "carve", e.hold

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
                seen["during"] = send_ops.in_flight()["claimed"]
                return c.send_message(fan, "claimed before the hold")

            op2 = send_ops.op_id("onlyfans", AID, "composer", str(fan), "claimed")
            send_ops.dispatch("onlyfans", AID, op2, "composer", str(fan), send_ops.digest("x"), claimed_then_held)
            assert len(http.accepts) == 1, "send claimed before the hold did not finish"
            assert seen["during"] == 1, seen
            assert (await _drain_now())["claimed_sends_inflight"] == 0
            _clear()

            op3 = send_ops.op_id("onlyfans", AID, "composer", str(fan), "unknown")
            bad = client(FakeHttp(raises(unknown_proxy())))
            with contextlib.suppress(Exception):
                send_ops.dispatch("onlyfans", AID, op3, "composer", str(fan), send_ops.digest("y"),
                                  lambda: bad.send_message(fan, "unknown"))
            assert (await _drain_now())["uncertain_sends"] == 1, await _drain_now()
            assert send_ops.resolve(AID, op3, False, "test")
            assert (await _drain_now())["uncertain_sends"] == 0

            job = remote_login.RemoteLoginJob(id="j-test", email="a@b.c", principal=None, created_at=time.time(),
                                              expires_at=time.time() + 60, platform="onlyfans")
            with remote_login._jobs_lock:
                remote_login._jobs[job.id] = job
            try:
                assert (await _drain_now())["remote_login_jobs"] == 1
                job.state = remote_login.STATE_DONE
                assert (await _drain_now())["remote_login_jobs"] == 0
            finally:
                with remote_login._jobs_lock:
                    remote_login._jobs.pop(job.id, None)

            assert (await _drain_now())["held"] is False
            http, _fan = _fresh()
            tick = await ax.run_once(AID, KIND, payload={"n": 1})
            assert tick.get("status") == "ok" and len(http.accepts) == 1, tick



async def case_fansly_write_held_without_tripwire_preloaded():
    import cell_hold
    from fansly_client import FanslyClient

    sent = []
    c = object.__new__(FanslyClient)
    c.dry_run, c.timeout = False, 1
    c._headers = lambda *a, **k: {}
    c.http = SimpleNamespace(request=lambda *a, **k: sent.append(a) or Resp(200, {"success": True}))
    async with held_cell():
        with patch.dict(sys.modules):
            sys.modules.pop("send_tripwire")
            try:
                c._request("POST", "/message", json_body={"content": "x"})
                raise AssertionError("Fansly write went out under a writes hold")
            except cell_hold.CellHeld:
                pass
    assert not sent


class _UploadHttp(FakeHttp):
    def post(self, url, multipart=None, headers=None, timeout=None):
        self.calls.append(("POST", url, None))
        return Resp(200, {"id": 1}, url)


async def case_claimed_send_upload_finishes_under_writes_hold_unclaimed_refused():
    import cell_hold
    import proxies
    import send_ops
    from of_client import OFClient

    convert = "https://convert.onlyfans.com/file/upload"
    media = dict(s3_etag="e", s3_location="l", s3_key="k", s3_bucket="b", filename="f.jpg")
    async with held_cell(set_hold=False):
        with patch.object(proxies, "CELLS", True), patch.object(OFClient, "require_proxy", lambda self, where: None):
            http = _UploadHttp()
            c = client(http)
            fan = next(FANS)

            def upload_then_send():
                _set_hold("carve-3")
                c.convert_register(**media)
                return c.send_message(fan, "claimed with media")

            op = send_ops.op_id("onlyfans", AID, "composer", str(fan), "upload")
            send_ops.dispatch("onlyfans", AID, op, "composer", str(fan), send_ops.digest("u"), upload_then_send)
            assert http.calls[0][1] == convert and len(http.accepts) == 1, http.calls
            try:
                c.convert_register(**media)
                raise AssertionError("unclaimed upload went through a writes hold")
            except cell_hold.CellHeld as e:
                assert e.hold.op == "carve-3"
            assert len(http.calls) == 2 and cell_hold._writes_inflight == 0, http.calls


async def case_mass_cancel_resumes_unfinished_targets():
    from _send_kill_hold import _jobs

    def first_cancel(http, url, body):
        _set_hold()
        return Resp(200, {}, url)

    http = FakeHttp(first_cancel)
    async with held_cell(set_hold=False):
        with _executor(True) as ax, patch.object(ax, "_make_client", return_value=client(http)):
            await _seed()
            jid = await ax.enqueue_job(AID, "unsend_messages",
                                       payload={"targets": [{"queue_id": 801}, {"queue_id": 802}]})
            tick = await ax.run_once(AID, "unsend_messages")
            assert tick.get("reason") == "cell_held", tick
            assert _jobs([jid])[jid] == ("pending", None)
            _clear()
            tick = await ax.run_once(AID, "unsend_messages")
            assert tick.get("status") == "ok", tick
            assert _jobs([jid])[jid] == ("done", None)
            assert [c[:2] for c in http.calls] == [
                ("DELETE", "/messages/queue/801"), ("DELETE", "/messages/queue/802")], http.calls


class _ExcludeHttp(FakeHttp):
    def __init__(self):
        super().__init__()
        self.members = []
        self.lid = None
        self.hold_on_read = True
        self.list_writes_inflight = []

    def get(self, url, headers=None, timeout=None):
        return self.request("GET", url, headers=headers, timeout=timeout)

    def request(self, method, url, json=None, headers=None, timeout=None):
        path = url.split("/api2/v2")[-1].split("?")[0]
        self.calls.append((method, path, json))
        if method == "GET" and path == "/lists":
            if self.hold_on_read:
                self.hold_on_read = False
                _set_hold()
            rows = [] if self.lid is None else [{"id": self.lid, "name": "Auto_Exclude"}]
            return Resp(200, {"list": rows, "hasMore": False}, url)
        if method == "GET" and path == "/lists/73/users":
            return Resp(200, {"list": [{"id": uid} for uid in self.members], "hasMore": False}, url)
        if method != "GET" and (path == "/lists" or path.startswith("/lists/73/users/")):
            import cell_hold
            self.list_writes_inflight.append(cell_hold._writes_inflight)
        if method == "POST" and path == "/lists":
            self.lid = 73
            return Resp(200, {"id": self.lid}, url)
        if path.startswith("/lists/73/users/"):
            uid = int(path.rsplit("/", 1)[-1])
            (self.members.append if method == "POST" else self.members.remove)(uid)
            return Resp(200, {}, url)
        assert (method, path) == ("POST", "/messages/queue"), (method, path)
        assert json["excludedLists"] == [73], json
        self.accepts.append(json)
        return Resp(200, {"id": 123}, url)


async def case_auto_exclude_hold_defers_scheduled_broadcast():
    import of_write
    from _send_kill_hold import _jobs

    from _send_kill_hold import _db

    async with held_cell(set_hold=False):
        await _seed()
        for existing in (False, True):
            http = _ExcludeHttp()
            if existing:
                http.lid, http.members = 73, [801, 802]
            with _executor(True) as ax, patch.object(ax, "_make_client", return_value=client(http)):
                of_write._write_gates.pop(AID, None)
                prior_runs = _db("SELECT id FROM mass_runs WHERE account_id=?", (AID,))
                jid = await ax.enqueue_job(AID, "send_mass_message", payload={
                    "text": "held broadcast", "user_lists": ["fans"], "excluded_users": [802]})
                tick = await ax.run_once(AID, "send_mass_message")
                assert tick.get("reason") == "cell_held", tick
                assert _jobs([jid])[jid] == ("pending", None)
                assert _db("SELECT id FROM mass_runs WHERE account_id=?", (AID,)) == prior_runs
                assert all(method == "GET" for method, _, _ in http.calls), http.calls
                _clear()
                tick = await ax.run_once(AID, "send_mass_message")
                assert tick.get("status") == "ok", tick
                assert _jobs([jid])[jid] == ("done", None)
                assert len(http.accepts) == 1 and http.members == [802], http.calls


async def case_manual_mass_claim_covers_auto_exclude():
    import mass_queue_api as mq
    from _send_kill_cell import request, route
    from _send_kill_manual import rows

    http = _ExcludeHttp()
    async with held_cell(set_hold=False):
        await _seed()
        req = request({"x-op-id": "exclude-after-claim"})
        with route(req, client(http)):
            result = await mq.of_send_or_schedule_mass(
                req, mq._MassScheduleBody(text="claimed broadcast", user_lists=["fans"], excluded_users=[802]))
        assert result["id"] == 123 and len(http.accepts) == 1 and http.members == [802], http.calls
        assert http.list_writes_inflight == [1, 1], http.calls
        row = rows("manual_mass_send", 802, "exclude-after-claim")
        assert [(r["state"], r["attempts"]) for r in row] == [("sent", 1)], row


async def case_restore_commit_survives_restart_before_boot_returns():
    from datetime import datetime, timedelta
    import automation_executor as ax
    import cell_hold
    import cell_mode
    import run_decide
    from _send_kill_hold import _jobs

    class InterruptedBoot(Exception):
        pass

    original_park = ax.park_restore

    async def stop_after_commit(*args, **kwargs):
        await original_park(*args, **kwargs)
        raise InterruptedBoot

    cutoff = datetime.utcnow()
    async with held_cell(set_hold=False):
        await _seed()
        overdue = await ax.enqueue_job(AID, "scheduled_send", run_at=cutoff - timedelta(seconds=1))
        later = await ax.enqueue_job(AID, "scheduled_send", run_at=cutoff + timedelta(seconds=1))
        with contextlib.closing(sqlite3.connect(_harness.DB_PATH)) as db, db:
            db.execute("UPDATE cell_meta SET data_gen=2")
        cell_mode.install_meta(SYNC_URL)
        try:
            with patch.object(cell_hold, "datetime") as clock:
                clock.utcnow.return_value = cutoff
                with patch.object(ax, "park_restore", stop_after_commit):
                    try:
                        await cell_hold.boot(SYNC_URL)
                    except InterruptedBoot:
                        pass
                    else:
                        raise AssertionError("parking did not reach the commit boundary")
                clock.utcnow.return_value = cutoff + timedelta(seconds=2)
                await cell_hold.boot(SYNC_URL)
            assert _jobs([overdue, later]) == {
                overdue: ("error", run_decide.RESTORE_REASON), later: ("pending", None)}
        finally:
            with contextlib.closing(sqlite3.connect(_harness.DB_PATH)) as db, db:
                db.execute("UPDATE cell_meta SET data_gen=1, last_data_gen=1")
            cell_mode.install_meta(SYNC_URL)


if __name__ == "__main__":
    _harness.run()
