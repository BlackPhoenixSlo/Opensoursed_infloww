#!/usr/bin/env python3
"""What skips the account's residential proxy, and what must not.

Infloww's desktop sends OF's unsigned static hosts direct (bypassRules.ts); /img
does the same, through a bare session that carries nothing of the account: a
request from the relay's own IP with the account's cookies or headers would link
the account to that IP. Everything else stays on the account's proxy: the CDN
media URLs OF signs with `AWS:SourceIp`, and the of2transcoder S3 uploads (the
relay's one IP is shared by every account, so a direct PUT would link them).

  case_s3_puts_keep_the_proxy            — single-part and multipart PUTs
  case_img_static_hosts_are_direct       — static*/public.onlyfans.com via /img,
                                           on the bare session, never the account's
  case_the_direct_session_is_bare        — no cookies kept or sent, no headers, no proxy
  case_img_signed_cdn_keeps_the_proxy    — cdn2.onlyfans.com (IP-signed) does not

OF is faked: no request leaves the process.
Run: ./venv/bin/python service/tests/test_direct_egress.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import asyncio  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

_TMP = Path(tempfile.gettempdir()) / f"direct_egress_test_{uuid.uuid4().hex}"
os.environ["IMG_CACHE_DIR"] = str(_TMP / "cache")

import curl_cffi  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402 — after _harness (DB) + the cache dir are bound
import img_api  # noqa: E402

PROXY = {"http": "http://u:p@proxy.example:8000", "https": "http://u:p@proxy.example:8000"}


def _resp(*, etag=None, body=None):
    return SimpleNamespace(ok=True, status_code=200, text="",
                           headers={"etag": f'"{etag}"'} if etag else {},
                           json=lambda: body)


class _Mime:
    def __init__(self):
        self.parts = []

    def addpart(self, *, name, data):
        self.parts.append((name, data))


class _Wire:
    """Everything upload_media sends, with the kwargs each call carried."""

    def __init__(self):
        self.puts: list[dict] = []
        self.part_proxies: list[dict] = []

    def client(self) -> of_client.OFClient:
        c = of_client.OFClient.__new__(of_client.OFClient)
        c.user_id = "4242"
        c.timeout_s = 30
        c.user_agent = "test-agent"
        c.me = lambda: {"upload": {"geoUploadArgs": {"preset": "of_beta"}}}
        c.vault_media_lookup_hash = lambda *_a, **_k: None
        c._proxy_retry = lambda fn, **_k: fn()
        c.post_json = self._post_json
        # The session the account's OF calls ride: proxied, as in production.
        c.http = SimpleNamespace(proxies=dict(PROXY), put=self._put, post=self._post)
        return c

    def _post_json(self, url, *, json_body):
        if url.endswith("/upload/signed/create"):
            s3 = f"https://of2transcoder.s3-accelerate.amazonaws.com/{json_body['key']}"
            out = {"key": json_body["key"], "uploadToken": "t"}
            if json_body["parts"] > 1:
                out.update(uploadId="U1", keys=[
                    {"part": n, "putUrl": f"{s3}?partNumber={n}&X-Amz=sig"}
                    for n in range(1, json_body["parts"] + 1)])
            else:
                out["putUrl"] = f"{s3}?X-Amz=sig"
            return out
        if url.endswith("/upload/signed/finish"):
            return {"ETag": '"assembled-2"'}
        raise AssertionError(f"unexpected POST {url}")

    def _put(self, url, **kw):
        self.puts.append({"url": url, **kw})
        return _resp(etag="etag-1")

    def _post(self, url, **kw):
        return _resp(body={"processId": "p1", "host": "convert1.onlyfans.com"})

    def part_session(self, **_k):
        wire = self

        class _PartSession:
            def __init__(self):
                self.proxies = {}

            def put(self, url, **kw):
                assert "proxies" not in kw, kw
                wire.part_proxies.append(dict(self.proxies))
                return _resp(etag="part")

            def close(self):
                pass

        return _PartSession()


def _upload(size: int) -> _Wire:
    wire = _Wire()
    saved = (curl_cffi.CurlMime, of_client.requests)
    curl_cffi.CurlMime = _Mime
    of_client.requests = SimpleNamespace(Session=wire.part_session)
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "clip.mp4"
            p.write_bytes(os.urandom(size))
            res = wire.client().upload_media(str(p))
    finally:
        curl_cffi.CurlMime, of_client.requests = saved
    assert res["ready"] is True, res
    return wire


def case_s3_puts_keep_the_proxy():
    wire = _upload(1024)
    (put,) = wire.puts
    assert put["url"].startswith("https://of2transcoder.s3-accelerate.amazonaws.com/"), put
    assert "proxies" not in put, "the PUT rides the account's proxied session"
    wire = _upload(of_client._PART_SIZE + 1024)
    assert wire.part_proxies == [PROXY, PROXY], wire.part_proxies


class _ImgResp:
    status_code = 200
    headers = {"Content-Type": "image/jpeg", "Content-Length": "3"}

    def iter_content(self, chunk_size=65536):
        yield b"abc"

    def close(self):
        pass


def _img(u: str) -> dict[str, list]:
    """GET /img?u=u with a browser that sends Range and the account header;
    returns the calls each session got."""
    seen: dict[str, list] = {"account": [], "direct": []}

    def _get(who):
        def get(url, **kw):
            seen[who].append({"url": url, **kw})
            return _ImgResp()
        return get

    account = SimpleNamespace(http=SimpleNamespace(get=_get("account"), proxies=dict(PROXY),
                                                   cookies={"sess": "acct"}, headers={"user-agent": "acct-ua"}),
                              timeout_s=30)
    saved = (server._get_client, img_api._DIRECT_HTTP)
    server._get_client = lambda *a, **k: account
    img_api._DIRECT_HTTP = SimpleNamespace(get=_get("direct"))
    try:
        req = SimpleNamespace(headers={"range": "bytes=0-", "x-account-id": "acct-1"})
        resp = img_api.proxy_image(req, u=u)

        async def _drain():   # releases the fetch slot the stream holds
            async for _ in resp.body_iterator:
                pass
        asyncio.run(_drain())
    finally:
        server._get_client, img_api._DIRECT_HTTP = saved
    return seen


def case_img_static_hosts_are_direct():
    for u in ("https://static2.onlyfans.com/static/prod/f/rev/img/logo.png",
              "https://public.onlyfans.com/files/thumbs/c144/a/b/avatar.jpg"):
        seen = _img(u)
        assert seen["account"] == [], (u, "the account's session must not fetch a direct host")
        (call,) = seen["direct"]
        # Only the browser's Range rides along: no cookie, UA, x-bc, user-id or other account header.
        assert call["headers"] == {"Range": "bytes=0-"}, call
        assert "proxies" not in call and "cookies" not in call, call


def case_the_direct_session_is_bare():
    s = img_api._DIRECT_HTTP
    assert s.discard_cookies is True, "a Set-Cookie from OF must not be kept and replayed"
    assert dict(s.cookies) == {} and dict(s.headers) == {} and not s.proxies, (s.cookies, s.headers, s.proxies)


def case_img_signed_cdn_keeps_the_proxy():
    for u in ("https://cdn2.onlyfans.com/files/t/tt/x/source.jpg?Policy=P&Signature=s&Key-Pair-Id=K",
              "https://thumbs.onlyfans.com/public/files/thumbs/c144/x.jpg",
              "https://static2.onlyfans.com.evil.example/x.png"):
        try:
            seen = _img(u)
        except server.HTTPException as e:   # not an allowed CDN host at all
            assert e.status_code == 400, (u, e)
            continue
        assert seen["direct"] == [], (u, seen)
        (call,) = seen["account"]
        assert "proxies" not in call, (u, call)


_harness.run()
