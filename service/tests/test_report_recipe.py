#!/usr/bin/env python3
"""Report recipe (`report_recipe`, `POST /admin/reports/run`, `GET /admin/reports/catalogue`) on two seeded
Agencies sharing a Creator: a foreign Creator is refused, the Master sees its own links only, no engine is
ever handed None (or an empty list), no other-Agency Employee row shows, `employee_sales` refuses a shared
Creator, owners only, one run per Agency, the three formats, fan_spend's sort + limit in SQL, the report
zone (a fractional one read by the minute).

Seeded straight into the temp DB; no network.

Run: ./venv/bin/python service/tests/test_report_recipe.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import zipfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from sqlalchemy import text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import msg_stats  # noqa: E402
import of_stats_daily  # noqa: E402
import report_recipe  # noqa: E402
import sales_attribution  # noqa: E402
import stats  # noqa: E402
import stats_fans  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Employee, Fan, Transaction, User, UserAccount  # noqa: E402

IDS = fx.seed_two_agencies()
ENGINE = sa.create_engine(os.environ["CHATTERLY_DB_URL"])
SHARED, B_ONLY, MASTER_C = IDS["creator_a"], IDS["creator_b"], "1000003"
WHEN = datetime.utcnow() - timedelta(days=1)


def _seed() -> dict[str, int]:
    async def _go():
        async with get_session() as s:
            s.add(Account(id=MASTER_C, nickname="creator_m", color="#aaaaaa"))
            s.add(User(id="nolinks", username="agency_c_owner", password=fx.PASSWORD))
            emps = {k: Employee(display_name=k, color="#cccccc", is_active=True, user_id=IDS[owner])
                    for k, owner in (("emp_a", "agency_a_owner"), ("emp_b", "agency_b_owner"))}
            s.add_all(emps.values())
            s.add_all([Fan(account_id=SHARED, fan_id=11, of_display_name="Big Spender"),
                       Fan(account_id=SHARED, fan_id=12, of_username="small")])
            await s.flush()
            out = {k: e.id for k, e in emps.items()}
        async with get_session() as s:
            s.add(UserAccount(user_id=IDS["agency_b_owner"], account_id=SHARED))  # co-owned by A and B
            s.add(UserAccount(user_id=IDS["agency_master"], account_id=MASTER_C))
            for aid, fan, kind, cents in ((SHARED, 11, "ppv_message", 1000), (SHARED, 11, "tip", 500),
                                          (SHARED, 12, "tip", 300), (B_ONLY, 21, "tip", 700),
                                          (MASTER_C, 31, "tip", 900)):
                s.add(Transaction(account_id=aid, fan_id=fan, kind=kind, amount_cents=cents, occurred_at=WHEN,
                                  status="cleared", currency="USD", source="ledger"))
        return out
    (account_registry.ACCOUNTS_DIR / MASTER_C).mkdir()
    return asyncio.run(_go())


EMP = _seed()
_mid = iter(range(81_000_001, 81_100_000))


def _msg(aid: str, sender: int, price: int = 0, paid: bool = False) -> None:
    with ENGINE.begin() as conn:
        conn.execute(text(
            "INSERT INTO messages (account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
            "media_count, price_cents, is_paid, is_tip, is_unsent, is_promise, sent_by_employee_id, mass_run_id, "
            "automation_kind, created_at, ingested_at) VALUES (:a, 11, :m, 'out', '', 'hey', '[]', 0, :p, :paid, "
            "0, 0, 0, :e, NULL, NULL, :c, :c)"),
            {"a": aid, "m": next(_mid), "p": price, "paid": paid, "e": sender,
             "c": WHEN.strftime("%Y-%m-%d %H:%M:%S.%f")})


_msg(SHARED, EMP["emp_a"])
_msg(SHARED, EMP["emp_a"], price=500, paid=True)
_msg(SHARED, EMP["emp_b"], price=900)

A = fx.login_owner("agency_a_owner")
B = fx.login_owner("agency_b_owner")
MASTER = fx.login_owner("agency_master")
WEEK = {"preset": "last_7_days"}


def _run(client, recipe, fmt="json", status=200):
    r = client.post("/admin/reports/run", json={"recipe": recipe, "format": fmt})
    assert r.status_code == status, f"{recipe} {fmt}: {r.status_code} {r.text}"
    return r.json() if fmt == "json" and status == 200 else r


def case_routes_registered():
    import server
    paths = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    assert ("POST", "/admin/reports/run") in paths and ("GET", "/admin/reports/catalogue") in paths


def case_every_dataset_has_an_engine():
    assert report_recipe.ENGINES.keys() == report_recipe.rd.CATALOGUE.keys()


def case_owner_sales_reads_own_creators_only():
    out = _run(A, {"dataset": "sales", "window": WEEK, "metrics": ["gross", "sales"]})
    assert out["columns"] == ["Creator", "Gross ($)", "Sales"], out
    assert out["rows"] == [["creator_a", 18.0, 3]], out
    assert out["window"]["tz"] == "UTC" and out["row_count"] == 1 and out["truncated"] is False
    by_kind = _run(B, {"dataset": "sales", "window": WEEK, "group_by": ["creator", "kind"], "kinds": ["tip"]})
    assert sorted(r[:2] for r in by_kind["rows"]) == [["creator_a", "Tips"], ["creator_b", "Tips"]], by_kind


def case_foreign_creator_refused():
    r = _run(A, {"dataset": "sales", "window": WEEK, "creators": [B_ONLY]}, status=400)
    assert r.json()["errors"] == {"creators": f"not one of your Creators: {B_ONLY}"}, r.json()
    r = _run(MASTER, {"dataset": "fan_spend", "window": WEEK, "creators": [SHARED]}, status=400)
    assert "not one of your Creators" in r.json()["errors"]["creators"]


def case_master_sees_own_links_only():
    out = _run(MASTER, {"dataset": "sales", "window": WEEK, "metrics": ["gross"]})
    assert out["rows"] == [["creator_m", 9.0]], out
    out = _run(MASTER, {"dataset": "chat_activity", "window": WEEK})
    assert out["rows"] == [], out


def case_no_other_agency_employee_row():
    a = _run(A, {"dataset": "chat_activity", "window": WEEK, "group_by": ["employee", "creator"]})
    assert a["columns"] == ["Employee", "Creator", "Messages", "PPVs sent", "PPVs unlocked", "Unlock rate (%)"]
    assert a["rows"] == [["emp_a", "creator_a", 2, 1, 1, 100.0]], a
    b = _run(B, {"dataset": "chat_activity", "window": WEEK})
    assert b["rows"] == [["emp_b", 1, 1, 0, 0.0]], b
    r = _run(A, {"dataset": "chat_activity", "window": WEEK, "employees": [EMP["emp_b"]]}, status=400)
    assert r.json()["errors"] == {"employees": f"not one of your Employees: {EMP['emp_b']}"}


def case_employee_sales_refuses_shared_creator():
    r = _run(A, {"dataset": "employee_sales", "window": WEEK}, status=400)
    assert "shared with another Agency" in r.json()["errors"]["creators"], r.json()
    out = _run(MASTER, {"dataset": "employee_sales", "window": WEEK, "group_by": ["employee", "day"]})
    assert out["columns"] == ["Employee", "Day", "Earnings ($)", "Sales"], out
    assert all(row[0] == "Unattributed" for row in out["rows"]) and sum(r[2] for r in out["rows"]) <= 9.0, out


def case_master_oversight_link_is_no_co_owner():
    """A Master also linking an Agency's Creator: the Agency's employee_sales still exports it (the
    attribution reads that Agency's rules); the Master's own refuses it; a second real Agency still refuses."""
    link = {"u": IDS["agency_master"], "a": B_ONLY}
    with ENGINE.begin() as conn:
        conn.execute(text("INSERT INTO user_accounts (user_id, account_id) VALUES (:u, :a)"), link)
    try:
        out = _run(B, {"dataset": "employee_sales", "window": WEEK, "creators": [B_ONLY]})
        assert out["columns"][0] == "Employee", out
        r = _run(MASTER, {"dataset": "employee_sales", "window": WEEK, "creators": [B_ONLY]}, status=400)
        assert "shared with another Agency" in r.json()["errors"]["creators"], r.json()
        _run(MASTER, {"dataset": "employee_sales", "window": WEEK, "creators": [MASTER_C]})
        r = _run(B, {"dataset": "employee_sales", "window": WEEK, "creators": [SHARED]}, status=400)
        assert "shared with another Agency" in r.json()["errors"]["creators"], r.json()
    finally:
        with ENGINE.begin() as conn:
            conn.execute(text("DELETE FROM user_accounts WHERE user_id = :u AND account_id = :a"), link)


def case_no_engine_gets_none():
    seen: list = []

    def spy(mod, name, key):
        real = getattr(mod, name)

        def wrapped(*a, **k):
            ids = k.get(key) if key in k else a[0]
            seen.append((name, ids))
            assert isinstance(ids, list) and ids and all(isinstance(i, str) for i in ids), (name, ids)
            return real(*a, **k)
        setattr(mod, name, wrapped)
        return real

    patched = [(msg_stats, "send_stats", "account_ids"), (sales_attribution, "credited_sales", "account_ids"),
               (stats, "_day_sums", "account_ids"), (of_stats_daily, "earnings_window", "account_ids"),
               (stats_fans, "fan_spend_q", "account_ids")]
    reals = [(m, n, spy(m, n, k)) for m, n, k in patched]
    try:
        for client, ds in ((A, "sales"), (A, "chat_activity"), (A, "fan_spend"), (MASTER, "employee_sales")):
            _run(client, {"dataset": ds, "window": WEEK})
        assert {n for n, _ in seen} == {n for _, n, _ in patched}, seen
        seen.clear()
        none = fx.login_owner("agency_c_owner")  # an Agency with no Creators: an empty table, no read
        for ds in ("sales", "employee_sales", "chat_activity", "fan_spend"):
            assert _run(none, {"dataset": ds, "window": WEEK})["rows"] == []
        assert seen == [], seen
    finally:
        for m, n, real in reals:
            setattr(m, n, real)


def case_owners_only():
    chatter = fx.login_chatter("chatter_a")
    assert chatter.post("/admin/reports/run", json={"recipe": {}, "format": "json"}).status_code == 403
    assert chatter.get("/admin/reports/catalogue").status_code == 403
    anon = _harness.make_client()
    assert anon.post("/admin/reports/run", json={"recipe": {}, "format": "json"}).status_code == 401
    cat = A.get("/admin/reports/catalogue")
    assert cat.status_code == 200 and [d["dataset"] for d in cat.json()["datasets"]] == \
        ["chat_activity", "employee_sales", "fan_spend", "sales"]


def case_one_run_per_agency():
    report_recipe._running.add(IDS["agency_a_owner"])
    try:
        r = _run(A, {"dataset": "sales", "window": WEEK}, status=429)
        assert "already running" in r.json()["errors"]["run"]
        _run(B, {"dataset": "sales", "window": WEEK})  # another Agency is not held up
    finally:
        report_recipe._running.discard(IDS["agency_a_owner"])
    _run(A, {"dataset": "sales", "window": WEEK})
    assert not report_recipe._running


def case_parse_errors_come_back_per_field():
    r = _run(A, {"dataset": "sales", "window": {"preset": "forever"}, "kinds": ["dance"]}, status=400)
    assert set(r.json()["errors"]) == {"window", "kinds"}, r.json()
    r = _run(A, {"dataset": "employee_sales", "window": {"preset": "last_365_days"}}, status=400)
    assert "at most 92" in r.json()["errors"]["window"]


def case_formats():
    recipe = {"dataset": "sales", "window": WEEK, "metrics": ["gross"]}
    r = _run(A, recipe, "csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="sales_' in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    assert r.text.splitlines() == ["Creator,Gross ($)", "creator_a,18.0"], r.text
    x = _run(A, recipe, "xlsx")
    assert x.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert '.xlsx"' in x.headers["content-disposition"]
    sheet = zipfile.ZipFile(io.BytesIO(x.content)).read("xl/worksheets/sheet1.xml").decode()
    assert "creator_a" in sheet and "Gross ($)" in sheet


def case_fan_spend_sort_and_limit_in_sql():
    out = _run(A, {"dataset": "fan_spend", "window": WEEK, "metrics": ["total", "tips"], "sort": "tips", "limit": 1})
    assert out["columns"] == ["Creator", "Fan", "Total ($)", "Tips ($)"], out
    assert out["rows"] == [["creator_a", "Big Spender", 15.0, 5.0]], out
    out = _run(A, {"dataset": "fan_spend", "window": WEEK, "kinds": ["tip"], "metrics": ["total"]})
    assert out["rows"] == [["creator_a", "Big Spender", 5.0], ["creator_a", "@small", 3.0]], out


def case_fan_spend_sql_orders_by_what_shape_orders_by():
    # Review F1: Zed spends the most in total, Amy tips the most. metrics=["tips"] + limit 1 is the biggest
    # tipper (SQL used to cut by total first); sort "fan" + limit 1 is refused (SQL cannot cut by a label).
    async def _go():
        async with get_session() as s:
            s.add_all([Fan(account_id=MASTER_C, fan_id=41, of_display_name="Zed"),
                       Fan(account_id=MASTER_C, fan_id=42, of_display_name="Amy")])
            for fan, kind, cents in ((41, "ppv_message", 5000), (41, "tip", 100), (42, "tip", 1500)):
                s.add(Transaction(account_id=MASTER_C, fan_id=fan, kind=kind, amount_cents=cents, occurred_at=WHEN,
                                  status="cleared", currency="USD", source="ledger"))
    asyncio.run(_go())
    out = _run(MASTER, {"dataset": "fan_spend", "window": WEEK, "metrics": ["tips"], "limit": 1})
    assert out["rows"] == [["creator_m", "Amy", 15.0]], out
    out = _run(MASTER, {"dataset": "fan_spend", "window": WEEK, "metrics": ["total"], "limit": 1})
    assert out["rows"] == [["creator_m", "Zed", 51.0]], out
    r = _run(MASTER, {"dataset": "fan_spend", "window": WEEK, "sort": "fan", "limit": 1}, status=400)
    assert "sorts by one of the chosen metrics" in r.json()["errors"]["sort"], r.json()


def case_engine_notes_reach_json_and_files():
    # Review F16: credited_sales' fallback line is a note in json and the last line of a file.
    real = report_recipe.ENGINES["sales"]

    async def noted(r, sc):
        cells, more, _ = await real(r, sc)
        return cells, more, [sales_attribution.FALLBACK_LINE]
    report_recipe.ENGINES["sales"] = noted
    try:
        recipe = {"dataset": "sales", "window": WEEK, "metrics": ["gross"]}
        assert _run(A, recipe)["notes"] == [sales_attribution.FALLBACK_LINE]
        lines = _run(A, recipe, "csv").text.splitlines()
        assert lines[-1].startswith("# Shift schedule"), lines
        sheet = zipfile.ZipFile(io.BytesIO(_run(A, recipe, "xlsx").content)).read("xl/worksheets/sheet1.xml")
        assert b"# Shift schedule" in sheet
    finally:
        report_recipe.ENGINES["sales"] = real


def case_report_zone_and_fractional_zone():
    fx.store_blob(IDS["agency_a_owner"], "preferences", {"report_tz": "Asia/Kolkata", "week_start": "sunday"})
    try:
        out = _run(A, {"dataset": "sales", "window": WEEK, "metrics": ["gross"], "group_by": ["week"]})
        assert out["window"]["tz"] == "Asia/Kolkata" and sum(r[1] for r in out["rows"]) == 18.0, out
        act = _run(A, {"dataset": "chat_activity", "window": {"preset": "today"}, "group_by": ["hour"]})
        assert act["window"]["tz"] == "Asia/Kolkata", act
    finally:
        fx.store_blob(IDS["agency_a_owner"], "preferences", {})


_harness.run()
