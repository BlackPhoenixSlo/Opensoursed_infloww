#!/usr/bin/env python3
import _harness  # MUST be first: binds a throwaway temp DB (unset env falls back to PROD)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import datetime  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import employees  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Employee, Transaction, UserSetting  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

APPLIED = "/admin/settings/applied"

IDS = fx.seed_two_agencies()


def _mirror(chatter: str, owner: str) -> int:
    emp = asyncio.run(employees.get_or_create_mirror_employee(
        IDS[chatter], IDS[owner], display_name=chatter, color="#bbbbbb"))
    assert emp is not None
    return emp


def _mirror_count(chatter: str) -> int:
    async def _count():
        async with get_session() as s:
            return (await s.execute(select(func.count()).select_from(Employee)
                                    .where(Employee.chatter_id == IDS[chatter]))).scalar_one()
    return asyncio.run(_count())


EMP = {"chatter_a@a": _mirror("chatter_a", "agency_a_owner")}

OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
MASTER = fx.login_owner("agency_master")
CHATTER_A = fx.login_chatter("chatter_a")
CHATTER_B = fx.login_chatter("chatter_b")
CHATTER_AB = fx.login_chatter("chatter_ab")

PROMPT = "Fixture translator prompt, never shown to a chatter"

ALL_OPT_IN = ["/growth/auto-funnel", "/growth/auto-mass", "/growth/auto-post", "/growth/auto-reply",
              "/growth/auto-story", "/growth/gen-info"]

FLAGS_DEFAULT = {"fansly_manager": True, "leak_tracker": False}
FANSLY_OFF = {**FLAGS_DEFAULT, "fansly_manager": False}
NO_LAYOUT = {"creator_cols": None}

DEFAULTS = {
    "preferences": {"tz": None, "report_tz": None, "week_start": "monday", "hide_trial_popup": False},
    "messaging": {"ai_translation": True},
    "permissions": {"enforced": True, "pages": None, "scope": "all", "opt_in": ALL_OPT_IN, "denied_actions": [], "denied_cards": []},
    "flags": FLAGS_DEFAULT,
    "reports": NO_LAYOUT,
}
ROLES_OFF = {**DEFAULTS, "permissions": {**DEFAULTS["permissions"], "enforced": False}}
CHATTER_DEFAULTS = {**ROLES_OFF, "permissions": {**ROLES_OFF["permissions"], "opt_in": [], "denied_actions": [], "denied_cards": []}}
CHATTER_HIDDEN_CARDS = ["/#card-earnings", "/#card-employee-sales", "/#card-per-model"]


def _put(client, tab: str, blob: dict) -> None:
    r = client.put(f"/admin/settings/{tab}", json=blob)
    assert r.status_code == 200, f"PUT {tab}: {r.status_code} {r.text}"


def _applied(client, creator: str | None = None) -> dict:
    headers = {"X-Account-Id": IDS[creator]} if creator else {}
    r = client.get(APPLIED, headers=headers)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    return r.json()


def _agency_a_roles(**assignments: str) -> dict:
    return {
        "enforce": True,
        "roles": [{"id": "role-closer", "name": "Closer", "description": "Fixture role",
                   "permissions": {"/messages-pro": True, "/analytics/employee-reports": False},
                   "scope": "self"}],
        "assignments": assignments,
    }


_put(OWNER_A, "preferences", {"tz": "Europe/Ljubljana", "report_tz": "America/New_York",
                              "week_start": "sunday", "language": "es", "hide_trial_popup": True})
_put(OWNER_A, "messaging", {"ai_translation": False, "prompt": PROMPT})
AGENCY_A_ROLES = _agency_a_roles(**{str(EMP["chatter_a@a"]): "role-closer", "999999": "admin"})
_put(OWNER_A, "roles", AGENCY_A_ROLES)
_put(OWNER_B, "preferences", {"tz": "Asia/Tokyo"})
_put(OWNER_B, "messaging", {"ai_translation": True})
_put(OWNER_B, "roles", {"enforce": False})

AGENCY_A_PREFS = {"tz": "Europe/Ljubljana", "report_tz": "America/New_York", "week_start": "sunday",
                  "hide_trial_popup": True}
AGENCY_B_PREFS = {"tz": "Asia/Tokyo", "report_tz": None, "week_start": "monday", "hide_trial_popup": False}


def case_owner_reads_its_agency_and_is_never_role_checked():
    assert _applied(OWNER_A) == {
        "preferences": AGENCY_A_PREFS,
        "messaging": {"ai_translation": False},
        "permissions": {"enforced": True, "pages": None, "scope": "all", "opt_in": ALL_OPT_IN, "denied_actions": [], "denied_cards": []},
        "flags": FLAGS_DEFAULT,
        "reports": NO_LAYOUT,
    }


def case_owner_naming_its_own_creator_reads_the_same():
    assert _applied(OWNER_A, "creator_a") == _applied(OWNER_A)


def case_chatter_reads_its_agency_and_its_own_role():
    want = {
        "preferences": AGENCY_A_PREFS,
        "messaging": {"ai_translation": False},
        "permissions": {"enforced": True, "pages": ["/messages-pro"], "scope": "self", "opt_in": [], "denied_actions": [], "denied_cards": []},
        "flags": FLAGS_DEFAULT,
        "reports": NO_LAYOUT,
    }
    assert _applied(CHATTER_A) == want
    assert _applied(CHATTER_A, "creator_a") == want


def case_chatter_body_carries_no_roles_list_other_assignment_or_prompt():
    r = CHATTER_A.get(APPLIED)
    assert r.status_code == 200, r.text
    text = r.text
    for leak in ("Closer", "role-closer", "999999", "Fixture role", PROMPT, "assignments",
                 "roles", "prompt", "language", "analytics"):
        assert leak not in text, f"{leak!r} leaked into {text}"
    assert set(r.json()) == {"preferences", "messaging", "permissions", "flags", "reports"}


def case_never_saved_agency_reads_the_defaults_enforcement_on_and_roles_off_grants_every_page():
    assert _applied(MASTER) == DEFAULTS
    assert _applied(CHATTER_B) == {**CHATTER_DEFAULTS, "preferences": AGENCY_B_PREFS}


def case_master_reads_its_own_agency_even_naming_another_agencys_creator():
    assert _applied(MASTER, "creator_a") == DEFAULTS


def case_two_agency_chatter_with_no_creator_gets_no_zone_strictest_translation_and_any_page():
    assert _mirror_count("chatter_ab") == 0
    assert _applied(CHATTER_AB) == {
        "preferences": {"tz": None, "report_tz": None, "week_start": "monday", "hide_trial_popup": False},
        "messaging": {"ai_translation": False},
        "permissions": {"enforced": True, "pages": None, "scope": "self", "opt_in": [], "denied_actions": [],
                        "denied_cards": CHATTER_HIDDEN_CARDS},
        "flags": FLAGS_DEFAULT,
        "reports": NO_LAYOUT,
    }
    assert _mirror_count("chatter_ab") == 2


def case_two_agency_chatter_with_no_creator_gets_503_when_a_mirror_cannot_be_resolved():
    async def _db_down(chatter_id, owner_user_id, *, display_name, color):
        return None

    original = employees.get_or_create_mirror_employee
    employees.get_or_create_mirror_employee = _db_down
    try:
        r = CHATTER_AB.get(APPLIED)
    finally:
        employees.get_or_create_mirror_employee = original
    assert r.status_code == 503 and r.json() == {"detail": "mirror employee unavailable"}, \
        f"{r.status_code} {r.text}"


def case_two_agency_chatter_follows_the_creator_in_scope():
    assert _applied(CHATTER_AB, "creator_a") == {
        "preferences": AGENCY_A_PREFS,
        "messaging": {"ai_translation": False},
        "permissions": {"enforced": True, "pages": ["/", "/growth/get-to-know-fans", "/growth/scripts", "/messages-pro",
                                                    "/of-manager/messages", "/of-manager/notifications"],
                        "scope": "self", "opt_in": [],
                        "denied_actions": [], "denied_cards": CHATTER_HIDDEN_CARDS},
        "flags": FLAGS_DEFAULT,
        "reports": NO_LAYOUT,
    }
    assert _applied(CHATTER_AB, "creator_b") == {**CHATTER_DEFAULTS, "preferences": AGENCY_B_PREFS}


def case_two_agency_chatter_with_both_enforcing_gets_the_union_of_granted_pages():
    EMP["chatter_ab@a"] = _mirror("chatter_ab", "agency_a_owner")
    EMP["chatter_ab@b"] = _mirror("chatter_ab", "agency_b_owner")
    _put(OWNER_A, "roles", _agency_a_roles(**{str(EMP["chatter_a@a"]): "role-closer",
                                              str(EMP["chatter_ab@a"]): "role-closer"}))
    _put(OWNER_B, "roles", {
        "enforce": True,
        "roles": [{"id": "role-analyst", "name": "Analyst", "description": "",
                   "permissions": {"/analytics/employee-reports": True}, "scope": "all"}],
        "assignments": {str(EMP["chatter_ab@b"]): "role-analyst"},
    })
    _put(OWNER_A, "messaging", {"ai_translation": True, "prompt": PROMPT})
    try:
        assert _applied(CHATTER_AB) == {
            "preferences": {"tz": None, "report_tz": None, "week_start": "monday", "hide_trial_popup": False},
            "messaging": {"ai_translation": True},
            "permissions": {"enforced": True,
                            "pages": ["/analytics/employee-reports", "/messages-pro"],
                            "scope": "self", "opt_in": [], "denied_actions": [], "denied_cards": []},
            "flags": FLAGS_DEFAULT,
            "reports": NO_LAYOUT,
        }
        assert _applied(CHATTER_AB, "creator_b")["permissions"] == {
            "enforced": True, "pages": ["/analytics/employee-reports"], "scope": "all", "opt_in": [], "denied_actions": [], "denied_cards": []}
    finally:
        _put(OWNER_A, "roles", _agency_a_roles(**{str(EMP["chatter_a@a"]): "role-closer",
                                                  "999999": "admin"}))
        _put(OWNER_B, "roles", {"enforce": False})
        _put(OWNER_A, "messaging", {"ai_translation": False, "prompt": PROMPT})


def case_built_in_admin_role_grants_every_page_with_all_data():
    _put(OWNER_A, "roles", _agency_a_roles(**{str(EMP["chatter_a@a"]): "admin"}))
    try:
        assert _applied(CHATTER_A)["permissions"] == {"enforced": True, "pages": None, "scope": "all",
                                                      "opt_in": [], "denied_actions": [], "denied_cards": []}
    finally:
        _put(OWNER_A, "roles", _agency_a_roles(**{str(EMP["chatter_a@a"]): "role-closer",
                                                  "999999": "admin"}))


def case_enforcement_off_grants_every_page_whatever_the_role():
    roles = _agency_a_roles(**{str(EMP["chatter_a@a"]): "role-closer"})
    _put(OWNER_A, "roles", {**roles, "enforce": False})
    try:
        assert _applied(CHATTER_A)["permissions"] == {"enforced": False, "pages": None, "scope": "all",
                                                      "opt_in": [], "denied_actions": [], "denied_cards": []}
    finally:
        _put(OWNER_A, "roles", _agency_a_roles(**{str(EMP["chatter_a@a"]): "role-closer",
                                                  "999999": "admin"}))


def case_another_agencys_session_never_sees_this_agencys_values():
    body = _applied(OWNER_B)
    assert body == {**ROLES_OFF, "preferences": AGENCY_B_PREFS}, body
    assert "Ljubljana" not in json.dumps(body)
    r = CHATTER_B.get(APPLIED, headers={"X-Account-Id": IDS["creator_a"]})
    assert r.status_code == 403, f"{r.status_code} {r.text}"
    assert "Ljubljana" not in r.text


def case_a_stored_invalid_field_reads_as_its_default():
    fx.store_blob(IDS["agency_b_owner"], "preferences",
                  {"tz": "Mars/Olympus_Mons", "report_tz": "Asia/Tokyo", "week_start": "friday",
                   "hide_trial_popup": "yes"})
    fx.store_blob(IDS["agency_b_owner"], "messaging", {"ai_translation": "no"})
    fx.store_blob(IDS["agency_b_owner"], "roles", {"enforce": "yes"})
    try:
        assert _applied(OWNER_B) == {
            "preferences": {"tz": None, "report_tz": "Asia/Tokyo", "week_start": "monday", "hide_trial_popup": False},
            "messaging": {"ai_translation": True},
            "permissions": {"enforced": True, "pages": None, "scope": "all", "opt_in": ALL_OPT_IN, "denied_actions": [], "denied_cards": []},
            "flags": FLAGS_DEFAULT,
            "reports": NO_LAYOUT,
        }
    finally:
        _put(OWNER_B, "preferences", {"tz": "Asia/Tokyo"})
        _put(OWNER_B, "messaging", {"ai_translation": True})
        _put(OWNER_B, "roles", {"enforce": False})


def case_fansly_manager_is_on_unless_the_agency_stored_it_false():
    _put(OWNER_A, "flags", {"fansly_manager": False})
    try:
        assert _applied(OWNER_A)["flags"] == FANSLY_OFF
        assert _applied(CHATTER_A)["flags"] == FANSLY_OFF
        assert _applied(CHATTER_AB, "creator_a")["flags"] == FANSLY_OFF
        assert _applied(OWNER_B)["flags"] == FLAGS_DEFAULT
        assert _applied(CHATTER_AB, "creator_b")["flags"] == FLAGS_DEFAULT
        assert _applied(CHATTER_AB)["flags"] == FANSLY_OFF
        _put(OWNER_A, "flags", {"fansly_manager": True})
        assert _applied(CHATTER_AB)["flags"] == FLAGS_DEFAULT
        _put(OWNER_A, "flags", {})
        _put(OWNER_B, "flags", {"fansly_manager": False})
        assert _applied(CHATTER_AB)["flags"] == FANSLY_OFF
        assert _applied(CHATTER_AB, "creator_a")["flags"] == FLAGS_DEFAULT
    finally:
        _put(OWNER_A, "flags", {})
        _put(OWNER_B, "flags", {})


def case_a_stored_invalid_flag_reads_as_missing():
    fx.store_blob(IDS["agency_a_owner"], "flags", {"fansly_manager": "yes", "leak_tracker": "no"})
    try:
        assert _applied(OWNER_A)["flags"] == FLAGS_DEFAULT
    finally:
        _put(OWNER_A, "flags", {})


def case_owner_saves_the_creator_columns_and_every_session_reads_them():
    cols = ["ppvsSent", "totalEarnings", "totalSubscriptionsEarnings"]
    try:
        _put(OWNER_A, "reports", {"creator_cols": cols})
        assert _applied(OWNER_A)["reports"] == {"creator_cols": cols}
        assert _applied(CHATTER_A)["reports"] == {"creator_cols": cols}
        assert _applied(OWNER_B)["reports"] == NO_LAYOUT
        assert CHATTER_A.put("/admin/settings/reports", json={"creator_cols": []}).status_code == 401
        for bad in ("x", ["a", "a"], [""], [1], [{}], [["x"]]):
            r = OWNER_A.put("/admin/settings/reports", json={"creator_cols": bad})
            assert r.status_code == 400 and "reports.creator_cols" in r.text, r.text
        assert _applied(OWNER_A)["reports"] == {"creator_cols": cols}
    finally:
        _put(OWNER_A, "reports", {})


def case_signed_out_is_401():
    r = _harness.make_client().get(APPLIED)
    assert r.status_code == 401, f"{r.status_code} {r.text}"


# /applied is declared before /{tab}: an owner gets the read, never the 404 "unknown settings tab"
def case_applied_is_not_read_as_a_tab_name():
    r = OWNER_A.get(APPLIED)
    assert r.status_code == 200 and "tab" not in r.json(), r.text
    assert CHATTER_A.get("/admin/settings/preferences").status_code == 401


def _seed_report_sales() -> None:
    async def _seed():
        async with get_session() as s:
            for when, cents in (("2026-06-10T02:00:00", 200), ("2026-06-11T03:30:00", 1000),
                                ("2026-06-11T12:00:00", 500), ("2026-06-12T03:30:00", 300)):
                s.add(Transaction(account_id=IDS["creator_a"], kind="tip", amount_cents=cents,
                                  occurred_at=datetime.fromisoformat(when), status="cleared",
                                  currency="USD", source="ledger"))
    asyncio.run(_seed())


_seed_report_sales()

REPORT = "/admin/stats/revenue?from=2026-06-10&to=2026-06-11&group_by=day"
NEW_YORK_DAYS = [{"day": "2026-06-10", "kind": None, "total_cents": 1000, "count": 1},
                 {"day": "2026-06-11", "kind": None, "total_cents": 800, "count": 2}]
UTC_DAYS = [{"day": "2026-06-10", "kind": None, "total_cents": 200, "count": 1},
            {"day": "2026-06-11", "kind": None, "total_cents": 1500, "count": 2}]


def _report(client, account_id: str | None = None) -> list[dict]:
    url = REPORT + (f"&account_id={IDS[account_id]}" if account_id else "")
    r = client.get(url)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    return r.json()["rows"]


@contextmanager
def _roles_not_enforced():
    _put(OWNER_A, "roles", {**AGENCY_A_ROLES, "enforce": False})
    try:
        yield
    finally:
        _put(OWNER_A, "roles", AGENCY_A_ROLES)


def case_report_days_start_and_end_at_midnight_in_the_report_time_zone():
    assert _report(OWNER_A, "creator_a") == NEW_YORK_DAYS
    assert _report(OWNER_A) == NEW_YORK_DAYS
    with _roles_not_enforced():
        assert _report(CHATTER_A) == NEW_YORK_DAYS


def case_two_agency_chatter_follows_the_report_zone_of_the_creator_in_scope():
    with _roles_not_enforced():
        assert _report(CHATTER_AB, "creator_a") == NEW_YORK_DAYS


def case_two_agency_chatter_with_no_creator_keeps_utc_days():
    with _roles_not_enforced():
        assert _report(CHATTER_AB) == UTC_DAYS


def case_no_report_zone_keeps_utc_days():
    _put(OWNER_A, "preferences", {"tz": "Europe/Ljubljana", "week_start": "sunday"})
    try:
        assert _report(OWNER_A, "creator_a") == UTC_DAYS
    finally:
        _put(OWNER_A, "preferences", {"tz": "Europe/Ljubljana", "report_tz": "America/New_York",
                                      "week_start": "sunday", "language": "es", "hide_trial_popup": True})


def case_a_stored_invalid_report_zone_keeps_utc_days():
    fx.store_blob(IDS["agency_a_owner"], "preferences", {"report_tz": "Mars/Olympus_Mons"})
    try:
        assert _report(OWNER_A, "creator_a") == UTC_DAYS
    finally:
        _put(OWNER_A, "preferences", {"tz": "Europe/Ljubljana", "report_tz": "America/New_York",
                                      "week_start": "sunday", "language": "es", "hide_trial_popup": True})


def case_full_iso_bounds_are_unchanged_by_the_report_zone():
    r = OWNER_A.get("/admin/stats/revenue?from=2026-06-11T00:00:00Z&to=2026-06-11T23:59:59Z"
                    "&group_by=kind")
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [{"day": None, "kind": "tip", "total_cents": 1500, "count": 2}]



TRANSLATE = "/admin/translate"
TURNED_OFF = {"detail": "Turned off by your organization"}
_provider_calls: list[str] = []


@contextmanager
def _patched_provider():
    import translate_api

    async def _fake_fetch(client, sem, text: str, target: str, source: str = "auto"):
        _provider_calls.append(text)
        return {"text": f"EN:{text}", "lang": "es"}

    saved = translate_api._fetch_one
    translate_api._fetch_one = _fake_fetch
    _provider_calls.clear()
    try:
        yield
    finally:
        translate_api._fetch_one = saved


def _translate(client, text: str, creator: str | None = None):
    headers = {"X-Account-Id": IDS[creator]} if creator else {}
    with _patched_provider():
        return client.post(TRANSLATE, json={"texts": [text], "target": "en"}, headers=headers)


def _translated(r, text: str) -> None:
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.json() == {"results": [{"text": f"EN:{text}", "lang": "es"}]}, r.text


def _refused(r) -> None:
    assert (r.status_code, r.json()) == (403, TURNED_OFF), f"{r.status_code} {r.text}"
    assert _provider_calls == [], _provider_calls


def case_translate_refuses_a_chatter_while_its_agency_has_ai_translation_off():
    _refused(_translate(CHATTER_A, "gate hola uno"))
    _refused(_translate(CHATTER_A, "gate hola dos", "creator_a"))


def case_translate_never_refuses_an_owner():
    _translated(_translate(OWNER_A, "gate hola tres"), "gate hola tres")
    _translated(_translate(OWNER_A, "gate hola cuatro", "creator_a"), "gate hola cuatro")


def case_translate_allows_the_chatter_again_once_ai_translation_is_back_on():
    _put(OWNER_A, "messaging", {"ai_translation": True, "prompt": PROMPT})
    try:
        _translated(_translate(CHATTER_A, "gate hola cinco"), "gate hola cinco")
    finally:
        _put(OWNER_A, "messaging", {"ai_translation": False, "prompt": PROMPT})


def case_translate_allows_a_chatter_whose_agency_never_stored_messaging_or_the_key():
    async def _drop_messaging_blob():
        async with get_session() as s:
            row = await s.get(UserSetting, (IDS["agency_b_owner"], "messaging"))
            if row is not None:
                await s.delete(row)
    asyncio.run(_drop_messaging_blob())
    try:
        _translated(_translate(CHATTER_B, "gate hola seis"), "gate hola seis")
        fx.store_blob(IDS["agency_b_owner"], "messaging", {"prompt": PROMPT})
        _translated(_translate(CHATTER_B, "gate hola siete"), "gate hola siete")
    finally:
        _put(OWNER_B, "messaging", {"ai_translation": True})


def case_translate_follows_the_creator_in_scope_for_a_two_agency_chatter():
    with _roles_not_enforced():
        _refused(_translate(CHATTER_AB, "gate hola ocho", "creator_a"))
        _translated(_translate(CHATTER_AB, "gate hola nueve", "creator_b"), "gate hola nueve")
        _refused(_translate(CHATTER_AB, "gate hola diez"))


_harness.run()
