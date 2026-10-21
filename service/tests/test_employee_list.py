#!/usr/bin/env python3
"""The Employee list on the Relay for Manage employees (docs/spec/phase-05-remaining-parity-gaps.md, item 1).

`GET /admin/employees` gains `account_ids` on each row: the Employee's Creator
access, `null` meaning all Creators (the wildcard access row), a list of
Creator ids otherwise, and `[]` with no access. Every field it had before is
unchanged. The list is owner-only: a chatter session is refused 403 and an
unauthenticated caller 401, and one Agency's owner never sees another
Agency's Employees. Deactivate and re-activate are the existing soft-disable
(`DELETE`) and `PATCH {is_active: true}`, read back through the list.

The seam is the Relay over HTTP with real session cookies from the shared
two-Agency fixture.

ASSUMPTION: these cases live here, not in service/tests/test_employee_groups.py
where the spec's Testing Decisions put them, because that file is ticket 35's
and does not exist yet. Rung 5 (smallest: a new file suite.sh runs). Overturned
by ticket 35 folding these cases into test_employee_groups.py, or by Phase 5's
Acceptance block listing this file.

Run: ./venv/bin/python service/tests/test_employee_list.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import _agency_fixtures as fx  # noqa: E402

LIST = "/admin/employees"

IDS = fx.seed_two_agencies()

OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
MASTER = fx.login_owner("agency_master")
CHATTER_A = fx.login_chatter("chatter_a")
CHATTER_AB = fx.login_chatter("chatter_ab")
ANON = _harness.make_client()


def _create(client, name: str) -> int:
    r = client.post(LIST, json={"display_name": name})
    assert r.status_code == 200, f"create {name}: {r.status_code} {r.text}"
    return r.json()["id"]


def _grant(client, employee_id: int, body: dict) -> None:
    r = client.put(f"{LIST}/{employee_id}/access", json=body)
    assert r.status_code == 200, f"access {employee_id}: {r.status_code} {r.text}"


def _rows(client) -> dict[int, dict]:
    r = client.get(LIST)
    assert r.status_code == 200, f"list: {r.status_code} {r.text}"
    return {row["id"]: row for row in r.json()["employees"]}


EMP_ALL = _create(OWNER_A, "Fixture All Creators")
EMP_ONE = _create(OWNER_A, "Fixture One Creator")
EMP_NONE = _create(OWNER_A, "Fixture No Access")
EMP_B = _create(OWNER_B, "Fixture Agency B")
_grant(OWNER_A, EMP_ALL, {"account_ids": [], "wildcard": True})
_grant(OWNER_A, EMP_ONE, {"account_ids": [IDS["creator_a"]]})
_grant(OWNER_B, EMP_B, {"account_ids": [IDS["creator_b"]]})


def case_each_row_carries_its_creator_access():
    rows = _rows(OWNER_A)
    assert rows[EMP_ALL]["account_ids"] is None, rows[EMP_ALL]
    assert rows[EMP_ONE]["account_ids"] == [IDS["creator_a"]], rows[EMP_ONE]
    assert rows[EMP_NONE]["account_ids"] == [], rows[EMP_NONE]


def case_existing_fields_are_unchanged():
    row = _rows(OWNER_A)[EMP_ONE]
    # `group_id` is item 4's additive field (ticket 36; covered in test_employee_groups.py).
    # `kind` and `user_id` are additive (the owner row and the name-only rows read apart from logins).
    assert set(row) == {"id", "display_name", "color", "is_active", "chatter_id",
                        "created_at", "account_ids", "group_id", "kind", "user_id"}, sorted(row)
    assert row["group_id"] is None, row
    assert row["display_name"] == "Fixture One Creator" and row["is_active"] is True, row
    assert row["chatter_id"] is None and row["kind"] == "name", row



def case_a_chatter_is_refused_403():
    for chatter in (CHATTER_A, CHATTER_AB):
        for query in ("", "?include_disabled=false"):
            r = chatter.get(LIST + query)
            assert r.status_code == 403, f"{query}: {r.status_code} {r.text}"


def case_an_unauthenticated_caller_gets_401():
    r = ANON.get(LIST)
    assert r.status_code == 401, f"{r.status_code} {r.text}"


def _every_employee_route() -> list:
    """Every Manage employees route on one Employee: Assign (ticket 31) and Deactivate / re-activate."""
    return [
        ("GET access", "GET", f"{LIST}/{EMP_ONE}/access", None),
        ("PUT access", "PUT", f"{LIST}/{EMP_ONE}/access", {"account_ids": [IDS["creator_b"]]}),
        ("PATCH is_active", "PATCH", f"{LIST}/{EMP_ONE}", {"is_active": False}),
        ("DELETE deactivate", "DELETE", f"{LIST}/{EMP_ONE}", None),
    ]


def case_every_employee_route_is_401_signed_out_and_404_across_agencies():
    """Story 55: signed out is 401, and Agency B's owner gets 404 on Agency A's Employee, which stays unchanged."""
    for client, want in ((ANON, 401), (OWNER_B, 404)):
        for label, method, path, body in _every_employee_route():
            r = client.request(method, path, json=body)
            assert r.status_code == want, f"{label} expected {want}: {r.status_code} {r.text}"
    row = _rows(OWNER_A)[EMP_ONE]
    assert row["account_ids"] == [IDS["creator_a"]], f"a refused write changed the access: {row}"
    assert row["is_active"] is True, f"a refused write changed is_active: {row}"


def case_another_agencys_employees_never_appear():
    a, b = _rows(OWNER_A), _rows(OWNER_B)
    assert EMP_B not in a and set(a) >= {EMP_ALL, EMP_ONE, EMP_NONE}, sorted(a)
    # Agency B's list is its owner row, its own name-only row and its own logins' Employee rows.
    assert {i for i, r in b.items() if r["kind"] == "name"} == {EMP_B}, sorted(b)
    assert [r["display_name"] for r in b.values() if r["kind"] == "owner"] == ["agency_b_owner"], b
    assert {r["chatter_id"] for r in b.values() if r["chatter_id"]} == {IDS["chatter_b"], IDS["chatter_ab"]}, b
    assert b[EMP_B]["account_ids"] == [IDS["creator_b"]], b[EMP_B]


def _login_row(client, chatter: str) -> dict:
    rows = [r for r in _rows(client).values() if r["chatter_id"] == IDS[chatter]]
    assert len(rows) == 1, rows
    return rows[0]


def case_every_linked_login_is_listed_as_an_employee_before_it_acts():
    """A login linked to the Agency is an Employee at once (its row is made on the list read), with its
    username, Activated, and every Creator while no allowlist narrows it."""
    row = _login_row(OWNER_A, "chatter_a")
    assert row["username"] == "chatter_a" and row["is_active"] is True, row
    assert row["account_ids"] is None, row
    assert {r["username"] for r in _rows(OWNER_A).values() if r["chatter_id"]} == {"chatter_a", "chatter_ab"}


def case_a_logins_creator_access_is_the_enforced_allowlist():
    eid = _login_row(OWNER_A, "chatter_a")["id"]
    _grant(OWNER_A, eid, {"account_ids": [IDS["creator_a"]]})
    assert _login_row(OWNER_A, "chatter_a")["account_ids"] == [IDS["creator_a"]]
    r = OWNER_A.get(f"/admin/chatters/{IDS['chatter_a']}/access")
    assert r.status_code == 200 and r.json()["account_ids"] == [IDS["creator_a"]], r.text
    # Another Agency's Creator is refused, and an empty set (it would read back as every Creator) too.
    r = OWNER_A.put(f"{LIST}/{eid}/access", json={"account_ids": [IDS["creator_b"]]})
    assert r.status_code == 403, f"{r.status_code} {r.text}"
    r = OWNER_A.put(f"{LIST}/{eid}/access", json={"account_ids": []})
    assert r.status_code == 400, f"{r.status_code} {r.text}"
    assert _login_row(OWNER_A, "chatter_a")["account_ids"] == [IDS["creator_a"]]
    _grant(OWNER_A, eid, {"account_ids": [], "wildcard": True})
    assert _login_row(OWNER_A, "chatter_a")["account_ids"] is None


def case_deactivating_a_login_unlinks_it_and_activating_links_it_again():
    chatter_b = fx.login_chatter("chatter_b")
    assert [a["account_id"] for a in chatter_b.get("/chatter/me/accounts").json()] == [IDS["creator_b"]]
    eid = _login_row(OWNER_B, "chatter_b")["id"]
    r = OWNER_B.delete(f"{LIST}/{eid}")
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert _login_row(OWNER_B, "chatter_b")["is_active"] is False
    assert all(r["chatter_id"] != IDS["chatter_b"] for r in OWNER_B.get(LIST + "?include_disabled=false")
               .json()["employees"])
    # Its only Agency gone, the login is signed out everywhere (S14) and told why at sign-in (6.14).
    assert chatter_b.get("/chatter/me").json() is None
    r = chatter_b.post("/chatter/login", json={"username": "chatter_b", "password": fx.PASSWORD})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "account_deactivated", r.text
    r = OWNER_B.patch(f"{LIST}/{eid}", json={"is_active": True})
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert _login_row(OWNER_B, "chatter_b")["is_active"] is True
    chatter_b = fx.login_chatter("chatter_b")
    assert [a["account_id"] for a in chatter_b.get("/chatter/me/accounts").json()] == [IDS["creator_b"]]


def case_the_master_still_sees_every_agency():
    rows = _rows(MASTER)
    assert {EMP_ALL, EMP_ONE, EMP_NONE, EMP_B} <= set(rows), sorted(rows)
    assert rows[EMP_ALL]["account_ids"] is None, rows[EMP_ALL]


def case_deactivate_and_reactivate_round_trip_through_the_soft_disable():
    r = OWNER_A.delete(f"{LIST}/{EMP_NONE}")
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert _rows(OWNER_A)[EMP_NONE]["is_active"] is False
    r = OWNER_A.patch(f"{LIST}/{EMP_NONE}", json={"is_active": True})
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert _rows(OWNER_A)[EMP_NONE]["is_active"] is True


def _owner_row(client) -> dict:
    rows = [r for r in _rows(client).values() if r["kind"] == "owner"]
    assert len(rows) == 1, rows
    return rows[0]


def _last_write_by(client, path: str) -> dict:
    rows = [a for a in client.get("/admin/audit", params={"limit": 500}).json()["actions"]
            if a["action"] == f"PATCH {path}"]
    assert rows, path
    return rows[0]


def case_an_owner_session_acts_as_the_owner_without_picking_a_name():
    """No "Who's chatting?": an Owner session's write lands on the owner's own row, with no header."""
    owner = _owner_row(OWNER_A)
    assert owner["display_name"] == "agency_a_owner" and owner["chatter_id"] is None, owner
    path = f"{LIST}/{EMP_ONE}"
    r = OWNER_A.patch(path, json={"color": "#112233"})
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert _last_write_by(OWNER_A, path)["employee_id"] == owner["id"]
    # A header naming another Agency's row is a spoof: still the owner, never that row.
    r = OWNER_A.patch(path, json={"color": "#445566"}, headers={"X-Employee-Id": str(EMP_B)})
    assert r.status_code == 200, r.text
    assert _last_write_by(OWNER_A, path)["employee_id"] == owner["id"]
    assert _owner_row(OWNER_A)["id"] == owner["id"]  # one owner row, however often it is read


def case_the_owner_row_cannot_be_deleted_or_limited():
    oid = _owner_row(OWNER_A)["id"]
    assert OWNER_A.delete(f"{LIST}/{oid}").status_code == 400
    assert OWNER_A.put(f"{LIST}/{oid}/access", json={"account_ids": [IDS["creator_a"]]}).status_code == 400
    assert _owner_row(OWNER_A)["is_active"] is True


def case_the_role_presets_are_seeded_once_and_stay_deleted():
    """Manager / VA arrive as ordinary roles beside the built-in Owner, Admin, Team Leader, Chatter and Creator
    (Chatter is built in since w5-a, so it is no longer a preset); a deleted one is never put back."""
    _rows(OWNER_B)  # any owner read seeds
    roles = OWNER_B.get("/admin/settings/roles").json()["config"]["roles"]
    assert [r["name"] for r in roles] == ["Manager", "VA"], roles
    by = {r["id"]: r for r in roles}
    assert by["manager"]["permissions"].get("/messages-pro") is True and by["manager"]["scope"] == "all"
    assert not by["va"]["permissions"].get("/messages-pro") and not by["va"]["permissions"].get("/")
    r = OWNER_B.put("/admin/settings/roles", json={"roles": [by["va"]]})
    assert r.status_code == 200, r.text
    _rows(OWNER_B)
    assert [x["id"] for x in OWNER_B.get("/admin/settings/roles").json()["config"]["roles"]] == ["va"]


def case_every_preset_page_is_a_permission_page():
    from settings_api import ROLE_PRESETS
    from settings_schema import BUILT_IN_ROLE_DEFAULTS
    from permissions import PAGE_MAP
    for p in ROLE_PRESETS:
        assert set(p["pages"]) <= set(PAGE_MAP), (p["id"], set(p["pages"]) - set(PAGE_MAP))
    for rid, d in BUILT_IN_ROLE_DEFAULTS.items():
        assert set(d["pages"]) <= set(PAGE_MAP), (rid, set(d["pages"]) - set(PAGE_MAP))


def case_an_unstored_built_in_role_grants_its_defaults():
    """Team Leader / Chatter / Creator are built in (Infloww's live default roles, w5-a): never stored, they
    grant their default pages and scope; stored, the stored copy wins; Owner / Admin still grant every page."""
    from permissions import _role, _EVERY_PAGE
    from settings_schema import BUILT_IN_ROLE_DEFAULTS
    blob = {"roles": [], "assignments": {"1": "team-leader", "2": "chatter", "3": "creator", "4": "admin", "5": "x"}}
    for emp, rid in ((1, "team-leader"), (2, "chatter"), (3, "creator")):
        role = _role(blob, emp)
        assert role["id"] == rid and role["scope"] == BUILT_IN_ROLE_DEFAULTS[rid]["scope"], role
        assert {h for h, on in role["permissions"].items() if on} == set(BUILT_IN_ROLE_DEFAULTS[rid]["pages"])
    assert _role(blob, 2)["permissions"].get("/messages-pro") is True
    assert not _role(blob, 3)["permissions"].get("/messages-pro")
    assert _role(blob, 1)["scope"] == "subordinates" and _role(blob, 2)["scope"] == "self"
    assert _role(blob, 4) is _EVERY_PAGE and _role(blob, 5) is None
    stored = {"id": "chatter", "name": "Chatter", "permissions": {"/": True}, "scope": "self"}
    assert _role({**blob, "roles": [stored]}, 2) is stored


def case_the_built_in_roles_are_assignable():
    for rid in ("team-leader", "chatter", "creator"):
        r = OWNER_A.post("/admin/chatters/invite", json={"role_id": rid})
        assert r.status_code == 200, (rid, r.text)
    assert OWNER_A.post("/admin/chatters/invite", json={"role_id": "owner"}).status_code == 400
    r = OWNER_A.put("/admin/settings/roles", json={"roles": [], "assignments": {}})
    assert r.status_code == 200, r.text


_harness.run()
