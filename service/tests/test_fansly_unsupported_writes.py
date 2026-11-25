#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

import accounts as account_registry  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="fansly_unsupported_")
account_registry.SESSIONS_DIR = Path(_TMP.name)
account_registry.ACCOUNTS_DIR = Path(_TMP.name) / "accounts"
account_registry.ACTIVE_FILE = Path(_TMP.name) / "active.json"
account_registry.MIGRATED_MARKER = Path(_TMP.name) / ".migrated"

import read_flip  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, User, UserAccount  # noqa: E402
from fansly_client import FanslySession  # noqa: E402
from fansly_shim import FanslyShimClient  # noqa: E402
from side_effect_gate import refusal  # noqa: E402

http = _harness.make_client()

_AID = "8802101"
FAN = 9101

_shim = FanslyShimClient.__new__(FanslyShimClient)
_local: list[tuple] = []


class _FakeOF:
    def __init__(self) -> None:
        self.writes: list[tuple] = []

    def pin_message(self, message_id, user_id):
        self.writes.append(("pin", message_id, user_id))
        return {"success": True}

    def unpin_message(self, message_id, user_id):
        self.writes.append(("unpin", message_id, user_id))
        return {"success": True}

    def mark_chat_unread(self, chat_id):
        self.writes.append(("unread", chat_id))
        return {"success": True}

    def add_users_to_lists(self, body):
        self.writes.append(("lists", body))
        return {k: list(v) for k, v in body.items()}


async def _record_local(account_id, *, fan_id, value, at=None):
    _local.append((account_id, fan_id, value))

server._resolve_account_id = lambda _req=None: _AID  # type: ignore[assignment]
read_flip.set_local_unread = _record_local          # type: ignore[assignment]
server._bust_chat_detail = lambda *a, **k: None      # type: ignore[assignment]


def _status(call) -> int:
    try:
        call()
    except server.HTTPException as e:
        return e.status_code
    return 200


async def _astatus(coro) -> int:
    try:
        await coro
    except server.HTTPException as e:
        return e.status_code
    return 200


def case_fansly_pin_unpin_answer_501():
    server._get_client = lambda *a, **k: _shim  # type: ignore[assignment]
    assert _status(lambda: server.of_pin_message(77, FAN)) == 501
    assert _status(lambda: server.of_unpin_message(77, FAN)) == 501


async def case_fansly_mark_unread_answers_501_and_flips_nothing_locally():
    server._get_client = lambda *a, **k: _shim  # type: ignore[assignment]
    _local.clear()
    assert await _astatus(server.of_mark_chat_unread(FAN)) == 501
    assert _local == [], f"a 501 still flipped the local unread badge: {_local}"


async def case_of_client_still_reaches_the_writes():
    fake = _FakeOF()
    server._get_client = lambda *a, **k: fake  # type: ignore[assignment]
    _local.clear()
    assert server.of_pin_message(77, FAN) == {"success": True}
    assert server.of_unpin_message(77, FAN) == {"success": True}
    assert await server.of_mark_chat_unread(FAN) == {"success": True}
    assert fake.writes == [("pin", 77, FAN), ("unpin", 77, FAN), ("unread", FAN)], fake.writes
    assert _local == [(_AID, FAN, 1)], _local


def case_shim_methods_carry_the_marker():
    for name in ("pin_message", "unpin_message", "mark_chat_unread"):
        assert getattr(getattr(FanslyShimClient, name), "fansly_unsupported", None), name
        assert getattr(_shim, name)(77, FAN) == {"success": True}, name



async def _owner() -> None:
    async with get_session() as s:
        boss = User(id=uuid.uuid4().hex, username="boss", password="pw")
        s.add_all([boss, Account(id=_AID, nickname=_AID)])
        await s.flush()
        s.add(UserAccount(user_id=boss.id, account_id=_AID))

asyncio.run(_owner())
assert http.post("/auth/login", json={"username": "boss", "password": "pw"}).status_code == 200


def _call(method: str, path: str, client, **kw):
    server._get_client = lambda *a, **k: client  # type: ignore[assignment]
    return http.request(method, path, headers={"X-Account-Id": _AID}, **kw)


def case_table_routes_answer_501_with_their_reason():
    r = _call("POST", "/api/of/v2/labels", _shim, json={"name": "x"})
    assert r.status_code == 501 and "post labels not captured" in r.json()["detail"], (r.status_code, r.text)
    r = _call("DELETE", f"/api/of/v2/chats/{FAN}/messages/pin", _shim)
    assert r.status_code == 501 and "no message pinning" in r.json()["detail"], (r.status_code, r.text)


def case_refusal_same_on_class_and_instance():
    want = {"add_users_to_lists": None, "restrict_user": "Fansly has no restrict",
            "chat_media": "chat media gallery not captured",
            "list_users_in": "list members read not captured",
            "no_such_method": "no_such_method is not on this platform"}
    for name, reason in want.items():
        assert refusal(FanslyShimClient, name) == refusal(_shim, name) == reason, name


def _recording_shim(echo):
    shim = FanslyShimClient(FanslySession({"accountId": "1", "token": "t", "check_key": "k",
                                           "device_id": "d", "user_agent": "UA"}))
    calls: list = []

    def record(method, path, *, json_body=None, **_kw):
        if (method, path) != ("POST", "/lists/commands"):
            raise AssertionError(f"unrecorded request {method} {path}")
        calls.append(json_body)
        return echo

    shim._request = record
    return shim, calls


def case_list_add_sends_recipe_body_and_returns_echoed_ids():
    a, b, lid = 951237126601601111, 951237126601602222, "900537126601601024"
    echo = [{"type": 1, "listItem": {"id": str(a), "listId": lid}}]
    shim, calls = _recording_shim(echo)
    r = _call("POST", "/api/of/v2/lists/users", shim, json={lid: [a, b]})
    assert r.status_code == 200, (r.status_code, r.text)
    assert calls == [{"listCommands": [{"type": 1, "listItem": {"id": str(a), "listId": lid}},
                                       {"type": 1, "listItem": {"id": str(b), "listId": lid}}]}], calls
    assert r.json() == {lid: [str(a)]}, r.json()


def case_of_list_add_unchanged():
    fake = _FakeOF()
    r = _call("POST", "/api/of/v2/lists/users", fake, json={"7": [1, 2]})
    assert r.status_code == 200 and r.json() == {"7": [1, 2]}, (r.status_code, r.text)
    assert fake.writes == [("lists", {"7": [1, 2]})], fake.writes


class _ChatOF(_FakeOF):
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*a, **k):
            self.writes.append((name, *a))
            return {"list": [], "hasMore": False} if name == "chat_media" else {"success": True}
        return call


class _SideEffects:
    def __init__(self) -> None:
        self.seen: list[tuple] = []

    def install(self) -> None:
        import automation_executor

        async def send(_req, user_id, body):
            self.seen.append(("send", user_id, body.text))
            return {"id": 1}

        async def mark_read(chat_id):
            self.seen.append(("mark_read", chat_id))
            return {"success": True}

        async def paced(aid, fn, **_k):
            self.seen.append(("pacer", aid))
            return await asyncio.to_thread(fn)

        server.send_message = send                                     # type: ignore[assignment]
        server.of_mark_chat_read = mark_read                           # type: ignore[assignment]
        automation_executor.of_write_paced = paced                     # type: ignore[assignment]
        read_flip.bust_chat_list_and_badges = lambda aid, chat_id=None: self.seen.append(("bust", chat_id))


def _on(platform: str) -> None:
    account_registry.save_meta(_AID, {"id": _AID, "nickname": _AID, "platform": platform})


def _no_session(*_a, **_k):
    raise server.HTTPException(status_code=503, detail={"error": "no_session"})


def _restricted() -> set[int]:
    from automations._common import load_of_restricted_ids
    return asyncio.run(load_of_restricted_ids(_AID))


_CHAT_ROUTES = (
    ("POST", f"/api/of/v2/users/{FAN}/block", {}, "block user", ("block_user", FAN)),
    ("DELETE", f"/api/of/v2/users/{FAN}/block", {}, "unblock user", ("unblock_user", FAN)),
    ("GET", "/api/of/v2/users/search", {"q": "ann"}, "search users", ("search_users", "ann")),
    ("GET", f"/api/of/v2/chats/{FAN}/messages/search", {"query": "hi"}, "search chat", ("search_chat", FAN, "hi", None)),
    ("GET", f"/api/of/v2/chats/{FAN}/media", {}, "chat media", ("chat_media", FAN)),
    ("GET", f"/api/of/v2/chats/{FAN}/media/photos", {}, "chat media", ("chat_media", FAN)),
)


def case_fansly_restrict_answers_501_before_ack_read_or_skip_row():
    _on("fansly")
    fx = _SideEffects()
    fx.install()
    r = _call("POST", f"/api/of/v2/users/{FAN}/restrict", _shim)
    assert r.status_code == 501 and r.json()["detail"] == "restrict user: not on this platform", (r.status_code, r.text)
    assert fx.seen == [], f"restrict acted before refusing: {fx.seen}"
    assert FAN not in _restricted()
    r = _call("DELETE", f"/api/of/v2/users/{FAN}/restrict", _shim)
    assert r.status_code == 501 and r.json()["detail"] == "unrestrict user: not on this platform", (r.status_code, r.text)
    assert fx.seen == [], fx.seen


def case_fansly_chat_routes_answer_501():
    _on("fansly")
    for method, path, params, what, _ in _CHAT_ROUTES:
        r = _call(method, path, _shim, params=params)
        assert r.status_code == 501 and r.json()["detail"] == f"{what}: not on this platform", (path, r.status_code, r.text)


def case_fansly_delete_chat_answers_501_with_no_pacer_slot_or_bust():
    _on("fansly")
    fx = _SideEffects()
    fx.install()
    r = _call("DELETE", f"/api/of/v2/chats/{FAN}", _shim)
    assert r.status_code == 501 and r.json()["detail"] == "delete chat: not on this platform", (r.status_code, r.text)
    assert fx.seen == [], f"delete chat acted before refusing: {fx.seen}"


def case_of_restrict_and_unrestrict_still_act():
    _on("onlyfans")
    fx = _SideEffects()
    fx.install()
    fake = _ChatOF()
    r = _call("POST", f"/api/of/v2/users/{FAN}/restrict", fake)
    assert r.status_code == 200 and r.json()["restricted"] is True, (r.status_code, r.text)
    assert fx.seen == [("send", FAN, "."), ("mark_read", FAN)], fx.seen
    assert [w[0] for w in fake.writes] == ["restrict_user", "hide_chat"], fake.writes
    assert FAN in _restricted()
    r = _call("DELETE", f"/api/of/v2/users/{FAN}/restrict", fake)
    assert r.status_code == 200 and r.json()["restricted"] is False, (r.status_code, r.text)
    assert [w[0] for w in fake.writes][2:] == ["unrestrict_user", "unhide_chat"], fake.writes
    assert FAN not in _restricted()


def case_of_chat_routes_still_reach_the_client():
    _on("onlyfans")
    for method, path, params, _, want in _CHAT_ROUTES:
        fake = _ChatOF()
        r = _call(method, path, fake, params=params)
        assert r.status_code == 200, (path, r.status_code, r.text)
        assert len(fake.writes) == 1 and fake.writes[0][:len(want)] == want, (path, fake.writes)


def case_of_delete_chat_paced_and_busted():
    _on("onlyfans")
    fx = _SideEffects()
    fx.install()
    fake = _ChatOF()
    r = _call("DELETE", f"/api/of/v2/chats/{FAN}", fake)
    assert r.status_code == 200, (r.status_code, r.text)
    assert fake.writes == [("delete_chat", FAN)], fake.writes
    assert fx.seen == [("pacer", _AID), ("bust", FAN)], fx.seen


def case_of_no_session_restrict_still_tries_ack_and_read():
    _on("onlyfans")
    fx = _SideEffects()
    fx.install()
    server._get_client = _no_session  # type: ignore[assignment]
    r = http.post(f"/api/of/v2/users/{FAN}/restrict", headers={"X-Account-Id": _AID})
    assert r.status_code == 503, (r.status_code, r.text)
    assert fx.seen == [("send", FAN, "."), ("mark_read", FAN)], fx.seen


def case_of_no_session_delete_chat_still_takes_a_pacer_slot():
    _on("onlyfans")
    fx = _SideEffects()
    fx.install()
    server._get_client = _no_session  # type: ignore[assignment]
    r = http.delete(f"/api/of/v2/chats/{FAN}", headers={"X-Account-Id": _AID})
    assert r.status_code == 503, (r.status_code, r.text)
    assert fx.seen == [("pacer", _AID)], fx.seen


_GROUP = {"startDate": "2026-01-01 00:00:00", "endDate": "2026-02-01 00:00:00"}
_OWNER_ROUTES = (
    ("GET", "/api/of/v2/lists/7/users", {}, None, "list members", ("list_users_in", "7")),
    ("PATCH", "/api/of/v2/lists/7", {}, {"name": "x"}, "rename list", ("rename_list", "7", "x")),
    ("DELETE", "/api/of/v2/lists/7", {}, None, "delete list", ("delete_list", "7")),
    ("PUT", f"/api/of/v2/subscriptions/{FAN}/discount", {}, {"discount": 10, "period": 1},
     "subscription discount", ("set_subscription_discount", FAN, 10, 1)),
    ("GET", "/api/of/v2/users/me/stats/messages/group", _GROUP, None, "mass message history",
     ("engagement_messages", "group")),
)
_QUEUE = ("GET", "/api/of/v2/messages/queue", {}, None, "scheduled messages", ("scheduled_messages",))


def case_fansly_list_discount_and_group_feed_answer_501():
    _on("fansly")
    busted: list[str] = []
    server._invalidate_chat_folders = lambda *a, **k: busted.append("folders")  # type: ignore[assignment]
    server._bust_chat_list_cache = lambda *a, **k: busted.append("chat_list")   # type: ignore[assignment]
    for method, path, params, body, what, _ in _OWNER_ROUTES:
        r = _call(method, path, _shim, params=params, json=body)
        assert r.status_code == 501 and r.json()["detail"] == f"{what}: not on this platform", (path, r.status_code, r.text)
    assert busted == [], f"a refused route still dropped a cache: {busted}"


def case_fansly_scheduled_messages_answers_501():
    _on("fansly")
    r = _call("GET", _QUEUE[1], _shim)
    assert r.status_code == 501 and r.json()["detail"] == "scheduled messages: not on this platform", (r.status_code, r.text)


def case_of_list_discount_queue_and_group_feed_still_reach_the_client():
    _on("onlyfans")
    for method, path, params, body, _, want in (*_OWNER_ROUTES, _QUEUE):
        fake = _ChatOF()
        r = _call(method, path, fake, params=params, json=body)
        assert r.status_code == 200, (path, r.status_code, r.text)
        assert len(fake.writes) == 1 and fake.writes[0][:len(want)] == want, (path, fake.writes)


def _admin_mass(client, aid: str = _AID):
    server._load_client = lambda _aid: client  # type: ignore[assignment]
    q = {"account_id": aid}
    return http.get("/admin/mass-messages", params=q), http.post("/admin/mass-messages/refresh", params=q)


def case_fansly_admin_mass_messages_and_refresh_answer_501_on_an_empty_cache():
    _on("fansly")
    for r in _admin_mass(_shim):
        assert r.status_code == 501 and r.json()["detail"] == "mass message history: not on this platform", (
            r.request.url, r.status_code, r.text)


def case_of_admin_mass_messages_and_refresh_still_reach_the_client():
    _on("onlyfans")
    fake = _ChatOF()
    got, refreshed = _admin_mass(fake)
    assert got.status_code == 200 and got.json()["items"] == [], (got.status_code, got.text)
    assert refreshed.status_code == 200 and refreshed.json()["items"] == [], (refreshed.status_code, refreshed.text)
    assert [w[0] for w in fake.writes] == ["mass_message_history"] * 2, fake.writes


def case_of_no_session_admin_mass_messages_unchanged():
    _on("onlyfans")
    server._load_client = _no_session  # type: ignore[assignment]
    got = http.get("/admin/mass-messages", params={"account_id": _AID})
    refreshed = http.post("/admin/mass-messages/refresh", params={"account_id": _AID})
    assert got.status_code == 200 and got.json()["items"] == [], (got.status_code, got.text)
    assert refreshed.status_code == 503, (refreshed.status_code, refreshed.text)


async def _seed_vault(*media: tuple[int, str | None, int]) -> None:
    from datetime import datetime, timedelta

    import vault_dupes
    from db.models import VaultItem
    async with get_session() as s:
        for media_id, packed, days_old in media:
            s.add(VaultItem(account_id=_AID, media_id=media_id, kind="photo", tags="[]", send_count=0,
                            created_at=datetime.utcnow() - timedelta(days=days_old), content_hash=packed,
                            content_hash_kind=vault_dupes.HASH_KIND if packed else None))


async def _removed_at(media_id: int):
    from sqlalchemy import select

    from db.models import VaultItem
    async with get_session() as s:
        return (await s.execute(select(VaultItem.removed_at).where(
            VaultItem.account_id == _AID, VaultItem.media_id == media_id))).scalar_one()


def _vault_hide(client, path: str, body: dict):
    import automation_executor
    automation_executor._make_client = lambda *a, **k: client  # type: ignore[assignment]
    return http.post(path, json={"account_id": _AID, **body})


def _dupe_pair(original: int, copy: int, md5: str) -> None:
    import vault_dupes
    packed = vault_dupes.pack_hash(md5 * 32, int(md5, 16), int(md5, 16))
    asyncio.run(_seed_vault((original, packed, 30), (copy, packed, 10)))


def case_fansly_vault_item_and_duplicate_remove_answer_501_and_mark_nothing_removed():
    _on("fansly")
    asyncio.run(_seed_vault((601, None, 1)))
    r = _vault_hide(_shim, "/admin/vault-ai/items/601/hide", {})
    assert r.status_code == 501 and r.json()["detail"] == "remove from vault: not on this platform", (r.status_code, r.text)
    assert asyncio.run(_removed_at(601)) is None
    _dupe_pair(611, 612, "a")
    r = _vault_hide(_shim, "/admin/vault-ai/duplicates/hide", {"media_ids": [612]})
    assert r.status_code == 501 and r.json()["detail"] == "remove from vault: not on this platform", (r.status_code, r.text)
    assert asyncio.run(_removed_at(612)) is None


def case_of_vault_item_and_duplicate_remove_still_hide_and_mark_removed():
    _on("onlyfans")
    asyncio.run(_seed_vault((701, None, 1)))
    fake = _ChatOF()
    r = _vault_hide(fake, "/admin/vault-ai/items/701/hide", {})
    assert r.status_code == 200 and r.json()["hidden"] is True, (r.status_code, r.text)
    _dupe_pair(711, 712, "b")
    r = _vault_hide(fake, "/admin/vault-ai/duplicates/hide", {"media_ids": [712]})
    assert r.status_code == 200 and r.json()["hidden_ids"] == [712], (r.status_code, r.text)
    assert fake.writes == [("hide_vault_media", [701]), ("hide_vault_media", [712])], fake.writes
    assert asyncio.run(_removed_at(701)) is not None and asyncio.run(_removed_at(712)) is not None


class _GalleryOF:
    user_id = _AID

    def __init__(self) -> None:
        self.calls = 0

    def chat_media(self, chat_id, **_kw):
        self.calls += 1
        return {"list": [], "hasMore": False}


async def _synced_at(fan: int):
    from sqlalchemy import select

    from db.models import FanMediaSync
    async with get_session() as s:
        return (await s.execute(select(FanMediaSync.synced_at).where(
            FanMediaSync.account_id == _AID, FanMediaSync.fan_id == fan))).scalar_one_or_none()


def _backfill(client, fan: int):
    server._load_client = lambda _aid: client  # type: ignore[assignment]
    return http.post("/admin/vault/fan-history/sync", json={"account_id": _AID, "fan_id": fan})


def case_fansly_vault_backfill_answers_not_synced_and_leaves_synced_at_null():
    _on("fansly")
    r = _backfill(_shim, FAN + 1)
    assert r.status_code == 200 and r.json()["synced"] is False, (r.status_code, r.text)
    assert asyncio.run(_synced_at(FAN + 1)) is None


def case_of_vault_backfill_still_walks_and_stamps_synced_at():
    _on("onlyfans")
    fake = _GalleryOF()
    r = _backfill(fake, FAN + 2)
    assert r.status_code == 200 and r.json()["synced"] is True, (r.status_code, r.text)
    assert fake.calls == 1 and asyncio.run(_synced_at(FAN + 2)) is not None


class _MassOF:
    def __init__(self) -> None:
        self.writes: list[tuple] = []

    def send_mass_message(self, **kw):
        self.writes.append(("send_mass_message", kw["excluded_user_lists"]))
        return {"id": 66001, "createdAt": "2026-11-25T10:00:00+00:00"}

    def schedule_mass_message(self, **kw):
        self.writes.append(("schedule_mass_message", kw["excluded_user_lists"]))
        return {"id": 66002}


_MASS = {"text": "hi all", "user_lists": ["7"], "excluded_users": [5]}
_MASS_BODIES = (_MASS, {**_MASS, "scheduled_date": "2026-12-01T10:00:00.000Z"}, {**_MASS, "save_for_later": True})


import audiences  # noqa: E402
import mass_queue_api  # noqa: E402

_REAL_RESERVE, _REAL_RESOLVE = mass_queue_api._reserve_send, audiences.resolve_mass_audience


def _mass_spies() -> list[str]:
    seen: list[str] = []

    def reserve(key):
        seen.append("reserve")
        _REAL_RESERVE(key)

    async def resolve(*a, **k):
        seen.append("audience")
        return await _REAL_RESOLVE(*a, **k)

    async def exclude_list(*_a, **_k):
        seen.append("exclude_list")
        return 4242

    mass_queue_api._reserve_send = reserve             # type: ignore[assignment]
    audiences.resolve_mass_audience = resolve          # type: ignore[assignment]
    audiences.ensure_exclude_list = exclude_list       # type: ignore[assignment]
    return seen


async def _mass_runs() -> int:
    from sqlalchemy import func, select

    from db.models import MassRun
    async with get_session() as s:
        return (await s.execute(select(func.count()).select_from(MassRun).where(MassRun.account_id == _AID))).scalar_one()


def case_fansly_mass_route_answers_501_before_key_audience_exclude_list_or_run():
    _on("fansly")
    for body, what in zip(_MASS_BODIES, ("mass message", "scheduled mass message", "scheduled mass message")):
        seen = _mass_spies()
        runs = asyncio.run(_mass_runs())
        r = _call("POST", "/api/of/v2/messages/queue", _shim, json=body)
        assert r.status_code == 501 and r.json()["detail"] == f"{what}: not on this platform", (body, r.status_code, r.text)
        assert seen == [], (body, seen)
        assert mass_queue_api._send_keys == {} and asyncio.run(_mass_runs()) == runs, body


def case_of_mass_route_still_resolves_syncs_mints_and_posts():
    _on("onlyfans")
    for body, post in zip(_MASS_BODIES, ("send_mass_message", "schedule_mass_message", "schedule_mass_message")):
        seen = _mass_spies()
        runs = asyncio.run(_mass_runs())
        fake = _MassOF()
        r = _call("POST", "/api/of/v2/messages/queue", fake, json=body)
        assert r.status_code == 200, (body, r.status_code, r.text)
        assert seen == ["reserve", "audience", "exclude_list"], (body, seen)
        assert fake.writes == [(post, [4242])], (body, fake.writes)
        assert asyncio.run(_mass_runs()) == runs + 1 and mass_queue_api._send_keys == {}, body


def case_of_no_session_mass_route_still_reserves_and_resolves_first():
    _on("onlyfans")
    seen = _mass_spies()
    server._get_client = _no_session  # type: ignore[assignment]
    r = http.post("/api/of/v2/messages/queue", headers={"X-Account-Id": _AID}, json=_MASS)
    assert r.status_code == 503, (r.status_code, r.text)
    assert seen == ["reserve", "audience"], seen
    assert mass_queue_api._send_keys == {}


_harness.run()
