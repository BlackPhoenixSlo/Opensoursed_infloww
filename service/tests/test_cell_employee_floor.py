from __future__ import annotations

import _harness

import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

_harness.bootstrap()

import agency_copy as ac  # noqa: E402
import cell_mode  # noqa: E402
import employees  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="cell-floor-"))


def _db(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None, timeout=30)
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _control(name: str, emp_ids=(1, 2, 3)) -> str:
    path = str(_TMP / f"{name}.db")
    with contextlib.closing(sqlite3.connect(_harness.DB_PATH)) as src, contextlib.closing(sqlite3.connect(path)) as dst:
        src.backup(dst)
    with contextlib.closing(_db(path)) as db:
        db.execute("DELETE FROM employees")
        for i in emp_ids:
            db.execute("INSERT INTO employees (id, display_name, is_active, created_at, user_id) VALUES"
                       " (?, ?, 1, '2026-01-01', 'u1')", (i, f"E{i}"))
    ac.install(f"sqlite:///{path}", "control")
    return path


@contextlib.contextmanager
def _placement(*data_cells: str):
    p = _TMP / f"placement-{'-'.join(data_cells) or 'none'}.json"
    cells = {"s01": {"role": "control"}, **{c: {"role": "data"} for c in data_cells}}
    p.write_text(json.dumps({"schema": 1, "agency": "acme", "min_cell_proto": 1, "cells": cells}))
    old = os.environ.get("OI_CELL_MAP")
    os.environ["OI_CELL_MAP"] = str(p)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("OI_CELL_MAP", None)
        else:
            os.environ["OI_CELL_MAP"] = old


def _insert(path: str) -> int:
    with contextlib.closing(_db(path)) as db:
        return db.execute("INSERT INTO employees (display_name, is_active, created_at, user_id) VALUES"
                          " ('New', 1, '2026-01-02', 'u1')").lastrowid


def _refused(path: str) -> None:
    with contextlib.closing(_db(path)) as db:
        n = db.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        try:
            db.execute("INSERT INTO employees (display_name, is_active, created_at, user_id) VALUES"
                       " ('New', 1, '2026-01-02', 'u1')")
        except sqlite3.IntegrityError as e:
            assert ac.FLOOR_MSG in str(e), e
        else:
            raise AssertionError("Employee created while the floor is pending")
        assert db.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == n


def _pending(path: str) -> int:
    with contextlib.closing(_db(path)) as db:
        return db.execute("SELECT pending FROM employee_floor").fetchone()[0]


def case_floor_waits_for_every_placement_data_cell_then_floors_above_all() -> None:
    ctl = _control("ctl-wait")
    with _placement("s02", "s03"):
        assert ac.report_max_emp(ctl, "s02", 9) is None and _pending(ctl) == 0, "gate closed before any restore"
        ac.bump_epoch(ctl)
        assert _pending(ctl) == 1
        with contextlib.closing(_db(ctl)) as db:
            assert db.execute("SELECT COUNT(*) FROM employee_floor_reports").fetchone()[0] == 0, "reports kept"
        _refused(ctl)
        assert ac.report_max_emp(ctl, "s02", 50) is None
        assert ac.report_max_emp(ctl, "s02", 40) is None
        assert ac.report_max_emp(ctl, "s99", 500) is None, "a key not in Placement opened the gate"
        _refused(ctl)
        assert ac.report_max_emp(ctl, "s03", 80) == 501
        assert _pending(ctl) == 0
        with contextlib.closing(_db(ctl)) as db:
            assert db.execute("SELECT max_emp FROM employee_floor_reports WHERE cell = 's02'").fetchone() == (50,)
            row = db.execute("SELECT id, display_name, is_active, user_id, chatter_id FROM employees"
                             " ORDER BY id DESC LIMIT 1").fetchone()
        assert row == (501, ac.FLOOR_NAME, 0, None, None), row
        assert _insert(ctl) == 502


def case_no_placeholder_when_control_holds_the_highest_id() -> None:
    ctl = _control("ctl-high", (1, 2, 100))
    with _placement("s02"):
        ac.bump_epoch(ctl)
        assert ac.report_max_emp(ctl, "s02", 60) == 100
    with contextlib.closing(_db(ctl)) as db:
        assert db.execute("SELECT COUNT(*) FROM employees WHERE display_name = ?", (ac.FLOOR_NAME,)).fetchone() == (0,)
    assert _insert(ctl) == 101


def case_report_before_restore_does_not_count() -> None:
    ctl = _control("ctl-old")
    with _placement("s02"):
        ac.report_max_emp(ctl, "s02", 70)
        ac.bump_epoch(ctl)
        _refused(ctl)
        assert ac.report_max_emp(ctl, "s02", 70) == 71
    assert _insert(ctl) == 72


def case_restored_control_without_data_cells_opens_at_boot() -> None:
    ctl = _control("ctl-none")
    with _placement():
        ac.bump_epoch(ctl)
        assert _pending(ctl) == 1
        ac.install(f"sqlite:///{ctl}", "control")
    assert _pending(ctl) == 0


def case_bump_epoch_creates_floor_tables_on_an_old_backup() -> None:
    ctl = _control("ctl-oldbackup")
    with contextlib.closing(_db(ctl)) as db:
        db.execute("DROP TRIGGER cell_floor_employees_insert")
        db.execute("DROP TABLE employee_floor")
        db.execute("DROP TABLE employee_floor_reports")
    ac.bump_epoch(ctl)
    assert _pending(ctl) == 1
    with _placement("s02"):
        ac.install(f"sqlite:///{ctl}", "control")
        _refused(ctl)


def case_data_cell_has_no_floor_trigger() -> None:
    cell = str(_TMP / "cell.db")
    with contextlib.closing(sqlite3.connect(_harness.DB_PATH)) as src, contextlib.closing(sqlite3.connect(cell)) as dst:
        src.backup(dst)
    ac.install(f"sqlite:///{cell}", "data")
    with contextlib.closing(_db(cell)) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'cell_floor_%'"
                          " OR name LIKE 'employee_floor%'").fetchall() == []


async def case_placeholder_hidden_from_rosters_and_not_automation() -> None:
    from db.engine import get_session
    from sqlalchemy import text
    async with get_session() as s:
        auto = (await s.execute(text("INSERT INTO employees (display_name, is_active, created_at, user_id)"
                                     " VALUES ('Automation', 0, '2026-01-01', NULL) RETURNING id"))).scalar()
        await s.execute(text("INSERT INTO employees (display_name, is_active, created_at, user_id)"
                             " VALUES (:n, 0, '2026-01-01', NULL)"), {"n": ac.FLOOR_NAME})
    assert await employees.get_automation_employee_id() == auto
    names = [e["display_name"] for e in (await employees.list_employees(include_disabled=True))["employees"]]
    assert ac.FLOOR_NAME not in names, names
    assert ac.FLOOR_NAME != "Automation"
    async with get_session() as s:
        await s.execute(text("DELETE FROM employees WHERE display_name IN (:n, 'Automation')"), {"n": ac.FLOOR_NAME})


async def case_data_cell_mirror_miss_writes_nothing() -> None:
    from db.engine import get_session
    from sqlalchemy import text
    async with get_session() as s:
        before = (await s.execute(text("SELECT COUNT(*) FROM employees"))).scalar()
    with _placement("s02"), patch.dict(os.environ, OI_CELL_ROLE="data"):
        got = await employees.get_or_create_mirror_employee("nobody-chatter", "nobody-owner",
                                                            display_name="X", color=None)
    assert got is None
    async with get_session() as s:
        assert (await s.execute(text("SELECT COUNT(*) FROM employees"))).scalar() == before


async def case_backfill_writes_owner_mirror_login_mirror_role_and_presets() -> None:
    from db.engine import get_session
    from sqlalchemy import text
    from settings_api import read_blob
    async with get_session() as s:
        await s.execute(text("INSERT INTO users (id, username, password, created_at, last_seen_at, is_admin)"
                             " VALUES ('bf-owner', 'bfowner', 'p', '2026-01-01', '2026-01-01', 0)"))
        await s.execute(text("INSERT INTO chatters (id, username, password, is_active, created_at, last_seen_at)"
                             " VALUES ('bf-chat', 'bfchat', 'p', 1, '2026-01-01', '2026-01-01')"))
        await s.execute(text("INSERT INTO chatter_users VALUES ('bf-chat', 'bf-owner', '2026-01-01')"))
    for _ in range(2):
        assert await employees.backfill_agency_rows() >= 1
    async with get_session() as s:
        rows = (await s.execute(text("SELECT id, chatter_id FROM employees WHERE user_id = 'bf-owner'"))).all()
        assert sorted(c for _i, c in rows) == ["bf-chat", "owner:bf-owner"], rows
        login = next(i for i, c in rows if c == "bf-chat")
        roles = await read_blob(s, "bf-owner", "roles")
        assert roles["assignments"][str(login)] == "chatter", roles
        assert {"manager", "va"} <= {r["id"] for r in roles["roles"]}, roles
        assert (await s.execute(text("SELECT 1 FROM user_settings WHERE user_id = 'bf-owner'"
                                     " AND tab = 'role-presets'"))).first()


def case_env_unset_installs_nothing() -> None:
    assert "OI_CELL_MAP" not in os.environ
    with patch.dict(os.environ, OI_CELL_ROLE="data"):
        assert cell_mode.role() is None
    with contextlib.closing(_db(str(_harness.DB_PATH))) as db:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'cell_floor_%'"
                                          " OR name LIKE 'employee_floor%' OR name LIKE 'agency_copy_%'")}
    assert not names, names


async def case_env_unset_mirror_miss_inserts_as_main() -> None:
    got = await employees.get_or_create_mirror_employee("unset-chatter", "bf-owner", display_name="U", color=None)
    assert isinstance(got, int), got


def case_floor_report_skips_write_lock_when_clear() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        path = str(tmp_path / "floor.db")
        with sqlite3.connect(path) as db:
            ac._floor_tables(db)
            db.execute("INSERT INTO employee_floor_reports VALUES ('s02', 1, 10, 'before')")
            db.execute("CREATE TABLE agency_copy_version (epoch, version, grant_gen)")
            db.execute("INSERT INTO agency_copy_version VALUES (1, 1, 1)")
        assert ac.report_max_emp(path, "s02", 99) is None
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT max_emp, reported_at FROM employee_floor_reports").fetchall() == [(10, "before")]


_harness.run()
