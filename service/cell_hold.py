from __future__ import annotations

import contextlib
import logging
import sqlite3
from typing import Annotated, NamedTuple

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

import cell_mode

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
    global _path
    _path = sync_url.split("sqlite:///", 1)[1]
    gen = cell_mode.data_gen()
    with contextlib.closing(_connect()) as db:
        db.execute(DDL)
        if "last_data_gen" not in {r[1] for r in db.execute("PRAGMA table_info(cell_meta)")}:
            db.execute("ALTER TABLE cell_meta ADD COLUMN last_data_gen INTEGER")
        last = db.execute("SELECT COALESCE(last_data_gen, 1) FROM cell_meta").fetchone()[0]
        if gen is None or gen <= last:
            return []
        op = f"data_gen {last}->{gen}"
        held = sorted((p, a) for a, p in cell_mode._owned_platforms().items())
        db.execute("BEGIN IMMEDIATE")
        for platform, account in held:
            db.execute(f"INSERT INTO cell_holds (scope, platform, account, why, blocks, op, set_by, set_at)"
                       f" SELECT 'creator', ?, ?, 'restore', 'automations', ?, 'boot', {_NOW} WHERE NOT EXISTS"
                       " (SELECT 1 FROM cell_holds WHERE platform=? AND account=? AND why='restore' AND op=?"
                       " AND released_at IS NULL)", (platform, account, op, platform, account, op))
        db.execute("COMMIT")
    log.warning("Cells: restore Cell hold (%s) on %d Creator(s): automated sends wait for a person's release",
                op, len(held))
    return held


async def boot(sync_url: str) -> list[tuple[str, str]]:
    if restored := install(sync_url):
        import automation_executor
        n = await automation_executor.park_restore([a for _, a in restored])
        log.warning("Cells: %d due job(s) parked as may have sent (restore)", n)
    with contextlib.closing(_connect()) as db:
        db.execute("UPDATE cell_meta SET last_data_gen=?", (cell_mode.data_gen(),))
    return restored


def holds() -> list[Hold]:
    if _path is None:
        return []
    with contextlib.closing(_connect()) as db:
        return [Hold(*r) for r in db.execute(f"SELECT {_COLS} FROM cell_holds WHERE released_at IS NULL ORDER BY id")]


class CellHeld(HTTPException):
    def __init__(self, hold: Hold):
        super().__init__(status_code=409, detail={"error": "cell_held", "why": hold.why, "op": hold.op})


def writes_held() -> Hold | None:
    if _path is None:
        return None
    with contextlib.closing(_connect()) as db:
        row = db.execute(f"SELECT {_COLS} FROM cell_holds WHERE released_at IS NULL AND scope='cell'"
                         " AND blocks='writes' ORDER BY id LIMIT 1").fetchone()
    return None if row is None else Hold(*row)


def refuse_writes() -> None:
    if (hold := writes_held()) is not None:
        raise CellHeld(hold)


def active(platform: str, account: str) -> Hold | None:
    for h in holds():
        if h.scope == "cell" or (h.platform, h.account) == (platform, str(account)):
            return h
    return None


def held_ids() -> frozenset[str]:
    owned = cell_mode._owned_platforms()
    rows = holds()
    if any(h.scope == "cell" for h in rows):
        return frozenset(owned)
    return frozenset(h.account for h in rows if owned.get(h.account) == h.platform)


def held(account_id) -> Hold | None:
    platform = cell_mode._owned_platforms().get(str(account_id))
    return None if platform is None else active(platform, str(account_id))


def release_restore(platform: str, account: str, by: str) -> int:
    with contextlib.closing(_connect()) as db:
        return db.execute(f"UPDATE cell_holds SET released_by=?, released_at={_NOW} WHERE scope='creator'"
                          " AND why='restore' AND platform=? AND account=? AND released_at IS NULL",
                          (by, platform, account)).rowcount


router = APIRouter()


def _actor() -> str:
    from auth import get_request_user
    from chatters import get_request_chatter
    if (user := get_request_user()) is not None:
        return f"user:{user.id}:{user.username}"
    if (chatter := get_request_chatter()) is not None:
        return f"chatter:{chatter.id}:{chatter.username}"
    return "anonymous"


@router.get("/api/cell/hold")
def drain(authorization: Annotated[str | None, Header()] = None):
    import fleet_api
    import remote_login
    import send_ops
    if not fleet_api.secret_ok((authorization or "").removeprefix("Bearer ").strip()):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    cell = next((h for h in holds() if h.scope == "cell"), None)
    sends = send_ops.in_flight()
    return {"held": cell is not None, "op": cell and cell.op, "why": cell and cell.why,
            "blocks": cell and cell.blocks, "remote_login_jobs": remote_login.running(),
            "claimed_sends_inflight": sends["claimed"], "uncertain_sends": sends["uncertain"]}


@router.post("/admin/cell-holds/release")
async def release(account_id: str = Query(...)) -> dict:
    from auth import assert_account_owned
    assert_account_owned(account_id)
    platform = cell_mode._owned_platforms().get(account_id)
    if platform is None:
        raise HTTPException(409, {"error": "not_owner", "accounts": [account_id]})
    by = _actor()
    n = release_restore(platform, account_id, by)
    log.warning("Cells: restore Cell hold released for %s:%s by %s (%d row(s)); parked jobs stay parked",
                platform, account_id, by, n)
    left = held(account_id)
    return {"released": n, "held": None if left is None else {"why": left.why, "scope": left.scope}}
