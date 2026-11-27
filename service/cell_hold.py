from __future__ import annotations

import contextlib
import logging
from ipaddress import ip_address
from threading import Lock
import sqlite3
from datetime import datetime
from typing import Annotated, NamedTuple

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

import cell_mode
from send_tripwire import CellHeld

log = logging.getLogger("cell-hold")

DDL = """CREATE TABLE IF NOT EXISTS cell_holds (
  id INTEGER PRIMARY KEY,
  scope TEXT NOT NULL CHECK (scope IN ('creator','cell')),
  platform TEXT, account TEXT,
  why TEXT NOT NULL CHECK (why IN ('restore','move','entry_cut','carve')),
  blocks TEXT NOT NULL CHECK (blocks IN ('automations','writes')),
  op TEXT, set_by TEXT NOT NULL, set_at TEXT NOT NULL, released_by TEXT, released_at TEXT,
  CHECK ((scope = 'creator') = (account IS NOT NULL AND platform IS NOT NULL)))"""
_NOW = "strftime('%Y-%m-%d %H:%M:%f','now')"
_COLS = "id, scope, platform, account, why, blocks, op, set_by, set_at"

_path: str | None = None


class Hold(NamedTuple):
    id: int
    scope: str
    platform: str | None
    account: str | None
    why: str
    blocks: str
    op: str | None
    set_by: str
    set_at: str


def _connect() -> sqlite3.Connection:
    if _path is None:
        raise sqlite3.OperationalError("cell_holds store not installed")
    return sqlite3.connect(_path, timeout=30, isolation_level=None)


def install(sync_url: str) -> list[tuple[str, str]]:
    bump = _install(sync_url)
    return [] if bump is None else bump[0]


def _install(sync_url: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]], bool] | None:
    global _path
    _path = sync_url.split("sqlite:///", 1)[1]
    gen = cell_mode.data_gen()
    with contextlib.closing(_connect()) as db:
        db.execute(DDL)
        if "last_data_gen" not in {r[1] for r in db.execute("PRAGMA table_info(cell_meta)")}:
            with db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("ALTER TABLE cell_meta ADD COLUMN last_data_gen INTEGER")
        last = db.execute("SELECT COALESCE(last_data_gen, 1) FROM cell_meta").fetchone()[0]
        if gen is None or gen <= last:
            return None
        op = f"data_gen {last}->{gen}"
        owned = sorted((p, a) for a, p in cell_mode._owned_platforms().items())
        import restore_reconcile
        peek = restore_reconcile.arm(db)
        held = [(p, a) for p, a in owned if not (peek and p == "onlyfans")]
        db.execute("BEGIN IMMEDIATE")
        for platform, account in held:
            db.execute(f"INSERT INTO cell_holds (scope, platform, account, why, blocks, op, set_by, set_at)"
                       f" SELECT 'creator', ?, ?, 'restore', 'automations', ?, 'boot', {_NOW} WHERE NOT EXISTS"
                       " (SELECT 1 FROM cell_holds WHERE platform=? AND account=? AND why='restore' AND op=?"
                       " AND released_at IS NULL)", (platform, account, op, platform, account, op))
        db.execute("COMMIT")
    log.warning("Cells: restore Cell hold (%s) on %d Creator(s): automated sends wait for a person's release",
                op, len(held))
    return held, owned, peek


_queue_check = None


async def boot(sync_url: str) -> list[tuple[str, str]]:
    global _queue_check
    cutoff = datetime.utcnow()
    gen = cell_mode.data_gen()
    if bump := _install(sync_url):
        held, owned, peek = bump
        import automation_executor
        n = await automation_executor.park_restore([a for _, a in owned], cutoff, data_gen=gen)
        log.warning("Cells: %d due job(s) parked as may have sent (restore)", n)
        if peek:
            import asyncio
            import restore_reconcile
            _queue_check = asyncio.create_task(restore_reconcile.boot_queue_check(owned))
        return held
    with contextlib.closing(_connect()) as db:
        db.execute("UPDATE cell_meta SET last_data_gen=?", (gen,))
    return []


def holds(db: sqlite3.Connection | None = None) -> list[Hold]:
    if _path is None:
        return []
    if db is None:
        with contextlib.closing(_connect()) as conn:
            return holds(conn)
    return [Hold(*r) for r in db.execute(f"SELECT {_COLS} FROM cell_holds WHERE released_at IS NULL ORDER BY id")]


def blocking(rows: list[Hold], platform: str, account: str, automated: bool) -> Hold | None:
    writes = next((h for h in rows if h.scope == "cell" and h.blocks == "writes"), None)
    if writes is not None or not automated:
        return writes
    return next((h for h in rows if h.scope == "cell" or (h.platform, h.account) == (platform, account)), None)


async def refused(request: Request, exc: CellHeld) -> JSONResponse:
    return JSONResponse({"detail": {"error": "cell_held", "why": exc.hold.why, "op": exc.hold.op}},
                        status_code=409)


_write_lock = Lock()
_writes_inflight = 0


@contextlib.contextmanager
def writing():
    global _writes_inflight
    with _write_lock:
        _writes_inflight += 1
    try:
        yield
    finally:
        with _write_lock:
            _writes_inflight -= 1


def wire_write(fn):
    with writing():
        refuse_writes()
        return fn()


def writes_held() -> Hold | None:
    return blocking(holds(), "", "", False)


def refuse_writes() -> None:
    if (hold := writes_held()) is not None:
        raise CellHeld(hold)


def held(account_id) -> Hold | None:
    platform = cell_mode._owned_platforms().get(str(account_id))
    return None if platform is None else blocking(holds(), platform, str(account_id), True)


_RESTORE_MATCH = "scope='creator' AND why='restore' AND platform=? AND account=? AND released_at IS NULL"


def restore_holds(platform: str, account: str) -> list[Hold]:
    if _path is None:
        return []
    with contextlib.closing(_connect()) as db:
        return [Hold(*r) for r in db.execute(f"SELECT {_COLS} FROM cell_holds WHERE {_RESTORE_MATCH} ORDER BY id",
                                             (platform, account))]


def release_restore(platform: str, account: str, by: str, op: str | None = None) -> int:
    args = (by, platform, account)
    match_op = ""
    if op is not None:
        match_op = " AND op=?"
        args += (op,)
    with contextlib.closing(_connect()) as db:
        return db.execute(f"UPDATE cell_holds SET released_by=?, released_at={_NOW} WHERE {_RESTORE_MATCH}{match_op}",
                          args).rowcount


router = APIRouter()


@router.get("/api/cell/hold")
async def drain(request: Request, authorization: Annotated[str | None, Header()] = None):
    from automation_executor import runs_inflight
    from starlette.concurrency import run_in_threadpool
    import fleet_api
    import remote_login
    import send_ops
    try:
        local = request.client is not None and ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if not local or "x-forwarded-for" in request.headers:
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    if not fleet_api.secret_ok((authorization or "").removeprefix("Bearer ").strip()):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    cell = next((h for h in await run_in_threadpool(holds) if h.scope == "cell"), None)
    sends = await run_in_threadpool(send_ops.in_flight)
    return {"held": cell is not None, "op": cell and cell.op, "why": cell and cell.why,
            "blocks": cell and cell.blocks, "remote_login_jobs": remote_login.running(),
            "automation_runs_inflight": runs_inflight(), "writes_inflight": _writes_inflight,
            "claimed_sends_inflight": sends["claimed"], "uncertain_sends": sends["uncertain"]}


@router.post("/admin/cell-holds/release")
async def release(account_id: str = Query(...), op: str | None = None) -> dict:
    from auth import assert_account_owned, get_request_user
    user = get_request_user()
    if user is None:
        raise HTTPException(403, "owner authorization required")
    assert_account_owned(account_id)
    platform = cell_mode._owned_platforms().get(account_id)
    if platform is None:
        raise HTTPException(409, {"error": "not_owner", "accounts": [account_id]})
    by = f"user:{user.id}:{user.username}"
    n = release_restore(platform, account_id, by, op)
    log.warning("Cells: restore Cell hold released for %s:%s by %s (%d row(s)); parked jobs stay parked",
                platform, account_id, by, n)
    left = held(account_id)
    return {"released": n, "held": None if left is None else {"why": left.why, "scope": left.scope}}
