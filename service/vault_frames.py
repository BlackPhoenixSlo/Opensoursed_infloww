"""
vault_frames.py — ONE vault media → the pictures of it.

Everything between "here is a media id" and "here are the frames a vision model
can read" lives here: which url in an OF payload is the picture, which store
holds its permanent bytes, and how a clip becomes stills.

Split out of `vault_ai_api` for the same reason `vision.py` was: describing a
media has nothing to do with routing, folder mirroring or PPV weeks, and the
2026-08-04 incident was a direct consequence of it being buried in 3.5k lines of
those — the fetch it hand-rolled had drifted years away from the ladder
`vault_stills` had grown for exactly this problem, and nothing sat close enough
to either to notice.

The order every lookup takes, and the whole point of this module:

    permanent local bytes  →  the url we stored  →  re-sign with OF  →  give up

OF's signed urls resolve for about a day. A collect stores them; a describe sweep
runs whenever an operator presses the button. Anything that reads a stored url
and stops there works only when those two happen to be close together, which is
not a property the code can rely on and did not have on 2026-08-04, when a sweep
31 hours behind its collect read nothing at all and recorded 979 photos as
un-renderable while their bytes sat on disk.

Rules for anything added here: no routes, no DB writes beyond what the still
store already owns, no prompts. What to ASK about a picture belongs to the
consumer; this module only produces the picture.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import logging
from typing import Any, NamedTuple

import admission  # bounded-concurrency lanes — a LEAF, so no lazy server import
import storyboard  # the scrub-frame store — no server import, so not lazy
import automation_executor as ax  # _make_client seam (same one automations use)
import vault_mirror  # the OF-media → mirror-row mapping (thumb_of)
import vault_stills
import vision
from db.models import VaultItem  # the mirror row `collect` is handed (annotation)
from of_shapes import still_url  # shared OF payload-shape reader

log = logging.getLogger("of-relay.vault_frames")

# Why a frameless item got no frames, as a `describe_status`.
#
# The two outcomes want OPPOSITE retry policies, and collapsing them is what made
# the 2026-08-04 incident invisible: every failure was stamped `blocked_drm`, so
# 1,777 items whose signatures had merely expired inherited the 7-day cool-off
# meant for clips OF genuinely cannot render, and the next sweep skipped them.
#   no_variant   → OF answered with a payload carrying nothing renderable.
#                  Asking again changes nothing. Cool off.
#   fetch_failed → we could not read bytes we have every reason to think exist.
#                  Retry on the very next sweep, no cool-off.
#   gone         → OF has deleted it. The still store already stamped
#                  `removed_at`, which every candidate query filters on, so this
#                  status is only ever read by whoever asked for THIS item.
# Unknown reasons fall to the retryable side: over-retrying costs a fetch,
# under-retrying costs a description nobody notices is missing.
NO_IMAGE_STATUS = {"no_variant": "blocked_drm", "fetch_failed": "fetch_failed",
                    "gone": "gone"}

# How many storyboard frames a describe asks for when nothing overrides it.
DESCRIBE_FRAMES = 9


# ── What a payload offers ───────────────────────────────────────────

def describe_image_of(files: dict | None) -> str | None:
    """The image variant to send the VISION model — not the same choice as the UI
    thumb. Takes a bare `files` dict (vault items store one); the ordering and the
    centre-crop lesson behind it live in `of_shapes.still_url`, shared with the
    inbound-DM describe path so both ask the same question of the same payloads."""
    return still_url({"files": files}) if isinstance(files, dict) else None


def video_url(m: dict) -> str | None:
    """Signed progressive mp4 URL for a video (240p → 720p → full). None for
    DRM-only videos (no sliceable source) — those can't be warmed."""
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
    """OF's own pre-extracted poster-frame URLs for a video
    (`files.preview.options[]`). For SAMPLE-AES DRM clips — which ffmpeg can't
    slice — these are the ONLY renderable representation (same frames the chat
    VaultPicker slideshows). Falls back to the single poster thumb."""
    files = raw.get("files") or {}
    prev = files.get("preview") or {}
    out = [o.get("url") for o in (prev.get("options") or []) if isinstance(o, dict) and o.get("url")]
    if not out:
        one = vault_mirror.thumb_of(files)
        if one:
            out = [one]
    return out


def preview_count(raw: dict) -> int:
    """How many preview frames OF offers for a clip (`files.preview.options`): up to 9, spread across the whole
    clip (owner-confirmed 2026-11-12); a clip under 9 s gets about one per second. 0 = only the poster thumb."""
    prev = (raw.get("files") or {}).get("preview") or {}
    return sum(1 for o in (prev.get("options") or []) if isinstance(o, dict) and o.get("url"))


PREVIEW_MIN = 3   # previews that stand in for the clip's mp4: at least this many, or any on a clip this short (s)


def previews_enough(raw: dict, dur: float) -> bool:
    """OF's preview set reads the clip (D58: no mp4 download, no ffmpeg): ≥ PREVIEW_MIN frames, or any on a clip
    of ≤ PREVIEW_MIN s (whose ~1 frame per second covers all of it). One poster on a longer clip is not enough."""
    n = preview_count(raw)
    return n >= PREVIEW_MIN or (n >= 1 and 0 < dur <= PREVIEW_MIN)


# ── Which url each permanent store holds ────────────────────────────
#
# One rule per store, written once and used for BOTH the stored payload and a
# re-signed one, so the two can't disagree about which picture they mean. The
# three render routes and the describe ladder below share them for that reason.

def pick_thumb(m: dict) -> str | None:
    """The 300px square — the grid + picker tile."""
    return vault_mirror.thumb_of(m.get("files") if isinstance(m.get("files"), dict) else {})


def pick_image(m: dict) -> str | None:
    """Aspect-preserving preview → full → …; the square only if the media exposes
    nothing else."""
    return describe_image_of(m.get("files") if isinstance(m.get("files"), dict) else {})


def pick_poster(i: int) -> vault_stills.Pick:
    """Frame `i` of the poster set, or None if the video has fewer frames."""
    def pick(m: dict) -> str | None:
        frames = poster_frames(m)
        return frames[i] if i < len(frames) else None
    return pick


# ── The storyboard ──────────────────────────────────────────────────

def warm_one_sync(client: Any, url: str, dur: float) -> str:
    """Extract + cache the 12-frame storyboard for ONE video, if not already
    on disk. Incremental: `_storyboard_all_frames_present` short-circuits a
    video we've already warmed (so re-collect only does NEW videos). Reuses
    the relay's own storyboard helpers; downloads through the account's OF
    client so the URL's source-IP signature matches.

    Returns its own outcome vocabulary; `_WARM_REASON` is the only place that
    translates it into this module's."""
    h = storyboard._video_path_hash(url)
    if storyboard._storyboard_all_frames_present(h):
        return "cached"

    # The ffmpeg lane — the SAME lane `/img/scrub` takes, and taken here for a
    # bigger reason. This function is what a describe calls when it meets a clip
    # nobody warmed, and a describe sweep runs `_VISION_GLOBAL_CONCURRENCY`
    # items concurrently: without this, eight cold clips meant eight mp4
    # downloads and eight ffmpeg processes on a two-core box, each holding a
    # vision slot while it ran. Taken AFTER the cached check, so a warm vault
    # never queues at all.
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
    """`want` frame indices spread evenly over `n_have` slots, endpoints
    included. 12 frames → 3 gives [1,5,10]; → 9 gives [0,1,3,4,5,6,8,9,11].
    Endpoints matter for `beats`: the model has to see how a clip ENDS."""
    if want >= n_have:
        return list(range(n_have))
    if want <= 1:
        return [n_have // 2]
    step = (n_have - 1) / (want - 1)
    return sorted({int(round(i * step)) for i in range(want)})


def storyboard_frames(url: str | None, want: int) -> list[str]:
    """`want` frames of this video's storyboard, IF the whole set is on disk.

    Keyed by url rather than by hash so no caller has to know that the store is
    hash-addressed — which matters more than it looks: `_video_path_hash` reads
    the host and path, so frames warmed under a re-signed url answer to a
    different key than the stored one, and a caller holding the wrong key finds
    nothing and concludes the clip is un-renderable."""
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


# ── The ladder ──────────────────────────────────────────────────────

class Collected(NamedTuple):
    """The frames to send a vision model, and WHY there aren't any.

    `reason` uses `vault_stills.Still`'s vocabulary unchanged, because it answers
    the same question one layer up. It is what the caller stamps on the row, and
    the two failing values want OPPOSITE retry policies:

        fetch_failed  we could not read bytes we have every reason to think
                      exist — a dead signature, OF unreachable. Retry at once.
        no_variant    OF answered, and its answer carries nothing renderable.
                      Asking again changes nothing; cool off.

    Collapsing those two is the whole 2026-08-04 incident: every failure was
    recorded as the second, so 1,777 items inherited a 7-day cool-off and the
    sweep that would have fixed them skipped them."""

    images: list[str]
    reason: str  # "ok" | "gone" | "no_variant" | "fetch_failed"
    # What to tell a PERSON, when there is more to say than the status.
    #
    # `reason` is the row's retry policy and nothing else, so the two failures
    # that matter most to an operator are indistinguishable in it: an expired OF
    # signature and a crash in this module are both `fetch_failed`. One means OF
    # is being OF; the other means we shipped a bug. Since `collect` stopped
    # raising, this is the ONLY channel that difference has — the sweep hands it
    # straight to `first_error`, which is what the button reports.
    detail: str = ""


# `warm_one_sync`'s outcome in the vocabulary above. Anything not listed either
# produced frames or means "OF has nothing sliceable", which is `no_variant`.
# Warm outcome → this module's reason vocabulary. Anything NOT named here falls
# to `no_variant`, which is the COOL-OFF side — so a value that means "try again
# shortly" must be listed, or the item inherits the 7-day DRM cooldown meant for
# clips OF genuinely cannot render. That mistake is on record: it froze 1,777
# items whose signatures had merely expired.
#   busy — the ffmpeg lane was full. We learned nothing about this clip at all,
#          so it is the most retryable outcome there is.
_WARM_REASON = {"dl_fail": "fetch_failed", "error": "fetch_failed",
                "busy": "fetch_failed"}


async def _poster_stills(account_id: str, media_id: int, media: dict,
                         want: int, warm: str) -> Collected:
    """OF's pre-extracted poster frames, through the permanent store.

    The fallback for a clip ffmpeg cannot slice — OF serves these even for DRM.
    Reading them through `vault_stills` (rather than fetching the urls directly)
    is what makes a DRM clip describable a SECOND time: the first pass leaves the
    frames on disk, and every pass after that costs no OF call at all."""
    frames: list[str] = []
    transient = False
    # `pick_poster` re-derives each url from the payload — one rule, one place —
    # so all this needs from the list is how many frames are on offer, `want` of them spread over the set (the
    # clip's end included). Fetched together (D58: they ARE the clip's reading now; `bytes_for` bounds the fan-out).
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
    """Frames for one clip: the warmed storyboard, else OF's poster set.

    The storyboard is both the cheap path and the durable one — its key is taken
    from the url with the query string stripped, so frames warmed under one
    signature keep answering under the next. That is the entire reason clips
    survived the 2026-08-04 expiry and photos did not.

    A clip we never warmed still needs a live mp4, and the stored url is as dead
    as any other. So the miss re-signs ONCE, and everything after it — the mp4,
    the key its frames are written under, the poster urls — comes from that one
    fresh payload. Mixing a fresh mp4 with stale poster urls is how two halves of
    the same read end up describing different media."""
    frames = storyboard_frames(video_url(raw), want)
    if frames:
        return Collected(frames, "ok")

    fresh = await vault_stills.resolve_fresh(account_id, media_id, client)
    if fresh.media is None:
        # `gone` vs `fetch_failed` comes back WITH the miss — the two want
        # opposite retry policies and the store already knows which it was.
        return Collected([], fresh.reason)
    media = fresh.media
    dur = float(media.get("duration") or raw.get("duration") or 0)
    if previews_enough(media, dur):   # the frames the Jev pass already stored (`_poster_stills`): no mp4 at all
        got = await _poster_stills(account_id, media_id, media, want, "")
        if len(got.images) >= min(PREVIEW_MIN, want, preview_count(media)):   # too few landed: the mp4 below
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


# A single item's whole frame budget: re-sign, mp4 download, ffmpeg extract, the
# poster-set fallback, all of it. Generous — a 17-minute clip pulled at 240p and
# sliced into 12 stills is minutes of honest work, and killing that costs a
# description. What it bounds is the OTHER case: a fetch that never returns holds
# a sweep slot AND a process-wide vision slot forever, and the 50-item chunk
# barrier above it can never close. Timing out reads as `fetch_failed`, which is
# the retry-at-once side of the vocabulary — the next sweep tries again.
COLLECT_TIMEOUT_S = 180


async def collect(account_id: str, item: VaultItem, raw: dict,
                  want: int = DESCRIBE_FRAMES) -> Collected:
    """Frames for one vault item, as base64 data-URLs.

    Photos read IMAGE_DIR, never THUMB_DIR. The thumb is a 300px centre-crop of a
    3:4 portrait — its top and bottom are simply gone — and reading a flag off
    that crop is what made the vision model over-report `fully_nude`. `pick_image`
    is `describe_image_of`, so this is the same variant describe has always sent.

    NEVER raises. Every caller is a bulk sweep walking a vault, and a media that
    explodes has to cost that one media — the callers each stamp `reason` onto the
    row and move on, which is strictly more useful than an exception, because a
    raise leaves no row at all and the item looks untouched forever."""
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


# ── A video's Jev frames (D54) ──────────────────────────────────────
#
# D58 (owner 2026-11-12, load speed): a clip with OF's preview set (`previews_enough`: up to 9 frames spread across
# it, ~720 px) is read off those, src "preview": no mp4 download, no ffmpeg; the describe reads the same stored frames.
# A clip longer than env `JEV_PREVIEW_LONG_S` (default 120 s) read so is `review` long: 9 frames over minutes can miss
# the act (live 11-12: a 221 s clip read $10 off previews, $100 off its 240p). Only a clip without previews takes the
# mp4 ladder below.
# Jev reads a clip off 12 frames from its 720p rendition (the bench's 400px storyboard lost $100 insertions, D53).
# The whole 720p mp4 comes through the account's client (no range seeks: one plain GET, as `warm_one_sync`), capped:
# above JEV_VIDEO_CAP_BYTES the 240p one (capped too) is read and the reading is marked `review` (never a free lane).
# With no 720p rendition OF's `files.full` (the native upload: 640x480 / 564x360 on the 3/30 such clips probed
# 11-12) is tried before the 240p; read off it, the reading is `review` no_720 only when its frames' short side is
# under JEV_VIDEO_MIN_SHORT_PX; read off the 240p, always. Nothing readable → OF's poster frames, `review` too.
# The cap is env `JEV_VIDEO_CAP_BYTES` (default 50 MB; the per-clip budget grows with it). One ffmpeg pass writes the
# native frames Jev reads (transient) and, when the clip's storyboard is not on disk yet, the 400px scrub frames
# under the hash hover scrub and describe look them up by (`video_url`'s: the 240p url's), so the describe that
# follows reads the same frames and hover never builds them again.

JEV_VIDEO_FRAMES = storyboard._STORYBOARD_FRAMES
JEV_VIDEO_MIN_SHORT_PX = 480   # a no-720p clip's native frames at least this on their short side: no review
_JEV_VIDEO_CAP_DEFAULT = 50_000_000
_JEV_PREVIEW_LONG_DEFAULT = 120.0


def _env_preview_long_s() -> float:
    """Env `JEV_PREVIEW_LONG_S`: a clip read off previews longer than this (s) is `review` long (unset / unparsable /
    <= 0 → 120)."""
    import os
    try:
        v = float(os.environ.get("JEV_PREVIEW_LONG_S") or 0)
    except ValueError:
        v = 0.0
    return v if v > 0 else _JEV_PREVIEW_LONG_DEFAULT


def _env_cap_bytes() -> int:
    """Env `JEV_VIDEO_CAP_BYTES`: the per-clip download cap in bytes (unset / unparsable / <= 0 → 50 MB). Every byte
    under it is proxy traffic: probed 11-12, 11 of 27 720p mp4s were over 50 MB (p90 182 MB, max 1.08 GB)."""
    import os
    try:
        v = int(os.environ.get("JEV_VIDEO_CAP_BYTES") or 0)
    except ValueError:
        v = 0
    return v if v > 0 else _JEV_VIDEO_CAP_DEFAULT


def _budget_s(cap: int) -> int:
    """Whole budget for one clip's frames: re-sign, a cap-sized download at ~1 MB/s through a proxy, the ffmpeg
    pass, the poster fallback (190 s + 1 s per MB of cap: 240 s at 50 MB), bounded at 15 min. Past it the item is
    `fetch_failed` (retry next sweep)."""
    return min(900, 190 + cap // 1_000_000)


JEV_VIDEO_CAP_BYTES = _env_cap_bytes()
JEV_VIDEO_TIMEOUT_S = _budget_s(JEV_VIDEO_CAP_BYTES)
_JEV_FFMPEG_TIMEOUT_S = 90   # capped further by the clip's deadline (`_ffmpeg_timeout`)
_JEV_DL_RESERVE_S = 30       # the download stops this long before the clip's deadline: ffmpeg's share


class JevFrames(NamedTuple):
    """One clip's frames for `vault_jev.run_video` (native-resolution JPEG bytes, clip order), and why not."""

    frames: list[bytes]
    reason: str              # `Collected.reason`'s vocabulary
    detail: str = ""
    src: str = ""            # "preview" | "720" | "240" | "full" | "poster"
    review: str | None = None  # no_720 | over_cap | src_failed | few_frames | poster_only | long: may be too low
    nbytes: int = 0
    # a source failed on the way here (download failed / raised, ffmpeg short, deadline), frames or none: the reading
    # may be better next sweep, so `vault_jev_pass` retries it (up to its ceiling) instead of stamping this one
    transient: bool = False


def _download_capped(client: Any, url: str, path: Any, deadline: float) -> tuple[str, int]:
    """("ok" | "over_cap" | "dl_fail", bytes seen). Refuses on content-length before reading a byte, and stops
    reading once past the cap or the deadline (a missing header cannot pull an uncapped file)."""
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
    """ffmpeg's timeout: `_JEV_FFMPEG_TIMEOUT_S`, never past the clip's absolute `deadline` (min 1 s)."""
    import time
    return max(1.0, min(_JEV_FFMPEG_TIMEOUT_S, deadline - time.monotonic()))


def _extract_jev(src: Any, dur: float, out: Any, scrub: Any | None, deadline: float) -> list[bytes]:
    """One ffmpeg run: frame i at storyboard's mid-segment time, native resolution (q2) into `out`, and 400px
    (storyboard's scale + q5) into `scrub` when given; killed at `_ffmpeg_timeout(deadline)`. Returns the
    native frames that landed, in order."""
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
    """Move a full 400px set into the storyboard store (missing frames backfilled from the nearest, as
    `_storyboard_extract_batch` does), one atomic rename per frame. Copied into the store first: the temp dir and
    the store are different filesystems in the container (a bind mount), where a rename across them fails EXDEV
    (measured on AE 2026-11-12: 6 of 8 first reads of a 720p clip failed so)."""
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
        shutil.copyfile(tmp / f"{i}.jpg", part)
        os.replace(part, dest / f"{i}.jpg")


def _short_side(jpeg: bytes) -> int:
    """A decoded frame's short side in px (0 when it does not decode)."""
    import io
    from PIL import Image
    try:
        with Image.open(io.BytesIO(jpeg)) as im:
            return min(im.size)
    except Exception:  # noqa: BLE001
        return 0


def _jev_frames_sync(client: Any, media: dict, dur: float, deadline: float) -> JevFrames | None:
    """The download + ffmpeg half (a thread), all inside the clip's absolute `deadline` (monotonic): downloads
    stop `_JEV_DL_RESERVE_S` before it, ffmpeg is killed at it. A source that fails (download, decode) or lands
    fewer than `JEV_VIDEO_FRAMES` frames hands over to the next, whose reading is then `review` src_failed; with
    none whole, the source that landed the most frames is read, `review` few_frames. No frame at all: None when
    every mp4 was over the cap, else `fetch_failed` (the caller reads the posters either way). A reading after any
    source failed is `transient` (`vault_jev_pass` retries it)."""
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
    best: tuple[list[bytes], str, int] | None = None   # the most frames a short source landed
    fails: list[str] = []
    with tempfile.TemporaryDirectory(prefix="jev-video-") as td:
        tmp = Path(td)
        for label, url in cands:
            if time.monotonic() > deadline - _JEV_DL_RESERVE_S:
                fails.append(f"out of time before the {label} mp4")
                break
            for p in ("out", "scrub"):   # the last source's frames
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
                if not lock.acquire(blocking=False):   # a hover is building it: leave the scrub to it
                    lock = None
            try:
                (tmp / "out").mkdir()
                if lock is not None:
                    (tmp / "scrub").mkdir()
                # the file's own length (the bench's), not OF's whole-second `duration`: seeks past the real
                # end land no frame (measured 11-12: 9/12 on 2-3 s clips)
                d = storyboard._storyboard_probe_duration(tmp / "src.mp4") or dur
                frames = _extract_jev(tmp / "src.mp4", max(0.1, d or 1.0), tmp / "out",
                                      tmp / "scrub" if lock is not None else None, deadline)
                if lock is not None:
                    _publish_scrub(tmp / "scrub", h)
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


# A sweep's clip took its JEV_VIDEO slot before its vision slot (`lane_ahead`): `_collect_jev_video` claims that slot
# instead of entering the lane, and owns its release from then on (the frame thread's end). One mutable cell, so a
# task spawned under the visit (copied context) claims the same slot.
_LANE_TICKET: contextvars.ContextVar[list[bool] | None] = contextvars.ContextVar("jev_lane_ticket", default=None)


@contextlib.asynccontextmanager
async def lane_ahead(label: str):
    """Take a JEV_VIDEO slot, waiting as long as it takes (the caller holds nothing meanwhile), for this task's
    next `_collect_jev_video`; given back on exit (or by `drop_lane`) unless that claimed it."""
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
    """Take over this task's `lane_ahead` slot (True), once; False: none held, enter the lane yourself."""
    t = _LANE_TICKET.get()
    if t is None or t[0]:
        return False
    t[0] = True
    return True


def drop_lane() -> None:
    """Give back this task's unclaimed `lane_ahead` slot now (the Jev pass is over: no frames left to read), so it
    is not held through the describe call after."""
    if _claim_lane():
        admission.JEV_VIDEO.exit()


async def _collect_jev_video(account_id: str, item: VaultItem, deadline: float) -> JevFrames:
    """Every step inside one absolute `deadline` (monotonic, set once by `collect_jev_video`): the re-sign and
    the posters are cut at it, the download + ffmpeg thread stops itself by it (`_jev_frames_sync`)."""
    import time

    def left() -> float:
        return max(0.0, deadline - time.monotonic())
    client = await asyncio.to_thread(ax._make_client, account_id)
    fresh = await asyncio.wait_for(vault_stills.resolve_fresh(account_id, item.media_id, client), left())
    if fresh.media is None:
        return JevFrames([], fresh.reason)
    media = fresh.media
    dur = float(media.get("duration") or item.duration_seconds or 0)
    if previews_enough(media, dur):   # D58: OF's spread preview frames read the clip; the mp4s only without them
        pv = await asyncio.wait_for(_poster_stills(account_id, item.media_id, media, JEV_VIDEO_FRAMES, ""), left())
        if len(pv.images) >= min(PREVIEW_MIN, preview_count(media)):
            short = len(pv.images) < min(JEV_VIDEO_FRAMES, preview_count(media))   # some failed: retried
            drop_lane()   # a sweep's mp4 slot (`lane_ahead`) this read never needed: not held through Jev's call
            review = "long" if dur > _env_preview_long_s() else "few_frames" if short else None
            return JevFrames([base64.b64decode(u.split(",", 1)[1]) for u in pv.images], "ok", src="preview",
                             review=review, transient=short)
    if video_url(media):
        # a sweep's clip already holds its slot (`lane_ahead`); a lone visit waits briefly (`admission.JEV_VIDEO`)
        if not _claim_lane() and not await admission.JEV_VIDEO.enter_async(f"jev video media={item.media_id}"):
            return JevFrames([], "fetch_failed", "jev_video lane full — retried next sweep")

        async def held() -> JevFrames | None:
            try:
                return await asyncio.to_thread(_jev_frames_sync, client, media, dur, deadline)
            finally:
                admission.JEV_VIDEO.exit()
        # shielded: a cancelled caller leaves the thread (bounded by `deadline`) to finish and free the lane itself
        got = await asyncio.shield(asyncio.ensure_future(held()))
        if got is not None and got.frames:
            return got
    else:
        got = None
    posters = await asyncio.wait_for(
        _poster_stills(account_id, item.media_id, media, JEV_VIDEO_FRAMES, ""), left())
    if not posters.images:   # every mp4 failed: that (retry next sweep), not the posters' reason
        return got if got is not None else JevFrames([], posters.reason, posters.detail)
    # `got` here = every mp4 failed (not over the cap, not absent): the posters stand in for a brief failure
    return JevFrames([base64.b64decode(u.split(",", 1)[1]) for u in posters.images], "ok", src="poster",
                     review="poster_only", transient=got is not None)


async def collect_jev_video(account_id: str, item: VaultItem) -> JevFrames:
    """One clip's Jev frames (module section above). Re-signs once (the mp4s and posters all come from that one
    fresh payload). Never raises; a failure is the result's `reason` (+ `detail`), `collect`'s vocabulary. One
    absolute deadline, `JEV_VIDEO_TIMEOUT_S` from now, bounds every step (`_collect_jev_video`)."""
    import time
    try:
        return await _collect_jev_video(account_id, item, time.monotonic() + JEV_VIDEO_TIMEOUT_S)
    except asyncio.TimeoutError:
        log.warning("collect_jev_video timed out after %ss account=%s media=%s",
                    JEV_VIDEO_TIMEOUT_S, account_id, item.media_id)
        return JevFrames([], "fetch_failed", f"gave up reading the clip after {JEV_VIDEO_TIMEOUT_S}s", transient=True)
    except Exception as e:  # noqa: BLE001
        log.exception("collect_jev_video failed account=%s media=%s", account_id, item.media_id)
        return JevFrames([], "fetch_failed", f"{type(e).__name__}: {e}"[:200])


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
