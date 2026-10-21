#!/usr/bin/env python3
"""The one-time grant of Bookmarks to stored roles granting Collections (settings_api.migrate_bookmarks_page_once).

Bookmarks left Collections for a page of its own; a stored role (custom, a seeded preset, a saved built-in copy)
that granted Collections reached it before, so it is given Bookmarks once. A role not granting Collections, or
already holding the Bookmarks key, is untouched; so is the rest of the blob. A marker keeps it from running twice.

Run: ./venv/bin/python service/tests/test_bookmarks_page_migration.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import settings_api  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import UserSetting  # noqa: E402

IDS = fx.seed_two_agencies()
COLL, BOOK = "/of-manager/collections", "/of-manager/collections/bookmarks/all"


def _role(rid: str, perms: dict) -> dict:
    return {"id": rid, "name": rid, "description": "", "permissions": perms, "scope": "self"}


def _blob(owner: str) -> dict | None:
    async def _read():
        async with get_session() as s:
            row = await s.get(UserSetting, (IDS[owner], "roles"))
            return json.loads(row.config_json) if row else None
    return asyncio.run(_read())


A_BEFORE = {
    "enforce": True,
    "roles": [
        _role("va", {COLL: True, "/messages-pro": True}),        # the seeded VA preset
        _role("creator", {COLL: True}),                          # a saved built-in Creator copy
        _role("closer", {COLL: False, "/messages-pro": True}),   # Collections off
        _role("chosen", {COLL: True, BOOK: False}),              # Bookmarks already chosen
        "not a role",
    ],
    "assignments": {"7": "va"},
}
fx.store_blob(IDS["agency_a_owner"], "roles", A_BEFORE)
B_BEFORE = {"roles": [_role("plain", {"/messages-pro": True})]}
fx.store_blob(IDS["agency_b_owner"], "roles", B_BEFORE)

WIDENED = asyncio.run(settings_api.migrate_bookmarks_page_once())


def case_roles_granting_collections_get_bookmarks_and_nothing_else_moves():
    a = _blob("agency_a_owner")
    perms = {r["id"]: r["permissions"] for r in a["roles"] if isinstance(r, dict)}
    assert perms == {
        "va": {COLL: True, "/messages-pro": True, BOOK: True},
        "creator": {COLL: True, BOOK: True},
        "closer": {COLL: False, "/messages-pro": True},
        "chosen": {COLL: True, BOOK: False},
    }, perms
    assert a["roles"][-1] == "not a role" and a["enforce"] is True and a["assignments"] == {"7": "va"}, a
    assert _blob("agency_b_owner") == B_BEFORE
    assert WIDENED == 2, WIDENED


def case_it_runs_once():
    fx.store_blob(IDS["agency_b_owner"], "roles", {"roles": [_role("late", {COLL: True})]})
    assert asyncio.run(settings_api.migrate_bookmarks_page_once()) == 0
    assert _blob("agency_b_owner")["roles"][0]["permissions"] == {COLL: True}


_harness.run()
