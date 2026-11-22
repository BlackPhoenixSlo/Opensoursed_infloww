"""A headerless request resolves ONE account for its whole life (W30 #1).

Cached/coalesced reads key by `_current_aid()` and fetch through `_get_client()`, which
re-resolves. The default (active) account flipping A -> B between the two calls cached B's
body under A. The active-account fallback is now read once per request (request.scope).
"""
import _harness  # noqa: F401  (first: temp DB)

_harness.bootstrap()

from starlette.requests import Request  # noqa: E402

import server  # noqa: E402


def _req() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/of/v2/chats/1",
                    "query_string": b"", "headers": []})


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


_harness.run()
