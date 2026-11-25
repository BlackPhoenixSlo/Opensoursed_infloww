#!/usr/bin/env python3
import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
from _clock_fixtures import utc_now, z  # noqa: E402
from db.engine import get_session, init_db  # noqa: E402
from db.models import (  # noqa: E402
    SETTINGS_EPOCH, Account, Employee, Message, SettingsVersion, Transaction, User, UserAccount,
    UserSetting,
)

fx.seed_two_agencies()
_MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations" / "versions"
SINCE_THE_START = "1970-01-01T00:00:00Z"
CONVERTERS = {"messages": "converters", "posts_tips": "converters", "subscriptions_chatter_opt_in": False}


async def _apply_view() -> None:
    spec = importlib.util.spec_from_file_location("mig_attr_view", _MIGRATIONS / "20261027_0100_converters_window.py")
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    async with get_session() as s:
        await s.execute(text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
        await s.execute(text(mig._NEW_VIEW_SQL))


asyncio.run(_apply_view())

_next_id = iter(range(8_000_001, 8_100_000))


class Agency:

    def __init__(self, name: str):
        self.user_id, self.creator = uuid.uuid4().hex, str(next(_next_id))

        async def _seed():
            async with get_session() as s:
                s.add(User(id=self.user_id, username=name, password=fx.PASSWORD))
                s.add(Account(id=self.creator, nickname=f"sv_{name}", color="#aaaaaa"))
            async with get_session() as s:
                s.add(UserAccount(user_id=self.user_id, account_id=self.creator))
                emp = Employee(display_name=f"{name}_emp", is_active=True, created_at=datetime.utcnow(),
                               user_id=self.user_id)
                s.add(emp)
                await s.flush()
                return emp.id
        (account_registry.ACCOUNTS_DIR / self.creator).mkdir()
        self.employee = asyncio.run(_seed())
        self.client = fx.login_owner(name)

    def put(self, tab: str, blob: dict, effective_from: str | None = None):
        params = {} if effective_from is None else {"effective_from": effective_from}
        return self.client.put(f"/admin/settings/{tab}", json=blob, params=params)

    def sales(self, exclude_of_fee: bool, effective_from: str | None = None) -> None:
        r = self.put("sales", {"exclude_welcome": False, "exclude_of_fee": exclude_of_fee,
                               "attribution": CONVERTERS}, effective_from)
        assert r.status_code == 200, f"PUT sales: {r.status_code} {r.text}"

    def tip(self, cents: int, at: datetime) -> None:
        fan, mid = next(_next_id), next(_next_id)

        async def _seed():
            async with get_session() as s:
                s.add(Message(account_id=self.creator, fan_id=fan, message_id=mid, direction="out", body="x",
                              sent_by_employee_id=self.employee, created_at=at - timedelta(hours=1),
                              ingested_at=at - timedelta(hours=1)))
                s.add(Transaction(account_id=self.creator, fan_id=fan, kind="tip", message_id=mid,
                                  amount_cents=cents, occurred_at=at, status="cleared", currency="USD",
                                  source="ledger"))
        asyncio.run(_seed())

    def payroll(self, frm: str, to: str) -> dict:
        r = self.client.get("/admin/stats/per-employee", params={"from": frm, "to": to, "by_account": "true"})
        assert r.status_code == 200, f"per-employee: {r.status_code} {r.text}"
        return {row["employee_id"]: sub["revenue_cents"] for row in r.json()["employees"]
                for sub in row.get("per_account", []) if sub["account_id"] == self.creator and sub["revenue_cents"]}

    def history(self, tab: str = "sales") -> list[tuple]:
        r = self.client.get(f"/admin/settings/{tab}")
        assert r.status_code == 200, f"GET {tab}: {r.status_code} {r.text}"
        return [(h["effective_from"], h["in_effect"]) for h in r.json()["history"]]


def _at(day: str, hhmm: str = "12:00") -> datetime:
    return datetime.fromisoformat(f"2026-05-{day}T{hhmm}:00")




def case_a_backdated_change_recomputes_only_the_sales_from_its_effective_time():
    a = Agency("sv_backdated")
    a.sales(False, SINCE_THE_START)
    for day in ("04", "06", "08"):
        a.tip(1000, _at(day))
    assert a.payroll("2026-05-04", "2026-05-08") == {a.employee: 3000}
    a.sales(True, "2026-05-05T00:00:00Z")
    assert a.payroll("2026-05-04", "2026-05-08") == {a.employee: 2600}
    a.sales(False, "2026-05-07T00:00:00+00:00")
    assert a.payroll("2026-05-04", "2026-05-08") == {a.employee: 2800}
    assert [a.payroll(f"2026-05-{d}", f"2026-05-{d}") for d in ("04", "06", "08")] == \
        [{a.employee: 1000}, {a.employee: 800}, {a.employee: 1000}]
    assert a.history() == [("2026-05-07T00:00:00Z", True), ("2026-05-05T00:00:00Z", False), (None, False)], \
        a.history()


def case_a_change_effective_now_leaves_past_payroll_and_reaches_the_next_sale():
    a = Agency("sv_now")
    a.sales(False, SINCE_THE_START)
    a.tip(1000, _at("04"))
    a.sales(True)
    a.tip(1000, datetime.utcnow() + timedelta(seconds=1))
    today, tomorrow = datetime.utcnow().date(), datetime.utcnow().date() + timedelta(days=1)
    assert a.payroll("2026-05-04", "2026-05-04") == {a.employee: 1000}
    assert a.payroll(str(today), str(tomorrow)) == {a.employee: 800}
    assert a.payroll("2026-05-04", str(tomorrow)) == {a.employee: 1800}
    assert a.history() == [(a.history()[0][0], True), (None, False)]


def case_two_versions_at_one_time_read_the_later_save():
    a = Agency("sv_same_time")
    a.tip(1000, _at("04"))
    a.sales(True, "2026-05-01T00:00:00Z")
    a.sales(False, "2026-05-01T00:00:00Z")
    assert a.payroll("2026-05-04", "2026-05-04") == {a.employee: 1000}


def case_a_sale_before_any_version_reads_the_defaults():
    a = Agency("sv_defaults")
    a.tip(1000, _at("04"))
    a.tip(1000, _at("06"))
    a.sales(True, "2026-05-05T00:00:00Z")
    assert a.payroll("2026-05-04", "2026-05-06") == {a.employee: 1800}


def case_the_effective_time_must_be_a_zoned_time_not_later_than_now():
    a = Agency("sv_refused")
    later = z(utc_now() + timedelta(hours=1))
    for value in (later, "2026-05-05T00:00:00", "yesterday"):
        r = a.put("sales", {"exclude_of_fee": True}, value)
        assert r.status_code == 400, f"{value}: {r.status_code} {r.text}"
    assert a.history() == [], "a refused save wrote no version"
    r = a.put("sales", {"exclude_of_fee": True}, "1900-01-01T00:00:00Z")
    assert r.status_code == 200, r.text
    assert r.json()["history"] == [{**r.json()["history"][0], "effective_from": None, "in_effect": True}]


def case_other_tabs_are_not_versioned():
    a = Agency("sv_messaging")
    r = a.put("messaging", {}, "2026-05-05T00:00:00Z")
    assert r.status_code == 200, r.text
    assert "history" not in r.json(), r.json()




async def _raw_blob(user_id: str, tab: str, raw: str, saved: datetime = datetime(2026, 4, 1)) -> None:
    async with get_session() as s:
        s.add(UserSetting(user_id=user_id, tab=tab, config_json=raw, updated_at=saved))


async def _versions(user_id: str) -> list[tuple]:
    async with get_session() as s:
        return [tuple(r) for r in (await s.execute(
            select(SettingsVersion.tab, SettingsVersion.effective_from, SettingsVersion.config_json)
            .where(SettingsVersion.user_id == user_id)
            .order_by(SettingsVersion.tab, SettingsVersion.effective_from))).all()]


async def _left(user_id: str) -> list[str]:
    async with get_session() as s:
        return sorted((await s.execute(select(UserSetting.tab).where(UserSetting.user_id == user_id))).scalars())


async def _count() -> int:
    async with get_session() as s:
        return (await s.execute(select(func.count()).select_from(SettingsVersion))).scalar_one()


def case_the_boot_move_keeps_every_figure_a_stored_blob_gave():
    a = Agency("sv_boot")
    a.tip(1000, _at("04"))
    a.tip(1000, datetime(2026, 6, 1, 12))
    blob = '{"exclude_of_fee": true, "attribution": {"messages": "converters", "posts_tips": "converters"}}'
    asyncio.run(_raw_blob(a.user_id, "sales", blob))
    asyncio.run(_raw_blob(a.user_id, "messaging", "{}"))
    asyncio.run(init_db())
    assert asyncio.run(_versions(a.user_id)) == [("sales", SETTINGS_EPOCH, blob)]
    assert asyncio.run(_left(a.user_id)) == ["messaging"], "only the versioned tabs move"
    assert a.payroll("2026-05-04", "2026-06-01") == {a.employee: 1600}
    assert a.history() == [(None, True)]
    before = asyncio.run(_count())
    asyncio.run(init_db())
    assert asyncio.run(_count()) == before, "a second boot moves nothing"


def case_a_blob_stored_after_the_move_lands_as_a_save_from_its_own_time():
    a = Agency("sv_rollback")
    a.tip(1000, _at("04"))
    a.tip(1000, datetime(2026, 6, 1, 12))
    on = '{"exclude_of_fee": true, "attribution": {"messages": "converters", "posts_tips": "converters"}}'
    off = '{"exclude_of_fee": false, "attribution": {"messages": "converters", "posts_tips": "converters"}}'
    asyncio.run(_raw_blob(a.user_id, "sales", on))
    asyncio.run(init_db())
    asyncio.run(_raw_blob(a.user_id, "sales", off, datetime(2026, 5, 20)))
    asyncio.run(init_db())
    assert asyncio.run(_versions(a.user_id)) == [("sales", SETTINGS_EPOCH, on), ("sales", datetime(2026, 5, 20), off)]
    assert asyncio.run(_left(a.user_id)) == []
    assert a.payroll("2026-05-04", "2026-06-01") == {a.employee: 1800}
    assert a.history() == [("2026-05-20T00:00:00Z", True), (None, False)]


def case_migration_upgrade_and_downgrade_on_a_fresh_temp_file():
    found = list(_MIGRATIONS.glob("*_shift_scope_versions.py"))
    assert len(found) == 1, found
    spec = importlib.util.spec_from_file_location("shift_scope_versions", found[0])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.down_revision == "0077_tx_credit_rollup", mod.down_revision
    assert len(mod.revision) <= 32, "alembic_version.version_num is VARCHAR(32)"
    path = Path(tempfile.gettempdir()) / f"shift_scope_versions_{uuid.uuid4().hex}.db"
    assert str(path) != os.environ.get("RELAY_DB_PATH", "")
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE users (id TEXT PRIMARY KEY);
            CREATE TABLE shifts (id INTEGER PRIMARY KEY, repeat_until DATE);
            CREATE TABLE user_settings (user_id TEXT, tab TEXT, config_json TEXT, updated_at DATETIME,
                                        PRIMARY KEY (user_id, tab));
            INSERT INTO users VALUES ('u1');
            INSERT INTO shifts VALUES (1, NULL);
            INSERT INTO user_settings VALUES ('u1', 'sales', '{"exclude_of_fee": true}', '2026-04-01 00:00:00');
            INSERT INTO user_settings VALUES ('u1', 'time-tracking', '{"enabled": true}', '2026-04-01 00:00:00');
            INSERT INTO user_settings VALUES ('u1', 'general', '{}', '2026-04-01 00:00:00');
        """)
    engine = sa.create_engine(f"sqlite:///{path}")
    try:
        def _run(step) -> None:
            with engine.begin() as conn:
                with Operations.context(MigrationContext.configure(conn)):
                    step()

        def _rows(sql: str) -> list[tuple]:
            with sqlite3.connect(path) as conn:
                return conn.execute(sql).fetchall()

        _run(mod.upgrade)
        moved = [("u1", "sales", "1970-01-01 00:00:00.000000", '{"exclude_of_fee": true}'),
                 ("u1", "time-tracking", "1970-01-01 00:00:00.000000", '{"enabled": true}')]
        versions = "SELECT user_id, tab, effective_from, config_json FROM settings_versions ORDER BY tab"
        assert _rows(versions) == moved, _rows(versions)
        assert _rows("SELECT tab FROM user_settings") == [("general",)]
        assert _rows("SELECT cancelled_dates FROM shifts") == [(None,)]
        _run(mod.upgrade)
        assert _rows(versions) == moved
        with sqlite3.connect(path) as conn:
            conn.execute("INSERT INTO user_settings VALUES ('u1', 'sales', '{\"x\": 1}', '2026-04-02 00:00:00')")
        _run(mod.upgrade)
        assert _rows(versions) == [moved[0], ("u1", "sales", "2026-04-02 00:00:00", '{"x": 1}'), moved[1]], \
            _rows(versions)

        with sqlite3.connect(path) as conn:
            conn.execute("INSERT INTO settings_versions (user_id, tab, effective_from, config_json) VALUES "
                         "('u1', 'sales', '2026-05-05 00:00:00.000000', '{\"exclude_of_fee\": false}'), "
                         "('u1', 'sales', '2999-01-01 00:00:00.000000', '{\"later\": true}')")
        _run(mod.downgrade)
        assert _rows("SELECT tab, config_json FROM user_settings ORDER BY tab") == [
            ("general", "{}"), ("sales", '{"exclude_of_fee": false}'), ("time-tracking", '{"enabled": true}')]
        assert _rows("SELECT name FROM sqlite_master WHERE name LIKE '%settings_versions%'") == []
        assert "cancelled_dates" not in {c[1] for c in _rows("PRAGMA table_info(shifts)")}
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)


_harness.run()
