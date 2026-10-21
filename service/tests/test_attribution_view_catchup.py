#!/usr/bin/env python3
"""init_db builds the attribution view a fresh box never got from alembic.

create_all builds no views and nothing on boot runs alembic, so Stats and Sales
records 500'd with "no such table: per_employee_revenue_with_attribution" on
any box that was not upgraded by hand. `ensure_attribution_view` creates the
view when it is missing, rebuilds an older revision, and leaves the current
one alone.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)
_harness.bootstrap()

import importlib  # noqa: E402
import importlib.util  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import create_engine, inspect, text  # noqa: E402

db_engine = importlib.import_module("db.engine")  # `from db import engine` is the AsyncEngine

_VIEW = "per_employee_revenue_with_attribution"
_VERSIONS = Path(__file__).resolve().parent.parent / "db" / "migrations" / "versions"


def _sync_engine():
    url = db_engine.DATABASE_URL.replace("+aiosqlite", "")
    return create_engine(url)


def _cols(eng) -> set[str]:
    insp = inspect(eng)
    if _VIEW not in insp.get_view_names():
        return set()
    return {c["name"] for c in insp.get_columns(_VIEW)}


def case_fresh_init_db_has_the_current_view() -> None:
    eng = _sync_engine()
    try:
        cols = _cols(eng)
        assert {"tx_id", "rule"} <= cols, cols
        # And it is queryable, which is what the 500 was about.
        with eng.connect() as c:
            c.execute(text(f"SELECT COUNT(*) FROM {_VIEW}")).scalar()
        assert db_engine.ensure_attribution_view(eng) == "present"
    finally:
        eng.dispose()


def case_missing_view_is_created() -> None:
    eng = _sync_engine()
    try:
        with eng.begin() as c:
            c.execute(text(f"DROP VIEW IF EXISTS {_VIEW}"))
        assert _cols(eng) == set()
        assert db_engine.ensure_attribution_view(eng) == "created"
        assert {"tx_id", "rule"} <= _cols(eng)
    finally:
        eng.dispose()


def case_older_revision_is_rebuilt() -> None:
    path = _VERSIONS / "20260710_0200_attr_view_orphan_rows.py"
    spec = importlib.util.spec_from_file_location("mig0042", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    eng = _sync_engine()
    try:
        with eng.begin() as c:
            c.execute(text(f"DROP VIEW IF EXISTS {_VIEW}"))
            c.execute(text(mig._NEW_VIEW_SQL))
        assert "tx_id" not in _cols(eng), "fixture: 0042 predates tx_id"
        assert db_engine.ensure_attribution_view(eng) == "rebuilt"
        assert {"tx_id", "rule"} <= _cols(eng)
        assert db_engine.ensure_attribution_view(eng) == "present"
    finally:
        eng.dispose()


_harness.run()
