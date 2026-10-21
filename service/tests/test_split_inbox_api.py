#!/usr/bin/env python3
"""
split_inbox_api — the Split Inbox store on account_ai_config.split_inbox_json
(ADR-0004; docs/spec/phase-02-fan-list-pane.md, Contracts).

Drives GET/PUT /admin/split-inbox over HTTP through the harness client against
the temp DB, so router registration and the session middleware are exercised.
Cookie cases follow test_chatter_auth.py: an owner, one Creator of hers, and a
chatter linked to her. Covers the unset default, an owner's round trip, the
owner gate (chatter GET 200 / PUT 403, anonymous 401), 422 on a bad count or a
non-object assignments, dropped out-of-range entries and unknown keys, and the
start-up catch-up that adds the column to an existing database.

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

client = _harness.make_client()
import server  # noqa: E402 — already imported by make_client; fresh clients below
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402

ACCOUNT = "acct_split_owner"
PASSWORD = "secretpw"
UNSET = {"group_count": 1, "assignments": {}}


async def _seed() -> None:
    owner = uuid.uuid4().hex
    chatter = uuid.uuid4().hex
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(User(id=owner, username="splitowner", password=PASSWORD))
        s.add(Account(id=ACCOUNT, nickname="split model", color="#aaaaaa"))
        s.add(UserAccount(user_id=owner, account_id=ACCOUNT))
        s.add(Chatter(id=chatter, username="splitchatter", password=PASSWORD,
                      display_name="Splitchatter", created_at=now, last_seen_at=now))
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=chatter, user_id=owner, created_at=now))
    # An install from before role enforcement was on by default: its logins hold Admin.
    await seed_pre_enforcement_install()


asyncio.run(_seed())


def _owner() -> TestClient:
    c = TestClient(server.app)
    r = c.post("/auth/login", json={"username": "splitowner", "password": PASSWORD})
    assert r.status_code == 200, f"owner login failed: {r.status_code} {r.text}"
    return c


def _chatter() -> TestClient:
    c = TestClient(server.app)
    r = c.post("/chatter/login", json={"username": "splitchatter", "password": PASSWORD})
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
    assert r.json() == {"account_id": ACCOUNT, "config": UNSET}, r.json()


def case_an_owner_put_then_get_round_trips():
    owner = _owner()
    cfg = {"group_count": 3, "assignments": {"501": 2, "502": 3}}
    r = _put(owner, cfg)
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"account_id": ACCOUNT, "config": cfg}, r.json()
    r = _get(owner)
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"account_id": ACCOUNT, "config": cfg}, r.json()


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
    ):
        r = _put(owner, bad)
        assert r.status_code == 422, (bad, r.status_code, r.text)
    assert asyncio.run(_stored()) == before, "a rejected save must not write"


def case_out_of_range_entries_and_unknown_keys_are_dropped():
    owner = _owner()
    r = _put(owner, {
        "group_count": 2,
        "assignments": {"601": 1, "602": 3, "603": 0, "604": "2", "605": 2, "606": None},
        # Story 54: the store can hold no Employee binding.
        "employee_ids": {"1": [7]},
    })
    assert r.status_code == 200, (r.status_code, r.text)
    want = {"group_count": 2, "assignments": {"601": 1, "605": 2}}
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


_harness.run()
