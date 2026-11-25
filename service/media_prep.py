from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path

log = logging.getLogger("of-relay.media_prep")

COMPRESS_OFF_MB = 1_000_000
COMPRESS_OVER_MB = int(os.environ.get("VAULT_COMPRESS_OVER_MB") or COMPRESS_OFF_MB)
# Kept under VAULT_UPLOAD_MAX_MB: bitrate targeting is approximate and an overshoot is a rejected file.
TARGET_MB = int(os.environ.get("VAULT_COMPRESS_TARGET_MB") or 190)
# Caps the LONG edge: a height cap shaves 44% off the width of every 9:16 master (see _scale_vf).
MAX_HEIGHT = int(os.environ.get("VAULT_COMPRESS_MAX_HEIGHT") or 1080)
AUDIO_KBPS = 128
TRANSCODE_CRF = int(os.environ.get("VAULT_TRANSCODE_CRF") or 20)
# One deadline per file across all passes, so a remux that hangs to the ceiling cannot spend it twice on the transcode.
FFMPEG_BUDGET_S = int(os.environ.get("VAULT_FFMPEG_BUDGET_S") or 3600)
# One budget per file across all passes, so a failed remux falling through to a transcode cannot spend it twice.
_MIN_DURATION_RATIO = 0.98
_MIN_DURATION_SLACK_S = 1.0
# Truncation detector: `-c copy` of a source with a short mdat exits 0 and writes a valid short mp4, and the original is deleted after upload.
_MEASURE_TIMEOUT_S = int(os.environ.get("VAULT_MEASURE_TIMEOUT_S") or 300)

_VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".webm", ".mpg", ".mpeg",
                   ".wmv", ".ts", ".m2ts", ".mts", ".flv", ".3gp"}
_MP4_SUFFIXES = {".mp4", ".m4v"}
# Only h264-in-mp4 has HAR evidence for OF's transcoder; the rest are guesses, so the set stays small (a wrong guess costs one transcode).
_OF_ACCEPTS_UNCHANGED = {"h264", "hevc", "av1", "vp9", "mpeg4"}
# Cover-art streams: treating one as the video would upload a slideshow of the poster frame instead of the footage.
_STILL_VIDEO_CODECS = {"mjpeg", "png", "bmp", "gif", "webp", "tiff", "ppm"}
# A still-picture "video" stream is cover art (Plex/MakeMKV write these), not the footage.
_MP4_LEGAL_AUDIO = {"aac", "mp3", "ac3", "eac3", "alac", "mp2", "opus"}


def have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg"))


def can_shrink(name: str | Path, mime: str | None = None) -> bool:
    if not have_ffmpeg():
        return False
    if mime:
        if mime.startswith("video/"):
            return True
        if mime.startswith(("image/", "audio/")):
            return False
    return is_video(Path(name))


def is_video(path: Path) -> bool:
    return path.suffix.lower() in _VIDEO_SUFFIXES


@dataclass(frozen=True)
class Probe:
    answered: bool = False
    video: str | None = None
    video_index: int | None = None
    has_video: bool = False
    audio: tuple[str, ...] = ()
    duration: float | None = None
    video_duration: float | None = None
    audio_durations: tuple[float, ...] = ()
    other_streams: bool = False

    @property
    def kept_duration(self) -> float | None:
        # format.duration spans streams a remux drops (e.g. subtitles): judging a correct remux by it flagged it as truncated.
        kept = [d for d in (self.video_duration, *self.audio_durations)
                if d and d > 0]
        if kept:
            return max(kept)
        if self.other_streams:
            return None
        return self.duration if self.duration and self.duration > 0 else None

    @property
    def vmap(self) -> str:
        return f"0:{self.video_index}" if self.video_index is not None else "0:v:0"

    @property
    def audio_needs_aac(self) -> bool:
        return any(a not in _MP4_LEGAL_AUDIO for a in self.audio)


def probe(path: Path) -> Probe:
    if not shutil.which("ffprobe"):
        return Probe()
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_entries",
             "format=duration:stream=index,codec_type,codec_name,duration"
             ":stream_tags=DURATION:stream_disposition=attached_pic",
             str(path)],
            capture_output=True, text=True, timeout=60, check=True).stdout
        doc = json.loads(out)
    except Exception:  # noqa: BLE001 — probing is advisory
        log.debug("ffprobe failed on %s", path, exc_info=True)
        return Probe()

    streams = doc.get("streams") or []
    if not streams:
        return Probe()
    videos: list[tuple[int, str, float | None]] = []
    audio: list[tuple[str, float | None]] = []
    other = False
    for s in streams:
        kind = s.get("codec_type")
        name = (s.get("codec_name") or "").lower()
        secs = _stream_seconds(s)
        if kind == "video":
            if (s.get("disposition") or {}).get("attached_pic"):
                continue
            videos.append((int(s.get("index") or 0), name, secs))
        elif kind == "audio":
            audio.append((name, secs))
        else:
            other = True
    moving = [v for v in videos if v[1] not in _STILL_VIDEO_CODECS]
    picked = (moving or videos or [(None, None, None)])[0]

    dur = (doc.get("format") or {}).get("duration")
    try:
        duration = float(dur) if dur else None
    except (TypeError, ValueError):
        duration = None
    return Probe(answered=True, video=picked[1] or None, video_index=picked[0],
                 has_video=bool(videos),
                 audio=tuple(a for a, _ in audio if a), duration=duration,
                 video_duration=picked[2],
                 audio_durations=tuple(d for _, d in audio if d),
                 other_streams=other)


def _stream_seconds(stream: dict) -> float | None:
    # Matroska has no stream=duration, only a per-stream DURATION tag (HH:MM:SS.nnn).
    raw = stream.get("duration")
    try:
        if raw is not None:
            secs = float(raw)
            return secs if secs > 0 else None
    except (TypeError, ValueError):
        pass
    tag = (stream.get("tags") or {}).get("DURATION")
    if not tag:
        return None
    try:
        h, m, s = str(tag).split(":")
        secs = int(h) * 3600 + int(m) * 60 + float(s)
    except (TypeError, ValueError):
        return None
    return secs if secs > 0 else None


def source_duration(path: Path, pr: Probe) -> float | None:
    kept = pr.kept_duration
    if kept and kept > 0:
        return kept
    return _measure_duration(path, pr)


def _measure_duration(path: Path, pr: Probe) -> float | None:
    # Pipe-written containers (OBS, captures) carry no duration in the header: count packets, bounded by its own timeout.
    if not shutil.which("ffprobe") or pr.video_index is None:
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-select_streams", str(pr.video_index), "-count_packets",
             "-show_entries", "stream=nb_read_packets,avg_frame_rate",
             str(path)],
            capture_output=True, text=True, timeout=_MEASURE_TIMEOUT_S,
            check=True).stdout
        s = (json.loads(out).get("streams") or [{}])[0]
        packets = int(s.get("nb_read_packets") or 0)
        num, _, den = str(s.get("avg_frame_rate") or "").partition("/")
        fps = float(num) / float(den or 1)
    except Exception:  # noqa: BLE001 — measuring is advisory, like probing
        log.debug("media_prep: could not measure %s", path, exc_info=True)
        return None
    if packets <= 0 or fps <= 0:
        return None
    secs = packets / fps
    log.info("media_prep: %s states no duration — measured %.1fs from %d "
             "packets", path.name, secs, packets)
    return secs


PASSTHROUGH = "passthrough"
REMUX = "remux"
TRANSCODE = "transcode"
COMPRESS = "compress"

DONE = "done"
FAILED = "failed"
UNVERIFIED = "unverified"


@dataclass(frozen=True)
class Pass:
    out: Path | None
    verdict: str = FAILED

    def __bool__(self) -> bool:
        return self.out is not None


@dataclass(frozen=True)
class Plan:
    action: str
    why: str
    probe: Probe = Probe()
    source_duration: float | None = None


def plan_for(path: Path, *, over_mb: int = COMPRESS_OVER_MB,
             mime: str | None = None) -> Plan:
    try:
        if not can_shrink(path.name, mime):
            return Plan(PASSTHROUGH, "not a video ffmpeg can take a pass at")
        oversize = path.stat().st_size > over_mb * 1024 * 1024
    except OSError:
        return Plan(PASSTHROUGH, "unreadable")

    pr = probe(path)
    audio_only = pr.answered and not pr.has_video
    plan = Plan(COMPRESS, f"over the opt-in {over_mb} MB compress threshold", pr) \
        if (oversize and not audio_only) else plan_by_codec(path, pr)
    return with_source_duration(path, plan)


def with_source_duration(path: Path, plan: Plan) -> Plan:
    if plan.action == PASSTHROUGH or plan.source_duration is not None:
        return plan
    return replace(plan, source_duration=source_duration(path, plan.probe))


def plan_by_codec(path: Path, pr: Probe) -> Plan:
    is_mp4 = path.suffix.lower() in _MP4_SUFFIXES
    if pr.answered and not pr.has_video:
        # No picture (audio-only .mkv): remux/transcode would both die on "Stream map '' matches no streams".
        return Plan(PASSTHROUGH, "no video stream — nothing to normalise", pr)
    if pr.video is None:
        # ffprobe cannot say: leave mp4, else try the cheap remux; never transcode on a guess.
        return Plan(PASSTHROUGH, "already .mp4; codec unknown", pr) if is_mp4 else \
            Plan(REMUX, "codec unknown — a copy-remux is cheap to try", pr)
    if pr.video not in _OF_ACCEPTS_UNCHANGED:
        return Plan(TRANSCODE, f"{pr.video} is not a codec we hand OF unchanged", pr)
    if is_mp4 and not pr.audio_needs_aac:
        return Plan(PASSTHROUGH, f"already mp4/{pr.video} — OF takes this at any size", pr)
    if is_mp4:
        return Plan(REMUX, f"mp4/{pr.video} but audio mp4 cannot carry "
                           f"({', '.join(pr.audio)})", pr)
    return Plan(REMUX, f"{pr.video} in {path.suffix.lower()} — remux to mp4, "
                       f"no re-encode", pr)


def _scale_vf(short_edge: int) -> str:
    long_edge = (short_edge * 16 // 9) // 2 * 2
    box_w = f"min(iw,if(gte(iw,ih),{long_edge},{short_edge}))"
    box_h = f"min(ih,if(gte(iw,ih),{short_edge},{long_edge}))"
    return (f"scale='{box_w}':'{box_h}':force_original_aspect_ratio=decrease"
            f",scale=trunc(iw/2)*2:trunc(ih/2)*2")


def _run_ffmpeg(cmd: list[str], out: Path, src: Path, *, what: str,
                timeout_s: float, source_duration: float | None) -> Pass:
    # Output must reproduce the source duration: `-c copy` of a short mdat exits 0 with a valid short file, and the original is deleted after upload.
    if not source_duration or source_duration <= 0:
        log.warning("media_prep: cannot establish %s's running time — not "
                    "attempting the %s, because an output we cannot verify may "
                    "be a fraction of the source", src.name, what)
        return Pass(None, UNVERIFIED)
    if timeout_s <= 0:
        log.warning("media_prep: no ffmpeg budget left for %s on %s", what, src.name)
        return Pass(None, FAILED)
    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout_s, check=True)
    except subprocess.CalledProcessError as e:
        tail = (e.stderr or b"")[-400:].decode("utf-8", "replace")
        log.warning("media_prep: %s failed on %s — %s", what, src.name, tail)
        out.unlink(missing_ok=True)
        return Pass(None, FAILED)
    except Exception as e:  # noqa: BLE001
        log.warning("media_prep: %s error on %s — %s", what, src.name, e)
        out.unlink(missing_ok=True)
        return Pass(None, FAILED)
    if not out.exists() or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        return Pass(None, FAILED)
    if not _duration_survived(src, out, source_duration, what=what):
        out.unlink(missing_ok=True)
        return Pass(None, UNVERIFIED)
    return Pass(out, DONE)


def _duration_survived(src: Path, out: Path, source_duration: float,
                       *, what: str) -> bool:
    made = probe(out).duration
    if not made:
        log.warning("media_prep: cannot read the %s output's duration for %s "
                    "— uploading the original", what, src.name)
        return False
    floor = min(source_duration * _MIN_DURATION_RATIO,
                source_duration - _MIN_DURATION_SLACK_S)
    if made < floor:
        log.warning("media_prep: %s of %s came out %.1fs from a %.1fs source — "
                    "TRUNCATED, discarding it and uploading the original",
                    what, src.name, made, source_duration)
        return False
    return True


def _out_path(src: Path, dest_dir: Path, tag: str) -> Path:
    # Digest of the source path: `-y` into the shared dir would let holiday.mov's remux overwrite holiday_mp4.mp4's staged bytes.
    key = hashlib.sha1(str(src.resolve()).encode("utf-8", "replace")).hexdigest()[:8]
    return dest_dir / f"{src.stem}_{key}_{tag}.mp4"


def _plan_probe(path: Path, plan: Plan | None) -> tuple[Probe, float | None]:
    pr = plan.probe if (plan is not None and plan.probe.answered) else probe(path)
    dur = plan.source_duration if (plan is not None and plan.source_duration) \
        else source_duration(path, pr)
    return pr, dur


def _remux(path: Path, dest_dir: Path, *, plan: Plan | None = None,
           timeout_s: float = FFMPEG_BUDGET_S) -> Pass:
    # Explicit maps: .mov timecode/data streams make a bare `-c copy` fail, and 0:v:0 may be cover art.
    if not have_ffmpeg():
        return Pass(None, FAILED)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = _out_path(path, dest_dir, "mp4")
    pr, dur = _plan_probe(path, plan)
    acodec = ["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k"] if pr.audio_needs_aac \
        else ["-c:a", "copy"]
    cmd = ["ffmpeg", "-nostdin", "-y", "-i", str(path),
           "-map", pr.vmap, "-map", "0:a?", "-c:v", "copy", *acodec,
           "-movflags", "+faststart", str(out)]
    log.info("media_prep: remuxing %s (%.0f MB) into mp4 — no re-encode",
             path.name, path.stat().st_size / 1e6)
    return _run_ffmpeg(cmd, out, path, what="remux", timeout_s=timeout_s,
                       source_duration=dur)


def _transcode(path: Path, dest_dir: Path, *, crf: int = TRANSCODE_CRF,
               plan: Plan | None = None,
               timeout_s: float = FFMPEG_BUDGET_S) -> Pass:
    if not have_ffmpeg():
        return Pass(None, FAILED)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = _out_path(path, dest_dir, "h264")
    pr, dur = _plan_probe(path, plan)
    cmd = ["ffmpeg", "-nostdin", "-y", "-i", str(path),
           "-map", pr.vmap, "-map", "0:a?",
           "-vf", _scale_vf(MAX_HEIGHT),
           "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high",
           "-pix_fmt", "yuv420p", "-crf", str(crf),
           "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k",
           "-movflags", "+faststart", str(out)]
    log.info("media_prep: transcoding %s (%.0f MB) to h264 mp4 @ crf %d",
             path.name, path.stat().st_size / 1e6, crf)
    return _run_ffmpeg(cmd, out, path, what="transcode", timeout_s=timeout_s,
                       source_duration=dur)


def compress(path: Path, dest_dir: Path, *, target_mb: int = TARGET_MB,
             plan: Plan | None = None,
             timeout_s: float = FFMPEG_BUDGET_S) -> Path | None:
    return _compress(path, dest_dir, target_mb=target_mb, plan=plan,
                     timeout_s=timeout_s).out


def _compress(path: Path, dest_dir: Path, *, target_mb: int = TARGET_MB,
              plan: Plan | None = None,
              timeout_s: float = FFMPEG_BUDGET_S) -> Pass:
    if not have_ffmpeg():
        return Pass(None, FAILED)

    dest_dir.mkdir(parents=True, exist_ok=True)
    out = _out_path(path, dest_dir, "compressed")
    pr, duration = _plan_probe(path, plan)

    # Audio is a fixed cost per second: halve it past ten minutes so it does not eat the picture's budget.
    audio_kbps = AUDIO_KBPS if not duration or duration <= 600 else 64

    def _common(max_edge: int) -> list[str]:
        return [
            "ffmpeg", "-nostdin", "-y", "-i", str(path),
            "-map", pr.vmap, "-map", "0:a?",
            "-vf", _scale_vf(max_edge),
            "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", f"{audio_kbps}k",
            "-movflags", "+faststart",
        ]

    if duration and duration > 1:
        video_kbps = int((target_mb * 8 * 1024) / duration - audio_kbps)
        # Long video: drop resolution to what the bitrate can carry; holding 1080p there blew past the size target.
        max_edge = MAX_HEIGHT
        for h, needed in ((MAX_HEIGHT, 1500), (720, 800), (480, 400), (360, 200)):
            if h > MAX_HEIGHT:
                continue
            if video_kbps >= needed:
                max_edge = h
                break
            max_edge = h
        video_kbps = max(video_kbps, 150)
        cmd = _common(max_edge) + [
            "-b:v", f"{video_kbps}k", "-maxrate", f"{int(video_kbps * 1.5)}k",
            "-bufsize", f"{video_kbps * 2}k", str(out)]
        log.info("media_prep: %s (%.0f MB, %.0fs) -> long edge %d @ %dk video "
                 "+ %dk audio", path.name, path.stat().st_size / 1e6, duration,
                 max_edge, video_kbps, audio_kbps)
    else:
        cmd = _common(MAX_HEIGHT) + ["-crf", "26", str(out)]
        log.info("media_prep: %s — no duration, falling back to CRF 26", path.name)

    res = _run_ffmpeg(cmd, out, path, what="compress", timeout_s=timeout_s,
                      source_duration=duration)
    if res.out is None:
        return res
    if out.stat().st_size >= path.stat().st_size:
        log.info("media_prep: %s did not shrink (%.0f -> %.0f MB), keeping original",
                 path.name, path.stat().st_size / 1e6, out.stat().st_size / 1e6)
        out.unlink(missing_ok=True)
        return Pass(None, FAILED)
    log.info("media_prep: %s %.0f MB -> %.0f MB", path.name,
             path.stat().st_size / 1e6, out.stat().st_size / 1e6)
    return res


def prepare(path: str | Path, dest_dir: str | Path, *,
            over_mb: int = COMPRESS_OVER_MB,
            target_mb: int = TARGET_MB,
            mime: str | None = None) -> tuple[Path, bool]:
    p = Path(path)
    plan = plan_for(p, over_mb=over_mb, mime=mime)
    if plan.action == PASSTHROUGH:
        log.debug("media_prep: %s left alone — %s", p.name, plan.why)
        return p, False
    if not have_ffmpeg():
        log.info("media_prep: ffmpeg not installed — uploading %s as-is", p.name)
        return p, False
    if not plan.source_duration:
        # Refuse before the encode runs: an output whose duration cannot be checked may be truncated, and the original is deleted after upload.
        log.info("media_prep: cannot establish %s's running time (no ffprobe, "
                 "or a container that states none and could not be measured) — "
                 "uploading it as-is rather than encoding something we would "
                 "then have to refuse", p.name)
        return p, False
    log.info("media_prep: %s -> %s (%s)", p.name, plan.action, plan.why)
    deadline = time.monotonic() + FFMPEG_BUDGET_S

    def _left() -> float:
        return deadline - time.monotonic()

    def _stop(res: Pass, what: str) -> bool:
        if res.verdict != UNVERIFIED:
            return False
        log.info("media_prep: the %s of %s could not be verified — uploading "
                 "the original rather than spending a second pass to be "
                 "refused again", what, p.name)
        return True

    try:
        dest = Path(dest_dir)
        res = Pass(None, FAILED)
        if plan.action == COMPRESS:
            res = _compress(p, dest, target_mb=target_mb, plan=plan,
                            timeout_s=_left())
            if _stop(res, "compress"):
                return p, False
            if res.out is None:
                plan = replace(plan_by_codec(p, plan.probe),
                               source_duration=plan.source_duration)
                log.info("media_prep: compress of %s produced nothing — "
                         "falling through to %s (%s)", p.name, plan.action, plan.why)
        if plan.action == REMUX:
            res = _remux(p, dest, plan=plan, timeout_s=_left())
            if _stop(res, "remux"):
                return p, False
            if res.out is None:
                log.info("media_prep: remux of %s did not take — transcoding", p.name)
                res = _transcode(p, dest, plan=plan, timeout_s=_left())
        elif plan.action == TRANSCODE:
            res = _transcode(p, dest, plan=plan, timeout_s=_left())
    except Exception:  # noqa: BLE001 — preparation is an optimisation, not a gate
        log.exception("media_prep: unexpected failure preparing %s", p)
        return p, False
    return (res.out, True) if res.out else (p, False)
