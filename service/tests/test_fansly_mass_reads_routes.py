#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

from sqlalchemy import delete, select, update  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts" / "demo-shots"))
sys.path.append(str(_ROOT / "fansly"))

client = _harness.make_client()

import accounts as account_registry  # noqa: E402
import audiences  # noqa: E402
import fansly_backend  # noqa: E402
import fansly_nova  # noqa: E402
import fansly_relay  # noqa: E402
import mass_broadcast_cache  # noqa: E402
import mass_queue_api  # noqa: E402
import messages  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Fan, MassBroadcastCache, MassMessageFunnel, MassRun, Message, User, UserAccount,
)

_TMP = tempfile.TemporaryDirectory(prefix="fansly_mass_reads_routes_")
account_registry.SESSIONS_DIR = Path(_TMP.name)
account_registry.ACCOUNTS_DIR = Path(_TMP.name) / "accounts"
account_registry.ACTIVE_FILE = Path(_TMP.name) / "active.json"
account_registry.MIGRATED_MARKER = Path(_TMP.name) / ".migrated"
os.environ.setdefault("DEMO_SHOTS_TMP", _TMP.name)

AID = fansly_nova.ACCOUNT
POST = int(fansly_nova.SCHEDULED_POST)
BROADCAST = 900539700124344901
SCHEDULED_BROADCAST = int(fansly_nova.SCHEDULED_BROADCAST)
OF_AID = "9999076"
OF_QUEUE = 76001
REFUSAL = "platform_lacks:unsend_mass_message"
FAN = 900539700124344321

fansly_relay.install(datetime.utcnow().isoformat())
SHIM = fansly_backend.get_client(AID)
_raw_request = SHIM._request
SHIM.log = []


def _logged(method, path, *, params=None, **kw):
    SHIM.log.append((method, path))
    if method == "POST" and path == f"/post/scheduled/{POST}/cancel":
        return {}
    return _raw_request(method, path, params=params, **kw)


SHIM._request = _logged


async def _seed_accounts() -> None:
    async with get_session() as s:
        s.add(User(id="owner-76", username="owner76", password="pw"))
        for aid in (AID, OF_AID):
            s.add(Account(id=aid, nickname=aid))
            s.add(UserAccount(user_id="owner-76", account_id=aid))
            s.add(Fan(account_id=aid, fan_id=FAN))


asyncio.run(_seed_accounts())
account_registry.save_meta(AID, {"id": AID, "nickname": "nova", "platform": "fansly"})
account_registry.save_meta(OF_AID, {"id": OF_AID, "nickname": "of"})


async def _seed_bookkeeping(aid: str, queue_id: int, *, cached: bool) -> None:
    sent = datetime.utcnow() - timedelta(hours=1)
    async with get_session() as s:
        funnel = MassMessageFunnel(name=f"funnel {aid} {queue_id}", opening_message="hey",
                                   steps_json=json.dumps([{"step": 1, "messages": ["m1"]}]))
        s.add(funnel)
        await s.flush()
        run = MassRun(account_id=aid, funnel_id=funnel.id, queue_id=queue_id, status="ok",
                      body="blast", sent_at=sent)
        s.add(run)
        await s.flush()
        s.add(Message(account_id=aid, fan_id=FAN, message_id=queue_id + 7, direction="out", body="blast",
                      created_at=sent, mass_run_id=run.id))
        if cached:
            s.add(MassBroadcastCache(account_id=aid, queue_id=queue_id, sent_at=sent, body_text="blast",
                                     is_canceled=False, can_unsend=True, fetched_at=datetime.utcnow()))


async def _rows(aid: str) -> dict:
    async with get_session() as s:
        cache = (await s.execute(select(
            MassBroadcastCache.queue_id, MassBroadcastCache.is_canceled, MassBroadcastCache.can_unsend)
            .where(MassBroadcastCache.account_id == aid))).all()
        runs = (await s.execute(select(MassRun.queue_id, MassRun.discovery_closed_at, MassRun.unsent_at)
                                .where(MassRun.account_id == aid))).all()
        mirror = (await s.execute(select(Message.message_id, Message.is_unsent)
                                  .where(Message.account_id == aid))).all()
    return {"cache": sorted(map(tuple, cache)), "runs": sorted(map(tuple, runs), key=str),
            "mirror": sorted(map(tuple, mirror))}


def _delete(aid: str, queue_id: int):
    SHIM.log.clear()
    with (patch.object(mass_broadcast_cache, "mark_canceled",
                       wraps=mass_broadcast_cache.mark_canceled) as mark,
          patch.object(audiences, "close_funnel_discovery_for_queue",
                       wraps=audiences.close_funnel_discovery_for_queue) as funnel,
          patch.object(messages, "mark_queue_unsent", wraps=messages.mark_queue_unsent) as mirror):
        before = asyncio.run(_rows(aid))
        r = client.delete(f"/api/of/v2/messages/queue/{queue_id}", headers={"x-account-id": aid})
        after = asyncio.run(_rows(aid))
    return r, before, after, (mark.call_count, funnel.call_count, mirror.call_count)


def _refused(r) -> None:
    assert r.status_code == 501, (r.status_code, r.text)
    assert r.json()["detail"] == REFUSAL, r.json()


def case_cached_broadcast_refuses_before_any_shim_call():
    asyncio.run(_seed_bookkeeping(AID, BROADCAST, cached=True))
    r, before, after, spies = _delete(AID, BROADCAST)
    _refused(r)
    assert SHIM.log == [], SHIM.log
    assert after == before, (before, after)
    assert spies == (0, 0, 0), spies


def case_uncached_unlisted_id_refuses_after_one_scheduled_read():
    asyncio.run(_seed_bookkeeping(AID, SCHEDULED_BROADCAST, cached=False))
    r, before, after, spies = _delete(AID, SCHEDULED_BROADCAST)
    _refused(r)
    assert SHIM.log == [("GET", "/post/scheduled")], SHIM.log
    assert after == before, (before, after)
    assert spies == (0, 0, 0), spies


def case_cached_and_listed_id_refuses_before_any_shim_call():
    asyncio.run(_seed_bookkeeping(AID, POST, cached=True))
    try:
        r, before, after, spies = _delete(AID, POST)
        _refused(r)
        assert SHIM.log == [], SHIM.log
        assert after == before, (before, after)
        assert spies == (0, 0, 0), spies
    finally:
        async def _uncache():
            async with get_session() as s:
                row = await s.get(MassBroadcastCache, (AID, POST))
                await s.delete(row)
        asyncio.run(_uncache())


def case_listed_post_cancels_with_no_mass_bookkeeping():
    r, before, after, spies = _delete(AID, POST)
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"success": True}, r.json()
    assert SHIM.log == [("GET", "/post/scheduled"), ("POST", f"/post/scheduled/{POST}/cancel")], SHIM.log
    assert after == before, (before, after)
    assert spies == (0, 0, 0), spies


class _OFClient:
    def __init__(self):
        self.calls: list[tuple] = []

    def cancel_scheduled(self, queue_id):
        self.calls.append(("cancel_scheduled", queue_id))
        return {"success": True}

    def schedules(self, **_kw):
        raise AssertionError("OnlyFans DELETE must not read schedules")


def case_onlyfans_delete_keeps_todays_request_and_bookkeeping():
    asyncio.run(_seed_bookkeeping(OF_AID, OF_QUEUE, cached=True))
    of = _OFClient()
    with patch.object(mass_queue_api, "_get_client", lambda: of):
        r, before, after, spies = _delete(OF_AID, OF_QUEUE)
    assert r.status_code == 200, (r.status_code, r.text)
    assert of.calls == [("cancel_scheduled", OF_QUEUE)], of.calls
    assert SHIM.log == [], SHIM.log
    assert spies == (1, 1, 1), spies
    assert before["cache"] == [(OF_QUEUE, False, True)] and after["cache"] == [(OF_QUEUE, True, False)], after
    (_, closed, unsent), = after["runs"]
    assert closed is not None and unsent is not None, after["runs"]
    assert after["mirror"] == [(OF_QUEUE + 7, True)], after["mirror"]


def case_stats_group_route_on_nova_returns_her_two_broadcasts_with_string_ids():
    SHIM.log.clear()
    now = datetime.utcnow()
    r = client.get("/api/of/v2/users/me/stats/messages/group", headers={"x-account-id": AID},
                   params={"startDate": (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"),
                           "endDate": (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")})
    assert r.status_code == 200, (r.status_code, r.text)
    body = r.json()
    assert [i["id"] for i in body["items"]] == ["900539700124344801", "900539700124344800"], body
    assert all(i["canUnsend"] is False for i in body["items"]), body
    assert (body["hasMore"], body["incomplete"]) == (False, False), body
    assert SHIM.log == [("GET", "/message/broadcast/stats")] * 2, SHIM.log


def case_queue_route_on_nova_pages_her_scheduled_broadcast_and_schedules_stay_posts_only():
    want = {"id": "900539700124344902", "text": "flash sale this weekend, watch your DMs"}
    for params, rows, more in (({}, [want], False), ({"limit": 1}, [want], False),
                               ({"limit": 1, "offset": 1}, [], False)):
        SHIM.log.clear()
        r = client.get("/api/of/v2/messages/queue", headers={"x-account-id": AID}, params=params)
        assert r.status_code == 200, (params, r.status_code, r.text)
        body = r.json()
        assert set(body) == {"list", "hasMore"} and body["hasMore"] is more, (params, body)
        assert [{k: i[k] for k in ("id", "text")} for i in body["list"]] == rows, (params, body)
        assert all(set(i) == {"id", "text", "scheduledDate"} and isinstance(i["scheduledDate"], str)
                   for i in body["list"]), (params, body)
        assert SHIM.log == [("GET", "/message/broadcast/scheduled")], (params, SHIM.log)
    SHIM.log.clear()
    r = client.get("/api/of/v2/schedules", headers={"x-account-id": AID})
    assert r.status_code == 200, (r.status_code, r.text)
    assert [i["id"] for i in r.json()["list"]] == [fansly_nova.SCHEDULED_POST], r.json()
    assert SHIM.log == [("GET", "/post/scheduled")], SHIM.log


def case_queued_message_and_buyers_on_nova_answer_501_before_any_request():
    for path, params, detail in (
            (f"/api/of/v2/messages/queue/{SCHEDULED_BROADCAST}", {},
             "queued_message: no single-row GET; its only caller is the queued-message edit, graded I"),
            ("/api/of/v2/messages/queue/buyers", {"queue_id": BROADCAST},
             "mass_message_buyers: no buyers in broadcast stats; a priced broadcast needs a Proof purchase")):
        SHIM.log.clear()
        r = client.get(path, headers={"x-account-id": AID}, params=params)
        assert r.status_code == 501, (path, r.status_code, r.text)
        assert r.json()["detail"] == detail, (path, r.json())
        assert SHIM.log == [], (path, SHIM.log)


def case_unknown_account_is_refused_before_any_request():
    r, before, after, spies = _delete("9999077", BROADCAST)
    assert r.status_code == 404, (r.status_code, r.text)
    assert r.json()["detail"]["error"] == "unknown_account", r.json()
    assert SHIM.log == [], SHIM.log
    assert after == before, (before, after)
    assert spies == (0, 0, 0), spies


STATS = ("GET", "/message/broadcast/stats")
NOVA_NEWEST = "900539700124344801"
NOVA_BOTH = [NOVA_NEWEST, "900539700124344800"]
OF_IDS = [3218765432, 2**53 - 1]
ADMIN_KEYS = {"account_id", "days_back", "items"}
FLAG_KEYS = {"hasMore", "incomplete"}


async def _uncache_all(aid: str) -> None:
    async with get_session() as s:
        await s.execute(delete(MassBroadcastCache).where(MassBroadcastCache.account_id == aid))


def _restart() -> None:
    mass_broadcast_cache._WALKS.clear()


def _admin(method: str, aid: str, days_back: int, limit: int) -> dict:
    SHIM.log.clear()
    path = "/admin/mass-messages/refresh" if method == "POST" else "/admin/mass-messages"
    r = client.request(method, path, headers={"x-account-id": aid},
                       params={"days_back": days_back, "limit": limit})
    assert r.status_code == 200, (method, r.status_code, r.text)
    body = r.json()
    extra = {"written"} if method == "POST" else set()
    assert set(body) == ADMIN_KEYS | FLAG_KEYS | extra, body
    return body


def case_nova_admin_read_walks_cold_refresh_and_after_restart_but_never_warm_per_window():
    asyncio.run(_uncache_all(AID))
    _restart()
    for step, method, gets in (("cold", "GET", 1), ("refresh", "POST", 1), ("warm", "GET", 0),
                               ("restart", "GET", 1)):
        if step == "restart":
            _restart()
        for days_back, has_more in ((30, True), (3, False)):
            body = _admin(method, AID, days_back, 1)
            assert SHIM.log == [STATS] * gets, (step, days_back, SHIM.log)
            assert [i["id"] for i in body["items"]] == [NOVA_NEWEST], (step, days_back, body)
            assert all(i["canUnsend"] is False for i in body["items"]), (step, days_back, body)
            assert (body["hasMore"], body["incomplete"]) == (has_more, False), (step, days_back, body)
        if step == "warm":
            body = _admin("GET", AID, 30, 100)
            assert SHIM.log == [STATS] * 2, SHIM.log
            assert [i["id"] for i in body["items"]] == NOVA_BOTH, body
            assert (body["hasMore"], body["incomplete"]) == (False, False), body


def _stalled_stats(page_for):
    def _request(method, path, *, params=None, **kw):
        SHIM.log.append((method, path))
        if (method, path) == STATS:
            return page_for(params["before"])
        return _raw_request(method, path, params=params, **kw)
    return patch.object(SHIM, "_request", _request)


def case_nova_admin_read_on_a_repeated_cursor_answers_incomplete():
    asyncio.run(_uncache_all(AID))
    _restart()
    nova_page = _raw_request("GET", "/message/broadcast/stats", params={"before": "0"})
    with _stalled_stats(lambda _before: nova_page):
        body = _admin("GET", AID, 30, 100)
    assert SHIM.log == [STATS] * 2, SHIM.log
    assert [i["id"] for i in body["items"]] == NOVA_BOTH, body
    assert (body["hasMore"], body["incomplete"]) == (True, True), body


def case_nova_admin_refresh_at_the_page_cap_answers_incomplete():
    asyncio.run(_uncache_all(AID))
    _restart()
    future = int(time.time()) + 10 * 86400

    def _page(before):
        nxt = (int(before) or 900000000000000000) - 1
        return {"messages": [{"id": str(nxt), "type": 3, "content": "future", "createdAt": future,
                              "attachments": [], "stats": {"total": 0, "delivered": 0, "read": 0}}]}
    with _stalled_stats(_page):
        body = _admin("POST", AID, 30, 100)
    assert SHIM.log == [STATS] * 20, len(SHIM.log)
    assert body["items"] == [], body
    assert (body["hasMore"], body["incomplete"]) == (True, True), body


class _OFHistory:
    def __init__(self):
        self.calls: list[dict] = []

    def mass_message_history(self, **kw):
        self.calls.append(kw)
        return {"items": [{"id": i, "date": (datetime.utcnow() - timedelta(hours=n + 2)).isoformat() + "+00:00",
                           "text": f"of {i}"} for n, i in enumerate(OF_IDS)], "hasMore": False}


async def _seed_of_cache(fetched_at: datetime) -> None:
    async with get_session() as s:
        for n, qid in enumerate(OF_IDS):
            s.add(MassBroadcastCache(account_id=OF_AID, queue_id=qid, body_text=f"of {qid}",
                                     sent_at=datetime.utcnow() - timedelta(hours=n + 2), fetched_at=fetched_at))


async def _age_of_cache() -> None:
    async with get_session() as s:
        await s.execute(update(MassBroadcastCache).where(MassBroadcastCache.account_id == OF_AID)
                        .values(fetched_at=datetime.utcnow() - timedelta(days=2)))


def _of_admin(of: _OFHistory) -> dict:
    with patch.object(server, "_load_client", lambda aid: of):
        r = client.get("/admin/mass-messages", headers={"x-account-id": OF_AID},
                       params={"days_back": 30, "limit": 100})
    assert r.status_code == 200, (r.status_code, r.text)
    body = r.json()
    assert [i["id"] for i in body["items"]] == OF_IDS, body
    assert all(type(i["id"]) is int for i in body["items"]), body
    return body


def case_onlyfans_admin_read_keeps_int_ids_todays_staleness_and_no_flags_until_walked():
    asyncio.run(_uncache_all(OF_AID))
    _restart()
    asyncio.run(_seed_of_cache(datetime.utcnow()))
    of = _OFHistory()
    body = _of_admin(of)
    assert of.calls == [], of.calls
    assert set(body) == ADMIN_KEYS, body
    asyncio.run(_age_of_cache())
    body = _of_admin(of)
    assert len(of.calls) == 1, of.calls
    assert (body["hasMore"], body["incomplete"]) == (False, False), body
    body = _of_admin(of)
    assert len(of.calls) == 1, of.calls
    assert (body["hasMore"], body["incomplete"]) == (False, False), body


if __name__ == "__main__":
    with client:
        assert client.post("/auth/login", json={"username": "owner76", "password": "pw"}).status_code == 200
        _harness.run()
