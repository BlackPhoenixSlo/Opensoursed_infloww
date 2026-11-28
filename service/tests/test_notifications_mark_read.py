#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

import accounts as account_registry  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="notifications_mark_read_")
account_registry.SESSIONS_DIR = Path(_TMP.name)
account_registry.ACCOUNTS_DIR = Path(_TMP.name) / "accounts"
account_registry.ACTIVE_FILE = Path(_TMP.name) / "active.json"
account_registry.MIGRATED_MARKER = Path(_TMP.name) / ".migrated"

import of_client  # noqa: E402
import relay_cache  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, User, UserAccount  # noqa: E402
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
_real_resolve = server._resolve_account_id
server._resolve_account_id = lambda _req=None: _AID  # type: ignore[assignment]
server._load_client = lambda _aid: _fake             # type: ignore[assignment]


def _reset() -> None:
    _fake.reads.clear()
    _fake.fail = None
    relay_cache.invalidate_money_feeds(_AID)


async def _seed_cache() -> None:
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


_ROWS = [
    {"id": "9300", "type": 3003, "acknowledgedAt": None, "createdAt": 1790000300},
    {"id": "9200", "type": 1002, "acknowledgedAt": 1790000250, "createdAt": 1790000200},
    {"id": "9100", "type": 7001, "acknowledgedAt": None, "createdAt": 1790000100},
]
_ZEROS = {"subscribes": 0, "tips": 0, "comments": 0, "mentions": 0, "hearts": 0, "gifts": 0, "all": 0}


def _shim(rows: list[dict], ignored: bool = False) -> tuple[FanslyShimClient, list[tuple]]:
    sent: list[tuple] = []
    shim = FanslyShimClient.__new__(FanslyShimClient)
    rows = [dict(r) for r in rows]

    def _request(method, path, *, params=None, json_body=None, **_kw):
        sent.append((method, path, json_body))
        if method == "GET" and path == "/notifications":
            return {"notifications": [dict(r) for r in rows]}
        if method == "GET" and path == "/notifications/unack":
            unread = [r["type"] for r in rows if not r["acknowledgedAt"]]
            return [{"type": t, "total": unread.count(t)} for t in sorted(set(unread))]
        if not ignored:
            for r in rows:
                r["acknowledgedAt"] = r["acknowledgedAt"] or 1790000400
        return True
    shim._request = _request  # type: ignore[method-assign]
    return shim, sent


def _ack(shim: FanslyShimClient) -> dict:
    return FanslyShimClient.notifications_read.__wrapped__(shim)


def case_fansly_shim_sends_bundle_ack():
    shim, sent = _shim(_ROWS)
    got = _ack(shim)
    assert ("POST", "/notifications/ack", {"beforeAnd": "9300", "type": ""}) in sent, sent
    assert [s[0] for s in sent].count("POST") == 1, sent
    assert got == {"counters": _ZEROS}, got


def case_fansly_ack_ignored_keeps_the_count():
    shim, sent = _shim(_ROWS, ignored=True)
    got = _ack(shim)
    assert got["counters"]["all"] == 2, got
    assert sent[-1][:2] == ("GET", "/notifications/unack"), sent


def case_fansly_shim_nothing_unread_sends_nothing():
    for rows in ([], [dict(r, acknowledgedAt=1790000400) for r in _ROWS]):
        shim, sent = _shim(rows)
        assert _ack(shim) == {"counters": _ZEROS}
        assert [s for s in sent if s[0] == "POST"] == [], sent


FANSLY_AID = "8802011"
OF_AID = "8802012"
http = _harness.make_client()


async def _seed_accounts() -> None:
    async with get_session() as s:
        boss = User(id=uuid.uuid4().hex, username="mark_read_boss", password="pw")
        s.add_all([boss, Account(id=FANSLY_AID, nickname=FANSLY_AID), Account(id=OF_AID, nickname=OF_AID)])
        await s.flush()
        s.add_all([UserAccount(user_id=boss.id, account_id=FANSLY_AID),
                   UserAccount(user_id=boss.id, account_id=OF_AID)])

asyncio.run(_seed_accounts())
account_registry.save_meta(FANSLY_AID, {"id": FANSLY_AID, "nickname": FANSLY_AID, "platform": "fansly"})
account_registry.save_meta(OF_AID, {"id": OF_AID, "nickname": OF_AID, "platform": "onlyfans"})
assert http.post("/auth/login", json={"username": "mark_read_boss", "password": "pw"}).status_code == 200


def _post_read(aid: str, client):
    with (patch.object(server, "_resolve_account_id", _real_resolve),
          patch.object(server, "_load_client", lambda _aid: client)):
        return http.post("/api/of/v2/users/notifications/read", headers={"X-Account-Id": aid})


def case_fansly_route_answers_501_before_any_shim_request():
    shim, sent = _shim(_ROWS)
    r = _post_read(FANSLY_AID, shim)
    assert r.status_code == 501, (r.status_code, r.text)
    assert r.json() == {"detail": "mark notifications read: not on this platform"}, r.json()
    assert sent == [], sent


def case_onlyfans_route_still_marks_read():
    _reset()
    r = _post_read(OF_AID, _fake)
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"counters": _COUNTERS}, r.json()
    assert _fake.reads == [None], _fake.reads


def case_routes_registered():
    posts = {r.path for r in server.app.routes if "POST" in getattr(r, "methods", set())}
    assert "/api/of/v2/users/notifications/read" in posts
    assert "/api/of/v2/users/notifications/read/{type}" not in posts


_harness.run()
