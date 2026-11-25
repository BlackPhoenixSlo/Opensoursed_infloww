#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import uuid  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

import accounts as account_registry  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, User, UserAccount, VaultSend  # noqa: E402

_harness.make_client()
import server  # noqa: E402

ACC_A, ACC_B = "acc_vs_a", "acc_vs_b"
_ACCOUNTS = (ACC_A, ACC_B)
account_registry.get_account = lambda aid: {"id": aid} if aid in _ACCOUNTS else None
account_registry.list_accounts = lambda: [{"id": a, "has_session": True} for a in _ACCOUNTS]
account_registry.is_account = lambda aid: aid in _ACCOUNTS


async def _setup() -> None:
    async with get_session() as s:
        owner_a = User(id=uuid.uuid4().hex, username="owner_a", password="pw")
        owner_b = User(id=uuid.uuid4().hex, username="owner_b", password="pw")
        s.add_all([owner_a, owner_b])
        s.add_all([Account(id=a, nickname=a) for a in _ACCOUNTS])
        await s.flush()
        s.add_all([
            UserAccount(user_id=owner_a.id, account_id=ACC_A),
            UserAccount(user_id=owner_b.id, account_id=ACC_B),
        ])
        await s.commit()


asyncio.run(_setup())


def _login(username: str) -> TestClient:
    c = TestClient(server.app)
    r = c.post("/auth/login", json={"username": username, "password": "pw"})
    assert r.status_code == 200, f"{username} login failed: {r.status_code} {r.text}"
    return c


def _rows(aid: str) -> int:
    async def go() -> int:
        async with get_session() as s:
            return int((await s.execute(
                select(func.count()).select_from(VaultSend)
                .where(VaultSend.account_id == aid))).scalar_one())
    return asyncio.run(go())


def _send(c: TestClient, aid: str, msg: int):
    return c.post("/admin/vault/sends", json={
        "account_id": aid, "fan_id": 77, "media_ids": [101, 102], "message_id": msg})


def _backfill(c: TestClient, aid: str, msg: int):
    return c.post("/admin/vault/sends/backfill", json={
        "account_id": aid, "fan_id": 77,
        "items": [{"message_id": msg, "media_ids": [201, 202, 203]}]})


# the isolation middleware reads only query/path, so these routes gate themselves on body.account_id
def case_foreign_owner_is_refused() -> None:
    c = _login("owner_a")
    before = _rows(ACC_B)
    r = _send(c, ACC_B, 1)
    assert r.status_code == 403, f"sends: {r.status_code} {r.text}"
    r = _backfill(c, ACC_B, 2)
    assert r.status_code == 403, f"backfill: {r.status_code} {r.text}"
    assert _rows(ACC_B) == before == 0, f"rows written for B: {_rows(ACC_B)}"


def case_owner_writes_own_account() -> None:
    c = _login("owner_a")
    before = _rows(ACC_A)
    r = _send(c, ACC_A, 3)
    assert r.status_code == 200 and r.json() == {"ok": True, "inserted": 2}, r.text
    r = _backfill(c, ACC_A, 4)
    body = r.json() if r.status_code == 200 else {}
    assert {k: body.get(k) for k in ("ok", "inserted", "skipped")} == {"ok": True, "inserted": 3, "skipped": 0} \
        and set(body["history"]["by_media"]) >= {"201", "202", "203"}, r.text
    assert _rows(ACC_A) == before + 5


def case_anonymous_is_refused() -> None:
    c = TestClient(server.app)
    before = (_rows(ACC_A), _rows(ACC_B))
    for aid in _ACCOUNTS:
        assert _send(c, aid, 5).status_code == 401
        assert _backfill(c, aid, 6).status_code == 401
    assert (_rows(ACC_A), _rows(ACC_B)) == before


class _WallClient:

    def __init__(self, user_id):
        self.user_id = user_id
        self.me_calls = 0
        self.posts_for: list = []

    def me(self):
        self.me_calls += 1
        return {"id": 999}

    def user_posts(self, uid, **_kw):
        self.posts_for.append(uid)
        return {"list": [{"id": 5, "postedAt": "2026-11-01T10:00:00+00:00", "media": [{"id": 4242}]}],
                "hasMore": False}


def _wall(c: TestClient, fake: _WallClient):
    orig = server._load_client
    server._load_client = lambda _aid: fake
    try:
        return c.get("/admin/vault/wall-media", params={"account_id": ACC_A, "force": "true"})
    finally:
        server._load_client = orig


def case_wall_scan_takes_the_session_user_id() -> None:
    c = _login("owner_a")
    fake = _WallClient("12345")
    r = _wall(c, fake)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert fake.me_calls == 0, f"/users/me called {fake.me_calls}x"
    assert fake.posts_for == [12345], fake.posts_for
    assert 4242 in r.json()["media_ids"], r.json()


def case_wall_scan_without_a_usable_user_id_is_a_500() -> None:
    c = _login("owner_a")
    for bad in (None, "", "abc", "12a", "0", "-5", "1.5"):
        fake = _WallClient(bad)
        r = _wall(c, fake)
        assert r.status_code == 500, f"user_id={bad!r}: {r.status_code} {r.text}"
        assert r.json().get("detail") == "Could not resolve current user id from /users/me", r.text
        assert fake.posts_for == [] and fake.me_calls == 0, (bad, fake.posts_for, fake.me_calls)


def case_fansly_wall_scan_stays_a_500() -> None:
    c = _login("owner_a")
    fake = _WallClient("123456789012345678")
    orig = account_registry.get_platform
    account_registry.get_platform = lambda aid: "fansly" if aid == ACC_A else orig(aid)
    try:
        r = _wall(c, fake)
    finally:
        account_registry.get_platform = orig
    assert r.status_code == 500, f"{r.status_code} {r.text}"
    assert r.json().get("detail") == "Could not resolve current user id from /users/me", r.text
    assert fake.posts_for == [] and fake.me_calls == 0, (fake.posts_for, fake.me_calls)


_harness.run()
