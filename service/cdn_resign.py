"""cdn_resign.py — a stale OF CDN url, re-signed by media id, for the byte routes that take one (`/img`,
`/img/scrub`).

OF signs every CDN url for the egress IP that listed it (`AWS:SourceIp` in the Policy) and for a day or two
(`DateLessThan`). The browser holds whatever url its listing carried: the mirror's raw_json (as old as the last
Collect), the relay's vault cache (20 h), its own query cache. Once the account moves to another proxy, or the
signature ages out, every one of those urls 403s through the account's client. Measured on AE 2026-11-06: a
Creator rebound twice in a day, mirror urls signed for two dead IPs, 108/108 `/img/scrub` 502s.

The stills (`vault_stills.bytes_for`) already re-sign by id. This is the same move for the routes that are handed
a url: when the caller names the media (`media_id`), a 403 re-reads that one media from OF through the account's
CURRENT client (`vault_stills.resolve_fresh`, which also writes the mirror row) and retries once with the url of
the SAME host+path in the fresh payload. The path match is also the gate: it can only ever hand back a fresh
signature for the file the caller already named.

`current` lets the next request skip the 403: a fresh url seen for that host+path within FRESH_TTL_S is used up
front (a hover asks 12 frames, a tile up to 9 posters, a <video> many ranges, all with the browser's stale url).
A failed re-sign (no fresh url, or a fresh url that still answers 403) is remembered for FAIL_TTL_S per media
so a dead clip costs one OF call per 5 min, not one per frame. A by-id read that failed in transit (OF's 429, a proxy
blip: `fetch_failed`) is remembered only FAIL_TRANSIENT_S: long enough that a hover's frames make one call, short
enough that the download panel's Retry works (AE 2026-11-10, measured: a 118-file download 429'd at file 92 and every
Retry inside the next 5 min failed with no OF call). RAM-only: a restart costs one OF call per media on its
next 403. `fetch` is the one GET -> 403 -> re-sign -> retry sequence both routes run.

Re-sign by PAGE first. OF's vault listing (`list=all, sort=asc`, the collect walk's) returns 100 media per call, each
the same payload as a by-id read, in (createdAt, id) order (measured on AE 2026-11-11: 0 inversions over 4,561
walk-ordered mirror pairs, ties by id asc). The mirror holds both, so a media's listing offset is a COUNT of the
account's live rows before it: one listing read re-signs the 100-item window holding the media, remembers every
url in it and writes the window back over the mirror (`vault_runs.upsert_page`, the walk's write). A download of N
expired files costs ~one OF call per window it touches, not N (AE 2026-11-10, a 118-file selection: 6 windows, 118
by-id reads). The mirror can lag OF (a deletion it has not seen shifts every later offset), so a window that does
not hold the media is checked against its (createdAt, id) range and its neighbour on that side is read once; a
media still not found, or a mirror with no row for it, falls back to the by-id read. Each window is read at most
once per FRESH_TTL_S (`_pages`), so drift costs at most one extra read per window, never one per file; a window
read that failed in transit fails its media FAIL_TRANSIENT_S and makes no by-id read (the same 429 would answer).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime
from itertools import islice
from typing import Any, Awaitable, Callable, Iterator
from urllib.parse import urlsplit

from sqlalchemy import and_, func, or_, select

import relay_coalesce
import vault_runs
import vault_stills
from db.engine import get_session
from db.models import VaultItem
from isotime import parse_iso

log = logging.getLogger("of-relay.cdn_resign")

FRESH_TTL_S = 3600
FAIL_TTL_S = 300
FAIL_TRANSIENT_S = 15
_CAP = 20_000
PAGE = 100   # OF's vault/media limit cap

_lock = threading.Lock()
_fresh: dict[tuple[str, str], tuple[str, float]] = {}   # (account, host+path) -> (signed url, monotonic ts)
_failed: dict[tuple[str, int], float] = {}              # (account, media id) -> monotonic time it may retry
_Key = tuple[datetime, int]                              # a media's listing sort key: (createdAt, id)
_Page = tuple[frozenset[int], "_Key | None", "_Key | None"]   # a window read: its ids, lowest key, highest key
_pages: dict[tuple[str, int], tuple[float, _Page | None]] = {}  # (account, offset) -> (expiry, read | None=failed)


def _put(d: dict, k: Any, v: Any) -> None:
    """d[k] = v as the newest entry; past _CAP the oldest go. Caller holds _lock."""
    d.pop(k, None)
    d[k] = v
    if len(d) > _CAP:
        for old in list(islice(d, len(d) - _CAP)):
            del d[old]


def _base(u: str) -> str:
    p = urlsplit(u)
    return (p.hostname or "").lower() + p.path


def _urls(obj: Any) -> Iterator[str]:
    """Every http(s) url anywhere in an OF media dict (files.*, videoSources, preview options...)."""
    if isinstance(obj, str):
        if obj.startswith(("https://", "http://")):
            yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _urls(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _urls(v)


def same_file(u: str, media: dict | None) -> bool:
    """Whether the media payload contains this CDN host and path."""
    base = _base(u)
    return any(_base(x) == base for x in _urls(media or {}))


def current(account_id: str, u: str) -> str:
    """`u`, or the url we re-signed for the same host+path within FRESH_TTL_S."""
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
    """The media's offset in OF's asc listing as the mirror sees it, and its sort key; None without a live row."""
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
    """One listing window from OF: every url remembered, the window written over the mirror. None when the read
    failed; an empty window (past OF's end) is (∅, None, None)."""
    try:
        resp = await asyncio.to_thread(client.vault_media, limit=PAGE, offset=offset, type="all", sort="asc")
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


async def _page(account_id: str, offset: int, client: Any) -> _Page | None:
    """The window at `offset`: read once per FRESH_TTL_S (a failed read is remembered FAIL_TRANSIENT_S), shared by
    concurrent callers."""
    with _lock:
        hit = _pages.get((account_id, offset))
    if hit is not None and time.monotonic() < hit[0]:
        return hit[1]

    async def read() -> _Page | None:
        got = await _read_page(account_id, offset, client)
        with _lock:
            _put(_pages, (account_id, offset),
                 (time.monotonic() + (FRESH_TTL_S if got is not None else FAIL_TRANSIENT_S), got))
        return got
    return await relay_coalesce.coalesce(("cdn_resign_page", account_id, offset), read)


async def _via_page(account_id: str, media_id: int, client: Any) -> str:
    """Re-sign `media_id` by reading its listing window (module doc): "hit" (its urls are remembered), "failed" (a
    window read failed in transit) or "miss" (not found that way: read it by id)."""
    pos = await _position(account_id, media_id)
    if pos is None:
        return "miss"
    n, want = pos
    off = n // PAGE * PAGE
    for _ in range(2):   # the mirror's window, then once the neighbour on the media's side
        page = await _page(account_id, off, client)
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


async def resign(account_id: str, media_id: int, failed_u: str, client: Any) -> str | None:
    """A freshly signed url for `failed_u`'s host+path, from the media's listing window or else one by-id read of
    `media_id` (module doc); None when OF has no such media, the read failed, or OF handed back the very url that
    just failed. Concurrent callers for one window / media share the read."""
    key = (account_id, int(media_id))
    with _lock:
        until = _failed.get(key)
    if until is not None and time.monotonic() < until:
        return None
    cur = current(account_id, failed_u)
    if cur != failed_u:  # another request re-signed it meanwhile
        return cur
    via = await _via_page(account_id, int(media_id), client)
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
                get: Callable[[str], Awaitable[Any]]) -> tuple[Any, str]:
    """GET `u` with `get` and return (the response, the url it came from); the caller owns and closes it. With an
    account and a media id: the url re-signed earlier for that file is used up front (`current`), and a 403
    re-signs once (`resign`) and GETs the fresh url; when no fresh url comes, the 403 comes back (closed). A retry
    that still 403s marks the media failed and forgets the fresh url, so the next request with it makes no OF read
    for FAIL_TTL_S."""
    if not (account_id and media_id):
        return await get(u), u
    u = current(account_id, u)
    r = await get(u)
    if r.status_code != 403:
        return r, u
    await asyncio.to_thread(_close, r)
    new = await resign(account_id, media_id, u, client)
    if new is None:
        return r, u
    r = await get(new)
    if r.status_code == 403:
        _fail((account_id, int(media_id)))
        with _lock:
            _fresh.pop((account_id, _base(new)), None)
        log.info("cdn_resign account=%s media=%s retry still 403", account_id, media_id)
    return r, new
