from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import threading
import time as _time_mod
from pathlib import Path
from typing import Any, Callable

from curl_cffi import requests as curl_requests
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

import admission
import cdn_resign
import img_clip
from of_client import DEFAULT_TIMEOUT_S, IMPERSONATE, OF_CDN_SUFFIXES
from relay_host import get_request_client as _get_client
from relay_host import load_client as _load_client
from relay_host import periodic as _periodic
from relay_host import priority_lane_background as _priority_lane_background

log = logging.getLogger("of-relay")

router = APIRouter()
streams_router = APIRouter()
cache_router = APIRouter()



# OF's CDN signs URLs with AWS:SourceIp=<egress IP>/32, so the fetch is tunnelled through the account's client; known CDN hosts only (SSRF).
_ALLOWED_CDN_SUFFIXES = (
    *OF_CDN_SUFFIXES,
    ".fansly.com",
)

# Unsigned static hosts (desktop sends them direct too) go out the relay's own WAN to save proxy bandwidth; signed cdn*.onlyfans.com stays on the account's proxy.
_DIRECT_CDN_HOST = re.compile(r"static\d*\.onlyfans\.com|public\.onlyfans\.com")
# Bare session, never the account's: a fetch from the relay's own IP must carry nothing naming an account, or it links the account to that IP.
_DIRECT_HTTP = curl_requests.Session(impersonate=IMPERSONATE, discard_cookies=True)

_img_active: int = 0
_img_high_water: int = 0
_img_total_started: int = 0
_img_total_aborted: int = 0


# Signed URLs rotate per upstream fetch (~1h lifetime), so the browser caches on this stable hash; after expiry by-hash is 410 and the frontend falls back to /img?u=.
_IMG_HASH_TTL_S = 60 * 60
_IMG_HASH_CAP = 50_000
_img_hash_lock = threading.Lock()
_img_hash_map: dict[str, tuple[str, float]] = {}


def _img_stable_hash(account_id: str, u: str) -> str:
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(u)
    base = (parsed.hostname or "").lower() + (parsed.path or "")
    return hashlib.sha1(f"{account_id}\0{base}".encode("utf-8")).hexdigest()[:20]


def _img_hash_remember(account_id: str, u: str) -> str:
    h = _img_stable_hash(account_id, u)
    now = _time_mod.monotonic()
    with _img_hash_lock:
        _img_hash_map[h] = (u, now)
        if len(_img_hash_map) > _IMG_HASH_CAP:
            ordered = sorted(_img_hash_map.items(), key=lambda kv: kv[1][1])
            for k, _ in ordered[: len(ordered) // 10]:
                _img_hash_map.pop(k, None)
    return h


# Keyed on host+path (signature stripped) so re-signed URLs hit and accounts share bytes; whole objects only, never a partial.
_IMG_CACHE_DIR = Path(os.environ.get("IMG_CACHE_DIR", "/tmp/of-relay-img-cache"))
_IMG_CACHE_MAX_BYTES = int(os.environ.get("IMG_CACHE_MAX_BYTES", str(2 * 1024 * 1024)))
_IMG_CACHE_TTL_S = int(os.environ.get("IMG_CACHE_TTL_S", str(7 * 24 * 60 * 60)))
_IMG_CACHE_EVICT_INTERVAL_S = 30 * 60
# Ceiling of the whole store (it shares the disk with SQLite): past it each sweep deletes the least recently used.
_IMG_CACHE_BUDGET_BYTES = 2 * 1024 * 1024 * 1024
# private: a Creator's media is kept by the browser, never by a shared cache.
_CACHE_CONTROL = "private, max-age=604800, stale-while-revalidate=86400, immutable"
IMG_RESIGN = "img_resign"
_img_cache_hits: int = 0
_img_cache_misses: int = 0
_img_cache_collapsed: int = 0
_img_cache_writes: int = 0
_img_cache_skipped_partial: int = 0
_img_cache_skipped_too_big: int = 0
_img_cache_write_errors: int = 0


def _img_cache_key(u: str) -> str:
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(u)
    base = (parsed.hostname or "").lower() + (parsed.path or "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def _img_cache_paths(h: str) -> tuple[Path, Path]:
    sub = _IMG_CACHE_DIR / h[:2]
    return sub / f"{h}.bin", sub / f"{h}.ct"


def _img_cache_lookup(u: str) -> tuple[Path, str] | None:
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
    try:
        now = _time_mod.time()
        if now - bin_p.stat().st_mtime < _IMG_CACHE_EVICT_INTERVAL_S:
            return
        os.utime(bin_p, (now, now))
        try:
            os.utime(ct_p, (now, now))
        except OSError:
            pass
    except OSError:
        pass


def _img_cache_write(u: str, content_type: str, data: bytes) -> bool:
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
        for p in (tmp_bin, tmp_ct):  # type: ignore[possibly-unbound]
            try: p.unlink()
            except (OSError, NameError): pass
        return False


def _img_cache_evict_once() -> int:
    if not _IMG_CACHE_DIR.exists():
        return 0
    import time as _t
    cutoff = _t.time() - _IMG_CACHE_TTL_S
    removed = 0
    # Pinned just-sent media is protected from TTL eviction during its warm-up so the local copy outlives OF's CDN cold-start.
    _pin_prune_expired()
    with _pin_lock:
        protected = set(_pinned_keys)
    kept: list[tuple[float, int, Path]] = []
    try:
        for sub in _IMG_CACHE_DIR.iterdir():
            if not sub.is_dir():
                continue
            for f in sub.iterdir():
                try:
                    if f.stem in protected:
                        continue
                    st = f.stat()
                    if st.st_mtime < cutoff:
                        f.unlink()
                        if f.suffix == ".bin":
                            removed += 1
                    elif f.suffix == ".bin":
                        kept.append((st.st_mtime, st.st_size, f))
                except OSError:
                    continue
    except OSError:
        return removed
    total = sum(size for _, size, _ in kept)
    for _, size, f in sorted(kept):
        if total <= _IMG_CACHE_BUDGET_BYTES:
            break
        for p in (f, f.with_suffix(".ct")):
            try:
                p.unlink()
            except OSError:
                pass
        total -= size
        removed += 1
    return removed


async def _img_cache_sweep() -> None:
    removed = await asyncio.to_thread(_img_cache_evict_once)
    if removed:
        log.info("img cache evicted: %d entries (TTL=%ds, budget=%dB)", removed, _IMG_CACHE_TTL_S,
                 _IMG_CACHE_BUDGET_BYTES)


async def _img_cache_evictor_loop() -> None:
    await _periodic("img cache evictor", _IMG_CACHE_EVICT_INTERVAL_S, _img_cache_sweep)


# A just-sent image's CDN URL can be cold for seconds/minutes: its bytes are cached under the same host+path key the reconciled /img?u= resolves to.
_IMG_PIN_WARM_S = int(os.environ.get("IMG_PIN_WARM_S", str(24 * 60 * 60)))
_IMG_PIN_MAX_URLS = 6
_pin_lock = threading.Lock()
_pinned_media: dict[str, dict[str, Any]] = {}
_pinned_keys: set[str] = set()
_img_pins_added: int = 0
_img_pins_fetched: int = 0
_img_pins_fetch_errors: int = 0
_img_pins_skipped_existing: int = 0


def _pin_prune_expired() -> None:
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
    global _img_pins_fetched, _img_pins_fetch_errors, _img_pins_added, _img_pins_skipped_existing
    from urllib.parse import urlparse as _urlparse
    seen: dict[str, str] = {}
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
        "img_cache_collapsed": _img_cache_collapsed,
        **admission.all_stats(),
    }


@router.get("/img")
async def proxy_image(
    request: Request,
    u: str = Query(..., description="Absolute OF CDN URL"),
    media_id: int | None = Query(None, description="The vault media `u` belongs to. When set, an upstream 403 (url signed for the account's old proxy IP, or expired) re-reads that media from OF and retries once with its fresh url for the same file."),
):
    """Fetch `u` via the requesting account's OF client (so the source IP
    matches the URL's signed Policy) and stream the bytes back. The unsigned
    static hosts (`_DIRECT_CDN_HOST`) are the exception: they go out the
    relay's own IP on `_DIRECT_HTTP`, with no cookies or account headers.
    With `media_id`, a 403 re-signs once (cdn_resign)."""
    # `async def` with every blocking step in the threadpool, so a request queued for a slot holds no threadpool token.
    from urllib.parse import urlparse
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="bad scheme")
    host = (parsed.hostname or "").lower()
    if not any(host.endswith(s) for s in _ALLOWED_CDN_SUFFIXES):
        raise HTTPException(status_code=400, detail="host not allowed")

    range_hdr = request.headers.get("range") or request.headers.get("Range")

    global _img_cache_hits, _img_cache_misses
    cached = await run_in_threadpool(_serve_if_cached, u, "HIT")
    if cached is not None:
        _img_cache_hits += 1
        return cached
    _img_cache_misses += 1

    client = None
    if _DIRECT_CDN_HOST.fullmatch(host):
        http, timeout_s = _DIRECT_HTTP, DEFAULT_TIMEOUT_S
    else:
        client = await run_in_threadpool(_get_client, request)
        http, timeout_s = client.http, client.timeout_s
    resign_aid = str(getattr(client, "account_id", "") or "")

    # Forward the browser's Range so <video> can seek; without it upstream returns the whole file as 200.
    upstream_headers: dict[str, str] = {}
    if range_hdr:
        upstream_headers["Range"] = range_hdr

    held = admission.VIDEO_STREAM if range_hdr else admission.IMG_FETCH
    if not await held.enter_async(u[:80]):
        raise HTTPException(
            status_code=503,
            detail=f"too many {held.name} requests in flight; retry shortly",
        )

    # The slot is held by this frame until the StreamingResponse; a leaked slot drains the lane to zero and rejects forever, and the unwind closes the upstream response (an unclosed 403 holds its socket).
    r = None
    try:
        # Re-read inside the slot: a herd of tiles on one media all miss and queue, and would each pay an OF round-trip for bytes the first waiter wrote.
        cached = await run_in_threadpool(_serve_if_cached, u, "COLLAPSED")
        if cached is not None:
            global _img_cache_collapsed
            _img_cache_collapsed += 1
            held.exit()
            return cached
        try:
            def get(url: str) -> Any:
                return run_in_threadpool(http.get, url, timeout=timeout_s, stream=True,
                                         headers=upstream_headers or None)
            r, fetch_u = await cdn_resign.fetch(resign_aid, media_id, u, client, get, IMG_RESIGN)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"upstream fetch failed: {e}")
        if r.status_code not in (200, 206):
            raise HTTPException(status_code=r.status_code, detail="upstream non-2xx")
        clip = img_clip.small_clip(r) if range_hdr else None
        if clip is not None:
            stale, r = r, None
            resp = await run_in_threadpool(
                _cache_clip, stale, clip, u,
                lambda: http.get(fetch_u, timeout=timeout_s, stream=True))
            held.exit()
            return resp
        return _stream_upstream(
            r, u, held, range_hdr,
            account_id_hdr=request.headers.get("x-account-id") or "")
    except BaseException:
        try:
            # Default executor, NOT the anyio pool: a token-needing close while the slot is held is a deadlock cycle; closing a streamed response joins its thread, a cancelled frame cannot await.
            asyncio.get_running_loop().run_in_executor(None, _close_then_exit, r, held)
        except RuntimeError:
            _close_then_exit(r, held)
        raise


def _cache_clip(r: Any, clip: img_clip.Clip, u: str, refetch: Callable[[], Any]) -> Response:
    data, ct = img_clip.read(r, clip, refetch)
    if _img_cache_write(u, ct, data):
        hit = _serve_if_cached(u, "FILLED")
        if hit is not None:
            return hit
    return Response(data, media_type=ct, headers={"Cache-Control": _CACHE_CONTROL, "X-Img-Cache": "MISS"})


def _close_then_exit(r: Any, held: admission.Lane) -> None:
    try:
        if r is not None:
            r.close()
    except Exception:
        pass
    finally:
        held.exit()


def _serve_if_cached(u: str, label: str) -> FileResponse | None:
    hit = _img_cache_lookup(u)
    return None if hit is None else _serve_cached(hit, u, label=label)


def _serve_cached(hit: tuple[Path, str], u: str, *, label: str) -> FileResponse:
    bin_p, ct_cached = hit
    _img_cache_touch(*_img_cache_paths(_img_cache_key(u)))
    return FileResponse(
        str(bin_p),
        media_type=ct_cached,
        headers={
            "Cache-Control": _CACHE_CONTROL,
            "X-Img-Cache": label,
        },
    )


def _stream_upstream(r: Any, u: str, held: admission.Lane,
                     range_hdr: str | None, *,
                     account_id_hdr: str) -> StreamingResponse:
    ct = r.headers.get("Content-Type", "application/octet-stream")
    out_headers = {"Cache-Control": _CACHE_CONTROL}
    if account_id_hdr:
        try:
            h_stable = _img_hash_remember(account_id_hdr, u)
            out_headers["X-Img-Hash"] = h_stable
        except Exception:
            pass
    for h in ("Content-Range", "Accept-Ranges", "Content-Length", "ETag", "Last-Modified"):
        v = r.headers.get(h)
        if v:
            out_headers[h] = v
    if "Accept-Ranges" not in out_headers:
        out_headers["Accept-Ranges"] = "bytes"

    _MAX_STREAM_SEC = 60
    import time as _time
    started_mono = _time.monotonic()

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
                    break
                if chunk:
                    if local_buf is not None:
                        if len(local_buf) + len(chunk) > _IMG_CACHE_MAX_BYTES:
                            _img_cache_skipped_too_big += 1
                            local_buf = None
                        else:
                            local_buf.extend(chunk)
                    yield chunk
            else:
                completed = True
        except (ConnectionResetError, BrokenPipeError, GeneratorExit):
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
            if completed and not aborted and local_buf is not None and len(local_buf) > 0:
                try:
                    _img_cache_write(u, ct, bytes(local_buf))
                except Exception:
                    log.warning("img cache write failed (u=%s)", u[:120], exc_info=True)
            held.exit()

    return StreamingResponse(
        _safe_iter(),
        media_type=ct,
        status_code=r.status_code,
        headers=out_headers,
    )


@router.get("/img/by-hash/{h}")
async def proxy_image_by_hash(request: Request, h: str):
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
        with _img_hash_lock:
            _img_hash_map.pop(h, None)
        raise HTTPException(
            status_code=410,
            detail="signed URL expired; refetch the producing endpoint for a fresh one",
        )
    return await proxy_image(request, u=u)


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
