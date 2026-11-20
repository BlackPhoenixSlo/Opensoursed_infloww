#!/usr/bin/env python3
"""
POST /api/of/v2/users/notifications/read — the bell's mark-read, OF web's `setNotificationsReadByType`.

The chat page's Notifications badge is OF's own counter (`/users/notifications/count` `all`); only this write lowers
it. Covered:
  case_client_sends_ofs_exact_request   POST {API_BASE}/users/notifications/read, no body, no trailing slash
  case_route_calls_of_busts_cache_returns_counters
  case_of_error_is_502_and_keeps_cache  a non-2xx from OF: surfaced, cached count untouched (badge not zeroed)
  case_fansly_shim_sends_bundle_ack     POST /notifications/ack {beforeAnd: <newest row id>, type: ""}, zeroed counters
  case_fansly_shim_nothing_unread_sends_nothing
  case_fansly_route_marks_read_busts_cache  the route on a real FanslyShimClient: no more 501
  case_fansly_ack_error_keeps_cache     a Fansly non-2xx raises (app handler: 502), cached count untouched
  case_client_without_read_flip_answers_501
  case_routes_registered                the path is on the app (no typed variant)

Run: ./venv/bin/python service/tests/test_notifications_mark_read.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import of_client  # noqa: E402
import relay_cache  # noqa: E402
import server  # noqa: E402
from fansly_client import FanslyAPIError  # noqa: E402
from fansly_shim import FanslyShimClient  # noqa: E402
from of_client import OFAPIError  # noqa: E402

_AID = "8802001"
_COUNTERS = {"all": 0, "tip": 0, "purchases": 0, "subscribed": 0}


class _FakeOF:
    def __init__(self) -> None:
        self.reads: list[str | None] = []
        self.fail: int | None = None

    def notifications_read(self):
        self.reads.append(None)
        if self.fail:
            status = self.fail

            class _Resp:
                status_code, text = status, '{"error":{"message":"boom"}}'
            raise OFAPIError(f"{status} for https://onlyfans.com/api2/v2/users/notifications/read", response=_Resp())
        return {"counters": dict(_COUNTERS)}


_fake = _FakeOF()
server._resolve_account_id = lambda _req=None: _AID  # type: ignore[assignment]
server._load_client = lambda _aid: _fake             # type: ignore[assignment]


def _reset() -> None:
    _fake.reads.clear()
    _fake.fail = None
    relay_cache.invalidate_money_feeds(_AID)


async def _seed_cache() -> None:
    """A badge of 7 and a feed page held in the relay's cache, as a recent bell open leaves them."""
    async def count():
        return {"all": 7, "tip": 2}

    async def feed():
        return {"list": [{"id": 1, "isRead": False}], "hasMore": False}
    await relay_cache.get_or_fetch("notifications_count", _AID, (), ttl_seconds=30.0, fetcher=count)
    await relay_cache.get_or_fetch("notifications", _AID, (20, 0, ""), ttl_seconds=30.0, fetcher=feed)


def case_client_sends_ofs_exact_request():
    sent: list[tuple] = []

    class _T:
        def post_json(self, url, **kw):
            sent.append((url, kw))
            return {"counters": {"all": 0}}
    of_client.OFClient.notifications_read(_T())
    assert sent == [(f"{of_client.API_BASE}/users/notifications/read", {})], sent


async def case_route_calls_of_busts_cache_returns_counters():
    _reset()
    await _seed_cache()
    got = await server.of_notifications_mark_read()
    assert _fake.reads == [None], _fake.reads
    assert got == {"counters": _COUNTERS}, got
    assert relay_cache.peek("notifications_count", _AID, ()) is None, "count still cached after mark-read"
    assert relay_cache.peek("notifications", _AID, (20, 0, "")) is None, "feed still cached after mark-read"


async def case_of_error_is_502_and_keeps_cache():
    _reset()
    await _seed_cache()
    _fake.fail = 500
    try:
        await server.of_notifications_mark_read()
    except server.HTTPException as e:
        assert e.status_code == 502, e.status_code
        assert e.detail["upstream_status"] == 500, e.detail
    else:
        raise AssertionError("OF 500 answered 2xx")
    assert relay_cache.peek("notifications_count", _AID, ()) == {"all": 7, "tip": 2}, "failed write dropped the badge"


# Fansly's feed, newest first, as `GET /notifications` answers it (ids/types invented; shape from RECIPES.md).
_ROWS = [
    {"id": "9300", "type": 3003, "acknowledgedAt": None, "createdAt": 1790000300},
    {"id": "9200", "type": 1002, "acknowledgedAt": 1790000250, "createdAt": 1790000200},
    {"id": "9100", "type": 7001, "acknowledgedAt": None, "createdAt": 1790000100},
]
_ZEROS = {"subscribes": 0, "tips": 0, "comments": 0, "mentions": 0, "hearts": 0, "gifts": 0, "all": 0}


def _shim(rows: list[dict], fail: bool = False, ignored: bool = False) -> tuple[FanslyShimClient, list[tuple]]:
    """The real shim class, no session: `_request` is the wire, recorded. An ack acks every row,
    unless Fansly `ignored` it (2xx, nothing changed)."""
    sent: list[tuple] = []
    shim = FanslyShimClient.__new__(FanslyShimClient)
    rows = [dict(r) for r in rows]

    def _request(method, path, *, params=None, json_body=None, **_kw):
        sent.append((method, path, json_body))
        if method == "GET" and path == "/notifications":
            return {"notifications": [dict(r) for r in rows]}
        if fail:
            raise FanslyAPIError("400 for https://apiv3.fansly.com/api/v1/notifications/ack")
        if not ignored:
            for r in rows:
                r["acknowledgedAt"] = r["acknowledgedAt"] or 1790000400
        return True
    shim._request = _request  # type: ignore[method-assign]
    return shim, sent


def case_fansly_shim_sends_bundle_ack():
    """Fansly web's `acknowledgeAllNotifications` (main.14d24b3e179efdb7.js `BJ`): POST /notifications/ack
    `{beforeAnd: <newest notification id>, type: <selected types joined, "" = all>}`."""
    shim, sent = _shim(_ROWS)
    got = shim.notifications_read()
    assert ("POST", "/notifications/ack", {"beforeAnd": "9300", "type": ""}) in sent, sent
    assert [s[0] for s in sent].count("POST") == 1, sent
    assert got == {"counters": _ZEROS}, got


def case_fansly_ack_ignored_keeps_the_count():
    """A 2xx ack that changed nothing (the body is bundle-derived): the answer is the feed re-read, not zeros."""
    shim, sent = _shim(_ROWS, ignored=True)
    got = shim.notifications_read()
    assert got["counters"]["all"] == 2, got
    assert sent[-1][:2] == ("GET", "/notifications"), sent


def case_fansly_shim_nothing_unread_sends_nothing():
    """Fansly web skips the write when its unread count is 0 or it holds no rows; so does the shim."""
    for rows in ([], [dict(r, acknowledgedAt=1790000400) for r in _ROWS]):
        shim, sent = _shim(rows)
        assert shim.notifications_read() == {"counters": _ZEROS}
        assert [s for s in sent if s[0] == "POST"] == [], sent


async def case_fansly_route_marks_read_busts_cache():
    _reset()
    await _seed_cache()
    shim, sent = _shim(_ROWS)
    server._load_client = lambda _aid: shim  # type: ignore[assignment]
    try:
        got = await server.of_notifications_mark_read()
    finally:
        server._load_client = lambda _aid: _fake  # type: ignore[assignment]
    assert got == {"counters": _ZEROS}, got
    assert ("POST", "/notifications/ack", {"beforeAnd": "9300", "type": ""}) in sent, sent
    assert relay_cache.peek("notifications_count", _AID, ()) is None, "count still cached after mark-read"
    assert relay_cache.peek("notifications", _AID, (20, 0, "")) is None, "feed still cached after mark-read"


async def case_fansly_ack_error_keeps_cache():
    _reset()
    await _seed_cache()
    shim, _sent = _shim(_ROWS, fail=True)
    server._load_client = lambda _aid: shim  # type: ignore[assignment]
    try:
        await server.of_notifications_mark_read()
    except FanslyAPIError:
        pass   # the app's FanslyAPIError handler answers it 502
    else:
        raise AssertionError("a rejected Fansly ack answered 2xx")
    finally:
        server._load_client = lambda _aid: _fake  # type: ignore[assignment]
    assert relay_cache.peek("notifications_count", _AID, ()) == {"all": 7, "tip": 2}, "failed write dropped the badge"


async def case_client_without_read_flip_answers_501():
    _reset()
    server._load_client = lambda _aid: object()  # type: ignore[assignment]
    try:
        await server.of_notifications_mark_read()
    except server.HTTPException as e:
        assert e.status_code == 501, e.status_code
    else:
        raise AssertionError("a client without notifications_read answered 2xx")
    finally:
        server._load_client = lambda _aid: _fake  # type: ignore[assignment]


def case_routes_registered():
    posts = {r.path for r in server.app.routes if "POST" in getattr(r, "methods", set())}
    assert "/api/of/v2/users/notifications/read" in posts
    assert "/api/of/v2/users/notifications/read/{type}" not in posts


_harness.run()
