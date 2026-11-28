from __future__ import annotations

import contextlib
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

from fastapi import APIRouter, HTTPException, Query

log = logging.getLogger("restore-reconcile")

PEEK_WINDOW = timedelta(hours=24)
PEEK_PAGES = 5
QUEUE_PAGES = 20
KIND = "restore_peek"
_COLS = ("reconcile_since", "restored_at", "peek_until", "gap_confirmed_by", "gap_confirmed_at")
DDL = """CREATE TABLE IF NOT EXISTS reconcile_peeks (
  platform TEXT NOT NULL, account TEXT NOT NULL, target TEXT NOT NULL, data_gen INTEGER NOT NULL,
  peeked_at TEXT NOT NULL, unmatched INTEGER NOT NULL, PRIMARY KEY (platform, account, target, data_gen))"""
_NOW = "strftime('%Y-%m-%d %H:%M:%S','now')"

_path: str | None = None


def _connect() -> sqlite3.Connection:
    if _path is None:
        raise sqlite3.OperationalError("restore_reconcile store not installed")
    return sqlite3.connect(_path, timeout=30, isolation_level=None)


def install(sync_url: str) -> None:
    global _path
    _path = sync_url.split("sqlite:///", 1)[1]
    with contextlib.closing(_connect()) as db:
        db.execute(DDL)
        have = {r[1] for r in db.execute("PRAGMA table_info(cell_meta)")}
        for col in _COLS:
            if col not in have:
                db.execute(f"ALTER TABLE cell_meta ADD COLUMN {col} TEXT")


def active() -> bool:
    return _path is not None


def arm(db: sqlite3.Connection) -> bool:
    if "reconcile_since" not in {r[1] for r in db.execute("PRAGMA table_info(cell_meta)")} or not db.execute(
            "SELECT reconcile_since IS NOT NULL FROM cell_meta").fetchone()[0]:
        return False
    until = (datetime.now(timezone.utc) + PEEK_WINDOW).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE cell_meta SET peek_until=?", (until,))
    log.warning("Cells: lossy restore: per-thread peek armed until %s", until)
    return True


def window(db: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    if db is None:
        if _path is None:
            return None
        with contextlib.closing(_connect()) as conn:
            return window(conn)
    row = db.execute(f"SELECT data_gen, {', '.join(_COLS)} FROM cell_meta").fetchone()
    if row is None or row[1] is None:
        return None
    return dict(zip(("data_gen", *_COLS), row))


def _utc(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def peeking(w: dict[str, Any] | None, now: datetime | None = None) -> bool:
    until = _utc(w and w["peek_until"])
    return until is not None and (now or datetime.utcnow()) < until


def _creator_messages(client, account: str, target: str, since: datetime, until: datetime) -> list[dict]:
    out, before = [], None
    for _ in range(PEEK_PAGES):
        page = client.get_messages(target, limit=50, peek=True, before_id=before)
        rows = page.get("list") or []
        for m in rows:
            at = _utc(m.get("createdAt"))
            if at is not None and since < at <= until and str((m.get("fromUser") or {}).get("id")) == account:
                out.append(m)
        oldest = _utc(rows[-1].get("createdAt")) if rows else None
        if not page.get("hasMore") or (oldest is not None and oldest <= since):
            return out
        if not rows or oldest is None:
            raise ValueError("incomplete restore peek page")
        before = rows[-1]["id"]
    raise ValueError("restore peek page limit reached before the gap start")


def _known(db: sqlite3.Connection, account: str, target: str, msg_id: str, restored_at: str) -> bool:
    if db.execute("SELECT 1 FROM send_ops WHERE account=? AND upstream_id=? LIMIT 1", (account, msg_id)).fetchone():
        return True
    with contextlib.suppress(sqlite3.Error, ValueError):
        return db.execute("SELECT 1 FROM messages WHERE account_id=? AND fan_id=? AND message_id=? AND ingested_at<?",
                          (account, int(target), int(msg_id), restored_at)).fetchone() is not None
    return False


class QueueHold(NamedTuple):
    why: str
    op: str


def queue_hold(w: dict | None) -> QueueHold | None:
    if w and w["peek_until"] and not w["gap_confirmed_at"]:
        return QueueHold("restore_gap_unconfirmed", f"data_gen {w['data_gen']}")
    return None


def refuse_queue(platform: str, kind: str, db: sqlite3.Connection | None = None) -> None:
    from send_ops import MANUAL, QUEUE
    from send_tripwire import CellHeld
    if active() and platform == "onlyfans" and kind in QUEUE and kind not in MANUAL:
        if hold := queue_hold(window(db)):
            raise CellHeld(hold)


def before_send(platform: str, account: str, kind: str, target: str) -> None:
    import send_ops
    if _path is None or platform != "onlyfans" or kind in send_ops.MANUAL:
        return
    if kind in send_ops.QUEUE:
        refuse_queue(platform, kind)
        return
    with contextlib.closing(_connect()) as db:
        w = window(db)
        if not peeking(w) or db.execute(
                "SELECT 1 FROM reconcile_peeks WHERE platform=? AND account=? AND target=? AND data_gen=?",
                (platform, account, target, w["data_gen"])).fetchone():
            return
    import automation_executor
    try:
        found = _creator_messages(automation_executor._make_client(account), account, target,
                                  _utc(w["reconcile_since"]), _utc(w["restored_at"]) or datetime.utcnow())
    except Exception as e:
        log.warning("Cells: restore peek failed account=%s target=%s: %s", account, target, e)
        raise send_ops.SendRefused(503, "peek_failed", target=target) from e
    with contextlib.closing(_connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        lost = [m for m in found if not _known(db, account, target, str(m["id"]), w["restored_at"] or _now())]
        for m in lost:
            send_ops.record_uncertain(db, platform, account, KIND, target, w["data_gen"], str(m["id"]),
                                      {"id": m["id"], "createdAt": m.get("createdAt"), "text": m.get("text") or ""})
        db.execute(f"INSERT OR IGNORE INTO reconcile_peeks VALUES (?,?,?,?,{_NOW},?)",
                   (platform, account, target, w["data_gen"], len(lost)))
        db.execute("COMMIT")
    if lost:
        log.warning("Cells: restore peek account=%s fan=%s: %d creator message(s) since %s unknown here;"
                    " Fan held until a person marks them", account, target, len(lost), w["reconcile_since"])


def native_queue_unknown(account: str, client=None) -> list[dict]:
    if client is None:
        import automation_executor
        client = automation_executor._make_client(account)
    items, offset = [], 0
    for _ in range(QUEUE_PAGES):
        page = client.scheduled_messages(limit=50, offset=offset)
        rows = page.get("list") or []
        items += rows
        if not page.get("hasMore") or not rows:
            break
        offset += len(rows)
    with contextlib.closing(_connect()) as db:
        known = {str(r[0]) for r in db.execute(
            "SELECT upstream_id FROM send_ops WHERE account=? AND upstream_id IS NOT NULL"
            " UNION SELECT queue_id FROM mass_runs WHERE account_id=? AND queue_id IS NOT NULL"
            " UNION SELECT queue_id FROM mass_broadcast_cache WHERE account_id=?", (account, account, account))}
    unknown = [i for i in items if str(i.get("id")) not in known]
    for i in unknown:
        log.warning("Cells: lossy restore: OF native queue item %s on %s is not in this DB (scheduled %s)",
                    i.get("id"), account, i.get("scheduledDate") or i.get("date"))
    return unknown


async def boot_queue_check(accounts: list[tuple[str, str]]) -> dict[str, list[dict]]:
    import asyncio
    out = {}
    for platform, account in accounts:
        if platform != "onlyfans":
            continue
        try:
            out[account] = await asyncio.to_thread(native_queue_unknown, account)
        except Exception:
            log.exception("Cells: native queue listing failed for %s; check OF's queue by hand", account)
    return out


def gap(db: sqlite3.Connection | None = None) -> tuple[datetime, datetime] | None:
    w = window(db)
    if w is None or not w["restored_at"]:
        return None
    return _utc(w["reconcile_since"]), _utc(w["restored_at"])


def gap_unconfirmed() -> tuple[datetime, datetime] | None:
    w = window()
    return None if w is None or w["gap_confirmed_at"] else gap()


def unattributed(account: str) -> list[dict]:
    span = gap()
    if span is None:
        return []
    with contextlib.closing(_connect()) as db:
        rows = db.execute(
            "SELECT fan_id, message_id, created_at FROM messages WHERE account_id=? AND direction='out'"
            " AND created_at>=? AND created_at<? ORDER BY created_at",
            (account, *(t.strftime("%Y-%m-%d %H:%M:%S") for t in span))).fetchall()
    return [{"fan_id": f, "message_id": m, "created_at": at, "attribution": "unattributed"} for f, m, at in rows]


def confirm_gap(by: str) -> bool:
    with contextlib.closing(_connect()) as db:
        return db.execute(f"UPDATE cell_meta SET gap_confirmed_by=?, gap_confirmed_at={_NOW}"
                          " WHERE restored_at IS NOT NULL AND gap_confirmed_at IS NULL", (by,)).rowcount == 1


def held_keys(events, by_employee: bool) -> set:
    span = gap_unconfirmed()
    if span is None:
        return set()
    lo, hi = span
    now = datetime.utcnow()
    return {e.employee_id if by_employee else e.account_id for e in events
            if e.in_utc < hi and (e.out_utc or now) > lo}


router = APIRouter()


@router.get("/admin/cell/restore-gap")
async def restore_gap(account_id: str = Query(...)) -> dict:
    from auth import assert_account_owned
    from starlette.concurrency import run_in_threadpool
    assert_account_owned(account_id)
    w = await run_in_threadpool(window)
    if w is None:
        return {"gap": None, "messages": []}
    return {"gap": {k: w[k] for k in _COLS} | {"data_gen": w["data_gen"], "peeking": peeking(w),
                    "queue_held": queue_hold(w) is not None},
            "messages": await run_in_threadpool(unattributed, account_id)}


@router.post("/admin/cell/restore-gap/confirm")
async def restore_gap_confirm() -> dict:
    from auth import assert_account_owned, get_request_user
    from cell_mode import owned_ids
    from starlette.concurrency import run_in_threadpool
    user = get_request_user()
    owned = owned_ids()
    if user is None or not owned:
        raise HTTPException(403, "owner authorization required")
    if not user.is_admin:
        for account in owned:
            assert_account_owned(account)
    by = f"user:{user.id}:{user.username}"
    ok = await run_in_threadpool(confirm_gap, by)
    log.warning("Cells: restore gap shifts confirmed by %s (%s)", by, "ok" if ok else "nothing to confirm")
    return {"confirmed": ok}
