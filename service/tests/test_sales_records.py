#!/usr/bin/env python3
"""Sales records on the Relay (docs/spec/phase-05-remaining-parity-gaps.md, item 3; ticket 33, stories 19-21,
25, 26, 29 and 30).

`GET /admin/stats/sales-records` lists one row per credited share of each sale Employee reports count (roadmap
S7: one crediting path, so each Employee's Earnings add up to its Employee reports revenue), each with its `rule`
(`manual`, `message`, `tip_lookback`, `shift` or `unassigned`) and "Assigned by" ("Auto" for rule-based credit,
"Manual" for an override), filtered by Creator, Employees, Sales types, Date and "Show unassigned sales",
paged by `before_id`, and with `format=csv` the whole filtered set streamed as CSV with the 50k cap, which
`X-Row-Count` carries as an upper bound (the /admin/paid-messages precedent).
Under Role enforcement a chatter's rows narrow to its Data scope; with it off the Employee reports scope holds.
Ticket 36 (stories 20, 38): `group_id` narrows to the Employees placed in that Employee group (another Agency's or a
missing group is 404), and "Self and subordinates" is the chatter's own Employee plus the Employees in the groups below
its own group, never its peers.
No session is 401 and another Agency's Creator id is 404.
Reassign (ticket 34, stories 22-24, 27, 28) goes through the existing `POST /admin/ingest/transactions/{id}/attribute`:
owner or Master only (a chatter 403, with or without Role enforcement), another Agency's sale 404, an Employee outside
the sale's Agency 400, and each write one `sales.reassign` action with the old and new Employee, which "Assigned by"
reads ("Owner" or "Master"); the audit middleware's generic row is still written and never read.

The seam is the Relay over HTTP with real session cookies from the shared two-Agency fixture, over messages,
transactions and fans seeded straight into the temp DB with fixed past timestamps; the view is the revision
this ticket adds (`*_attr_view_sales_records.py`), applied as test_sales_attribution_rules applies its
predecessor. The migration itself round-trips on a throwaway SQLite file. Every expected row is written out
by hand from the seed.

ASSUMPTION: a single foreign `?account_id=` is answered 403 by `_account_isolation_middleware` (server.py)
before the route runs, so the route's 404 "creator not found" is asserted for what gets past that gate (an
unknown id, and a repeated param whose foreign value the gate does not read); both are asserted, and no
foreign row ever appears; spec story 55 allows 403/404 across Agencies. Rung 1 (the gate is in the code)
and rung 3 (phase-03's S4S answers a foreign Creator 403). Overturned if the gate should defer to the route's 404 for this path.

Run: ./venv/bin/python service/tests/test_sales_records.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import csv  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import csv_export  # noqa: E402
import employees  # noqa: E402
from _clock_fixtures import IDS, employee as _employee, with_anonymous_admin  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Action, Base, Fan, Message, Transaction, UserAccount  # noqa: E402

_MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations" / "versions"
ROUTE = "/admin/stats/sales-records"
DAY = "2026-05-04"


def _load(pattern: str):
    found = sorted(_MIGRATIONS.glob(pattern))
    assert len(found) == 1, f"want one {pattern}, found {found}"
    spec = importlib.util.spec_from_file_location(found[0].stem, found[0])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIG = _load("*_attr_view_sales_records.py")
PREDECESSOR = _load("20260710_0200_attr_view_orphan_rows.py")


async def _apply_view() -> None:
    # init_db (create_all) builds no views: apply this ticket's revision.
    async with get_session() as s:
        await s.execute(text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
        await s.execute(text(MIG._NEW_VIEW_SQL))


asyncio.run(_apply_view())

OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
CHATTER_A = fx.login_chatter("chatter_a")
ANON = _harness.make_client()


def _at(hhmm: str, day: str = DAY) -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}:00")


def _creator(aid: str, owner: str = "agency_a_owner") -> str:
    """A Creator of `owner`'s Agency used by this file only."""
    async def _seed():
        async with get_session() as s:
            s.add(Account(id=aid, nickname=f"sr_creator_{aid[-2:]}", color="#aaaaaa"))
        async with get_session() as s:
            s.add(UserAccount(user_id=IDS[owner], account_id=aid))
    (account_registry.ACCOUNTS_DIR / aid).mkdir()
    asyncio.run(_seed())
    return aid


_next_id = iter(range(8_000_001, 8_100_000))


def _message(aid: str, fan: int, sender: int | None, at: datetime) -> int:
    mid = next(_next_id)

    async def _seed():
        async with get_session() as s:
            s.add(Message(account_id=aid, fan_id=fan, message_id=mid, direction="out", body="x",
                          sent_by_employee_id=sender, created_at=at, ingested_at=at))
    asyncio.run(_seed())
    return mid


def _sale(aid: str, kind: str, cents: int, at: datetime, fan: int | None = 1, message_id: int | None = None,
          manual: int | None = None, net: int | None = None, status: str = "cleared") -> int:
    async def _seed():
        async with get_session() as s:
            tx = Transaction(account_id=aid, fan_id=fan, kind=kind, message_id=message_id, amount_cents=cents,
                             occurred_at=at, status=status, currency="USD", source="ledger",
                             attributed_employee_id=manual, net_cents=net)
            s.add(tx)
            await s.flush()
            return tx.id
    return asyncio.run(_seed())


def _fan(aid: str, fan: int, display: str | None, username: str | None) -> None:
    async def _seed():
        async with get_session() as s:
            s.add(Fan(account_id=aid, fan_id=fan, of_display_name=display, of_username=username))
    asyncio.run(_seed())


def _get(client, query: str = "", status: int = 200):
    r = client.get(f"{ROUTE}?{query}")
    assert r.status_code == status, f"{query}: {r.status_code} {r.text}"
    return r


def _rows(client, query: str) -> list[dict]:
    return _get(client, query).json()["rows"]


def _ids(client, query: str) -> list[int]:
    return [row["tx_id"] for row in _rows(client, query)]


# ── The seed: Creator C1 of Agency A, one sale per shape the view carries ─────────────────────────────────

C1 = _creator("3000001")
C2 = _creator("3000002")
E1, E2, E3 = _employee("sr_emp_1"), _employee("sr_emp_2"), _employee("sr_emp_3")

_fan(C1, 11, "Fixture Fan Eleven", "fixture_fan_11")
_fan(C1, 13, None, "fixture_fan_13")
M1 = _message(C1, 11, E1, _at("09:00"))
M2 = _message(C1, 12, None, _at("09:30"))   # an outbound message no Employee sent
M3 = _message(C1, 16, E1, _at("09:45"))
_message(C1, 13, E2, _at("10:00", "2026-05-02"))  # E2 wrote to fan 13 two days before its tip

T_MSG = _sale(C1, "ppv_message", 1000, _at("10:00"), fan=11, message_id=M1, net=800)
T_NOSENDER = _sale(C1, "tip", 400, _at("10:05"), fan=12, message_id=M2)
T_LOOK = _sale(C1, "tip", 500, _at("10:10"), fan=13)
T_NOBODY = _sale(C1, "tip", 300, _at("10:15"), fan=14)
T_ORPHAN = _sale(C1, "ppv_message", 700, _at("10:20"), fan=15, message_id=7_999_999)
T_MANUAL = _sale(C1, "ppv_message", 200, _at("10:25"), fan=16, message_id=M3, manual=E3)
T_MANUAL_TIP = _sale(C1, "tip", 150, _at("10:30"), fan=13, manual=E3)
T_TIE = _sale(C1, "tip", 50, _at("10:30"), fan=19)  # same instant as T_MANUAL_TIP, a later id
T_PENDING = _sale(C1, "custom", 900, _at("10:35"), fan=17, manual=E1, status="pending")
# Not in the view, so never a Sales record: a subscription and a refunded sale.
_sale(C1, "subscription", 1200, _at("10:40"), fan=None)
_sale(C1, "ppv_message", 999, _at("10:45"), fan=20, message_id=_message(C1, 20, E1, _at("10:44")), status="refunded")
T_OTHER_DAY = _sale(C1, "ppv_post", 250, _at("09:00", "2026-05-05"), fan=18)
T_C2 = _sale(C2, "tip", 600, _at("11:00"), fan=31)
T_B = _sale(IDS["creator_b"], "tip", 700, _at("11:00"), fan=41)

C1_DAY = f"account_id={C1}&from={DAY}&to={DAY}"
# Newest first; a tie on the instant breaks by the higher transaction id.
ORDER = [T_PENDING, T_TIE, T_MANUAL_TIP, T_MANUAL, T_ORPHAN, T_NOBODY, T_LOOK, T_NOSENDER, T_MSG]


# ── Each Rule on the right sale ─────────────────────────────────────────────────────────────────────────────

def case_each_rule_and_assigned_by_lands_on_the_right_sale():
    got = {row["tx_id"]: (row["rule"], row["employee_id"], row["assigned_by"]) for row in _rows(OWNER_A, C1_DAY)}
    assert got == {
        T_MSG: ("message", E1, "Auto"),
        T_NOSENDER: ("unassigned", None, "Auto"),
        T_LOOK: ("tip_lookback", E2, "Auto"),
        T_NOBODY: ("unassigned", None, "Auto"),
        T_ORPHAN: ("unassigned", None, "Auto"),
        T_MANUAL: ("manual", E3, "Manual"),
        T_MANUAL_TIP: ("manual", E3, "Manual"),
        T_TIE: ("unassigned", None, "Auto"),
        T_PENDING: ("manual", E1, "Manual"),
    }, got


def case_a_row_carries_every_column_of_the_read_contract():
    rows = {row["tx_id"]: row for row in _rows(OWNER_A, C1_DAY)}
    assert rows[T_MSG] == {
        "tx_id": T_MSG, "occurred_at": "2026-05-04T10:00:00Z", "employee_id": E1, "employee_name": "sr_emp_1",
        "account_id": C1, "fan_id": 11, "fan_label": "Fixture Fan Eleven", "earnings_cents": 1000,
        "gross_cents": 1000, "net_cents": 800, "kind": "ppv_message", "rule": "message", "assigned_by": "Auto",
        "status": "cleared",
    }, rows[T_MSG]
    assert rows[T_LOOK]["fan_label"] == "@fixture_fan_13", rows[T_LOOK]
    assert rows[T_NOBODY]["fan_label"] is None and rows[T_NOBODY]["fan_id"] == 14, rows[T_NOBODY]
    assert rows[T_NOBODY]["employee_name"] is None, rows[T_NOBODY]
    assert (rows[T_PENDING]["status"], rows[T_PENDING]["net_cents"]) == ("pending", None), rows[T_PENDING]


def case_each_sale_is_credited_as_employee_reports_credit_it_under_any_sales_settings():
    """Roadmap S7: Sales records and Employee reports credit each sale through one path
    (`sales_attribution.credit`), so under every Sales Settings each Employee's Earnings on a Creator add up to
    its Employee reports revenue there (the Unattributed bucket too), and Earnings follows the fee toggle."""
    def _put(blob):
        # Backdated to the start (Sales Settings are versioned, roadmap W6 6.4), so it credits the fixture sales.
        r = OWNER_A.put("/admin/settings/sales", json=blob, params={"effective_from": "1970-01-01T00:00:00Z"})
        assert r.status_code == 200, r.text

    def _reports() -> dict:
        body = OWNER_A.get(f"/admin/stats/per-employee?from={DAY}&to={DAY}&by_account=true").json()
        return {e["employee_id"]: sub["revenue_cents"] for e in body["employees"] for sub in e["per_account"]
                if sub["account_id"] == C1 and sub["revenue_cents"]}

    def _records() -> dict:
        out: dict = {}
        for row in _rows(OWNER_A, f"{C1_DAY}&limit=500"):
            out[row["employee_id"]] = out.get(row["employee_id"], 0) + row["earnings_cents"]
        return out

    settings = (
        {},
        {"exclude_welcome": True, "exclude_of_fee": True,
         "attribution": {"messages": "sender", "posts_tips": "shift", "subscriptions_chatter_opt_in": False}},
        {"exclude_of_fee": True,
         "attribution": {"messages": "converters", "posts_tips": "converters", "subscriptions_chatter_opt_in": True}},
    )
    try:
        for blob in settings:
            _put(blob)
            assert _records() == _reports(), (blob, _records(), _reports())
        rows = {row["tx_id"]: row for row in _rows(OWNER_A, C1_DAY)}
        assert (rows[T_MSG]["earnings_cents"], rows[T_MSG]["gross_cents"]) == (800, 1000), rows[T_MSG]
        assert (rows[T_LOOK]["earnings_cents"], rows[T_LOOK]["gross_cents"]) == (400, 500), rows[T_LOOK]
        assert (rows[T_LOOK]["employee_id"], rows[T_LOOK]["rule"]) == (E2, "tip_lookback"), rows[T_LOOK]
        # With the opt-in on, the subscription Employee reports count is listed too.
        assert any(r["kind"] == "subscription" for r in _rows(OWNER_A, f"{C1_DAY}&limit=500"))
    finally:
        _put({})


def case_subscriptions_refunds_and_other_days_are_not_listed():
    assert _ids(OWNER_A, C1_DAY) == ORDER


# ── Filters ─────────────────────────────────────────────────────────────────────────────────────────────────

def case_every_filter_narrows_the_rows():
    def ids(extra: str) -> set[int]:
        return set(_ids(OWNER_A, f"{C1_DAY}&{extra}"))
    assert ids("kind=tip") == {T_NOSENDER, T_LOOK, T_NOBODY, T_MANUAL_TIP, T_TIE}
    assert ids("kind=tip&kind=custom") == {T_NOSENDER, T_LOOK, T_NOBODY, T_MANUAL_TIP, T_TIE, T_PENDING}
    assert ids(f"employee_id={E3}") == {T_MANUAL, T_MANUAL_TIP}
    assert ids(f"employee_id={E1}&employee_id={E2}") == {T_MSG, T_PENDING, T_LOOK}
    assert ids(f"employee_id={E1}&kind=custom") == {T_PENDING}
    assert set(_ids(OWNER_A, f"account_id={C1}&from=2026-05-05&to=2026-05-05")) == {T_OTHER_DAY}
    assert set(_ids(OWNER_A, f"account_id={C1}&from=2026-05-04&to=2026-05-05")) == set(ORDER) | {T_OTHER_DAY}
    assert set(_ids(OWNER_A, f"account_id={C2}&from={DAY}&to={DAY}")) == {T_C2}
    both = set(_ids(OWNER_A, f"account_id={C1}&account_id={C2}&from={DAY}&to={DAY}"))
    assert both == set(ORDER) | {T_C2}, both
    every = set(_ids(OWNER_A, f"from={DAY}&to={DAY}&limit=500"))
    assert every >= set(ORDER) | {T_C2} and T_B not in every, every


def case_show_unassigned_sales_lists_only_uncredited_sales():
    assert _ids(OWNER_A, f"{C1_DAY}&assigned=unassigned") == [T_TIE, T_ORPHAN, T_NOBODY, T_NOSENDER]


# ── Paging and CSV ──────────────────────────────────────────────────────────────────────────────────────────

def case_pages_by_before_id_newest_first_across_a_tie():
    seen, before, pages = [], None, 0
    while True:
        query = f"{C1_DAY}&limit=2" + (f"&before_id={before}" if before else "")
        body = _get(OWNER_A, query).json()
        pages += 1
        assert len(body["rows"]) <= 2, body
        seen += [row["tx_id"] for row in body["rows"]]
        before = body["next_before_id"]
        if before is None:
            break
        assert before == seen[-1], (before, seen)
    assert seen == ORDER and pages == 5, (seen, pages)
    assert _get(OWNER_A, C1_DAY).json()["next_before_id"] is None


def case_a_before_id_outside_the_requested_creators_gives_an_empty_page():
    # Another Agency's sale, a sale of a Creator not requested, and an unknown id are no cursor at all, so the
    # page never reveals when that sale happened.
    for cursor in (T_B, T_C2, 99_999_999):
        body = _get(OWNER_A, f"{C1_DAY}&before_id={cursor}").json()
        assert body == {"rows": [], "next_before_id": None}, (cursor, body)


HEADER = ["tx_id", "occurred_at", "employee_id", "employee_name", "account_id", "fan_id", "fan_label",
          "earnings_cents", "gross_cents", "net_cents", "kind", "rule", "assigned_by", "status"]


def _csv(query: str) -> tuple[list[list[str]], str]:
    r = _get(OWNER_A, f"{query}&format=csv")
    assert r.headers["content-type"].startswith("text/csv"), r.headers
    assert "attachment" in r.headers.get("content-disposition", ""), r.headers
    return list(csv.reader(io.StringIO(r.text))), r.headers["x-row-count"]


def case_csv_exports_the_whole_filtered_set_with_its_header_and_row_count():
    lines, count = _csv(f"{C1_DAY}&limit=2")  # limit and paging do not apply to the export
    assert lines[0] == HEADER, lines[0]
    assert [int(line[0]) for line in lines[1:]] == ORDER, lines
    # X-Row-Count is the cap, an upper bound sent before the streamed body (the /admin/paid-messages
    # precedent, messages.py), not the exact count: the file itself holds 9 rows.
    assert count == "50000", count
    assert lines[-1] == [str(T_MSG), "2026-05-04T10:00:00Z", str(E1), "sr_emp_1", C1, "11", "Fixture Fan Eleven",
                         "1000", "1000", "800", "ppv_message", "message", "Auto", "cleared"], lines[-1]
    lines, count = _csv(f"{C1_DAY}&assigned=unassigned")
    assert [int(line[0]) for line in lines[1:]] == [T_TIE, T_ORPHAN, T_NOBODY, T_NOSENDER] and count == "50000"


def case_csv_stops_at_the_row_cap_with_a_truncated_line():
    cap = csv_export.CSV_MAX_ROWS  # one cap for both server-side CSV exports
    assert cap == 50_000, cap
    csv_export.CSV_MAX_ROWS = 2
    try:
        lines, count = _csv(C1_DAY)
    finally:
        csv_export.CSV_MAX_ROWS = cap
    assert count == "2", count
    assert [int(line[0]) for line in lines[1:3]] == ORDER[:2], lines
    assert len(lines) == 4 and lines[3][0].startswith("# TRUNCATED"), lines


# ── Data scope under Role enforcement ───────────────────────────────────────────────────────────────────────

EMP_A = asyncio.run(employees.get_or_create_mirror_employee(
    IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color="#bbbbbb"))
E_OTHER = _employee("sr_emp_other")
CA = IDS["creator_a"]
T_OWN = _sale(CA, "ppv_message", 600, _at("12:00"), fan=21, message_id=_message(CA, 21, EMP_A, _at("11:00")))
T_PEER = _sale(CA, "ppv_message", 400, _at("12:05"), fan=22, message_id=_message(CA, 22, E_OTHER, _at("11:05")))
T_LOOSE = _sale(CA, "tip", 250, _at("12:10"), fan=23)
CA_DAY = f"account_id={CA}&from={DAY}&to={DAY}"
CA_ALL = {T_OWN, T_PEER, T_LOOSE}


def _roles(enforce: bool, scope: str, pages: tuple[str, ...] = ("/analytics/sales-records",)) -> None:
    r = OWNER_A.put("/admin/settings/roles", json={
        "enforce": enforce,
        "roles": [{"id": "role-sr", "name": "Fixture sales", "description": "",
                   "permissions": {p: True for p in pages}, "scope": scope}],
        "assignments": {str(EMP_A): "role-sr"}})
    assert r.status_code == 200, r.text


def _reset_roles() -> None:
    assert OWNER_A.put("/admin/settings/roles", json={}).status_code == 200


def case_with_role_enforcement_off_a_chatter_keeps_the_employee_reports_scope():
    _roles(False, "self")
    try:
        assert set(_ids(CHATTER_A, CA_DAY)) == CA_ALL
        assert set(_ids(CHATTER_A, f"{CA_DAY}&assigned=unassigned")) == {T_LOOSE}
    finally:
        _reset_roles()


def case_with_role_enforcement_on_a_self_scope_chatter_sees_only_its_own_sales():
    try:
        _roles(True, "self")
        assert set(_ids(CHATTER_A, CA_DAY)) == {T_OWN}
        assert _ids(CHATTER_A, f"{CA_DAY}&assigned=unassigned") == []
        assert _ids(CHATTER_A, f"{CA_DAY}&employee_id={E_OTHER}") == []
        lines = list(csv.reader(io.StringIO(_get(CHATTER_A, f"{CA_DAY}&format=csv").text)))
        assert [int(line[0]) for line in lines[1:]] == [T_OWN], lines
        # The owner, never checked, still sees every row.
        assert set(_ids(OWNER_A, CA_DAY)) == CA_ALL
        _roles(True, "all")
        assert set(_ids(CHATTER_A, CA_DAY)) == CA_ALL
    finally:
        _reset_roles()


def case_with_role_enforcement_on_a_role_without_the_page_is_refused():
    _roles(True, "all", pages=("/analytics/employee-reports",))
    try:
        r = _get(CHATTER_A, CA_DAY, status=403)
        assert r.json() == {"detail": "Your role does not allow Sales records"}, r.text
    finally:
        _reset_roles()


# ── Employee groups: the group filter and "Self and subordinates" (ticket 36) ──────────────────────────────
# A tree of Agency A, on its own day so no row above moves:
#     Fixture SR Lead (EMP_A, E_PEER) ── Fixture SR Team (E_SUB) ── Fixture SR Deep (E_DEEP)
#     Fixture SR Other (E_ELSE)

G_DAY = "2026-05-06"
E_PEER, E_SUB, E_DEEP, E_ELSE = (_employee(f"sr_emp_{n}") for n in ("peer", "sub", "deep", "else"))


def _group(client, name: str, parent_id: int | None = None) -> int:
    r = client.post("/admin/employee-groups", json={"name": name, "parent_id": parent_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _members(group_id: int, employee_ids: list[int]) -> None:
    r = OWNER_A.put("/admin/employee-groups/members", json={"group_id": group_id, "employee_ids": employee_ids})
    assert r.status_code == 200, r.text


G_LEAD = _group(OWNER_A, "Fixture SR Lead")
G_TEAM = _group(OWNER_A, "Fixture SR Team", G_LEAD)
G_DEEP = _group(OWNER_A, "Fixture SR Deep", G_TEAM)
G_OTHER = _group(OWNER_A, "Fixture SR Other")
G_B = _group(OWNER_B, "Fixture SR B Team")
for _g, _ids_in in ((G_LEAD, [EMP_A, E_PEER]), (G_TEAM, [E_SUB]), (G_DEEP, [E_DEEP]), (G_OTHER, [E_ELSE])):
    _members(_g, _ids_in)


def _g_sale(fan: int, sender: int | None, hhmm: str) -> int:
    at = _at(hhmm, G_DAY)
    if sender is None:
        return _sale(CA, "tip", 100, at, fan=fan)
    return _sale(CA, "ppv_message", 100, at, fan=fan, message_id=_message(CA, fan, sender, _at("09:00", G_DAY)))


G_OWN, G_PEER, G_SUB, G_DEEP_SALE, G_ELSE, G_LOOSE = (
    _g_sale(31, EMP_A, "12:00"), _g_sale(32, E_PEER, "12:01"), _g_sale(33, E_SUB, "12:02"),
    _g_sale(34, E_DEEP, "12:03"), _g_sale(35, E_ELSE, "12:04"), _g_sale(36, None, "12:05"))
G_ALL = {G_OWN, G_PEER, G_SUB, G_DEEP_SALE, G_ELSE, G_LOOSE}
G_Q = f"account_id={CA}&from={G_DAY}&to={G_DAY}"


def case_the_group_filter_keeps_the_sales_of_the_employees_placed_in_that_group():
    assert set(_ids(OWNER_A, G_Q)) == G_ALL
    assert set(_ids(OWNER_A, f"{G_Q}&group_id={G_LEAD}")) == {G_OWN, G_PEER}
    assert set(_ids(OWNER_A, f"{G_Q}&group_id={G_TEAM}")) == {G_SUB}
    assert set(_ids(OWNER_A, f"{G_Q}&group_id={G_OTHER}")) == {G_ELSE}
    assert _ids(OWNER_A, f"{G_Q}&group_id={G_LEAD}&employee_id={E_PEER}") == [G_PEER]
    assert _ids(OWNER_A, f"{G_Q}&group_id={G_LEAD}&assigned=unassigned") == []
    lines = list(csv.reader(io.StringIO(_get(OWNER_A, f"{G_Q}&group_id={G_TEAM}&format=csv").text)))
    assert [int(line[0]) for line in lines[1:]] == [G_SUB], lines


def case_the_group_filter_answers_404_for_another_agencys_or_a_missing_group():
    for group in (G_B, 999_999):
        for query in (f"{G_Q}&group_id={group}", f"{G_Q}&group_id={group}&format=csv"):
            r = _get(OWNER_A, query, status=404)
            assert r.json() == {"detail": "group not found"}, r.text
    _get(OWNER_B, f"group_id={G_LEAD}", status=404)


def case_with_role_enforcement_on_self_and_subordinates_sees_its_own_and_the_groups_below_never_peers():
    try:
        _roles(True, "subordinates")
        assert set(_ids(CHATTER_A, G_Q)) == {G_OWN, G_SUB, G_DEEP_SALE}
        assert _ids(CHATTER_A, f"{G_Q}&employee_id={E_PEER}") == []
        assert _ids(CHATTER_A, f"{G_Q}&group_id={G_OTHER}") == []
        assert _ids(CHATTER_A, f"{G_Q}&group_id={G_DEEP}") == [G_DEEP_SALE]
        lines = list(csv.reader(io.StringIO(_get(CHATTER_A, f"{G_Q}&format=csv").text)))
        assert {int(line[0]) for line in lines[1:]} == {G_OWN, G_SUB, G_DEEP_SALE}, lines
        # The owner is never narrowed (the Master: test_role_enforcement.py's subordinates case).
        assert set(_ids(OWNER_A, G_Q)) == G_ALL
        _roles(True, "self")
        assert _ids(CHATTER_A, G_Q) == [G_OWN]
        _roles(True, "all")
        assert set(_ids(CHATTER_A, G_Q)) == G_ALL
    finally:
        _reset_roles()


# ── Sessions and Agencies ───────────────────────────────────────────────────────────────────────────────────

def case_an_unauthenticated_caller_gets_401_even_with_anonymous_admin():
    _get(ANON, C1_DAY, status=401)
    with_anonymous_admin(lambda: _get(ANON, C1_DAY, status=401))
    with_anonymous_admin(lambda: _get(ANON, f"{C1_DAY}&format=csv", status=401))


def case_another_agencys_creator_id_is_404_and_its_rows_never_appear():
    """A single foreign `account_id` is refused 403 by the account isolation middleware before the handler
    (`service/server.py`, `_account_isolation_middleware`); a foreign or unknown id the middleware lets
    through (it reads one `account_id` value) is the handler's 404."""
    b = IDS["creator_b"]
    _get(OWNER_A, f"account_id={b}", status=403)
    for query in (f"account_id={b}&account_id={C1}", "account_id=999999999", f"account_id={b}&account_id={C1}"
                  "&format=csv"):
        r = _get(OWNER_A, query, status=404)
        assert r.json() == {"detail": "creator not found"}, r.text
    assert T_B not in _ids(OWNER_A, f"from={DAY}&to={DAY}&limit=500")
    b_rows = set(_ids(OWNER_B, f"from={DAY}&to={DAY}&limit=500"))
    assert T_B in b_rows and not (b_rows & (set(ORDER) | CA_ALL | {T_C2})), b_rows


# ── Reassign ────────────────────────────────────────────────────────────────────────────────────────────────
# Ticket 34 (stories 22-24, 27, 28): the existing manual attribute route, now owner or Master only, inside the
# sale's Agency, writing one `sales.reassign` action that "Assigned by" reads. Its own Creator, so no row above moves.

ATTR = "/admin/ingest/transactions/{}/attribute"
C3 = _creator("3000003")
C3_DAY = f"account_id={C3}&from={DAY}&to={DAY}"
E_B = _employee("sr_emp_b", owner="agency_b_owner")
MASTER = fx.login_owner("agency_master")


def _attribute(client, tx: int, employee_id: int | None, status: int = 200):
    r = client.post(ATTR.format(tx), json={"employee_id": employee_id})
    assert r.status_code == status, f"{tx} -> {employee_id}: {r.status_code} {r.text}"
    return r


def _c3_row(tx: int) -> tuple:
    row = next(r for r in _rows(OWNER_A, C3_DAY) if r["tx_id"] == tx)
    return row["rule"], row["employee_id"], row["assigned_by"]


def _actions(tx: int) -> tuple[list[dict], int]:
    """This sale's `sales.reassign` actions (oldest first), and how many generic middleware rows its POSTs left."""
    async def _read():
        async with get_session() as s:
            rows = (await s.execute(select(Action).order_by(Action.id))).scalars().all()
        mine = [{"employee_id": a.employee_id, "account_id": a.account_id, "target_type": a.target_type,
                 "payload": json.loads(a.payload_json)}
                for a in rows if a.action == "sales.reassign" and a.target_id == str(tx)]
        generic = sum(1 for a in rows if a.action == f"POST {ATTR.format(tx)}")
        return mine, generic
    return asyncio.run(_read())


def _entry(actor: str, old: int | None, new: int | None, shown: int | None) -> dict:
    """`old`/`new` are the override column before and after; `shown` the Employee the row credited before."""
    return {"employee_id": None, "account_id": C3, "target_type": "transaction",
            "payload": {"actor": actor, "before": {"employee_id": old}, "after": {"employee_id": new},
                        "shown_before": {"employee_id": shown}}}


OWNER_ACTOR = f"owner:{IDS['agency_a_owner']}"
MASTER_ACTOR = f"master:{IDS['agency_master']}"


def case_reassign_and_clear_each_write_one_sales_reassign_entry_that_assigned_by_reads():
    t = _sale(C3, "ppv_message", 800, _at("13:05"), fan=51, message_id=_message(C3, 51, E1, _at("13:00")))
    assert _c3_row(t) == ("message", E1, "Auto")

    r = _attribute(OWNER_A, t, E2)
    # The route keeps its response.
    assert r.json() == {"id": t, "account_id": C3, "kind": "ppv_message", "amount_cents": 800,
                        "attributed_employee_id": E2}, r.text
    assert _c3_row(t) == ("manual", E2, "Owner")
    assert _actions(t) == ([_entry(OWNER_ACTOR, None, E2, E1)], 1), _actions(t)

    _attribute(OWNER_A, t, None)  # clear: the Rule credits the message's sender again
    assert _c3_row(t) == ("message", E1, "Auto")
    assert _actions(t) == ([_entry(OWNER_ACTOR, None, E2, E1), _entry(OWNER_ACTOR, E2, None, E2)], 2), _actions(t)

    _attribute(MASTER, t, E3)
    assert _c3_row(t) == ("manual", E3, "Master")
    _attribute(OWNER_A, t, E2)  # the latest entry names who assigned it
    assert _c3_row(t) == ("manual", E2, "Owner")
    mine, generic = _actions(t)
    assert mine[2:] == [_entry(MASTER_ACTOR, None, E3, E1), _entry(OWNER_ACTOR, E3, E2, E3)] and generic == 4, mine


def case_the_middlewares_generic_row_is_not_read_as_a_reassign():
    """An override with no `sales.reassign` entry (set before this ticket) is "Manual", though the audit
    middleware's generic row for its POST is there."""
    t = _sale(C3, "tip", 120, _at("13:10"), fan=52, manual=E1)

    async def _legacy_post():
        async with get_session() as s:
            s.add(Action(employee_id=None, account_id=None, action=f"POST {ATTR.format(t)}",
                         target_id="attribute", payload_json=json.dumps({"employee_id": E1})))
    asyncio.run(_legacy_post())
    assert _c3_row(t) == ("manual", E1, "Manual")
    assert _actions(t) == ([], 1)


def case_an_override_set_outside_reassign_after_a_clear_reads_manual():
    """The ingest backfill (attribution_backfill.attribute_orphans) sets an empty override with no audit entry.
    After a reassign and a clear, the latest entry no longer describes the override, so the row is "Manual",
    not the owner who cleared it."""
    t = _sale(C3, "tip", 170, _at("13:12"), fan=55)
    _attribute(OWNER_A, t, E2)
    assert _c3_row(t) == ("manual", E2, "Owner")
    _attribute(OWNER_A, t, None)
    assert _c3_row(t)[2] == "Auto"

    async def _backfill():  # the backfill's own write: an UPDATE of the override, no Action
        async with get_session() as s:
            await s.execute(sa.update(Transaction).where(Transaction.id == t).values(attributed_employee_id=E2))
    asyncio.run(_backfill())
    assert _c3_row(t) == ("manual", E2, "Manual")
    assert [e["payload"]["after"] for e in _actions(t)[0]] == [{"employee_id": E2}, {"employee_id": None}]


def case_another_agencys_sale_is_404_and_its_employee_400_and_nothing_changes():
    t = _sale(C3, "tip", 130, _at("13:15"), fan=53, manual=E1)
    t_b = _sale(IDS["creator_b"], "tip", 140, _at("13:15"), fan=42)
    for client, tx, emp in ((OWNER_B, t, E_B), (OWNER_B, t, None), (OWNER_A, t_b, E1), (OWNER_A, 99_999_999, E1)):
        r = _attribute(client, tx, emp, status=404)
        assert r.json() == {"detail": "sale not found"}, r.text
    for client in (OWNER_A, MASTER):
        r = _attribute(client, t, E_B, status=400)
        assert r.json() == {"detail": "employee not in this sale's agency"}, r.text
    _attribute(OWNER_A, t, 99_999_999, status=400)
    assert _c3_row(t) == ("manual", E1, "Manual")
    assert _actions(t) == ([], 0)
    assert _actions(t_b) == ([], 0)
    b_row = next(r for r in _rows(OWNER_B, f"account_id={IDS['creator_b']}&from={DAY}&to={DAY}") if r["tx_id"] == t_b)
    assert (b_row["rule"], b_row["employee_id"]) == ("unassigned", None), b_row


def case_a_chatter_is_refused_403_with_and_without_role_enforcement():
    t = _sale(C3, "tip", 160, _at("13:20"), fan=54)
    _attribute(CHATTER_A, t, EMP_A, status=403)
    _roles(True, "all", pages=("/analytics/sales-records", "/analytics/employee-reports"))
    try:
        assert set(_ids(CHATTER_A, C3_DAY)) >= {t}  # the role reaches the page, and still no Reassign
        _attribute(CHATTER_A, t, EMP_A, status=403)
        _attribute(CHATTER_A, t, None, status=403)
    finally:
        _reset_roles()
    _attribute(ANON, t, E1, status=401)
    with_anonymous_admin(lambda: _attribute(ANON, t, E1, status=401))
    assert _c3_row(t) == ("unassigned", None, "Auto")
    assert _actions(t) == ([], 0)


# ── The view revision ───────────────────────────────────────────────────────────────────────────────────────

def _view_columns(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [r[1] for r in conn.execute("pragma table_info(per_employee_revenue_with_attribution)")]
    finally:
        conn.close()


def case_the_view_revision_round_trips_on_a_throwaway_file():
    assert MIG.down_revision == "0068_s4s", MIG.down_revision
    workdir = Path(tempfile.mkdtemp(prefix="sales_records_migration_"))
    path = workdir / "mig.db"
    assert path != Path(_harness.DB_PATH)
    engine = sa.create_engine(f"sqlite:///{path}")
    old = ["sent_by_employee_id", "automation_kind", "account_id", "kind", "amount_cents", "occurred_at"]
    try:
        Base.metadata.create_all(engine)

        def _run(step) -> None:
            with engine.begin() as conn:
                with Operations.context(MigrationContext.configure(conn)):
                    step()

        _run(PREDECESSOR.upgrade)
        assert _view_columns(path) == old
        _run(MIG.upgrade)
        assert _view_columns(path) == old + ["tx_id", "rule"], _view_columns(path)
        _run(MIG.downgrade)
        assert _view_columns(path) == old, _view_columns(path)
        conn = sqlite3.connect(path)
        try:
            sql = conn.execute("select sql from sqlite_master where name='per_employee_revenue_with_attribution'"
                               ).fetchone()[0]
        finally:
            conn.close()
        assert sql.strip() == PREDECESSOR._NEW_VIEW_SQL.strip(), "downgrade did not restore the predecessor"
        _run(MIG.upgrade)
        assert _view_columns(path) == old + ["tx_id", "rule"], _view_columns(path)
    finally:
        engine.dispose()
        shutil.rmtree(workdir, ignore_errors=True)


_harness.run()
