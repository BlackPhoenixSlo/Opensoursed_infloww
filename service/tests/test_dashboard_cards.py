#!/usr/bin/env python3
"""The Dashboard's per-card permissions (roadmap W5 5.12).

  cards     a role's `/#card-<id>` key stored false hides that card (Applied settings' `denied_cards`) and
            refuses its Dashboard routes while no other card reading them is shown; another page granting a
            route still opens it. The built-in Chatter, unstored, hides the revenue cards; a missing key, an
            owner and enforcement off hide nothing. A card key is no Function permission.
  drift     app/lib/dashboardCards.ts `CARD_PERMISSIONS` is `permissions.CARD_KEYS` with its revenue flags; each
            card route is a Dashboard route the app serves.

No network.

Run: ./venv/bin/python service/tests/test_dashboard_cards.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import employees  # noqa: E402
import permissions  # noqa: E402
import server  # noqa: E402

IDS = fx.seed_two_agencies()
CARDS_TS = Path(__file__).resolve().parents[2] / "app" / "lib" / "dashboardCards.ts"


def _mirror(chatter: str) -> int:
    emp = asyncio.run(employees.get_or_create_mirror_employee(
        IDS[chatter], IDS["agency_a_owner"], display_name=chatter, color="#bbbbbb"))
    assert emp is not None
    return emp


EMP_A = _mirror("chatter_a")
OWNER_A = fx.login_owner("agency_a_owner")
CHATTER_A = fx.login_chatter("chatter_a")
Q = "?from=2026-03-03&to=2026-03-03"
REVENUE = f"/admin/stats/revenue{Q}&group_by=day"
PER_MODEL = f"/admin/stats/per-model{Q}"
PER_EMPLOYEE = f"/admin/stats/per-employee{Q}"
CARD_ROUTES = (REVENUE, PER_MODEL, PER_EMPLOYEE)
DENIED_DASHBOARD = {"detail": "Your role does not allow Dashboard"}

def _role(role_id: str, perms: dict[str, bool], scope: str = "self") -> dict:
    return {"id": role_id, "name": f"Fixture {role_id}", "description": "", "permissions": perms, "scope": scope}


def _assign(role: dict) -> None:
    r = OWNER_A.put("/admin/settings/roles", json={"enforce": True, "roles": [role],
                                                   "assignments": {str(EMP_A): role["id"]}})
    assert r.status_code == 200, r.text


def _built_in_chatter(enforce: bool = True) -> None:
    """chatter_a on the built-in Chatter as never stored (the defaults `permissions._role` gives)."""
    fx.store_blob(IDS["agency_a_owner"], "roles", {"enforce": enforce, "roles": [], "assignments": {
        str(EMP_A): "chatter"}})


def _reset() -> None:
    r = OWNER_A.put("/admin/settings/roles", json={"enforce": False})
    assert r.status_code == 200, r.text


def _status(client, path: str) -> int:
    return client.get(path).status_code


def _denied_cards(client) -> list[str]:
    return client.get("/admin/settings/applied").json()["permissions"]["denied_cards"]


# ── Per-card permissions ────────────────────────────────────────────────────

def case_the_built_in_chatter_is_refused_the_revenue_cards_routes():
    try:
        _built_in_chatter()
        # Per-model KPIs' OF fan counts and new-subscriber chart (an earnings series) close with it.
        for path in (*CARD_ROUTES, "/api/of/v2/subscriptions/count/all",
                     "/api/of/v2/subscriptions/subscribers/chart?by=new"):
            r = CHATTER_A.get(path)
            assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, f"{path}: {r.status_code} {r.text}"
        assert _denied_cards(CHATTER_A) == sorted(permissions.REVENUE_CARD_KEYS)
        # Enforcement off: every card, every route.
        _built_in_chatter(enforce=False)
        assert _denied_cards(CHATTER_A) == []
        assert _status(CHATTER_A, REVENUE) == 200
    finally:
        _reset()


def case_a_hidden_card_closes_its_route_and_another_page_granting_it_reopens_it():
    try:
        _assign(_role("role-dash", {"/": True, "/#card-earnings": False}))
        assert _denied_cards(CHATTER_A) == ["/#card-earnings"]
        r = CHATTER_A.get(REVENUE)
        assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, r.text
        # The other cards keep their reads.
        for path in (PER_MODEL, PER_EMPLOYEE):
            assert _status(CHATTER_A, path) == 200, path
        # Creator reports serves revenue too, so its grant opens it whatever the Dashboard hides.
        _assign(_role("role-dash", {"/": True, "/analytics/creator-reports": True, "/#card-earnings": False}))
        assert _status(CHATTER_A, REVENUE) == 200
    finally:
        _reset()


def case_per_model_closes_with_its_card():
    try:
        _assign(_role("role-dash", {"/": True, "/#card-earnings": False}))
        assert _status(CHATTER_A, PER_MODEL) == 200
        _assign(_role("role-dash", {"/": True, "/#card-per-model": False}))
        assert _status(CHATTER_A, PER_MODEL) == 403
        assert _status(CHATTER_A, "/api/of/v2/subscriptions/count/all") == 403
    finally:
        _reset()


def case_a_role_storing_no_card_key_hides_nothing_and_a_card_key_is_no_function_permission():
    try:
        _assign(_role("role-dash", {"/": True}))
        assert _denied_cards(CHATTER_A) == []
        for path in CARD_ROUTES:
            assert _status(CHATTER_A, path) == 200, path
        _assign(_role("role-dash", {"/": True, "/#card-employee-sales": False}))
        perms = CHATTER_A.get("/admin/settings/applied").json()["permissions"]
        assert perms["denied_cards"] == ["/#card-employee-sales"] and perms["denied_actions"] == [], perms
    finally:
        _reset()


def case_without_the_dashboard_every_card_route_is_refused():
    try:
        _assign(_role("role-pro", {"/messages-pro": True}))
        for path in CARD_ROUTES:
            assert _status(CHATTER_A, path) == 403, path
    finally:
        _reset()


def case_an_owner_hides_no_card():
    _built_in_chatter()
    try:
        assert _denied_cards(OWNER_A) == []
        for path in CARD_ROUTES:
            assert _status(OWNER_A, path) == 200, path
    finally:
        _reset()


# ── Drift ───────────────────────────────────────────────────────────────────

def case_the_frontend_card_list_is_the_relays():
    rows = re.findall(r'^\s*"(/#card-[^"]+)": \{ label: "([^"]+)", revenue: (true|false) \},', CARDS_TS.read_text(),
                      re.M)
    assert {k: label for k, label, _ in rows} == permissions.CARD_KEYS, rows
    assert len(rows) == len(permissions.CARD_KEYS)
    assert sorted(k for k, _, money in rows if money == "true") == sorted(permissions.REVENUE_CARD_KEYS)


def case_card_keys_are_no_action_and_their_routes_are_dashboard_routes_the_app_serves():
    assert not set(permissions.DASHBOARD_CARDS) & set(permissions.ACTIONS)
    assert not set(permissions.CARD_KEYS) & set(permissions.ACTION_KEYS)
    paths = {route.path for route in server.app.routes}
    for card, (_, routes, _) in permissions.DASHBOARD_CARDS.items():
        for route in routes:
            assert route in paths, f"{card}: {route} is no route"
            assert "/" in (permissions.route_pages(route, "GET") or ()), f"{card}: {route} is no Dashboard route"


_harness.run()
