#!/usr/bin/env python3
"""Bio pages owner admin API (bio_pages/admin.py) over the real relay app: auth (401 / chatter 403 by prefix and by
handler / impersonated writes 403), tenancy (another owner's ids 404 on every route, its rows unchanged), create and
diff PATCH, links (order, cap, stock icons), atomic reorder, image uploads (size, format, EXIF, alpha, frame 0,
resize, fresh names), deletes (rows, cascades, files), 30-day stats and no destination/geo in any log line; create
with a Creator (OnlyFans name + an "OnlyFans" link from the cached users_me), the vault avatar (photo only, owned
page), the request-derived public base when BIO_PUBLIC_URL is unset and `short_url` from BIO_SHORT_URL.
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
os.environ.pop("BIO_SHORT_URL", None)
os.environ["BIO_SERVER_IP"] = "203.0.113.7"
os.environ.pop("BIO_PRIMARY_HOSTS", None)

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
from bio_pages import admin as bio_admin  # noqa: E402
from bio_pages import app as bio_app  # noqa: E402
from bio_pages import decide  # noqa: E402
from bio_pages import domains  # noqa: E402
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
sql("INSERT INTO bio_custom_domains(id, profile_id, domain, status, token) VALUES ('bcd', ?, 'bob.example', "
    "'pending', 'btoken')", B_PID)


def _b_snapshot():
    return (sql("SELECT * FROM bio_profiles WHERE id = ?", B_PID), sql("SELECT * FROM bio_links WHERE profile_id = ?",
                                                                      B_PID),
            sql("SELECT * FROM bio_custom_domains WHERE profile_id = ?", B_PID),
            sorted(p.name for p in (FILES / "links" / B_LID).iterdir()))


# ── auth ─────────────────────────────────────────────────────────────

ROUTES = [("GET", BASE), ("POST", BASE), ("GET", f"{BASE}/stock/onlyicon.webp"),
          ("GET", f"{BASE}/files/links/{B_LID}/backgroundImage_bbbbbbbbbb.webp"),
          ("GET", f"{BASE}/{B_PID}"), ("PATCH", f"{BASE}/{B_PID}"), ("DELETE", f"{BASE}/{B_PID}"),
          ("POST", f"{BASE}/{B_PID}/avatar"), ("DELETE", f"{BASE}/{B_PID}/avatar"),
          ("POST", f"{BASE}/{B_PID}/avatar/vault"),
          ("POST", f"{BASE}/{B_PID}/background"), ("DELETE", f"{BASE}/{B_PID}/background"),
          ("POST", f"{BASE}/{B_PID}/background/vault"),
          ("POST", f"{BASE}/{B_PID}/links"), ("PUT", f"{BASE}/{B_PID}/links/order"),
          ("PATCH", f"{BASE}/{B_PID}/links/{B_LID}"), ("DELETE", f"{BASE}/{B_PID}/links/{B_LID}"),
          ("POST", f"{BASE}/{B_PID}/links/{B_LID}/background"),
          ("POST", f"{BASE}/{B_PID}/links/{B_LID}/background/vault"),
          ("DELETE", f"{BASE}/{B_PID}/links/{B_LID}/background"),
          ("PUT", f"{BASE}/{B_PID}/domain"), ("DELETE", f"{BASE}/{B_PID}/domain"),
          ("POST", f"{BASE}/{B_PID}/domain/check")]


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
            kw = {"json": {"ids": [B_LID]} if path.endswith("/order") else {"domain": "hijack.example"}
                  if path.endswith("/domain") else
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
    assert sql("SELECT bot_check FROM bio_links WHERE id = ?", lk["id"]) == [(1,)], "a new Link is bot-checked"
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
    # the page's own background: 1080 max side, in the public JSON, removable
    pbg = f"{BASE}/{pid}/background"
    assert public_json("upload_page").json()["profile"]["backgroundUrl"] == ""
    page = upload(owner, pbg, img("PNG", (3000, 1500))).json()
    pbg_name = page["profile"]["background_url"].rsplit("/", 1)[1]
    assert pbg_name.startswith("background_") and served(page["profile"]["background_url"]).size == (1080, 540)
    assert public_json("upload_page").json()["profile"]["backgroundUrl"] == f"/api/files/profiles/{pid}/{pbg_name}"
    assert page["profile"]["avatar_url"].rsplit("/", 1)[1] == name2, "the avatar stays"
    # the upload is audited as the page's stored Creator (no X-Account-Id sent)
    owner.patch(f"{BASE}/{pid}", json={"account_id": IDS["creator_a"]}).raise_for_status()
    assert upload(owner, pbg, img("PNG", (3000, 1500))).status_code == 200
    assert sql("SELECT account_id FROM actions ORDER BY id DESC LIMIT 1") == [(IDS["creator_a"],)]
    owner.patch(f"{BASE}/{pid}", json={"account_id": None}).raise_for_status()
    pbg_name = owner.get(f"{BASE}/{pid}").json()["profile"]["background_url"].rsplit("/", 1)[1]
    page = owner.delete(pbg).json()
    assert page["profile"]["background_url"] == "" and not (FILES / "profiles" / pid / pbg_name).exists()
    assert (FILES / "profiles" / pid / name2).exists()
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


# ── create with a Creator ────────────────────────────────────────────

def case_create_with_creator_fills_name_and_onlyfans_link():
    calls: list[str] = []
    me: dict | None = {"name": "Ava From OF", "username": "ava.of"}

    async def fake_me(aid):
        calls.append(aid)
        return me
    real, bio_admin._of_me = bio_admin._of_me, fake_me
    try:
        aid = IDS["creator_a"]
        r = owner.post(BASE, json={"username": "ava_page", "display_name": "", "account_id": aid})
        assert r.status_code == 201, r.text
        page = r.json()
        assert page["profile"]["display_name"] == "Ava From OF" and calls == [aid], (page["profile"], calls)
        [lk] = page["links"]
        assert (lk["title"], lk["destination"], lk["tracking"], lk["icon_stock"]) == (
            "OnlyFans", "https://onlyfans.com/ava.of", True, "onlyicon"), lk
        assert public_json("ava_page").status_code == 200
        # a typed name stays; the link is still added
        page = owner.post(BASE, json={"username": "ava_two", "display_name": " Mine ", "account_id": aid}).json()
        assert page["profile"]["display_name"] == "Mine" and len(page["links"]) == 1
        # no name on OF: the @username; OF unreadable: no link, and an empty name is refused
        me = {"username": "only_user"}
        assert create(owner, "ava_three", display_name=None, account_id=aid)["profile"]["display_name"] == "only_user"
        me = None
        r = owner.post(BASE, json={"username": "ava_four", "account_id": aid})
        assert r.status_code == 422 and r.json()["detail"]["field"] == "display_name", r.text
        assert create(owner, "ava_five", account_id=aid)["links"] == []
        # refused before any OF read: a bad username, a foreign Creator; no Creator, no read
        calls.clear()
        assert owner.post(BASE, json={"username": "x", "account_id": aid}).status_code == 422
        assert owner.post(BASE, json={"username": "ava_six", "account_id": IDS["creator_b"]}).status_code in (403, 404)
        create(owner, "ava_seven")
        assert calls == [], calls
    finally:
        bio_admin._of_me = real


def case_creator_set_later_adds_onlyfans_link_first():
    me: dict | None = {"name": "Ava", "username": "ava.later"}

    async def fake_me(aid):
        return me
    real, bio_admin._of_me = bio_admin._of_me, fake_me
    try:
        aid = IDS["creator_a"]
        pid = create(owner, "later_page")["profile"]["id"]
        add_link(owner, pid, title="Mine")
        r = owner.patch(f"{BASE}/{pid}", json={"account_id": aid})
        assert r.status_code == 200, r.text
        links = r.json()["links"]
        assert [(lk["title"], lk["destination"], lk["tracking"]) for lk in links] == [
            ("OnlyFans", "https://onlyfans.com/ava.later", True), ("Mine", DEST, False)], links
        # already links to OnlyFans: none added on a re-set; OF unreadable: none either
        dirs = lambda: sorted(p.name for p in (bio_admin.files.files_dir() / "links").iterdir())
        before = dirs()
        assert len(owner.patch(f"{BASE}/{pid}", json={"account_id": aid}).json()["links"]) == 2
        assert dirs() == before, "no orphan icon when no link is added"
        www = create(owner, "later_www")["profile"]["id"]
        add_link(owner, www, title="Mine", destination="http://www.OnlyFans.com/ava")
        assert len(owner.patch(f"{BASE}/{www}", json={"account_id": aid}).json()["links"]) == 1, "www/http variant counts"
        me = None
        bare = create(owner, "later_bare")["profile"]["id"]
        assert owner.patch(f"{BASE}/{bare}", json={"account_id": aid}).json()["links"] == []
        assert owner.patch(f"{BASE}/{bare}", json={"bio": "x"}).status_code == 200
    finally:
        bio_admin._of_me = real


# ── vault avatar ─────────────────────────────────────────────────────

def case_vault_avatar_photo_only_and_owned():
    import vault_stills
    vault_dir = Path(tempfile.mkdtemp(prefix="bio_vault_stills_"))
    real_dir, vault_stills.IMAGE_DIR = vault_stills.IMAGE_DIR, vault_dir
    try:
        aid = IDS["creator_a"]
        for mid, kind in ((9001, "photo"), (9002, "video"), (9003, "gif")):
            sql("INSERT INTO vault_items(account_id, media_id, kind, tags, send_count, created_at) VALUES "
                "(?, ?, ?, '[]', 0, '2026-11-01 00:00:00')", aid, mid, kind)
            path = vault_stills.image_path(aid, mid)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(img("JPEG", (1200, 900)))
        pid = create(owner, "vault_page", account_id=aid)["profile"]["id"]
        url = f"{BASE}/{pid}/avatar/vault"
        r = owner.post(url, json={"media_id": 9001, "type": "photo"})
        assert r.status_code == 200, r.text
        name = r.json()["profile"]["avatar"]
        assert name.startswith("avatar_") and name.endswith(".webp"), name
        assert served(r.json()["profile"]["avatar_url"]).size == (512, 384)
        # video / gif refused, by mirror kind or by the picked type; the avatar stays
        for body in ({"media_id": 9002}, {"media_id": 9003, "type": "photo"}, {"media_id": 9001, "type": "video"}):
            r = owner.post(url, json=body)
            assert r.status_code == 415 and r.json()["detail"] == "Pick a photo, not a video.", (body, r.text)
        for bad in ({}, {"media_id": "9001"}, {"media_id": True}, {"media_id": -1}):
            assert owner.post(url, json=bad).status_code == 422, bad
        assert owner.get(f"{BASE}/{pid}").json()["profile"]["avatar"] == name
        # a page with no Creator: 409; another owner's page (either way round): 404, unchanged
        bare = create(owner, "vault_bare")["profile"]["id"]
        assert owner.post(f"{BASE}/{bare}/avatar/vault", json={"media_id": 9001}).status_code == 409
        before = _b_snapshot()
        assert owner.post(f"{BASE}/{B_PID}/avatar/vault", json={"media_id": 9001}).status_code == 404
        assert other.post(url, json={"media_id": 9001}).status_code == 404
        assert _b_snapshot() == before and owner.get(f"{BASE}/{pid}").json()["profile"]["avatar"] == name
        # a link's background from the vault: photo only, the link's own page
        lid = add_link(owner, pid)["links"][-1]["id"]
        burl = f"{BASE}/{pid}/links/{lid}/background/vault"
        r = owner.post(burl, json={"media_id": 9001, "type": "photo"})
        assert r.status_code == 200, r.text
        lk = next(x for x in r.json()["links"] if x["id"] == lid)
        assert lk["background_image"].startswith("backgroundImage_"), lk
        assert served(lk["background_url"]).size[0] > 512, lk
        assert owner.post(burl, json={"media_id": 9002}).status_code == 415
        assert owner.post(f"{BASE}/{bare}/links/{lid}/background/vault", json={"media_id": 9001}).status_code == 404
        # the page's background from the vault: photo only, 1080 max side, the page's own Creator
        purl = f"{BASE}/{pid}/background/vault"
        r = owner.post(purl, json={"media_id": 9001})
        assert r.status_code == 200, r.text
        assert served(r.json()["profile"]["background_url"]).size == (1080, 810), r.json()["profile"]
        assert owner.post(purl, json={"media_id": 9002}).status_code == 415
        assert owner.post(f"{BASE}/{bare}/background/vault", json={"media_id": 9001}).status_code == 409
        assert other.post(purl, json={"media_id": 9001}).status_code == 404
        assert other.post(burl, json={"media_id": 9001}).status_code == 404
    finally:
        vault_stills.IMAGE_DIR = real_dir


# ── public base ──────────────────────────────────────────────────────

def case_public_base_from_request_when_unset():
    pid = create(owner, "base_page")["profile"]["id"]
    saved = os.environ.pop("BIO_PUBLIC_URL")
    try:
        body = owner.get(BASE, headers={"x-forwarded-host": "app.test, inner", "x-forwarded-proto": "https"}).json()
        assert body["public_base"] == "https://app.test/p", body["public_base"]
        row = next(p for p in body["profiles"] if p["id"] == pid)
        assert row["public_url"] == "https://app.test/p/base_page", row
        r = owner.get(f"{BASE}/{pid}", headers={"x-forwarded-host": "App.Test:8443", "x-forwarded-proto": "https"})
        assert r.json()["profile"]["public_url"] == "https://app.test:8443/p/base_page", r.text
        assert owner.get(BASE).json()["public_base"] == "http://testserver/p"
        for bad in ({"x-forwarded-host": "evil.test/x"}, {"x-forwarded-host": "a.test", "x-forwarded-proto": "ftp"}):
            assert owner.get(BASE, headers=bad).json()["public_base"] is None, bad
    finally:
        os.environ["BIO_PUBLIC_URL"] = saved
    assert owner.get(BASE, headers={"x-forwarded-host": "app.test"}).json()["public_base"] == "https://ofl.test"


def case_short_url_from_env():
    pid = create(owner, "short_page")["profile"]["id"]
    assert owner.get(f"{BASE}/{pid}").json()["profile"]["short_url"] is None
    os.environ["BIO_SHORT_URL"] = "https://short.test/s/"
    try:
        prof = owner.get(f"{BASE}/{pid}").json()["profile"]
        assert prof["short_url"] == "https://short.test/s/short_page", prof
        assert prof["public_url"] == "https://ofl.test/short_page", prof
    finally:
        os.environ.pop("BIO_SHORT_URL")


# ── custom domain ────────────────────────────────────────────────────

IP = "203.0.113.7"


def case_domain_pure_tables():
    for raw, want in ((" Shop.Example.COM ", "shop.example.com"), ("HTTPS://x.io/", "https://x.io/")):
        assert domains.normalize(raw) == want, raw
    for d, ok in (("", False), ("nodot", False), ("1.2.3.4", False), ("a_b.com", False), ("a..b.com", False),
                  ("-a.com", False), ("a" * 64 + ".com", False), (("a" * 60 + ".") * 5 + "com", False),
                  (("a" * 60 + ".") * 4 + "com", True), ("https://x.io/", False), ("x.io.", False),
                  ("shop.example.com", True), ("xn--bcher-kva.example", True)):
        assert domains.valid(d) == ok, d
    own = {"app.test"}
    for d, mine in (("ofl.ink", True), ("x.ofl.ink", True), ("inflowwww.com", True), ("app.inflowwww.com", True),
                    ("app.test", True), ("x.app.test", True), ("myofl.ink", False), ("shop.example.com", False)):
        assert domains.own_host(d, own) == mine, d
    assert domains.host_of("https://Ofl.Test:8443/p") == "ofl.test" and domains.host_of(None) is None
    assert domains._txt_value('"ab" "cd"') == "abcd" and domains._txt_value("plain") == "plain"
    assert domains._caa_entry('0 issue "letsencrypt.org"') == ("issue", "letsencrypt.org")
    # v2's relativeName and recordsFor
    assert [domains.relative_name(d, pre) for d, pre in (("a.com", ""), ("a.com", "_oflink"), ("x.y.a.com", ""),
                                                          ("x.a.com", "_oflink"))] == ["@", "_oflink", "x.y",
                                                                                         "_oflink.x"]
    assert domains.records_for("www.a.com", "t", IP, "2001:db8::1") == [
        {"type": "A", "name": "www", "value": IP}, {"type": "AAAA", "name": "www", "value": "2001:db8::1"},
        {"type": "TXT", "name": "_oflink.www", "value": "oflink-verify=t"}]
    assert [r["type"] for r in domains.records_for("a.com", "t", IP, None)] == ["A", "TXT"]
    # v2's checks (b)-(e), its sentences
    v6 = "2001:db8::1"
    proof = ("oflink-verify=tok",)
    rows = [(domains.Dns((IP,), (), proof), None, []),
            (domains.Dns((IP,), (v6,), proof), "2001:0db8:0:0:0:0:0:1", []),
            (domains.Dns(), None, ["No TXT record _oflink.d.example yet.", "No A record for d.example yet."]),
            (domains.Dns((IP,), (), ("tok",)), None,
             ["The TXT record _oflink.d.example does not hold oflink-verify=tok yet."]),
            (domains.Dns(("198.51.100.1",), (), proof), None, ["d.example points to 198.51.100.1, not 203.0.113.7."]),
            (domains.Dns((IP, "198.51.100.1"), (), proof), None, ["Delete the A record 198.51.100.1."]),
            (domains.Dns((IP,), (v6,), proof), None, ["Delete the AAAA record 2001:db8::1."]),
            (domains.Dns((IP,), (v6, "2001:db8::2"), proof), v6, ["Delete the AAAA record 2001:db8::2."]),
            (domains.Dns((IP,), (), proof, (("issue", "digicert.com"),)), None,
             ["A CAA record for d.example does not allow letsencrypt.org. Add one that does, or delete it."]),
            (domains.Dns((IP,), (), proof, (("issue", "letsencrypt.org; validationmethods=http-01"),
                                             ("issue", "digicert.com"))), None, []),
            (domains.Dns((IP,), (), proof, (("iodef", "mailto:x@y"),)), None, [])]
    for dns, ipv6, want in rows:
        assert domains.problems("d.example", "tok", IP, ipv6, dns) == want, (dns, ipv6)


class _FakeNet:
    """domains.lookup / probe over a table: {domain: Dns}, probe answers from `certs`; counts calls."""
    def __init__(self):
        self.dns: dict[str, domains.Dns | None] = {}
        self.certs: set[str] = set()
        self.calls = 0

    def __enter__(self):
        self.saved = domains.lookup, domains.probe

        async def lookup(d):
            self.calls += 1
            got = self.dns.get(d)
            if got is None:
                raise domains.DnsUnavailable
            return got

        async def probe(d):
            return d in self.certs
        domains.lookup, domains.probe = lookup, probe
        return self

    def __exit__(self, *exc):
        domains.lookup, domains.probe = self.saved


def _unthrottle(pid):
    sql("UPDATE bio_custom_domains SET checked = NULL WHERE profile_id = ?", pid)


def check(client, pid):
    _unthrottle(pid)
    return client.post(f"{BASE}/{pid}/domain/check")


def _tok(page):
    """The token in the page's TXT record (`oflink-verify=<token>`)."""
    txt = next(r for r in page["profile"]["custom_domain"]["records"] if r["type"] == "TXT")
    return txt["value"].removeprefix("oflink-verify=")


def case_domain_set_validation_and_replace():
    pid = create(owner, "dom_set_x")["profile"]["id"]
    page = owner.get(f"{BASE}/{pid}").json()["profile"]
    assert page["domain_server_ip"] == IP and page["home_url"] == page["public_url"], page
    sql("INSERT INTO bio_spare_domains(id, domain) VALUES ('spare1', 'spare.example')")
    for bad, msg in ((None, "Enter a domain."), (123, "Enter a domain."), ("  ", "Enter a domain."),
                     ("nodot", "Enter the domain alone, like domsetx.com: no https://, no slash, no spaces."),
                     ("https://a.com/", "Enter the domain alone, like domsetx.com"), ("a.com.", "Enter the domain"),
                     ("1.2.3.4", "Enter the domain"), ("a" * 250 + ".com", "Enter the domain"),
                     ("ofl.ink", "ofl.ink is one of ofl.ink's own addresses. Use a domain you own."),
                     ("x.inflowwww.com", "own addresses"), ("ofl.test", "own addresses"),
                     ("spare.example", "spare.example is one of ofl.ink's own addresses"),
                     ("www.spare.example", "own addresses")):
        r = owner.put(f"{BASE}/{pid}/domain", json={"domain": bad})
        assert r.status_code == 422 and r.json()["detail"]["field"] == "domain", (bad, r.status_code, r.text)
        assert msg in r.json()["detail"]["msg"], (bad, r.json())
    r = owner.put(f"{BASE}/{pid}/domain", json={"domain": "x.app.test"}, headers={"x-forwarded-host": "app.test"})
    assert r.status_code == 422, "the request's own host and its subdomains are this service's"
    assert sql("SELECT COUNT(*) FROM bio_custom_domains WHERE profile_id = ?", pid) == [(0,)]
    page = owner.put(f"{BASE}/{pid}/domain", json={"domain": " Links.Example.COM "}).json()
    d = page["profile"]["custom_domain"]
    assert d["domain"] == "links.example.com" and d["status"] == "pending" and d["checked"] is None, d
    tok = _tok(page)
    assert len(tok) == 32 and tok.isalnum() and tok == tok.lower(), tok
    assert d["records"] == [{"type": "A", "name": "links", "value": IP},
                            {"type": "TXT", "name": "_oflink.links", "value": f"oflink-verify={tok}"}], d
    assert "token" not in d
    again = owner.put(f"{BASE}/{pid}/domain", json={"domain": "links.example.com"}).json()
    assert _tok(again) == tok, "the same domain keeps its row and token"
    os.environ["BIO_SERVER_IPV6"] = "2001:DB8::1"
    try:
        recs = owner.get(f"{BASE}/{pid}").json()["profile"]["custom_domain"]["records"]
        assert recs[1] == {"type": "AAAA", "name": "links", "value": "2001:db8::1"}, recs
    finally:
        os.environ.pop("BIO_SERVER_IPV6")
    new = owner.put(f"{BASE}/{pid}/domain", json={"domain": "other.example.com"}).json()
    assert new["profile"]["custom_domain"]["domain"] == "other.example.com" and _tok(new) != tok
    assert sql("SELECT domain FROM bio_custom_domains WHERE profile_id = ?", pid) == [("other.example.com",)]
    r = owner.delete(f"{BASE}/{pid}/domain")
    assert r.status_code == 200 and r.json()["profile"]["custom_domain"] is None
    assert sql("SELECT COUNT(*) FROM bio_custom_domains WHERE profile_id = ?", pid) == [(0,)]
    assert owner.delete(f"{BASE}/{pid}/domain").status_code == 200, "removing none is a no-op"
    r = owner.post(f"{BASE}/{pid}/domain/check")
    assert r.status_code == 409 and r.json()["detail"] == "This page has no custom domain.", r.text


def case_domain_cap_per_account():
    have = sql("SELECT COUNT(*) FROM bio_custom_domains c JOIN bio_profiles p ON p.id = c.profile_id "
               "WHERE p.owner_user_id = ?", A)[0][0]
    pids = []
    for i in range(domains.MAX_PER_OWNER - have):
        pid = create(owner, f"cap_{i}")["profile"]["id"]
        assert owner.put(f"{BASE}/{pid}/domain", json={"domain": f"cap{i}.example"}).status_code == 200
        pids.append(pid)
    extra = create(owner, "cap_extra")["profile"]["id"]
    r = owner.put(f"{BASE}/{extra}/domain", json={"domain": "cap-extra.example"})
    assert r.status_code == 409 and "at most 10" in r.json()["detail"], r.text
    assert owner.put(f"{BASE}/{pids[0]}/domain", json={"domain": "cap-swap.example"}).status_code == 200, \
        "replacing a page's own domain is not a new one"
    bpid = create(other, "cap_b")["profile"]["id"]
    assert other.put(f"{BASE}/{bpid}/domain", json={"domain": "b-own.example"}).status_code == 200, \
        "another account's cap is its own"
    assert other.delete(f"{BASE}/{bpid}").status_code == 204
    for pid in pids:
        owner.delete(f"{BASE}/{pid}/domain")


def _tls_ask(domain):
    return bio_get(f"/internal/tls-ask?domain={domain}").status_code


def _problems(body):
    return " ".join(body["check"]["problems"])


def case_domain_check_transitions_and_uniqueness():
    pid = create(owner, "dom_check")["profile"]["id"]
    rival = create(owner, "dom_rival")["profile"]["id"]
    D = "shop.example"
    tok = _tok(owner.put(f"{BASE}/{pid}/domain", json={"domain": D}).json())
    rtok = _tok(owner.put(f"{BASE}/{rival}/domain", json={"domain": D}).json())
    assert tok != rtok, "two pages may hold the same pending domain: nobody squats it"
    assert _tls_ask(D) == 404, "pending names nobody"
    proof, rproof = f"oflink-verify={tok}", f"oflink-verify={rtok}"
    with _FakeNet() as net:
        steps = [(None, "pending", "The DNS lookup for shop.example did not answer. Try again in a few minutes."),
                 (domains.Dns(), "pending", "No TXT record _oflink.shop.example yet. No A record for shop.example yet."),
                 (domains.Dns(("198.51.100.9",), (), (proof,)), "pending",
                  "shop.example points to 198.51.100.9, not 203.0.113.7."),
                 (domains.Dns((IP,), ("2001:db8::1",), (proof,)), "pending", "Delete the AAAA record 2001:db8::1."),
                 (domains.Dns((IP,), (), ("nope",)), "pending",
                  f"The TXT record _oflink.shop.example does not hold {proof} yet."),
                 (domains.Dns((IP,), (), (proof, rproof)), "pending_cert", domains.CERT_MSG)]
        for dns, status, msg in steps:
            net.dns[D] = dns
            r = check(owner, pid)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["profile"]["custom_domain"]["status"] == status, (dns, body["profile"]["custom_domain"])
            assert body["check"]["status"] == status and _problems(body) == msg, (dns, body["check"])
            assert body["profile"]["public_url"] != f"https://{D}/"
        assert sql("SELECT checked IS NOT NULL FROM bio_custom_domains WHERE profile_id = ?", pid) == [(1,)]
        r = owner.post(f"{BASE}/{pid}/domain/check")
        assert r.status_code == 429, "a second check within CHECK_GAP_S"
        # pending_cert: served by the bio app (the cert needs it), isolated to its Profile
        assert _tls_ask(D) == 200
        assert bio_get("/api/profiles/dom_check.json", host=D).status_code == 200
        assert bio_get("/api/profiles/dom_rival.json", host=D).status_code == 404
        # the rival proves the same DNS too: v2's "taken" problem, the rival stays pending
        body = check(owner, rival).json()
        assert body["check"] == {"status": "pending", "problems": ["Another Profile already uses shop.example."]}, body
        assert sql("SELECT status FROM bio_custom_domains WHERE profile_id = ?", rival) == [("pending",)]
        third = create(other, "dom_third")["profile"]["id"]
        r = other.put(f"{BASE}/{third}/domain", json={"domain": D})
        assert r.status_code == 409 and r.json()["detail"] == {
            "field": "domain", "msg": "Another Profile already uses shop.example."}, r.text
        # the certificate answers: live
        net.certs.add(D)
        body = check(owner, pid).json()
        assert body["profile"]["custom_domain"]["status"] == "live" and body["check"]["problems"] == [], body
        assert body["profile"]["public_url"] == f"https://{D}/" and body["profile"]["home_url"].endswith("/dom_check")
        listed = next(p for p in owner.get(BASE).json()["profiles"] if p["id"] == pid)
        assert listed["custom_domain"] == {"domain": D, "status": "live"}, listed
        calls = net.calls
        assert check(owner, pid).json()["profile"]["custom_domain"]["status"] == "live"
        assert net.calls == calls, "a live domain's check reads no DNS"
        # DNS broken while pending_cert sends it back to pending
        sql("UPDATE bio_custom_domains SET status = 'pending_cert' WHERE profile_id = ?", pid)
        net.dns[D] = domains.Dns()
        assert check(owner, pid).json()["profile"]["custom_domain"]["status"] == "pending"
        assert _tls_ask(D) == 404
        net.dns[D] = None  # DNS unreadable: the status stays
        sql("UPDATE bio_custom_domains SET status = 'pending_cert' WHERE profile_id = ?", pid)
        assert check(owner, pid).json()["profile"]["custom_domain"]["status"] == "pending_cert"
        # a spare domain added since it was saved: v2's own-address problem, no DNS read
        sql("INSERT INTO bio_spare_domains(id, domain) VALUES ('spare2', 'example')")
        calls = net.calls
        body = check(owner, pid).json()
        assert body["check"] == {"status": "pending", "problems": [
            "shop.example is one of ofl.ink's own addresses. Use a domain you own."]} and net.calls == calls, body
        sql("DELETE FROM bio_spare_domains WHERE id = 'spare2'")
        # the row changed between the read and the write: refused, nothing written
        net.dns[D] = domains.Dns((IP,), (), (proof,))
        real = domains.check

        async def swap(*a):
            sql("DELETE FROM bio_custom_domains WHERE profile_id = ?", pid)
            return "live", []
        domains.check = swap
        try:
            r = check(owner, pid)
        finally:
            domains.check = real
        assert r.status_code == 409 and sql("SELECT COUNT(*) FROM bio_custom_domains WHERE profile_id = ?", pid) == [
            (0,)], r.text
    for p in (rival,):
        owner.delete(f"{BASE}/{p}/domain")
    other.delete(f"{BASE}/{third}")


def case_domain_off_without_server_ip():
    pid = create(owner, "dom_off")["profile"]["id"]
    assert owner.put(f"{BASE}/{pid}/domain", json={"domain": "off.example"}).status_code == 200
    saved = os.environ.pop("BIO_SERVER_IP")
    try:
        os.environ["BIO_SERVER_IP"] = "not-an-ip"
        page = owner.get(f"{BASE}/{pid}").json()
        assert page["profile"]["domain_server_ip"] is None
        r = owner.put(f"{BASE}/{pid}/domain", json={"domain": "off2.example"})
        assert r.status_code == 409 and r.json()["detail"] == domains.OFF_MSG
        assert owner.post(f"{BASE}/{pid}/domain/check").status_code == 409
        assert owner.delete(f"{BASE}/{pid}/domain").json()["profile"]["custom_domain"] is None
    finally:
        os.environ["BIO_SERVER_IP"] = saved


def case_no_destination_or_geo_in_logs():
    hits = [ln for ln in LOGS.lines if "slopdest" in ln or GEO_VAL in ln]
    assert not hits, hits[:3]



_harness.run()
