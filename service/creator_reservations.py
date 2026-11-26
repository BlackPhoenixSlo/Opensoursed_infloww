from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import sqlite3
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StrictInt, StrictStr

log = logging.getLogger(__name__)

PENDING_TTL_S = 15 * 60
CALL_TIMEOUT_S = 5.0
ADMITTED_PLATFORMS = frozenset({"onlyfans"})
router = APIRouter()


def _connect(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.execute("PRAGMA busy_timeout=30000")
    return db


@contextlib.contextmanager
def _immediate(path: str):
    with contextlib.closing(_connect(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
        finally:
            if db.in_transaction:
                db.execute("ROLLBACK")


def install(sync_url: str) -> None:
    with contextlib.closing(_connect(sync_url.split("sqlite:///", 1)[1])) as db:
        db.execute("CREATE TABLE IF NOT EXISTS creator_reservations (account_id TEXT PRIMARY KEY,"
                   " platform TEXT NOT NULL, cell TEXT NOT NULL,"
                   " state TEXT CHECK (state IN ('pending','active')), expires_at REAL)")
        have = {r[1] for r in db.execute("PRAGMA table_info(creator_reservations)")}
        for col in ("handoff_op", "handoff_batch"):
            if col not in have:
                db.execute(f"ALTER TABLE creator_reservations ADD COLUMN {col} TEXT")


def reserve(path: str, cell: str, platform: str, account_id: str, state: str,
            now: float | None = None) -> tuple[int, dict]:
    now = time.time() if now is None else now
    with _immediate(path) as db:
        row = db.execute("SELECT platform, cell, state, expires_at FROM creator_reservations"
                         " WHERE account_id = ?", (account_id,)).fetchone()
        live = row is not None and not (row[2] == "pending" and row[3] is not None and row[3] <= now)
        if live and row[1] != cell:
            return 409, {"error": "lives_in_cell", "cell": row[1], "platform": row[0]}
        if live and row[0] != platform:
            return 409, {"error": "PlatformCollision", "cell": row[1], "platform": row[0],
                         "message": f"account {account_id} is already a {row[0]} Creator;"
                                    f" a {platform} session can't be linked to it"}
        active = state == "active" or (live and row[2] == "active")
        got = "active" if active else "pending"
        expires = None if active else now + PENDING_TTL_S
        db.execute("INSERT INTO creator_reservations (account_id, platform, cell, state, expires_at)"
                   " VALUES (?, ?, ?, ?, ?) ON CONFLICT (account_id) DO UPDATE SET platform = excluded.platform,"
                   " cell = excluded.cell, state = excluded.state, expires_at = excluded.expires_at",
                   (account_id, platform, cell, got, expires))
        db.execute("COMMIT")
    return 200, {"account_id": account_id, "platform": platform, "cell": cell, "state": got, "expires_at": expires}


def _batch_sha(from_cell: str, to_cell: str, accounts: list[tuple[str, str]], gen: int) -> str:
    doc = {"from": from_cell, "to": to_cell, "accounts": sorted(f"{p}:{a}" for p, a in accounts), "gen": gen}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def handoff(path: str, op: str, from_cell: str, to_cell: str, accounts: list[tuple[str, str]],
            expect_gen: int, placement_gen: int | None) -> tuple[int, dict]:
    batch = _batch_sha(from_cell, to_cell, accounts, expect_gen)
    want = {a for _p, a in accounts}
    ok = {"op": op, "to_cell": to_cell, "accounts": sorted(f"{p}:{a}" for p, a in accounts)}
    with _immediate(path) as db:
        done = db.execute("SELECT account_id, cell, handoff_batch FROM creator_reservations"
                          " WHERE handoff_op = ?", (op,)).fetchall()
        if done:
            if {r[0] for r in done} == want and all(r[1] == to_cell and r[2] == batch for r in done):
                return 200, {**ok, "status": "already_applied"}
            return 409, {"error": "op_batch_mismatch", "op": op}
        if placement_gen != expect_gen:
            return 409, {"error": "placement_gen_mismatch", "expected": expect_gen, "have": placement_gen}
        for platform, aid in accounts:
            row = db.execute("SELECT platform, cell, state FROM creator_reservations WHERE account_id = ?",
                             (aid,)).fetchone()
            if row is None or row != (platform, from_cell, "active"):
                return 409, {"error": "not_held_by_source", "account": f"{platform}:{aid}",
                             **dict(zip(("platform", "cell", "state"), row or (None, None, None)))}
        db.executemany("UPDATE creator_reservations SET cell = ?, handoff_op = ?, handoff_batch = ?"
                       " WHERE account_id = ?", [(to_cell, op, batch, aid) for _p, aid in accounts])
        db.execute("COMMIT")
    return 200, {**ok, "status": "applied"}


class _Handoff(BaseModel):
    op: StrictStr
    from_cell: StrictStr
    to_cell: StrictStr
    accounts: list[StrictStr]
    expect_placement_gen: StrictInt


def _placement_gen() -> int | None:
    try:
        with open(os.environ["OI_CELL_MAP"], "rb") as fh:
            gen = json.loads(fh.read()).get("generation")
    except (KeyError, OSError, ValueError, AttributeError):
        return None
    return gen if isinstance(gen, int) and not isinstance(gen, bool) else None


@router.post("/api/cell/reservations/handoff")
def take_handoff(body: _Handoff, authorization: Annotated[str | None, Header()] = None):
    import agency_copy
    import fleet_api
    import platforms
    if not fleet_api.secret_ok((authorization or "").removeprefix("Bearer ").strip()):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    parsed = [tuple(a.split(":", 1)) for a in body.accounts]
    if (not body.op or not body.from_cell or not body.to_cell or body.from_cell == body.to_cell or not parsed
            or any(len(p) != 2 or p[0] not in platforms.KEYS or not p[1] for p in parsed)
            or len({p[1] for p in parsed}) != len(parsed)):
        return JSONResponse({"detail": {"error": "bad_handoff"}}, status_code=422)
    from db.engine import sync_database_url
    status, out = handoff(agency_copy.db_path(sync_database_url()), body.op, body.from_cell, body.to_cell, parsed,
                          body.expect_placement_gen, _placement_gen())
    log.log(logging.INFO if status == 200 else logging.WARNING, "Cells: reservation hand-off %s %s -> %s (%d): %s",
            body.op, body.from_cell, body.to_cell, status, out)
    return JSONResponse(out if status == 200 else {"detail": out}, status_code=status)


class _Claim(BaseModel):
    creator_id: StrictStr
    platform: StrictStr
    state: Literal["pending", "active"]


@router.post("/fleet/reservations")
def take(body: _Claim, authorization: Annotated[str | None, Header()] = None):
    import agency_copy
    import platforms
    cell = agency_copy._caller(authorization)
    if cell is None:
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    if not body.creator_id or body.platform not in platforms.KEYS:
        return JSONResponse({"detail": {"error": "bad_reservation"}}, status_code=422)
    from db.engine import sync_database_url
    status, out = reserve(agency_copy.db_path(sync_database_url()), cell, body.platform, body.creator_id,
                          body.state)
    if status != 200:
        log.warning("Cells: reservation %s:%s for %s refused: %s", body.platform, body.creator_id, cell, out)
    return JSONResponse(out if status == 200 else {"detail": out}, status_code=status)


def _refusal(status: int, error: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": error, **extra})


def claim_on_control(platform: str, account_id: str, state: str) -> dict:
    import httpx

    import accounts
    url = os.environ.get("OI_CELL_CONTROL_URL", "").rstrip("/")
    if not url:
        raise _refusal(503, "control_unreachable", account_id=account_id, why="OI_CELL_CONTROL_URL unset")
    try:
        r = httpx.post(f"{url}/fleet/reservations", timeout=CALL_TIMEOUT_S,
                       json={"creator_id": account_id, "platform": platform, "state": state},
                       headers={"Authorization": f"Bearer {os.environ.get('OI_CELL_COPY_KEY', '')}"})
    except httpx.HTTPError as e:
        log.error("Cells: control unreachable for the %s reservation of %s: %s", state, account_id, e)
        raise _refusal(503, "control_unreachable", account_id=account_id) from None
    if r.status_code == 200:
        return r.json()
    detail = None
    with contextlib.suppress(ValueError, AttributeError):
        detail = r.json().get("detail")
    detail = detail if isinstance(detail, dict) else {}
    if r.status_code == 409 and detail.get("error") == "PlatformCollision":
        raise accounts.PlatformCollision(f"{detail.get('message')} (Cell {detail.get('cell')})")
    if r.status_code == 409 and detail.get("error") == "lives_in_cell":
        raise _refusal(409, "lives_in_cell", cell=detail.get("cell"), account_id=account_id)
    log.error("Cells: control answered %d to the %s reservation of %s", r.status_code, state, account_id)
    raise _refusal(503, "control_unreachable", account_id=account_id, status=r.status_code)


def admit(account_id: str, platform: str) -> None:
    import cell_mode
    aid = str(account_id)
    if platform not in ADMITTED_PLATFORMS:
        raise _refusal(409, "platform_not_admitted", platform=platform, account_id=aid)
    if not cell_mode.owned(platform, aid):
        raise _refusal(409, "not_owner", account_id=aid)
    claim_on_control(platform, aid, "pending")


def activate(account_id: str) -> None:
    import accounts
    try:
        claim_on_control(accounts.get_platform(account_id), str(account_id), "active")
    except Exception as e:
        log.error("Cells: CREATOR RESERVATION NOT ACTIVE for %s (%s: %s); it expires in %d min unless retried",
                  account_id, type(e).__name__, getattr(e, "detail", e), PENDING_TTL_S // 60)
