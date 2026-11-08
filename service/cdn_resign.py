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
so a dead clip costs one OF call per 5 min, not one per frame. RAM-only: a restart costs one OF call per media on its
next 403. `fetch` is the one GET -> 403 -> re-sign -> retry sequence both routes run.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Awaitable, Callable, Iterator
from urllib.parse import urlsplit

import relay_coalesce
import vault_stills

log = logging.getLogger("of-relay.cdn_resign")

FRESH_TTL_S = 3600
FAIL_TTL_S = 300
_CAP = 20_000

_lock = threading.Lock()
_fresh: dict[tuple[str, str], tuple[str, float]] = {}   # (account, host+path) -> (signed url, monotonic ts)
_failed: dict[tuple[str, int], float] = {}              # (account, media id) -> monotonic ts


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
        if len(_fresh) > _CAP:
            _fresh.clear()
        for u in _urls(media):
            _fresh[(account_id, _base(u))] = (u, now)


def _fail(key: tuple[str, int]) -> None:
    with _lock:
        if len(_failed) > _CAP:
            _failed.clear()
        _failed[key] = time.monotonic()


def _close(r: Any) -> None:
    try:
        r.close()
    except Exception:
        pass


async def resign(account_id: str, media_id: int, failed_u: str, client: Any) -> str | None:
    """A freshly signed url for `failed_u`'s host+path, from one by-id read of `media_id`; None when OF has no
    such media, the read failed, or OF handed back the very url that just failed. Concurrent callers for one
    media share the read."""
    key = (account_id, int(media_id))
    with _lock:
        t = _failed.get(key)
    if t is not None and time.monotonic() - t < FAIL_TTL_S:
        return None
    cur = current(account_id, failed_u)
    if cur != failed_u:  # another request re-signed it meanwhile
        return cur
    fresh = await relay_coalesce.coalesce(
        ("cdn_resign", account_id, int(media_id)),
        lambda: vault_stills.resolve_fresh(account_id, int(media_id), client))
    if fresh.media is not None:
        _remember(account_id, fresh.media)
    new = current(account_id, failed_u)
    if new == failed_u:
        _fail(key)
        log.info("cdn_resign account=%s media=%s failed reason=%s", account_id, media_id,
                 fresh.reason if fresh.media is None else "no_same_path")
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
