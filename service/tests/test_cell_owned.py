from __future__ import annotations

import _harness

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import socket  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import select  # noqa: E402

_harness.bootstrap()

A, B, C = "900539700124344320", "900539700124344321", "900539700124344322"
ALL = {A, B, C}
CELLS = {"s02": (A,), "s03": (B, C)}
SERVICE = Path(__file__).resolve().parents[1]
WINDOW = "from=2026-11-01&to=2026-11-03"
_placement = Path(tempfile.mkdtemp()) / "placement.json"
_placement.write_text(json.dumps({
    "schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-26T10:00:00Z", "by": "fleet.py",
    "min_cell_proto": 1,
    "cells": {"ctl": {"box": "b1", "epoch": 1, "relay": "127.0.0.1:1", "role": "control", "state": "live"},
              "s02": {"box": "b1", "epoch": 1, "relay": "127.0.0.1:2", "role": "data", "state": "live"},
              "s03": {"box": "b1", "epoch": 1, "relay": "127.0.0.1:3", "role": "data", "state": "live"}},
    "accounts": {f"onlyfans:{a}": sid for sid, accts in CELLS.items() for a in accts}}))
_CELL_ENV = {"OI_CELL_MAP": str(_placement), "OI_CELL_ID": "s02", "OI_CELL_ROLE": "data",
             "OI_ACCOUNTS": f"onlyfans:{A}", "OI_EPOCH": "1"}
os.environ.update(_CELL_ENV)
os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import accounts as account_registry  # noqa: E402
import auth  # noqa: E402
import automation_executor as ax  # noqa: E402
import cell_mode  # noqa: E402
import chatters  # noqa: E402
from automation_registry import register  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AutomationRun, MassRun, ScheduledJob, Transaction, User, UserAccount  # noqa: E402

client = _harness.make_client()
import server  # noqa: E402

MASTER, OWNER = "u-master", "u-owner"


@contextlib.contextmanager
def _env(**kv):
    keys = (*_CELL_ENV, "OI_ACCOUNTS")
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in kv.items() if v is not None})
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _cell(sid: str, role: str = "data"):
    accts = ",".join(f"onlyfans:{a}" for a in CELLS.get(sid, ()))
    return _env(**{**_CELL_ENV, "OI_CELL_ID": sid, "OI_CELL_ROLE": role, "OI_ACCOUNTS": accts})


def _unset():
    return _env()


@contextlib.contextmanager
def _patched(obj, name, value):
    real = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, real)


def _seed() -> None:
    async def go():
        async with get_session() as s:
            if await s.get(Account, A) is not None:
                return
            for aid in sorted(ALL):
                s.add(Account(id=aid))
            s.add(User(id=MASTER, username="master", password="x", is_admin=True))
            s.add(User(id=OWNER, username="owner", password="x", is_admin=False))
            await s.flush()
            for aid in sorted(ALL):
                s.add(UserAccount(user_id=MASTER, account_id=aid))
            for aid in (A, B):
                s.add(UserAccount(user_id=OWNER, account_id=aid))
            for aid, cents in ((A, 1000), (B, 2000), (C, 4000)):
                for day in (1, 2):
                    s.add(Transaction(account_id=aid, kind="tip", amount_cents=cents, status="cleared",
                                      occurred_at=datetime(2026, 11, day, 12), currency="USD", source="ledger"))
    asyncio.run(go())


def _get(path: str, user: str | None):
    client.cookies.clear()
    if user:
        client.cookies.set(auth.COOKIE_NAME, auth._make_cookie(user))
    r = client.get(path)
    assert r.status_code == 200, (path, r.status_code, r.text[:300])
    return r.json()


def _reads(user: str | None) -> tuple[int, set[str]]:
    rev = _get(f"/admin/stats/revenue?{WINDOW}&group_by=kind", user)["rows"]
    rows = _get(f"/admin/stats/per-model?{WINDOW}", user)["per_model"]
    return sum(r["total_cents"] for r in rev), {str(r["account_id"]) for r in rows}


def check_two_cells_split_one_db(user: str | None) -> None:
    _seed()
    with _unset():
        total, listed = _reads(user)
    assert total == 14000 and listed == ALL, (user, total, listed)
    got = {}
    for sid in CELLS:
        with _cell(sid):
            got[sid] = _reads(user)
    assert {sid: g[1] for sid, g in got.items()} == {sid: set(a) for sid, a in CELLS.items()}, (user, got)
    assert sum(g[0] for g in got.values()) == total and all(g[0] for g in got.values()), (user, got)


def case_two_cells_from_one_db_sum_to_the_source_master() -> None:
    check_two_cells_split_one_db(MASTER)


def case_two_cells_from_one_db_sum_to_the_source_anonymous() -> None:
    check_two_cells_split_one_db(None)


def case_env_unset_is_a_no_op() -> None:
    ids = frozenset(ALL)
    with _unset():
        assert cell_mode.owned_set() is None
        assert cell_mode.clamp(ids) is ids and cell_mode.clamp(None) is None
        assert auth.AuthedUser(MASTER, "m", ids).account_ids is ids
        assert auth.clamp_account_filter(None) is None and auth.clamp_account_filter(B) == [B]
        assert ax._owned_only(ScheduledJob.account_id) == ()


def case_cell_owned_keys_by_platform() -> None:
    with _cell("s02"):
        assert A in cell_mode.owned_set() and B not in cell_mode.owned_set()
        assert cell_mode.owned("onlyfans", A) and not cell_mode.owned("fansly", A)
    with _cell("ctl", role="control"):
        assert cell_mode.owned_set() == frozenset(), "Control owns no Creator"
    with _env(**{**_CELL_ENV, "OI_ACCOUNTS": None}):
        assert cell_mode.owned_set() == frozenset(), "Cells map set without OI_ACCOUNTS fails closed"
    with _env(OI_ACCOUNTS=f"onlyfans:{A}"):
        assert cell_mode.owned_set() is None, "OI_ACCOUNTS without the Cells map is not a Cell"


def check_actor_and_master_clamp() -> None:
    _seed()

    async def ids_for(uid, admin):
        async with get_session() as s:
            return await auth.account_ids_for(s, uid, admin)
    with _cell("s03"):
        assert auth.AuthedUser(MASTER, "m", asyncio.run(ids_for(MASTER, True))).account_ids == {B, C}
        assert auth.AuthedUser(OWNER, "o", asyncio.run(ids_for(OWNER, False))).account_ids == {B}
        ident = chatters.ChatterIdentity(id_="c1", username="c", display_name=None, color=None,
                                         owner_user_ids=frozenset({OWNER}), account_ids=frozenset({A, B}))
        assert ident.account_ids == {B}, ident.account_ids
        assert sorted(auth.clamp_account_filter(None)) == [B, C]
    with _cell("ctl", role="control"):
        assert auth.AuthedUser(OWNER, "o", frozenset({A, B})).account_ids == {A, B}, "Control keeps grant sets"
        assert auth.clamp_account_filter(None) == []


def case_actor_and_master_ids_clamp_to_owned() -> None:
    check_actor_and_master_clamp()


def case_control_reads_no_creator_rows() -> None:
    _seed()
    for user in (MASTER, None):
        with _cell("ctl", role="control"):
            assert _reads(user) == (0, set()), (user, _reads(user))


@register("t_owned_noop")
async def _t_noop(account_id: str, payload: dict, *, run_id: int) -> dict:
    return {}


def check_non_owned_due_job_never_claimed() -> None:
    _seed()

    async def go():
        tag = uuid.uuid4().hex
        async with get_session() as s:
            await s.execute(ScheduledJob.__table__.delete().where(ScheduledJob.kind == "t_owned_noop"))
            for aid in (A, B):
                s.add(ScheduledJob(account_id=aid, kind="t_owned_noop", payload_json=json.dumps({"t": tag}),
                                   status="pending", run_at=datetime.utcnow() - timedelta(seconds=5)))
        await ax._drain_due_jobs_once()
        deadline = time.monotonic() + 20
        while ax._inflight_tasks and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        async with get_session() as s:
            rows = (await s.execute(select(ScheduledJob.account_id, ScheduledJob.status).where(
                ScheduledJob.kind == "t_owned_noop", ScheduledJob.payload_json.contains(tag)))).all()
        return dict(rows)
    with _cell("s02"):
        st = asyncio.run(go())
    assert st[B] == "pending" and st[A] != "pending", st


def case_non_owned_due_job_is_never_claimed() -> None:
    check_non_owned_due_job_never_claimed()


def check_orphan_recovery_skips_non_owned() -> None:
    _seed()

    async def go():
        async with get_session() as s:
            await s.execute(ScheduledJob.__table__.delete().where(ScheduledJob.status == "running"))
            for aid in (A, B):
                s.add(ScheduledJob(account_id=aid, kind="t_owned_noop", payload_json="{}", status="running",
                                   run_at=datetime.utcnow()))
                s.add(AutomationRun(account_id=aid, kind="t_owned_noop", status="running"))
                s.add(MassRun(account_id=aid, status="running"))
        await ax._reconcile_orphans()
        async with get_session() as s:
            jobs = dict((await s.execute(select(ScheduledJob.account_id, ScheduledJob.status).where(
                ScheduledJob.kind == "t_owned_noop", ScheduledJob.account_id.in_((A, B)),
                ScheduledJob.payload_json == "{}"))).all())
            runs = {r.account_id: r.status for r in (await s.execute(select(AutomationRun))).scalars()}
            masses = {r.account_id: r.status for r in (await s.execute(select(MassRun))).scalars()}
        return jobs, runs, masses
    with _cell("s02"):
        jobs, runs, masses = asyncio.run(go())
    assert jobs == {A: "pending", B: "running"}, jobs
    assert runs[A] == "error" and runs[B] == "running", runs
    assert masses[A] != "running" and masses[B] == "running", masses


def case_orphan_recovery_skips_non_owned_rows() -> None:
    check_orphan_recovery_skips_non_owned()


def case_pumps_start_only_for_owned() -> None:
    started: list[str] = []
    with _patched(account_registry, "list_accounts",
                  lambda include_watchers=False: [{"id": a, "has_session": True} for a in sorted(ALL)]), \
            _patched(server, "_start_account_pump", started.append), _cell("s03"):
        asyncio.run(server._reconcile_pumps())
    assert sorted(started) == [B, C], started


def _red(check, *args) -> None:
    try:
        check(*args)
    except AssertionError:
        return
    raise AssertionError(f"{check.__name__} stayed green with its filter dropped")


def case_dropping_a_filter_turns_red() -> None:
    with _patched(ax, "_CELLS", False):
        _red(check_non_owned_due_job_never_claimed)
    with _patched(ax, "_owned_only", lambda col: ()):
        _red(check_orphan_recovery_skips_non_owned)
    with _patched(cell_mode, "clamp", lambda ids: ids):
        _red(check_actor_and_master_clamp)
    with _patched(cell_mode, "read_scope", lambda ids: ids):
        _red(check_two_cells_split_one_db, None)


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def case_running_relays_on_one_db_copy() -> None:
    _seed()
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        procs, ports = [], {}
        try:
            for sid in ("main", *CELLS):
                work = root / sid
                (work / "home").mkdir(parents=True)
                db = work / "relay.db"
                with contextlib.closing(sqlite3.connect(_harness.DB_PATH)) as src, \
                        contextlib.closing(sqlite3.connect(db)) as dst:
                    src.backup(dst)
                env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(work / "home"),
                       "TMPDIR": str(work), "CHATTERLY_TEST_MODE": "1", "SHARE_TOKEN": "",
                       "ALLOW_ANONYMOUS_ADMIN": "1", "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
                       "CHATTERLY_DB_URL": f"sqlite:///{db}", "SESSION_SECRET": "cell-owned-session",
                       "CHATTER_SESSION_SECRET": "cell-owned-chatter", "ADMIN_PASSWORD": "cell-owned-admin",
                       "VAPID_KEY_FILE": str(work / "vapid.pem")}
                if sid != "main":
                    env |= {**_CELL_ENV, "OI_CELL_ID": sid,
                            "OI_ACCOUNTS": ",".join(f"onlyfans:{a}" for a in CELLS[sid])}
                port = ports[sid] = _port()
                log = open(work / "relay.log", "wb")
                procs.append((subprocess.Popen(["nice", "-n", "10", sys.executable, "-m", "uvicorn", "server:app",
                                                "--host", "127.0.0.1", "--port", str(port)],
                                               cwd=SERVICE, env=env, stdout=log, stderr=subprocess.STDOUT), log, work))
            deadline = time.monotonic() + 240
            for (p, _log, work), port in zip(procs, ports.values()):
                while True:
                    assert p.poll() is None, (work / "relay.log").read_text()[-3000:]
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/livez", timeout=5) as r:
                            if r.status == 200:
                                break
                    except OSError:
                        pass
                    assert time.monotonic() < deadline, "relay never answered /livez"
                    time.sleep(0.5)

            def read(port):
                def j(path):
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=30) as r:
                        return json.loads(r.read())
                rows = j(f"/admin/stats/per-model?{WINDOW}")["per_model"]
                return (sum(r["total_cents"] for r in j(f"/admin/stats/revenue?{WINDOW}&group_by=kind")["rows"]),
                        {str(r["account_id"]) for r in rows})
            got = {sid: read(port) for sid, port in ports.items()}
        finally:
            for p, log, _work in procs:
                p.terminate()
                try:
                    p.wait(30)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
                log.close()
    main = got.pop("main")
    assert main == (14000, ALL), main
    assert sum(g[0] for g in got.values()) == main[0], got
    assert {sid: g[1] for sid, g in got.items()} == {sid: set(a) for sid, a in CELLS.items()}, got
    print(f"    relays: main={main[0]} " + " ".join(f"{sid}={g[0]}:{sorted(g[1])}" for sid, g in got.items()))


_harness.run()
