#!/usr/bin/env python3
"""`/img` Range requests on small clips — the disk cache answers them. Plain-assert, no pytest (repo convention).

Why: a vault GIF is an OF mp4 (`files.full`) a <video> loops (VaultGifLoop, the Media details panel). A <video>
always sends Range, and `/img` used to skip its disk cache for Range, so every picker open re-downloaded every
on-screen GIF through the account's paid proxy (measured in the PR #277 work).

  case_miss_fetches_once_then_disk      — `bytes=0-` miss: one upstream GET (Range forwarded), the whole clip to
                                          disk, a 206 off disk; the next opens (other ranges, other signatures):
                                          0 upstream.
  case_ranges_off_disk                  — a cached clip: `bytes=0-`, open-ended, closed, suffix → 206 with the
                                          right Content-Range / Accept-Ranges / Content-Length and bytes;
                                          past the end → 416 `bytes */n`. No upstream, no lane slot.
  case_partial_of_small_refetches_whole — upstream answers a part (Safari's `bytes=0-1` probe): one more GET
                                          without Range fetches the whole clip, then disk.
  case_big_or_unknown_streams_through   — over IMG_RANGE_CACHE_MAX_BYTES, or no size: today's pass-through
                                          (upstream's 206 streamed, nothing on disk, every request upstream).
  case_plain_get_keeps_the_photo_cap    — no Range: a 3 MB object (over the 2 MB photo cap, under the clip cap)
                                          is still not cached.

OF's CDN is faked at the client's `http.get`: no request leaves the process.
Run: ./venv/bin/python service/tests/test_img_range_cache.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

_TMP = Path(tempfile.gettempdir()) / f"img_range_test_{uuid.uuid4().hex}"
os.environ["IMG_CACHE_DIR"] = str(_TMP / "cache")

import admission  # noqa: E402
import img_api  # noqa: E402
import server  # noqa: E402 — after _harness (DB) + IMG_CACHE_DIR are bound

_harness.bootstrap()
CLIENT = _harness.make_client()

CLIP = bytes(range(256)) * 400            # 102_400 bytes: a small GIF clip
PATH = "https://cdn2.onlyfans.com/files/g/ab/gif_clip.mp4"


def _u(sig: str = "s1") -> str:
    return f"{PATH}?Policy=P&Signature={sig}&Key-Pair-Id=K"


class _Resp:
    """CloudFront as OF's CDN answers: a Range → 206 + Content-Range; `sized=False` drops the sizes (chunked)."""

    def __init__(self, body: bytes, range_: str | None, sized: bool = True):
        n = len(body)
        self.headers = {"Content-Type": "video/mp4", "Accept-Ranges": "bytes"}
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", range_ or "")
        if m:
            a = int(m.group(1)) if m.group(1) else n - int(m.group(2))
            b = int(m.group(2)) if m.group(1) and m.group(2) else n - 1
            self.status_code, self._body = 206, body[a:b + 1]
            if sized:
                self.headers["Content-Range"] = f"bytes {a}-{b}/{n}"
        else:
            self.status_code, self._body = 200, body
        if sized:
            self.headers["Content-Length"] = str(len(self._body))
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self):
        self.closed = True


class _Cdn:
    def __init__(self, body: bytes = CLIP, sized: bool = True, partial: bool = False):
        self.body, self.sized, self.partial = body, sized, partial
        self.gets: list[str | None] = []   # the Range each upstream GET carried (None: none)

    def get(self, url, timeout=None, stream=False, headers=None):
        rng = (headers or {}).get("Range")
        self.gets.append(rng)
        if rng and self.partial:   # a CDN that only ever answers the first 2 bytes of a Range
            rng = "bytes=0-1"
        return _Resp(self.body, rng, self.sized)


def _rig(cdn: _Cdn) -> None:
    shutil.rmtree(_TMP / "cache", ignore_errors=True)
    server._get_client = lambda *a, **k: SimpleNamespace(http=cdn, timeout_s=5, account_id="acct-1")


def _get(rng: str | None = None, sig: str = "s1"):
    return CLIENT.get("/img", params={"u": _u(sig)}, headers={"Range": rng} if rng else {})


def _on_disk() -> bool:
    return img_api._img_cache_lookup(_u()) is not None


def case_miss_fetches_once_then_disk():
    cdn = _Cdn()
    _rig(cdn)
    r = _get("bytes=0-")
    assert r.status_code == 206, (r.status_code, r.text[:200])
    assert r.headers["content-range"] == f"bytes 0-{len(CLIP) - 1}/{len(CLIP)}", r.headers
    assert r.content == CLIP
    assert cdn.gets == ["bytes=0-"], cdn.gets
    assert _on_disk()
    # Reopen: another range, another signature (OF re-signed), the details panel's own <video>: 0 upstream.
    for rng, sig in (("bytes=0-", "s2"), ("bytes=4096-", "s3"), (None, "s4")):
        r = _get(rng, sig)
        assert r.status_code in (200, 206) and r.headers.get("x-img-cache") == "HIT", (rng, r.status_code, r.headers)
    assert cdn.gets == ["bytes=0-"], f"a reopen went upstream: {cdn.gets}"


def case_ranges_off_disk():
    cdn = _Cdn()
    _rig(cdn)
    img_api._img_cache_write(_u(), "video/mp4", CLIP)
    n = len(CLIP)
    video_free = admission.VIDEO_STREAM.free()
    for rng, a, b in (("bytes=0-", 0, n - 1), ("bytes=1000-", 1000, n - 1), ("bytes=10-19", 10, 19),
                      ("bytes=-500", n - 500, n - 1)):
        r = _get(rng)
        assert r.status_code == 206, (rng, r.status_code)
        assert r.headers["content-range"] == f"bytes {a}-{b}/{n}", (rng, r.headers)
        assert r.headers["accept-ranges"] == "bytes", r.headers
        assert int(r.headers["content-length"]) == b - a + 1 == len(r.content), (rng, r.headers)
        assert r.content == CLIP[a:b + 1], rng
    r = _get(f"bytes={n}-")
    assert r.status_code == 416, r.status_code
    assert r.headers["content-range"] == f"bytes */{n}", r.headers
    assert cdn.gets == [], cdn.gets
    assert admission.VIDEO_STREAM.free() == video_free, "a lane slot leaked or a hit took one"


def case_partial_of_small_refetches_whole():
    cdn = _Cdn(partial=True)
    _rig(cdn)
    r = _get("bytes=0-1")
    assert r.status_code == 206 and r.content == CLIP[:2], (r.status_code, r.headers)
    assert cdn.gets == ["bytes=0-1", None], f"want the probe then one whole GET: {cdn.gets}"
    assert _on_disk()
    r = _get("bytes=0-")
    assert r.status_code == 206 and r.content == CLIP and cdn.gets == ["bytes=0-1", None], cdn.gets


def case_big_or_unknown_streams_through():
    big = b"v" * (img_api._IMG_RANGE_CACHE_MAX_BYTES + 1)
    for cdn in (_Cdn(body=big), _Cdn(sized=False)):
        _rig(cdn)
        for _ in range(2):
            r = _get("bytes=0-")
            assert r.status_code == 206 and r.headers.get("x-img-cache") == "BYPASS", (r.status_code, r.headers)
            assert r.content == cdn.body
        assert cdn.gets == ["bytes=0-", "bytes=0-"], cdn.gets
        assert not _on_disk(), "a big / unknown-size video was buffered to disk"
        r = _get("bytes=100-")
        assert r.status_code == 206 and r.content == cdn.body[100:], r.status_code
    assert admission.VIDEO_STREAM.busy == 0, "a streamed answer kept its slot"


def case_plain_get_keeps_the_photo_cap():
    body = b"p" * (3 * 1024 * 1024)
    assert img_api._IMG_CACHE_MAX_BYTES < len(body) <= img_api._IMG_RANGE_CACHE_MAX_BYTES
    cdn = _Cdn(body=body)
    _rig(cdn)
    r = _get()
    assert r.status_code == 200 and len(r.content) == len(body)
    assert not _on_disk(), "a plain GET over the 2 MB photo cap was cached"


_harness.run()
