#!/usr/bin/env python3
"""Bio pages owner admin API (bio_pages/admin.py) over the real relay app: auth (401 / chatter 403 by prefix and by
handler / impersonated writes 403), tenancy (another owner's ids 404 on every route, its rows unchanged), create and
diff PATCH, links (order, cap, stock icons), atomic reorder, image uploads (size, format, EXIF, alpha, frame 0,
resize, fresh names), deletes (rows, cascades, files), 30-day stats and no destination/geo in any log line.
The public side is read through bio_pages.app over ASGI on the same temp DB and files dir.

Run: ./venv/bin/python service/tests/test_bio_admin_api.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first

import os  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

FILES = Path(tempfile.mkdtemp(prefix="bio_admin_files_"))
os.environ["BIO_FILES_DIR"] = str(FILES)
os.environ["BIO_PUBLIC_URL"] = "https://ofl.test/"
os.environ.pop("BIO_HEALTH_URL", None)

_harness.bootstrap()

import asyncio  # noqa: E402
import logging  # noqa: E402
import sqlite3  # noqa: E402
import struct  # noqa: E402
import zlib  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from io import BytesIO  # noqa: E402

import httpx  # noqa: E402
from PIL import Image  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from bio_pages import app as bio_app  # noqa: E402
from bio_pages import decide  # noqa: E402
from bio_pages import images  # noqa: E402
from bio_pages.assets import PUBLIC  # noqa: E402

IDS = fx.seed_two_agencies()
A, B = IDS["agency_a_owner"], IDS["agency_b_owner"]
owner = fx.login_owner("agency_a_owner")
other = fx.login_owner("agency_b_owner")
chatter = fx.login_chatter("chatter_a")
anon = _harness.make_client()
BASE = "/admin/bio-pages"
DEST, GEO_VAL = "https://dest.test/slopdest-admin", "slopgeo-admin"


def case_image_mode_table():
    for mode in ("RGB", "L"):
        im = Image.new(mode, (2, 1), (255, 0, 0) if mode == "RGB" else 100)
        raw = BytesIO()
        im.save(raw, "PNG", transparency=(255, 0, 0) if mode == "RGB" else 100)
        out = Image.open(BytesIO(images.encode(raw.getvalue(), images.AVATAR_SIDE))).convert("RGBA")
        assert out.getpixel((0, 0))[3] == 0, (mode, out.getpixel((0, 0)))
    im = Image.new("I;16", (1, 1))
    im.putpixel((0, 0), 32768)
    raw = BytesIO()
    im.save(raw, "PNG")
    out = Image.open(BytesIO(images.encode(raw.getvalue(), images.AVATAR_SIDE))).convert("RGB")
    assert 80 < out.getpixel((0, 0))[0] < 180, out.getpixel((0, 0))
    im = Image.new("I;16", (2, 1))
    im.putpixel((0, 0), 1000)
    im.putpixel((1, 0), 32768)
    raw = BytesIO()
    im.save(raw, "PNG", transparency=1000)
    out = Image.open(BytesIO(images.encode(raw.getvalue(), images.AVATAR_SIDE))).convert("RGBA")
    assert out.getpixel((0, 0))[3] == 0 and out.getpixel((1, 0))[3] == 255, list(out.getdata())
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    key = (1000, 2000, 3000)
    rgb16 = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 16, 2, 0, 0, 0))
             + chunk(b"tRNS", struct.pack(">HHH", *key))
             + chunk(b"IDAT", zlib.compress(b"\x00" + struct.pack(">HHHHHH", *key, 4000, 5000, 6000)))
             + chunk(b"IEND", b""))
    out = Image.open(BytesIO(images.encode(rgb16, images.AVATAR_SIDE))).convert("RGBA")
    assert [out.getpixel((x, 0))[3] for x in range(2)] == [0, 255], list(out.getdata())


class _Logs(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        try:
            self.lines.append(record.getMessage())
        except Exception:  # noqa: BLE001
            self.lines.append(str(record.msg))


LOGS = _Logs()
logging.getLogger().addHandler(LOGS)


def sql(q: str, *args):
    c = sqlite3.connect(_harness.DB_PATH)
    try:
        rows = c.execute(q, args).fetchall()
        c.commit()
        return rows
    finally:
        c.close()


def create(client, username: str, **kw):
    r = client.post(BASE, json={"username": username, "display_name": username.title(), **kw})
    assert r.status_code == 201, (r.status_code, r.text)
    return r.json()


def add_link(client, pid: str, **kw):
    body = {"title": "Link", "destination": DEST, **kw}
    r = client.post(f"{BASE}/{pid}/links", json=body)
    assert r.status_code == 201, (r.status_code, r.text)
    return r.json()


def public_json(username: str):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bio_app.app), base_url="http://localhost") as c:
            return await c.get(f"/api/profiles/{username}.json")
    return asyncio.run(go())


def bio_get(path: str, **headers):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bio_app.app), base_url="http://localhost") as c:
            return await c.get(path, headers=headers)
    return asyncio.run(go())


def upload(client, path: str, data: bytes, name="x.jpg"):
    return client.post(path, files={"file": (name, data, "application/octet-stream")})


def img(fmt: str, size=(64, 32), mode="RGB", color=(200, 10, 10), **save) -> bytes:
    out = BytesIO()
    Image.new(mode, size, color).save(out, fmt, **save)
    return out.getvalue()


def png_header(w: int, h: int) -> bytes:
    """A PNG whose IHDR claims w x h, with one tiny IDAT: Pillow reads the size without decoding."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" * 10)) + chunk(b"IEND", b""))


def served(url: str) -> Image.Image:
    r = owner.get(url)
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp", (url, r.status_code)
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable"
    return Image.open(BytesIO(r.content))


# seeded by SQL for B (the tenancy oracle) and one legacy A row whose stored code fails today's rule
B_PID, B_LID = "bbbbbbbbbbbbbb1", "bbbbbbbbbbbbbl1"
sql("INSERT INTO bio_profiles(id, owner_user_id, username, display_name, mode) VALUES (?, ?, 'bobpage', 'Bob', "
    "'direct')", B_PID, B)
sql("INSERT INTO bio_links(id, profile_id, link_id, title, destination, background_image) VALUES (?, ?, "
    "'bbbbbbbbbbk1', 'B link', 'https://b.test/x', 'backgroundImage_bbbbbbbbbb.webp')", B_LID, B_PID)
(FILES / "links" / B_LID).mkdir(parents=True)
(FILES / "links" / B_LID / "backgroundImage_bbbbbbbbbb.webp").write_bytes(img("WEBP"))


def _b_snapshot():
    return (sql("SELECT * FROM bio_profiles WHERE id = ?", B_PID), sql("SELECT * FROM bio_links WHERE profile_id = ?",
                                                                      B_PID),
            sorted(p.name for p in (FILES / "links" / B_LID).iterdir()))


# ── auth ─────────────────────────────────────────────────────────────

ROUTES = [("GET", BASE), ("POST", BASE), ("GET", f"{BASE}/stock/onlyicon.webp"),
          ("GET", f"{BASE}/files/links/{B_LID}/backgroundImage_bbbbbbbbbb.webp"),
          ("GET", f"{BASE}/{B_PID}"), ("PATCH", f"{BASE}/{B_PID}"), ("DELETE", f"{BASE}/{B_PID}"),
          ("POST", f"{BASE}/{B_PID}/avatar"), ("DELETE", f"{BASE}/{B_PID}/avatar"),
          ("POST", f"{BASE}/{B_PID}/links"), ("PUT", f"{BASE}/{B_PID}/links/order"),
          ("PATCH", f"{BASE}/{B_PID}/links/{B_LID}"), ("DELETE", f"{BASE}/{B_PID}/links/{B_LID}"),
          ("POST", f"{BASE}/{B_PID}/links/{B_LID}/background"),
          ("DELETE", f"{BASE}/{B_PID}/links/{B_LID}/background")]


def case_auth():
    before = _b_snapshot()
    for method, path in ROUTES:
        assert anon.request(method, path).status_code == 401, (method, path)
        r = chatter.request(method, path)
        assert r.status_code == 403, (method, path, r.status_code)
    # the handler refuses a chatter too, without the prefix block
    import chatters
    blocked = chatters._CHATTER_BLOCKED_ADMIN_PREFIXES
    chatters._CHATTER_BLOCKED_ADMIN_PREFIXES = tuple(p for p in blocked if p != "/admin/bio-pages")
    try:
        r = chatter.get(BASE)
        assert r.status_code == 403 and r.json()["detail"] == "bio pages are owner-only", r.text
        assert chatter.post(BASE, json={"username": "chat1", "display_name": "C"}).status_code == 403
    finally:
        chatters._CHATTER_BLOCKED_ADMIN_PREFIXES = blocked
    assert _b_snapshot() == before


def case_impersonated_reads_only():
    master = fx.login_owner("agency_master")
    r = master.post("/admin/impersonate", json={"user_id": B, "admin_password": os.environ["ADMIN_PASSWORD"]})
    assert r.status_code == 200, r.text
    r = master.get(BASE)
    assert r.status_code == 200 and [p["id"] for p in r.json()["profiles"]] == [B_PID], r.text
    assert master.get(f"{BASE}/{B_PID}").status_code == 200
    for method, path in ROUTES:
        if method != "GET":
            assert master.request(method, path, json={}).status_code == 403, (method, path)
    assert sql("SELECT display_name FROM bio_profiles WHERE id = ?", B_PID) == [("Bob",)]


# ── tenancy ──────────────────────────────────────────────────────────

def case_tenancy():
    before = _b_snapshot()
    png = img("PNG")
    for method, path in ROUTES[2:]:
        if "stock" in path:
            continue
        kw = {}
        if path.endswith(("/avatar", "/background")) and method == "POST":
            kw = {"files": {"file": ("x.png", png, "image/png")}}
        elif method in ("POST", "PATCH", "PUT"):
            kw = {"json": {"ids": [B_LID]} if path.endswith("/order") else
                  ({"title": "x", "destination": "https://x"} if path.endswith("/links") else {"title": "hijack"}
                   if "/links/" in path else {"display_name": "hijack"})}
        r = owner.request(method, path, **kw)
        assert r.status_code == 404, (method, path, r.status_code, r.text)
    assert _b_snapshot() == before

    # A's own page with B's link id
    mine = create(owner, "tenant_a")["profile"]["id"]
    for method, path in (("PATCH", f"{BASE}/{mine}/links/{B_LID}"), ("DELETE", f"{BASE}/{mine}/links/{B_LID}"),
                         ("DELETE", f"{BASE}/{mine}/links/{B_LID}/background"),
                         ("GET", f"{BASE}/files/profiles/{B_PID}/x.webp")):
        assert owner.request(method, path, **({"json": {"title": "x"}} if method == "PATCH" else {})
                             ).status_code == 404, path
    for bad in ("short", "UPPERCASEIDXXXX", "../../../etc/pa", "a" * 16):
        assert owner.get(f"{BASE}/{bad}").status_code == 404, bad
    assert _b_snapshot() == before
    listed = owner.get(BASE).json()["profiles"]
    assert B_PID not in {p["id"] for p in listed} and mine in {p["id"] for p in listed}
    r = owner.post(BASE, json={"username": "steal1", "display_name": "S", "account_id": IDS["creator_b"]})
    assert r.status_code == 403 and r.json()["detail"] == "not your account", r.text
    r = owner.patch(f"{BASE}/{mine}", json={"account_id": IDS["creator_b"]})
    assert r.status_code == 403, r.text
    assert owner.patch(f"{BASE}/{mine}", json={"account_id": IDS["creator_a"]}).json()["profile"][
        "account_id"] == IDS["creator_a"]
    assert owner.patch(f"{BASE}/{mine}", json={"account_id": None}).json()["profile"]["account_id"] is None

def case_owner_fault_reaches_read_write_and_file():
    from bio_pages import admin
    from slop.lib.bio_faults import _admin_no_owner_filter

    read = f"{BASE}/{B_PID}"
    write = f"{BASE}/{B_PID}"
    file = f"{BASE}/files/links/{B_LID}/backgroundImage_bbbbbbbbbb.webp"
    assert owner.get(read).status_code == 404
    assert owner.patch(write, json={"display_name": "Bob"}).status_code == 404
    assert owner.get(file).status_code == 404
    profile, link = admin._own_profile, admin._own_link
    try:
        _admin_no_owner_filter()
        assert owner.get(read).status_code == 200
        assert owner.patch(write, json={"display_name": "Bob"}).status_code == 200
        assert owner.get(file).status_code == 200
    finally:
        admin._own_profile, admin._own_link = profile, link


def case_failed_icon_link_removes_dir_and_cleanup_preserves_404():
    from bio_pages import files

    real_id, real_remove = files.new_id, files.remove
    lid = "failediconlink1"
    try:
        files.new_id = lambda n: lid if n == 15 else real_id(n)
        r = owner.post(f"{BASE}/{B_PID}/links", json={"title": "No", "destination": DEST, "icon": "onlyicon"})
        assert r.status_code == 404, r.text
        assert not (FILES / "links" / lid).exists()

        def bad_remove(*_args):
            raise OSError("cleanup refused")

        files.remove = bad_remove
        before = len(LOGS.lines)
        r = owner.post(f"{BASE}/{B_PID}/links", json={"title": "No", "destination": DEST, "icon": "onlyicon"})
        assert r.status_code == 404, r.text
        assert len([x for x in LOGS.lines[before:] if "file cleanup failed" in x]) == 1, LOGS.lines[before:]
    finally:
        files.new_id, files.remove = real_id, real_remove
        (FILES / "links" / lid / "onlyicon_dummy.webp").unlink(missing_ok=True)
        if (FILES / "links" / lid).exists():
            import shutil
            shutil.rmtree(FILES / "links" / lid)


def case_nonfinite_geo_and_surrogate_are_422():
    pid = create(owner, "invalid_geo")['profile']['id']
    lid = add_link(owner, pid)['links'][0]['id']
    for raw in (b'{"geo":{"US":NaN}}', b'{"geo":{"US":1e999}}'):
        r = owner.patch(f"{BASE}/{pid}/links/{lid}", content=raw, headers={"content-type": "application/json"})
        assert r.status_code == 422 and r.json()["detail"]["field"] == "geo", (raw, r.status_code, r.text)
    r = owner.patch(f"{BASE}/{pid}", content=b'{"display_name":"\\ud800"}',
                    headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.json()["detail"]["field"] == "display_name", (r.status_code, r.text)


def case_bad_health_url_is_cached_false():
    from bio_pages import admin
    old = os.environ.get("BIO_HEALTH_URL")
    cache = admin._serving_cache
    os.environ["BIO_HEALTH_URL"] = "://bad"
    admin._serving_cache = (0, True)
    try:
        async def both():
            return await asyncio.gather(admin.serving(), admin.serving())
        assert asyncio.run(both()) == [False, False]
        assert admin._serving_cache[1] is False
    finally:
        admin._serving_cache = cache
        if old is None:
            os.environ.pop("BIO_HEALTH_URL", None)
        else:
            os.environ["BIO_HEALTH_URL"] = old


# ── create / patch ───────────────────────────────────────────────────

def case_create_and_patch():
    p = create(owner, "  Alice_Page ")
    prof = p["profile"]
    assert prof["username"] == "alice_page" and prof["mode"] == "escape_ig" and p["links"] == []
    assert prof["public_url"] == "https://ofl.test/alice_page" and prof["verified"] is False
    assert decide.RECORD_ID.fullmatch(prof["id"])
    r = owner.post(BASE, json={"username": "ALICE_PAGE", "display_name": "x"})
    assert r.status_code == 409 and r.json()["detail"] == {"field": "username", "msg": "That username is taken."}
    r = other.post(BASE, json={"username": "alice_page", "display_name": "x"})
    assert r.status_code == 409, "usernames are global"
    r = owner.post(BASE, json={"username": "api", "display_name": "x"})
    assert r.status_code == 422 and r.json()["detail"]["msg"] == "That username is reserved."
    r = owner.post(BASE, json={"username": "abc", "display_name": "x", "verified": True})
    assert r.status_code == 422 and r.json()["detail"] == {"field": "verified", "msg": "verified can't be set here"}
    assert owner.post(BASE, content=b"[1]", headers={"content-type": "application/json"}).status_code == 422
    assert owner.post(BASE, content=b"{", headers={"content-type": "application/json"}).status_code == 422
    pid = prof["id"]
    r = owner.patch(f"{BASE}/{pid}", json={"bio": "hi", "verified": True, "mode": "direct"})
    got = r.json()["profile"]
    assert (got["bio"], got["verified"], got["mode"], got["display_name"]) == ("hi", True, "direct", "Alice_Page")
    assert owner.patch(f"{BASE}/{pid}", json={"username": "x"}).status_code == 422
    # legacy value (20-digit code) survives an unrelated PATCH
    lk = add_link(owner, pid)["links"][0]
    sql("UPDATE bio_links SET default_tracking_code = '12345678901234567890' WHERE id = ?", lk["id"])
    r = owner.patch(f"{BASE}/{pid}/links/{lk['id']}", json={"title": "Renamed"})
    assert r.status_code == 200 and r.json()["links"][0]["default_tracking_code"] == "12345678901234567890"
    r = owner.patch(f"{BASE}/{pid}/links/{lk['id']}", json={"default_tracking_code": "12345678901234567890"})
    assert r.status_code == 422 and r.json()["detail"]["field"] == "default_tracking_code"
    pj = public_json("alice_page").json()
    assert pj["profile"]["displayName"] == "Alice_Page" and pj["profile"]["verified"] is True
    assert pj["links"][0]["title"] == "Renamed"


# ── links ────────────────────────────────────────────────────────────

def case_links_order_cap_and_icons():
    pid = create(owner, "links_page")["profile"]["id"]
    ids = []
    for i in range(3):
        page = add_link(owner, pid, title=f"L{i}", geo={"US": GEO_VAL}, tracking=True)
        ids.append(page["links"][-1]["id"])
        assert [lk["sort_order"] for lk in page["links"]] == list(range(i + 1))
    assert page["links"][0]["geo"] == {"US": GEO_VAL}
    page = add_link(owner, pid, title="Icon", icon="onlyicon")
    lk = page["links"][-1]
    assert lk["icon_stock"] == "onlyicon" and lk["icon"].startswith("onlyicon_") and lk["icon_url"]
    stored = FILES / "links" / lk["id"] / lk["icon"]
    assert stored.read_bytes() == (PUBLIC / "images" / "onlyicon.webp").read_bytes()
    assert owner.get(lk["icon_url"]).content == stored.read_bytes()
    page = owner.patch(f"{BASE}/{pid}/links/{lk['id']}", json={"icon": "igicon"}).json()
    lk2 = page["links"][-1]
    assert lk2["icon_stock"] == "igicon" and not stored.exists()
    page = owner.patch(f"{BASE}/{pid}/links/{lk['id']}", json={"icon": None}).json()
    assert page["links"][-1]["icon"] == "" and page["links"][-1]["icon_stock"] is None
    assert not (FILES / "links" / lk["id"] / lk2["icon"]).exists()
    pub = public_json("links_page").json()["links"]
    assert [x["title"] for x in pub] == ["L0", "L1", "L2", "Icon"] and pub[-1]["icon"] == ""
    # stock route
    r = owner.get(f"{BASE}/stock/twitchicon.webp")
    assert r.status_code == 200 and r.content == (PUBLIC / "images" / "twitchicon.webp").read_bytes()
    for bad in ("nope.webp", "onlyicon.png", "..%2Fonlyicon.webp"):
        assert owner.get(f"{BASE}/stock/{bad}").status_code == 404, bad
    # cap
    con = sqlite3.connect(_harness.DB_PATH)
    con.executemany("INSERT INTO bio_links(id, profile_id, link_id, title, destination, sort_order) "
                    "VALUES (?, ?, ?, 't', 'https://x', ?)",
                    [(f"cap{i:012d}", pid, f"c{i:011d}", 100 + i) for i in range(decide.MAX_LINKS - 4)])
    con.commit()
    con.close()
    r = owner.post(f"{BASE}/{pid}/links", json={"title": "one too many", "destination": "https://x"})
    assert r.status_code == 409, r.text
    assert sql("SELECT COUNT(*) FROM bio_links WHERE profile_id = ?", pid) == [(decide.MAX_LINKS,)]


def case_reorder():
    pid = create(owner, "order_page")["profile"]["id"]
    for i in range(4):
        page = add_link(owner, pid, title=f"T{i}")
    ids = [lk["id"] for lk in page["links"]]
    want = [ids[2], ids[0], ids[3], ids[1]]
    r = owner.put(f"{BASE}/{pid}/links/order", json={"ids": want})
    assert r.status_code == 200 and [lk["id"] for lk in r.json()["links"]] == want, r.text
    assert [x["title"] for x in public_json("order_page").json()["links"]] == ["T2", "T0", "T3", "T1"]
    for bad in (want[:3], want + [B_LID], [want[0]] * 4, want[:3] + [want[0]], want + ["x" * 15]):
        r = owner.put(f"{BASE}/{pid}/links/order", json={"ids": bad})
        assert r.status_code == 409 and r.json()["detail"] == "the links changed: reload", (bad, r.text)
    for bad in ({"ids": "x"}, {"ids": [1]}, {}):
        assert owner.put(f"{BASE}/{pid}/links/order", json=bad).status_code == 422, bad
    assert [lk["id"] for lk in owner.get(f"{BASE}/{pid}").json()["links"]] == want


# ── uploads ──────────────────────────────────────────────────────────

def case_uploads():
    page = create(owner, "upload_page")
    pid = page["profile"]["id"]
    lid = add_link(owner, pid)["links"][0]["id"]
    av = f"{BASE}/{pid}/avatar"
    bg = f"{BASE}/{pid}/links/{lid}/background"
    # no content-length (chunked) → 411
    r = owner.post(av, content=iter([b"--x\r\n"]), headers={"content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 411, r.status_code
    big = b"\xff\xd8" + b"\x00" * (21 * 1024 * 1024)
    assert upload(owner, av, big).status_code == 413
    for bad, name in ((b"hello, not an image", "a.txt"), (b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic", "a.heic"),
                      (img("JPEG")[:200], "trunc.jpg"), (png_header(10_000, 10_000), "huge.png")):
        r = upload(owner, av, bad, name)
        assert r.status_code == 415 and r.json()["detail"] == "Pick a JPG, PNG, GIF or WebP image.", (name, r.text)
    assert owner.post(av, files={"other": ("x", b"x")}).status_code == 422
    # EXIF orientation 6 (rotate 90 CW): stored 300x100 → upright 100x300, no EXIF out
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x010F] = "SlopCam"
    raw = BytesIO()
    Image.new("RGB", (300, 100), (0, 200, 0)).save(raw, "JPEG", exif=exif.tobytes())
    page = upload(owner, av, raw.getvalue()).json()
    name1 = page["profile"]["avatar"]
    assert name1.startswith("avatar_") and name1.endswith(".webp")
    im = served(page["profile"]["avatar_url"])
    assert im.size == (100, 300), im.size
    assert not im.getexif() and "exif" not in im.info and "icc_profile" not in im.info
    # a new name each time; old file gone; public bio app serves it immutable
    page = upload(owner, av, img("PNG", (3000, 1500), "RGBA", (0, 0, 255, 0))).json()
    name2 = page["profile"]["avatar"]
    assert name2 != name1 and not (FILES / "profiles" / pid / name1).exists()
    im = served(page["profile"]["avatar_url"])
    assert im.size == (512, 256) and im.mode == "RGBA" and im.getpixel((5, 5))[3] == 0, (im.size, im.mode)
    r = bio_get(f"/api/files/profiles/{pid}/{name2}")
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert public_json("upload_page").json()["profile"]["avatarUrl"] == f"/api/files/profiles/{pid}/{name2}"
    # GIF → frame 0; background 1080 max side
    frames = [Image.new("RGB", (2000, 3000), c) for c in ((255, 0, 0), (0, 0, 255))]
    gif = BytesIO()
    frames[0].save(gif, "GIF", save_all=True, append_images=frames[1:])
    page = upload(owner, bg, gif.getvalue(), "a.gif").json()
    im = served(page["links"][0]["background_url"])
    assert im.size == (720, 1080) and im.convert("RGB").getpixel((10, 10))[0] > 200, (im.size,)
    # removes
    page = owner.delete(av).json()
    assert page["profile"]["avatar"] == "" and not (FILES / "profiles" / pid / name2).exists()
    bg_name = page["links"][0]["background_image"]
    page = owner.delete(bg).json()
    assert page["links"][0]["background_image"] == "" and not (FILES / "links" / lid / bg_name).exists()
    assert owner.delete(av).status_code == 200, "removing nothing is fine"


# ── delete ───────────────────────────────────────────────────────────

def case_deletes():
    page = create(owner, "doomed")
    pid = page["profile"]["id"]
    page = add_link(owner, pid, icon="linkicon")
    page = add_link(owner, pid, title="Two")
    lid1, lid2 = (lk["id"] for lk in page["links"])
    key2 = page["links"][1]["link_id"]
    upload(owner, f"{BASE}/{pid}/avatar", img("PNG"))
    sql("INSERT INTO bio_custom_domains(id, profile_id, domain, status) VALUES ('cd1', ?, 'doomed.test', 'live')", pid)
    sql("INSERT INTO bio_daily(day, profile_id, link_id, country, in_app, code, views, clicks) VALUES "
        "('2026-11-01', ?, '', 'US', '', '', 5, 0), ('2026-11-01', ?, ?, 'US', '', '', 0, 3)", pid, pid, lid2)
    assert owner.get(f"{BASE}/{pid}").json()["profile"]["public_url"] == "https://doomed.test/"
    # link delete: row + dir gone, its bio_daily rows stay, Reveal 404
    page = owner.delete(f"{BASE}/{pid}/links/{lid2}").json()
    assert [lk["id"] for lk in page["links"]] == [lid1] and not (FILES / "links" / lid2).exists()
    assert sql("SELECT clicks FROM bio_daily WHERE link_id = ?", lid2) == [(3,)]
    assert bio_get(f"/.netlify/functions/reveal?id={key2}", **{"sec-fetch-site": "same-origin"}).status_code == 404
    assert owner.delete(f"{BASE}/{pid}/links/{lid2}").status_code == 404
    # profile delete: links, domain, bio_daily gone (FK), dirs gone, username free
    assert (FILES / "links" / lid1).exists() and (FILES / "profiles" / pid).exists()
    r = owner.delete(f"{BASE}/{pid}")
    assert r.status_code == 204 and r.content == b""
    for table, col in (("bio_profiles", "id"), ("bio_links", "profile_id"), ("bio_custom_domains", "profile_id"),
                       ("bio_daily", "profile_id")):
        assert sql(f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", pid) == [(0,)], table
    assert not (FILES / "links" / lid1).exists() and not (FILES / "profiles" / pid).exists()
    assert owner.get(f"{BASE}/{pid}").status_code == 404 and public_json("doomed").status_code == 404
    assert create(owner, "doomed")["profile"]["id"] != pid


# ── stats ────────────────────────────────────────────────────────────

def case_stats_30_days():
    pid = create(owner, "stats_page")["profile"]["id"]
    today = datetime.now(timezone.utc).date()
    rows = []
    for back in range(31):
        day = (today - timedelta(days=back)).isoformat()
        rows.append((day, pid, "", "US", "", "", back + 1, 0))
        rows.append((day, pid, "l" * 15, "DE", "instagram", "7", 0, 2))
    con = sqlite3.connect(_harness.DB_PATH)
    con.executemany("INSERT INTO bio_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()
    body = owner.get(BASE).json()
    assert body["public_base"] == "https://ofl.test" and body["serving"] is False
    row = next(p for p in body["profiles"] if p["id"] == pid)
    assert (row["views_30d"], row["clicks_30d"]) == (sum(range(1, 31)), 60), row
    assert body["profiles"][0]["id"] == pid, "updated_at DESC"
    assert row["link_count"] == 0 and row["public_url"] == "https://ofl.test/stats_page"


def case_no_destination_or_geo_in_logs():
    hits = [ln for ln in LOGS.lines if "slopdest" in ln or GEO_VAL in ln]
    assert not hits, hits[:3]



_harness.run()
