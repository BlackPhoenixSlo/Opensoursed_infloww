#!/usr/bin/env python3
"""The Dashboard's reads on the Relay (docs/spec/infloww-parity-round-2/phase-01-dashboard.md, Testing
Decisions, seam 2; ticket 24, stories 7, 10, 23, 25, 26 and 34; ticket 25 adds the Net read; ticket 26 adds
Employee sales, stories 16, 17, 24 and 33).

The KPI header's Total earnings and channel tiles read `GET /admin/stats/revenue?from&to&group_by=kind` with no
`account_id`, so `clamp_account_filter` bounds it to the session's own Creators; in Net mode (the capture's
default) the header adds `include_net=true`. Each case calls the exact query string the header sends
(`URLSearchParams({from, to, group_by: "kind"})`, then `include_net=true` in Net, so `:` travels as `%3A`), with
the `from`/`to` instants `periodWindow` (app/lib/dateRange.ts) produces for the fixture zone, as its table cases in
app/app/page.render.test.tsx pin them. Agency A's report time zone is Pacific/Honolulu (UTC-10:00, west of UTC,
no daylight saving), "now" is Wednesday 2026-10-14 02:00 there, and the sales sit one minute either side of that
day's midnight (10:00Z).

Employee sales reads `GET /admin/stats/per-employee?from&to` (`URLSearchParams({from, to})`), with no
`account_id`, so the Relay's account clamp and the role's Data scope bound it. The page map grants that read to the
Dashboard as well as to Employee reports, so a chatter whose role grants only the Dashboard loads the whole header.

The seam is the Relay over HTTP with real session cookies from the shared two-Agency fixture, over transactions
seeded straight into the temp DB. Every expected row is written out by hand from the seed.

Run: ./venv/bin/python service/tests/test_dashboard_reads.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime  # noqa: E402
from urllib.parse import urlencode  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import employees  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Message, Transaction  # noqa: E402

IDS = fx.seed_two_agencies()


def _mirror(chatter: str, owner: str) -> int:
    emp = asyncio.run(employees.get_or_create_mirror_employee(
        IDS[chatter], IDS[owner], display_name=f"Fixture {chatter}", color="#bbbbbb"))
    assert emp is not None
    return emp


EMP_A = _mirror("chatter_a", "agency_a_owner")
EMP_B = _mirror("chatter_b", "agency_b_owner")
# Role enforcement off in Agency A until a role case turns it on (`_roles`).
fx.store_blob(IDS["agency_a_owner"], "roles", {"enforce": False})

OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
CHATTER_A = fx.login_chatter("chatter_a")
ANON = _harness.make_client()

# periodWindow("yesterday" | "today", "Pacific/Honolulu", _) at 2026-10-14T12:00:00Z.
YESTERDAY = ("2026-10-13T10:00:00.000Z", "2026-10-14T09:59:59.999Z")
TODAY = ("2026-10-14T10:00:00.000Z", "2026-10-15T09:59:59.999Z")
# periodWindow("week", "Pacific/Honolulu", "sunday") at the same instant: Sunday Oct 11 to Saturday Oct 17.
WEEK = ("2026-10-11T10:00:00.000Z", "2026-10-18T09:59:59.999Z")


def _header_query(window: tuple[str, str], net: bool = False) -> str:
    """The revenue read exactly as DashboardHeader builds it, in Gross or in Net."""
    q = {"from": window[0], "to": window[1], "group_by": "kind"}
    if net:
        q["include_net"] = "true"
    return "/admin/stats/revenue?" + urlencode(q)


def _put(client, tab: str, blob: dict) -> None:
    r = client.put(f"/admin/settings/{tab}", json=blob)
    assert r.status_code == 200, f"PUT {tab}: {r.status_code} {r.text}"


def _seed_sales() -> None:
    # Agency A, Creator A: a PPV message at 23:59 on Tuesday Oct 13 in Honolulu, a tip at 00:01 on Wednesday.
    # Agency B, Creator B: a subscription inside each window. Each sale carries OnlyFans's net figure but A's
    # tip, which has none yet (ticket 25's Net read counts it in `net_missing_count`).
    sales = (
        (IDS["creator_a"], "ppv_message", 700, 560, "2026-10-14T09:59:00"),
        (IDS["creator_a"], "tip", 1250, None, "2026-10-14T10:01:00"),
        (IDS["creator_b"], "subscription", 9000, 7200, "2026-10-13T20:00:00"),
        (IDS["creator_b"], "subscription", 4000, 3200, "2026-10-14T20:00:00"),
    )

    async def _seed():
        async with get_session() as s:
            for aid, kind, cents, net, when in sales:
                s.add(Transaction(account_id=aid, fan_id=1, kind=kind, amount_cents=cents, net_cents=net,
                                  occurred_at=datetime.fromisoformat(when), status="cleared",
                                  currency="USD", source="ledger"))
    asyncio.run(_seed())


def _seed_employee_sales() -> None:
    # On Monday Oct 12, outside Yesterday and Today: each Agency's mirror Employee sends one message, and a PPV
    # message sale is linked to it (A $30.00, B $25.00). With the never-saved Sales Settings, Time tracking off,
    # Converters credit the linked sender; A's two unlinked sales above (the $7.00 PPV and the $12.50 tip, whose
    # fan has no message) are Unattributed, and B's subscriptions stay out (the Subscriptions opt-in is off).
    when = datetime.fromisoformat("2026-10-12T20:00:00")

    async def _seed():
        async with get_session() as s:
            for aid, fan, mid, emp, cents in ((IDS["creator_a"], 2, 9201, EMP_A, 3000),
                                              (IDS["creator_b"], 3, 9202, EMP_B, 2500)):
                s.add(Message(account_id=aid, fan_id=fan, message_id=mid, direction="out", body="x",
                              sent_by_employee_id=emp, created_at=when, ingested_at=when))
                s.add(Transaction(account_id=aid, fan_id=fan, kind="ppv_message", amount_cents=cents,
                                  message_id=mid, occurred_at=when, status="cleared", currency="USD",
                                  source="ledger"))
    asyncio.run(_seed())


_put(OWNER_A, "preferences", {"report_tz": "Pacific/Honolulu", "week_start": "sunday"})
_seed_sales()
_seed_employee_sales()


def _rows(client, window: tuple[str, str], net: bool = False) -> list[dict]:
    r = client.get(_header_query(window, net))
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    return r.json()["rows"]


def _row(kind: str, cents: int) -> dict:
    return {"day": None, "kind": kind, "total_cents": cents, "count": 1}


def _net_row(kind: str, cents: int, net: int, missing: int) -> dict:
    # The seeded sales carry no fee or VAT, so both sum to 0.
    return {**_row(kind, cents), "net_cents": net, "net_missing_count": missing, "fee_cents": 0, "vat_cents": 0}


def case_the_query_is_the_one_the_header_sends():
    assert _header_query(TODAY) == (
        "/admin/stats/revenue?from=2026-10-14T10%3A00%3A00.000Z&to=2026-10-15T09%3A59%3A59.999Z&group_by=kind")


def case_the_net_query_is_the_one_the_header_sends():
    # The string app/app/page.render.test.tsx pins for a seeded ?window=yesterday in Net, the default.
    assert _header_query(YESTERDAY, net=True) == (
        "/admin/stats/revenue?from=2026-10-13T10%3A00%3A00.000Z&to=2026-10-14T09%3A59%3A59.999Z"
        "&group_by=kind&include_net=true")


def case_agency_a_owner_sees_only_agency_a_net_figures():
    assert _rows(OWNER_A, TODAY, net=True) == [_net_row("tip", 1250, 0, 1)]
    assert _rows(OWNER_A, YESTERDAY, net=True) == [_net_row("ppv_message", 700, 560, 0)]


def case_agency_b_owner_sees_none_of_agency_a_net_figures():
    assert _rows(OWNER_B, TODAY, net=True) == [_net_row("subscription", 4000, 3200, 0)]
    assert _rows(OWNER_B, YESTERDAY, net=True) == [_net_row("subscription", 9000, 7200, 0)]


def case_agency_a_owner_sees_only_agency_a_sales():
    assert _rows(OWNER_A, TODAY) == [_row("tip", 1250)]
    assert _rows(OWNER_A, YESTERDAY) == [_row("ppv_message", 700)]


def case_agency_b_owner_sees_none_of_agency_a():
    assert _rows(OWNER_B, TODAY) == [_row("subscription", 4000)]
    assert _rows(OWNER_B, YESTERDAY) == [_row("subscription", 9000)]


def case_chatter_linked_to_a_sees_only_a_creators():
    assert _rows(CHATTER_A, TODAY) == [_row("tip", 1250)]
    assert _rows(CHATTER_A, YESTERDAY) == [_row("ppv_message", 700)]


def case_signed_out_is_401():
    r = ANON.get(_header_query(TODAY))
    assert r.status_code == 401, f"{r.status_code} {r.text}"


def case_the_west_of_utc_midnight_splits_yesterday_and_today():
    # 09:59Z and 10:01Z share a UTC day; the Honolulu windows put them on either side of midnight.
    assert [r["kind"] for r in _rows(OWNER_A, YESTERDAY)] == ["ppv_message"]
    assert [r["kind"] for r in _rows(OWNER_A, TODAY)] == ["tip"]
    utc_day = ("2026-10-14T00:00:00.000Z", "2026-10-14T23:59:59.999Z")
    assert sorted(r["kind"] for r in _rows(OWNER_A, utc_day)) == ["ppv_message", "tip"]


# ── Employee sales (ticket 26) ──────────────────────────────────────────────

def _sales_query(window: tuple[str, str]) -> str:
    """The per-employee read exactly as DashboardHeader builds it."""
    return "/admin/stats/per-employee?" + urlencode({"from": window[0], "to": window[1]})


def _sales(client, window: tuple[str, str] = WEEK) -> list[tuple[int | None, str, int]]:
    r = client.get(_sales_query(window))
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    return [(e["employee_id"], e["display_name"], e["revenue_cents"]) for e in r.json()["employees"]]


A_SALES = [(EMP_A, "Fixture chatter_a", 3000), (None, "Unattributed", 1950)]


def case_the_employee_sales_query_is_the_one_the_header_sends():
    # The string app/app/page.render.test.tsx pins for a seeded ?window=yesterday.
    assert _sales_query(YESTERDAY) == (
        "/admin/stats/per-employee?from=2026-10-13T10%3A00%3A00.000Z&to=2026-10-14T09%3A59%3A59.999Z")


def case_agency_a_owner_sees_only_agency_a_employees_and_sales():
    assert _sales(OWNER_A) == A_SALES
    assert _sales(OWNER_A, YESTERDAY) == [(None, "Unattributed", 700)]
    assert _sales(OWNER_A, TODAY) == [(None, "Unattributed", 1250)]


def case_agency_b_owner_sees_none_of_agency_a_employees_or_sales():
    assert _sales(OWNER_B) == [(EMP_B, "Fixture chatter_b", 2500)]
    assert _sales(OWNER_B, TODAY) == []


def case_chatter_linked_to_a_sees_only_a_creators_employee_sales():
    assert _sales(CHATTER_A) == A_SALES


def case_employee_sales_signed_out_is_401():
    r = ANON.get(_sales_query(WEEK))
    assert r.status_code == 401, f"{r.status_code} {r.text}"


def _roles(pages: dict[str, bool] | None, scope: str = "self") -> None:
    """Agency A enforces one role on EMP_A granting `pages`; None turns enforcement off."""
    if pages is None:
        _put(OWNER_A, "roles", {"enforce": False})
        return
    _put(OWNER_A, "roles", {"enforce": True, "assignments": {str(EMP_A): "role-fixture"}, "roles": [
        {"id": "role-fixture", "name": "Fixture role", "description": "", "permissions": pages, "scope": scope}]})


def case_a_dashboard_only_chatter_loads_every_header_read_bounded_by_its_data_scope():
    try:
        _roles({"/": True})
        # The Applied settings (the report time zone and week start), then the header's three reads.
        for path in ("/admin/settings/applied", _header_query(WEEK), _header_query(WEEK, net=True),
                     _sales_query(WEEK)):
            r = CHATTER_A.get(path)
            assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
        # A "self" Data scope still shows only the chatter's own row, with no Unattributed bucket.
        assert _sales(CHATTER_A) == [(EMP_A, "Fixture chatter_a", 3000)]
        _roles({"/": True}, scope="all")
        assert _sales(CHATTER_A) == A_SALES
    finally:
        _roles(None)


def case_a_role_granting_neither_the_dashboard_nor_employee_reports_is_refused_employee_sales():
    try:
        _roles({"/": False, "/analytics/employee-reports": False, "/analytics/creator-reports": True})
        r = CHATTER_A.get(_sales_query(WEEK))
        assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow Dashboard"}, r.text
        _roles({"/analytics/employee-reports": True})
        assert CHATTER_A.get(_sales_query(WEEK)).status_code == 200
    finally:
        _roles(None)


_harness.run()
