from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import logging
from typing import Any, NamedTuple

import admission
import storyboard
import automation_executor as ax
import vault_mirror
import vault_stills
import vision
from db.models import VaultItem
from of_shapes import still_url

log = logging.getLogger("of-relay.vault_frames")

# no_variant: OF's payload has nothing renderable, cool off. fetch_failed: bytes that should exist could not be read, retry at once. A fetch failure stamped blocked_drm would freeze the item for the DRM cooldown.
NO_IMAGE_STATUS = {"no_variant": "blocked_drm", "fetch_failed": "fetch_failed",
                    "gone": "gone"}

DESCRIBE_FRAMES = 9



def describe_image_of(files: dict | None) -> str | None:
    return still_url({"files": files}) if isinstance(files, dict) else None


def video_url(m: dict) -> str | None:
    vs = m.get("videoSources")
    if isinstance(vs, dict):
        for k in ("240", "720"):
            if vs.get(k):
                return vs[k]
    files = m.get("files")
    full = files.get("full") if isinstance(files, dict) else None
    if isinstance(full, dict) and full.get("url"):
        return full["url"]
    return None


def poster_frames(raw: dict) -> list[str]:
    files = raw.get("files") or {}
    prev = files.get("preview") or {}
    out = [o.get("url") for o in (prev.get("options") or []) if isinstance(o, dict) and o.get("url")]
    if not out:
        one = vault_mirror.thumb_of(files)
        if one:
            out = [one]
    return out


def preview_count(raw: dict) -> int:
    prev = (raw.get("files") or {}).get("preview") or {}
    return sum(1 for o in (prev.get("options") or []) if isinstance(o, dict) and o.get("url"))


PREVIEW_MIN = 3


def previews_enough(raw: dict, dur: float) -> bool:
    n = preview_count(raw)
    return n >= PREVIEW_MIN or (n >= 1 and 0 < dur <= PREVIEW_MIN)



def pick_thumb(m: dict) -> str | None:
    return vault_mirror.thumb_of(m.get("files") if isinstance(m.get("files"), dict) else {})


def pick_image(m: dict) -> str | None:
    return describe_image_of(m.get("files") if isinstance(m.get("files"), dict) else {})


def pick_poster(i: int) -> vault_stills.Pick:
    def pick(m: dict) -> str | None:
        frames = poster_frames(m)
        return frames[i] if i < len(frames) else None
    return pick



def warm_one_sync(client: Any, url: str, dur: float) -> str:
    h = storyboard._video_path_hash(url)
    if storyboard._storyboard_all_frames_present(h):
        return "cached"

    if not admission.STORYBOARD_BUILD.enter(f"warm h={h}"):
        return "busy"
    dest = storyboard._STORYBOARD_DIR / h
    src_path = dest / "source.tmp"
    r = None
    try:
        dest.mkdir(parents=True, exist_ok=True)
        r = client.http.get(url, timeout=client.timeout_s, stream=True)
        if r.status_code not in (200, 206):
            return "dl_fail"
        with src_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if chunk:
                    f.write(chunk)
        ok = storyboard._storyboard_extract_batch(
            src_path, dest, storyboard._ALL_FRAME_INDICES, max(0.1, dur or 1.0)
        )
        return "warmed" if ok else "extract_fail"
    except Exception:  # noqa: BLE001
        log.warning("warm storyboard failed url=%s", url[:100], exc_info=True)
        return "error"
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:  # noqa: BLE001
                log.warning("storyboard response close failed", exc_info=True)
        try:
            src_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        admission.STORYBOARD_BUILD.exit()


def spread(n_have: int, want: int) -> list[int]:
    if want >= n_have:
        return list(range(n_have))
    if want <= 1:
        return [n_have // 2]
    step = (n_have - 1) / (want - 1)
    return sorted({int(round(i * step)) for i in range(want)})


def storyboard_frames(url: str | None, want: int) -> list[str]:
    if not url:
        return []
    h = storyboard._video_path_hash(url)
    if not storyboard._storyboard_all_frames_present(h):
        return []
    out: list[str] = []
    for i in spread(storyboard._STORYBOARD_FRAMES, want):
        p = storyboard._storyboard_frame_path(h, i)
        if p.is_file():
            out.append(vision.img_data_url(p.read_bytes()))
    return out



class Collected(NamedTuple):

    images: list[str]
    reason: str
    detail: str = ""


# Warm outcomes not named here must be listed, or the item inherits the 7-day DRM cooldown meant for clips OF cannot render (it froze a whole vault).
_WARM_REASON = {"dl_fail": "fetch_failed", "error": "fetch_failed",
                "busy": "fetch_failed"}


async def _poster_stills(account_id: str, media_id: int, media: dict,
                         want: int, warm: str) -> Collected:
    frames: list[str] = []
    transient = False
    stills = await asyncio.gather(*(
        vault_stills.bytes_for(account_id, media_id, vault_stills.poster_path(account_id, media_id, i),
                               pick_poster(i))
        for i in spread(len(poster_frames(media)), want)))
    for still in stills:
        if still.data is not None:
            frames.append(vision.img_data_url(still.data))
        elif still.reason == "gone":
            return Collected([], "gone")
        elif still.reason == "fetch_failed":
            transient = True
    if frames:
        return Collected(frames, "ok")
    if transient:
        return Collected([], "fetch_failed")
    return Collected([], _WARM_REASON.get(warm, "no_variant"))


async def _collect_video(account_id: str, media_id: int, raw: dict,
                         client: Any, want: int) -> Collected:
    frames = storyboard_frames(video_url(raw), want)
    if frames:
        return Collected(frames, "ok")
    if previews_enough(raw, float(raw.get("duration") or 0)):
        on_disk = [b for i in spread(len(poster_frames(raw)), want)
                   for p in (vault_stills.poster_path(account_id, media_id, i),) if p.is_file()
                   for b in (p.read_bytes(),)]
        if len(on_disk) >= min(PREVIEW_MIN, want, preview_count(raw)):
            return Collected([vision.img_data_url(b) for b in on_disk], "ok")

    fresh = await vault_stills.resolve_fresh(account_id, media_id, client)
    if fresh.media is None:
        return Collected([], fresh.reason)
    media = fresh.media
    dur = float(media.get("duration") or raw.get("duration") or 0)
    if previews_enough(media, dur):
        got = await _poster_stills(account_id, media_id, media, want, "")
        if len(got.images) >= min(PREVIEW_MIN, want, preview_count(media)):
            return got

    warm = ""
    fresh_url = video_url(media)
    if fresh_url:
        warm = await asyncio.to_thread(
            warm_one_sync, client, fresh_url,
            dur)
        frames = storyboard_frames(fresh_url, want)
        if frames:
            return Collected(frames, "ok")

    return await _poster_stills(account_id, media_id, media, want, warm)


# Generous (a long clip is minutes of honest work) but bounds a fetch that never returns; a timeout reads as fetch_failed so the next sweep retries.
COLLECT_TIMEOUT_S = 180


async def collect(account_id: str, item: VaultItem, raw: dict,
                  want: int = DESCRIBE_FRAMES) -> Collected:
    try:
        return await asyncio.wait_for(
            _collect(account_id, item, raw, want), timeout=COLLECT_TIMEOUT_S)
    except asyncio.TimeoutError:
        log.warning("collect timed out after %ss account=%s media=%s kind=%s",
                    COLLECT_TIMEOUT_S, account_id, item.media_id, item.kind)
        return Collected([], "fetch_failed",
                         f"gave up reading the media after {COLLECT_TIMEOUT_S}s")
    except Exception as e:  # noqa: BLE001
        log.exception("collect failed account=%s media=%s kind=%s",
                      account_id, item.media_id, item.kind)
        return Collected([], "fetch_failed", f"{type(e).__name__}: {e}"[:200])



# A clip with OF's preview set is read off previews (no mp4 download, no ffmpeg); only a clip without previews takes the capped 240p mp4, marked `review`, never a free lane.
JEV_VIDEO_FRAMES = storyboard._STORYBOARD_FRAMES
JEV_VIDEO_MIN_SHORT_PX = 480
_JEV_VIDEO_CAP_DEFAULT = 50_000_000
_JEV_PREVIEW_LONG_DEFAULT = 120.0


def _env_preview_long_s() -> float:
    import os
    try:
        v = float(os.environ.get("JEV_PREVIEW_LONG_S") or 0)
    except ValueError:
        v = 0.0
    return v if v > 0 else _JEV_PREVIEW_LONG_DEFAULT


def _env_cap_bytes() -> int:
    # Over 50 MB an mp4 is proxy traffic: probed, 11 of 27 720p mp4s exceeded it (max 1.08 GB).
    import os
    try:
        v = int(os.environ.get("JEV_VIDEO_CAP_BYTES") or 0)
    except ValueError:
        v = 0
    return v if v > 0 else _JEV_VIDEO_CAP_DEFAULT


def _budget_s(cap: int) -> int:
    return min(900, 190 + cap // 1_000_000)


JEV_VIDEO_CAP_BYTES = _env_cap_bytes()
JEV_VIDEO_TIMEOUT_S = _budget_s(JEV_VIDEO_CAP_BYTES)
_JEV_FFMPEG_TIMEOUT_S = 90
_JEV_DL_RESERVE_S = 30


class JevFrames(NamedTuple):

    frames: list[bytes]
    reason: str
    detail: str = ""
    src: str = ""
    review: str | None = None
    nbytes: int = 0
    transient: bool = False


def _download_capped(client: Any, url: str, path: Any, deadline: float) -> tuple[str, int]:
    import time
    r = client.http.get(url, timeout=client.timeout_s, stream=True)
    try:
        if r.status_code not in (200, 206):
            return "dl_fail", 0
        try:
            cl = int(r.headers.get("content-length") or 0)
        except (TypeError, ValueError):
            cl = 0
        if cl > JEV_VIDEO_CAP_BYTES:
            return "over_cap", cl
        n = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                n += len(chunk)
                if n > JEV_VIDEO_CAP_BYTES:
                    return "over_cap", n
                if time.monotonic() > deadline:
                    return "dl_fail", n
                f.write(chunk)
        return "ok", n
    finally:
        try:
            r.close()
        except Exception:  # noqa: BLE001
            pass


def _ffmpeg_timeout(deadline: float) -> float:
    import time
    return max(1.0, min(_JEV_FFMPEG_TIMEOUT_S, deadline - time.monotonic()))


def _extract_jev(src: Any, dur: float, out: Any, scrub: Any | None, deadline: float) -> list[bytes]:
    import subprocess
    safe = max(0.1, dur - 0.1)
    args = ["ffmpeg", "-y", "-nostdin", "-loglevel", "error"]
    for i in range(JEV_VIDEO_FRAMES):
        ts = min((i + 0.5) * dur / JEV_VIDEO_FRAMES, safe)
        args += ["-ss", f"{ts:.4f}", "-i", str(src),
                 "-map", f"{i}:v:0", "-frames:v", "1", "-q:v", "2", str(out / f"{i}.jpg")]
        if scrub is not None:
            args += ["-map", f"{i}:v:0", "-frames:v", "1", "-vf", f"scale={storyboard._STORYBOARD_WIDTH}:-2",
                     "-q:v", "5", str(scrub / f"{i}.jpg")]
    try:
        subprocess.run(args, check=False, capture_output=True, timeout=_ffmpeg_timeout(deadline))
    except Exception:  # noqa: BLE001 — timeout, no ffmpeg: whatever landed is the answer
        log.warning("jev video ffmpeg failed src=%s", src, exc_info=True)
    return [(out / f"{i}.jpg").read_bytes() for i in range(JEV_VIDEO_FRAMES) if (out / f"{i}.jpg").is_file()]


def _publish_scrub(tmp: Any, h: str) -> None:
    import os
    import shutil
    have = [i for i in range(JEV_VIDEO_FRAMES) if (tmp / f"{i}.jpg").is_file()]
    if not have:
        return
    dest = storyboard._STORYBOARD_DIR / h
    dest.mkdir(parents=True, exist_ok=True)
    for i in range(JEV_VIDEO_FRAMES):
        if i not in have:
            shutil.copyfile(tmp / f"{min(have, key=lambda j: abs(j - i))}.jpg", tmp / f"{i}.jpg")
    for i in range(JEV_VIDEO_FRAMES):
        part = dest / f".{i}.jpg.{os.getpid()}.part"
        try:
            shutil.copyfile(tmp / f"{i}.jpg", part)
            os.replace(part, dest / f"{i}.jpg")
        except BaseException:
            part.unlink(missing_ok=True)
            raise


def _short_side(jpeg: bytes) -> int:
    import io
    from PIL import Image
    try:
        with Image.open(io.BytesIO(jpeg)) as im:
            return min(im.size)
    except Exception:  # noqa: BLE001
        return 0


def _jev_frames_sync(client: Any, media: dict, dur: float, deadline: float) -> JevFrames | None:
    import shutil
    import tempfile
    import time
    from pathlib import Path
    vs = media.get("videoSources") if isinstance(media.get("videoSources"), dict) else {}
    files = media.get("files") if isinstance(media.get("files"), dict) else {}
    full = (files.get("full") or {}).get("url") if isinstance(files.get("full"), dict) else None
    no720 = not vs.get("720")
    order = (("full", full), ("240", vs.get("240"))) if no720 else \
        (("720", vs.get("720")), ("240", vs.get("240")), ("full", full))
    cands = [(k, u) for k, u in order if u]
    review = None
    scrub_url = video_url(media)
    h = storyboard._video_path_hash(scrub_url) if scrub_url else None
    best: tuple[list[bytes], str, int] | None = None
    fails: list[str] = []
    with tempfile.TemporaryDirectory(prefix="jev-video-") as td:
        tmp = Path(td)
        for label, url in cands:
            if time.monotonic() > deadline - _JEV_DL_RESERVE_S:
                fails.append(f"out of time before the {label} mp4")
                break
            for p in ("out", "scrub"):
                shutil.rmtree(tmp / p, ignore_errors=True)
            try:
                got, n = _download_capped(client, url, tmp / "src.mp4", deadline - _JEV_DL_RESERVE_S)
            except Exception:  # noqa: BLE001 — the connection, not the clip: try the next source
                log.warning("jev video download raised src=%s", label, exc_info=True)
                got, n = "dl_fail", 0
            if got == "over_cap":
                review = review or "over_cap"
                continue
            name = label if label == "full" else f"{label}p"
            if got != "ok":
                fails.append(f"{name} download failed")
                continue
            lock = None
            if h and not storyboard._storyboard_all_frames_present(h):
                lock = storyboard._storyboard_lock_for(h)
                if not lock.acquire(blocking=False):
                    lock = None
            try:
                (tmp / "out").mkdir()
                if lock is not None:
                    (tmp / "scrub").mkdir()
                # Seek by the file's own length, not OF's whole-second `duration`: seeks past the real end land no frame (9/12 on 2-3 s clips).
                d = storyboard._storyboard_probe_duration(tmp / "src.mp4") or dur
                frames = _extract_jev(tmp / "src.mp4", max(0.1, d or 1.0), tmp / "out",
                                      tmp / "scrub" if lock is not None else None, deadline)
                if lock is not None:
                    try:
                        _publish_scrub(tmp / "scrub", h)
                    except Exception:  # noqa: BLE001
                        log.warning("jev video scrub publish failed hash=%s", h, exc_info=True)
            finally:
                if lock is not None:
                    lock.release()
            if len(frames) < JEV_VIDEO_FRAMES:
                fails.append(f"ffmpeg read {len(frames)}/{JEV_VIDEO_FRAMES} frames from the {name} mp4")
                if frames and (best is None or len(frames) > len(best[0])):
                    best = (frames, label, n)
                continue
            if no720 and (label != "full" or _short_side(frames[0]) < JEV_VIDEO_MIN_SHORT_PX):
                review = "no_720"
            elif fails:
                review = review or "src_failed"
            return JevFrames(frames, "ok", src=label, review=review, nbytes=n, transient=bool(fails))
    if best is not None:
        return JevFrames(best[0], "ok", src=best[1], review="few_frames", nbytes=best[2], transient=True)
    return JevFrames([], "fetch_failed", "; ".join(fails)[:200], transient=True) if fails else None


_LANE_TICKET: contextvars.ContextVar[list[bool] | None] = contextvars.ContextVar("jev_lane_ticket", default=None)


@contextlib.asynccontextmanager
async def lane_ahead(label: str):
    await admission.JEV_VIDEO.enter_async(label, forever=True)
    ticket = [False]
    tok = _LANE_TICKET.set(ticket)
    try:
        yield
    finally:
        _LANE_TICKET.reset(tok)
        if not ticket[0]:
            admission.JEV_VIDEO.exit()


def _claim_lane() -> bool:
    t = _LANE_TICKET.get()
    if t is None or t[0]:
        return False
    t[0] = True
    return True


def drop_lane() -> None:
    if _claim_lane():
        admission.JEV_VIDEO.exit()


async def _collect_jev_video(account_id: str, item: VaultItem, deadline: float) -> JevFrames:
    import time

    def left() -> float:
        return max(0.0, deadline - time.monotonic())
    client = await asyncio.to_thread(ax._make_client, account_id)
    fresh = await asyncio.wait_for(vault_stills.resolve_fresh(account_id, item.media_id, client), left())
    if fresh.media is None:
        return JevFrames([], fresh.reason, transient=fresh.reason == "fetch_failed")
    media = fresh.media
    dur = float(media.get("duration") or item.duration_seconds or 0)
    if previews_enough(media, dur):
        pv = await asyncio.wait_for(_poster_stills(account_id, item.media_id, media, JEV_VIDEO_FRAMES, ""), left())
        if len(pv.images) >= min(PREVIEW_MIN, preview_count(media)):
            short = len(pv.images) < min(JEV_VIDEO_FRAMES, preview_count(media))
            drop_lane()
            review = "long" if dur <= 0 or dur > _env_preview_long_s() else "few_frames" if short else None
            return JevFrames([base64.b64decode(u.split(",", 1)[1]) for u in pv.images], "ok", src="preview",
                             review=review, transient=short)
    if video_url(media):
        if not _claim_lane() and not await admission.JEV_VIDEO.enter_async(f"jev video media={item.media_id}"):
            return JevFrames([], "fetch_failed", "jev_video lane full — retried next sweep")

        async def held() -> JevFrames | None:
            try:
                return await asyncio.to_thread(_jev_frames_sync, client, media, dur, deadline)
            finally:
                admission.JEV_VIDEO.exit()
        got = await asyncio.shield(asyncio.ensure_future(held()))
        if got is not None and got.frames:
            return got
    else:
        got = None
    posters = await asyncio.wait_for(
        _poster_stills(account_id, item.media_id, media, JEV_VIDEO_FRAMES, ""), left())
    if not posters.images:
        return got if got is not None else JevFrames([], posters.reason, posters.detail,
                                                     transient=posters.reason == "fetch_failed")
    return JevFrames([base64.b64decode(u.split(",", 1)[1]) for u in posters.images], "ok", src="poster",
                     review="poster_only", transient=got is not None)


async def collect_jev_video(account_id: str, item: VaultItem) -> JevFrames:
    import time
    try:
        return await _collect_jev_video(account_id, item, time.monotonic() + JEV_VIDEO_TIMEOUT_S)
    except asyncio.TimeoutError:
        log.warning("collect_jev_video timed out after %ss account=%s media=%s",
                    JEV_VIDEO_TIMEOUT_S, account_id, item.media_id)
        return JevFrames([], "fetch_failed", f"gave up reading the clip after {JEV_VIDEO_TIMEOUT_S}s", transient=True)
    except Exception as e:  # noqa: BLE001 — counted toward the retry cap (`vault_jev_pass`), never re-downloaded forever
        log.exception("collect_jev_video failed account=%s media=%s", account_id, item.media_id)
        return JevFrames([], "fetch_failed", f"{type(e).__name__}: {e}"[:200], transient=True)


async def _collect(account_id: str, item: VaultItem, raw: dict,
                   want: int) -> Collected:
    client = await asyncio.to_thread(ax._make_client, account_id)
    if item.kind == "video":
        return await _collect_video(account_id, item.media_id, raw, client, want)
    still = await vault_stills.bytes_for(
        account_id, item.media_id,
        vault_stills.image_path(account_id, item.media_id), pick_image)
    if still.data is None:
        return Collected([], still.reason)
    return Collected([vision.img_data_url(still.data)], "ok")
