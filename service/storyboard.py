from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

import anyio.from_thread

import admission
import cdn_resign
from img_api import _ALLOWED_CDN_SUFFIXES, _CACHE_CONTROL, IMG_RESIGN
from relay_host import get_request_client as _get_client
from relay_host import periodic as _periodic

log = logging.getLogger("of-relay")

router = APIRouter()
stats_router = APIRouter()



_STORYBOARD_DIR = Path(os.environ.get("STORYBOARD_DIR", "/tmp/of-relay-storyboard"))
_STORYBOARD_FRAMES = 12
_STORYBOARD_WIDTH = 400
_STORYBOARD_BUILD_TIMEOUT_S = 30
_storyboard_locks: dict[str, threading.Lock] = {}
_storyboard_locks_lock = threading.Lock()
_storyboard_total_built: int = 0
_storyboard_total_served: int = 0
_storyboard_build_failures: int = 0
_storyboard_cancel_events: dict[str, threading.Event] = {}
_storyboard_cancel_events_lock = threading.Lock()
# A cancel after this fraction of bytes has landed is ignored: finish the file already paid for so the next hover is warm.
_STORYBOARD_CANCEL_KEEP_THRESHOLD = 0.80
_storyboard_total_cancelled: int = 0
_storyboard_total_cancel_ignored: int = 0


def _storyboard_register_session(session_id: str) -> threading.Event:
    with _storyboard_cancel_events_lock:
        ev = threading.Event()
        _storyboard_cancel_events[session_id] = ev
        return ev


def _storyboard_release_session(session_id: str) -> None:
    with _storyboard_cancel_events_lock:
        _storyboard_cancel_events.pop(session_id, None)


def _storyboard_signal_cancel(session_id: str) -> bool:
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
            continue
        try:
            if (_STORYBOARD_DIR / h).is_dir():
                continue
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
    await _periodic("storyboard evictor", 30 * 60, _storyboard_lock_sweep)


def _video_path_hash(u: str) -> str:
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
    media_id: int | None = None,
) -> bool:
    global _storyboard_build_failures, _storyboard_total_cancelled, _storyboard_total_cancel_ignored
    # media_id makes a 403 re-sign that media and retry once: the browser's URL may be signed for the account's old proxy IP or be expired.
    cancel_event = _storyboard_register_session(session_id) if session_id else None
    r = None
    try:
        client = _get_client(request)
        aid = str(getattr(client, "account_id", "") or "")

        def get(url: str):
            return asyncio.to_thread(client.http.get, url, timeout=client.timeout_s, stream=True)
        r, u = anyio.from_thread.run(cdn_resign.fetch, aid, media_id, u, client, get, IMG_RESIGN)
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
                    fraction = (bytes_done / total_bytes) if total_bytes > 0 else 0.0
                    if total_bytes > 0 and fraction >= _STORYBOARD_CANCEL_KEEP_THRESHOLD:
                        _storyboard_total_cancel_ignored += 1
                        cancel_event.clear()
                    else:
                        _storyboard_total_cancelled += 1
                        return False
                if chunk:
                    f.write(chunk)
                    bytes_done += len(chunk)
        return True
    except Exception:
        log.warning("storyboard download failed for %s", u[:120], exc_info=True)
        _storyboard_build_failures += 1
        try: src_path.unlink(missing_ok=True)
        except Exception: pass
        return False
    finally:
        if r is not None:
            try: r.close()
            except Exception: pass
        if session_id:
            _storyboard_release_session(session_id)


def _storyboard_probe_duration(src_path: Path) -> float:
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
    import subprocess
    # Stay 100ms before the encoded EOF: a duration rounded up would make the last seek land past EOF on short clips.
    safe_dur = max(0.1, dur - 0.1)
    args: list[str] = ["ffmpeg", "-y", "-nostdin", "-loglevel", "error"]
    for pos, i in enumerate(indices):
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
    media_id: int | None = None,
) -> bool:
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
        # Another caller may have produced the frame while we waited on the lock.
        if frame_path.is_file():
            return True

        # Build slot taken INSIDE the per-video lock: waiters on the same video would reserve a core they never use.
        if not admission.STORYBOARD_BUILD.enter(f"scrub h={h}"):
            return False
        build_slot = True

        dest.mkdir(parents=True, exist_ok=True)
        src_path = dest / "source.tmp"

        if not src_path.is_file():
            if not _storyboard_download(request, u, src_path, session_id, media_id):
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


def _check_cdn_url(u: str) -> None:
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="bad scheme")
    host = (parsed.hostname or "").lower()
    if not any(host.endswith(s) for s in _ALLOWED_CDN_SUFFIXES):
        raise HTTPException(status_code=400, detail="host not allowed")


@router.get("/img/scrub")
def proxy_image_scrub(
    request: Request,
    u: str = Query(..., description="Signed OF video URL (.mp4)"),
    i: int = Query(..., ge=0, lt=_STORYBOARD_FRAMES, description="Frame index 0..11"),
    dur: float | None = Query(None, gt=0, description="Video duration in seconds (from VaultMedia.duration). When supplied, the relay skips its own ffprobe."),
    sid: str | None = Query(None, description="Per-hover session id. The matching /img/scrub/cancel POST carries the same value; the server scopes cancellation to this session so a stale cancel from a previous hover can't abort a fresh build."),
    media_id: int | None = Query(None, description="The vault media `u` belongs to. When set, an upstream 403 (url signed for the account's old proxy IP, or expired) re-reads that media from OF and retries once with its fresh url for the same file."),
):
    """Returns the i-th frame of the 12-frame storyboard for video `u`.
    First call builds; subsequent calls serve from disk."""
    _check_cdn_url(u)

    h = _video_path_hash(u)
    ok = _ensure_storyboard_frame(request, u, h, i, hint_duration=dur, session_id=sid, media_id=media_id)
    if not ok:
        raise HTTPException(status_code=502, detail="storyboard build failed")
    frame_path = _storyboard_frame_path(h, i)
    if not frame_path.is_file():
        raise HTTPException(status_code=404, detail=f"frame {i} not extracted")

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
            "Cache-Control": _CACHE_CONTROL,
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
    _check_cdn_url(u)
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
