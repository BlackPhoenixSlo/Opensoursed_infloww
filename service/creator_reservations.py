from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StrictInt, StrictStr

from agency_copy import caller, db_path, matching_digest
from cell_mode import refusal, read_placement

log = logging.getLogger(__name__)

PENDING_TTL_S = 15 * 60
CALL_TIMEOUT_S = 5.0
ADMITTED_PLATFORMS = frozenset({"onlyfans"})
router = APIRouter()
_activation_lock = threading.Lock()
_reseed_activations = threading.Event()
_pending_activation: set[tuple[str, str]] = set()


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
    with contextlib.closing(_connect(db_path(sync_url))) as db:
        db.execute("CREATE TABLE IF NOT EXISTS creator_reservations (account_id TEXT PRIMARY KEY,"
                   " platform TEXT NOT NULL, cell TEXT NOT NULL,"
                   " state TEXT CHECK (state IN ('pending','active')), expires_at REAL)")
        db.execute("CREATE TABLE IF NOT EXISTS creator_handoff_ops (op TEXT PRIMARY KEY, batch TEXT NOT NULL)")
        have = {r[1] for r in db.execute("PRAGMA table_info(creator_reservations)")}
        for col in ("handoff_op", "handoff_batch"):
            if col not in have:
                db.execute(f"ALTER TABLE creator_reservations ADD COLUMN {col} TEXT")
        db.execute("INSERT OR IGNORE INTO creator_handoff_ops (op, batch)"
                   " SELECT handoff_op, handoff_batch FROM creator_reservations"
                   " WHERE handoff_op IS NOT NULL AND handoff_batch IS NOT NULL")


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
    ok = {"op": op, "to_cell": to_cell, "accounts": sorted(f"{p}:{a}" for p, a in accounts)}
    with _immediate(path) as db:
        receipt = db.execute("SELECT batch FROM creator_handoff_ops WHERE op = ?", (op,)).fetchone()
        if receipt:
            if receipt[0] == batch:
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
        db.execute("INSERT INTO creator_handoff_ops (op, batch) VALUES (?, ?)", (op, batch))
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
        gen = read_placement().get("generation")
    except (KeyError, OSError, ValueError, AttributeError):
        return None
    return gen if isinstance(gen, int) and not isinstance(gen, bool) else None


@router.post("/api/cell/reservations/handoff")
def take_handoff(body: _Handoff, authorization: Annotated[str | None, Header()] = None):
    import platforms
    token = (authorization or "").removeprefix("Bearer ").strip()
    keys = os.environ.get("OI_CELL_HANDOFF_KEYS", "").split(",")
    if (matching_digest(token, keys) is None
            or hmac.compare_digest(token.encode(), os.environ.get("FLEET_SECRET", "").strip().encode())
            or caller(authorization) is not None):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    parsed = [tuple(a.split(":", 1)) for a in body.accounts]
    if (not body.op or not body.from_cell or not body.to_cell or body.from_cell == body.to_cell or not parsed
            or any(len(p) != 2 or p[0] not in platforms.KEYS or not p[1] for p in parsed)
            or len({p[1] for p in parsed}) != len(parsed)):
        return JSONResponse({"detail": {"error": "bad_handoff"}}, status_code=422)
    from db.engine import sync_database_url
    status, out = handoff(db_path(sync_database_url()), body.op, body.from_cell, body.to_cell, parsed,
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
    import platforms
    cell = caller(authorization)
    if cell is None:
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    if not body.creator_id or body.platform not in platforms.KEYS:
        return JSONResponse({"detail": {"error": "bad_reservation"}}, status_code=422)
    if body.platform not in ADMITTED_PLATFORMS:
        return JSONResponse({"detail": {"error": "platform_not_admitted"}}, status_code=403)
    try:
        assigned = read_placement()["accounts"].get(f"{body.platform}:{body.creator_id}")
    except (KeyError, OSError, ValueError, AttributeError, TypeError):
        return JSONResponse({"detail": {"error": "placement_unavailable"}}, status_code=503)
    if assigned != cell:
        return JSONResponse({"detail": {"error": "not_owner"}}, status_code=403)
    from db.engine import sync_database_url
    status, out = reserve(db_path(sync_database_url()), cell, body.platform, body.creator_id,
                          body.state)
    if status != 200:
        log.warning("Cells: reservation %s:%s for %s refused: %s", body.platform, body.creator_id, cell, out)
    return JSONResponse(out if status == 200 else {"detail": out}, status_code=status)


def claim_on_control(platform: str, account_id: str, state: str) -> dict:
    import httpx

    import accounts
    url = os.environ.get("OI_CELL_CONTROL_URL", "").rstrip("/")
    if not url:
        raise refusal(503, "control_unreachable", account_id=account_id, why="OI_CELL_CONTROL_URL unset")
    try:
        r = httpx.post(f"{url}/fleet/reservations", timeout=CALL_TIMEOUT_S,
                       json={"creator_id": account_id, "platform": platform, "state": state},
                       headers={"Authorization": f"Bearer {os.environ.get('OI_CELL_COPY_KEY', '')}"})
    except httpx.HTTPError as e:
        log.error("Cells: control unreachable for the %s reservation of %s: %s", state, account_id, e)
        raise refusal(503, "control_unreachable", account_id=account_id) from None
    if r.status_code == 200:
        return r.json()
    detail = None
    with contextlib.suppress(ValueError, AttributeError):
        detail = r.json().get("detail")
    detail = detail if isinstance(detail, dict) else {}
    if r.status_code == 403 and detail.get("error") in ("platform_not_admitted", "not_owner"):
        raise refusal(409, detail["error"], account_id=account_id)
    if r.status_code == 409 and detail.get("error") == "PlatformCollision":
        raise accounts.PlatformCollision(f"{detail.get('message')} (Cell {detail.get('cell')})")
    if r.status_code == 409 and detail.get("error") == "lives_in_cell":
        raise refusal(409, "lives_in_cell", cell=detail.get("cell"), account_id=account_id)
    log.error("Cells: control answered %d to the %s reservation of %s", r.status_code, state, account_id)
    raise refusal(503, "control_unreachable", account_id=account_id, status=r.status_code)


def admit(account_id: str, platform: str) -> None:
    import cell_mode
    aid = str(account_id)
    if platform not in ADMITTED_PLATFORMS:
        raise refusal(409, "platform_not_admitted", platform=platform, account_id=aid)
    if not cell_mode.owned(platform, aid):
        raise refusal(409, "not_owner", account_id=aid)
    claim_on_control(platform, aid, "pending")


def activate(account_id: str) -> None:
    import accounts

    _activate(accounts.get_platform(account_id), str(account_id))


def _activate(platform: str, account_id: str) -> bool:
    try:
        claim_on_control(platform, account_id, "active")
    except Exception as e:
        with _activation_lock:
            _pending_activation.add((platform, account_id))
        log.error("Cells: Creator reservation activation for %s:%s failed; queued for retry (%s: %s)",
                  platform, account_id, type(e).__name__, getattr(e, "detail", e))
        return False
    with _activation_lock:
        _pending_activation.discard((platform, account_id))
    return True


def _is_connected(platform: str, account_id: str) -> bool:
    import accounts
    import cell_mode

    return (platform in ADMITTED_PLATFORMS and cell_mode.owned(platform, account_id)
            and accounts.latest_session_path(account_id) is not None and not accounts.is_watcher(account_id))


def _connected_owned() -> set[tuple[str, str]]:
    import accounts
    import cell_mode

    connected = set()
    for aid in cell_mode.owned_ids():
        platform = None
        try:
            platform = accounts.get_platform(aid)
            if _is_connected(platform, aid):
                connected.add((platform, aid))
        except Exception:
            log.exception("Cells: could not inspect Creator %s:%s during reservation discovery", platform, aid)
            if platform in ADMITTED_PLATFORMS:
                connected.add((platform, aid))
    return connected


def reseed_activations() -> None:
    _reseed_activations.set()


def _retry_activation(platform: str, account_id: str) -> bool:
    try:
        if _is_connected(platform, account_id):
            return _activate(platform, account_id)
        with _activation_lock:
            _pending_activation.discard((platform, account_id))
        return True
    except Exception:
        log.exception("Cells: could not inspect Creator %s:%s; retrying reservation activation", platform, account_id)
        return False


async def retry_activations() -> None:
    reseed_activations()
    seed_backoff = backoff = 1
    while True:
        if _reseed_activations.is_set():
            _reseed_activations.clear()
            try:
                connected = await asyncio.to_thread(_connected_owned)
                with _activation_lock:
                    _pending_activation.update(connected)
                seed_backoff = 1
            except Exception:
                log.exception("Cells: could not seed reservation activation retries")
                reseed_activations()
                await asyncio.sleep(seed_backoff)
                seed_backoff = min(seed_backoff * 2, 30)
        with _activation_lock:
            pending = list(_pending_activation)
        if not pending:
            backoff = 1
            await asyncio.sleep(1)
        for start in range(0, len(pending), 8):
            results = [await asyncio.to_thread(_retry_activation, *key) for key in pending[start:start + 8]]
            await asyncio.sleep(1 if all(results) else backoff)
            backoff = 1 if all(results) else min(backoff * 2, 30)
