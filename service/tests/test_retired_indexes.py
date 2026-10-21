#!/usr/bin/env python3
"""
init_db drops a retired index only once its replacement exists.

`_RETIRED_INDEXES` maps an index the models no longer declare to the wider one
that replaced it. If the catch-up failed to CREATE the replacement, dropping
the old one would leave the table with neither, so the old one stays.

Plain-assert standalone script (no pytest), run via:

    ./venv/bin/python service/tests/test_retired_indexes.py

Exit 0 = all pass.
"""
from __future__ import annotations

import _harness  # noqa: F401  # MUST be first — binds a throwaway DB (prod-fallback guard)

import asyncio
import sqlite3

_harness.bootstrap()

from sqlalchemy import create_engine  # noqa: E402

from db.engine import _RETIRED_INDEXES, _drop_retired_indexes, init_db  # noqa: E402

_OLD = "ix_messages_account_fan_time"
_NEW = "ix_messages_chat_seq"


def _sql(*stmts: str) -> None:
    c = sqlite3.connect(str(_harness.DB_PATH))
    try:
        for stmt in stmts:
            c.execute(stmt)
        c.commit()
    finally:
        c.close()


def _indexes() -> set[str]:
    c = sqlite3.connect(f"file:{_harness.DB_PATH}?mode=ro", uri=True)
    try:
        return {r[1] for r in c.execute("pragma index_list(messages)")}
    finally:
        c.close()


def _restore_old() -> None:
    _sql(f"CREATE INDEX IF NOT EXISTS {_OLD} ON messages (account_id, fan_id, created_at)")


def case_mapping_names_the_replacement() -> None:
    assert _RETIRED_INDEXES[_OLD] == ("messages", _NEW)


def case_kept_while_replacement_missing() -> None:
    _restore_old()
    _sql(f"DROP INDEX IF EXISTS {_NEW}")
    eng = create_engine(f"sqlite:///{_harness.DB_PATH}")
    try:
        _drop_retired_indexes(eng)
    finally:
        eng.dispose()
    live = _indexes()
    assert _OLD in live and _NEW not in live, sorted(live)


def case_boot_creates_replacement_then_drops_old() -> None:
    _restore_old()
    _sql(f"DROP INDEX IF EXISTS {_NEW}")
    asyncio.run(init_db())
    live = _indexes()
    assert _NEW in live and _OLD not in live, sorted(live)


def main() -> int:
    cases = [v for k, v in globals().items() if k.startswith("case_")]
    for case in cases:
        case()
        print(f"ok  {case.__name__}")
    print(f"{len(cases)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
