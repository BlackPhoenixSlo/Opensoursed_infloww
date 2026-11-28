import _harness  # noqa: F401  (first: temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402
import uuid  # noqa: E402

from starlette.requests import Request  # noqa: E402

import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import User  # noqa: E402


def _req() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/of/v2/chats/1",
                    "query_string": b"", "headers": []})


# The active-account fallback flipping between cache-key and client resolution cached B's body under A.
def case_cache_key_account_equals_client_account_when_active_flips():
    flips = iter(["acct-A", "acct-B", "acct-B", "acct-B"])
    loaded = []
    orig = (server.account_registry.get_active_account_id, server._load_client)
    server.account_registry.get_active_account_id = lambda: next(flips)
    server._load_client = lambda aid: loaded.append(aid) or aid
    token = server._request_ctx.set(_req())
    try:
        key_aid = server._current_aid()
        client_aid = server._get_client()
    finally:
        server._request_ctx.reset(token)
        server.account_registry.get_active_account_id, server._load_client = orig
    assert key_aid == client_aid == "acct-A", (key_aid, client_aid, loaded)


def case_a_new_request_sees_the_new_active_account():
    orig = server.account_registry.get_active_account_id
    try:
        server.account_registry.get_active_account_id = lambda: "acct-A"
        assert server._resolve_account_id(_req()) == "acct-A"
        server.account_registry.get_active_account_id = lambda: "acct-B"
        assert server._resolve_account_id(_req()) == "acct-B"
    finally:
        server.account_registry.get_active_account_id = orig


def case_an_unknown_named_account_answers_a_machine_readable_404():
    from fastapi import HTTPException
    req = Request({"type": "http", "method": "GET", "path": "/api/of/v2/chats",
                   "query_string": b"", "headers": [(b"x-account-id", b"70001383")]})
    try:
        server._resolve_account_id(req)
    except HTTPException as e:
        assert e.status_code == 404, e.status_code
        assert e.detail == {"error": "unknown_account", "message": "Unknown account_id '70001383'"}, e.detail
    else:
        raise AssertionError("an unknown account resolved")


def case_the_chat_list_route_carries_the_unknown_account_code():
    async def owner() -> None:
        async with get_session() as s:
            s.add(User(id=uuid.uuid4().hex, username="pin-boss", password="pw"))
    asyncio.run(owner())
    http = _harness.make_client()
    assert http.post("/auth/login", json={"username": "pin-boss", "password": "pw"}).status_code == 200
    r = http.get("/api/of/v2/chats?limit=10", headers={"X-Account-Id": "70001383"})
    assert r.status_code == 404, (r.status_code, r.text)
    assert r.json()["detail"]["error"] == "unknown_account", r.text


_harness.run()
