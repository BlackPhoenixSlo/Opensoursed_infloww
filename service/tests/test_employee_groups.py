#!/usr/bin/env python3
"""Employee groups on the Relay for the Organization Chart (docs/spec/phase-05-remaining-parity-gaps.md, item 4;
ticket 35, stories 31-33, 36, 37, 39; ticket 36, stories 34, 35, 38).

`GET /admin/employee-groups` lists the Agency's groups as `{groups:[{id,name,parent_id,employee_count}]}`;
`POST /admin/employee-groups {name, parent_id|null}` adds one under the Agency root (null) or under one of the
Agency's own groups; `PATCH /admin/employee-groups/{id} {name?, parent_id?}` renames and/or moves one (409 for a
move under itself or its own sub-group, so no cycle); `DELETE /admin/employee-groups/{id}` removes an empty one. Names are unique among siblings
(409), a missing or another Agency's parent is 404, and a group with sub-groups or Employees is 409 on delete.
`PUT /admin/employee-groups/members {group_id|null, employee_ids[]}` (Batch edit group) places the Employees in one
group, or none, in one write: another Agency's or a missing group is 404, an Employee outside the Agency 400, and
the write is all or nothing. `GET /admin/employees` carries each Employee's `group_id`. `subtree_employee_ids`, the
"Self and subordinates" Data scope's set, is the Employee plus every Employee in a strict descendant group of its own.
Every route is owner session or Master: 401 signed out (also with ALLOW_ANONYMOUS_ADMIN=1), 403 for a chatter
(also when Role enforcement grants it Manage employees), and another Agency's group is 404.

The seam is the Relay over HTTP with real session cookies from the shared two-Agency fixture. Two storage cases
close the file, each on its own `tempfile.mkdtemp` SQLite file, never the harness database or the default URL:
the `init_db()` catch-up adds the groups table and the Employee group column to a database lacking both, and the
migration round-trips upgrade → downgrade → upgrade.

Run: ./venv/bin/python service/tests/test_employee_groups.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402
from sqlalchemy import func, select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import employees  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Employee, EmployeeGroup  # noqa: E402

ROUTE = "/admin/employee-groups"
_REPO = Path(__file__).resolve().parents[2]
_MIGRATIONS = _REPO / "service" / "db" / "migrations"

IDS = fx.seed_two_agencies()
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
MASTER = fx.login_owner("agency_master")
ANON = _harness.make_client()


def _with_env(name: str, value: str, fn):
    old = os.environ.get(name)
    os.environ[name] = value
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


def _create(client, name: str, parent_id: int | None = None, status: int = 200) -> dict:
    r = client.post(ROUTE, json={"name": name, "parent_id": parent_id})
    assert r.status_code == status, f"create {name!r} under {parent_id}: {r.status_code} {r.text}"
    return r.json()


def _groups(client) -> dict[int, dict]:
    r = client.get(ROUTE)
    assert r.status_code == 200, f"list: {r.status_code} {r.text}"
    body = r.json()
    assert set(body) == {"groups"}, body
    return {g["id"]: g for g in body["groups"]}


def _delete(client, group_id: int, status: int = 200) -> dict:
    r = client.delete(f"{ROUTE}/{group_id}")
    assert r.status_code == status, f"delete {group_id}: {r.status_code} {r.text}"
    return r.json()


def _group_count() -> int:
    async def go() -> int:
        async with get_session() as s:
            return (await s.execute(select(func.count()).select_from(EmployeeGroup))).scalar_one()
    return asyncio.run(go())


def _new_employee(client, name: str) -> int:
    r = client.post("/admin/employees", json={"display_name": name})
    assert r.status_code == 200, f"employee {name}: {r.status_code} {r.text}"
    return r.json()["id"]


def _place(employee_id: int, group_id: int | None) -> None:
    """Puts an Employee in a group straight in the DB, bypassing Batch edit group."""
    async def go() -> None:
        async with get_session() as s:
            await s.execute(update(Employee).where(Employee.id == employee_id).values(group_id=group_id))
    asyncio.run(go())


def _every_route(client) -> list:
    # 401 and 403 come before 404, so an id that may not exist is fine here.
    return [
        ("GET", client.get(ROUTE)),
        ("POST", client.post(ROUTE, json={"name": "Fixture Refused", "parent_id": None})),
        ("DELETE", client.delete(f"{ROUTE}/1")),
        ("PATCH", client.patch(f"{ROUTE}/1", json={"name": "Fixture Refused"})),
        ("PUT members", client.put(f"{ROUTE}/members", json={"group_id": None, "employee_ids": [1]})),
    ]


# ── Sessions: 401, 403 ───────────────────────────────────────────────

def case_signed_out_is_401_on_every_route_with_and_without_anonymous_admin():
    for label, r in _every_route(ANON):
        assert r.status_code == 401, f"{label} signed out: {r.status_code} {r.text}"
    for label, r in _with_env("ALLOW_ANONYMOUS_ADMIN", "1", lambda: _every_route(ANON)):
        assert r.status_code == 401, f"{label} with ALLOW_ANONYMOUS_ADMIN=1: {r.status_code} {r.text}"
    assert _group_count() == 0, "a signed-out call wrote a group"


def case_a_chatter_is_403_on_every_route():
    for name in ("chatter_a", "chatter_b", "chatter_ab"):
        chatter = fx.login_chatter(name)
        for label, r in _every_route(chatter):
            assert r.status_code == 403, f"{label} as {name}: {r.status_code} {r.text}"
    assert _group_count() == 0, "a chatter wrote a group"


def case_a_chatter_is_403_even_when_role_enforcement_grants_manage_employees():
    mirror = asyncio.run(employees.get_or_create_mirror_employee(
        IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color="#bbbbbb"))
    r = OWNER_A.put("/admin/settings/roles", json={
        "enforce": True,
        "roles": [{"id": "role-team", "name": "Fixture team lead", "description": "",
                   "permissions": {"/employees": True}, "scope": "all"}],
        "assignments": {str(mirror): "role-team"}})
    assert r.status_code == 200, r.text
    try:
        chatter = fx.login_chatter("chatter_a")
        for label, r in _every_route(chatter):
            assert r.status_code == 403, f"{label} under Role enforcement: {r.status_code} {r.text}"
    finally:
        assert OWNER_A.put("/admin/settings/roles", json={}).status_code == 200
    assert _group_count() == 0, "a chatter wrote a group under Role enforcement"


# ── Create and list ──────────────────────────────────────────────────

def case_an_owner_builds_a_tree_under_the_agency_root_and_lists_it():
    sales = _create(OWNER_A, "Fixture Sales")
    assert set(sales) == {"id", "name", "parent_id", "employee_count"}, sales
    assert (sales["name"], sales["parent_id"], sales["employee_count"]) == ("Fixture Sales", None, 0), sales
    nights = _create(OWNER_A, "Fixture Nights", sales["id"])
    assert nights["parent_id"] == sales["id"], nights
    weekend = _create(OWNER_A, "Fixture Weekend", nights["id"])
    groups = _groups(OWNER_A)
    assert {g: (v["name"], v["parent_id"], v["employee_count"]) for g, v in groups.items()} == {
        sales["id"]: ("Fixture Sales", None, 0),
        nights["id"]: ("Fixture Nights", sales["id"], 0),
        weekend["id"]: ("Fixture Weekend", nights["id"], 0),
    }, groups


def case_a_name_is_trimmed_and_must_be_1_to_64_characters():
    g = _create(OWNER_A, "  Fixture Trimmed  ")
    assert g["name"] == "Fixture Trimmed", g
    before = _group_count()
    for bad in ("", "   ", "x" * 65, None, 7):
        r = OWNER_A.post(ROUTE, json={"name": bad, "parent_id": None})
        assert r.status_code == 422, f"name {bad!r}: {r.status_code} {r.text}"
    _create(OWNER_A, "y" * 64)
    assert _group_count() == before + 1


def case_sibling_names_are_unique_but_cousins_may_share_one():
    root = _create(OWNER_A, "Fixture Unique Root")
    _create(OWNER_A, "Fixture Unique Root", status=409)
    left = _create(OWNER_A, "Fixture Left", root["id"])
    right = _create(OWNER_A, "Fixture Right", root["id"])
    _create(OWNER_A, "Fixture Left", root["id"], status=409)
    a = _create(OWNER_A, "Fixture Leaf", left["id"])
    b = _create(OWNER_A, "Fixture Leaf", right["id"])
    assert a["id"] != b["id"]
    # Another Agency's group of the same name and parent (the root) is not a sibling.
    _create(OWNER_B, "Fixture Unique Root")


def case_a_missing_or_another_agencys_parent_is_404_and_writes_nothing():
    b_group = _create(OWNER_B, "Fixture B Parent")
    before = _group_count()
    for parent in (999_999, b_group["id"]):
        _create(OWNER_A, "Fixture Orphan", parent, status=404)
    assert _group_count() == before


# ── Rename and move ──────────────────────────────────────────────────

def _patch(client, group_id: int, body: dict, status: int = 200) -> dict:
    r = client.patch(f"{ROUTE}/{group_id}", json=body)
    assert r.status_code == status, f"patch {group_id} {body}: {r.status_code} {r.text}"
    return r.json()


def case_patch_renames_and_moves_a_group_and_keeps_absent_fields():
    top = _create(OWNER_A, "Fixture Move Top")
    other = _create(OWNER_A, "Fixture Move Other")
    g = _create(OWNER_A, "Fixture Move Me", top["id"])
    worker = _new_employee(OWNER_A, "Fixture Move Worker")
    _place(worker, g["id"])

    out = _patch(OWNER_A, g["id"], {"name": "  Fixture Moved  "})
    assert (out["name"], out["parent_id"], out["employee_count"]) == ("Fixture Moved", top["id"], 1), out
    out = _patch(OWNER_A, g["id"], {"parent_id": other["id"]})
    assert (out["name"], out["parent_id"]) == ("Fixture Moved", other["id"]), out
    out = _patch(OWNER_A, g["id"], {"name": "Fixture Moved Root", "parent_id": None})
    assert (out["name"], out["parent_id"]) == ("Fixture Moved Root", None), out
    assert _groups(OWNER_A)[g["id"]] == out
    # Renaming to its own name in place is not a clash with itself.
    _patch(OWNER_A, g["id"], {"name": "Fixture Moved Root"})


def case_patch_refuses_a_cycle_a_sibling_clash_and_bad_input():
    a = _create(OWNER_A, "Fixture Cycle A")
    b = _create(OWNER_A, "Fixture Cycle B", a["id"])
    c = _create(OWNER_A, "Fixture Cycle C", b["id"])
    clash = _create(OWNER_A, "Fixture Cycle Clash", a["id"])
    before = _groups(OWNER_A)

    for parent in (a["id"], b["id"], c["id"]):
        _patch(OWNER_A, a["id"], {"parent_id": parent}, status=409)
    _patch(OWNER_A, b["id"], {"parent_id": c["id"]}, status=409)
    _patch(OWNER_A, clash["id"], {"name": "Fixture Cycle B"}, status=409)
    _create(OWNER_A, "Fixture Cycle C")  # a root group named like c
    _patch(OWNER_A, c["id"], {"parent_id": None}, status=409)
    for bad in ({}, {"name": ""}, {"name": "x" * 65}, {"name": 7}, {"parent_id": "1"}, {"parent_id": True}):
        _patch(OWNER_A, b["id"], bad, status=422)
    b_group = _create(OWNER_B, "Fixture Cycle Theirs")
    _patch(OWNER_A, b["id"], {"parent_id": b_group["id"]}, status=404)
    _patch(OWNER_A, 999_999, {"name": "Fixture Ghost"}, status=404)
    _patch(OWNER_B, a["id"], {"name": "Fixture Stolen"}, status=404)
    after = _groups(OWNER_A)
    assert {k: after[k] for k in before} == before, "a refused PATCH wrote"


# ── Delete ───────────────────────────────────────────────────────────

def case_delete_removes_an_empty_group_and_is_409_for_sub_groups_or_employees():
    parent = _create(OWNER_A, "Fixture Delete Parent")
    child = _create(OWNER_A, "Fixture Delete Child", parent["id"])
    staffed = _create(OWNER_A, "Fixture Delete Staffed")
    worker = _new_employee(OWNER_A, "Fixture Group Worker")
    _place(worker, staffed["id"])
    assert _groups(OWNER_A)[staffed["id"]]["employee_count"] == 1

    _delete(OWNER_A, parent["id"], status=409)
    _delete(OWNER_A, staffed["id"], status=409)
    # A deactivated Employee is still one of the group's Employees.
    assert OWNER_A.delete(f"/admin/employees/{worker}").status_code == 200
    _delete(OWNER_A, staffed["id"], status=409)
    assert {parent["id"], child["id"], staffed["id"]} <= set(_groups(OWNER_A))

    assert _delete(OWNER_A, child["id"]) == {"deleted": child["id"]}
    assert _delete(OWNER_A, parent["id"]) == {"deleted": parent["id"]}
    _place(worker, None)
    assert _delete(OWNER_A, staffed["id"]) == {"deleted": staffed["id"]}
    groups = _groups(OWNER_A)
    assert not {parent["id"], child["id"], staffed["id"]} & set(groups), groups
    _delete(OWNER_A, parent["id"], status=404)


# ── Batch edit group, the Employee list, the subtree helper ──────────

def _members(client, group_id, employee_ids, status: int = 200):
    r = client.put(f"{ROUTE}/members", json={"group_id": group_id, "employee_ids": employee_ids})
    assert r.status_code == status, f"members {group_id} {employee_ids}: {r.status_code} {r.text}"
    return r.json()


def _roster(client) -> dict[int, dict]:
    r = client.get("/admin/employees")
    assert r.status_code == 200, r.text
    return {e["id"]: e for e in r.json()["employees"]}


def _group_of() -> dict[int, int | None]:
    async def go() -> dict[int, int | None]:
        async with get_session() as s:
            return dict((await s.execute(select(Employee.id, Employee.group_id))).all())
    return asyncio.run(go())


def case_batch_edit_group_places_the_selected_employees_in_one_group_or_none_in_one_write():
    team = _create(OWNER_A, "Fixture Batch Team")
    other = _create(OWNER_A, "Fixture Batch Other")
    e1, e2, e3 = (_new_employee(OWNER_A, f"Fixture Batch {n}") for n in ("One", "Two", "Three"))

    assert _members(OWNER_A, team["id"], [e1, e2]) == {"group_id": team["id"], "employee_ids": [e1, e2]}
    placed = _group_of()
    assert (placed[e1], placed[e2], placed[e3]) == (team["id"], team["id"], None), placed
    assert _groups(OWNER_A)[team["id"]]["employee_count"] == 2

    # One write moves Employees out of one group into another, and one to none.
    _members(OWNER_A, other["id"], [e2, e3])
    placed = _group_of()
    assert (placed[e1], placed[e2], placed[e3]) == (team["id"], other["id"], other["id"]), placed
    assert _members(OWNER_A, None, [e1, e3]) == {"group_id": None, "employee_ids": [e1, e3]}
    placed = _group_of()
    assert (placed[e1], placed[e2], placed[e3]) == (None, other["id"], None), placed
    groups = _groups(OWNER_A)
    assert (groups[team["id"]]["employee_count"], groups[other["id"]]["employee_count"]) == (0, 1), groups


def case_batch_edit_group_refuses_another_agencys_group_404_and_employees_400_writing_nothing():
    mine = _create(OWNER_A, "Fixture Refuse Mine")
    theirs = _create(OWNER_B, "Fixture Refuse Theirs")
    e_a = _new_employee(OWNER_A, "Fixture Refuse A")
    e_b = _new_employee(OWNER_B, "Fixture Refuse B")
    before = _group_of()

    for group in (theirs["id"], 999_999):
        _members(OWNER_A, group, [e_a], status=404)
    # Another Agency's Employee, or an unknown one, refuses the whole write: e_a is not placed either.
    for ids in ([e_a, e_b], [e_a, 999_999]):
        r = _members(OWNER_A, mine["id"], ids, status=400)
        assert "employee" in r["detail"].lower(), r
    _members(OWNER_B, theirs["id"], [e_a], status=400)
    _members(OWNER_B, mine["id"], [e_b], status=404)
    _members(MASTER, None, [e_a], status=400)
    _members(MASTER, mine["id"], [e_a], status=404)
    for bad in ({"group_id": mine["id"]}, {"group_id": mine["id"], "employee_ids": []},
                {"group_id": mine["id"], "employee_ids": "1"}, {"group_id": mine["id"], "employee_ids": [True]},
                {"group_id": "1", "employee_ids": [e_a]}, {"employee_ids": [e_a]}):
        r = OWNER_A.put(f"{ROUTE}/members", json=bad)
        assert r.status_code == 422, f"{bad}: {r.status_code} {r.text}"
    assert _group_of() == before


def case_the_employee_list_carries_each_employees_group_beside_its_creator_access():
    team = _create(OWNER_A, "Fixture List Team")
    placed = _new_employee(OWNER_A, "Fixture List Placed")
    loose = _new_employee(OWNER_A, "Fixture List Loose")
    _members(OWNER_A, team["id"], [placed])
    rows = _roster(OWNER_A)
    assert rows[placed]["group_id"] == team["id"], rows[placed]
    assert rows[loose]["group_id"] is None, rows[loose]
    assert all("group_id" in e and "account_ids" in e for e in rows.values()), rows


def case_the_subtree_helper_is_the_employee_and_strict_descendant_groups_never_peers():
    """A three-level tree under Agency A:

        Fixture Tree Lead (lead, peer)
        ├── Fixture Tree Mid (mid)
        │   └── Fixture Tree Deep (deep)
        └── Fixture Tree Side (side)
        Fixture Tree Elsewhere (elsewhere)      ← another root group
        (no group: loose)
    """
    from employee_groups_api import subtree_employee_ids

    lead_g = _create(OWNER_A, "Fixture Tree Lead")
    mid_g = _create(OWNER_A, "Fixture Tree Mid", lead_g["id"])
    deep_g = _create(OWNER_A, "Fixture Tree Deep", mid_g["id"])
    side_g = _create(OWNER_A, "Fixture Tree Side", lead_g["id"])
    else_g = _create(OWNER_A, "Fixture Tree Elsewhere")
    lead, peer, mid, deep, side, elsewhere, loose = (
        _new_employee(OWNER_A, f"Fixture Tree {n}")
        for n in ("Lead Person", "Peer", "Mid Person", "Deep Person", "Side Person", "Elsewhere Person", "Loose"))
    for group, ids in ((lead_g, [lead, peer]), (mid_g, [mid]), (deep_g, [deep]), (side_g, [side]),
                       (else_g, [elsewhere])):
        _members(OWNER_A, group["id"], ids)

    agency = IDS["agency_a_owner"]
    tree = lambda e: asyncio.run(subtree_employee_ids(agency, e))  # noqa: E731
    assert tree(lead) == {lead, mid, deep, side}
    assert tree(peer) == {peer, mid, deep, side}
    assert tree(mid) == {mid, deep}
    assert tree(deep) == {deep}
    assert tree(side) == {side}
    assert tree(elsewhere) == {elsewhere}
    assert tree(loose) == {loose}
    # Another Agency's helper call never reads Agency A's tree.
    assert asyncio.run(subtree_employee_ids(IDS["agency_b_owner"], lead)) == {lead}


# ── Agencies ─────────────────────────────────────────────────────────

def case_another_agencys_groups_are_invisible_and_404():
    a_group = _create(OWNER_A, "Fixture A Private")
    b_groups = _groups(OWNER_B)
    assert a_group["id"] not in b_groups, b_groups
    assert all(g["name"] != "Fixture A Private" for g in b_groups.values()), b_groups
    _delete(OWNER_B, a_group["id"], status=404)
    _create(OWNER_B, "Fixture Into A", a_group["id"], status=404)
    assert a_group["id"] in _groups(OWNER_A)


def case_the_master_manages_its_own_agencys_groups_only():
    a_group = _create(OWNER_A, "Fixture A For Master")
    mine = _create(MASTER, "Fixture Master Team")
    child = _create(MASTER, "Fixture Master Sub", mine["id"])
    groups = _groups(MASTER)
    assert set(groups) == {mine["id"], child["id"]}, groups
    _delete(MASTER, a_group["id"], status=404)
    _create(MASTER, "Fixture Master Into A", a_group["id"], status=404)
    _delete(MASTER, child["id"])
    _delete(MASTER, mine["id"])
    assert _groups(MASTER) == {}
    assert a_group["id"] in _groups(OWNER_A)


# ── Storage: init_db() catch-up and the migration ────────────────────

def _columns(path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[1] for r in conn.execute(f"pragma table_info({table})")}
    finally:
        conn.close()


def _tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    finally:
        conn.close()


def _indexes(path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[1] for r in conn.execute(f"pragma index_list({table})")}
    finally:
        conn.close()


def _init_db_on(path: Path) -> None:
    """`init_db()` in a child process bound to `path` only (`DATABASE_URL`), never the harness file."""
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{path}", "CHATTERLY_DB_URL": f"sqlite:///{path}",
           "CHATTERLY_TEST_MODE": "1"}
    code = "import asyncio; from db.engine import init_db; asyncio.run(init_db())"
    r = subprocess.run([sys.executable, "-c", code], cwd=_REPO / "service", env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"init_db on {path}: {r.returncode}\n{r.stdout}\n{r.stderr}"


def case_init_db_adds_the_groups_table_and_the_employee_group_column_to_a_database_lacking_them():
    workdir = Path(tempfile.mkdtemp(prefix="employee_groups_catchup_"))
    path = workdir / "catchup.db"
    assert path != Path(_harness.DB_PATH)
    try:
        _init_db_on(path)  # a fresh file: create_all, stamped
        conn = sqlite3.connect(path)
        try:
            conn.execute("DROP TABLE employee_groups")
            conn.execute("ALTER TABLE employees DROP COLUMN group_id")
            conn.commit()
        finally:
            conn.close()
        assert "employee_groups" not in _tables(path) and "group_id" not in _columns(path, "employees")

        _init_db_on(path)  # alembic_version exists: the additive catch-up

        assert "employee_groups" in _tables(path)
        assert {"id", "agency_user_id", "parent_id", "name", "created_at"} <= _columns(path, "employee_groups")
        assert "ix_employee_groups_agency" in _indexes(path, "employee_groups"), _indexes(path, "employee_groups")
        assert "group_id" in _columns(path, "employees")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _load_migration():
    found = sorted((_MIGRATIONS / "versions").glob("*_employee_groups.py"))
    assert len(found) == 1, f"want one *_employee_groups.py, found {found}"
    spec = importlib.util.spec_from_file_location(found[0].stem, found[0])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def case_the_migration_is_on_the_single_head_and_round_trips_on_a_throwaway_file():
    mod = _load_migration()
    assert mod.down_revision == "0069_attr_view_sales_records", mod.down_revision
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(_MIGRATIONS / "alembic.ini"), "heads"],
        cwd=_REPO, env={**os.environ, "PYTHONPATH": str(_REPO)}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    heads = [line for line in r.stdout.splitlines() if line.strip()]
    assert len(heads) == 1 and heads[0].endswith("(head)"), r.stdout
    # A later revision may sit on top of this one; it still lies on the single line of history.
    h = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(_MIGRATIONS / "alembic.ini"), "history"],
        cwd=_REPO, env={**os.environ, "PYTHONPATH": str(_REPO)}, capture_output=True, text=True, timeout=300)
    assert h.returncode == 0 and f"-> {mod.revision}" in h.stdout, h.stdout[-2000:]

    workdir = Path(tempfile.mkdtemp(prefix="employee_groups_migration_"))
    path = workdir / "mig.db"
    assert path != Path(_harness.DB_PATH)
    conn = sqlite3.connect(path)
    try:
        # The predecessor's shape of the two tables the revision touches.
        conn.execute("CREATE TABLE users (id VARCHAR PRIMARY KEY, username VARCHAR NOT NULL)")
        conn.execute("CREATE TABLE employees (id INTEGER PRIMARY KEY, display_name VARCHAR NOT NULL, "
                     "user_id VARCHAR, chatter_id VARCHAR)")
        conn.commit()
    finally:
        conn.close()
    engine = sa.create_engine(f"sqlite:///{path}")
    try:
        def _run(step) -> None:
            with engine.begin() as c:
                with Operations.context(MigrationContext.configure(c)):
                    step()

        _run(mod.upgrade)
        assert "employee_groups" in _tables(path) and "group_id" in _columns(path, "employees")
        assert "ix_employee_groups_agency" in _indexes(path, "employee_groups")
        _run(mod.upgrade)  # idempotent, as the house's inspector-guarded revisions are
        _run(mod.downgrade)
        assert "employee_groups" not in _tables(path), _tables(path)
        assert "group_id" not in _columns(path, "employees"), _columns(path, "employees")
        assert _columns(path, "employees") == {"id", "display_name", "user_id", "chatter_id"}
        _run(mod.upgrade)
        assert "employee_groups" in _tables(path) and "group_id" in _columns(path, "employees")
        conn = sqlite3.connect(path)
        try:
            conn.execute("INSERT INTO users (id, username) VALUES ('u1', 'fixture_owner')")
            conn.execute("INSERT INTO employee_groups (agency_user_id, parent_id, name) VALUES ('u1', NULL, 'G')")
            conn.execute("INSERT INTO employee_groups (agency_user_id, parent_id, name) VALUES ('u1', 1, 'G')")
            try:
                conn.execute("INSERT INTO employee_groups (agency_user_id, parent_id, name) VALUES ('u1', 1, 'G')")
                raise AssertionError("UNIQUE(agency_user_id, parent_id, name) did not hold")
            except sqlite3.IntegrityError:
                pass
        finally:
            conn.close()
    finally:
        engine.dispose()
        shutil.rmtree(workdir, ignore_errors=True)


_harness.run()
