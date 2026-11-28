from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime
from itertools import islice
from typing import Any, Awaitable, Callable, Iterator, NamedTuple
from urllib.parse import urlsplit

from sqlalchemy import and_, func, or_, select

import of_pacing
import relay_coalesce
import vault_runs
import vault_stills
from db.engine import get_session
from db.models import VaultItem
from isotime import parse_iso

log = logging.getLogger("of-relay.cdn_resign")

# OF signs CDN urls for the egress IP that listed them (AWS:SourceIp) and for a day or two: a proxy move or aging 403s every held url.
FRESH_TTL_S = 3600
FAIL_TTL_S = 300
# A failure in transit (429, proxy blip) cools off only this long so the download panel's Retry works; a real refusal waits FAIL_TTL_S.
FAIL_TRANSIENT_S = 15
_CAP = 20_000
PAGE = 100  # OF's vault/media limit cap

_lock = threading.Lock()
_fresh: dict[tuple[str, str], tuple[str, float]] = {}
_failed: dict[tuple[str, int], float] = {}
_Key = tuple[datetime, int]
_Page = tuple[frozenset[int], "_Key | None", "_Key | None"]


class _Window(NamedTuple):
    until: float
    page: _Page | None
    reread: bool


_pages: dict[tuple[str, int], _Window] = {}


def _put(d: dict, k: Any, v: Any) -> None:
    # Caller holds _lock.
    d.pop(k, None)
    d[k] = v
    if len(d) > _CAP:
        for old in list(islice(d, len(d) - _CAP)):
            del d[old]


def _base(u: str) -> str:
    p = urlsplit(u)
    return (p.hostname or "").lower() + p.path


def _urls(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        if obj.startswith(("https://", "http://")):
            yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _urls(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _urls(v)


# Only a fresh url of the SAME host+path is handed back: the gate that stops a re-sign naming another file.
def same_file(u: str, media: dict | None) -> bool:
    base = _base(u)
    return any(_base(x) == base for x in _urls(media or {}))


def current(account_id: str, u: str) -> str:
    with _lock:
        hit = _fresh.get((account_id, _base(u)))
    if hit is not None and time.monotonic() - hit[1] < FRESH_TTL_S:
        return hit[0]
    return u


def _remember(account_id: str, media: dict) -> None:
    now = time.monotonic()
    with _lock:
        for u in _urls(media):
            _put(_fresh, (account_id, _base(u)), (u, now))


def _fail(key: tuple[str, int], ttl: float = FAIL_TTL_S) -> None:
    with _lock:
        _put(_failed, key, time.monotonic() + ttl)


async def _position(account_id: str, media_id: int) -> tuple[int, _Key] | None:
    async with get_session() as s:
        row = (await s.execute(select(VaultItem.created_at, VaultItem.removed_at).where(
            VaultItem.account_id == account_id, VaultItem.media_id == media_id))).first()
        if row is None or row.removed_at is not None:
            return None
        c = row.created_at
        n = await s.scalar(select(func.count()).select_from(VaultItem).where(
            VaultItem.account_id == account_id, VaultItem.removed_at.is_(None),
            or_(VaultItem.created_at < c, and_(VaultItem.created_at == c, VaultItem.media_id < media_id))))
    return int(n or 0), (c, media_id)


async def _read_page(account_id: str, offset: int, client: Any) -> _Page | None:
    try:
        resp = await asyncio.to_thread(client.vault_media, limit=PAGE, offset=offset, type="all", sort="asc")
    except of_pacing.ReadPacingExpired:
        raise
    except Exception as e:  # noqa: BLE001
        log.info("cdn_resign account=%s page=%s failed: %s", account_id, offset, e)
        return None
    items = [m for m in (resp or {}).get("list") or [] if isinstance(m, dict) and m.get("id") is not None]
    for m in items:
        _remember(account_id, m)
    try:
        await vault_runs.upsert_page(account_id, items)
    except Exception:  # noqa: BLE001 — the urls are remembered; the mirror catches up on its next read
        log.exception("cdn_resign account=%s page=%s mirror write failed", account_id, offset)
    keys = [(t, int(m["id"])) for m in items for t in (parse_iso(m.get("createdAt")),) if t is not None]
    log.info("cdn_resign account=%s page=%s items=%s", account_id, offset, len(items))
    return frozenset(int(m["id"]) for m in items), min(keys, default=None), max(keys, default=None)


async def _page(account_id: str, offset: int, client: Any, force: bool = False) -> _Page | None:
    with _lock:
        hit = _pages.get((account_id, offset))
    if hit is not None and time.monotonic() < hit.until and (hit.page is None or not force or hit.reread):
        return hit.page

    async def read() -> _Page | None:
        got = await _read_page(account_id, offset, client)
        with _lock:
            _put(_pages, (account_id, offset),
                 _Window(time.monotonic() + (FRESH_TTL_S if got is not None else FAIL_TRANSIENT_S), got, force))
        return got
    return await relay_coalesce.coalesce(("cdn_resign_page", account_id, offset), read)


async def _via_page(account_id: str, media_id: int, client: Any, force: bool = False) -> str:
    pos = await _position(account_id, media_id)
    if pos is None:
        return "miss"
    n, want = pos
    off = n // PAGE * PAGE
    # Listing is (createdAt, id) asc; the mirror can lag OF (a deletion shifts every later offset), so try its window, then the neighbour on the media's side.
    for _ in range(2):
        page = await _page(account_id, off, client, force)
        if page is None:
            return "failed"
        ids, lo, hi = page
        if media_id in ids:
            return "hit"
        if lo is None or want < lo:
            off -= PAGE
        elif want > hi and len(ids) >= PAGE:
            off += PAGE
        else:
            break
        if off < 0:
            break
    log.info("cdn_resign account=%s media=%s not in its window", account_id, media_id)
    return "miss"


def _close(r: Any) -> None:
    try:
        r.close()
    except Exception:
        pass


async def resign(account_id: str, media_id: int, failed_u: str, client: Any, kind: str) -> str | None:
    return await of_pacing.walk(account_id, kind, lambda: _resign(account_id, media_id, failed_u, client))


async def _resign(account_id: str, media_id: int, failed_u: str, client: Any) -> str | None:
    key = (account_id, int(media_id))
    with _lock:
        until = _failed.get(key)
    if until is not None and time.monotonic() < until:
        return None
    cur = current(account_id, failed_u)
    if cur != failed_u:
        return cur
    with _lock:
        seen = _fresh.get((account_id, _base(failed_u)))
    handed = seen is not None and seen[0] == failed_u
    via = await _via_page(account_id, int(media_id), client)
    if via == "hit" and handed and current(account_id, failed_u) == failed_u:
        # The failed url was handed out by a window read (egress switch since): read the window again once, not by id.
        via = await _via_page(account_id, int(media_id), client, force=True)
    if via == "failed":
        _fail(key, FAIL_TRANSIENT_S)
        return None
    reason = "no_same_path"
    if via == "miss" or current(account_id, failed_u) == failed_u:
        fresh = await relay_coalesce.coalesce(
            ("cdn_resign", account_id, int(media_id)),
            lambda: vault_stills.resolve_fresh(account_id, int(media_id), client))
        if fresh.media is not None:
            _remember(account_id, fresh.media)
        else:
            reason = fresh.reason
    new = current(account_id, failed_u)
    if new == failed_u:
        _fail(key, FAIL_TRANSIENT_S if reason == "fetch_failed" else FAIL_TTL_S)
        log.info("cdn_resign account=%s media=%s failed reason=%s", account_id, media_id, reason)
        return None
    log.info("cdn_resign account=%s media=%s ok", account_id, media_id)
    return new


async def fetch(account_id: str, media_id: int | None, u: str, client: Any,
                get: Callable[[str], Awaitable[Any]], kind: str) -> tuple[Any, str]:
    if not (account_id and media_id):
        return await get(u), u
    u = current(account_id, u)
    r = await get(u)
    if r.status_code != 403:
        return r, u
    await asyncio.to_thread(_close, r)
    new = await resign(account_id, media_id, u, client, kind)
    if new is None:
        return r, u
    r = await get(new)
    if r.status_code == 403:
        _fail((account_id, int(media_id)))
        with _lock:
            _fresh.pop((account_id, _base(new)), None)
        log.info("cdn_resign account=%s media=%s retry still 403", account_id, media_id)
    return r, new
