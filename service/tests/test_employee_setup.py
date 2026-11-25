import _harness

_harness.bootstrap()

import _agency_fixtures as fx  # noqa: E402

LIST = "/admin/employees"
IDS = fx.seed_two_agencies()
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
CHATTER_A = fx.login_chatter("chatter_a")


def _rows(client) -> dict[int, dict]:
    r = client.get(LIST)
    assert r.status_code == 200, r.text
    return {e["id"]: e for e in r.json()["employees"]}


def _assignments(client) -> dict[str, str]:
    return client.get("/admin/settings/roles").json()["config"].get("assignments", {})


def _sign_in(username: str, password: str) -> int:
    return _harness.make_client().post("/chatter/login", json={"username": username, "password": password}).status_code


def case_the_owner_creates_a_login_with_its_role_and_creators():
    r = OWNER_A.post(f"{LIST}/login", json={
        "username": "made_by_owner", "password": "secret-1", "display_name": "Made By Owner",
        "role_id": "chatter", "account_ids": [IDS["creator_a"]],
    })
    assert r.status_code == 200, r.text
    eid = r.json()["employee_id"]
    row = _rows(OWNER_A)[eid]
    assert row["kind"] == "login" and row["username"] == "made_by_owner" and row["is_active"] is True, row
    assert row["display_name"] == "Made By Owner" and row["account_ids"] == [IDS["creator_a"]], row
    assert _assignments(OWNER_A)[str(eid)] == "chatter"
    assert _sign_in("made_by_owner", "secret-1") == 200
    assert OWNER_A.post(f"{LIST}/login", json={"username": "made_by_owner", "password": "secret-1"}).status_code == 409
    assert OWNER_A.post(f"{LIST}/login", json={"username": "x_role", "password": "secret-1", "role_id": "nope"}).status_code == 400
    assert OWNER_A.post(f"{LIST}/login", json={
        "username": "x_creator", "password": "secret-1", "account_ids": [IDS["creator_b"]]}).status_code == 403


def case_an_invite_carries_the_role_and_creators_until_it_is_accepted():
    r = OWNER_A.post("/admin/chatters/invite", json={"role_id": "va", "account_ids": [IDS["creator_a"]]})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    new = _harness.make_client()
    r = new.post(f"/chatter/register?token={token}", json={"username": "invited_va", "password": "secret-2"})
    assert r.status_code == 200, r.text
    row = next(e for e in _rows(OWNER_A).values() if e.get("username") == "invited_va")
    assert row["account_ids"] == [IDS["creator_a"]], row
    assert _assignments(OWNER_A)[str(row["id"])] == "va"
    assert OWNER_A.post("/admin/chatters/invite").status_code == 200
    assert OWNER_A.post("/admin/chatters/invite", json={"role_id": "nope"}).status_code == 400


def case_linking_an_existing_login_applies_the_setup_at_once():
    r = OWNER_B.post("/admin/chatters/link", json={"username": "made_by_owner", "role_id": "manager"})
    assert r.status_code == 200, r.text
    eid = r.json()["employee_id"]
    assert _rows(OWNER_B)[eid]["username"] == "made_by_owner"
    assert _assignments(OWNER_B)[str(eid)] == "manager"


def case_edit_saves_name_role_creators_and_group_together():
    eid = next(e["id"] for e in _rows(OWNER_A).values() if e.get("username") == "invited_va")
    g = OWNER_A.post("/admin/employee-groups", json={"name": "Night shift"})
    assert g.status_code in (200, 201), g.text
    gid = g.json()["id"]
    r = OWNER_A.put(f"{LIST}/{eid}/setup", json={
        "display_name": "Renamed VA", "role_id": "manager", "account_ids": None, "group_id": gid})
    assert r.status_code == 200, r.text
    row = _rows(OWNER_A)[eid]
    assert (row["display_name"], row["account_ids"], row["group_id"]) == ("Renamed VA", None, gid), row
    assert _assignments(OWNER_A)[str(eid)] == "manager"
    r = OWNER_A.put(f"{LIST}/{eid}/setup", json={"role_id": None})
    assert r.status_code == 200 and _assignments(OWNER_A)[str(eid)] == "chatter", r.text
    assert OWNER_B.put(f"{LIST}/{eid}/setup", json={"display_name": "x"}).status_code == 404
    owner_row = next(e["id"] for e in _rows(OWNER_A).values() if e["kind"] == "owner")
    assert OWNER_A.put(f"{LIST}/{owner_row}/setup", json={"display_name": "x"}).status_code == 400


def case_the_owner_resets_an_employees_password():
    eid = next(e["id"] for e in _rows(OWNER_A).values() if e.get("username") == "invited_va")
    r = OWNER_A.post(f"{LIST}/{eid}/password", json={"password": "brand-new-pw"})
    assert r.status_code == 200, r.text
    assert _sign_in("invited_va", "secret-2") == 401
    assert _sign_in("invited_va", "brand-new-pw") == 200
    assert OWNER_A.post(f"{LIST}/{eid}/password", json={"password": "123"}).status_code == 400


def case_reset_password_is_owner_only_and_never_on_a_shared_login():
    eid = next(e["id"] for e in _rows(OWNER_A).values() if e.get("username") == "invited_va")
    assert CHATTER_A.post(f"{LIST}/{eid}/password", json={"password": "hijacked"}).status_code == 403
    assert OWNER_B.post(f"{LIST}/{eid}/password", json={"password": "hijacked"}).status_code == 404
    assert _harness.make_client().post(f"{LIST}/{eid}/password", json={"password": "hijacked"}).status_code == 401
    shared = next(e["id"] for e in _rows(OWNER_A).values() if e.get("username") == "made_by_owner")
    r = OWNER_A.post(f"{LIST}/{shared}/password", json={"password": "hijacked"})
    assert r.status_code == 409, r.text
    assert _sign_in("made_by_owner", "secret-1") == 200


def case_pending_invites_are_listed_resent_and_revoked():
    r = OWNER_A.post("/admin/chatters/invite", json={"display_name": "Pending Pat", "role_id": "chatter",
                                                     "account_ids": [IDS["creator_a"]]})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    rows = OWNER_A.get("/admin/chatters/invites").json()
    row = next(i for i in rows if i["token"] == token)
    assert (row["display_name"], row["role_id"], row["account_ids"]) == ("Pending Pat", "chatter", [IDS["creator_a"]])
    assert all(i["token"] != token for i in OWNER_B.get("/admin/chatters/invites").json())
    assert OWNER_B.delete(f"/admin/chatters/invites/{token}").status_code == 404
    assert OWNER_B.post(f"/admin/chatters/invites/{token}/resend").status_code == 404
    assert CHATTER_A.get("/admin/chatters/invites").status_code == 403

    r = OWNER_A.post(f"/admin/chatters/invites/{token}/resend")
    assert r.status_code == 200, r.text
    fresh = r.json()["token"]
    assert fresh != token
    assert _harness.make_client().get(f"/chatter/invite/{token}").status_code != 200
    row = next(i for i in OWNER_A.get("/admin/chatters/invites").json() if i["token"] == fresh)
    assert row["display_name"] == "Pending Pat" and row["role_id"] == "chatter"

    assert OWNER_A.delete(f"/admin/chatters/invites/{fresh}").status_code == 200
    assert all(i["token"] != fresh for i in OWNER_A.get("/admin/chatters/invites").json())
    assert OWNER_A.delete(f"/admin/chatters/invites/{fresh}").status_code == 404
    r = _harness.make_client().post(f"/chatter/register?token={fresh}", json={"username": "too_late", "password": "secret-9"})
    assert r.status_code != 200, r.text
    used = next((i for i in OWNER_A.get("/admin/chatters/invites").json() if i.get("role_id") == "va"), None)
    assert used is None


def _register(token: str, username: str) -> int:
    r = _harness.make_client().post(f"/chatter/register?token={token}", json={"username": username, "password": "secret-3"})
    assert r.status_code == 200, r.text
    return next(e["id"] for e in _rows(OWNER_A).values() if e.get("username") == username)


def _link_without_employee_row(username: str) -> str:
    import asyncio
    import uuid
    from datetime import datetime

    from db.engine import get_session
    from db.models import Chatter, ChatterUser

    cid, now = uuid.uuid4().hex, datetime.utcnow()

    async def _seed():
        async with get_session() as s:
            s.add(Chatter(id=cid, username=username, password=fx.PASSWORD, display_name=username,
                          color="#bbbbbb", created_at=now, last_seen_at=now))
        async with get_session() as s:
            s.add(ChatterUser(chatter_id=cid, user_id=IDS["agency_a_owner"], created_at=now))
    asyncio.run(_seed())
    return cid


def case_every_way_in_without_a_role_lands_on_the_built_in_chatter():
    r = OWNER_A.post(f"{LIST}/login", json={"username": "no_role_made", "password": "secret-1"})
    assert r.status_code == 200, r.text
    assert _assignments(OWNER_A)[str(r.json()["employee_id"])] == "chatter"
    token = OWNER_A.post("/admin/chatters/invite").json()["token"]
    bare = _register(token, "no_role_bare")
    assert _assignments(OWNER_A)[str(bare)] == "chatter"
    config = OWNER_A.get("/admin/settings/roles").json()["config"]
    temp = {"id": "role-temp", "name": "Temp", "description": "", "permissions": {"/": True}, "scope": "self"}
    assert OWNER_A.put("/admin/settings/roles", json={**config, "roles": [*config["roles"], temp]}).status_code == 200
    token = OWNER_A.post("/admin/chatters/invite", json={"role_id": "role-temp"}).json()["token"]
    assert OWNER_A.put("/admin/settings/roles", json=config).status_code == 200
    gone = _register(token, "no_role_gone")
    assert _assignments(OWNER_A)[str(gone)] == "chatter"
    r = OWNER_B.post("/admin/chatters/link", json={"username": "no_role_made"})
    assert r.status_code == 200, r.text
    assert _assignments(OWNER_B)[str(r.json()["employee_id"])] == "chatter"
    cid = _link_without_employee_row("no_role_lazy")
    assert fx.login_chatter("no_role_lazy").get("/admin/settings/applied").status_code == 200
    lazy = next(e["id"] for e in _rows(OWNER_A).values() if e.get("chatter_id") == cid)
    assert _assignments(OWNER_A)[str(lazy)] == "chatter"
    owner_row = next(e["id"] for e in _rows(OWNER_A).values() if e["kind"] == "owner")
    assert str(owner_row) not in _assignments(OWNER_A)


def case_a_roles_save_that_drops_a_login_gives_it_chatter():
    config = OWNER_A.get("/admin/settings/roles").json()["config"]
    eid = next(e["id"] for e in _rows(OWNER_A).values() if e.get("username") == "no_role_made")
    assert OWNER_A.put(f"{LIST}/{eid}/setup", json={"role_id": "manager"}).status_code == 200
    dropped = {k: v for k, v in _assignments(OWNER_A).items() if k != str(eid)}
    r = OWNER_A.put("/admin/settings/roles", json={**config, "assignments": dropped})
    assert r.status_code == 200, r.text
    assert r.json()["config"]["assignments"][str(eid)] == "chatter"
    assert _assignments(OWNER_A)[str(eid)] == "chatter"


_harness.run()
