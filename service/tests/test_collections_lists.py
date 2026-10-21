#!/usr/bin/env python3
"""OF Manager > Collections list writes: bulk add (POST /lists/users) and Clear list
(DELETE /lists/{id}/users), plus the client calls behind create, rename, delete and the
single add/remove the collections pages use; a list's Posts tab read
(GET /lists/{id}/posts, its query as OF's web client sends it, captured live); and
Search users (GET /lists/{id}/users `query`, OF's web client's param).

Each route passes its body to the fake client as is, and each client method sends
OF's own method, path and body (read from OF's web client, module 138255). An OF
rejection surfaces as the usual structured 502. Plain-assert, OF faked.

  case_routes_are_registered
  case_bulk_add_passes_through
  case_bulk_add_needs_users
  case_clear_list_passes_through
  case_client_requests
  case_list_posts_passes_through
  case_list_posts_request
  case_list_users_search
  case_list_id_is_validated
  case_of_error_is_502

Run: ./venv/bin/python service/tests/test_collections_lists.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

from fastapi import HTTPException  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402


class _Fake:
    def __init__(self, fail=False):
        self.calls: list[tuple] = []
        self.fail = fail

    def _maybe_fail(self):
        if self.fail:
            class R:
                status_code = 400
                text = '{"error":{"message":"List not found"}}'
            raise of_client.OFAPIError("400", response=R())

    def add_users_to_lists(self, users_by_list):
        self.calls.append(("add_users_to_lists", users_by_list))
        self._maybe_fail()
        return dict(users_by_list)

    def clear_list(self, list_id):
        self.calls.append(("clear_list", list_id))
        self._maybe_fail()
        return {"success": True}

    def list_users_in(self, list_id, *, limit=20, offset=0, query=None):
        self.calls.append(("list_users_in", list_id, limit, offset, query))
        self._maybe_fail()
        return {"list": [{"id": 901}], "hasMore": False}

    def list_posts_in(self, list_id, *, limit=10, offset=0, type=None):
        self.calls.append(("list_posts_in", list_id, limit, offset, type))
        self._maybe_fail()
        return {"list": [{"id": 5, "author": {"id": 901, "_view": "a"}}], "hasMore": False, "nextOffset": 10}


def _with(fake, fn):
    orig = server._get_client, server._resolve_account_id
    server._get_client = lambda: fake
    server._resolve_account_id = lambda _req=None: "acct-lists"
    try:
        return fn()
    finally:
        server._get_client, server._resolve_account_id = orig


def case_routes_are_registered():
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    for want in [
        ("POST", "/api/of/v2/lists"),
        ("PATCH", "/api/of/v2/lists/{list_id}"),
        ("DELETE", "/api/of/v2/lists/{list_id}"),
        ("POST", "/api/of/v2/lists/users"),
        ("DELETE", "/api/of/v2/lists/{list_id}/users"),
        ("POST", "/api/of/v2/lists/{list_id}/users/{user_id}"),
        ("DELETE", "/api/of/v2/lists/{list_id}/users/{user_id}"),
        ("GET", "/api/of/v2/lists/{list_id}/posts"),
    ]:
        assert want in routes, f"{want} missing"


def case_bulk_add_passes_through():
    fake = _Fake()
    out = _with(fake, lambda: server.of_add_users_to_lists({"7": [901, 902]}))
    assert fake.calls == [("add_users_to_lists", {"7": [901, 902]})], fake.calls
    assert out == {"7": [901, 902]}, out


def case_bulk_add_needs_users():
    for body in ({}, {"7": []}):
        fake = _Fake()
        try:
            _with(fake, lambda: server.of_add_users_to_lists(body))
        except HTTPException as e:
            assert e.status_code == 422, e.status_code
        else:
            raise AssertionError(f"expected a 422 for {body}")
        assert fake.calls == [], fake.calls


def case_clear_list_passes_through():
    fake = _Fake()
    out = _with(fake, lambda: server.of_clear_list("7"))
    assert fake.calls == [("clear_list", "7")], fake.calls
    assert out == {"success": True}, out


def case_client_requests():
    c = of_client.OFClient.__new__(of_client.OFClient)
    sent = []
    c.request_json = lambda method, path, **kw: sent.append((method, path, kw)) or {"ok": 1}
    base = of_client.API_BASE
    c.add_users_to_lists({"7": [901]})
    c.clear_list("7")
    c.create_list("Synthetic list")
    c.rename_list("7", "Renamed list")
    c.delete_list("7")
    c.add_user_to_list("8", 901)
    c.remove_user_from_list("7", 901)
    assert sent == [
        ("POST", f"{base}/lists/users", {"json_body": {"7": [901]}}),
        ("DELETE", f"{base}/lists/7/users", {}),
        ("POST", f"{base}/lists", {"json_body": {"name": "Synthetic list"}}),
        ("PATCH", f"{base}/lists/7", {"json_body": {"name": "Renamed list"}}),
        ("DELETE", f"{base}/lists/7", {}),
        ("POST", f"{base}/lists/8/users/901", {}),
        ("DELETE", f"{base}/lists/7/users/901", {}),
    ], sent


def case_list_posts_passes_through():
    fake = _Fake()
    out = _with(fake, lambda: server.of_list_posts_in("tagged", limit=20, offset=10, type="photos"))
    assert fake.calls == [("list_posts_in", "tagged", 20, 10, "photos")], fake.calls
    assert out["list"][0]["author"] == {"id": 901, "_view": "a"}, out


def case_list_posts_request():
    c = of_client.OFClient.__new__(of_client.OFClient)
    sent = []
    c.get_json = lambda path, **kw: sent.append((path, kw)) or {"list": []}
    base = of_client.API_BASE
    c.list_posts_in("tagged")
    c.list_posts_in("7", limit=20, offset=10, type="locked")
    assert sent == [
        (f"{base}/lists/tagged/posts", {"params": {"offset": 0, "limit": 10, "skip_users": "all"}}),
        (f"{base}/lists/7/posts", {"params": {"offset": 10, "limit": 20, "type": "locked", "skip_users": "all"}}),
    ], sent


def case_list_users_search():
    """Search users: the route passes `query` on (an empty one as none) and the client sends it as OF's own
    `query` param (module 138255); with no search the request is as before. Over 100 characters is a 422."""
    fake = _Fake()
    _with(fake, lambda: server.of_list_users_in("7", limit=50, offset=0, query="alpha"))
    _with(fake, lambda: server.of_list_users_in("7", limit=50, offset=0, query=""))
    assert fake.calls == [("list_users_in", "7", 50, 0, "alpha"), ("list_users_in", "7", 50, 0, None)], fake.calls
    c = of_client.OFClient.__new__(of_client.OFClient)
    sent = []
    c.get_json = lambda path, **kw: sent.append((path, kw)) or {"list": []}
    base = of_client.API_BASE
    c.list_users_in("7", limit=50)
    c.list_users_in("7", limit=50, query="alpha")
    assert sent == [
        (f"{base}/lists/7/users", {"params": {"limit": 50, "offset": 0}}),
        (f"{base}/lists/7/users", {"params": {"limit": 50, "offset": 0, "query": "alpha"}}),
    ], sent
    import os
    client = _harness.make_client()
    was = os.environ.get("ALLOW_ANONYMOUS_ADMIN")
    os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
    try:
        fake = _Fake()
        r = _with(fake, lambda: client.get("/api/of/v2/lists/7/users?limit=50&query=" + "a" * 101))
        assert r.status_code == 422, (r.status_code, r.text)
        r = _with(fake, lambda: client.get("/api/of/v2/lists/7/users?limit=50&query=Alpha%20One"))
        assert r.status_code == 200, (r.status_code, r.text)
        assert fake.calls == [("list_users_in", "7", 50, 0, "Alpha One")], fake.calls
    finally:
        if was is None:
            os.environ.pop("ALLOW_ANONYMOUS_ADMIN", None)
        else:
            os.environ["ALLOW_ANONYMOUS_ADMIN"] = was


def case_list_id_is_validated():
    """A list's id reaches OF's path only as a number or a built-in name: anything else is a 422, OF not called."""
    import os
    fake = _Fake()
    client = _harness.make_client()
    was = os.environ.get("ALLOW_ANONYMOUS_ADMIN")
    os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"  # the route's validation, not the sign-in gate (read per call)
    try:
        # Every /lists/{list_id} route: reads, rename, delete, add/remove one user, Clear list.
        routes = [("GET", "{}", None), ("GET", "{}/posts", None), ("GET", "{}/users", None),
                  ("PATCH", "{}", {"name": "Renamed list"}), ("DELETE", "{}", None),
                  ("POST", "{}/users/901", None), ("DELETE", "{}/users/901", None), ("DELETE", "{}/users", None)]
        for method, path, body in routes:
            for bad in ("7..", "7%3Fx=1", "fans%20x", "%2E%2E"):
                url = "/api/of/v2/lists/" + path.format(bad)
                r = _with(fake, lambda: client.request(method, url, json=body))
                assert r.status_code == 422, (method, url, r.status_code, r.text)
        assert fake.calls == [], fake.calls
        r = _with(fake, lambda: client.get("/api/of/v2/lists/tagged/posts?limit=10"))
        assert r.status_code == 200, (r.status_code, r.text)
        r = _with(fake, lambda: client.delete("/api/of/v2/lists/7/users"))
        assert r.status_code == 200, (r.status_code, r.text)
        assert fake.calls == [("list_posts_in", "tagged", 10, 0, None), ("clear_list", "7")], fake.calls
    finally:
        if was is None:
            os.environ.pop("ALLOW_ANONYMOUS_ADMIN", None)
        else:
            os.environ["ALLOW_ANONYMOUS_ADMIN"] = was


def case_of_error_is_502():
    for call in (
        lambda: server.of_add_users_to_lists({"7": [901]}),
        lambda: server.of_clear_list("7"),
        lambda: server.of_list_posts_in("7", limit=10, offset=0, type=None),
    ):
        try:
            _with(_Fake(fail=True), call)
        except HTTPException as e:
            assert e.status_code == 502, e.status_code
            assert e.detail["upstream_status"] == 400, e.detail
            assert "List not found" in e.detail["upstream_body"], e.detail
        else:
            raise AssertionError("expected a 502")


_harness.run()
