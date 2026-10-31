"""service/img_api.py — server.py's image block, moved wholesale: the `/img`
OF-CDN proxy (`/img`, `/img/by-hash/{h}`), its on-disk cache and TTL evictor
(`_img_cache_evictor_loop`, started by server.py), pinned outbound media
(`_pin_sent_media`, called by send_message), and their admin views
(`/admin/streams`, `/admin/img-cache/disk`, `/admin/img-cache/stats`).

Server-global helpers (`_get_client`, `_load_client`, `_periodic`,
`_priority_lane_background`) are relay_host's call-time forwards, so a test's
`server._get_client = fake` still reaches these routes. Never `from server import`.

Three routers, each included mid-file in server.py at its handlers' old spot,
for route order (pinned by service/tests/test_route_order.py).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import threading
import time as _time_mod
from pathlib import Path
from typing import Any

from curl_cffi import requests as curl_requests
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

import admission
from of_client import DEFAULT_TIMEOUT_S, IMPERSONATE, OF_CDN_SUFFIXES
from relay_host import get_request_client as _get_client
from relay_host import load_client as _load_client
from relay_host import periodic as _periodic
from relay_host import priority_lane_background as _priority_lane_background

log = logging.getLogger("of-relay")

router = APIRouter()          # /img, /img/by-hash/{h}
streams_router = APIRouter()  # /admin/streams
cache_router = APIRouter()    # /admin/img-cache/disk, /admin/img-cache/stats


# ── Image proxy ────────────────────────────────────────────────
# OF's CDN signs URLs with `AWS:SourceIp=<egress IP>/32` — the IP of the
# proxy that fetched the API response. The user's browser doesn't share
# that IP, so the image fetch fails on any account whose session uses a
# different egress than the user's home IP. We tunnel the fetch back
# through the account's HTTP client so the source IP matches.
#
# Restricted to known OF CDN hosts to keep this from becoming an SSRF
# foot-gun. Caches at the browser via Cache-Control passthrough.

_ALLOWED_CDN_SUFFIXES = (
    *OF_CDN_SUFFIXES,
    ".fansly.com",  # Fansly media CDN (cdn3.fansly.com); Policy-signed, not ip-bound
)

# OF's unsigned static hosts, which Infloww's desktop sends direct
# (bypassRules.ts: `static*.onlyfans.com`, `public.onlyfans.com`). No Policy and
# no SourceIp to match, so /img fetches them out the relay's own WAN instead of
# spending proxy bandwidth. Every other host (cdn*.onlyfans.com is the signed
# one) stays on the account's proxy.
_DIRECT_CDN_HOST = re.compile(r"static\d*\.onlyfans\.com|public\.onlyfans\.com")
# …and through this bare session, never the account's: no cookies (none kept,
# none sent), no account UA or OF headers, no proxy. A fetch from the relay's
# own IP must carry nothing that names an account, or it links the account to
# that IP. curl_cffi gives each thread its own curl handle, so one is enough.
_DIRECT_HTTP = curl_requests.Session(impersonate=IMPERSONATE, discard_cookies=True)

# In-flight /img stream counters. Each active proxy_image generator
# increments _img_active on first chunk and decrements in its finally
# block. Read via /admin/streams so the user can see whether hover-
# preview is actually blowing the budget or it's something else (e.g.,
# a stalled upstream holding a thread). Pure counters, no lock — Python
# int += is atomic enough for monotonic stats.
_img_active: int = 0
_img_high_water: int = 0
_img_total_started: int = 0
_img_total_aborted: int = 0

# The sync-side admission lanes this module drives (IMG_FETCH, VIDEO_STREAM)
# live in `admission` — instances included — because they bound resources of
# the PROCESS. Referenced through the module rather than aliased here: an
# alias is indirection that buys nothing, and reading
# `admission.IMG_FETCH` at the call site says where the ceiling is defined.
# Each carries its own sizing rationale there; the ⚠️ on IMG_FETCH is worth
# reading before retuning any of them.

# Stable handle for /img assets. OF CDN URLs include a signed Policy +
# Signature + Key-Pair-Id that rotate per upstream fetch — the SAME
# physical image looks like a different URL each time we re-list a chat.
# Browser HTTP cache keys by full URL, so signature rotation gives a
# 0% hit rate across re-fetches of the same chat.
#
# Fix: hash the stable identity of the asset (host + path, scoped by
# account), keep an in-memory hash → most-recent-signed-URL map, and
# expose /img/by-hash/<h> that the frontend can use as a stable cache
# key once it's seen the hash via /admin/img-cache/stats or via the
# response header X-Img-Hash from /img?u=...
#
# TTL on entries matches OF's signed-URL lifetime (~1h). After expiry,
# /img/by-hash/<h> returns 410 and the frontend falls back to /img?u=
# with a fresh URL from the next /messages payload.
_IMG_HASH_TTL_S = 60 * 60
_IMG_HASH_CAP = 50_000
_img_hash_lock = threading.Lock()
_img_hash_map: dict[str, tuple[str, float]] = {}   # hash -> (signed_url, ts_seen)


def _img_stable_hash(account_id: str, u: str) -> str:
    """SHA-1 (truncated to 20 hex chars) over the stable identity of an
    OF CDN asset. Drops the query string (Policy/Signature/Key-Pair-Id),
    lowercases the host, scopes by account so two accounts can't collide
    on a shared asset that might be re-signed differently."""
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(u)
    base = (parsed.hostname or "").lower() + (parsed.path or "")
    return hashlib.sha1(f"{account_id}\0{base}".encode("utf-8")).hexdigest()[:20]


def _img_hash_remember(account_id: str, u: str) -> str:
    """Record (or refresh) the hash → signed-URL mapping. Returns the hash.
    Naive size-cap: when over _IMG_HASH_CAP, drop oldest 10% by ts."""
    h = _img_stable_hash(account_id, u)
    now = _time_mod.monotonic()
    with _img_hash_lock:
        _img_hash_map[h] = (u, now)
        if len(_img_hash_map) > _IMG_HASH_CAP:
            # Sort once, drop the bottom 10% in one pass — cheaper than
            # per-eviction in steady state. Triggered rarely (only at cap).
            ordered = sorted(_img_hash_map.items(), key=lambda kv: kv[1][1])
            for k, _ in ordered[: len(ordered) // 10]:
                _img_hash_map.pop(k, None)
    return h


# ── On-disk image cache ───────────────────────────────────────────────
#
# Persistent cache for /img bytes, keyed by hostname+path (signature
# stripped) so it's shared across all accounts/users. Motivation:
#
#   - OF CDN URLs carry a Policy/Signature query string that rotates
#     every ~hours. The browser HTTP cache keys on the full URL, so
#     the moment OF hands us a freshly-signed URL for the same physical
#     asset (chat refetch, vault re-list, signature expiry) the browser
#     cache misses even within the same session.
#   - This cache keys on host+path → those re-signed URLs become disk
#     hits. Same physical image, served from disk, no upstream call.
#   - User A and user B viewing the same chat/profile both hit the same
#     bytes — cross-session sharing without a CDN round-trip each.
#
# Only stores SMALL FULL responses. Range requests (browser <video>) and
# 206 partials are never cached — partials would poison the cache, and
# videos are huge. _IMG_CACHE_MAX_BYTES caps per-file size as a safety
# net even when Content-Length isn't trustworthy.
_IMG_CACHE_DIR = Path(os.environ.get("IMG_CACHE_DIR", "/tmp/of-relay-img-cache"))
_IMG_CACHE_MAX_BYTES = int(os.environ.get("IMG_CACHE_MAX_BYTES", str(2 * 1024 * 1024)))
_IMG_CACHE_TTL_S = int(os.environ.get("IMG_CACHE_TTL_S", str(7 * 24 * 60 * 60)))
_IMG_CACHE_EVICT_INTERVAL_S = 30 * 60
_img_cache_hits: int = 0
_img_cache_misses: int = 0
# Requests that missed on the first look, queued for a fetch slot, and found
# the bytes already on disk when their turn came — i.e. a herd that collapsed
# instead of each member paying its own OF round-trip. Counted apart from
# `hits` on purpose: a rising number here is the cold-pane storm being absorbed,
# which is a different thing to report than a warm cache.
_img_cache_collapsed: int = 0
_img_cache_writes: int = 0
_img_cache_skipped_partial: int = 0
_img_cache_skipped_too_big: int = 0
_img_cache_write_errors: int = 0


def _img_cache_key(u: str) -> str:
    """Account-agnostic SHA-1 over host+path. Same physical asset → same
    key, regardless of which account fetched it or how OF signed the URL."""
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(u)
    base = (parsed.hostname or "").lower() + (parsed.path or "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def _img_cache_paths(h: str) -> tuple[Path, Path]:
    """Returns (bytes_path, content_type_path). Sharded into 2-char dirs
    so any one dir doesn't grow unbounded (matters for ext4/some FS)."""
    sub = _IMG_CACHE_DIR / h[:2]
    return sub / f"{h}.bin", sub / f"{h}.ct"


def _img_cache_lookup(u: str) -> tuple[Path, str] | None:
    """Returns (bytes_path, content_type) if a complete cache entry exists,
    else None. A complete entry has BOTH .bin and .ct present — half-written
    state is invisible (writers use unique .tmp paths and atomic rename)."""
    h = _img_cache_key(u)
    bin_p, ct_p = _img_cache_paths(h)
    if not bin_p.is_file() or not ct_p.is_file():
        return None
    try:
        ct = ct_p.read_text(encoding="utf-8", errors="replace").strip() or "application/octet-stream"
    except OSError:
        return None
    return bin_p, ct


def _img_cache_touch(bin_p: Path, ct_p: Path) -> None:
    """Refresh an entry's mtime on a cache HIT so the TTL evictor ages it by
    last-ACCESS, not last-WRITE. Without this a frequently-served image (a
    popular vault preview shared by many messages) is evicted at
    _IMG_CACHE_TTL_S even while in active use, forcing a CDN refetch and a
    visible tile flicker. Throttled: only bumps when the entry is already
    older than one evict interval, so a hot file costs at most ~one utime per
    interval — not one per request. Best-effort; never raises into the
    request path."""
    try:
        now = _time_mod.time()
        if now - bin_p.stat().st_mtime < _IMG_CACHE_EVICT_INTERVAL_S:
            return  # touched recently — skip the syscall
        os.utime(bin_p, (now, now))
        try:
            os.utime(ct_p, (now, now))
        except OSError:
            pass
    except OSError:
        pass


def _img_cache_write(u: str, content_type: str, data: bytes) -> bool:
    """Atomically write `data` for `u` to the cache. Unique .tmp filename
    + rename means concurrent writers for the same hash don't corrupt
    each other (last writer wins, identical bytes either way). Returns
    True on success."""
    global _img_cache_writes, _img_cache_write_errors
    h = _img_cache_key(u)
    bin_p, ct_p = _img_cache_paths(h)
    try:
        bin_p.parent.mkdir(parents=True, exist_ok=True)
        suffix = f".tmp.{os.getpid()}.{threading.get_ident()}"
        tmp_bin = bin_p.with_suffix(bin_p.suffix + suffix)
        tmp_ct = ct_p.with_suffix(ct_p.suffix + suffix)
        tmp_bin.write_bytes(data)
        tmp_ct.write_text(content_type, encoding="utf-8")
        os.replace(tmp_bin, bin_p)
        os.replace(tmp_ct, ct_p)
        _img_cache_writes += 1
        return True
    except OSError:
        _img_cache_write_errors += 1
        # Best-effort cleanup of leftover .tmp files; ignore errors.
        for p in (tmp_bin, tmp_ct):  # type: ignore[possibly-unbound]
            try: p.unlink()
            except (OSError, NameError): pass
        return False


def _img_cache_evict_once() -> int:
    """Walk the cache dir and delete entries older than _IMG_CACHE_TTL_S
    (by mtime). Returns the number of (bin, ct) pairs removed. Cheap on
    a few-tens-of-thousands of files; if the cache grows past that we'd
    want a smarter index, but this is fine for current expected size."""
    if not _IMG_CACHE_DIR.exists():
        return 0
    import time as _t
    cutoff = _t.time() - _IMG_CACHE_TTL_S
    removed = 0
    # Pinned just-sent media (Wave 2.1) is protected from TTL eviction
    # during its warm-up window so the local copy always outlives OF's
    # CDN cold-start. Prune expired pins first, then snapshot the surviving
    # key set so we can skip those files below.
    _pin_prune_expired()
    with _pin_lock:
        protected = set(_pinned_keys)
    try:
        for sub in _IMG_CACHE_DIR.iterdir():
            if not sub.is_dir():
                continue
            for f in sub.iterdir():
                try:
                    if f.stem in protected:
                        continue
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                        if f.suffix == ".bin":
                            removed += 1
                except OSError:
                    continue
    except OSError:
        return removed
    return removed


async def _img_cache_sweep() -> None:
    removed = await asyncio.to_thread(_img_cache_evict_once)
    if removed:
        log.info("img cache evicted: %d entries (TTL=%ds)", removed, _IMG_CACHE_TTL_S)


async def _img_cache_evictor_loop() -> None:
    """Periodic TTL sweep. Same shape as storyboard._storyboard_evictor_loop."""
    await _periodic("img cache evictor", _IMG_CACHE_EVICT_INTERVAL_S, _img_cache_sweep)


# ── Pinned outbound media (Wave 2.1) ──────────────────────────────────
#
# When WE send an image, the frontend renders it instantly from a local
# blob (useSendMessage `_localPreview`). After OF reconciles the message,
# the bubble swaps to /img?u=<of-cdn-url>. That CDN URL can be COLD for
# the first seconds/minutes after upload — OF's edge hasn't warmed the
# object yet — so a just-sent image can flip to a slow/blank state.
#
# Fix: right after a successful send, fetch the freshly-signed media URLs
# server-side ONCE and write the bytes into the on-disk /img cache under
# their host+path key — the SAME key the reconciled /img?u= request will
# resolve to (signature stripped, see `_img_cache_key`). The reconciled
# bubble then disk-HITs our local copy instead of racing OF's cold edge.
#
# We track the pin by MEDIA ID so (a) we never re-fetch the same media
# twice and (b) the TTL evictor leaves the entry alone during the warm-up
# window — guaranteeing the local copy outlives the CDN cold-start
# regardless of cache pressure. After the window, normal TTL reclaims it.
_IMG_PIN_WARM_S = int(os.environ.get("IMG_PIN_WARM_S", str(24 * 60 * 60)))
_IMG_PIN_MAX_URLS = 6                 # cap variants warmed per media (full/thumb/preview/…)
_pin_lock = threading.Lock()
# media_id -> {"keys": set[str], "pinned_at": float (monotonic)}
_pinned_media: dict[str, dict[str, Any]] = {}
_pinned_keys: set[str] = set()        # union of pinned cache-key hashes (fast evictor skip)
_img_pins_added: int = 0
_img_pins_fetched: int = 0
_img_pins_fetch_errors: int = 0
_img_pins_skipped_existing: int = 0


def _pin_prune_expired() -> None:
    """Drop pins past the warm-up window so normal TTL can reclaim their
    bytes, and rebuild the flat key set from survivors. Cheap; safe to
    call on every evictor pass."""
    now = _time_mod.monotonic()
    with _pin_lock:
        stale = [m for m, p in _pinned_media.items()
                 if now - p["pinned_at"] > _IMG_PIN_WARM_S]
        if not stale:
            return
        for m in stale:
            _pinned_media.pop(m, None)
        _pinned_keys.clear()
        for p in _pinned_media.values():
            _pinned_keys.update(p["keys"])


def _media_urls_from_result(result: Any) -> list[tuple[str, list[str]]]:
    """Extract [(media_id, [absolute CDN urls])] from an OF send response.
    Tolerant of shape drift: walks a top-level `media` list (the
    /chats/{id}/messages send echo) and pulls every `files.*.url` plus any
    top-level src/preview/thumb url on the item. Returns [] for shapes
    without per-message media (mass/queue echoes), so it's a no-op there."""
    out: list[tuple[str, list[str]]] = []
    if not isinstance(result, dict):
        return out
    media = result.get("media")
    if not isinstance(media, list):
        return out
    for it in media:
        if not isinstance(it, dict):
            continue
        mid = it.get("id")
        if mid is None:
            continue
        urls: list[str] = []
        files = it.get("files")
        if isinstance(files, dict):
            for variant in files.values():
                if isinstance(variant, dict):
                    u = variant.get("url")
                    if isinstance(u, str) and u.startswith("http"):
                        urls.append(u)
        for k in ("full", "src", "preview", "thumb", "squareThumb"):
            u = it.get(k)
            if isinstance(u, str) and u.startswith("http"):
                urls.append(u)
        if urls:
            out.append((str(mid), urls))
    return out


def _pin_one_media_blocking(account_id: str, media_id: str, urls: list[str]) -> None:
    """Fetch each variant's bytes (via the account's OF client) and write
    them into the on-disk /img cache under their host+path key, then record
    the pin keyed by media id. Runs in a worker thread (blocking curl).
    Best-effort — never raises out."""
    global _img_pins_fetched, _img_pins_fetch_errors, _img_pins_added, _img_pins_skipped_existing
    from urllib.parse import urlparse as _urlparse
    # Dedup by cache key (variants can share a path) and cap how many we warm.
    seen: dict[str, str] = {}   # cache_key -> url
    for u in urls:
        try:
            host = (_urlparse(u).hostname or "").lower()
        except Exception:
            continue
        if not any(host.endswith(s) for s in _ALLOWED_CDN_SUFFIXES):
            continue
        seen.setdefault(_img_cache_key(u), u)
        if len(seen) >= _IMG_PIN_MAX_URLS:
            break
    if not seen:
        return
    try:
        client = _load_client(account_id)
    except Exception:
        return
    pinned: set[str] = set()
    for k, u in seen.items():
        # Already on disk (e.g. re-sending a vault asset we've served
        # before) → no fetch, just pin the existing entry so the evictor
        # protects it for the warm-up window.
        if _img_cache_lookup(u) is not None:
            pinned.add(k)
            _img_pins_skipped_existing += 1
            continue
        try:
            with _priority_lane_background(account_id):
                r = client.http.get(u, timeout=client.timeout_s, stream=False)
            if r.status_code != 200:
                _img_pins_fetch_errors += 1
                continue
            data = r.content or b""
            # Honour the same size cap as the live cache — a >2MB asset
            # wouldn't be disk-cached on reconcile anyway, so pinning it
            # would just be dead weight the serve path can't use.
            if not (0 < len(data) <= _IMG_CACHE_MAX_BYTES):
                continue
            ct = r.headers.get("Content-Type", "application/octet-stream")
            if _img_cache_write(u, ct, data):
                pinned.add(k)
                _img_pins_fetched += 1
        except Exception:
            _img_pins_fetch_errors += 1
            continue
    if not pinned:
        return
    now = _time_mod.monotonic()
    with _pin_lock:
        entry = _pinned_media.get(media_id)
        if entry is None:
            entry = {"keys": set(), "pinned_at": now}
            _pinned_media[media_id] = entry
        entry["keys"] |= pinned
        entry["pinned_at"] = now
        _pinned_keys.update(pinned)
    _img_pins_added += 1


def _pin_sent_media(account_id: str, result: Any) -> None:
    """Fire-and-forget from a send handler: warm + pin the on-disk /img
    cache with the bytes of any media in an outbound send response, so the
    reconciled bubble serves a local copy instead of OF's cold edge.
    Reserves the media id under the lock immediately so concurrent/rapid
    sends of the same asset don't double-fetch. Never blocks the response;
    never raises."""
    try:
        items = _media_urls_from_result(result)
    except Exception:
        return
    if not items:
        return
    _pin_prune_expired()
    now = _time_mod.monotonic()
    fresh: list[tuple[str, list[str]]] = []
    with _pin_lock:
        for media_id, urls in items:
            if media_id in _pinned_media:
                continue
            # Reserve now (empty key set) so a second send of the same media
            # in-flight is deduped; the worker fills in the keys on success.
            _pinned_media[media_id] = {"keys": set(), "pinned_at": now}
            fresh.append((media_id, urls))
    for media_id, urls in fresh:
        try:
            asyncio.create_task(
                asyncio.to_thread(_pin_one_media_blocking, account_id, media_id, urls)
            )
        except Exception:
            log.debug("pin dispatch failed (media_id=%s)", media_id, exc_info=True)


@streams_router.get("/admin/streams")
def admin_streams() -> dict:
    """Live view of the /img stream budget. `active` = currently streaming
    right now; `high_water` = peak since startup. If active sits near the
    thread-pool limit while you scroll, that's the bottleneck. If it stays
    low but you still see ECONNRESETs, look elsewhere (Next dev proxy,
    upstream OF, network)."""
    return {
        "active": _img_active,
        "high_water": _img_high_water,
        "total_started": _img_total_started,
        "total_aborted": _img_total_aborted,
        # `collapsed` is the one to watch on a cold pane: it counts the storms
        # the fetch lane absorbed rather than passed on to OF.
        "img_cache_collapsed": _img_cache_collapsed,
        # Every lane reports itself — derived, not restated, so a lane added
        # later cannot be forgotten in the diagnostics that would show it
        # saturating. See service/admission.py.
        **admission.all_stats(),
    }


@router.get("/img")
def proxy_image(request: Request, u: str = Query(..., description="Absolute OF CDN URL")):
    """Fetch `u` via the requesting account's OF client (so the source IP
    matches the URL's signed Policy) and stream the bytes back. The unsigned
    static hosts (`_DIRECT_CDN_HOST`) are the exception: they go out the
    relay's own IP on `_DIRECT_HTTP`, with no cookies or account headers."""
    from urllib.parse import urlparse
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="bad scheme")
    host = (parsed.hostname or "").lower()
    if not any(host.endswith(s) for s in _ALLOWED_CDN_SUFFIXES):
        raise HTTPException(status_code=400, detail="host not allowed")

    range_hdr = request.headers.get("range") or request.headers.get("Range")

    # Disk-cache fast path: only safe when the client wants the WHOLE
    # asset (no Range). Cached bytes are account-agnostic — once we have
    # them, the upstream signature is irrelevant for serving them again.
    # Skipped on Range because we don't store partials.
    if not range_hdr:
        global _img_cache_hits, _img_cache_misses
        hit = _img_cache_lookup(u)
        if hit is not None:
            _img_cache_hits += 1
            return _serve_cached(hit, u, label="HIT")
        _img_cache_misses += 1

    if _DIRECT_CDN_HOST.fullmatch(host):
        http, timeout_s = _DIRECT_HTTP, DEFAULT_TIMEOUT_S
    else:
        client = _get_client(request)
        http, timeout_s = client.http, client.timeout_s

    # Forward the browser's Range header so video <video> tags can seek.
    # Without this, the upstream always returns 200 with the whole file and
    # the browser can't jump past whatever's buffered — long videos can't
    # be scrubbed, and `currentTime` writes stall.
    upstream_headers: dict[str, str] = {}
    if range_hdr:
        upstream_headers["Range"] = range_hdr

    # A Range request is a browser <video> seeking and has its own ceiling;
    # everything reaching here without one is a cache miss on its way to OF.
    # Picking the lane rather than branching on it keeps ONE admission site —
    # the rejection reads the same for both because the lane names itself.
    held = admission.VIDEO_STREAM if range_hdr else admission.IMG_FETCH
    if not held.enter(u[:80]):
        raise HTTPException(
            status_code=503,
            detail=f"too many {held.name} requests in flight; retry shortly",
        )

    if not range_hdr:
        # Re-read the store INSIDE the slot, the same way vault_stills does.
        # Forty tiles opening on one media all miss together, all queue here,
        # and without this re-read each would then pay its own OF round-trip
        # for bytes the first waiter has already written. The cap bounds how
        # many run at once; this is what stops them being redundant.
        hit = _img_cache_lookup(u)
        if hit is not None:
            held.exit()
            global _img_cache_collapsed
            # Not also counted as a hit: this request DID miss, and was already
            # tallied as one above. `collapsed` is the separate story of how
            # many of those misses the lane absorbed instead of forwarding.
            _img_cache_collapsed += 1
            return _serve_cached(hit, u, label="COLLAPSED")

    # From here to the `return StreamingResponse` the slot is held by THIS
    # frame; past it, `_safe_iter`'s finally owns the release. Everything
    # between is wrapped because a lane that leaks a slot never gets it back —
    # it drains to zero and then rejects every request forever. Three
    # hand-placed release sites used to cover only the two failures anyone had
    # thought of, leaving the header-building below unguarded.
    #
    # The unwind closes the upstream response too. That is not hypothetical
    # tidiness: OF answers 403 on an expired signature, which is the single most
    # common failure this proxy sees, and an unclosed streamed response holds its
    # socket. Leaking a descriptor per expired thumbnail, inside the very
    # function whose descriptor use took the process down, is the bug this whole
    # change exists to prevent.
    r = None
    try:
        try:
            r = http.get(
                u, timeout=timeout_s, stream=True,
                headers=upstream_headers or None,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"upstream fetch failed: {e}")
        # 206 (Partial Content) is the normal Range response — treat it as ok.
        if r.status_code not in (200, 206):
            raise HTTPException(status_code=r.status_code, detail="upstream non-2xx")
        return _stream_upstream(
            r, u, held, range_hdr,
            account_id_hdr=request.headers.get("x-account-id") or "")
    except BaseException:
        if r is not None:
            try: r.close()
            except Exception: pass
        held.exit()
        raise


def _serve_cached(hit: tuple[Path, str], u: str, *, label: str) -> FileResponse:
    """Serve bytes we already have on disk.

    `label` rides out as `X-Img-Cache` and is the only thing that differs
    between the two ways we get here — a first-look hit, and a waiter that
    found the bytes written while it queued for a fetch slot. They were two
    copies of this block; the header value is not a reason to have two.
    """
    bin_p, ct_cached = hit
    # Keep popular entries warm: age by last-access, not last-write, so a hot
    # vault preview isn't evicted out from under live use.
    _img_cache_touch(*_img_cache_paths(_img_cache_key(u)))
    return FileResponse(
        str(bin_p),
        media_type=ct_cached,
        headers={
            "Cache-Control":
                "public, max-age=604800, stale-while-revalidate=86400, immutable",
            "X-Img-Cache": label,
        },
    )


def _stream_upstream(r: Any, u: str, held: admission.Lane,
                     range_hdr: str | None, *,
                     account_id_hdr: str) -> StreamingResponse:
    """Wrap a live upstream response as the streamed reply, handing `held` to
    the generator — which is what releases it, whether the stream ends, the
    client vanishes, or the max-age timer fires.

    Takes the account id rather than the `Request` it came from: this streams
    bytes and needs exactly one header off the caller, and a helper holding a
    whole request object invites the next person to reach for more of it.

    ⚠️ The release lives in the generator's `finally`, so it depends on
    something iterating the generator. Starlette always does — including closing
    it on client disconnect, which arrives as GeneratorExit and is caught — but
    that is the one assumption keeping this lane from leaking, and it is why the
    caller unwinds by hand for every path that returns BEFORE this point.
    """
    ct = r.headers.get("Content-Type", "application/octet-stream")
    # OF's CDN sends short Cache-Control because the signed Policy expires,
    # but the IMAGE BYTES themselves don't expire. We override upstream's
    # header to keep the browser HTTP cache (and a future Service Worker)
    # holding the asset for 7 days — matches the disk-cache TTL above so
    # the browser doesn't re-fetch bytes we still have on disk. Once we've
    # fetched the bytes, the upstream signature is irrelevant for serving
    # them again. SWR window of 1 day lets the SW serve a stale copy
    # instantly while silently refreshing in the background.
    cache_control = "public, max-age=604800, stale-while-revalidate=86400, immutable"
    out_headers = {"Cache-Control": cache_control}
    # Stable hash exposed back to the browser so the frontend can pivot
    # to /img/by-hash/<h> on subsequent renders — same image, same key,
    # even after OF rotates the upstream signature.
    if account_id_hdr:
        try:
            h_stable = _img_hash_remember(account_id_hdr, u)
            out_headers["X-Img-Hash"] = h_stable
        except Exception:
            # Hashing should never fail (urlparse + sha1), but if it does
            # we just skip the header — the proxy still works.
            pass
    # Pass through the bits the <video> element relies on to seek. Without
    # Accept-Ranges Chrome won't even attempt a Range request; without
    # Content-Range it can't tell what slice it got back.
    for h in ("Content-Range", "Accept-Ranges", "Content-Length", "ETag", "Last-Modified"):
        v = r.headers.get(h)
        if v:
            out_headers[h] = v
    if "Accept-Ranges" not in out_headers:
        # If upstream didn't advertise but we got 206/200, hint that we
        # support ranges so the browser will try one next time.
        out_headers["Accept-Ranges"] = "bytes"

    # Wrap iter_content so a browser-side abort (the common case — user
    # hovers a new tile, the old <video> unmounts, the TCP socket dies)
    # cleanly closes the upstream connection instead of bubbling up as
    # an unhandled ChunkedEncodingError / ConnectionResetError that the
    # worker would otherwise log as a 500 and tear down the thread.
    # Also enforces a hard max-stream-age so a `/img` stream can't pin a
    # worker thread for the full lifetime of an mp4 — uvicorn's graceful
    # shutdown was taking 2+ minutes because in-flight streams blocked on
    # iter_content() and never noticed the shutdown signal. After
    # _MAX_STREAM_SEC we bail; the browser will reissue a Range request
    # for the rest, which is what `<video>` elements do natively anyway.
    _MAX_STREAM_SEC = 60
    import time as _time
    started_mono = _time.monotonic()

    # Tee bytes to the disk cache only when the upstream response is a
    # complete 200 (not 206), the request had no Range, and Content-Length
    # is either unknown or under the cap. We additionally enforce the cap
    # while streaming — past it, we drop the buffer rather than allocate
    # unbounded memory for a video that slipped past the host filter.
    out_headers["X-Img-Cache"] = "MISS" if not range_hdr else "BYPASS"
    cache_buffer: bytearray | None = None
    if not range_hdr and r.status_code == 200:
        try:
            advertised = int(r.headers.get("Content-Length") or 0)
        except ValueError:
            advertised = 0
        if 0 < advertised <= _IMG_CACHE_MAX_BYTES or advertised == 0:
            cache_buffer = bytearray()
        else:
            global _img_cache_skipped_too_big
            _img_cache_skipped_too_big += 1
    elif r.status_code == 206:
        global _img_cache_skipped_partial
        _img_cache_skipped_partial += 1

    def _safe_iter():
        global _img_active, _img_high_water, _img_total_started, _img_total_aborted
        global _img_cache_skipped_too_big
        _img_active += 1
        _img_total_started += 1
        if _img_active > _img_high_water:
            _img_high_water = _img_active
        aborted = False
        completed = False
        local_buf = cache_buffer
        try:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if _time.monotonic() - started_mono > _MAX_STREAM_SEC:
                    # Hit our cap — close upstream so the worker thread
                    # is reusable. The browser will Range-request the
                    # tail if it still wants more bytes.
                    break
                if chunk:
                    if local_buf is not None:
                        if len(local_buf) + len(chunk) > _IMG_CACHE_MAX_BYTES:
                            # Asset grew past the cap mid-stream — drop
                            # the buffer (don't cache), keep streaming.
                            _img_cache_skipped_too_big += 1
                            local_buf = None
                        else:
                            local_buf.extend(chunk)
                    yield chunk
            else:
                completed = True
        except (ConnectionResetError, BrokenPipeError, GeneratorExit):
            # Client went away — silent, this is normal browser behavior
            # for unmounting video elements.
            aborted = True
        except Exception:
            aborted = True
            log.warning("upstream stream error mid-flight (u=%s)", u[:120], exc_info=True)
        finally:
            if aborted:
                _img_total_aborted += 1
            _img_active = max(0, _img_active - 1)
            try:
                r.close()
            except Exception:
                pass
            # Only persist when the full upstream body landed cleanly.
            # Aborted/truncated bodies must never enter the cache.
            if completed and not aborted and local_buf is not None and len(local_buf) > 0:
                try:
                    _img_cache_write(u, ct, bytes(local_buf))
                except Exception:
                    log.warning("img cache write failed (u=%s)", u[:120], exc_info=True)
            # Released LAST, after the bytes are on disk. The waiter this hands
            # the slot to re-reads the store as its first act, so releasing
            # before the write is a race that costs exactly what the re-read
            # exists to save: it wakes, finds nothing, and pays its own
            # round-trip for bytes that were milliseconds away.
            held.exit()

    return StreamingResponse(
        _safe_iter(),
        media_type=ct,
        status_code=r.status_code,
        headers=out_headers,
    )


@router.get("/img/by-hash/{h}")
def proxy_image_by_hash(request: Request, h: str):
    """Stable-URL alias for /img. Resolves the hash to the most recent
    signed URL we've seen for it, then delegates to proxy_image. Returns
    410 if the signed URL has aged past _IMG_HASH_TTL_S — at that point
    the upstream signature is likely expired and the frontend should
    fetch a fresh URL from /messages (or whatever surface produced this
    asset originally) and call /img?u=... directly.

    The browser's Cache-Control window (2 days) is much longer than the
    upstream signature window (~1h), so most hits never reach the server
    at all — only first-sight requests touch us here."""
    with _img_hash_lock:
        entry = _img_hash_map.get(h)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail="unknown img hash; refetch the producing endpoint for a fresh signed URL",
        )
    u, ts = entry
    if _time_mod.monotonic() - ts > _IMG_HASH_TTL_S:
        # Drop the stale entry while we're here.
        with _img_hash_lock:
            _img_hash_map.pop(h, None)
        raise HTTPException(
            status_code=410,
            detail="signed URL expired; refetch the producing endpoint for a fresh one",
        )
    return proxy_image(request, u=u)


@cache_router.get("/admin/img-cache/disk")
def admin_img_cache_disk() -> dict:
    """Disk cache stats. `hit_rate` is the headline number — if it stays
    near zero, the cache isn't paying for itself; if it climbs past ~0.4
    we're saving meaningful upstream calls. `bytes` is a `du`-equivalent
    of the cache root so we can see growth over time."""
    total_bytes = 0
    entry_count = 0
    try:
        if _IMG_CACHE_DIR.exists():
            for sub in _IMG_CACHE_DIR.iterdir():
                if not sub.is_dir():
                    continue
                for f in sub.iterdir():
                    try:
                        st = f.stat()
                        total_bytes += st.st_size
                        if f.suffix == ".bin":
                            entry_count += 1
                    except OSError:
                        continue
    except OSError:
        pass
    total = _img_cache_hits + _img_cache_misses
    hit_rate = (_img_cache_hits / total) if total else 0.0
    return {
        "dir": str(_IMG_CACHE_DIR),
        "entries": entry_count,
        "bytes": total_bytes,
        "hits": _img_cache_hits,
        "misses": _img_cache_misses,
        "writes": _img_cache_writes,
        "hit_rate": round(hit_rate, 3),
        "skipped_partial": _img_cache_skipped_partial,
        "skipped_too_big": _img_cache_skipped_too_big,
        "write_errors": _img_cache_write_errors,
        "max_bytes_per_entry": _IMG_CACHE_MAX_BYTES,
        "ttl_seconds": _IMG_CACHE_TTL_S,
        # Wave 2.1 pinned-outbound-media stats.
        "pins_active": len(_pinned_media),
        "pinned_keys": len(_pinned_keys),
        "pins_added": _img_pins_added,
        "pins_fetched": _img_pins_fetched,
        "pins_skipped_existing": _img_pins_skipped_existing,
        "pins_fetch_errors": _img_pins_fetch_errors,
        "pin_warm_seconds": _IMG_PIN_WARM_S,
    }


@cache_router.get("/admin/img-cache/stats")
def admin_img_cache_stats() -> dict:
    """Live view of the hash → signed-URL map. `entries` counts distinct
    images we've ever proxied since boot; `freshest_age_s` shows how
    recently we saw activity. Used to gauge whether /img/by-hash is
    actually doing work (entries climbing == hits expected to follow)."""
    now = _time_mod.monotonic()
    with _img_hash_lock:
        n = len(_img_hash_map)
        if n:
            ages = [now - ts for _, ts in _img_hash_map.values()]
            oldest_age = int(max(ages))
            freshest_age = int(min(ages))
        else:
            oldest_age = 0
            freshest_age = 0
    return {
        "entries": n,
        "cap": _IMG_HASH_CAP,
        "ttl_seconds": _IMG_HASH_TTL_S,
        "oldest_age_s": oldest_age,
        "freshest_age_s": freshest_age,
    }
