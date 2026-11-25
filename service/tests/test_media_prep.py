#!/usr/bin/env python3
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import media_prep as M      # noqa: E402
import of_client            # noqa: E402

failures: list[str] = []
skipped: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  FAIL {label}: got {got!r}, want {want!r}")


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args],
                   check=True, capture_output=True)


def _dims(p: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def _codecs(p: Path) -> list[str]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name",
         "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, check=True).stdout
    return [line for line in out.split() if line]


print("\nmedia_prep.plan_by_codec")
_P = M.Probe


def _plan(name: str, video, audio=("aac",), idx=0):
    return M.plan_by_codec(Path(name), _P(answered=True, video=video,
                                          video_index=idx, has_video=True,
                                          audio=tuple(audio), duration=10.0))


check("h264 already in mp4 is left alone at any size",
      _plan("a.mp4", "h264").action, M.PASSTHROUGH)
check("hevc in mp4 too", _plan("a.m4v", "hevc").action, M.PASSTHROUGH)
check("h264 in a .mov is a remux, not a re-encode",
      _plan("a.mov", "h264").action, M.REMUX)
check("prores is a transcode", _plan("a.mov", "prores").action, M.TRANSCODE)
check("mp4 with audio mp4 cannot carry is still only a remux",
      _plan("a.mp4", "h264", ("pcm_s16le",)).action, M.REMUX)
check("an unprobeable .mp4 is left alone",
      M.plan_by_codec(Path("a.mp4"), _P()).action, M.PASSTHROUGH)
check("an unprobeable .mov gets the cheap remux ATTEMPT, never a blind transcode",
      M.plan_by_codec(Path("a.mov"), _P()).action, M.REMUX)
check("mjpeg is not something we hand OF unchanged",
      "mjpeg" in M._OF_ACCEPTS_UNCHANGED, False)
check("hevc is spelt the way ffprobe emits it, and h265 is not in the table",
      ("hevc" in M._OF_ACCEPTS_UNCHANGED, "h265" in M._OF_ACCEPTS_UNCHANGED),
      (True, False))

check("one bad stream among good ones still forces AAC",
      _P(answered=True, audio=("aac", "pcm_s16le")).audio_needs_aac, True)
check("all-legal audio is copied", _P(answered=True, audio=("aac", "mp3")).audio_needs_aac,
      False)
check("no audio at all is not a reason to re-encode",
      _P(answered=True, audio=()).audio_needs_aac, False)


print("\nmedia_prep.plan_for ordering")
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    mp4 = td / "conforming.mp4"
    mp4.write_bytes(b"\0" * (3 * 1024 * 1024))
    _have_ffmpeg = M.have_ffmpeg
    M.have_ffmpeg = lambda: True
    try:
        check("with the hatch on, even a conforming mp4 takes the compress pass",
              M.plan_for(mp4, over_mb=1).action, M.COMPRESS)
        check("with the hatch off (the default), it does not",
              M.plan_for(mp4, over_mb=M.COMPRESS_OFF_MB).action != M.COMPRESS, True)
        check("a non-video is never planned for at all",
              M.plan_for(td / "notes.txt", over_mb=1).action, M.PASSTHROUGH)
    finally:
        M.have_ffmpeg = _have_ffmpeg


print("\nmedia_prep._scale_vf")
check("the box is picked by orientation, so a portrait frame is not squashed",
      ("if(gte(iw,ih),1920,1080)" in M._scale_vf(1080)
       and "if(gte(iw,ih),1080,1920)" in M._scale_vf(1080)), True)
check("and never upscales", "force_original_aspect_ratio=decrease" in M._scale_vf(1080),
      True)


print("\nmedia_prep._out_path")
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    a, b = td / "holiday.mov", td / "holiday_mp4.mp4"
    a.touch(); b.touch()
    check("holiday.mov's remux does not land on holiday_mp4.mp4",
          M._out_path(a, td, "mp4") == b, False)
    check("the same source always resolves to the same output",
          M._out_path(a, td, "mp4"), M._out_path(a, td, "mp4"))


print("\nof_client.convert_rejected")


class _Resp:
    def __init__(self, code):
        self.status_code = code


class _HTTPErr(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.response = _Resp(code)


for code in (502, 503, 504):
    check(f"a {code} on the response object is a refusal",
          of_client.convert_rejected(_HTTPErr(code)), True)
check("a 500 is not", of_client.convert_rejected(_HTTPErr(500)), False)
check("a 200 is not", of_client.convert_rejected(_HTTPErr(200)), False)
check("the status is also read out of the message when there is no response",
      of_client.convert_rejected(RuntimeError("convert register failed: 504 ")), True)
check("...and 502/503 the same way",
      (of_client.convert_rejected(RuntimeError("convert register failed: 502 ")),
       of_client.convert_rejected(RuntimeError("convert register failed: 503 "))),
      (True, True))
check("a plain transport timeout is NOT a refusal — it is worth retrying",
      of_client.convert_rejected(RuntimeError("Operation timed out after 120000 ms")),
      False)
check("nor is a connection reset",
      of_client.convert_rejected(OSError("Connection reset by peer")), False)
check("a 5041 is not a 504", of_client.convert_rejected(
    RuntimeError("convert register failed: 5041")), False)


print("\nof_client.upload_claim claim retries")


def _client_whose_claim(fails_with: dict, then=None):
    c = of_client.OFClient.__new__(of_client.OFClient)
    calls = {"claims": 0}

    def _upload_media(*_a, **_kw):
        return dict(fails_with)

    def _claim(**_kw):
        calls["claims"] += 1
        return dict(then if then is not None else fails_with)

    c.upload_media = _upload_media
    c._claim_uploaded = _claim
    return c, calls


refused = {"ready": False, "rejected": True, "upload_key": "k", "etag": "e",
           "filename": "clip_mp4.mp4", "size": 1,
           "note": "OnlyFans' transcoder refused to register them"}
hung = {**refused, "rejected": False, "note": "bytes in S3 but claim failed: timed out"}

c, calls = _client_whose_claim(refused)
t0 = time.monotonic()
res = c.upload_claim("/tmp/clip_mp4.mp4", claim_retry_delays=(20, 60))
elapsed = time.monotonic() - t0
check("a REFUSED claim is not retried at all", calls["claims"], 0)
check("...so it costs no wall clock, not the 80s the ladder would sleep",
      elapsed < 2.0, True)
check("and the operator still gets the note that explains why",
      "refused to register" in (res.note or ""), True)

c, calls = _client_whose_claim(hung)
res = c.upload_claim("/tmp/clip.mov", claim_retry_delays=(0, 0))
check("a HUNG claim is retried, on every delay in the ladder", calls["claims"], 2)
check("the first failure's note survives an exhausted ladder",
      "claim failed" in (res.note or ""), True)

c, calls = _client_whose_claim(
    hung, then={"ready": True, "rejected": False, "send_with": [{"processId": 7}],
                "upload_key": "k", "etag": "e", "note": "claim re-registered"})
res = c.upload_claim("/tmp/clip.mov", claim_retry_delays=(0, 0))
check("a retry that succeeds stops the ladder with a claim to carry",
      (calls["claims"], bool(res.media), res.retries), (1, True, 1))


if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
    skipped.append("ffmpeg/ffprobe not installed — the real-media checks did "
                   "not run")
else:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        out = td / "out"

        print("\nmedia_prep.prepare — a file with embedded poster art")
        _ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(td / "base.mp4"))
        _ff("-f", "lavfi", "-i", "color=c=blue:s=320x240", "-frames:v", "1",
            str(td / "cover.jpg"))
        covered = td / "covered.mkv"
        _ff("-i", str(td / "cover.jpg"), "-i", str(td / "base.mp4"),
            "-map", "0:v", "-map", "1:v", "-map", "1:a",
            "-c:v:0", "mjpeg", "-c:v:1", "copy", "-c:a", "copy", str(covered))
        pr = M.probe(covered)
        check("the probe skips the poster and names the real video stream",
              (pr.video, pr.video_index), ("h264", 1))
        made, replaced = M.prepare(covered, out)
        check("it is remuxed, not transcoded and not passed through", replaced, True)
        check("and what comes out is the VIDEO, not a still image",
              _codecs(made), ["h264", "aac"])
        check("with the source's full running time",
              round(M.probe(made).duration or 0) == 5, True)

        print("\nmedia_prep.prepare — a source whose bytes are only half there")
        full = td / "full.mov"
        _ff("-f", "lavfi", "-i", "testsrc=size=640x480:rate=25:duration=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            "-movflags", "+faststart", str(full))
        trunc = td / "trunc.mov"
        trunc.write_bytes(full.read_bytes()[:int(full.stat().st_size * 0.4)])
        check("the truncated file still CLAIMS the full duration — which is "
              "why the exit code and the file size cannot catch this",
              round(M.probe(trunc).duration or 0), 30)
        made, replaced = M.prepare(trunc, out)
        check("so the OUTPUT's duration is checked, and a short one is refused",
              replaced, False)
        check("and the original is what goes up", made, trunc)
        check("an intact source of the same shape still prepares normally",
              M.prepare(full, out)[1], True)

        print("\nmedia_prep.transcode — orientation")
        portrait = td / "portrait.mov"
        _ff("-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=25:duration=2",
            "-c:v", "prores", "-pix_fmt", "yuv422p10le", str(portrait))
        plan = M.plan_for(portrait)
        check("prores is a transcode", plan.action, M.TRANSCODE)
        made, replaced = M.prepare(portrait, out)
        check("a 1080x1920 master is ALREADY 1080p and comes through whole",
              _dims(made), (1080, 1920))
        landscape = td / "uhd.mov"
        _ff("-f", "lavfi", "-i", "testsrc=size=3840x2160:rate=25:duration=1",
            "-c:v", "prores", "-pix_fmt", "yuv422p10le", str(landscape))
        check("while a 4K landscape one is capped on its long edge",
              _dims(M.prepare(landscape, out)[0]), (1920, 1080))
        small = td / "small.mov"
        _ff("-f", "lavfi", "-i", "testsrc=size=640x480:rate=25:duration=1",
            "-c:v", "prores", str(small))
        check("and something already small is never upscaled",
              _dims(M.prepare(small, out)[0]), (640, 480))

        print("\nmedia_prep.prepare — the escape hatch, switched on")
        fat = td / "fat.mp4"
        _ff("-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=25:duration=20",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
            "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest", str(fat))
        made, replaced = M.prepare(fat, out, over_mb=0, target_mb=2)
        check("an operator who switches VAULT_COMPRESS_OVER_MB on gets the "
              "size-targeted pass, not a fallthrough",
              (replaced, made.name.endswith("_compressed.mp4")), (True, True))
        check("and it really shrinks, to about the size asked for",
              (made.stat().st_size < fat.stat().st_size,
               made.stat().st_size < int(2.6 * 1024 * 1024)), (True, True))
        check("with the running time intact — a shrink is not a truncation",
              (made != fat, round(M.probe(made).duration or 0)), (True, 20))

        print("\nmedia_prep.prepare — the escape hatch produces nothing")
        check("a re-encode that comes out no smaller is thrown away — and the "
              "plan-carried probe and the self-taken one agree about it",
              (M.compress(full, out, target_mb=190,
                          plan=M.plan_for(full, over_mb=0)),
               M.compress(full, out, target_mb=190)), (None, None))
        made, replaced = M.prepare(full, out, over_mb=0, target_mb=190)
        check("compression that helps nothing falls through to the remux",
              (replaced, made.name.endswith("_mp4.mp4")), (True, True))
        check("and the remux is lossless — same picture codec, same duration",
              (_codecs(made)[0], round(M.probe(made).duration or 0)),
              ("h264", 30))

        print("\nmedia_prep.prepare — a subtitle track that outlives the picture")
        (td / "subs.srt").write_text(
            "1\n00:00:00,000 --> 00:00:20,000\nhello\n\n", encoding="utf-8")
        subbed = td / "subs.mkv"
        _ff("-i", str(td / "base.mp4"), "-i", str(td / "subs.srt"),
            "-map", "0:v", "-map", "0:a", "-map", "1:s",
            "-c:v", "copy", "-c:a", "copy", "-c:s", "srt", str(subbed))
        check("the container claims the SUBTITLE's running time, not the video's",
              (round(M.probe(subbed).duration or 0),
               round(M.probe(subbed).kept_duration or 0)), (20, 5))
        made, replaced = M.prepare(subbed, out)
        check("so the file is judged on the streams the remux KEEPS, and lands",
              (replaced, made.name.endswith("_mp4.mp4")), (True, True))
        check("with the picture intact and no subtitle stream carried into mp4",
              (_codecs(made), round(M.probe(made).duration or 0)),
              (["h264", "aac"], 5))

        print("\nmedia_prep.prepare — a container with no duration at all")
        piped = td / "piped.mkv"
        with piped.open("wb") as fh:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-y",
                 "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=8",
                 "-c:v", "libx264", "-f", "matroska", "-"],
                check=True, stdout=fh, stderr=subprocess.DEVNULL)
        pr_piped = M.probe(piped)
        check("nothing in the header says how long it is",
              (pr_piped.duration, pr_piped.kept_duration), (None, None))
        check("but it can still be MEASURED, once and cheaply",
              round(M.source_duration(piped, pr_piped) or 0), 8)
        made, replaced = M.prepare(piped, out)
        check("so an intact recording is normalised, not uploaded raw",
              (replaced, made.name.endswith("_mp4.mp4")), (True, True))
        check("and the measurement was not a licence to accept a short output",
              round(M.probe(made).duration or 0), 8)

        print("\nmedia_prep.prepare — ffmpeg present, ffprobe missing")
        _real_which = M.shutil.which
        launches_blind: list[str] = []
        _real_run_b = M.subprocess.run

        def _blind_which(name, *a, **kw):
            return None if name == "ffprobe" else _real_which(name, *a, **kw)

        def _counting_run_b(cmd, *a, **kw):
            if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "ffmpeg":
                launches_blind.append(" ".join(str(c) for c in cmd))
            return _real_run_b(cmd, *a, **kw)

        M.shutil.which = _blind_which
        M.subprocess.run = _counting_run_b
        try:
            made, replaced = M.prepare(full, out)
        finally:
            M.shutil.which = _real_which
            M.subprocess.run = _real_run_b
        check("such a host uploads the original, as documented",
              (made, replaced), (full, False))
        check("...and pays NOTHING for that decision — no remux, no transcode",
              launches_blind, [])

        print("\nmedia_prep.prepare — an audio-only file")
        audio_only = td / "audio.mkv"
        _ff("-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-c:a", "aac", str(audio_only))
        pr_audio = M.probe(audio_only)
        check("the probe ANSWERED — it simply found no picture",
              (pr_audio.answered, pr_audio.has_video, pr_audio.video),
              (True, False, None))
        launches: list[str] = []
        _real_run = M.subprocess.run

        def _counting_run(cmd, *a, **kw):
            if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "ffmpeg":
                launches.append(" ".join(str(c) for c in cmd))
            return _real_run(cmd, *a, **kw)

        M.subprocess.run = _counting_run
        try:
            made, replaced = M.prepare(audio_only, out)
        finally:
            M.subprocess.run = _real_run
        check("it is a truthful passthrough", (made, replaced), (audio_only, False))
        check("...costing zero ffmpeg launches, not two that die on an empty map",
              launches, [])
        check("and the reason logged says so",
              "no video stream" in M.plan_for(audio_only).why, True)

        print("\nmedia_prep.remux — audio legality is per file")
        mixed = td / "mixed.mkv"
        _ff("-i", str(td / "base.mp4"), "-f", "lavfi",
            "-i", "sine=frequency=880:duration=5",
            "-map", "0:v", "-map", "0:a", "-map", "1:a",
            "-c:v", "copy", "-c:a:0", "copy", "-c:a:1", "pcm_s16le", str(mixed))
        pr = M.probe(mixed)
        check("the probe sees BOTH audio streams, not just the first",
              len(pr.audio) == 2 and pr.audio_needs_aac, True)
        made, replaced = M.prepare(mixed, out)
        check("so no raw PCM survives into the 'normalised' mp4",
              [c for c in _codecs(made) if c.startswith("pcm")], [])

for s in skipped:
    print(f"\n  SKIP {s}")
if failures:
    print(f"\n{len(failures)} check(s) failed:", file=sys.stderr)
    for f in failures:
        print(f"  {f}", file=sys.stderr)
    raise SystemExit(1)
print("\nall media_prep checks passed")
