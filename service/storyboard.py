"""service/storyboard.py — server.py's video-scrub storyboard block, moved
wholesale: the 12-frame store (`_STORYBOARD_*`, `_video_path_hash`,
`_storyboard_all_frames_present`, `_ensure_storyboard_frame`), its build-lock /
cancel-session registry and evictor (`_storyboard_evictor_loop`, started by
server.py), and the routes `/img/scrub`, `/img/scrub/cancel`,
`/admin/storyboard/stats`. vault_frames reads the store through this module.

`_get_client` / `_periodic` are relay_host's call-time forwards, never
`from server import`. Two routers, each included mid-file in server.py at its
handlers' old spot, for route order (pinned by service/tests/test_route_order.py).

Builds take `admission.STORYBOARD_BUILD`, a process-wide lane shared with
vault_frames, which takes it for cold-clip warms.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

import admission
from img_api import _ALLOWED_CDN_SUFFIXES
from relay_host import get_request_client as _get_client
from relay_host import periodic as _periodic

log = logging.getLogger("of-relay")

router = APIRouter()        # /img/scrub, /img/scrub/cancel
stats_router = APIRouter()  # /admin/storyboard/stats


# ── Video scrub storyboard ────────────────────────────────────────────
#
# /img/scrub?u=<signed-video-url>&i=<0..11>
#
# Replaces the streaming hover-preview pipeline (two <video> elements
# pulling Range bytes through /img) with 12 pre-extracted JPGs at evenly
# spaced timestamps (every 8.33%). First request for a video triggers
# a one-time ffmpeg extraction: download the mp4, extract 12 frames,
# write to disk, drop the mp4. Subsequent requests serve directly from
# disk and are immutable cacheable.
#
# Motivation: streaming videos through /img pinned uvicorn threadpool
# slots for up to 60s each. Five users hovering through video tiles
# could deadlock the relay. Storyboard frames are ~20KB JPGs served
# from disk — never blocks the upstream pool past the one-time build.

# Configurable cache root. /tmp is fine on macOS (cleared at boot, so
# eviction handles itself). In Docker /tmp is per-container and goes
# away on restart — point STORYBOARD_DIR at a mounted volume in prod
# so storyboards survive across container restarts.
_STORYBOARD_DIR = Path(os.environ.get("STORYBOARD_DIR", "/tmp/of-relay-storyboard"))
_STORYBOARD_FRAMES = 12
_STORYBOARD_WIDTH = 400
# Drop from 90s → 30s. Past 30s Next dev's HTTP proxy and most browsers
# have already given up; holding the uvicorn worker thread any longer
# just leaks the slot for nothing. The client retries naturally on the
# next hover cycle so failing fast is cheaper than queueing zombies.
_STORYBOARD_BUILD_TIMEOUT_S = 30
_storyboard_locks: dict[str, threading.Lock] = {}
_storyboard_locks_lock = threading.Lock()
_storyboard_total_built: int = 0
_storyboard_total_served: int = 0
_storyboard_build_failures: int = 0
# Per-hover-session cancel signal. Set by POST /img/scrub/cancel when the
# user moves off a video before its download finishes. The download loop
# polls this every chunk and bails IF it hasn't already crossed the
# "almost done" threshold below — past that point we let the bytes
# finish landing so the next hover gets a warm cache.
#
# Keyed by `session_id` (client-generated UUID per hover) rather than by
# video hash on purpose: a previous fix used hash-keyed events, which let
# a late cancel POST from a prior hover abort a brand-new build for the
# same video (re-hover within ~100-300ms). With session-keyed events,
# the new hover gets a new id → fresh event → the stale cancel POST
# finds no entry and is a no-op.
_storyboard_cancel_events: dict[str, threading.Event] = {}
_storyboard_cancel_events_lock = threading.Lock()
# If the cancel arrives after this fraction of the bytes has landed,
# we finish the download anyway — the remaining bandwidth is cheap and
# the cached storyboard will be there next time the user hovers this
# video. Lower = more cache built (more wasted bytes on truly-abandoned
# videos); higher = less wasted bandwidth (more re-download next time).
# 0.80 was the user's call after measuring the tradeoff.
_STORYBOARD_CANCEL_KEEP_THRESHOLD = 0.80
_storyboard_total_cancelled: int = 0
_storyboard_total_cancel_ignored: int = 0


def _storyboard_register_session(session_id: str) -> threading.Event:
    """Reserve a cancel event for an active build's session. Called once
    at the start of a download; the event is dropped at end of build."""
    with _storyboard_cancel_events_lock:
        ev = threading.Event()
        _storyboard_cancel_events[session_id] = ev
        return ev


def _storyboard_release_session(session_id: str) -> None:
    """Drop the session's cancel event after the build finishes (success
    or failure). Late cancel POSTs that arrive after this find no entry
    and become a no-op, which is the desired behaviour."""
    with _storyboard_cancel_events_lock:
        _storyboard_cancel_events.pop(session_id, None)


def _storyboard_signal_cancel(session_id: str) -> bool:
    """Set the cancel event for `session_id` if a build is active. Returns
    True when a live session was found, False otherwise (stale cancel)."""
    with _storyboard_cancel_events_lock:
        ev = _storyboard_cancel_events.get(session_id)
    if ev is None:
        return False
    ev.set()
    return True


def _storyboard_lock_for(h: str) -> threading.Lock:
    with _storyboard_locks_lock:
        lk = _storyboard_locks.get(h)
        if lk is None:
            lk = threading.Lock()
            _storyboard_locks[h] = lk
        return lk


def _storyboard_evict_locks_once() -> int:
    """Drop `_storyboard_locks` entries for hashes whose on-disk
    storyboard dir is gone — the prune-storyboards cron deletes those
    dirs on TTL, but the in-memory lock dict would otherwise grow
    without bound (≈200 bytes per unique video ever hovered).

    Safety: we only evict a lock when (a) the dir is missing AND (b)
    `lock.acquire(blocking=False)` succeeds, meaning no thread is
    currently building. We then re-check the dir under the lock and
    only pop from the dict if the same lock instance is still mapped.
    Returns the number of entries evicted (for the periodic logger)."""
    existing: set[str] = set()
    try:
        if _STORYBOARD_DIR.exists():
            existing = {p.name for p in _STORYBOARD_DIR.iterdir() if p.is_dir()}
    except OSError:
        return 0
    with _storyboard_locks_lock:
        candidates = [h for h in _storyboard_locks.keys() if h not in existing]
    evicted = 0
    for h in candidates:
        with _storyboard_locks_lock:
            lk = _storyboard_locks.get(h)
        if lk is None:
            continue
        if not lk.acquire(blocking=False):
            continue  # active build → leave it alone
        try:
            if (_STORYBOARD_DIR / h).is_dir():
                continue  # someone resurrected it between our snapshot and now
            with _storyboard_locks_lock:
                if _storyboard_locks.get(h) is lk:
                    _storyboard_locks.pop(h, None)
                    evicted += 1
        finally:
            lk.release()
    return evicted


async def _storyboard_lock_sweep() -> None:
    evicted = await asyncio.to_thread(_storyboard_evict_locks_once)
    if evicted:
        log.info("storyboard locks evicted: %d", evicted)


async def _storyboard_evictor_loop() -> None:
    """Background task spawned at startup. Runs the lock evictor every
    30 minutes — matches the cadence of the prune-storyboards cron so
    the in-memory dict catches up shortly after the disk cleanup."""
    await _periodic("storyboard evictor", 30 * 60, _storyboard_lock_sweep)


def _video_path_hash(u: str) -> str:
    """SHA-1 of host+path (signature stripped, account-agnostic). Same
    physical video → same hash → same on-disk frames, regardless of
    which account fetched it or how OF signed the URL today."""
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(u)
    base = (parsed.hostname or "").lower() + (parsed.path or "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


_ALL_FRAME_INDICES = tuple(range(_STORYBOARD_FRAMES))


def _storyboard_frame_path(h: str, i: int) -> Path:
    return _STORYBOARD_DIR / h / f"{i}.jpg"


def _storyboard_all_frames_present(h: str) -> bool:
    return all(_storyboard_frame_path(h, i).is_file() for i in _ALL_FRAME_INDICES)


def _storyboard_download(
    request: Request, u: str, src_path: Path, session_id: str | None,
) -> bool:
    """Pull the mp4 into src_path via the right account's HTTP client (so
    the URL's source-IP signature matches). Returns False on failure or
    when the client cancelled before 90% of the bytes had landed.

    The cancel hook lets us bail mid-download when the user moves on to
    another video. Past `_STORYBOARD_CANCEL_KEEP_THRESHOLD` we ignore
    the cancel and finish the bytes anyway — the next hover gets a
    warm cache and the bandwidth we already burned isn't wasted.

    `session_id` scopes the cancel to one hover session. If empty/None
    (old client, no sid supplied), the build runs without cancellation
    support — a missed cancel is strictly better than the alternative,
    which was aborting unrelated builds."""
    global _storyboard_build_failures, _storyboard_total_cancelled, _storyboard_total_cancel_ignored
    # Fresh, session-scoped event. Drop it on exit (finally) so a late
    # cancel POST arriving after the build wraps up is a no-op — not a
    # poison flag for the next session that happens to reuse this id.
    cancel_event = _storyboard_register_session(session_id) if session_id else None
    try:
        client = _get_client(request)
        r = client.http.get(u, timeout=client.timeout_s, stream=True)
        if r.status_code not in (200, 206):
            log.warning("storyboard download non-2xx %d for %s", r.status_code, u[:120])
            _storyboard_build_failures += 1
            return False
        total_bytes = 0
        try:
            total_bytes = int(r.headers.get("content-length") or 0)
        except (TypeError, ValueError):
            total_bytes = 0
        bytes_done = 0
        with src_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if cancel_event is not None and cancel_event.is_set():
                    # Past the keep threshold? Honour the bytes we already
                    # paid for and finish the file — bumping the ignored
                    # counter so we can see the cap is working.
                    fraction = (bytes_done / total_bytes) if total_bytes > 0 else 0.0
                    if total_bytes > 0 and fraction >= _STORYBOARD_CANCEL_KEEP_THRESHOLD:
                        _storyboard_total_cancel_ignored += 1
                        cancel_event.clear()  # treat the rest of the dl as committed
                    else:
                        # Truly abort — drop the partial mp4, signal failure.
                        _storyboard_total_cancelled += 1
                        try: r.close()
                        except Exception: pass
                        return False
                if chunk:
                    f.write(chunk)
                    bytes_done += len(chunk)
        try: r.close()
        except Exception: pass
        return True
    except Exception:
        log.warning("storyboard download failed for %s", u[:120], exc_info=True)
        _storyboard_build_failures += 1
        try: src_path.unlink(missing_ok=True)
        except Exception: pass
        return False
    finally:
        if session_id:
            _storyboard_release_session(session_id)


def _storyboard_probe_duration(src_path: Path) -> float:
    """ffprobe → duration in seconds, 0 on failure."""
    import subprocess
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(src_path)],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return float(probe.stdout.strip())
    except Exception:
        return 0.0


def _storyboard_extract_batch(
    src_path: Path, dest: Path, indices: tuple[int, ...], dur: float,
) -> bool:
    """Extract all `indices` frames in a SINGLE ffmpeg invocation, using
    repeated `-ss TIME -i SRC -frames:v 1 OUT` blocks. ffmpeg reopens the
    file per `-i` (keyframe seek is fast on local disk) but the process
    spawn happens only once per batch — cuts pass-1 latency by ~4x for a
    4-frame batch vs. one subprocess per frame. Frames write directly to
    their final 0-based name.

    Tolerates partial success: if ffmpeg returns non-zero (common when
    the final frame's seek lands at/past EOF on short clips with
    rounded-up duration metadata) but at least one jpg landed on disk,
    we treat the batch as good. Returns False only if zero frames came
    out — that's the case where the source mp4 is unreadable or the
    timeout fired."""
    import subprocess
    # Stay at least 100ms before the encoded EOF — ffmpeg can't seek past
    # the last decodable frame, and short clips whose container metadata
    # rounds the duration up (e.g. "4.0s" for a 3.93s file) would otherwise
    # blow up on the last index.
    safe_dur = max(0.1, dur - 0.1)
    args: list[str] = ["ffmpeg", "-y", "-nostdin", "-loglevel", "error"]
    for pos, i in enumerate(indices):
        # Mid-segment seek (i + 0.5) lands away from cut boundaries where
        # an I-frame might be black or a hard transition.
        ts = (i + 0.5) * dur / _STORYBOARD_FRAMES
        ts = min(ts, safe_dur)
        out_path = dest / f"{i}.jpg"
        args += [
            "-ss", f"{ts:.4f}", "-i", str(src_path),
            "-map", f"{pos}:v:0",
            "-frames:v", "1",
            "-vf", f"scale={_STORYBOARD_WIDTH}:-2",
            "-q:v", "5",
            str(out_path),
        ]
    rc = -1
    try:
        proc = subprocess.run(
            args, check=False, capture_output=True,
            timeout=_STORYBOARD_BUILD_TIMEOUT_S,
        )
        rc = proc.returncode
    except Exception:
        log.warning(
            "storyboard batch extract crashed for %s indices=%s",
            dest.name, indices, exc_info=True,
        )

    landed = [i for i in indices if (dest / f"{i}.jpg").is_file()]
    if not landed:
        log.warning(
            "storyboard batch extract produced no frames for %s "
            "(rc=%s indices=%s dur=%.3f)",
            dest.name, rc, indices, dur,
        )
        return False
    if len(landed) < len(indices):
        # Backfill missing indices by copying the nearest neighbour so the
        # storyboard is always complete-shaped after a build. Without this
        # any missing frame would trigger a fresh download+extract on the
        # next request and fail the same way — an infinite loop.
        import shutil
        for i in indices:
            if (dest / f"{i}.jpg").is_file():
                continue
            nearest = min(landed, key=lambda j: abs(j - i))
            try:
                shutil.copyfile(dest / f"{nearest}.jpg", dest / f"{i}.jpg")
            except Exception:
                log.warning(
                    "storyboard backfill copy %s→%s failed for %s",
                    nearest, i, dest.name, exc_info=True,
                )
        log.info(
            "storyboard partial extract for %s: %d/%d frames (rc=%s dur=%.3f, backfilled rest)",
            dest.name, len(landed), len(indices), rc, dur,
        )
    return True


def _ensure_storyboard_frame(
    request: Request, u: str, h: str, i: int,
    *, hint_duration: float | None = None,
    session_id: str | None = None,
) -> bool:
    """Make sure frame `i` is on disk. Returns True if it is now.

    Single-pass build: any caller that finds the storyboard missing
    downloads the source mp4 and extracts all 12 frames in one batched
    ffmpeg invocation. We tried a two-phase (4-then-8) split but the
    measured breakdown showed ffmpeg is ~230ms total vs ~3-7s for the
    download — splitting saved nothing meaningful and added background-
    thread coordination.

    `hint_duration` (seconds) lets the caller skip ffprobe entirely —
    VaultMedia carries duration in the vault listing so the client
    passes it through. The worst case if it's wrong is mis-spaced
    scrub frames; we sanity-check it's positive."""
    global _storyboard_total_built, _storyboard_build_failures
    dest = _STORYBOARD_DIR / h
    frame_path = _storyboard_frame_path(h, i)

    if frame_path.is_file():
        return True

    lock = _storyboard_lock_for(h)
    if not lock.acquire(timeout=_STORYBOARD_BUILD_TIMEOUT_S):
        return False
    build_slot = False
    try:
        # Another concurrent caller may have produced our frame while we
        # waited on the lock.
        if frame_path.is_file():
            return True

        # Global build slot. Taken INSIDE the per-video lock deliberately:
        # everyone queued on that lock is waiting on a build of the SAME video
        # already under way, and a waiter holding a build slot would be
        # reserving a core it will never use. The lock stops duplicate work;
        # the lane stops N DISTINCT videos putting N ffmpeg processes on a
        # 2-core box.
        if not admission.STORYBOARD_BUILD.enter(f"scrub h={h}"):
            return False
        build_slot = True

        dest.mkdir(parents=True, exist_ok=True)
        src_path = dest / "source.tmp"

        # Download mp4 (skipped if a prior failed build left it around).
        if not src_path.is_file():
            if not _storyboard_download(request, u, src_path, session_id):
                # On cancel/error, drop the partial bytes — incomplete
                # mp4s aren't useful for extraction.
                try: src_path.unlink(missing_ok=True)
                except Exception: pass
                return False

        if hint_duration and hint_duration > 0:
            dur = hint_duration
        else:
            dur = _storyboard_probe_duration(src_path)
        if dur <= 0:
            _storyboard_build_failures += 1
            try: src_path.unlink(missing_ok=True)
            except Exception: pass
            return False

        if not _storyboard_extract_batch(src_path, dest, _ALL_FRAME_INDICES, dur):
            _storyboard_build_failures += 1
            # Drop the source mp4 on extract failure. The previous code
            # kept it around so a follow-up call could skip the download
            # and re-attempt extraction, but if the file is the cause of
            # the failure (corrupt download, codec ffmpeg can't decode)
            # leaving it on disk pins us into an infinite-retry loop on
            # this video — every subsequent hover hits the same broken
            # mp4 and fails the same way. Re-downloading is cheap
            # relative to a permanently-broken cache entry.
            try: src_path.unlink(missing_ok=True)
            except Exception: pass
            return False

        try: src_path.unlink(missing_ok=True)
        except Exception: pass
        _storyboard_total_built += 1
        return frame_path.is_file()
    finally:
        if build_slot:
            admission.STORYBOARD_BUILD.exit()
        lock.release()


@router.get("/img/scrub")
def proxy_image_scrub(
    request: Request,
    u: str = Query(..., description="Signed OF video URL (.mp4)"),
    i: int = Query(..., ge=0, lt=_STORYBOARD_FRAMES, description="Frame index 0..11"),
    dur: float | None = Query(None, gt=0, description="Video duration in seconds (from VaultMedia.duration). When supplied, the relay skips its own ffprobe."),
    sid: str | None = Query(None, description="Per-hover session id. The matching /img/scrub/cancel POST carries the same value; the server scopes cancellation to this session so a stale cancel from a previous hover can't abort a fresh build."),
):
    """Returns the i-th frame of the 12-frame storyboard for video `u`.
    First call builds; subsequent calls serve from disk."""
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="bad scheme")
    host = (parsed.hostname or "").lower()
    if not any(host.endswith(s) for s in _ALLOWED_CDN_SUFFIXES):
        raise HTTPException(status_code=400, detail="host not allowed")

    h = _video_path_hash(u)
    ok = _ensure_storyboard_frame(request, u, h, i, hint_duration=dur, session_id=sid)
    if not ok:
        raise HTTPException(status_code=502, detail="storyboard build failed")
    frame_path = _storyboard_frame_path(h, i)
    if not frame_path.is_file():
        raise HTTPException(status_code=404, detail=f"frame {i} not extracted")

    # Bump the dir's mtime so the prune script's find -mtime treats this
    # as "last used now". Cheap (one syscall) — does NOT touch each frame
    # file, just the parent dir, which is all the prune script looks at.
    try:
        os.utime(_STORYBOARD_DIR / h, None)
    except OSError:
        pass

    global _storyboard_total_served
    _storyboard_total_served += 1
    return FileResponse(
        frame_path,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=604800, immutable",
            "X-Img-Hash": h,
        },
    )


@router.post("/img/scrub/cancel")
def cancel_storyboard_build(
    u: str = Query(..., description="Signed OF video URL whose in-flight storyboard build should be cancelled"),
    sid: str | None = Query(None, description="Per-hover session id from the matching /img/scrub request. Cancellation is scoped to this session — a missing or unknown sid is a no-op (intentional: stale cancels from a previous hover must not abort fresh builds for the same video)."),
):
    """Signal the in-flight download for hover session `sid` to abort,
    unless it's already past `_STORYBOARD_CANCEL_KEEP_THRESHOLD` (in
    which case we let it finish so the bytes aren't wasted). Idempotent —
    calling with a sid that has no in-flight build is a no-op.

    `u` is still validated for hygiene but isn't used to route the cancel
    anymore — that would re-introduce the hash-keyed race where a late
    POST from a stale hover aborted a fresh hover of the same video.

    Browser fires this on hover end (useEffect cleanup in VaultPicker).
    Fire-and-forget; the browser doesn't wait for or read the response."""
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="bad scheme")
    host = (parsed.hostname or "").lower()
    if not any(host.endswith(s) for s in _ALLOWED_CDN_SUFFIXES):
        raise HTTPException(status_code=400, detail="host not allowed")
    if not sid:
        return {"ok": True, "ignored": "no-sid"}
    found = _storyboard_signal_cancel(sid)
    return {"ok": True, "found": found}


@stats_router.get("/admin/storyboard/stats")
def admin_storyboard_stats() -> dict:
    """How the scrub-frame storyboard cache is doing."""
    try:
        n_videos = sum(1 for p in _STORYBOARD_DIR.iterdir() if p.is_dir()) if _STORYBOARD_DIR.exists() else 0
    except Exception:
        n_videos = 0
    return {
        "cached_videos": n_videos,
        "frames_per_video": _STORYBOARD_FRAMES,
        "total_built": _storyboard_total_built,
        "total_served": _storyboard_total_served,
        "build_failures": _storyboard_build_failures,
        "total_cancelled": _storyboard_total_cancelled,
        "total_cancel_ignored": _storyboard_total_cancel_ignored,
        "cancel_keep_threshold": _STORYBOARD_CANCEL_KEEP_THRESHOLD,
    }
