#!/usr/bin/env python3
"""A vault url signed for the account's OLD proxy IP (or expired), re-signed by media id — `cdn_resign`, behind
`/img` and `/img/scrub` when the caller names the media. Plain-assert, no pytest (repo convention).

Why: OF signs CDN urls with `AWS:SourceIp` = the egress that listed them. After a proxy rebind every url the
mirror / vault cache / browser holds 403s through the account's new proxy. Measured on AE 2026-11-06: 108/108
`/img/scrub` 502 for a Creator moved twice that day.

  case_img_stale_url_resigns_once     — 403 -> one by-id read -> retry with the fresh url of the same file, 200;
                                        the next request with the same stale url goes straight to the fresh one.
  case_img_without_media_id_is_as_before — no media id: the 403 passes through, OF is never asked.
  case_fresh_url_must_be_the_same_file — a fresh payload without that host+path hands nothing back, and the
                                        failure is remembered (no OF call per frame).
  case_fresh_url_that_still_403s_is_remembered — re-signed but still 403: remembered as failed, the url forgotten;
                                        the next /img and scrub make no OF call, every response closed.
  case_scrub_download_resigns          — the storyboard download (a sync route's worker thread) does the same.
  case_herd_shares_one_read            — 12 concurrent frames / posters of one media: one by-id read.

OF is faked: no request leaves the process.
Run: ./venv/bin/python service/tests/test_cdn_resign.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import asyncio  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

_TMP = Path(tempfile.gettempdir()) / f"cdn_resign_test_{uuid.uuid4().hex}"
os.environ["IMG_CACHE_DIR"] = str(_TMP / "cache")
os.environ["STORYBOARD_DIR"] = str(_TMP / "storyboard")

import anyio  # noqa: E402
import anyio.to_thread  # noqa: E402

import cdn_resign  # noqa: E402
import img_api  # noqa: E402
import server  # noqa: E402 — after _harness (DB) + the dirs are bound
import storyboard  # noqa: E402

_harness.bootstrap()

FILE = "https://cdn2.onlyfans.com/files/v/ab/clip_240p.mp4"
STALE = f"{FILE}?Tag=2&Policy=old-ip&Signature=s&Key-Pair-Id=K"
FRESH = f"{FILE}?Tag=2&Policy=new-ip&Signature=s2&Key-Pair-Id=K"
MID = 4591793430


class _Resp:
    def __init__(self, status: int):
        self.status_code = status
        self.headers = {"Content-Type": "video/mp4", "Content-Length": "3"}
        self.closed = False

    def iter_content(self, chunk_size=65536):
        yield b"mp4"

    def close(self):
        self.closed = True


class _Client:
    """The account's client on its NEW proxy: the CDN answers only urls signed for it (`new-ip`)."""

    def __init__(self, fresh_media: dict | None):
        self.account_id = "acct-1"
        self.timeout_s = 5
        self.gets: list[str] = []
        self.resps: list[_Resp] = []
        self.byid: list[int] = []
        self.fresh_media = fresh_media
        self.lock = threading.Lock()

        def get(url, **_kw):
            r = _Resp(200 if "Policy=new-ip" in url else 403)
            with self.lock:
                self.gets.append(url)
                self.resps.append(r)
            return r
        self.http = SimpleNamespace(get=get)

    def vault_media_by_id(self, media_id: int) -> dict:
        time.sleep(0.05)  # a real OF round trip: concurrent callers overlap
        with self.lock:
            self.byid.append(int(media_id))
        return self.fresh_media


def _media(url: str) -> dict:
    return {"id": MID, "type": "video", "videoSources": {"240": url, "720": None},
            "files": {"full": {"url": url.replace("_240p", "_720p")}}}


def _reset(client: _Client) -> None:
    shutil.rmtree(_TMP / "cache", ignore_errors=True)   # /img's disk cache would answer before the CDN
    cdn_resign._fresh.clear()
    cdn_resign._failed.clear()
    server._get_client = lambda *a, **k: client


def _img(u: str, media_id: int | None, range_: str | None = None) -> int:
    """GET /img; with `range_` as a <video> seeking."""
    req = SimpleNamespace(headers={"range": range_} if range_ else {})

    async def _fetch() -> int:
        try:
            resp = await img_api.proxy_image(req, u=u, media_id=media_id)
        except server.HTTPException as e:
            return e.status_code
        if hasattr(resp, "body_iterator"):   # a FileResponse (a small Range answer, off disk) has none
            async for _ in resp.body_iterator:   # draining releases the lane slot
                pass
        return resp.status_code
    return asyncio.run(_fetch())


def case_img_stale_url_resigns_once():
    c = _Client(_media(FRESH))
    _reset(c)
    assert _img(STALE, MID) == 200
    assert c.gets == [STALE, FRESH], c.gets
    assert c.byid == [MID], c.byid
    c.gets.clear()
    shutil.rmtree(_TMP / "cache", ignore_errors=True)   # else the next range is a disk hit, upstream untouched
    # The next <video> range with the browser's stale url: no 403 round trip, no OF call.
    assert _img(STALE, MID, "bytes=100-") == 200
    assert c.gets == [FRESH], c.gets
    assert c.byid == [MID], c.byid


def case_img_without_media_id_is_as_before():
    c = _Client(_media(FRESH))
    _reset(c)
    assert _img(STALE, None) == 403
    assert c.gets == [STALE] and c.byid == [], (c.gets, c.byid)


def case_fresh_url_must_be_the_same_file():
    c = _Client(_media("https://cdn2.onlyfans.com/files/v/zz/other_240p.mp4?Policy=new-ip&Signature=x&Key-Pair-Id=K"))
    _reset(c)
    assert _img(STALE, MID) == 403
    assert c.byid == [MID] and c.gets == [STALE], (c.byid, c.gets)
    assert _img(STALE, MID) == 403
    assert c.byid == [MID], "a failed re-sign is remembered, not retried per request"
    assert c.gets == [STALE, STALE], c.gets


def case_fresh_url_that_still_403s_is_remembered():
    """OF re-signs the file, but the CDN still refuses the fresh url (signed for another egress): without the
    negative cache every frame would pay one by-id read + two CDN GETs for the next hour."""
    still = f"{FILE}?Tag=2&Policy=other-ip&Signature=s3&Key-Pair-Id=K"
    c = _Client(_media(still))
    _reset(c)
    assert _img(STALE, MID) == 403
    assert c.gets == [STALE, still] and c.byid == [MID], (c.gets, c.byid)
    assert cdn_resign.current("acct-1", STALE) == STALE, "the still-refused url is used up front"
    assert _img(STALE, MID) == 403
    assert c.byid == [MID], "a re-sign whose retry still 403s is retried per request"
    assert c.gets == [STALE, still, STALE], c.gets
    src = _TMP / "dl" / "still.tmp"
    src.parent.mkdir(parents=True, exist_ok=True)

    async def scrub() -> bool:
        return await anyio.to_thread.run_sync(
            lambda: storyboard._storyboard_download(SimpleNamespace(headers={}), STALE, src, None, MID))
    assert anyio.run(scrub) is False
    assert c.byid == [MID], c.byid
    assert all(r.closed for r in c.resps), "an upstream response was left open"


def case_scrub_download_resigns():
    c = _Client(_media(FRESH))
    _reset(c)
    dest = _TMP / "dl"
    dest.mkdir(parents=True, exist_ok=True)
    src = dest / "source.tmp"

    async def main() -> bool:
        return await anyio.to_thread.run_sync(
            lambda: storyboard._storyboard_download(SimpleNamespace(headers={}), STALE, src, None, MID))
    assert anyio.run(main) is True
    assert src.read_bytes() == b"mp4"
    assert c.gets == [STALE, FRESH] and c.byid == [MID], (c.gets, c.byid)
    # Without the media id the download fails as before (the 502 path), OF untouched.
    c2 = _Client(_media(FRESH))
    _reset(c2)

    async def bare() -> bool:
        return await anyio.to_thread.run_sync(
            lambda: storyboard._storyboard_download(SimpleNamespace(headers={}), STALE, src, None))
    assert anyio.run(bare) is False
    assert c2.byid == [], c2.byid


def case_herd_shares_one_read():
    c = _Client(_media(FRESH))
    _reset(c)

    async def herd() -> list:
        return await asyncio.gather(*(cdn_resign.resign("acct-1", MID, STALE, c) for _ in range(12)))
    got = asyncio.run(herd())
    assert got == [FRESH] * 12, got
    assert c.byid == [MID], c.byid


_harness.run()
