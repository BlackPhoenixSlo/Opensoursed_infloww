#!/usr/bin/env python3
"""/push/* routes (push_api) on the real app with real owner / chatter logins:
auth 401 / impersonation 403, key 503 while push is off, PUT upsert + re-bind only with matching
keys (409), key sizes + SSRF 400, cap 10, 20 PUT/min 429, DELETE + /push/test ownership,
logout deletes the subs of every principal cookie the request carried (only that session's),
two racing first PUTs of one endpoint end as one row (IntegrityError retried as the update).
Run: venv/bin/python -m pytest service/tests/test_push_api.py -q"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # pytest: tests/ is a package
import _harness  # noqa: E402  (first: temp DB)

import asyncio  # noqa: E402
import base64  # noqa: E402
import contextlib  # noqa: E402
import os  # noqa: E402
import secrets  # noqa: E402
import time  # noqa: E402

os.environ.setdefault("VAPID_SUBJECT", "mailto:push-test@example.com")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from sqlalchemy import select  # noqa: E402

_harness.bootstrap()
import _agency_fixtures as fx  # noqa: E402
import auth  # noqa: E402
import chatters  # noqa: E402
import push_api  # noqa: E402
import push_send  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import PushSubscription  # noqa: E402

IDS = fx.seed_two_agencies()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _keys() -> dict:
    pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"p256dh": _b64(pub), "auth": _b64(secrets.token_bytes(16))}


def _ep() -> str:
    return f"https://fcm.googleapis.com/fcm/send/{secrets.token_hex(8)}"


def _body(ep=None, keys=None, types=("purchases", "tip")) -> dict:
    return {"endpoint": ep or _ep(), "keys": keys or _keys(), "types": list(types), "platforms": {"onlyfans": True}}


def _rows(**where) -> list:
    async def q():
        async with get_session() as s:
            stmt = select(PushSubscription)
            for k, v in where.items():
                stmt = stmt.where(getattr(PushSubscription, k) == v)
            return (await s.execute(stmt)).scalars().all()
    return asyncio.run(q())


def _fresh():
    push_api._puts.clear()
    push_send._disabled = None


def test_auth_required_and_impersonation_403():
    _fresh()
    anon = _harness.make_client()
    assert anon.get("/push/key").status_code == 401
    assert anon.put("/push/subscription", json=_body()).status_code == 401
    master = fx.login_owner("agency_master")
    r = master.post("/admin/impersonate", json={"user_id": IDS["agency_a_owner"],
                                                "admin_password": os.environ["ADMIN_PASSWORD"]})
    assert r.status_code == 200, r.text
    assert master.get("/push/key").status_code == 403


def test_key_and_503_when_disabled():
    _fresh()
    c = fx.login_owner("agency_a_owner")
    r = c.get("/push/key")
    assert r.status_code == 200 and r.json()["key"] == push_send.public_key()
    assert len(push_send.b64d(r.json()["key"])) == 65
    push_send._disabled = "push is off: set VAPID_SUBJECT"
    try:
        r = c.get("/push/key")
        assert r.status_code == 503 and "VAPID_SUBJECT" in r.json()["detail"]["reason"]
        assert c.put("/push/subscription", json=_body()).status_code == 503
    finally:
        push_send._disabled = None


def test_subject_resolution():
    env = {k: os.environ.pop(k, None) for k in ("VAPID_SUBJECT", "SITE_URL")}
    try:
        assert push_send.subject()[0] is None
        os.environ["SITE_URL"] = "http://localhost:3001"
        assert push_send.subject()[0] is None
        os.environ["SITE_URL"] = "https://app.example.com"
        assert push_send.subject() == ("mailto:admin@app.example.com", "")
        os.environ["VAPID_SUBJECT"] = "mailto:ops@127.0.0.1"
        assert push_send.subject()[0] is None
        os.environ["VAPID_SUBJECT"] = "https://x.example.org"
        assert push_send.subject()[0] == "https://x.example.org"
    finally:
        for k, v in env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def test_put_upsert_and_rebind():
    _fresh()
    a, b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    body = _body()
    r1 = a.put("/push/subscription", json=body)
    assert r1.status_code == 200, r1.text
    sid = r1.json()["id"]
    assert a.put("/push/subscription", json={**body, "types": ["message"]}).json()["id"] == sid
    row = _rows(id=sid)[0]
    assert (row.principal_kind, row.principal_id) == ("user", IDS["agency_a_owner"]) and row.types == '["message"]'
    assert row.issued_ms > 0 and push_send._subs[sid].types == frozenset({"message"})
    assert b.put("/push/subscription", json={**body, "keys": _keys()}).status_code == 409
    assert _rows(id=sid)[0].principal_id == IDS["agency_a_owner"], "409 left the row alone"
    r = b.put("/push/subscription", json=body)
    assert r.status_code == 200 and r.json()["id"] == sid
    assert _rows(id=sid)[0].principal_id == IDS["agency_b_owner"]
    assert push_send._subs[sid].principal_id == IDS["agency_b_owner"]


def test_put_validation():
    _fresh()
    a = fx.login_owner("agency_a_owner")
    k = _keys()
    for bad in ({"p256dh": k["p256dh"][:-4], "auth": k["auth"]}, {"p256dh": k["p256dh"], "auth": _b64(b"x" * 15)},
                {"p256dh": "!!!", "auth": k["auth"]}):
        assert a.put("/push/subscription", json=_body(keys=bad)).status_code == 400
    # userinfo URLs built with {}: a literal user@host reads as an email to the public leak gate
    for ep in ("http://fcm.googleapis.com/x", "https://evil.example.com/x", f"https://{'u'}@fcm.googleapis.com/x",
               "https://fcm.googleapis.com:8443/x", "http://127.0.0.1:9/x"):
        assert a.put("/push/subscription", json=_body(ep=ep)).status_code == 400, ep
    assert a.put("/push/subscription", json=_body(ep="https://fcm.googleapis.com/" + "a" * 2100)).status_code == 422
    sid = a.put("/push/subscription", json=_body(types=("purchases", "bogus"))).json()["id"]
    assert _rows(id=sid)[0].types == '["purchases"]'


def test_cap_and_rate():
    _fresh()
    c = fx.login_chatter("chatter_b")
    ids = []
    for _ in range(12):
        r = c.put("/push/subscription", json=_body())
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
        time.sleep(0.002)
    mine = {r.id for r in _rows(principal_kind="chatter", principal_id=IDS["chatter_b"])}
    assert mine == set(ids[-10:]), "oldest two evicted"
    assert not set(ids[:2]) & set(push_send._subs)
    codes = [c.put("/push/subscription", json=_body()).status_code for _ in range(10)]
    assert codes.count(429) == 2 and codes[-1] == 429, codes


def test_delete_and_test_ownership():
    _fresh()
    a, b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    body = _body()
    sid = a.put("/push/subscription", json=body).json()["id"]
    assert b.post("/push/test", json={"id": sid}).status_code == 404
    assert b.request("DELETE", "/push/subscription", json={"endpoint": body["endpoint"]}).json() == {"deleted": 0}
    assert _rows(id=sid)
    assert a.request("DELETE", "/push/subscription", json={"endpoint": body["endpoint"]}).json() == {"deleted": 1}
    assert not _rows(id=sid) and sid not in push_send._subs


def test_logout_forgets_every_cookie_principal():
    _fresh()
    owner, chatter = fx.login_owner("agency_a_owner"), fx.login_chatter("chatter_a")
    time.sleep(0.01)
    other = fx.login_owner("agency_a_owner")       # a second session of the same owner
    s_owner = owner.put("/push/subscription", json=_body()).json()["id"]
    s_chat = chatter.put("/push/subscription", json=_body()).json()["id"]
    s_other = other.put("/push/subscription", json=_body()).json()["id"]
    both = _harness.make_client()
    both.cookies.set(auth.COOKIE_NAME, owner.cookies.get(auth.COOKIE_NAME))
    both.cookies.set(chatters.COOKIE_NAME, chatter.cookies.get(chatters.COOKIE_NAME))
    assert both.post("/auth/logout").status_code == 200
    assert not _rows(id=s_owner) and not _rows(id=s_chat), "both principals' subs gone"
    assert _rows(id=s_other) and s_other in push_send._subs, "the other session keeps its sub"
    assert s_owner not in push_send._subs and s_chat not in push_send._subs
    c2 = fx.login_chatter("chatter_a")
    s3 = c2.put("/push/subscription", json=_body()).json()["id"]
    assert c2.post("/chatter/logout").status_code == 200 and not _rows(id=s3)


def test_audit_skips_push():
    import audit_log
    assert any(p == "/push" for p in audit_log._AUDIT_SKIP_PREFIXES)


def test_concurrent_first_put_one_row():
    """Both PUTs read "no row" (held at a barrier after their SELECT), both insert: the loser's
    unique violation is retried as the update, so both answer the same id."""
    _fresh()
    a = fx.login_owner("agency_a_owner")
    pid, issued = auth.parse_cookie_issued(a.cookies.get(auth.COOKIE_NAME))
    body = push_api._SubBody(**_body())
    real = push_api.get_session

    async def go():
        arrived, both = [0], asyncio.Event()

        @contextlib.asynccontextmanager
        async def gated():
            async with real() as s:
                orig, first = s.execute, [True]

                async def execute(*args, **kw):
                    r = await orig(*args, **kw)
                    if first[0] and not both.is_set():
                        first[0] = False
                        arrived[0] += 1
                        if arrived[0] == 2:
                            both.set()
                        await asyncio.wait_for(both.wait(), 5)
                    return r
                s.execute = execute
                yield s
        push_api.get_session = gated
        try:
            return await asyncio.gather(*(push_api._save("user", pid, issued, body) for _ in range(2)),
                                        return_exceptions=True)
        finally:
            push_api.get_session = real
    ids = asyncio.run(go())
    assert all(isinstance(i, str) for i in ids) and ids[0] == ids[1], ids
    assert [r.id for r in _rows(endpoint=body.endpoint)] == [ids[0]] and ids[0] in push_send._subs


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
