#!/usr/bin/env python3
"""OF Manager home: the post actions' exact OF requests.

Like sends the post's author id, as OF's web client does (module 458723 `p`,
`/posts/{id}/favorites/{authorId}`); archive is OF's "Archive post"
(`458723.hf`, `POST /posts/{id}/archive`, no query). Plain-assert, OF faked
(no request leaves the process).

  case_like_sends_the_author_id
  case_like_defaults_to_me
  case_like_route_forwards_author_id
  case_archive_posts_archive
  case_archive_route_is_registered
  case_feed_delete_comment_pin_requests

Run: ./venv/bin/python service/tests/test_of_manager_home.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import of_client  # noqa: E402
import server  # noqa: E402

BASE = of_client.API_BASE


def _client():
    """An OFClient whose every request is recorded instead of sent."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.user_id = "4242"
    c.sent = []
    c.request_json = lambda method, path, **kw: c.sent.append((method, path, kw)) or {"success": True}
    return c


def _route(method, path):
    """The endpoint function behind `method path`."""
    for r in server.app.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", ()):
            return r.endpoint
    raise AssertionError(f"{method} {path} missing")


def _with_client(fn):
    c = _client()
    orig = server._get_client
    server._get_client = lambda: c
    try:
        fn()
    finally:
        server._get_client = orig
    return c.sent


def case_like_sends_the_author_id():
    c = _client()
    c.like_post(77, 515)
    assert c.sent == [("POST", f"{BASE}/posts/77/favorites/515", {})], c.sent


def case_like_defaults_to_me():
    c = _client()
    c.like_post(77)
    assert c.sent == [("POST", f"{BASE}/posts/77/favorites/4242", {})], c.sent


def case_like_route_forwards_author_id():
    like = _route("POST", "/api/of/v2/posts/{post_id}/like")
    sent = _with_client(lambda: (like(77, 515), like(78, None)))
    assert sent == [("POST", f"{BASE}/posts/77/favorites/515", {}),
                    ("POST", f"{BASE}/posts/78/favorites/4242", {})], sent


def case_archive_posts_archive():
    c = _client()
    c.archive_post(77)
    assert c.sent == [("POST", f"{BASE}/posts/77/archive", {})], c.sent


def case_archive_route_is_registered():
    archive = _route("POST", "/api/of/v2/posts/{post_id}/archive")
    sent = _with_client(lambda: archive(77))
    assert sent == [("POST", f"{BASE}/posts/77/archive", {})], sent


def case_feed_delete_comment_pin_requests():
    # The other routes the home page uses, as OF's web client sends them.
    sent = _with_client(lambda: (
        _route("DELETE", "/api/of/v2/posts/{post_id}")(77),
        _route("POST", "/api/of/v2/posts/{post_id}/comments")(77, server._TextBody(text="Synthetic comment")),
        _route("POST", "/api/of/v2/posts/{post_id}/pin")(77),
    ))
    assert sent == [
        ("DELETE", f"{BASE}/posts/77", {}),
        ("POST", f"{BASE}/posts/77/comments", {"json_body": {"text": "Synthetic comment"}}),
        ("POST", f"{BASE}/posts/77/pin", {"params": {"format": "status"}}),
    ], sent


_harness.run()
