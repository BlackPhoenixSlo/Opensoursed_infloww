#!/usr/bin/env python3
"""
`POST /admin/vault/sends` + `/admin/vault/sends/backfill` take `account_id` in
the BODY. `_account_isolation_middleware` reads only query/path, so the routes
gate themselves with `assert_account_owned(body.account_id)`.

  case_foreign_owner_is_refused:
      owner A posting owner B's account_id → 403 on both routes, and zero
      `vault_sends` rows written for B.
  case_owner_writes_own_account:
      owner A posting A's account_id → 200 on both routes, rows written.
  case_anonymous_is_refused:
      no session → 401 on both routes, nothing written. Pins the perimeter
      (the general admin gate already 401s); not this fix.

Run: ./venv/bin/python service/tests/test_vault_sends_owned.py  (exit 0 = pass)
"""
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

_harness.make_client()  # neutralises the startup spawns before `server` serves
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
    assert r.status_code == 200 and r.json() == {"ok": True, "inserted": 3, "skipped": 0}, r.text
    assert _rows(ACC_A) == before + 5


def case_anonymous_is_refused() -> None:
    c = TestClient(server.app)
    before = (_rows(ACC_A), _rows(ACC_B))
    for aid in _ACCOUNTS:
        assert _send(c, aid, 5).status_code == 401
        assert _backfill(c, aid, 6).status_code == 401
    assert (_rows(ACC_A), _rows(ACC_B)) == before


_harness.run()
