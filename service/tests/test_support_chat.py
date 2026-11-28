#!/usr/bin/env python3
import os
import tempfile
import uuid
from pathlib import Path

import _harness

HUB_URL = "https://hub.test"
TOKEN = "test-support-token"
PASSWORD = "test-support-password"
os.environ.update({
    "SUPPORT_HUB_URL": HUB_URL, "SUPPORT_HUB_TOKEN": TOKEN, "SUPPORT_INSTANCE": "AE",
    "SUPPORT_HUB_PASSWORD": PASSWORD,
    "SUPPORT_HUB_DB": str(Path(tempfile.gettempdir()) / f"support_hub_test_{uuid.uuid4().hex}.db"),
})

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import hmac  # noqa: E402
import io  # noqa: E402
import struct  # noqa: E402
import threading  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import server  # noqa: E402
import support_api  # noqa: E402
import support_hub  # noqa: E402
import support_photos  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Action  # noqa: E402
from llm_client import LLMKeyError  # noqa: E402

IDS = fx.seed_two_agencies()
fx.store_blob(IDS["agency_a_owner"], "account", {"agency_name": "Agency A"})
support_api._transport = httpx.ASGITransport(app=server.app)

CHATTER = fx.login_chatter("chatter_a")
OWNER_A = fx.login_owner("agency_a_owner")
ANON = _harness.make_client()
INST = {"Authorization": f"Bearer {TOKEN}"}


def _hub_client() -> TestClient:
    _harness.make_client()
    return TestClient(server.app, base_url="https://testserver")


def _hub_owner() -> TestClient:
    support_hub.reset_throttle()
    c = _hub_client()
    r = c.post("/support/api/login", json={"password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


@contextlib.contextmanager
def _env(**kv):
    saved = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _thread_of(owner: TestClient, name: str) -> dict:
    rows = [t for t in owner.get("/support/api/threads").json()["threads"] if t["name"] == name]
    assert len(rows) == 1, rows
    return rows[0]


def case_hub_page_served_only_when_enabled():
    c = _hub_client()
    r = c.get("/support")
    assert r.status_code == 200 and "Summarise all" in r.text
    assert "nonce-" in r.headers["content-security-policy"]
    assert "innerHTML" not in r.text
    with _env(SUPPORT_HUB_PASSWORD=None):
        assert c.get("/support").status_code == 404
        assert c.post("/support/api/login", json={"password": ""}).status_code == 404
        assert c.get("/support/api/instance/unread", params={"instance": "AE", "user_key": "x"},
                     headers=INST).status_code == 404


def case_owner_api_needs_cookie():
    c = _hub_client()
    assert c.get("/support/api/threads").status_code == 401
    assert c.get("/support/api/threads/1").status_code == 401
    assert c.post("/support/api/threads/1/reply", json={"text": "hi"}).status_code == 401
    assert c.post("/support/api/summarise").status_code == 401
    support_hub.reset_throttle()
    sid = "a" * 32
    for bad in ("9999999999.deadbeef", f"{sid}.1.{support_hub._sign(sid, 1)}",
                f"{sid}.9999999999.{support_hub._sign(sid, 9999999999)}"):
        c.cookies.set(support_hub.COOKIE, bad, path="/support")
        assert c.get("/support/api/threads").status_code == 401, bad
    support_hub.reset_throttle()


def case_non_ascii_digit_cookie_is_401_not_500():
    support_hub.reset_throttle()
    sid = "a" * 32
    for exp in ("\u00b2", "1\u00b2", "\u0661\u0662"):
        assert support_hub._session_ok(f"{sid}.{exp}.{'0' * 64}") is False
    raw = f"{support_hub.COOKIE}={sid}.\u00b2.{'0' * 64}".encode("latin-1")
    c = TestClient(server.app, base_url="https://testserver", raise_server_exceptions=False)
    r = c.get("/support/api/threads", headers={"cookie": raw})
    assert r.status_code == 401, (r.status_code, r.text)
    support_hub.reset_throttle()


def _set_cookie(c: TestClient, value: str) -> None:
    c.cookies.set(support_hub.COOKIE, value, path="/support")


def case_cookie_forged_from_password_alone_is_refused():
    support_hub.reset_throttle()
    sid, exp = "b" * 32, int(support_hub._clock()) + 3600
    old_key = hashlib.sha256(b"support-hub-session\0" + PASSWORD.encode()).digest()
    pw_key = hmac.new(hashlib.sha256(PASSWORD.encode()).digest(), b"support-hub-session\0", hashlib.sha256).digest()
    c = _hub_client()
    for key in (old_key, pw_key):
        for msg in (f"{sid}.{exp}", str(exp)):
            sig = hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()
            _set_cookie(c, f"{msg}.{sig}")
            assert c.get("/support/api/threads").status_code == 401
    support_hub.reset_throttle()


def case_signed_cookie_without_a_session_row_is_refused():
    support_hub.reset_throttle()
    sid, exp = "c" * 32, int(support_hub._clock()) + 3600
    c = _hub_client()
    _set_cookie(c, f"{sid}.{exp}.{support_hub._sign(sid, exp)}")
    assert c.get("/support/api/threads").status_code == 401
    support_hub.reset_throttle()


def case_repeated_bad_cookies_are_throttled():
    support_hub.reset_throttle()
    c = _hub_client()
    _set_cookie(c, "junk")
    for _ in range(support_hub.FAIL_LIMIT):
        assert c.get("/support/api/threads").status_code == 401
    r = c.get("/support/api/threads")
    assert r.status_code == 429 and r.headers.get("retry-after"), r.text
    assert c.post("/support/api/login", json={"password": PASSWORD}).status_code == 429
    assert _hub_client().get("/support/api/threads").status_code == 401
    support_hub.reset_throttle()


def case_cookie_dead_after_logout():
    c = _hub_owner()
    cookie = c.cookies.get(support_hub.COOKIE)
    assert c.get("/support/api/threads").status_code == 200
    assert c.post("/support/api/logout").status_code == 200
    replay = _hub_client()
    _set_cookie(replay, cookie)
    assert replay.get("/support/api/threads").status_code == 401
    support_hub.reset_throttle()


def case_password_change_signs_everyone_out():
    c = _hub_owner()
    with _env(SUPPORT_HUB_PASSWORD=PASSWORD + "-new"):
        assert c.get("/support/api/threads").status_code == 401
    assert c.get("/support/api/threads").status_code == 200
    support_hub.reset_throttle()


def case_parallel_wrong_logins_stay_within_limit():
    support_hub.reset_throttle()
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="203.0.113.9"))
    real = support_hub.client_addr.client_address
    support_hub.client_addr.client_address = lambda r: "203.0.113.9"
    statuses: list[int] = []
    gate = threading.Barrier(40)

    def hit():
        gate.wait()
        statuses.append(support_hub.login(req, support_hub.Login(password="nope")).status_code)
    try:
        threads = [threading.Thread(target=hit) for _ in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        support_hub.client_addr.client_address = real
    assert statuses.count(401) == support_hub.FAIL_LIMIT and statuses.count(429) == 40 - support_hub.FAIL_LIMIT, statuses
    support_hub.reset_throttle()


def case_instance_api_needs_token():
    c = _hub_client()
    q = {"instance": "AE", "user_key": "x"}
    assert c.get("/support/api/instance/unread", params=q).status_code == 401
    assert c.get("/support/api/instance/unread", params=q,
                 headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.post("/support/api/instance/messages", json={**q, "text": "x"},
                  headers={"Authorization": f"Bearer {TOKEN}x"}).status_code == 401
    assert c.get("/support/api/instance/unread", params=q, headers=INST).status_code == 200
    with _env(SUPPORT_HUB_TOKEN=None):
        assert c.get("/support/api/instance/unread", params=q,
                     headers={"Authorization": "Bearer "}).status_code == 401
    owner = _hub_owner()
    assert owner.get("/support/api/instance/unread", params=q).status_code == 401


def case_login_wrong_password_and_rate_limit():
    support_hub.reset_throttle()
    c = _hub_client()
    for _ in range(support_hub.FAIL_LIMIT):
        assert c.post("/support/api/login", json={"password": "nope"}).status_code == 401
    r = c.post("/support/api/login", json={"password": PASSWORD})
    assert r.status_code == 429 and r.headers.get("retry-after"), r.text
    support_hub.reset_throttle()
    r = c.post("/support/api/login", json={"password": PASSWORD})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    for flag in ("httponly", "secure", "samesite=strict", "path=/support"):
        assert flag in cookie, cookie
    assert c.get("/support/api/threads").status_code == 200
    assert c.post("/support/api/logout").status_code == 200
    assert c.get("/support/api/threads").status_code == 401


def case_global_fail_cap_spans_addresses():
    support_hub.reset_throttle()
    now = support_hub._clock()
    for i in range(support_hub.GLOBAL_FAIL_LIMIT):
        support_hub._record_fail(f"10.0.0.{i}", now)
    r = _hub_client().post("/support/api/login", json={"password": PASSWORD})
    assert r.status_code == 429
    support_hub.reset_throttle()


def case_identity_comes_from_session_not_body():
    support_api._unread.clear()
    r = CHATTER.post("/admin/support/messages", json={
        "text": "Need a faster vault search", "user_key": "spoof", "name": "Mallory",
        "role": "owner", "instance": "evil", "agency_id": "x"})
    assert r.status_code == 200, r.text
    assert r.json()["messages"][-1] == {**r.json()["messages"][-1], "from": "me",
                                        "text": "Need a faster vault search"}
    owner = _hub_owner()
    names = {t["name"] for t in owner.get("/support/api/threads").json()["threads"]}
    assert "Mallory" not in names
    t = _thread_of(owner, "chatter_a")
    assert (t["role"], t["instance"], t["agency_id"], t["agency_name"]) == (
        "chatter", "AE", IDS["agency_a_owner"], "Agency A"), t
    r = OWNER_A.post("/admin/support/messages", json={"text": "Owner here"})
    assert r.status_code == 200 and [m["text"] for m in r.json()["messages"]] == ["Owner here"]
    t = _thread_of(owner, "agency_a_owner")
    assert t["role"] == "owner"


def case_ingest_thread_reply_unread_read():
    support_api._unread.clear()
    assert CHATTER.post("/admin/support/messages", json={"text": "Bulk tags please"}).status_code == 200
    owner = _hub_owner()
    t = _thread_of(owner, "chatter_a")
    assert t["unread"] is True and t["last_text"] == "Bulk tags please"
    opened = owner.get(f"/support/api/threads/{t['id']}").json()
    assert [m["sender"] for m in opened["messages"]][-1] == "user"
    assert _thread_of(owner, "chatter_a")["unread"] is False
    assert CHATTER.get("/admin/support/unread").json() == {"configured": True, "unread": 0}
    support_api._unread.clear()
    r = owner.post(f"/support/api/threads/{t['id']}/reply", json={"text": "On it — next week"})
    assert r.status_code == 200 and r.json()["messages"][-1]["sender"] == "support"
    assert owner.post(f"/support/api/threads/{t['id']}/reply", json={"text": "   "}).status_code == 400
    assert CHATTER.get("/admin/support/unread").json() == {"configured": True, "unread": 1}
    msgs = CHATTER.get("/admin/support/thread").json()["messages"]
    assert msgs[-1]["from"] == "support" and msgs[-1]["text"] == "On it — next week"
    assert OWNER_A.get("/admin/support/unread").json()["unread"] == 0
    assert CHATTER.post("/admin/support/read").json()["ok"] is True
    assert CHATTER.get("/admin/support/unread").json()["unread"] == 0
    support_api._unread.clear()
    assert CHATTER.get("/admin/support/unread").json()["unread"] == 0


def case_unread_cached_30s():
    owner = _hub_owner()
    support_api._unread.clear()
    assert CHATTER.get("/admin/support/unread").json()["unread"] == 0
    t = _thread_of(owner, "chatter_a")
    owner.post(f"/support/api/threads/{t['id']}/reply", json={"text": "ping"})
    assert CHATTER.get("/admin/support/unread").json()["unread"] == 0
    real = support_api._clock
    support_api._clock = lambda: real() + support_api.UNREAD_TTL_S + 1
    try:
        assert CHATTER.get("/admin/support/unread").json()["unread"] == 1
    finally:
        support_api._clock = real
    CHATTER.post("/admin/support/read")


def case_not_configured_and_signed_out():
    with _env(SUPPORT_HUB_URL=None):
        assert CHATTER.get("/admin/support/unread").json() == {"configured": False}
        assert CHATTER.get("/admin/support/thread").json() == {"configured": False}
        assert CHATTER.post("/admin/support/messages", json={"text": "x"}).json() == {"configured": False}
    assert ANON.get("/admin/support/unread").status_code == 401
    assert ANON.post("/admin/support/messages", json={"text": "x"}).status_code == 401


def case_hub_down_is_502_not_crash():
    saved = support_api._transport
    support_api._transport = httpx.MockTransport(lambda req: httpx.Response(500))
    support_api._unread.clear()
    try:
        assert CHATTER.post("/admin/support/messages", json={"text": "x"}).status_code == 502
        assert CHATTER.get("/admin/support/unread").json() == {"configured": True, "unread": 0}
    finally:
        support_api._transport = saved


def case_share_token_gate_lets_only_the_hub_through():
    saved = server.SHARE_TOKEN
    server.SHARE_TOKEN = "gate-secret"
    try:
        c = _hub_client()
        assert c.get("/support").status_code == 200
        assert c.get("/support/api/threads").status_code == 401
        assert c.get("/admin/accounts").status_code == 401
        assert c.get("/supportx").status_code == 401
        with _env(SUPPORT_HUB_PASSWORD=None):
            assert c.get("/support").status_code == 401
    finally:
        server.SHARE_TOKEN = saved


def case_summarise_newest_first_and_no_key():
    owner = _hub_owner()
    seen = {}

    async def fake_chat(**kw):
        seen.update(kw)
        return SimpleNamespace(content="1. Vault search — 1 user — \"Need a faster vault search\"")
    real = support_hub.llm_client.chat
    support_hub.llm_client.chat = fake_chat
    try:
        r = owner.post("/support/api/summarise").json()
        assert r["summary"].startswith("1. Vault search") and r["threads"] == 2, r
        body = seen["messages"][1]["content"]
        assert seen["purpose"] == support_hub.PURPOSE and seen["account_id"] is None
        assert body.index("chatter_a") < body.index("agency_a_owner"), body
        assert "Team: On it — next week" in body and "install AE" in body
        assert seen["api_key"] is None
        os.environ["SUPPORT_HUB_DEEPSEEK_KEY"] = " hub-key "
        try:
            owner.post("/support/api/summarise")
        finally:
            del os.environ["SUPPORT_HUB_DEEPSEEK_KEY"]
        assert seen["api_key"] == "hub-key"

        async def no_key(**kw):
            raise LLMKeyError("missing", "deepseek", support_hub.PURPOSE, house=True)
        support_hub.llm_client.chat = no_key
        r = owner.post("/support/api/summarise").json()
        assert "no DeepSeek API key" in r["error"], r
    finally:
        support_hub.llm_client.chat = real


def case_send_rate_limit():
    c = _hub_client()
    who = {"instance": "AE", "user_key": f"rate:{uuid.uuid4().hex}", "name": "rate_user", "role": "owner"}
    for i in range(support_hub.SEND_LIMIT):
        assert c.post("/support/api/instance/messages", json={**who, "text": f"m{i}"}, headers=INST).status_code == 200
    assert c.post("/support/api/instance/messages", json={**who, "text": "one more"},
                  headers=INST).status_code == 429
    other = {**who, "user_key": f"rate:{uuid.uuid4().hex}"}
    assert c.post("/support/api/instance/messages", json={**other, "text": "hi"}, headers=INST).status_code == 200
    saved = support_api._transport
    support_api._transport = httpx.MockTransport(lambda req: httpx.Response(429, json={"detail": "send limit"}))
    try:
        r = CHATTER.post("/admin/support/messages", json={"text": "x"})
        assert r.status_code == 429 and "wait a few minutes" in r.json()["detail"], r.text
    finally:
        support_api._transport = saved


def _raw_post(path: str, headers: list[tuple[bytes, bytes]], length: int | None) -> tuple[int, int]:
    calls: list[int] = []

    head = (b'--zz\r\nContent-Disposition: form-data; name="photos"; filename="a.jpg"\r\n'
            b"Content-Type: image/jpeg\r\n\r\n")

    async def receive():
        calls.append(1)
        return {"type": "http.request", "body": head if len(calls) == 1 else b"x" * 65536, "more_body": True}
    out: dict[str, int] = {}

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
    hs = [(b"host", b"testserver"), (b"content-type", b"multipart/form-data; boundary=zz"), *headers]
    if length is not None:
        hs.append((b"content-length", str(length).encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
             "scheme": "https", "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "headers": hs, "client": ("203.0.113.5", 1234), "server": ("testserver", 443)}
    asyncio.run(server.app(scope, receive, send))
    return out["status"], len(calls)


def case_oversize_photo_posts_refused_before_body_is_read():
    support_hub.reset_throttle()
    big = 50 * 1024 * 1024
    bearer = [(b"authorization", f"Bearer {TOKEN}".encode())]
    assert _raw_post("/support/api/instance/messages/upload", [], big) == (401, 0)
    assert _raw_post("/support/api/threads/1/reply/upload", [], big) == (401, 0)
    assert _raw_post("/admin/support/messages/upload", [], big) == (401, 0)
    assert _raw_post("/support/api/instance/messages/upload", bearer, big) == (413, 0)
    cookie = _hub_owner().cookies.get(support_hub.COOKIE)
    owner = [(b"cookie", f"{support_hub.COOKIE}={cookie}".encode())]
    assert _raw_post("/support/api/threads/1/reply/upload", owner, big) == (413, 0)
    status, reads = _raw_post("/support/api/instance/messages/upload", bearer, None)
    assert status == 413 and reads <= support_photos.UPLOAD_CAP // 65536 + 2, (status, reads)
    support_hub.reset_throttle()


def _jpeg(w: int = 64, h: int = 48, orient: int | None = None) -> bytes:
    buf = io.BytesIO()
    kw = {}
    if orient is not None:
        ex = Image.Exif()
        ex[0x010F] = "TestCam"
        ex[0x0112] = orient
        kw["exif"] = ex.tobytes()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "JPEG", **kw)
    return buf.getvalue()


def _huge_header(w: int, h: int) -> bytes:
    raw = bytearray(_jpeg())
    at = raw.index(b"\xff\xc0")
    raw[at + 5:at + 9] = struct.pack(">HH", h, w)
    return bytes(raw)


def _files(*blobs: bytes) -> list:
    return [("photos", (f"p{i}.jpg", b, "image/jpeg")) for i, b in enumerate(blobs)]


def _hub_upload(c: TestClient, user_key: str, *blobs: bytes, text: str = ""):
    return c.post("/support/api/instance/messages/upload", headers=INST, files=_files(*blobs),
                  data={"instance": "AE", "user_key": user_key, "name": "photo_user", "role": "owner", "text": text})


def case_four_photos_roundtrip_crm_hub_owner_and_reply():
    support_hub.reset_throttle()
    r = CHATTER.post("/admin/support/messages/upload", data={"text": "see these"},
                     files=_files(_jpeg(orient=6), _jpeg(), _jpeg(), _jpeg()))
    assert r.status_code == 200, r.text
    last = r.json()["messages"][-1]
    assert last["from"] == "me" and last["text"] == "see these" and len(last["photos"]) == 4, last
    first = last["photos"][0]
    assert (first["w"], first["h"]) == (48, 64), first
    got = CHATTER.get(f"/admin/support/photos/{first['id']}")
    assert got.status_code == 200, got.text
    assert got.headers["content-type"] == "image/jpeg"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["content-security-policy"] == "default-src 'none'"
    assert got.headers["cache-control"] == "no-store"
    assert got.headers["content-disposition"] == "inline"
    with Image.open(io.BytesIO(got.content)) as im:
        assert im.format == "JPEG" and im.size == (48, 64)
        assert not im.getexif() and "exif" not in im.info, im.info
    owner = _hub_owner()
    t = _thread_of(owner, "chatter_a")
    opened = owner.get(f"/support/api/threads/{t['id']}").json()
    assert [p["id"] for p in opened["messages"][-1]["photos"]] == [p["id"] for p in last["photos"]]
    owned = owner.get(f"/support/api/photos/{first['id']}")
    assert owned.content == got.content and owned.headers["cache-control"] == "no-store"
    r = owner.post(f"/support/api/threads/{t['id']}/reply/upload", data={"text": ""}, files=_files(_jpeg(30, 20)))
    assert r.status_code == 200, r.text
    reply = r.json()["messages"][-1]
    assert reply["sender"] == "support" and reply["text"] == "" and len(reply["photos"]) == 1
    msgs = CHATTER.get("/admin/support/thread").json()["messages"]
    assert msgs[-1]["from"] == "support" and msgs[-1]["photos"] == reply["photos"]
    assert CHATTER.get(f"/admin/support/photos/{reply['photos'][0]['id']}").status_code == 200
    assert owner.post(f"/support/api/threads/{t['id']}/reply/upload", data={"text": "  "}).status_code == 400
    assert owner.post(f"/support/api/threads/{t['id']}/reply/upload", data={"text": "words only"}).status_code == 200
    body, _, _ = support_hub._digest_input()
    assert "User: see these [photo] [photo] [photo] [photo]" in body and "Team: [photo]" in body, body
    CHATTER.post("/admin/support/read")


def case_photo_of_another_thread_is_404_and_no_cookie_is_401():
    owner = _hub_owner()
    t = _thread_of(owner, "chatter_a")
    pid = owner.get(f"/support/api/threads/{t['id']}").json()["messages"][-2]["photos"][0]["id"]
    assert OWNER_A.get(f"/admin/support/photos/{pid}").status_code == 404
    assert _hub_client().get(f"/support/api/instance/photos/{pid}", headers=INST,
                             params={"instance": "AE", "user_key": "nobody"}).status_code == 404
    assert _hub_client().get(f"/support/api/instance/photos/{pid}",
                             params={"instance": "AE", "user_key": "nobody"}).status_code == 401
    assert owner.get("/support/api/photos/999999").status_code == 404
    assert _hub_client().get(f"/support/api/photos/{pid}").status_code == 401
    assert ANON.get(f"/admin/support/photos/{pid}").status_code == 401
    support_hub.reset_throttle()


def case_valid_session_never_throttled_on_shared_ip():
    owner = _hub_owner()
    cookie = owner.cookies.get(support_hub.COOKIE)
    t = _thread_of(owner, "chatter_a")
    pids = [p["id"] for m in owner.get(f"/support/api/threads/{t['id']}").json()["messages"] for p in m.get("photos", [])]
    assert len(pids) >= 4, pids
    bad = _hub_client()
    _set_cookie(bad, "junk")
    for _ in range(support_hub.FAIL_LIMIT):
        assert bad.get("/support/api/threads").status_code == 401
    assert bad.get("/support/api/threads").status_code == 429
    paths = [f"/support/api/photos/{pids[i % len(pids)]}" for i in range(12)]
    paths += [f"/support/api/threads/{t['id']}"] * 4 + ["/support/api/threads"] * 4
    statuses: list[int] = []
    gate = threading.Barrier(len(paths))

    def hit(path: str):
        c = _hub_client()
        _set_cookie(c, cookie)
        gate.wait()
        statuses.append(c.get(path).status_code)
    threads = [threading.Thread(target=hit, args=(p,)) for p in paths]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(paths) == 20 and statuses == [200] * 20, statuses
    support_hub.reset_throttle()


def case_send_limit_and_identity_checked_before_decode():
    c = _hub_client()
    key = f"early:{uuid.uuid4().hex}"
    who = {"instance": "AE", "user_key": key, "name": "early_user", "role": "owner"}
    for i in range(support_hub.SEND_LIMIT):
        assert c.post("/support/api/instance/messages", json={**who, "text": f"m{i}"}, headers=INST).status_code == 200
    decodes: list[int] = []
    real = support_photos._reencode
    support_photos._reencode = lambda raw: decodes.append(1) or real(raw)
    try:
        assert _hub_upload(c, key, _jpeg()).status_code == 429
        r = c.post("/support/api/instance/messages/upload", headers=INST, files=_files(_jpeg()),
                   data={"instance": "AE", "user_key": " "})
        assert r.status_code == 400, r.text
        assert _hub_owner().post("/support/api/threads/999999/reply/upload", files=_files(_jpeg())).status_code == 404
        assert decodes == [], decodes
    finally:
        support_photos._reencode = real
    support_hub.reset_throttle()


def case_bad_photos_refused():
    c = _hub_client()
    key = f"bad:{uuid.uuid4().hex}"
    assert _hub_upload(c, key, _huge_header(30000, 30000)).status_code == 400
    assert _hub_upload(c, key, _huge_header(3000, 3000)).status_code == 400
    assert _hub_upload(c, key, b"<html><script>alert(1)</script></html>").status_code == 400
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "PNG")
    assert _hub_upload(c, key, buf.getvalue()).status_code == 400
    assert _hub_upload(c, key, *[_jpeg()] * 5).status_code == 400
    assert _hub_upload(c, key, b"\xff\xd8" + b"0" * (support_photos.MAX_PHOTO_BYTES + 10)).status_code == 413
    assert _hub_upload(c, key).status_code == 400
    assert _hub_upload(c, key, text="text only").status_code == 200
    r = CHATTER.post("/admin/support/messages/upload", files=_files(*[_jpeg()] * 5))
    assert r.status_code == 400, r.text
    r = CHATTER.post("/admin/support/messages/upload", files=_files(b"<html></html>"))
    assert r.status_code == 400 and r.json()["detail"] == "Only photos (JPEG) can be sent.", r.text


def case_db_budget_refuses_new_photos():
    c = _hub_client()
    key = f"budget:{uuid.uuid4().hex}"
    with _env(SUPPORT_HUB_MAX_DB_GB="0.000001"):
        r = _hub_upload(c, key, _jpeg())
        assert r.status_code == 507, r.text
        assert _hub_upload(c, key, text="text still works").status_code == 200
        r = OWNER_A.post("/admin/support/messages/upload", files=_files(_jpeg()))
        assert r.status_code == 507 and "full" in r.json()["detail"], r.text


def case_support_traffic_not_audited():
    async def rows():
        async with get_session() as s:
            return list((await s.execute(select(Action.action))).scalars())
    assert not any("support" in a for a in asyncio.run(rows()))


_harness.run()
