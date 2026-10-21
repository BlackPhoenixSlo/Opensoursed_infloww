#!/usr/bin/env python3
"""The one-time move to Role enforcement on by default (settings_api.migrate_role_enforcement_once).

Role enforcement used to be off until an owner turned it on; it is now on
unless `enforce: false` is stored. In an Agency that never chose, each Employee
login (an `employees.is_login` row) holding no role, or a role its blob does not
hold, gets the built-in Admin, so it keeps every page it reached. A held role is
kept, and now applies: such a login can lose pages. The owner's own row is
never given a role, and owners are never checked. A login linked with no
Employee row yet is not migrated: its row, made later, gets Chatter. An Agency
that stored either switch value is untouched; a marker keeps it from running
twice.

Fixture: the shared two Agencies, their Employee rows made as before this
change (no role given on joining), plus chatter_b linked to the Master's
Agency, which stored `enforce: true` with nothing assigned.

Run: ./venv/bin/python service/tests/test_role_enforcement_migration.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import employees  # noqa: E402
import settings_api  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import ChatterUser, Employee, UserSetting  # noqa: E402
from sqlalchemy import select  # noqa: E402

IDS = fx.seed_two_agencies()
REVENUE = "/admin/stats/revenue?from=2026-06-10&to=2026-06-11&group_by=day"
CLOSER = {"id": "role-closer", "name": "Closer", "description": "",
          "permissions": {"/messages-pro": True}, "scope": "self"}


def _row(chatter_id: str, owner: str) -> int:
    """The Employee row as made before this change: no role given on joining."""
    async def _make():
        original = settings_api.give_role_to_unroled

        async def _pre_deploy(*_a, **_k):
            return 0
        settings_api.give_role_to_unroled = _pre_deploy
        try:
            return await employees.get_or_create_mirror_employee(
                chatter_id, IDS[owner], display_name=chatter_id[:16], color="#bbbbbb")
        finally:
            settings_api.give_role_to_unroled = original
    emp = asyncio.run(_make())
    assert emp is not None
    return emp


def _logins(owner: str) -> dict[str, int]:
    async def _read():
        async with get_session() as s:
            rows = await s.execute(select(Employee.chatter_id, Employee.id).where(
                Employee.user_id == IDS[owner], Employee.chatter_id.is_not(None)))
            return {c: e for c, e in rows.all()}
    return asyncio.run(_read())


def _blob(owner: str) -> dict:
    async def _read():
        async with get_session() as s:
            row = await s.get(UserSetting, (IDS[owner], "roles"))
            return json.loads(row.config_json) if row else None
    return asyncio.run(_read())


async def _link_b_to_master() -> None:
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=IDS["chatter_b"], user_id=IDS["agency_master"],
                          created_at=datetime.utcnow()))


# Agency A (never chose): chatter_a holds a custom role, chatter_ab a role the blob lost.
EMP_A = _row(IDS["chatter_a"], "agency_a_owner")
EMP_AB_A = _row(IDS["chatter_ab"], "agency_a_owner")
fx.store_blob(IDS["agency_a_owner"], "roles", {
    "roles": [CLOSER], "assignments": {str(EMP_A): "role-closer", str(EMP_AB_A): "role-gone"}})
# Agency B never stored roles: chatter_b has its row, holding no role; chatter_ab is linked with no row
# yet; the owner's own row (`owner:<uid>`) exists.
EMP_B = _row(IDS["chatter_b"], "agency_b_owner")
OWNER_ROW_B = _row(f"{employees.OWNER_KEY_PREFIX}{IDS['agency_b_owner']}", "agency_b_owner")
# The Master's Agency chose: on, nothing assigned.
asyncio.run(_link_b_to_master())
MASTER_BLOB = {"enforce": True, "roles": [], "assignments": {}}
fx.store_blob(IDS["agency_master"], "roles", MASTER_BLOB)

ASSIGNED = asyncio.run(settings_api.migrate_role_enforcement_once())


def case_logins_with_no_held_role_get_admin_and_a_held_role_is_kept():
    a = _blob("agency_a_owner")
    assert a["assignments"] == {str(EMP_A): "role-closer", str(EMP_AB_A): "admin"}, a
    assert a["roles"] == [CLOSER] and "enforce" not in a, a
    # Agency B: only the login with a row; never the owner's own row, never a link with no row.
    assert _blob("agency_b_owner")["assignments"] == {str(EMP_B): "admin"}
    assert set(_logins("agency_b_owner")) == {IDS["chatter_b"], f"owner:{IDS['agency_b_owner']}"}
    assert ASSIGNED == 2, ASSIGNED


def case_an_agency_that_stored_the_switch_is_untouched():
    assert _blob("agency_master") == MASTER_BLOB
    assert _logins("agency_master") == {}


def case_admin_logins_keep_every_page_held_roles_now_apply_and_owners_are_never_locked_out():
    # chatter_a's Closer grants Messages Pro, not the Dashboard: with enforcement now on, it loses the Dashboard.
    assert fx.login_chatter("chatter_a").get(REVENUE).status_code == 403
    r = fx.login_chatter("chatter_ab").get(REVENUE, headers={"X-Account-Id": IDS["creator_a"]})
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    for owner in ("agency_a_owner", "agency_b_owner", "agency_master"):
        assert fx.login_owner(owner).get(REVENUE).status_code == 200, owner


def case_a_login_whose_row_is_made_after_the_migration_gets_chatter():
    r = fx.login_chatter("chatter_ab").get(REVENUE, headers={"X-Account-Id": IDS["creator_b"]})
    assert r.status_code in (200, 403), f"{r.status_code} {r.text}"
    emp = _logins("agency_b_owner")[IDS["chatter_ab"]]
    assert _blob("agency_b_owner")["assignments"] == {str(EMP_B): "admin", str(emp): "chatter"}


def case_it_runs_once():
    fx.store_blob(IDS["agency_a_owner"], "roles", {"assignments": {}})
    assert asyncio.run(settings_api.migrate_role_enforcement_once()) == 0
    assert _blob("agency_a_owner") == {"assignments": {}}


_harness.run()
