#!/usr/bin/env python3
"""bio_pages.app over ASGI: routing in Hono's order, Profile JSON, ping, Reveal, files, tls-ask, isolation from the
relay and no destination in any answer or log line. Seeded by SQL into the harness temp DB.

Run: ./venv/bin/python service/tests/test_bio_app.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402

from bio_pages import assets  # noqa: E402
from bio_pages import app as bio_app  # noqa: E402
from bio_pages import decide, guard, store  # noqa: E402
from bio_pages.config import BioConfig  # noqa: E402

PID, PID2, PID3 = "p00000000000001", "p00000000000002", "p00000000000003"
LID, LID2 = "l00000000000001", "l00000000000002"
KEY, KEY2 = "k00000000001", "k00000000002"
DEST, GEO_CODE = "https://secret.example/slopdest-alice", "slopgeo77"
FILES = Path(tempfile.mkdtemp(prefix="bio_files_"))
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 fake"


class _Logs(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)  # the relay logs at INFO (basicConfig); aiosqlite's DEBUG echoes SQL
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(self.format(record) + (self.formatter.formatException(record.exc_info)
                                                 if record.exc_info else ""))


LOGS = _Logs()
LOGS.setFormatter(logging.Formatter("%(name)s %(message)s"))
logging.getLogger().addHandler(LOGS)
logging.getLogger().setLevel(logging.INFO)


def _seed():
    c = sqlite3.connect(_harness.DB_PATH)
    c.execute("INSERT INTO users(id, username, password) VALUES ('u1', 'u1', 'x')")
    c.executemany("INSERT INTO bio_profiles(id, owner_user_id, username, display_name, avatar, mode, verified) "
                  "VALUES (?, 'u1', ?, ?, ?, ?, ?)",
                  [(PID, "alice", "Alice", "a.webp", "direct", 1), (PID2, "bob", "Bob", "", "", 0),
                   (PID3, "carol", "Carol", "", "", 0)])
    c.executemany("INSERT INTO bio_links(id, profile_id, link_id, title, destination, default_tracking_code, geo, "
                  "tracking, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
                  [(LID2, PID, KEY2, "Second", DEST + "-2", "", json.dumps({"US": GEO_CODE}), 2.0),
                   (LID, PID, KEY, "First", DEST, "55", None, 1.0)])
    c.execute("INSERT INTO bio_spare_domains(id, domain) VALUES ('s1', 'spare.test')")
    c.executemany("INSERT INTO bio_custom_domains(id, profile_id, domain, status) VALUES (?, ?, ?, ?)",
                  [("c1", PID, "alice.test", "live"), ("c2", PID2, "bob.test", "pending"),
                   ("c3", PID3, "spare.test", "live")])
    c.commit()
    c.close()
    (FILES / "profiles" / PID).mkdir(parents=True)
    (FILES / "profiles" / PID / "a.webp").write_bytes(WEBP)
    (FILES / "profiles" / PID / ".hidden").write_bytes(b"x")
    (FILES / "secret.txt").write_bytes(b"x")


_seed()
bio_app.PRIMARY = decide.parse_primary_hosts("localhost,ofl.test")
bio_app.FILES_DIR = FILES
bio_app.INDEX_HTML = decide.render_index(assets.INDEX.read_text(), True)
NOW = [1000.0]
guard.configure(1000, clock=lambda: NOW[0])


def _daily() -> list[tuple]:
    c = sqlite3.connect(_harness.DB_PATH)
    try:
        return c.execute("SELECT profile_id, link_id, country, in_app, code, views, clicks FROM bio_daily "
                         "ORDER BY profile_id, link_id, country, in_app, code").fetchall()
    finally:
        c.close()


async def _calls(reqs):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bio_app.app), base_url="http://localhost") as cl:
        out = []
        for method, path, headers in reqs:
            out.append(await cl.request(method, path, headers={"host": "localhost", **(headers or {})}))
        return out


def call(method, path, **headers):
    return asyncio.run(_calls([(method, path, {k.replace("_", "-"): v for k, v in headers.items()})]))[0]


def _block(page: str):
    tag = '<script type="application/json" id="profile-bootstrap">'
    s = page.index(tag) + len(tag)
    return json.loads(page[s:page.index("</script>", s)])


def _is_page(r) -> bool:
    return r.status_code == 200 and 'id="profile-bootstrap"' in r.text


def case_profile_json():
    r = call("GET", "/api/profiles/Alice.json")
    assert r.status_code == 200 and r.headers["content-type"] == "application/json", r.headers
    assert r.headers["cache-control"] == bio_app.MR
    body = r.json()
    assert body["profile"]["username"] == "alice" and body["profile"]["verified"] is True
    assert body["profile"]["avatarUrl"] == f"/api/files/profiles/{PID}/a.webp"
    assert [lk["id"] for lk in body["links"]] == [KEY, KEY2], "sort_order, then the public link_id"
    assert body["links"][0]["default_tracknumber"] == "55" and "default_tracknumber" not in body["links"][1]
    r = call("GET", "/api/profiles/nobody.json")
    assert (r.status_code, r.content, r.headers["cache-control"]) == (404, b'{"error":"Profile not found"}', bio_app.MR)


def case_routing_table():
    nf = b'{"error":"Not found"}'
    rows = [
        ("GET", "/api/profiles/Alice.JSON", 404, nf),
        ("GET", "/api/profiles/a/b.json", 404, nf),
        ("GET", "/api/profiles/a%2Fb.json", 404, b'{"error":"Profile not found"}'),
        ("GET", "/api", 404, nf),
        ("POST", "/api/upload/x", 404, nf),
        ("DELETE", "/api/collections/bio_links/records", 404, nf),
        ("PUT", "/v/alice", 404, b"404 Not Found"),
        ("POST", "/v/alice/", 404, b"404 Not Found"),
        ("POST", "/foo", 404, b"404 Not Found"),
        ("DELETE", "/x", 404, b"404 Not Found"),
        ("GET", "/internal/healthz", 200, b""),
    ]
    for method, path, status, body in rows:
        r = call(method, path)
        assert (r.status_code, r.content) == (status, body), (method, path, r.status_code, r.content[:80])
    r = call("PUT", "/v/alice")
    assert r.headers["content-type"] == "text/plain; charset=UTF-8"
    assert "cache-control" not in call("GET", "/api").headers
    assert call("GET", "/internal/healthz").headers["cache-control"] == "no-store"
    for path in ("/v/alice", "/internal/healthz/", "/images"):
        assert _is_page(call("GET", path)), path
    assert _block(call("GET", "/index.html").text) == {"username": "index.html", "trackingCode": None,
                                                       "profilePath": "/index.html"}
    r = call("GET", "/style.css")
    assert r.status_code == 200 and r.headers["content-type"] == "text/css; charset=utf-8"
    assert r.content == (assets.PUBLIC / "style.css").read_bytes() and r.headers["cache-control"] == bio_app.MR
    r = call("GET", "/images/verified.svg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/svg+xml"
    assert r.content == (assets.PUBLIC / "images/verified.svg").read_bytes()
    for path in ("/netlify", "/netlify/functions/x", "/edit", "/edit/x"):
        r = call("GET", path)
        assert (r.status_code, r.content) == (404, bio_app.LANDING), path
        assert r.headers["content-type"] == bio_app.HTML and r.headers["cache-control"] == bio_app.MR


def case_head_mirrors_get():
    for path in ("/api/profiles/alice.json", "/alice", "/style.css", "/internal/healthz", "/netlify",
                 f"/api/files/profiles/{PID}/a.webp", "/api/profiles/none.json", "/"):
        g, h = call("GET", path), call("HEAD", path)
        assert g.status_code == h.status_code and h.content == b"", path
        assert {k: v for k, v in g.headers.items() if k != "content-length"} == \
               {k: v for k, v in h.headers.items() if k != "content-length"}, path


def case_pages_and_hosts():
    r = call("GET", "/")
    assert (r.status_code, r.content) == (200, bio_app.LANDING), "primary / → neutral stub"
    assert _block(call("GET", "/alice/123/deep").text) == {"username": "alice", "trackingCode": "123",
                                                           "profilePath": "/alice"}
    assert _block(call("GET", "/", host="alice.test").text) == {"username": "alice", "trackingCode": None,
                                                                "profilePath": "/"}
    assert _block(call("GET", "/123", host="alice.test").text)["trackingCode"] == "123"
    assert _block(call("GET", "/a/b", host="alice.test").text) is None, "custom 2 segments → null block, still 200"
    assert _block(call("GET", "/x", host="spare.test").text)["username"] == "x", "spare wins over a live custom"
    assert _block(call("GET", "/x", host="bob.test").text)["username"] == "x", "pending → unknown → path grammar"
    assert _block(call("GET", "/Al%69ce").text)["username"] == "Al%69ce"


def case_escape_tap_flag():
    """BIO_ESCAPE_TAP (default on) reaches the rendered card; bootstrap retains v2's shape."""
    saved = os.environ.pop("BIO_ESCAPE_TAP", None)
    try:
        assert BioConfig.from_env().escape_tap is True, "default on"
        for raw, want in (("", True), ("1", True), ("true", True), ("on", True), ("yes", True),
                          ("0", False), ("false", False), (" OFF ", False), ("no", False)):
            os.environ["BIO_ESCAPE_TAP"] = raw
            assert BioConfig.from_env().escape_tap is want, raw
        for raw in ("disabled", "n", "maybe"):
            os.environ["BIO_ESCAPE_TAP"] = raw
            try:
                BioConfig.from_env()
                assert False, raw
            except ValueError:
                pass
    finally:
        os.environ.pop("BIO_ESCAPE_TAP", None)
        if saved is not None:
            os.environ["BIO_ESCAPE_TAP"] = saved
    try:
        for flag in (True, False):
            bio_app.INDEX_HTML = decide.render_index(assets.INDEX.read_text(), flag)
            want = {"username": "alice", "trackingCode": "9", "profilePath": "/alice"}
            page = call("GET", "/alice/9").text
            assert _block(page) == want and f'data-escape-tap="{int(flag)}"' in page, flag
            assert _block(call("GET", "/9", host="alice.test").text)["profilePath"] == "/", flag
            assert _block(call("GET", "/a/b", host="alice.test").text) is None, flag
    finally:
        bio_app.INDEX_HTML = decide.render_index(assets.INDEX.read_text(), True)


def case_unknown_hosts_never_query():
    calls = []
    real = store.resolve_host_row

    async def spy(name):
        calls.append(name)
        return await real(name)
    store.resolve_host_row = spy
    try:
        for h in ("1.2.3.4", "[::1]:3000", "a_b.test", "localhost", "LocalHost:4173", "localhost."):
            assert call("GET", "/alice", host=h).status_code == 200, h
        assert calls == []
        call("GET", "/alice", host="Spare.Test.")
        assert calls == ["spare.test"]
    finally:
        store.resolve_host_row = real


def case_ping_records_a_view():
    before = _daily()
    r = call("POST", "/v/alice", cf_ipcountry="de", user_agent="x Instagram y")
    assert (r.status_code, r.content, r.headers["cache-control"]) == (204, b"", "no-store")
    asyncio.run(store.flush())
    assert set(_daily()) - set(before) == {(PID, "", "DE", "instagram", "", 1, 0)}
    call("POST", "/v/Alice", cf_ipcountry="DE", user_agent="x Instagram y")
    asyncio.run(store.flush())
    assert (PID, "", "DE", "instagram", "", 2, 0) in _daily(), "same day/key → one row, counted up"
    r = call("POST", "/v/nobody")
    assert (r.status_code, r.content) == (404, b'{"error":"Profile not found"}')


def case_reveal():
    same = {"sec_fetch_site": "same-origin"}
    r = call("GET", f"/.netlify/functions/reveal?id={KEY}&trackingId=4242&id=zzz", **same)
    assert (r.status_code, r.headers["cache-control"]) == (200, "no-store")
    assert r.content == json.dumps({"realUrl": DEST + "/c4242"}, separators=(",", ":")).encode()
    assert "access-control-allow-origin" not in r.headers
    asyncio.run(store.flush())
    assert (PID, LID, "XX", "", "4242", 0, 1) in _daily()
    r = call("GET", f"/.netlify/functions/reveal?id={KEY2}&trackingId=geo", x_country="US", **same)
    assert r.json() == {"realUrl": DEST + "-2/c" + GEO_CODE}
    asyncio.run(store.flush())
    assert (PID, LID2, "XX", "", GEO_CODE, 0, 1) in _daily()
    assert call("GET", "/.netlify/functions/reveal?id=k0000000000%31", **same).status_code == 200, "query decoded"
    for q in ("id=nope", "id=" + KEY.upper(), "", "id=" + KEY + "x"):
        r = call("GET", "/.netlify/functions/reveal?" + q, **same)
        assert (r.status_code, r.content) == (404, b'{"error":"Link not found"}'), q
    r = call("GET", f"/.netlify/functions/reveal?id={KEY}", sec_fetch_site="cross-site")
    assert (r.status_code, r.content) == (403, b'{"error":"Cross-origin request refused"}')
    r = call("GET", f"/.netlify/functions/reveal?id={KEY}", origin="http://evil.test")
    assert r.status_code == 403


def case_limits():
    NOW[0] = 5 * 60.0
    guard.configure(2, clock=lambda: NOW[0])
    try:
        rv = f"/.netlify/functions/reveal?id={KEY}"
        assert call("GET", rv, sec_fetch_site="cross-site").status_code == 403
        assert [call("GET", rv).status_code for _ in range(3)] == [200, 200, 429], "a 403 does not count"
        r = call("GET", rv)
        assert (r.content, r.headers["cache-control"]) == (b'{"error":"Too many requests"}', "no-store")
        assert [call("POST", p).status_code for p in ("/v/carol", "/v/Carol", "/v/CAROL")] == [204, 204, 429]
        assert call("POST", "/v/nobody2").status_code == 404 and call("POST", "/v/bob").status_code == 204
        NOW[0] += 60
        assert call("GET", rv).status_code == 200, "next minute"
    finally:
        guard.configure(1000, clock=lambda: NOW[0])


def case_files():
    r = call("GET", f"/api/files/profiles/{PID}/a.webp")
    assert (r.status_code, r.content) == (200, WEBP), (r.status_code, r.content[:80], LOGS.lines[-3:])
    assert r.headers["content-type"] == "image/webp" and r.headers["cache-control"] == bio_app.IMM
    for path in (f"/api/files/users/{PID}/a.webp", f"/api/files/profiles/{PID[:-1]}/a.webp",
                 f"/api/files/profiles/{PID}/..%2F..%2Fsecret.txt", f"/api/files/profiles/{PID}/.hidden",
                 f"/api/files/profiles/{PID}/b.webp", f"/api/files/profiles/{PID}/a.webp/x"):
        r = call("GET", path)
        assert r.status_code == 404, (path, r.status_code, r.content[:80])
        if path.endswith("/x"):
            continue  # 4 segments: #6
        assert r.content == b"" and "content-type" not in r.headers and "cache-control" not in r.headers, path


def case_tls_ask():
    rows = [("", 400), ("?domain=", 400), ("?domain=bad%20host!", 400), ("?domain=localhost", 200),
            ("?domain=spare.test", 200), ("?domain=alice.test", 200), ("?domain=bob.test", 404),
            ("?domain=nobody.test", 404)]
    for q, want in rows:
        r = call("GET", "/internal/tls-ask" + q)
        assert (r.status_code, r.content, r.headers["cache-control"]) == (want, b"", "no-store"), (q, r.status_code)
    real = store.resolve_host_row

    async def down(name):
        raise RuntimeError("database is locked")
    store.resolve_host_row = down
    try:
        assert call("GET", "/internal/tls-ask?domain=x.test").status_code == 503
    finally:
        store.resolve_host_row = real


def case_error_is_a_fixed_line():
    real = store.profile_with_links

    async def boom(name):
        raise ValueError("row " + DEST)
    store.profile_with_links = boom
    n = len(LOGS.lines)
    try:
        r = call("GET", "/api/profiles/alice.json")
    finally:
        store.profile_with_links = real
    assert (r.status_code, r.content, r.headers["cache-control"]) == (500, b'{"error":"Internal error"}', "no-store")
    assert any(ln.endswith("bio: request failed ValueError") for ln in LOGS.lines[n:])


def case_failed_write_never_fails_the_answer():
    lock = sqlite3.connect(_harness.DB_PATH, timeout=0)
    lock.execute("BEGIN IMMEDIATE")
    try:
        assert call("POST", "/v/alice").status_code == 204
        assert asyncio.run(store.flush()) is False
        assert store._batch
    finally:
        lock.rollback()
        lock.close()
    assert asyncio.run(store.flush()) is True


def case_isolation_from_the_relay():
    for path in ("/admin/accounts", "/auth/me", "/docs", "/openapi.json", "/livez", "/t/123", "/admin/x"):
        assert _is_page(call("GET", path)), path
        assert call("POST", path).status_code == 404 and call("POST", path).content == b"404 Not Found", path
    relay = _harness.make_client()
    r = relay.get("/api/profiles/x.json")
    assert r.status_code == 404 and "Profile not found" not in r.text, "the relay mounts no bio route"


def case_no_destination_leaks():
    asyncio.run(store.flush())
    answers = asyncio.run(_calls([(m, p, {"sec-fetch-site": "cross-site"} if "reveal" in p else {}) for m, p in [
        ("GET", "/api/profiles/alice.json"), ("GET", "/alice"), ("GET", "/alice/9"), ("GET", "/api/x"),
        ("GET", "/edit"), ("POST", "/v/nobody"), ("PUT", "/x"), ("GET", f"/.netlify/functions/reveal?id={KEY}"),
        ("GET", "/.netlify/functions/reveal?id=nope")]]))
    for r in answers:
        assert "slopdest" not in r.text and GEO_CODE not in r.text, (r.request.url, r.text[:200])
    for ln in LOGS.lines:
        assert "slopdest" not in ln and GEO_CODE not in ln, ln


def case_request_target_cap():
    assert call("GET", "/" + "a" * 16_383).status_code == 200
    assert call("GET", "/" + "a" * 16_384).status_code == 431


_harness.run()
