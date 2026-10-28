#!/usr/bin/env python3
"""The chatter identity cache (why and how: service/chatter_identity_cache.py).

Each case warms the victim session's entry first (asserted cached by counting
the identity reads of a request), makes the change through the real endpoint,
and checks the very next request.

    ./venv/bin/python service/tests/test_chatter_identity_cache.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import event as sa_event, select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import chatter_identity_cache as identity_cache  # noqa: E402
import login_throttle  # noqa: E402
from db.engine import engine, get_session  # noqa: E402
from db.models import Account, Chatter, ChatterUser, UserAccount  # noqa: E402

IDS = fx.seed_two_agencies()
CREATOR_A2 = "1000011"  # Agency A's second Creator, so a restriction can leave one

IDENTITY_TABLES = ("chatters", "chatter_users", "user_accounts", "chatter_account_access")
_sql: list[str] = []
_invalidate_on_access_read = False  # armed by the race case: one invalidate() mid-load


@sa_event.listens_for(engine.sync_engine, "before_cursor_execute")
def _record(_conn, _cursor, statement, *_a):
    global _invalidate_on_access_read
    _sql.append(statement)
    if (_invalidate_on_access_read and statement.lstrip().upper().startswith("SELECT")
            and "chatter_account_access" in statement):
        _invalidate_on_access_read = False
        identity_cache.invalidate()  # a write commits while the load is in flight


def _identity_reads() -> int:
    """SELECTs on the identity's tables since the last call."""
    n = sum(1 for q in _sql if q.lstrip().upper().startswith("SELECT")
            and any(f" {t}" in q or f'"{t}"' in q for t in IDENTITY_TABLES))
    _sql.clear()
    return n


def _reads_of_one_request(client) -> int:
    """Identity-table SELECTs of one request whose route reads none of them
    (folder-access, Creator A): 0 = the identity came from the cache,
    LOAD_READS = the middleware loaded it."""
    _identity_reads()
    client.get(f"/chatter/me/folder-access?account_id={IDS['creator_a']}")
    return _identity_reads()


LOAD_READS = 4  # chatters, chatter_users, user_accounts IN, chatter_account_access


def _assert_cached(client) -> None:
    _reads_of_one_request(client)  # loads it, unless already cached
    assert _reads_of_one_request(client) == 0, "the next request must be served from the cache"


def _db(coro_fn):
    return asyncio.run(coro_fn())


async def _seed_a2() -> None:
    async with get_session() as s:
        s.add(Account(id=CREATOR_A2, nickname="creator_a2", color="#aaaaaa"))
    async with get_session() as s:
        s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=CREATOR_A2))
    account_registry.upsert_account(CREATOR_A2, nickname="creator_a2")  # the founder grant reads the registry


_db(_seed_a2)


def _new_chatter(owners=("agency_a_owner",)) -> tuple[str, str]:
    """A fresh login linked to `owners`: (username, chatter id). Fresh per case so
    no case inherits another's grants or revocations."""
    name = f"cic_{uuid.uuid4().hex[:8]}"
    cid = uuid.uuid4().hex

    async def _w():
        now = datetime.utcnow()
        async with get_session() as s:
            s.add(Chatter(id=cid, username=name, password=fx.PASSWORD, display_name=name,
                          created_at=now, last_seen_at=now))
        async with get_session() as s:
            for o in owners:
                s.add(ChatterUser(chatter_id=cid, user_id=IDS[o], created_at=now))
    _db(_w)
    return name, cid


def _login(name: str):
    login_throttle.reset()
    return fx.login_chatter(name)


def _accounts(client) -> set[str]:
    r = client.get("/chatter/me/accounts")
    assert r.status_code == 200, r.text
    return {a["account_id"] for a in r.json()}


def _direct(client, aid: str):
    """A direct read gated by the identity's account set alone (no role gate):
    (status, detail)."""
    r = client.get(f"/chatter/me/folder-access?account_id={aid}")
    return r.status_code, (r.json().get("detail") if r.status_code != 200 else None)


DENIED = (403, "account not available to you")


def _owner(name: str):
    login_throttle.reset()
    return fx.login_owner(name)


def _employee_id(owner, name: str) -> int:
    rows = [r for r in owner.get("/admin/employees").json()["employees"] if r.get("username") == name]
    assert len(rows) == 1, rows
    return rows[0]["id"]


# ── cases ────────────────────────────────────────────────────────────

def case_second_request_reads_no_identity_table():
    name, _cid = _new_chatter()
    c = _login(name)
    first = _reads_of_one_request(c)
    assert first == LOAD_READS, f"a miss loads the identity in {LOAD_READS} reads, read {first}"
    assert _reads_of_one_request(c) == 0, "the second request must read no identity table"
    assert _accounts(c) == {IDS["creator_a"], CREATOR_A2}
    assert c.get("/chatter/me").json()["username"] == name


def case_ttl_expiry_rereads_a_direct_db_change():
    saved = identity_cache.TTL_S
    identity_cache.TTL_S = 0.3  # CHATTERLY_CHATTER_IDENTITY_TTL_S's value
    try:
        name, cid = _new_chatter()
        c = _login(name)
        assert _accounts(c) == {IDS["creator_a"], CREATOR_A2}

        async def _drop_link():  # a direct write with no event: only the TTL can see it
            async with get_session() as s:
                await s.execute(ChatterUser.__table__.delete().where(ChatterUser.chatter_id == cid))
        _db(_drop_link)
        assert _accounts(c) == {IDS["creator_a"], CREATOR_A2}, "within the TTL the cached identity serves"
        time.sleep(0.35)
        assert _accounts(c) == set(), "past the TTL the next request reads the DB"
    finally:
        identity_cache.TTL_S = saved


def case_log_out_other_sessions_refuses_a_cached_session():
    name, _cid = _new_chatter()
    here, there = _login(name), _login(name)
    _assert_cached(there)
    assert here.post("/auth/sessions/revoke-others").status_code == 200
    assert there.get("/chatter/me").json() is None, "a revoked cookie must be refused on the next request"
    assert here.get("/chatter/me").json()["username"] == name, "the revoking session's fresh cookie stays in"


def case_owner_password_reset_refuses_a_cached_session():
    name, _cid = _new_chatter()
    session = _login(name)
    _assert_cached(session)
    owner = _owner("agency_a_owner")
    r = owner.post(f"/admin/employees/{_employee_id(owner, name)}/password", json={"password": "brand-new-pw-1"})
    assert r.status_code == 200, r.text
    assert session.get("/chatter/me").json() is None


def case_owner_two_factor_reset_refuses_a_cached_session():
    name, _cid = _new_chatter()
    session = _login(name)
    _assert_cached(session)
    owner = _owner("agency_a_owner")
    r = owner.post(f"/admin/employees/{_employee_id(owner, name)}/2fa/reset")
    assert r.status_code == 200, r.text
    assert session.get("/chatter/me").json() is None, "a 2FA reset signs the login out everywhere"


def case_owner_deactivation_refuses_a_cached_session():
    name, _cid = _new_chatter()
    session = _login(name)
    assert _direct(session, IDS["creator_a"]) == (200, None)
    _assert_cached(session)
    owner = _owner("agency_a_owner")
    r = owner.patch(f"/admin/employees/{_employee_id(owner, name)}", json={"is_active": False})
    assert r.status_code == 200, r.text
    assert session.get("/chatter/me").json() is None, "a deactivated login (no Agency left) is signed out"
    assert _direct(session, IDS["creator_a"])[0] != 200


def case_owner_account_removed_disappears_on_next_request():
    name, _cid = _new_chatter()
    c = _login(name)
    assert _accounts(c) == {IDS["creator_a"], CREATOR_A2}
    _assert_cached(c)
    master = _owner("agency_master")
    pw = os.environ["ADMIN_PASSWORD"]
    r = master.request("DELETE", f"/admin/users/{IDS['agency_a_owner']}/accounts/{CREATOR_A2}",
                       json={"admin_password": pw})
    assert r.status_code == 200, r.text
    try:
        assert _accounts(c) == {IDS["creator_a"]}, "a Creator the owner lost must leave the chatter's union"
        assert _direct(c, CREATOR_A2) == DENIED
    finally:
        r = master.post(f"/admin/users/{IDS['agency_a_owner']}/accounts",
                        json={"account_id": CREATOR_A2, "admin_password": pw})
        assert r.status_code == 200, r.text
    assert _accounts(c) == {IDS["creator_a"], CREATOR_A2}, "a grant comes back on the next request too"


def case_restriction_applies_on_next_request():
    name, cid = _new_chatter()
    c = _login(name)
    assert _accounts(c) == {IDS["creator_a"], CREATOR_A2}
    assert _direct(c, CREATOR_A2) == (200, None)
    _assert_cached(c)
    owner = _owner("agency_a_owner")
    r = owner.put(f"/admin/chatters/{cid}/account-access", json={"account_ids": [IDS["creator_a"]]})
    assert r.status_code == 200, r.text
    assert _accounts(c) == {IDS["creator_a"]}
    assert _direct(c, CREATOR_A2) == DENIED
    assert _direct(c, IDS["creator_a"]) == (200, None)


def case_unlink_and_link_apply_on_next_request():
    name, _cid = _new_chatter(("agency_a_owner",))
    c = _login(name)
    assert _accounts(c) == {IDS["creator_a"], CREATOR_A2}
    _assert_cached(c)
    owner_b = _owner("agency_b_owner")
    r = owner_b.post("/admin/chatters/link", json={"username": name})
    assert r.status_code == 200, r.text
    assert _accounts(c) == {IDS["creator_a"], CREATOR_A2, IDS["creator_b"]}, "a new Agency's Creators appear"
    _assert_cached(c)
    assert owner_b.delete(f"/admin/employees/{_employee_id(owner_b, name)}").status_code == 200
    assert _accounts(c) == {IDS["creator_a"], CREATOR_A2}, "a deactivated Agency's Creators go"


def case_a_load_racing_an_invalidation_is_not_stored():
    global _invalidate_on_access_read
    name, cid = _new_chatter()
    c = _login(name)
    assert c.get("/chatter/me").json()["username"] == name
    assert identity_cache.get(cid) is not None, "control: a plain request stores the identity"
    identity_cache.invalidate()  # the next request loads
    _invalidate_on_access_read = True  # fires on the load's last read (chatter_account_access)
    try:
        assert c.get("/chatter/me").json()["username"] == name
        assert not _invalidate_on_access_read, "the load must read chatter_account_access"
    finally:
        _invalidate_on_access_read = False
    assert identity_cache.get(cid) is None, "an identity read before the write must not be pinned"


def case_last_seen_touch_keeps_the_300s_rule():
    name, cid = _new_chatter()
    c = _login(name)
    assert c.get("/chatter/me").json()["username"] == name
    old = datetime.utcnow() - timedelta(seconds=400)

    async def _age(to):
        async with get_session() as s:
            await s.execute(update(Chatter).where(Chatter.id == cid).values(last_seen_at=to))

    async def _stamp():
        async with get_session() as s:
            return (await s.execute(select(Chatter.last_seen_at).where(Chatter.id == cid))).scalar_one()
    # Stale in both the row and the cache: a hit writes it, as the row read did.
    _db(lambda: _age(old))
    identity_cache.get(cid).last_seen_at = old
    assert c.get("/chatter/me").json()["username"] == name
    assert _db(_stamp) > old + timedelta(seconds=300), "a hit older than 300 s must bump last_seen_at"
    # The cache stale, the row fresh (a sign-in bumped it): no write, the entry re-reads.
    fresh = datetime.utcnow() - timedelta(seconds=10)
    _db(lambda: _age(fresh))
    identity_cache.get(cid).last_seen_at = old
    assert c.get("/chatter/me").json()["username"] == name
    assert _db(_stamp) == fresh, "a row bumped within 300 s must not be written again"
    assert identity_cache.get(cid) is None
    # Fresh in the cache: no write at all.
    assert c.get("/chatter/me").json()["username"] == name
    _sql.clear()
    assert c.get("/chatter/me").json()["username"] == name
    assert not [q for q in _sql if q.lstrip().upper().startswith("UPDATE CHATTERS")]


def case_ttl_zero_is_off():
    saved = identity_cache.TTL_S
    identity_cache.TTL_S = 0  # CHATTERLY_CHATTER_IDENTITY_TTL_S's value
    try:
        name, cid = _new_chatter()
        c = _login(name)
        assert [_reads_of_one_request(c) for _ in range(3)] == [LOAD_READS] * 3, "TTL 0: every request loads"

        async def _drop_link():
            async with get_session() as s:
                await s.execute(ChatterUser.__table__.delete().where(ChatterUser.chatter_id == cid))
        _db(_drop_link)
        assert _accounts(c) == set(), "with the cache off a direct write shows at once"
    finally:
        identity_cache.TTL_S = saved


_harness.run()
