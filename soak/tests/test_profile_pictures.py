"""FakeOF's profile pictures (ticket 67): the account starts with a seeded cover whose /cdn bytes are fixed, and a cover
saved from an upload (storage PUT, convert claim, PATCH /users/me {header: item}) reads back under a new URL, as OF
does (ticket 67 follow-up, measured live 2026-11-21): late (the previous cover keeps showing for `STALE_S` seconds)
and re-encoded (other bytes, the same picture), so the cover proof's undo must wait and compare pixels, not sha256."""
import io
import time
from urllib.parse import urlsplit

import _path  # noqa: F401
from PIL import Image
from starlette.testclient import TestClient

from soak.fake_of import settings
from soak.fake_of.app import FakeOF
from soak.fake_of.signing import sign_value
from soak.world import World


def _pixels(data: bytes):
    im = Image.open(io.BytesIO(data))
    return im.size, im.convert("RGB").tobytes()


def test_saved_cover_reads_back_late_and_re_encoded() -> None:
    fake = FakeOF(World(seed=1))
    client = TestClient(fake.build())
    now, clock = [1000.0], settings._clock
    settings._clock = lambda: now[0]

    def call(method: str, path_qs: str, body=None):
        t = str(int(time.time() * 1000))
        uid = str(fake.world.creator_id)
        h = {"user-id": uid, "x-hash": fake.x_hash, "time": t,
             "sign": sign_value(fake.rules, time_ms=t, path_qs=path_qs, user_id=uid)}
        r = client.request(method, path_qs, headers=h, json=body)
        assert r.status_code == 200, (method, path_qs, r.status_code, r.text[:200])
        return r.json()

    def cdn(url: str) -> bytes:
        r = client.get("/cdn" + urlsplit(url).path)
        assert r.status_code == 200, (url, r.status_code)
        return r.content

    def save(data: bytes, name: str) -> str:
        signed = call("POST", "/api2/v2/upload/signed/create",
                      {"key": f"upload/u-{name}/1/{name}.png", "parts": 1, "contentType": "image/png"})
        put = client.put(urlsplit(signed["putUrl"]).path, content=data)
        assert put.status_code == 200
        item = client.post("/file/upload", data={"file[Key]": signed["key"], "file[uploadToken]": signed["uploadToken"],
                                                 "file[ETag]": put.headers["ETag"]}).json()
        return call("PATCH", "/api2/v2/users/me", {"header": item})["header"]

    def header() -> str:
        return call("GET", "/api2/v2/users/me")["header"]

    try:
        prior = header()
        assert prior == settings.picture_url(settings.PRIOR_COVER) and cdn(prior) == settings.PRIOR_COVER_PNG
        one, two = settings.vault._png(4), settings.PRIOR_COVER_PNG   # intact: FakeOF refuses a corrupt PNG, as OF does
        assert save(one, "a") == prior and header() == prior   # applied late: the previous cover still shows
        now[0] += settings.STALE_S
        first = header()
        assert first != prior and cdn(first) != one and _pixels(cdn(first)) == _pixels(one)   # re-encoded
        assert settings.posts.png_intact(cdn(first))
        assert save(two, "b") == first
        now[0] += settings.STALE_S - 0.5
        assert header() == first   # still stale
        now[0] += 0.5
        again = header()
        assert again not in (prior, first) and cdn(again) != two and _pixels(cdn(again)) == _pixels(two)
        assert client.get("/cdn/files/soak/profile/soak-process-99.png").status_code == 404
        call("PATCH", "/api2/v2/users/me", {"header": ""})
        assert header() is None   # a remove is not delayed
    finally:
        settings._clock = clock


def test_re_encode_keeps_a_jpeg_picture() -> None:
    out = io.BytesIO()
    Image.linear_gradient("L").resize((16, 9)).save(out, "JPEG")
    jpeg = out.getvalue()
    assert settings.reencode(jpeg) != jpeg and _pixels(settings.reencode(jpeg)) == _pixels(jpeg)
    assert settings.reencode(b"GIF89a") == b"GIF89a"


def main() -> int:
    test_saved_cover_reads_back_late_and_re_encoded()
    test_re_encode_keeps_a_jpeg_picture()
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
