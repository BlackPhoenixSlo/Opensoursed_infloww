#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds a throwaway temp DB (unset env falls back to PROD)

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
import of_pacing  # noqa: E402
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


# OF signs CDN urls for the egress IP that listed them (AWS:SourceIp); after a proxy rebind older urls 403
class _Client:

    def __init__(self, fresh_media: dict | None):
        self.account_id = "acct-1"
        self.timeout_s = 5
        self.gets: list[str] = []
        self.resps: list[_Resp] = []
        self.byid: list[int] = []
        self.walks: list[str | None] = []
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
        # a real OF round trip: concurrent callers overlap
        time.sleep(0.05)
        with self.lock:
            self.byid.append(int(media_id))
            self.walks.append(getattr(of_pacing._WALK.get(), "kind", None))
        return self.fresh_media


def _media(url: str) -> dict:
    return {"id": MID, "type": "video", "videoSources": {"240": url, "720": None},
            "files": {"full": {"url": url.replace("_240p", "_720p")}}}


def _reset(client: _Client) -> None:
    # /img's disk cache would answer before the CDN
    shutil.rmtree(_TMP / "cache", ignore_errors=True)
    cdn_resign._fresh.clear()
    cdn_resign._failed.clear()
    server._get_client = lambda *a, **k: client


def _img(u: str, media_id: int | None, range_: str | None = None) -> int:
    req = SimpleNamespace(headers={"range": range_} if range_ else {})

    async def _fetch() -> int:
        try:
            resp = await img_api.proxy_image(req, u=u, media_id=media_id)
        except server.HTTPException as e:
            return e.status_code
        if hasattr(resp, "body_iterator"):
            async for _ in resp.body_iterator:
                pass
        return resp.status_code
    return asyncio.run(_fetch())


def case_img_stale_url_resigns_once():
    c = _Client(_media(FRESH))
    _reset(c)
    assert _img(STALE, MID) == 200
    assert c.gets == [STALE, FRESH], c.gets
    assert c.byid == [MID], c.byid
    assert c.walks == ["img_resign"], ("the re-sign's OF read is paced on the Creator", c.walks)
    c.gets.clear()
    shutil.rmtree(_TMP / "cache", ignore_errors=True)
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
        return await asyncio.gather(*(cdn_resign.resign("acct-1", MID, STALE, c, "t") for _ in range(12)))
    got = asyncio.run(herd())
    assert got == [FRESH] * 12, got
    assert c.byid == [MID], c.byid


_harness.run()
