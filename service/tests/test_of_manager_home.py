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
  case_stories_feed_warns_when_it_would_go_empty
  case_streams_feed_and_highlight_requests

Run: ./venv/bin/python service/tests/test_of_manager_home.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import logging  # noqa: E402

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


class _Tap(logging.Handler):
    """The of-client logger's warnings."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class _Resp:
    status_code = 404


def _stories_warnings(answer) -> list[str]:
    """stories_feed's warnings when OF's GET /stories gives `answer` (an exception is raised)."""
    def _get(path, **_kw):
        assert path == f"{BASE}/stories", path
        if isinstance(answer, Exception):
            raise answer
        return answer

    tap, log = _Tap(), logging.getLogger("of-client")
    log.addHandler(tap)
    try:
        c = _client()
        c.get_json = _get
        try:
            c.stories_feed()
        except of_client.OFAPIError:
            pass
    finally:
        log.removeHandler(tap)
    return [m for m in tap.lines if m.startswith("stories_feed")]


def case_stories_feed_warns_when_it_would_go_empty():
    # 02-gaps G5: OF's web client reads /stories/map now; if OF retires
    # /stories, the strip's other creators must not vanish without a trace.
    assert _stories_warnings([]) == [], "an empty feed is a normal answer"
    assert _stories_warnings({"list": []}) == [], "a {list: [...]} page is one rowsOf reads"
    (line,) = _stories_warnings({"error": "gone"})
    assert "answered no list (dict)" in line, line
    (line,) = _stories_warnings(of_client.OFAPIError("404", response=_Resp()))
    assert "refused GET /stories (404)" in line, line
    assert _stories_warnings(of_client.OFDeniedError("ours")) == [], "the relay's own refusal is not OF's"


def case_streams_feed_and_highlight_requests():
    # The story strip's live and scheduled streams (OF's streams/feed) and a
    # highlight's stories (OF's stories/highlights/{id}), each one GET.
    got = []

    def _get(path, **kw):
        got.append((path, kw))
        return {"list": []}

    c = _client()
    c.get_json = _get
    orig = server._get_client
    server._get_client = lambda: c
    try:
        _route("GET", "/api/of/v2/streams/feed")()
        _route("GET", "/api/of/v2/stories/highlights/{highlight_id}")(1195022)
    finally:
        server._get_client = orig
    assert got == [(f"{BASE}/streams/feed", {"params": {"limit": 10}}),
                   (f"{BASE}/stories/highlights/1195022", {})], got


_harness.run()
