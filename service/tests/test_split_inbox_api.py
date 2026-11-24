#!/usr/bin/env python3
"""
split_inbox_api — the Split Inbox store on account_ai_config.split_inbox_json
(ADR-0004; docs/spec/phase-02-fan-list-pane.md, Contracts).

Drives GET/PUT /admin/split-inbox over HTTP through the harness client against
the temp DB, so router registration and the session middleware are exercised.
Cookie cases follow test_chatter_auth.py: an owner, one Creator of hers, and a
chatter linked to her. Covers the unset default, an owner's round trip, the
owner gate (chatter GET 200 / PUT 403, anonymous 401), 422 on a bad count or a
non-object assignments, dropped out-of-range entries and unknown keys, the
start-up catch-up that adds the column to an existing database, the fan id mod
N group rule, and a bound chatter's view: `my_group`, and the /chats choke point
serving only that group's fans (owner and unbound chatter unfiltered).

Fixture identifiers are invented (this repo mirrors to a public one).

Run: ./venv/bin/python service/tests/test_split_inbox_api.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import sqlite3  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from db.engine import get_session, init_db  # noqa: E402
from db.models import Account, AccountAiConfig, Chatter, ChatterUser, User, UserAccount  # noqa: E402
import relay_cache  # noqa: E402
import split_inbox  # noqa: E402

client = _harness.make_client()
import server  # noqa: E402 — already imported by make_client; fresh clients below
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402

ACCOUNT = "acct_split_owner"
PASSWORD = "secretpw"
UNSET = {"group_count": 1, "assignments": {}, "chatter_groups": {}}
CHATTER_ID = uuid.uuid4().hex
CHATTER2_ID = uuid.uuid4().hex


async def _seed() -> None:
    owner = uuid.uuid4().hex
    chatter = CHATTER_ID
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(User(id=owner, username="splitowner", password=PASSWORD))
        s.add(Account(id=ACCOUNT, nickname="split model", color="#aaaaaa"))
        s.add(UserAccount(user_id=owner, account_id=ACCOUNT))
        s.add(Chatter(id=chatter, username="splitchatter", password=PASSWORD,
                      display_name="Splitchatter", created_at=now, last_seen_at=now))
        s.add(Chatter(id=CHATTER2_ID, username="splitchatter2", password=PASSWORD,
                      display_name="Splitchatter2", created_at=now, last_seen_at=now))
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=chatter, user_id=owner, created_at=now))
        s.add(ChatterUser(chatter_id=CHATTER2_ID, user_id=owner, created_at=now))
    # An install from before role enforcement was on by default: its logins hold Admin.
    await seed_pre_enforcement_install()


asyncio.run(_seed())


def _owner() -> TestClient:
    c = TestClient(server.app)
    r = c.post("/auth/login", json={"username": "splitowner", "password": PASSWORD})
    assert r.status_code == 200, f"owner login failed: {r.status_code} {r.text}"
    return c


def _chatter(username: str = "splitchatter") -> TestClient:
    c = TestClient(server.app)
    r = c.post("/chatter/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, f"chatter login failed: {r.status_code} {r.text}"
    return c


def _get(c: TestClient):
    return c.get(f"/admin/split-inbox?account_id={ACCOUNT}")


def _put(c: TestClient, config):
    return c.put("/admin/split-inbox", json={"account_id": ACCOUNT, "config": config})


async def _stored() -> str | None:
    async with get_session() as s:
        row = await s.get(AccountAiConfig, ACCOUNT)
    return None if row is None else row.split_inbox_json


def _columns() -> set[str]:
    c = sqlite3.connect(str(_harness.DB_PATH))
    try:
        return {r[1] for r in c.execute("PRAGMA table_info(account_ai_config)")}
    finally:
        c.close()


# ── cases ─────────────────────────────────────────────────────────────

def case_get_on_an_unset_creator_returns_the_default():
    r = _get(_owner())
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"account_id": ACCOUNT, "config": UNSET, "my_group": None}, r.json()


def case_an_owner_put_then_get_round_trips():
    owner = _owner()
    cfg = {"group_count": 3, "assignments": {"501": 2, "502": 3}, "chatter_groups": {"c1": 2}}
    r = _put(owner, cfg)
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"account_id": ACCOUNT, "config": cfg}, r.json()
    r = _get(owner)
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"account_id": ACCOUNT, "config": cfg, "my_group": None}, r.json()


def case_a_chatter_reads_but_cannot_save_and_anonymous_gets_401():
    before = asyncio.run(_stored())
    chatter = _chatter()
    r = _get(chatter)
    assert r.status_code == 200, ("a chatter filters by group, so reads the split", r.status_code, r.text)
    r = _put(chatter, {"group_count": 9, "assignments": {}})
    assert r.status_code == 403, ("a chatter cannot change the split", r.status_code, r.text)
    assert asyncio.run(_stored()) == before, "a refused save must not write"

    anon = TestClient(server.app)
    assert _get(anon).status_code == 401, _get(anon).status_code
    r = _put(anon, {"group_count": 2, "assignments": {}})
    assert r.status_code == 401, (r.status_code, r.text)


def case_a_bad_count_or_non_object_assignments_is_422():
    owner = _owner()
    before = asyncio.run(_stored())
    for bad in (
        {"group_count": 0, "assignments": {}},
        {"group_count": 10, "assignments": {}},
        {"group_count": "x", "assignments": {}},
        {"group_count": 2, "assignments": [1, 2]},
        {"group_count": 2, "assignments": "1:2"},
        {"group_count": 2, "assignments": {}, "chatter_groups": [1]},
    ):
        r = _put(owner, bad)
        assert r.status_code == 422, (bad, r.status_code, r.text)
    assert asyncio.run(_stored()) == before, "a rejected save must not write"


def case_out_of_range_entries_and_unknown_keys_are_dropped():
    owner = _owner()
    r = _put(owner, {
        "group_count": 2,
        "assignments": {"601": 1, "602": 3, "603": 0, "604": "2", "605": 2, "606": None},
        "chatter_groups": {"a": 1, "b": 3, "c": True},
        "employee_ids": {"1": [7]},
    })
    assert r.status_code == 200, (r.status_code, r.text)
    want = {"group_count": 2, "assignments": {"601": 1, "605": 2}, "chatter_groups": {"a": 1}}
    assert r.json()["config"] == want, r.json()
    assert json.loads(asyncio.run(_stored())) == want, asyncio.run(_stored())
    assert _get(owner).json()["config"] == want


def case_the_start_up_catch_up_adds_the_column_back():
    """The relay never runs Alembic: an existing database gains the column only
    through init_db()'s additive catch-up (test_automation_queue_indexes.py)."""
    c = sqlite3.connect(str(_harness.DB_PATH))
    try:
        c.execute("ALTER TABLE account_ai_config DROP COLUMN split_inbox_json")
        c.commit()
    finally:
        c.close()
    assert "split_inbox_json" not in _columns(), "setup failed: the column survived the DROP"

    asyncio.run(init_db())

    assert "split_inbox_json" in _columns(), "init_db() did not add split_inbox_json back"


def case_the_group_rule_is_fan_id_mod_n_plus_one_and_a_move_wins():
    cfg = {"group_count": 3, "assignments": {"10": 3}, "chatter_groups": {}}
    assert split_inbox.group_of(9, cfg) == 1
    assert split_inbox.group_of("11", cfg) == 3
    assert split_inbox.group_of(10, cfg) == 3, "an explicit move wins"
    assert split_inbox.group_of("9223372036854775807", cfg) == 9223372036854775807 % 3 + 1
    assert split_inbox.group_of("abc", cfg) == 1, "a non-numeric id is group 1"
    assert split_inbox.group_of(-4, cfg) == 1


def _chats_page(*_a, **_k):
    return {"list": [{"withUser": {"id": i}} for i in (300, 301, 302, 303)], "hasMore": True, "asked_at": 0}


def _fans(c: TestClient) -> tuple[list[int], bool]:
    r = c.get("/api/of/v2/chats?limit=4&offset=0", headers={"X-Account-Id": ACCOUNT})
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json()["scanned"] == 4, r.json()
    return [row["withUser"]["id"] for row in r.json()["list"]], r.json()["hasMore"]


def case_a_bound_chatter_sees_only_its_group_on_chats_and_owner_sees_all():
    owner = _owner()
    r = _put(owner, {"group_count": 2, "assignments": {"301": 1},
                     "chatter_groups": {CHATTER_ID: 1}})
    assert r.status_code == 200, (r.status_code, r.text)
    real_page, real_client = server._assemble_chats_page, server._get_client
    real_get = server.account_registry.get_account
    from types import SimpleNamespace
    writes = []

    def mark_all():
        writes.append(ACCOUNT)
        return {"reason": "ack_rejected"}

    of = SimpleNamespace(mark_all_chats_read=mark_all)
    server._assemble_chats_page, server._get_client = _chats_page, lambda: of
    server.account_registry.get_account = lambda aid: {"id": aid} if aid == ACCOUNT else real_get(aid)
    relay_cache.invalidate("list_chats", ACCOUNT)
    try:
        chatter = _chatter()
        assert _get(chatter).json() == {
            "account_id": ACCOUNT, "config": {"group_count": 2, "assignments": {"301": 1}}, "my_group": 1,
        }, "a chatter gets its group, not the binding map"
        response = chatter.post("/api/of/v2/chats/mark-as-read", headers={"X-Account-Id": ACCOUNT})
        assert response.status_code == 409 and writes == [], (response.text, writes)
        assert _fans(chatter) == ([300, 301, 302], True), "group 1 = even ids + the move; hasMore stays OF's"
        assert _fans(owner) == ([300, 301, 302, 303], True), "the owner is unfiltered"
        assert _get(_chatter("splitchatter2")).json()["my_group"] is None
        assert _fans(_chatter("splitchatter2"))[0] == [300, 301, 302, 303], "an unbound chatter is unfiltered"
        dual = _owner()
        dual.post("/chatter/login", json={"username": "splitchatter", "password": PASSWORD})
        assert _fans(dual)[0] == [300, 301, 302, 303], "a User cookie wins (DA-1)"
        _put(owner, {"group_count": 1, "assignments": {}, "chatter_groups": {}})
        assert _fans(chatter)[0] == [300, 301, 302, 303], "an unsplit Creator is unfiltered at once"
    finally:
        server._assemble_chats_page, server._get_client = real_page, real_client
        server.account_registry.get_account = real_get
        relay_cache.invalidate("list_chats", ACCOUNT)


def case_users_me_withholds_inbox_count_for_bound_chatter():
    owner = _owner()
    assert _put(owner, {"group_count": 2, "chatter_groups": {CHATTER_ID: 1}}).status_code == 200

    async def seed():
        return await relay_cache.get_or_fetch(
            "users_me", ACCOUNT, ("users_me",), ttl_seconds=60,
            fetcher=lambda: {"id": ACCOUNT, "chatMessagesCount": 9},
        )

    relay_cache.invalidate("users_me", ACCOUNT)
    asyncio.run(seed())
    try:
        from unittest.mock import patch
        route = "/api/of/v2/users/me"
        headers = {"X-Account-Id": ACCOUNT}
        with patch.object(server.account_registry, "get_account", return_value={"id": ACCOUNT}):
            for path in (route, route + "?max_age=3600"):
                response = _chatter().get(path, headers=headers)
                assert response.status_code == 200 and response.json() == {"id": ACCOUNT}, response.text
                assert owner.get(path, headers=headers).json()["chatMessagesCount"] == 9
    finally:
        relay_cache.invalidate("users_me", ACCOUNT)


def case_sse_frames_are_gated_by_the_bound_group():
    import events
    import events_decide as ed
    split_inbox.remember(ACCOUNT, {"group_count": 2, "assignments": {}, "chatter_groups": {CHATTER_ID: 2}})
    msg = lambda fan: {"api2_chat_message": {"fromUser": {"id": fan}}, "__account_id": ACCOUNT}
    out = {"api2_chat_message": {"fromUser": {"id": ACCOUNT}, "toUser": {"id": 7}},
           "__account_id": ACCOUNT, "__fan_id": 7}
    assert ed.frame_fan_id(msg(5)) == 5 and ed.frame_fan_id(out) == 7
    assert ed.frame_fan_id({"chat_typing": {"fan_id": 4}, "__account_id": ACCOUNT}) == 4
    sub = events._Sub("all", frozenset({ACCOUNT}), frozenset(), chatter=CHATTER_ID)
    assert events._for(sub, msg(5)) is not None, "odd id: group 2"
    assert events._for(sub, msg(6)) is None, "even id: group 1, not this chatter's"
    assert events._for(sub, out) is not None and events._for(sub, {**out, "__fan_id": 8}) is None
    assert events._wants(sub, {"creator_refreshed": {"account_id": ACCOUNT}, "__account_id": ACCOUNT})
    owner_sub = events._Sub("all", frozenset({ACCOUNT}), frozenset())
    assert events._for(owner_sub, msg(6)) is not None
    frame = events.ew.Frame({"creator_refreshed": {"account_id": ACCOUNT, "values": {"unread_total": {"n": 9}, "x": 1}},
                             "__account_id": ACCOUNT})
    assert events._for(sub, frame)["creator_refreshed"]["values"] == {"x": 1}, "whole-inbox count stripped"
    assert events._for(owner_sub, frame) is frame
    warmed = events.ew.Frame({"creator_warmed": {"account_id": ACCOUNT, "roster": {"unread": 9}, "now": 1},
                              "__account_id": ACCOUNT})
    assert "roster" not in events._for(sub, warmed)["creator_warmed"]
    split_inbox.remember(ACCOUNT, split_inbox.unset())


async def case_outbound_echo_group_applies_live_and_on_replay():
    import events
    from unittest.mock import AsyncMock

    split_inbox.remember(ACCOUNT, {"group_count": 2, "assignments": {}, "chatter_groups": {CHATTER_ID: 2}})
    accounts = frozenset({ACCOUNT})
    q = events._register("all", accounts, frozenset(), False, None, CHATTER_ID).q
    try:
        async def echo(fan):
            await events.broadcast({"api2_chat_message": {"chatUserId": str(fan), "id": fan},
                                    "__account_id": ACCOUNT})

        await echo(101)
        cursor = q.get_nowait().eid
        await echo(102)
        await echo(103)
        live = []
        while not q.empty():
            live.append(q.get_nowait()["api2_chat_message"]["id"])
        request = AsyncMock()
        request.is_disconnected.return_value = True
        replay = b"".join([chunk async for chunk in events.sse_stream(
            request, "all", accounts=accounts, chatter=CHATTER_ID, last_event_id=cursor,
        )])
        assert b'"chatUserId": "103"' in replay and b'"chatUserId": "102"' not in replay, replay
        assert live == [103], live
    finally:
        await events.unsubscribe("all", q)
        split_inbox.remember(ACCOUNT, split_inbox.unset())


async def case_get_started_before_put_cannot_restore_binding():
    from contextlib import asynccontextmanager
    from unittest.mock import patch
    import split_inbox_api as api

    aid = ACCOUNT
    old = {"group_count": 2, "chatter_groups": {CHATTER_ID: 1}}
    revoked = {"group_count": 2}
    with patch.object(api, "assert_owner"), patch.object(api, "assert_account_owned"):
        await api.put_split_inbox(api._ConfigBody(account_id=aid, config=old))
        read_finished = asyncio.Event()
        release = asyncio.Event()
        first = True

        @asynccontextmanager
        async def pause_first_read():
            nonlocal first
            pause = first
            first = False
            async with get_session() as session:
                yield session
            if pause:
                read_finished.set()
                await release.wait()

        with patch.object(api, "get_session", pause_first_read):
            read = asyncio.create_task(api.get_split_inbox(aid))
            try:
                await asyncio.wait_for(read_finished.wait(), 2)
                await api.put_split_inbox(api._ConfigBody(account_id=aid, config=revoked))
            finally:
                release.set()
                response = await read
        assert response["config"]["chatter_groups"] == {}
        assert not split_inbox.bound_cached(CHATTER_ID, aid)


def _toast(i, fan=None, how="related"):
    t = {"id": i, "type": "favorited", "text": "x"}
    if how == "related" and fan is not None:
        t["data"] = {"relatedUser": {"id": fan}}
    elif how == "replacements":
        t["data"] = {"replacements": {"{RELATED_USER_ID}": fan}}
    elif how == "from":
        t["fromUser"] = {"id": fan}
    return t


def case_toasts_reach_a_bound_chatter_per_entry_on_sse():
    import events
    import events_decide as ed
    assert [ed.toast_fan_id(_toast(1, 5, h)) for h in ("related", "replacements", "from")] == [5, 5, 5]
    assert ed.toast_fan_id(_toast(1)) is None
    split_inbox.remember(ACCOUNT, {"group_count": 2, "assignments": {}, "chatter_groups": {CHATTER_ID: 2}})
    try:
        sub = events._Sub("all", frozenset({ACCOUNT}), frozenset(), chatter=CHATTER_ID)
        owner_sub = events._Sub("all", frozenset({ACCOUNT}), frozenset())
        mixed = events.ew.Frame({"toasts": [_toast(1, 5), _toast(2, 6, "from"), _toast(3)], "__account_id": ACCOUNT})
        assert events._for(sub, mixed) is not None
        assert [t["id"] for t in events._for(sub, mixed)["toasts"]] == [1, 3], "group 1's toast dropped"
        assert events._for(owner_sub, mixed) is mixed
        other = events.ew.Frame({"toasts": [_toast(4, 8, "replacements")], "__account_id": ACCOUNT})
        assert events._for(sub, other) is None, "only another group's toasts: no frame"
        assert events._for(owner_sub, other) is not None
        mine = events.ew.Frame({"toasts": [_toast(5, 7)], "__account_id": ACCOUNT})
        assert events._for(sub, mine) is mine
    finally:
        split_inbox.remember(ACCOUNT, split_inbox.unset())


def case_toasts_reach_a_bound_chatter_per_entry_on_push():
    from types import SimpleNamespace

    import push_notice as pn
    import push_send
    split_inbox.remember(ACCOUNT, {"group_count": 2, "assignments": {}, "chatter_groups": {CHATTER_ID: 2}})
    try:
        notices = pn.notices_for({"toasts": [_toast(1, 5), _toast(2, 6), _toast(3)], "__account_id": ACCOUNT})
        assert [n.fan_id for n in notices] == [5, 6, None]
        chatter = SimpleNamespace(kind="chatter", principal_id=CHATTER_ID)
        owner = SimpleNamespace(kind="user", principal_id="u1")
        unbound = SimpleNamespace(kind="chatter", principal_id=CHATTER2_ID)
        assert [n.id for n in notices if push_send._in_group(chatter, n)] == ["1", "3"]
        assert [n.id for n in notices if push_send._in_group(owner, n)] == ["1", "2", "3"]
        assert [n.id for n in notices if push_send._in_group(unbound, n)] == ["1", "2", "3"]
        dm = pn.notices_for({"api2_chat_message": {"id": 9, "fromUser": {"id": 6}, "text": "hi"},
                             "__account_id": ACCOUNT})
        assert dm[0].fan_id == 6 and not push_send._in_group(chatter, dm[0])
        assert "fan_id" not in pn.payload(dm[0])
    finally:
        split_inbox.remember(ACCOUNT, split_inbox.unset())


def case_a_bound_chatter_s_badge_counts_its_group_only():
    import accounts_admin_api as aa
    window = {"list": [
        {"withUser": {"id": 400}, "unreadMessagesCount": 1, "lastMessage": {"fromUser": {"id": 400}}},
        {"withUser": {"id": 401}, "unreadMessagesCount": 1, "lastMessage": {"fromUser": {"id": 401}}},
        {"withUser": {"id": 403}, "unreadMessagesCount": 2, "lastMessage": {"fromUser": {"id": 403}}},
    ], "hasMore": False}
    asyncio.run(relay_cache.get_or_fetch("list_chats", ACCOUNT, aa._ROSTER_WINDOW_KEY,
                                         ttl_seconds=600, fetcher=lambda: window))
    aa._amber_ctx[ACCOUNT] = ("999", frozenset())
    aa._roster_last[ACCOUNT] = {"unread": 3, "owe_reply": 0, "as_of": 1}
    real_watcher = aa.account_registry.is_watcher
    aa.account_registry.is_watcher = lambda aid: False
    try:
        _put(_owner(), {"group_count": 2, "assignments": {}, "chatter_groups": {CHATTER_ID: 2}})
        counts = lambda c: c.get("/admin/accounts/roster-counts").json()["counts"][ACCOUNT]
        assert counts(_owner())["unread"] == 3, "the owner keeps the whole inbox"
        assert counts(_chatter())["unread"] == 2, "group 2 = odd ids: 401 and 403"
        assert counts(_chatter("splitchatter2"))["unread"] == 3, "an unbound chatter keeps the whole inbox"
    finally:
        aa.account_registry.is_watcher = real_watcher
        relay_cache.invalidate("list_chats", ACCOUNT)
        _put(_owner(), {"group_count": 1, "assignments": {}, "chatter_groups": {}})


async def case_concurrent_puts_publish_in_commit_order():
    from contextlib import asynccontextmanager
    from unittest.mock import patch

    import httpx
    import split_inbox_api

    committed, release = asyncio.Event(), asyncio.Event()
    first_save = True

    @asynccontextmanager
    async def delay_first_publish():
        nonlocal first_save
        delay, first_save = first_save, False
        async with get_session() as session:
            yield session
        if delay:
            committed.set()
            await release.wait()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                 base_url="http://testserver", cookies=dict(_owner().cookies)) as c:
        async def save(count):
            response = await c.put("/admin/split-inbox", json={
                "account_id": ACCOUNT, "config": {"group_count": count},
            })
            assert response.status_code == 200, response.text

        with patch.object(split_inbox_api, "get_session", delay_first_publish):
            first = asyncio.create_task(save(2))
            await asyncio.wait_for(committed.wait(), 5)
            second = asyncio.create_task(save(3))
            try:
                await asyncio.wait({second}, timeout=0.5)
            finally:
                release.set()
                await asyncio.gather(first, second)
        stored = json.loads(await _stored())
        assert stored["group_count"] == 3, stored
        cached = split_inbox.heal(ACCOUNT, split_inbox.unset(), since=-1)
        assert cached == stored, (cached, stored)


_harness.run()
