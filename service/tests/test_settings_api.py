#!/usr/bin/env python3
"""Settings blobs: one JSON object per Agency and Blob tab, on the Relay.

`GET /admin/settings/{tab}` reads the signed-in owner's blob (`{}` when none is
stored) and `PUT /admin/settings/{tab}` replaces it whole (ADR-0007). Only the
six Blob tabs and `flags` are accepted. The check order is 401 (no User — a Chatter session
too) → 404 (not a Blob tab) → 413 (body over 64 KB) → 400 (not a JSON object,
or a value its tab's schema refuses, named by its dotted path). A saved blob is
stamped `version: 1`; unknown keys are kept. Consumers read a stored blob
through `applied_blob`, which drops each invalid stored field
(docs/spec/phase-04-apply-stored-settings.md).

Run: ./venv/bin/python service/tests/test_settings_api.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import delete as sa_delete, select  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Chatter, ChatterUser, User, UserSetting  # noqa: E402

import _agency_fixtures as fx  # noqa: E402


async def _seed_user(username: str, password: str = "secretpw") -> str:
    uid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username=username, password=password))
    return uid


async def _seed_chatter(username: str, owner_id: str,
                        password: str = "secretpw") -> str:
    cid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(Chatter(id=cid, username=username, password=password,
                      display_name=username, created_at=datetime.utcnow(),
                      last_seen_at=datetime.utcnow()))
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=cid, user_id=owner_id,
                          created_at=datetime.utcnow()))
    return cid


async def _rows(user_id: str) -> list[tuple[str, str]]:
    async with get_session() as s:
        res = await s.execute(
            select(UserSetting.tab, UserSetting.config_json)
            .where(UserSetting.user_id == user_id))
        return [tuple(r) for r in res.all()]


def _login(username: str):
    client = _harness.make_client()
    r = client.post("/auth/login",
                    json={"username": username, "password": "secretpw"})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return client


_U: dict[str, str] = {}


async def case_seed():
    _U["alpha"] = await _seed_user("alpha_one")
    _U["beta"] = await _seed_user("beta_two")
    _U["gamma"] = await _seed_user("gamma_three")
    _U["delta"] = await _seed_user("delta_four")
    await _seed_chatter("fixture_chatter", _U["alpha"])


def case_empty_get_returns_an_empty_config():
    r = _login("alpha_one").get("/admin/settings/account")
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.json() == {"tab": "account", "config": {}}, r.json()


def case_put_then_get_round_trips_the_whole_blob():
    client = _login("alpha_one")
    blob = {"name": "Alpha One", "nested": {"x": [1, 2]}, "unknown_key": True}
    r = client.put("/admin/settings/preferences", json=blob)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    stamped = {**blob, "version": 1}
    assert r.json() == {"tab": "preferences", "config": stamped}, r.json()
    got = client.get("/admin/settings/preferences")
    assert got.status_code == 200
    assert got.json() == {"tab": "preferences", "config": stamped}, got.json()

    # A second PUT replaces the blob whole: a key it leaves out is gone.
    r = client.put("/admin/settings/preferences", json={"name": "Alpha Two"})
    assert r.status_code == 200
    got = client.get("/admin/settings/preferences").json()
    assert got == {"tab": "preferences", "config": {"name": "Alpha Two", "version": 1}}, got


def case_every_blob_tab_is_accepted():
    client = _login("alpha_one")
    for tab in ("account", "preferences", "roles", "sales", "time-tracking",
                "messaging", "flags"):
        assert client.get(f"/admin/settings/{tab}").status_code == 200, tab


def case_unknown_tab_is_404_on_get_and_put():
    client = _login("alpha_one")
    for tab in ("billing", "security-org", "nope"):
        assert client.get(f"/admin/settings/{tab}").status_code == 404, tab
        r = client.put(f"/admin/settings/{tab}", json={"a": 1})
        assert r.status_code == 404, f"{tab}: {r.status_code}"
    assert all(t in {"account", "preferences", "roles", "sales",
                     "time-tracking", "messaging"}
               for t, _ in asyncio.run(_rows(_U["alpha"])))


def case_non_object_body_is_400():
    client = _login("beta_two")
    r = client.put("/admin/settings/account", json=[1, 2, 3])
    assert r.status_code == 400, f"list body: {r.status_code}"
    r = client.put("/admin/settings/account", content=b"not json",
                   headers={"content-type": "application/json"})
    assert r.status_code == 400, f"bad json: {r.status_code}"
    assert asyncio.run(_rows(_U["beta"])) == [], "a refused body was stored"


def case_body_over_64kb_is_413_and_nothing_is_stored():
    client = _login("beta_two")
    body = json.dumps({"pad": "x" * (65 * 1024)}).encode()
    assert len(body) > 65536
    r = client.put("/admin/settings/account", content=body,
                   headers={"content-type": "application/json"})
    assert r.status_code == 413, f"{r.status_code} {r.text[:200]}"
    assert asyncio.run(_rows(_U["beta"])) == [], "an oversized body was stored"


def case_unknown_tab_with_a_bad_body_is_404_before_400():
    client = _login("beta_two")
    r = client.put("/admin/settings/nope", json=[1, 2, 3])
    assert r.status_code == 404, f"{r.status_code} {r.text[:200]}"


def case_oversized_non_json_body_is_413_before_400():
    client = _login("beta_two")
    body = b"not json " * (8 * 1024)
    assert len(body) > 65536
    r = client.put("/admin/settings/account", content=body,
                   headers={"content-type": "application/json"})
    assert r.status_code == 413, f"{r.status_code} {r.text[:200]}"
    assert asyncio.run(_rows(_U["beta"])) == [], "an oversized body was stored"


def case_unreadable_stored_blob_reads_as_empty():
    async def _write():
        async with get_session() as s:
            for tab, raw in (("roles", "not json"), ("messaging", "[1]")):
                s.add(UserSetting(user_id=_U["alpha"], tab=tab,
                                  config_json=raw, updated_at=datetime.utcnow()))
    asyncio.run(_write())
    client = _login("alpha_one")
    for tab in ("roles", "messaging"):
        r = client.get(f"/admin/settings/{tab}")
        assert r.status_code == 200, f"{tab}: {r.status_code} {r.text[:200]}"
        assert r.json() == {"tab": tab, "config": {}}, r.json()


def case_no_session_is_401_on_get_and_put():
    client = _harness.make_client()
    assert client.get("/admin/settings/account").status_code == 401
    r = client.put("/admin/settings/account", json={"a": 1})
    assert r.status_code == 401, f"{r.status_code}"
    # 401 comes before 404: an anonymous caller learns nothing about the tabs.
    assert client.get("/admin/settings/nope").status_code == 401


def case_chatter_session_is_401():
    client = _harness.make_client()
    r = client.post("/chatter/login",
                    json={"username": "fixture_chatter", "password": "secretpw"})
    assert r.status_code == 200, f"chatter login failed: {r.status_code} {r.text}"
    assert client.get("/admin/settings/account").status_code == 401
    r = client.put("/admin/settings/account", json={"a": 1})
    assert r.status_code == 401, f"{r.status_code}"


def case_two_agencies_are_isolated():
    a = _login("alpha_one")
    b = _login("beta_two")
    # "roles" is the blob Batch edit roles writes (Phase 5 story 55): same one handler, same isolation.
    for tab in ("sales", "roles"):
        assert a.put(f"/admin/settings/{tab}", json={"who": "Alpha One"}).status_code == 200, tab
        assert b.put(f"/admin/settings/{tab}", json={"who": "Beta Two"}).status_code == 200, tab
        assert a.get(f"/admin/settings/{tab}").json()["config"] == {"who": "Alpha One", "version": 1}, tab
        assert b.get(f"/admin/settings/{tab}").json()["config"] == {"who": "Beta Two", "version": 1}, tab


def case_deleting_the_user_removes_its_rows():
    """CASCADE actually firing — `PRAGMA foreign_keys=ON` is wired at connect."""
    client = _login("gamma_three")
    assert client.put("/admin/settings/roles",
                      json={"who": "Gamma Three"}).status_code == 200
    assert len(asyncio.run(_rows(_U["gamma"]))) == 1

    async def _delete():
        async with get_session() as s:
            await s.execute(sa_delete(User).where(User.id == _U["gamma"]))
    asyncio.run(_delete())
    assert asyncio.run(_rows(_U["gamma"])) == [], "rows outlived their User"


# ── Validation and versioning (Phase 4 ticket 20) ───────────────────

def _role(rid: str, name: str, **over) -> dict:
    return {"id": rid, "name": name, "description": "", "permissions": {"/chats": True},
            "scope": "self", **over}


def _refused(client, tab: str, body: dict, path: str, label: str) -> None:
    r = client.put(f"/admin/settings/{tab}", json=body)
    assert r.status_code == 400, f"{label}: {r.status_code} {r.text[:300]}"
    detail = r.json()["detail"]
    assert detail.startswith(f"{path}: ") and len(detail) > len(path) + 2, f"{label}: {detail!r}"


def case_each_tab_refuses_a_bad_value_naming_its_dotted_path_and_stores_nothing():
    client = _login("delta_four")
    bad = [
        ("account", {"agency_name": "x" * 129}, "account.agency_name", "agency name over 128"),
        ("preferences", {"tz": "Mars/Olympus_Mons"}, "preferences.tz", "unknown zone"),
        ("preferences", {"tz": "Europe/Paris", "report_tz": "Nowhere/Town"}, "preferences.report_tz",
         "unknown report zone"),
        ("preferences", {"week_start": "friday"}, "preferences.week_start", "week start"),
        ("preferences", {"language": "fr"}, "preferences.language", "language"),
        ("time-tracking", {"enabled": True, "auto_clock_out_minutes": 0},
         "time-tracking.auto_clock_out_minutes", "minutes 0"),
        ("time-tracking", {"auto_clock_out_minutes": 1000}, "time-tracking.auto_clock_out_minutes",
         "minutes 1000 (Infloww's max is 999)"),
        ("time-tracking", {"auto_clock_out_minutes": 1441}, "time-tracking.auto_clock_out_minutes",
         "minutes 1441"),
        ("time-tracking", {"auto_clock_out_minutes": 30.5}, "time-tracking.auto_clock_out_minutes",
         "minutes not whole"),
        ("time-tracking", {"enabled": "true"}, "time-tracking.enabled", "enabled a string"),
        ("time-tracking", {"role_ids": "owner"}, "time-tracking.role_ids", "role ids not a list"),
        ("time-tracking", {"role_ids": ["owner", ""]}, "time-tracking.role_ids", "an empty role id"),
        ("time-tracking", {"role_ids": ["owner", 7]}, "time-tracking.role_ids", "a role id not a string"),
        ("time-tracking", {"role_ids": [f"role-{i}" for i in range(106)]}, "time-tracking.role_ids",
         "106 role ids"),
        ("shifts", {"presets": {"start": "09:00", "end": "17:00"}}, "shifts.presets",
         "presets not a list"),
        ("shifts", {"presets": [{"start": "9:00", "end": "17:00"}]}, "shifts.presets",
         "a preset start not HH:MM"),
        ("shifts", {"presets": [{"start": "09:00", "end": "24:00"}]}, "shifts.presets",
         "a preset end past 23:59"),
        ("shifts", {"presets": [{"start": "09:00", "end": "09:00"}]}, "shifts.presets",
         "a preset with no length"),
        ("shifts", {"presets": [{"start": "09:00"}]}, "shifts.presets",
         "a preset with no end"),
        ("shifts", {"presets": [{"start": "09:00", "end": "17:00", "name": "x"}]},
         "shifts.presets", "a preset with another key"),
        ("shifts", {"presets": [{"start": "09:00", "end": "17:00"}] * 51},
         "shifts.presets", "51 presets"),
        ("sales", {"attribution": {"messages": "lottery"}}, "sales.attribution.messages",
         "no such attribution option"),
        ("sales", {"attribution": {"posts_tips": "sender"}}, "sales.attribution.posts_tips",
         "sender is not a Posts and Tips option"),
        ("sales", {"multi_employee_shift": 1}, "sales.multi_employee_shift", "a number for a switch"),
        ("sales", {"attribution": "shift"}, "sales.attribution", "attribution not an object"),
        ("messaging", {"ai_translation": True, "prompt": "p" * 2001}, "messaging.prompt", "prompt over 2000"),
        ("roles", {"roles": [_role("role-a", "n" * 65)]}, "roles.roles.0.name", "role name over 64"),
        ("roles", {"roles": [_role("role-a", "Closer", description="d" * 257)]},
         "roles.roles.0.description", "description over 256"),
        ("roles", {"roles": [_role("role-a", "Closer", scope="team")]}, "roles.roles.0.scope", "scope"),
        ("roles", {"roles": [_role(f"role-{i}", f"Role {i}") for i in range(101)]}, "roles.roles",
         "101 roles"),
        ("roles", {"enforce": "yes"}, "roles.enforce", "enforce a string"),
        ("roles", {"roles": [_role("role-a", "Closer", disabled="yes")]}, "roles.roles.0.disabled",
         "disabled a string"),
        ("roles", {"roles": [_role("role-a", "Closer", permissions={"/messages-pro#unsend": "no"})]},
         "roles.roles.0.permissions", "a Function permission not true or false"),
        ("flags", {"fansly_manager": "on"}, "flags.fansly_manager", "a flag not a switch"),
    ]
    for tab, body, path, label in bad:
        _refused(client, tab, body, path, label)
    assert asyncio.run(_rows(_U["delta"])) == [], "a refused blob was stored"

    # The bounds themselves pass.
    ok = [
        ("account", {"agency_name": "x" * 128}),
        ("preferences", {"tz": "Europe/Paris", "report_tz": "America/New_York", "week_start": "sunday",
                         "language": "es"}),
        ("time-tracking", {"enabled": True, "auto_clock_out_minutes": 1, "clock_in_reminder": False}),
        ("time-tracking", {"enabled": True, "auto_clock_out_minutes": 999, "clock_in_reminder": True}),
        # Unknown ids are kept: the roles blob may hold them later.
        ("time-tracking", {"enabled": True, "role_ids": ["owner", "admin", "role-gone"]}),
        ("time-tracking", {"role_ids": []}),
        # A preset ending before it starts ends the next day.
        ("shifts", {"presets": [{"start": "00:00", "end": "23:59"}, {"start": "22:00", "end": "06:00"}]
                           * 25}),
        ("shifts", {"presets": []}),
        ("time-tracking", {"role_ids": ["owner", "admin", *(f"role-{i}" for i in range(100))]}),
        ("sales", {"exclude_welcome": True, "exclude_of_fee": False, "multi_employee_shift": True,
                   "attribution": {"messages": "sender", "posts_tips": "converters",
                                   "subscriptions_chatter_opt_in": True}}),
        ("messaging", {"ai_translation": False, "prompt": "p" * 2000}),
        ("flags", {"fansly_manager": True}),
        ("roles", {"enforce": False, "roles": [_role(f"role-{i}", f"Role {i}") for i in range(99)]
                   + [_role("role-x", "n" * 64, description="d" * 256, scope="all", disabled=True,
                            permissions={"/messages-pro": True, "/messages-pro#unsend": False})]}),
    ]
    for tab, body in ok:
        r = client.put(f"/admin/settings/{tab}", json=body)
        assert r.status_code == 200, f"{tab} at its bounds: {r.status_code} {r.text[:300]}"


def case_partial_blobs_save_unknown_keys_round_trip_and_version_is_stamped_1():
    client = _login("delta_four")
    body = {"week_start": "sunday", "from_a_newer_panel": {"nested": [1, "two"]}}
    r = client.put("/admin/settings/preferences", json=body)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    want = {**body, "version": 1}
    assert r.json() == {"tab": "preferences", "config": want}, r.json()
    assert client.get("/admin/settings/preferences").json()["config"] == want

    # Unknown keys inside a nested object are kept too.
    body = {"attribution": {"messages": "converters", "later_key": "kept"}}
    assert client.put("/admin/settings/sales", json=body).status_code == 200
    assert client.get("/admin/settings/sales").json()["config"] == {**body, "version": 1}

    # An explicit version 1 is accepted as is.
    r = client.put("/admin/settings/messaging", json={"version": 1, "ai_translation": True})
    assert r.status_code == 200 and r.json()["config"] == {"version": 1, "ai_translation": True}, r.text

    # Any other version is refused, and the stored blob is untouched.
    for version in (2, 0, "1", True, None):
        _refused(client, "messaging", {"version": version, "ai_translation": False},
                 "messaging.version", f"version {version!r}")
    assert client.get("/admin/settings/messaging").json()["config"] == {"version": 1, "ai_translation": True}


def case_role_assignments_must_name_a_held_role_and_ids_and_names_are_unique():
    client = _login("delta_four")
    roles = [_role("role-a", "Closer"), _role("role-b", "Opener")]

    _refused(client, "roles", {"roles": roles, "assignments": {"emp-1": "role-a", "emp-2": "role-gone"}},
             "roles.assignments.emp-2", "assignment to a missing role")
    _refused(client, "roles", {"assignments": {"emp-1": "role-a"}},
             "roles.assignments.emp-1", "assignment with no roles at all")
    _refused(client, "roles", {"roles": roles, "assignments": {"emp-1": 7}},
             "roles.assignments.emp-1", "assignment not a role id")
    _refused(client, "roles", {"roles": [*roles, _role("role-a", "Third")]},
             "roles.roles.2.id", "duplicate role id")
    _refused(client, "roles", {"roles": [*roles, _role("role-c", "  cLOSER ")]},
             "roles.roles.2.name", "case-insensitive duplicate name")

    # The built-in owner and admin always pass, with or without a roles list.
    body = {"assignments": {"emp-1": "owner", "emp-2": "admin"}}
    assert client.put("/admin/settings/roles", json=body).status_code == 200
    body = {"enforce": True, "roles": roles,
            "assignments": {"emp-1": "role-a", "emp-2": "role-b", "emp-3": "owner"}}
    r = client.put("/admin/settings/roles", json=body)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    assert client.get("/admin/settings/roles").json()["config"] == {**body, "version": 1}


def case_a_batch_edit_roles_save_keeps_every_other_key_and_an_invalid_one_is_refused():
    """Manage employees' "Batch edit roles" PUTs the whole roles blob with one
    role set for several Employee ids (docs/spec/phase-05-remaining-parity-
    gaps.md, story 9). The Relay's validation is the only gate: a save naming
    a role the blob does not hold is refused and the stored blob is kept."""
    asyncio.run(_seed_user("epsilon_five"))
    client = _login("epsilon_five")
    stored = {"enforce": True, "roles": [_role("role-a", "Closer"), _role("role-b", "Opener")],
              "assignments": {"7": "role-a"}, "panel_key": {"kept": True}}
    assert client.put("/admin/settings/roles", json=stored).status_code == 200

    batch = {**stored, "version": 1, "assignments": {"7": "role-b", "8": "role-b", "9": "role-b"}}
    r = client.put("/admin/settings/roles", json=batch)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    assert client.get("/admin/settings/roles").json()["config"] == batch

    _refused(client, "roles", {**batch, "assignments": {"7": "role-gone", "8": "role-gone"}},
             "roles.assignments.7", "batch to a role the blob does not hold")
    assert client.get("/admin/settings/roles").json()["config"] == batch, "a refused batch changed the blob"


def case_check_order_is_401_then_404_then_413_then_400():
    bad = {"auto_clock_out_minutes": 0}
    anon = _harness.make_client()
    assert anon.put("/admin/settings/time-tracking", json=bad).status_code == 401, "signed out"
    chatter = _harness.make_client()
    r = chatter.post("/chatter/login", json={"username": "fixture_chatter", "password": "secretpw"})
    assert r.status_code == 200, r.text
    assert chatter.get("/admin/settings/time-tracking").status_code == 401, "chatter GET"
    assert chatter.put("/admin/settings/time-tracking", json=bad).status_code == 401, "chatter PUT"

    owner = _login("delta_four")
    assert owner.put("/admin/settings/nope", json=bad).status_code == 404, "unknown tab"
    big = json.dumps({**bad, "pad": "x" * (65 * 1024)}).encode()
    r = owner.put("/admin/settings/time-tracking", content=big,
                  headers={"content-type": "application/json"})
    assert r.status_code == 413, f"oversize: {r.status_code}"
    _refused(owner, "time-tracking", bad, "time-tracking.auto_clock_out_minutes", "bad value")


def case_a_stored_invalid_field_is_served_unchanged_and_the_next_put_names_it():
    """A blob written straight into the store (as if saved before this Phase)
    with one invalid field: GET shows it unchanged, and the next PUT of that
    same blob answers 400 naming the field. That the field reads at its default
    with the rest intact is asserted at its consumers' HTTP routes
    (test_clock_api.py, test_shifts_api.py)."""
    stored = {
        "time-tracking": ({"enabled": True, "auto_clock_out_minutes": 0, "clock_in_reminder": True,
                           "extra": "kept"},
                          "time-tracking.auto_clock_out_minutes"),
        "sales": ({"multi_employee_shift": True, "attribution": {"messages": "lottery", "posts_tips": "shift"}},
                  "sales.attribution.messages"),
        "roles": ({"enforce": True, "roles": [_role("role-a", "Closer")],
                   "assignments": {"emp-1": "role-a", "emp-2": "role-gone"}},
                  "roles.assignments.emp-2"),
    }
    for tab, (blob, _) in stored.items():
        fx.store_blob(_U["beta"], tab, blob)

    client = _login("beta_two")
    for tab, (blob, path) in stored.items():
        got = client.get(f"/admin/settings/{tab}").json()["config"]
        assert got == blob, f"{tab}: GET changed the stored blob: {got}"
        _refused(client, tab, got, path, f"{tab} re-saved as stored")


_harness.run()
