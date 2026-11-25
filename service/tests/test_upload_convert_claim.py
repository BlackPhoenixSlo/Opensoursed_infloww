#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import curl_cffi  # noqa: E402
from starlette.datastructures import Headers, UploadFile  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402
import vault_cache  # noqa: E402

TOKEN = "tok3n+/="
GEO = {"preset": "of_beta", "protected_preset": "of_drm", "preset_public": "of_public",
       "preset_png": "of_png", "isDelay": True, "needThumbs": True,
       "additional": {"user": "4242"}}
CLAIM = {"processId": "p1", "host": "convert1.onlyfans.com", "extra": "x",
         "thumbs": [{"id": 1}]}


class _Mime:

    def __init__(self):
        self.parts = []

    def addpart(self, *, name, data):
        self.parts.append((name, data))


def _resp(*, etag=None, body=None, status=200):
    return SimpleNamespace(ok=200 <= status < 300, status_code=status, text="",
                           headers={"etag": f'"{etag}"'} if etag else {},
                           json=lambda: body)


def _server_key(our_key: str) -> str:
    # OF splices the creator id in after `upload/`
    return our_key.replace("upload/", "upload/4242/", 1)


class _Fake:

    def __init__(self, *, convert_fails: list | None = None):
        self.convert_bodies: list[list] = []
        self.json_posts: list[tuple] = []
        self.convert_fails = list(convert_fails or [])

    def client(self) -> of_client.OFClient:
        c = of_client.OFClient.__new__(of_client.OFClient)
        c.user_id = "4242"
        c.timeout_s = 30
        c.user_agent = "test-agent"
        c.me = lambda: {"upload": {"geoUploadArgs": dict(GEO)}}
        c.vault_media_lookup_hash = lambda *_a, **_k: None
        c._proxy_retry = lambda fn, **_k: fn()
        c.post_json = self._post_json
        c.http = SimpleNamespace(proxies={}, put=self._put, post=self._convert_post)
        return c

    def _post_json(self, url, *, json_body):
        self.json_posts.append((url, dict(json_body)))
        if url.endswith("/upload/signed/create"):
            key = _server_key(json_body["key"])
            s3 = f"https://of2transcoder.s3-accelerate.amazonaws.com/{key}"
            out = {"key": key, "getUrl": f"https://upload.onlyfans.com/{key[7:]}",  # getUrl is upload.onlyfans.com now: Location comes from part 1's putUrl, never getUrl
                   "uploadToken": TOKEN}
            if json_body["parts"] > 1:
                out.update(uploadId="U1", keys=[
                    {"part": n, "putUrl": f"{s3}?partNumber={n}&uploadId=U1&X-Amz=sig"}
                    for n in range(1, json_body["parts"] + 1)])
            else:
                out["putUrl"] = f"{s3}?X-Amz=sig"
            return out
        if url.endswith("/upload/signed/finish"):
            return {"ETag": '"assembled-2"'}
        raise AssertionError(f"unexpected POST {url}")

    def _put(self, url, **_k):
        return _resp(etag="etag-1")

    def _convert_post(self, url, *, multipart, **_k):
        assert url == "https://convert.onlyfans.com/file/upload", url
        self.convert_bodies.append(multipart.parts)
        if self.convert_fails:
            raise self.convert_fails.pop(0)
        return _resp(body=dict(CLAIM))


class _PartSession:
    def __init__(self, **_k):
        self.proxies = {}

    def put(self, url, **_k):
        return _resp(etag=f"part-{url.split('partNumber=')[1].split('&')[0]}")

    def close(self):
        pass


def _with_fakes(fn):
    saved = (curl_cffi.CurlMime, of_client.requests)
    curl_cffi.CurlMime = _Mime
    of_client.requests = SimpleNamespace(Session=_PartSession)
    try:
        return fn()
    finally:
        curl_cffi.CurlMime, of_client.requests = saved


async def _no_invalidate(_aid):
    return 0


vault_cache.invalidate = _no_invalidate


def _chat_body(name: str, data: bytes, ct: str) -> list:
    fake = _Fake()
    server._get_client = lambda *a, **k: fake.client()
    f = UploadFile(io.BytesIO(data), filename=name, headers=Headers({"content-type": ct}))
    res = _with_fakes(lambda: asyncio.run(server.of_upload_media(f)))
    assert res["ready"] is True, res
    assert res["send_with"] == [{"processId": "p1", "host": "convert1.onlyfans.com",
                                 "name": name, "extra": "x", "thumbId": 1}], res
    (body,) = fake.convert_bodies
    return body


def _vault_body(name: str, data: bytes) -> list:
    fake = _Fake()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / name
        p.write_bytes(data)
        res = _with_fakes(lambda: fake.client().upload_claim(str(p)))
    assert res.media, res
    (body,) = fake.convert_bodies
    return body


def _normalised(body: list) -> list:
    out = []
    for name, value in body:
        if name in ("file[Key]", "file[Location]"):
            head, _, tail = value.partition("upload/4242/")
            value = head + "upload/4242/<id>/" + tail.split("/", 2)[2]
        out.append((name, value))
    return out


def _expected(name: str, etag: str) -> list:
    loc = "https://of2transcoder.s3-accelerate.amazonaws.com/upload/4242/<id>/" + name
    return [
        ("preset", "of_beta"), ("protected_preset", "of_drm"),
        ("preset_public", "of_public"), ("preset_png", "of_png"),
        ("isDelay", "true"), ("needThumbs", "true"), ("additional[user]", "4242"),
        ("file[ETag]", f'"{etag}"'), ("file[Location]", loc),
        ("file[Key]", "upload/4242/<id>/" + name), ("file[Bucket]", "of2transcoder"),
        ("file[name]", name), ("file[uploadToken]", TOKEN), ("file[secure]", "false"),
    ]


def _assert_same(name: str, data: bytes, ct: str, etag: str):
    chat = _normalised(_chat_body(name, data, ct))
    vault = _normalised(_vault_body(name, data))
    assert chat == vault, f"chat and vault claims differ:\n{chat}\n{vault}"
    assert chat == _expected(name, etag), chat


def case_image_chat_and_vault_send_the_same_claim():
    _assert_same("photo.png", b"\x89PNG fake image bytes", "image/png", "etag-1")


def case_video_chat_and_vault_send_the_same_claim():
    _assert_same("clip.mp4", b"fake mp4 bytes" * 100, "video/mp4", "etag-1")


def case_multipart_video_chat_and_vault_send_the_same_claim():
    data = os.urandom(of_client._PART_SIZE + 1024)
    _assert_same("long.mp4", data, "video/mp4", "assembled-2")


def case_claim_retry_sends_the_same_claim():
    fake = _Fake(convert_fails=[RuntimeError("Operation timed out"),
                                RuntimeError("Operation timed out")])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "photo.png"
        p.write_bytes(b"\x89PNG retry bytes")
        res = _with_fakes(lambda: fake.client().upload_claim(
            str(p), claim_retry_delays=(0,)))
    assert res.media and res.retries == 1, res
    first, timeout_retry, ladder_retry = fake.convert_bodies
    assert first == timeout_retry == ladder_retry, fake.convert_bodies
    assert _normalised(first) == _expected("photo.png", "etag-1"), first


def case_signed_create_and_finish_carry_user_prefix():
    fake = _Fake()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "long.mp4"
        p.write_bytes(os.urandom(of_client._PART_SIZE + 1))
        _with_fakes(lambda: fake.client().upload_media(str(p)))
    (create_url, create), (finish_url, finish) = fake.json_posts
    assert create_url.endswith("/upload/signed/create") and create["userPrefix"] == "upload", create
    assert finish_url.endswith("/upload/signed/finish") and finish["userPrefix"] == "upload", finish
    assert finish["key"] == _server_key(create["key"]), (create, finish)


_harness.run()
