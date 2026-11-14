"""Bio reads and retained, batched daily counters on this process's DB engine."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from itertools import islice
from typing import Literal

from bio_pages.decide import HostKind

from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError, ProgrammingError, TimeoutError

from db.engine import engine, get_session

log = logging.getLogger("of-relay.bio")
EventKind = Literal["view", "click"]
_PROFILE_COLS = "id, username, display_name, bio, avatar, background_image, mode, verified"
# A deploy recreates this service and the relay together; only the relay's init_db adds columns. Until it has added
# bio_profiles.background_image (migration 0122) a page reads as having none, instead of a 503.
_PROFILE_COLS_PRE_0122 = _PROFILE_COLS.replace("background_image", "'' AS background_image")
_PUBLIC_LINK_COLS = ("id, profile_id, link_id, title, default_tracking_code, mode, icon, background_image, "
                     "is_adult, tracking, bot_check")
_LINK_COLS = _PUBLIC_LINK_COLS + ", destination, geo"
_UPSERT = text(
    "INSERT INTO bio_daily (day, profile_id, link_id, country, in_app, code, views, clicks)"
    " VALUES (:day, :profile_id, :link_id, :country, :in_app, :code, :views, :clicks)"
    " ON CONFLICT (day, profile_id, link_id, country, in_app, code)"
    " DO UPDATE SET views = bio_daily.views + excluded.views, clicks = bio_daily.clicks + excluded.clicks")


def _link(row) -> dict:
    d = dict(row._mapping)
    if "geo" in d:
        try:
            d["geo"] = json.loads(d["geo"]) if d["geo"] is not None else None
        except ValueError:
            d["geo"] = None
    return d


async def _profile_row(s, username: str):
    try:
        return (await s.execute(text(f"SELECT {_PROFILE_COLS} FROM bio_profiles WHERE username = :u"),
                                {"u": username})).first()
    except (OperationalError, ProgrammingError) as e:
        if "background_image" not in str(e.orig):
            raise
        await s.rollback()
    return (await s.execute(text(f"SELECT {_PROFILE_COLS_PRE_0122} FROM bio_profiles WHERE username = :u"),
                            {"u": username})).first()


async def profile_at(username: str) -> dict | None:
    async with get_session() as s:
        row = await _profile_row(s, username)
    return dict(row._mapping) if row else None


async def profile_with_links(username: str) -> tuple[dict, list[dict]] | None:
    async with get_session() as s:
        row = await _profile_row(s, username)
        if not row:
            return None
        links = (await s.execute(text(f"SELECT {_PUBLIC_LINK_COLS} FROM bio_links WHERE profile_id = :p "
                                      "ORDER BY sort_order, id"), {"p": row.id})).all()
    return dict(row._mapping), [_link(r) for r in links]


async def link_by_link_id(link_id: str) -> dict | None:
    async with get_session() as s:
        row = (await s.execute(text(f"SELECT {_LINK_COLS} FROM bio_links WHERE link_id = :l"), {"l": link_id})).first()
    return _link(row) if row else None


async def link_profile_id(row_id: str) -> str | None:
    """The Profile owning the Link row `row_id` (its files' record id), or None."""
    async with get_session() as s:
        return (await s.execute(text("SELECT profile_id FROM bio_links WHERE id = :i"), {"i": row_id})).scalar()


async def resolve_host_row(name: str) -> tuple[HostKind, str | None]:
    async with get_session() as s:
        row = (await s.execute(text(
            "SELECT k, username FROM ("
            " SELECT 0 AS k, NULL AS username FROM bio_spare_domains WHERE domain = :d"
            " UNION ALL"
            " SELECT 1 AS k, p.username FROM bio_custom_domains c JOIN bio_profiles p ON p.id = c.profile_id"
            " WHERE c.domain = :d AND c.status = 'live'"
            ") ORDER BY k LIMIT 1"), {"d": name})).first()
    if row is None:
        return "unknown", None
    return ("spare", None) if row.k == 0 else ("custom", row.username)


_batch: dict[tuple[str, str, str, str, str, str], list[int]] = {}
_flush_lock = asyncio.Lock()
_flush_task: asyncio.Task | None = None
MAX_KEYS = 10_000  # early flush at this many keys
BATCH_CAP = 50_000  # hard cap across pending and in-flight keys
CHUNK_SIZE = 1_000
_retry_after = 0.0
_busy_warnings = 0
_capped = 0
_inflight_keys: set[tuple[str, str, str, str, str, str]] = set()
_capped_logged_at = -1e9
_KEY_COLS = ("day", "profile_id", "link_id", "country", "in_app", "code")
_LIVE_QUERY = text("SELECT id FROM bio_profiles WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))


def _note_capped() -> None:
    global _capped, _capped_logged_at
    _capped += 1
    now = asyncio.get_running_loop().time()
    if now - _capped_logged_at >= 10:
        log.error("bio: counter batch full keys=%d dropped=%d", len(_batch.keys() | _inflight_keys), _capped)
        _capped_logged_at = now


async def record(kind: EventKind, profile_id: str, link_row_id: str, country: str, in_app: str, code: str) -> None:
    global _flush_task
    if kind not in ("view", "click"):
        raise ValueError("unknown bio event")
    key = (datetime.now(timezone.utc).strftime("%Y-%m-%d"), profile_id, link_row_id, country, in_app, code)
    counts = _batch.get(key)
    if counts is None:
        if key not in _inflight_keys and len(_batch) + len(_inflight_keys) >= BATCH_CAP:
            _note_capped()
            return
        counts = _batch[key] = [0, 0]
    counts[0 if kind == "view" else 1] += 1
    if (len(_batch) >= MAX_KEYS and asyncio.get_running_loop().time() >= _retry_after
            and (_flush_task is None or _flush_task.done())):
        _flush_task = asyncio.create_task(flush())


async def _live_split(conn, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    ids = sorted({r["profile_id"] for r in rows})
    live = set((await conn.execute(_LIVE_QUERY, {"ids": ids})).scalars())
    return ([r for r in rows if r["profile_id"] in live],
            [r for r in rows if r["profile_id"] not in live])


async def _write(rows: list[dict]) -> list[dict]:
    """One short write transaction; return rows whose profile no longer exists."""
    async with engine.connect() as conn:
        sqlite = engine.url.get_backend_name() == "sqlite"
        if sqlite:
            old_timeout = (await conn.execute(text("PRAGMA busy_timeout"))).scalar()
            await conn.execute(text("PRAGMA busy_timeout=100"))
        try:
            if sqlite:
                await conn.execute(text("BEGIN IMMEDIATE"))
            rows, orphans = await _live_split(conn, rows)
            if rows:
                try:
                    await conn.execute(_UPSERT, rows)
                except IntegrityError:
                    if sqlite:
                        raise
                    await conn.rollback()
                    rows, newly_orphaned = await _live_split(conn, rows)
                    orphans.extend(newly_orphaned)
                    if rows:
                        await conn.execute(_UPSERT, rows)
            await conn.commit()
            return orphans
        finally:
            if sqlite:
                try:
                    await conn.execute(text(f"PRAGMA busy_timeout={old_timeout}"))
                except Exception:  # noqa: BLE001 — a committed batch must never be merged twice
                    log.warning("bio: SQLite busy timeout reset failed")


async def flush() -> bool:
    """Persist at most CHUNK_SIZE keys per short transaction. Transient DB errors retain counts;
    orphan profile keys and permanent errors are dropped with counted lines.

    Never cancel this coroutine: cancellation after the batch swap can lose its uncommitted counts.
    """
    global _batch, _retry_after, _busy_warnings, _capped
    async with _flush_lock:
        taken_batch, _batch = _batch, {}
        _inflight_keys.update(taken_batch)
        try:
            while taken_batch:
                taken = {key: taken_batch.pop(key) for key in tuple(islice(taken_batch, CHUNK_SIZE))}
                rows = [dict(zip(_KEY_COLS, key), views=v[0], clicks=v[1]) for key, v in taken.items()]
                try:
                    if gone := await _write(rows):
                        log.error("bio: counter flush dropped orphan keys=%d views=%d clicks=%d", len(gone),
                                  sum(r["views"] for r in gone), sum(r["clicks"] for r in gone))
                except (OperationalError, TimeoutError, InterfaceError) as e:
                    _busy_warnings += 1
                    if _busy_warnings == 1 or _busy_warnings % 10 == 0:
                        log.warning("bio: counter flush deferred %s", type(e).__name__)
                    for key, counts in (*taken.items(), *taken_batch.items()):
                        dst = _batch.setdefault(key, [0, 0])
                        dst[0] += counts[0]
                        dst[1] += counts[1]
                    _retry_after = asyncio.get_running_loop().time() + 1.0
                    return False
                except Exception as e:  # noqa: BLE001 — retrying a chunk that fails for good would poison every flush
                    log.error("bio: counter flush dropped %s keys=%d views=%d clicks=%d", type(e).__name__, len(rows),
                              sum(r["views"] for r in rows), sum(r["clicks"] for r in rows))
                _inflight_keys.difference_update(taken)
            _retry_after = 0.0
            _busy_warnings = 0
            if _capped:
                log.error("bio: counter flush capped dropped=%d", _capped)
                _capped = 0
            return True
        finally:
            _inflight_keys.clear()


def capped_drops() -> int:
    return _capped


async def flush_loop(seconds: float, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            await flush()


def pending() -> tuple[int, int, int]:
    """Keys, views and clicks not yet committed."""
    return len(_batch), sum(v[0] for v in _batch.values()), sum(v[1] for v in _batch.values())
