#!/usr/bin/env python3
"""
split_inbox_api — the Split Inbox store on account_ai_config.split_inbox_json
(ADR-0004; docs/spec/phase-02-fan-list-pane.md, Contracts).

Drives GET/PUT/PATCH /admin/split-inbox over HTTP through the harness client against
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
from db.models import (  # noqa: E402
    Account, AccountAiConfig, Chatter, ChatterAccountAccess, ChatterUser, User, UserAccount,
)
import relay_cache  # noqa: E402
import split_inbox  # noqa: E402

client = _harness.make_client()
import server  # noqa: E402 — already imported by make_client; fresh clients below
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402

ACCOUNT = "acct_split_owner"
ACCOUNT2 = "acct_split_owner2"
FOREIGN = "acct_split_foreign"
NEW = "acct_split_new"
OWN = "acct_split_own"
PASSWORD = "secretpw"
UNSET = {"group_count": 1, "assignments": {}, "chatter_groups": {}}
CHATTER_ID = uuid.uuid4().hex
CHATTER2_ID = uuid.uuid4().hex
OWNER_ID = uuid.uuid4().hex
STRANGER_ID = uuid.uuid4().hex


async def _seed() -> None:
    owner = OWNER_ID
    chatter = CHATTER_ID
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(User(id=owner, username="splitowner", password=PASSWORD))
        s.add(Account(id=ACCOUNT, nickname="split model", color="#aaaaaa"))
        s.add(UserAccount(user_id=owner, account_id=ACCOUNT))
        s.add(Account(id=ACCOUNT2, nickname="split model two", color="#aaaaaa"))
        s.add(UserAccount(user_id=owner, account_id=ACCOUNT2))
        for aid in (NEW, OWN):
            s.add(Account(id=aid, nickname=aid, color="#aaaaaa"))
            s.add(UserAccount(user_id=owner, account_id=aid))
        s.add(User(id=STRANGER_ID, username="splitstranger", password=PASSWORD))
        s.add(Account(id=FOREIGN, nickname="someone else's model", color="#aaaaaa"))
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


async def _stored(account_id: str = ACCOUNT) -> str | None:
    async with get_session() as s:
        row = await s.get(AccountAiConfig, account_id)
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


def _fans(c: TestClient, account_id: str = ACCOUNT) -> tuple[list[int], bool]:
    r = c.get("/api/of/v2/chats?limit=4&offset=0", headers={"X-Account-Id": account_id})
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
        path, headers = "/api/of/v2/chats?limit=4&offset=0", {"X-Account-Id": ACCOUNT}
        version = chatter.get(path, headers=headers).json().get("split_version")
        assert version, "a bound chatter's page carries its split version"
        assert chatter.get(path, headers=headers).json()["split_version"] == version
        assert "split_version" not in owner.get(path, headers=headers).json()
        assert _put(owner, {"group_count": 2, "assignments": {}, "chatter_groups": {CHATTER_ID: 2}}).status_code == 200
        changed = chatter.get(path, headers=headers).json()
        assert changed.get("split_version") and changed["split_version"] != version
        assert [row["withUser"]["id"] for row in changed["list"]] == [301, 303]
        _put(owner, {"group_count": 1, "assignments": {}, "chatter_groups": {}})
        assert "split_version" not in chatter.get(path, headers=headers).json()
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



def _patch(c: TestClient, **body):
    return c.patch("/admin/split-inbox", json=body)


def _put_to(c: TestClient, account_id: str, config: dict):
    r = c.put("/admin/split-inbox", json={"account_id": account_id, "config": config})
    assert r.status_code == 200, (r.status_code, r.text)


def _all_stored() -> list[str | None]:
    return [asyncio.run(_stored(aid)) for aid in (ACCOUNT, ACCOUNT2, FOREIGN)]


def case_patch_merges_only_the_edits_into_each_stored_config():
    owner = _owner()
    _put_to(owner, ACCOUNT, {"group_count": 3, "assignments": {"701": 2, "702": 3},
                             "chatter_groups": {CHATTER_ID: 1, CHATTER2_ID: 2}})
    r = _patch(owner, account_ids=[ACCOUNT], chatter_groups={CHATTER2_ID: None, "c9": 3}, assignments={"703": 1})
    assert r.status_code == 200, (r.status_code, r.text)
    want = {"group_count": 3, "assignments": {"701": 2, "702": 3, "703": 1},
            "chatter_groups": {CHATTER_ID: 1}}
    assert r.json() == {"configs": {ACCOUNT: want}}, r.json()
    assert json.loads(asyncio.run(_stored())) == want
    assert _get(owner).json()["config"] == want
    assert split_inbox.bound_cached(CHATTER_ID, ACCOUNT) and not split_inbox.bound_cached(CHATTER2_ID, ACCOUNT)
    _put_to(owner, ACCOUNT, UNSET)


def case_patch_count_for_every_account_drops_only_what_falls_out_of_range():
    owner = _owner()
    _put_to(owner, ACCOUNT, {"group_count": 3, "assignments": {"701": 2, "702": 3}, "chatter_groups": {CHATTER_ID: 3}})
    _put_to(owner, ACCOUNT2, {"group_count": 2, "assignments": {"801": 2}, "chatter_groups": {CHATTER_ID: 1}})
    r = _patch(owner, account_ids=[ACCOUNT, ACCOUNT2], group_count=2, chatter_groups={CHATTER2_ID: 2})
    assert r.status_code == 200, (r.status_code, r.text)
    want = {
        ACCOUNT: {"group_count": 2, "assignments": {"701": 2}, "chatter_groups": {CHATTER2_ID: 2}},
        ACCOUNT2: {"group_count": 2, "assignments": {"801": 2}, "chatter_groups": {CHATTER_ID: 1, CHATTER2_ID: 2}},
    }
    assert r.json() == {"configs": want}, r.json()
    assert {aid: json.loads(asyncio.run(_stored(aid))) for aid in want} == want
    for aid in want:
        _put_to(owner, aid, UNSET)


def case_a_refused_patch_writes_nothing():
    owner = _owner()
    _put_to(owner, ACCOUNT, {"group_count": 2, "assignments": {"701": 2}, "chatter_groups": {}})
    before = _all_stored()
    for body, status in (
        ({"account_ids": [ACCOUNT, ACCOUNT2], "assignments": {"701": 1}}, 422),
        ({"account_ids": [], "group_count": 2}, 422),
        ({"account_ids": [""], "group_count": 2}, 422),
        ({"account_ids": [ACCOUNT], "group_count": 0}, 422),
        ({"account_ids": [ACCOUNT], "group_count": True}, 422),
        ({"account_ids": [ACCOUNT], "chatter_groups": {CHATTER_ID: "2"}}, 422),
        ({"account_ids": [ACCOUNT], "chatter_groups": [1]}, 422),
        ({"account_ids": [ACCOUNT], "assignments": {"701": None}}, 422),
        ({"account_ids": [ACCOUNT], "chatter_groups": {CHATTER_ID: 0}}, 422),
        ({"account_ids": [ACCOUNT], "assignments": {"701": -1}}, 422),
        ({"account_ids": [ACCOUNT], "assignments": {"701": 10}}, 422),
        ({"account_ids": [ACCOUNT, FOREIGN], "group_count": 3}, 403),
    ):
        r = _patch(owner, **body)
        assert r.status_code == status, (body, r.status_code, r.text)
    r = _patch(_chatter(), account_ids=[ACCOUNT], group_count=3)
    assert r.status_code == 403, ("a chatter cannot change the split", r.status_code, r.text)
    assert _patch(TestClient(server.app), account_ids=[ACCOUNT], group_count=3).status_code == 401
    assert _all_stored() == before, "a refused edit must not write"
    _put_to(owner, ACCOUNT, UNSET)


def case_a_stale_group_above_the_effective_count_is_409_and_writes_nothing():
    owner = _owner()
    _put_to(owner, ACCOUNT, {"group_count": 2, "assignments": {"701": 2}, "chatter_groups": {CHATTER_ID: 2}})
    _put_to(owner, ACCOUNT2, {"group_count": 3, "assignments": {}, "chatter_groups": {}})
    before, gens = _all_stored(), [split_inbox.generation(a) for a in (ACCOUNT, ACCOUNT2)]
    for body in (
        {"account_ids": [ACCOUNT], "chatter_groups": {CHATTER_ID: 3}},
        {"account_ids": [ACCOUNT], "assignments": {"701": 3}},
        {"account_ids": [ACCOUNT], "group_count": 2, "chatter_groups": {CHATTER2_ID: 3}},
        {"account_ids": [ACCOUNT2, ACCOUNT], "chatter_groups": {CHATTER2_ID: 3}},
    ):
        r = _patch(owner, **body)
        assert r.status_code == 409 and "Inbox 3" in r.json()["detail"], (body, r.status_code, r.text)
    assert _all_stored() == before, "a stale edit must not write"
    assert [split_inbox.generation(a) for a in (ACCOUNT, ACCOUNT2)] == gens, "nor publish"
    assert split_inbox.bound_cached(CHATTER_ID, ACCOUNT), "the valid Inbox 2 binding stays"
    r = _patch(owner, account_ids=[ACCOUNT], group_count=3, chatter_groups={CHATTER_ID: 3})
    assert r.status_code == 200 and r.json()["configs"][ACCOUNT]["chatter_groups"] == {CHATTER_ID: 3}, r.text
    for aid in (ACCOUNT, ACCOUNT2):
        _put_to(owner, aid, UNSET)


def case_a_binding_lands_only_on_models_the_chatter_is_granted():
    async def restrict(on: bool):
        async with get_session() as s:
            if on:
                s.add(ChatterAccountAccess(chatter_id=CHATTER2_ID, user_id=OWNER_ID, account_id=ACCOUNT))
            else:
                await s.delete(await s.get(ChatterAccountAccess, (CHATTER2_ID, OWNER_ID, ACCOUNT)))

    owner = _owner()
    asyncio.run(restrict(True))
    try:
        _put_to(owner, ACCOUNT2, {"group_count": 2, "assignments": {}, "chatter_groups": {CHATTER2_ID: 1}})
        r = _patch(owner, account_ids=[ACCOUNT, ACCOUNT2], group_count=2,
                   chatter_groups={CHATTER_ID: 2, CHATTER2_ID: 2})
        assert r.status_code == 200, (r.status_code, r.text)
        got = {aid: cfg["chatter_groups"] for aid, cfg in r.json()["configs"].items()}
        assert got == {ACCOUNT: {CHATTER_ID: 2, CHATTER2_ID: 2}, ACCOUNT2: {CHATTER_ID: 2, CHATTER2_ID: 1}}, got
        r = _patch(owner, account_ids=[ACCOUNT, ACCOUNT2], chatter_groups={CHATTER2_ID: None})
        assert r.status_code == 200, (r.status_code, r.text)
        got = {aid: cfg["chatter_groups"] for aid, cfg in r.json()["configs"].items()}
        assert got == {ACCOUNT: {CHATTER_ID: 2}, ACCOUNT2: {CHATTER_ID: 2}}, "an unbind clears a hidden lock too"
    finally:
        asyncio.run(restrict(False))
        for aid in (ACCOUNT, ACCOUNT2):
            _put_to(owner, aid, UNSET)


async def _restrict_chatter2_to_account(on: bool) -> None:
    async with get_session() as s:
        if on:
            s.add(ChatterAccountAccess(chatter_id=CHATTER2_ID, user_id=OWNER_ID, account_id=ACCOUNT))
        else:
            await s.delete(await s.get(ChatterAccountAccess, (CHATTER2_ID, OWNER_ID, ACCOUNT)))


async def _drop_default_and_rows() -> None:
    from sqlalchemy import delete
    from db.models import UserSetting
    async with get_session() as s:
        await s.execute(delete(UserSetting).where(UserSetting.tab == split_inbox.DEFAULT_TAB))
        await s.execute(delete(AccountAiConfig).where(AccountAiConfig.account_id.in_([NEW, OWN])))
    for aid in (NEW, OWN):
        split_inbox._configs.pop(aid, None)
    await split_inbox.default_changed(OWNER_ID)


def _config_of(c: TestClient, account_id: str) -> dict:
    r = c.get(f"/admin/split-inbox?account_id={account_id}")
    assert r.status_code == 200, (r.status_code, r.text)
    return r.json()


def case_an_all_models_save_is_the_default_for_a_creator_without_its_own_split():
    owner = _owner()
    for aid in (ACCOUNT, ACCOUNT2):
        _put_to(owner, aid, UNSET)
    _put_to(owner, OWN, {"group_count": 2, "assignments": {}, "chatter_groups": {}})
    asyncio.run(split_inbox.warm([NEW]))
    assert not split_inbox.bound_cached(CHATTER_ID, NEW), split_inbox._configs.get(NEW)
    asyncio.run(_restrict_chatter2_to_account(True))
    real_page, real_client = server._assemble_chats_page, server._get_client
    real_get = server.account_registry.get_account
    try:
        r = _patch(owner, account_ids=[ACCOUNT, ACCOUNT2], group_count=3,
                   chatter_groups={CHATTER_ID: 2, CHATTER2_ID: 3}, as_default=True)
        assert r.status_code == 200, (r.status_code, r.text)
        assert asyncio.run(_stored(NEW)) is None, "the default is not copied onto the new Creator"
        assert split_inbox.bound_cached(CHATTER_ID, NEW), "a cached inherited split refreshes on save"
        assert _config_of(owner, NEW)["config"] == {
            "group_count": 3, "assignments": {}, "chatter_groups": {CHATTER_ID: 2, CHATTER2_ID: 3},
        }, "chatter2's binding rides along unused until it is granted the new Creator"
        assert _config_of(_chatter(), NEW)["my_group"] == 2
        assert _config_of(owner, OWN)["config"] == {"group_count": 2, "assignments": {}, "chatter_groups": {}}

        server._assemble_chats_page, server._get_client = _chats_page, lambda: None
        server.account_registry.get_account = lambda aid: {"id": aid} if aid == NEW else real_get(aid)
        relay_cache.invalidate("list_chats", NEW)
        assert _fans(_chatter(), NEW)[0] == [301], "box 2 of 3 = id mod 3 == 1"
        assert _fans(owner, NEW)[0] == [300, 301, 302, 303]

        for body in ({"account_ids": [ACCOUNT], "group_count": 2, "chatter_groups": {CHATTER_ID: 1}},
                     {"account_ids": [ACCOUNT, ACCOUNT2], "chatter_groups": {CHATTER_ID: 1}}):
            r = _patch(owner, **body)
            assert r.status_code == 200, (body, r.status_code, r.text)
        assert _config_of(owner, NEW)["config"]["chatter_groups"] == {CHATTER_ID: 2, CHATTER2_ID: 3}, \
            "an edit without as_default leaves the default alone"

        r = _patch(owner, account_ids=[ACCOUNT, ACCOUNT2], chatter_groups={CHATTER_ID: None}, as_default=True)
        assert r.status_code == 200, (r.status_code, r.text)
        assert _config_of(owner, NEW)["config"] == {"group_count": 3, "assignments": {}, "chatter_groups": {}}
        assert not split_inbox.bound_cached(CHATTER_ID, NEW), split_inbox._configs.get(NEW)
    finally:
        server._assemble_chats_page, server._get_client = real_page, real_client
        server.account_registry.get_account = real_get
        relay_cache.invalidate("list_chats", NEW)
        asyncio.run(_restrict_chatter2_to_account(False))
        asyncio.run(_drop_default_and_rows())
        for aid in (ACCOUNT, ACCOUNT2):
            _put_to(owner, aid, UNSET)


def case_a_default_save_takes_the_split_every_target_now_shares():
    owner = _owner()
    _put_to(owner, ACCOUNT, {"group_count": 2, "assignments": {}, "chatter_groups": {CHATTER_ID: 1, CHATTER2_ID: 2}})
    _put_to(owner, ACCOUNT2, {"group_count": 2, "assignments": {}, "chatter_groups": {CHATTER_ID: 1, CHATTER2_ID: 1}})
    try:
        r = _patch(owner, account_ids=[ACCOUNT, ACCOUNT2], group_count=2, as_default=True)
        assert r.status_code == 200, (r.status_code, r.text)
        assert _config_of(owner, NEW)["config"] == {
            "group_count": 2, "assignments": {}, "chatter_groups": {CHATTER_ID: 1},
        }, "an untouched shared binding lands in the default; a differing one does not"
        r = _patch(owner, account_ids=[ACCOUNT, ACCOUNT2], chatter_groups={CHATTER2_ID: 2}, as_default=True)
        assert r.status_code == 200, (r.status_code, r.text)
        assert _config_of(owner, NEW)["config"] == {
            "group_count": 2, "assignments": {}, "chatter_groups": {CHATTER_ID: 1, CHATTER2_ID: 2},
        }
        _put_to(owner, NEW, {"group_count": 4, "assignments": {}, "chatter_groups": {}})
        r = _patch(owner, account_ids=[ACCOUNT, ACCOUNT2], group_count=3, as_default=True)
        assert r.status_code == 200, (r.status_code, r.text)
        assert _config_of(owner, NEW)["config"]["group_count"] == 4, "its own save wins over the default"
    finally:
        asyncio.run(_drop_default_and_rows())
        for aid in (ACCOUNT, ACCOUNT2):
            _put_to(owner, aid, UNSET)


def case_a_grant_given_after_the_default_applies_its_binding_at_once():
    owner = _owner()
    access = lambda ids: owner.put(f"/admin/chatters/{CHATTER2_ID}/account-access", json={"account_ids": ids})
    for aid in (ACCOUNT, ACCOUNT2):
        _put_to(owner, aid, UNSET)
    real_page, real_client = server._assemble_chats_page, server._get_client
    real_get = server.account_registry.get_account
    try:
        assert access([ACCOUNT]).status_code == 200
        r = _patch(owner, account_ids=[ACCOUNT, ACCOUNT2], group_count=3,
                   chatter_groups={CHATTER2_ID: 3}, as_default=True)
        assert r.status_code == 200, (r.status_code, r.text)
        asyncio.run(split_inbox.warm([NEW]))
        assert access([ACCOUNT, NEW]).status_code == 200
        server._assemble_chats_page, server._get_client = _chats_page, lambda: None
        server.account_registry.get_account = lambda aid: {"id": aid} if aid == NEW else real_get(aid)
        relay_cache.invalidate("list_chats", NEW)
        assert _fans(_chatter("splitchatter2"), NEW)[0] == [302], "box 3 of 3 = id mod 3 == 2"
    finally:
        server._assemble_chats_page, server._get_client = real_page, real_client
        server.account_registry.get_account = real_get
        relay_cache.invalidate("list_chats", NEW)
        access([])
        asyncio.run(_drop_default_and_rows())
        for aid in (ACCOUNT, ACCOUNT2):
            _put_to(owner, aid, UNSET)



async def _link_stranger(on: bool) -> None:
    from sqlalchemy import delete
    async with get_session() as s:
        if on:
            s.add_all([UserAccount(user_id=STRANGER_ID, account_id=aid) for aid in (NEW, FOREIGN)])
        else:
            await s.execute(delete(UserAccount).where(UserAccount.user_id == STRANGER_ID))
            await s.execute(delete(AccountAiConfig).where(AccountAiConfig.account_id == FOREIGN))
    split_inbox._configs.pop(FOREIGN, None)


def case_a_co_owned_creator_inherits_only_a_default_its_owners_agree_on():
    import events
    owner = _owner()
    for aid in (ACCOUNT, ACCOUNT2):
        _put_to(owner, aid, UNSET)
    asyncio.run(_link_stranger(True))
    stranger = TestClient(server.app)
    assert stranger.post("/auth/login", json={"username": "splitstranger", "password": PASSWORD}).status_code == 200
    sub = events._Sub("all", frozenset({NEW}), frozenset(), chatter=CHATTER_ID)
    even = {"api2_chat_message": {"fromUser": {"id": 300}}, "__account_id": NEW}
    try:
        r = _patch(owner, account_ids=[ACCOUNT, ACCOUNT2], group_count=2,
                   chatter_groups={CHATTER_ID: 2}, as_default=True)
        assert r.status_code == 200, (r.status_code, r.text)
        assert _config_of(owner, NEW)["config"]["chatter_groups"] == {CHATTER_ID: 2}, "only one owner has a default"
        assert events._for(sub, even) is None, "even id: box 1, not this chatter's"

        r = _patch(stranger, account_ids=[FOREIGN], group_count=2, as_default=True)
        assert r.status_code == 200, (r.status_code, r.text)
        assert _config_of(owner, NEW)["config"] == UNSET, "the owners' defaults differ: no split"
        assert events._for(sub, even) is not None, "the stranger's save refreshed the cached split"

        r = _patch(owner, account_ids=[ACCOUNT, ACCOUNT2], chatter_groups={CHATTER_ID: None}, as_default=True)
        assert r.status_code == 200, (r.status_code, r.text)
        assert _config_of(owner, NEW)["config"] == {"group_count": 2, "assignments": {}, "chatter_groups": {}}, \
            "equal defaults are inherited"
    finally:
        asyncio.run(_link_stranger(False))
        asyncio.run(_drop_default_and_rows())
        for aid in (ACCOUNT, ACCOUNT2):
            _put_to(owner, aid, UNSET)


def case_a_failed_cache_refresh_does_not_fail_the_committed_save():
    owner = _owner()
    real = split_inbox.default_changed

    async def broken(owner_id):
        raise RuntimeError("refresh down")
    split_inbox.default_changed = broken
    try:
        r = _patch(owner, account_ids=[ACCOUNT, ACCOUNT2], group_count=2, as_default=True)
        assert r.status_code == 200, (r.status_code, r.text)
        assert json.loads(asyncio.run(_stored(ACCOUNT)))["group_count"] == 2
    finally:
        split_inbox.default_changed = real
        asyncio.run(_drop_default_and_rows())
        for aid in (ACCOUNT, ACCOUNT2):
            _put_to(owner, aid, UNSET)



async def case_unrelated_owner_refresh_does_not_cancel_an_inherited_refresh():
    from db.models import UserSetting

    async with get_session() as s:
        s.add(UserSetting(user_id=OWNER_ID, tab=split_inbox.DEFAULT_TAB,
                          config_json=json.dumps({**UNSET, "group_count": 3})))
    split_inbox.remember(NEW, UNSET, inherited=True)
    read, resume = asyncio.Event(), asyncio.Event()
    real = split_inbox.resolve

    async def paused(s, ids):
        result = await real(s, ids)
        if NEW in ids:
            read.set()
            await resume.wait()
        return result

    split_inbox.resolve = paused
    refresh = asyncio.create_task(split_inbox.default_changed(OWNER_ID))
    try:
        await asyncio.wait_for(read.wait(), timeout=5)
        await split_inbox.default_changed(STRANGER_ID)
        resume.set()
        await refresh
        assert (await split_inbox.config(NEW))["group_count"] == 3
    finally:
        resume.set()
        await asyncio.gather(refresh, return_exceptions=True)
        split_inbox.resolve = real
        await _drop_default_and_rows()


async def case_failed_inherited_refresh_evicts_cached_default():
    split_inbox.remember(NEW, {**UNSET, "group_count": 3}, inherited=True)
    real = split_inbox.resolve

    async def broken(s, ids):
        raise RuntimeError("refresh down")

    split_inbox.resolve = broken
    try:
        try:
            await split_inbox.default_changed(OWNER_ID)
        except RuntimeError as exc:
            assert str(exc) == "refresh down"
        else:
            raise AssertionError("expected refresh failure")
        assert NEW not in split_inbox._configs
    finally:
        split_inbox.resolve = real
        await _drop_default_and_rows()



def case_grant_to_a_second_owner_refreshes_the_cached_inherited_split():
    import os
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch
    from db.models import UserSetting

    async def defaults():
        async with get_session() as s:
            for uid, n in ((OWNER_ID, 2), (STRANGER_ID, 3)):
                s.add(UserSetting(user_id=uid, tab=split_inbox.DEFAULT_TAB,
                                  config_json=json.dumps({**UNSET, "group_count": n})))

    asyncio.run(defaults())
    split_inbox._configs.pop(NEW, None)
    assert asyncio.run(split_inbox.config(NEW))["group_count"] == 2
    try:
        with TemporaryDirectory() as tmp, patch.object(server.account_registry, "ACCOUNTS_DIR", Path(tmp)):
            server.account_registry.save_meta(NEW, {"id": NEW})
            r = _owner().post(f"/admin/users/{STRANGER_ID}/accounts",
                              json={"account_id": NEW, "admin_password": os.environ["ADMIN_PASSWORD"]})
        assert r.status_code == 200, (r.status_code, r.text)
        assert asyncio.run(split_inbox.config(NEW)) == UNSET
        r = _owner().request("DELETE", f"/admin/users/{STRANGER_ID}/accounts/{NEW}",
                             json={"admin_password": os.environ["ADMIN_PASSWORD"]})
        assert r.status_code == 200, (r.status_code, r.text)
        assert asyncio.run(split_inbox.config(NEW))["group_count"] == 2, "revoking the co-owner restores the cached default"
    finally:
        asyncio.run(_link_stranger(False))
        asyncio.run(_drop_default_and_rows())


_harness.run()
