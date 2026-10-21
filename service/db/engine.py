"""
Async SQLAlchemy engine + session factory.

DATABASE_URL comes from service/.env (loaded via python-dotenv). Defaults
to SQLite for the single-machine deployment described in the plan.

Two ergonomics knobs on the SQLite path:
  • `check_same_thread=False` — required because we hand sessions to
    background tasks (the WS pump applies events from one task while
    HTTP handlers serve another).
  • PRAGMA journal_mode=WAL — readers don't block writers. Critical for
    "one tab reads while another tab + the WS pump writes."

For Postgres, none of these knobs apply — drop in the asyncpg URL and the
engine constructs the right pool with sane defaults.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool

HERE = Path(__file__).resolve().parent
# Load service/.env (gitignored). Falls back to env-vars already in process.
load_dotenv(HERE.parent / ".env", override=False)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{HERE.parent / 'chatterly.db'}",
)

_is_sqlite = DATABASE_URL.startswith("sqlite")

# A file SQLite keeps its connections in a pool. aiosqlite's own default for a
# file is NullPool: every session opens a connection (a thread plus the PRAGMAs
# below) and closes it, ~3-6x the cost of a pooled session. Overflow is
# unlimited, as NullPool's was, so a burst never waits on the pool (and the
# pool never awaits its queue, so pool_timeout is never consulted); only
# `pool_size` connections stay open between sessions. Memory bound: each kept
# connection's page cache grows to cache_size (64 MiB), so at most 5 x 64 MiB =
# 320 MiB is held while idle; overflow connections close on return, and the
# mmap is the OS page cache, shared. The in-memory DB keeps aiosqlite's
# StaticPool. CHATTERLY_DB_NULLPOOL=1 (set by tests/_harness.py, which runs a
# fresh event loop per case) keeps NullPool, so a connection never outlives
# the loop that opened it there.
_POOL_ARGS = {"poolclass": AsyncAdaptedQueuePool, "pool_size": 5, "max_overflow": -1}
_pooled = (
    _is_sqlite
    and ":memory:" not in DATABASE_URL
    and "mode=memory" not in DATABASE_URL
    and os.environ.get("CHATTERLY_DB_NULLPOOL") != "1"
)


def _set_sqlite_pragmas(dbapi_conn, _connection_record) -> None:
    """Per-connection PRAGMAs, set as each connection opens, so a pooled one
    carries them for its whole life."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA cache_size=-64000")   # 64 MiB
    cur.execute("PRAGMA busy_timeout=30000")  # 30 s — concurrent writers
    # Reads straight from the OS page cache instead of copying each
    # page through read(); 256 MiB covers the hot tables.
    cur.execute("PRAGMA mmap_size=268435456")
    # Sorts and temp b-trees (GROUP BY, DISTINCT, ORDER BY without an
    # index — every stats aggregate) stay in RAM, not a temp file.
    cur.execute("PRAGMA temp_store=MEMORY")
    cur.close()


def _make_engine(url: str, pooled: bool) -> AsyncEngine:
    """The relay's engine for `url`; a SQLite one sets its PRAGMAs on every
    connect from the first, before any connection exists."""
    # `echo=False` because the relay logs are noisy enough already. Flip to
    # True via env var when debugging a slow query.
    made = create_async_engine(
        url,
        echo=os.environ.get("DB_ECHO") == "1",
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        future=True,
        **(_POOL_ARGS if pooled else {}),
    )
    if url.startswith("sqlite"):
        event.listen(made.sync_engine, "connect", _set_sqlite_pragmas)
    return made


engine: AsyncEngine = _make_engine(DATABASE_URL, _pooled)

async_session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False,   # rows stay usable after .commit() — fewer .refresh() calls
    class_=AsyncSession,
)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Context-managed AsyncSession. Auto-commits on success, rolls back on
    exception. Use this from FastAPI route handlers + background tasks.

    Example:
        async with get_session() as s:
            s.add(Account(id="...", nickname="..."))
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Indexes a model no longer declares because a wider one replaced them under a
# new name: {retired: (table, replacement)}. init_db drops each only once its
# replacement exists, so a failed CREATE never leaves the table without both.
_RETIRED_INDEXES = {
    "ix_messages_account_fan_time": ("messages", "ix_messages_chat_seq"),  # W5 5.1
}


def _drop_retired_indexes(sync_engine) -> None:
    """Drop each `_RETIRED_INDEXES` entry whose replacement is live."""
    import logging
    from sqlalchemy import inspect, text

    inspector = inspect(sync_engine)
    for retired, (table, replacement) in _RETIRED_INDEXES.items():
        if not inspector.has_table(table):
            continue
        live = {ix["name"] for ix in inspector.get_indexes(table)}
        if retired not in live:
            continue
        if replacement not in live:
            logging.getLogger("of-relay.engine").warning(
                "keeping retired index %s: replacement %s missing", retired, replacement)
            continue
        try:
            with sync_engine.begin() as conn:
                conn.execute(text(f"DROP INDEX IF EXISTS {retired}"))
        except Exception:
            logging.getLogger("of-relay.engine").exception(
                "failed to drop retired index %s", retired)


def merge_ppv_exclude_into_dm(sync_engine) -> list[dict]:
    """Fold each account's local MASSppvEXCLUDE list into its MASSdmEXCLUDE list
    (merged 2026-10-21: one list now excludes a fan from every mass send). Copies
    the PPV members onto the DM list (INSERT OR IGNORE, minting the DM row if the
    account has none), then deletes the PPV members and the PPV row, in one
    transaction per account. Local only: the OnlyFans-side MASSppvEXCLUDE lists
    are left alone. Idempotent — a no-op once no PPV row remains. SQLite SQL.
    Returns one {account_id, ppv_members, copied} per merged account."""
    import logging
    from sqlalchemy import text

    out: list[dict] = []
    with sync_engine.connect() as conn:
        ppv_rows = conn.execute(text(
            "SELECT id, account_id FROM lists "
            "WHERE kind='exclude' AND name='MASSppvEXCLUDE' ORDER BY id")).all()
    for ppv_id, account_id in ppv_rows:
        with sync_engine.begin() as conn:
            dm_id = conn.execute(text(
                "SELECT id FROM lists WHERE account_id=:a AND kind='exclude' "
                "AND name='MASSdmEXCLUDE' ORDER BY id LIMIT 1"), {"a": account_id}).scalar()
            if dm_id is None:
                dm_id = conn.execute(text(
                    "INSERT INTO lists (account_id, name, kind, is_system, of_list_id) "
                    "VALUES (:a, 'MASSdmEXCLUDE', 'exclude', 1, NULL)"),
                    {"a": account_id}).lastrowid
            members = conn.execute(text(
                "SELECT COUNT(*) FROM list_members WHERE list_id=:p"), {"p": ppv_id}).scalar()
            copied = conn.execute(text(
                "INSERT OR IGNORE INTO list_members (list_id, fan_id, added_at, added_by_employee_id) "
                "SELECT :d, fan_id, added_at, added_by_employee_id FROM list_members "
                "WHERE list_id=:p"), {"d": dm_id, "p": ppv_id}).rowcount
            conn.execute(text("DELETE FROM list_members WHERE list_id=:p"), {"p": ppv_id})
            conn.execute(text("DELETE FROM lists WHERE id=:p"), {"p": ppv_id})
        out.append({"account_id": account_id, "ppv_members": int(members or 0),
                    "copied": int(copied or 0)})
        logging.getLogger("of-relay.engine").info(
            "mass-exclude merge: account=%s MASSppvEXCLUDE (%s members) folded into "
            "MASSdmEXCLUDE, %s new there", account_id, members, copied)
    return out


# Rows ANALYZE samples per index. Without a limit, the first ANALYZE of a
# table scans all of it — seconds on the big ones (messages, event_inbox) while
# holding a read transaction; 400 is SQLite's own suggested value for optimize.
_ANALYSIS_LIMIT = 400


async def optimize() -> None:
    """Refresh planner statistics for tables whose row counts moved. SQLite's
    advice for long-lived connections: run `PRAGMA optimize` periodically, not
    only on open — the pool's connections stay open between sessions (see
    `_POOL_ARGS`), and this runs on whichever one is checked out. Cheap when
    nothing changed. No-op off SQLite."""
    if not _is_sqlite:
        return
    from sqlalchemy import text
    async with engine.connect() as conn:
        await conn.execute(text(f"PRAGMA analysis_limit={_ANALYSIS_LIMIT}"))
        await conn.execute(text("PRAGMA optimize"))


async def init_db() -> None:
    """Apply migrations + set SQLite pragmas. Called from the FastAPI
    startup hook. Idempotent.

    Strategy:
      1. SQLite PRAGMAs are wired at engine creation (`_set_sqlite_pragmas`).
      2. If `alembic_version` table doesn't exist yet (fresh box), call
         `Base.metadata.create_all()` directly and stamp Alembic to the
         initial revision. We skip `alembic upgrade head` here because
         Alembic+SQLAlchemy 2.0.35+Python 3.13 hits a recursion bug on
         this schema's first run. The diffs in subsequent migrations are
         small enough that the bug doesn't trip.
      3. If `alembic_version` already exists, do the ADDITIVE catch-up below
         (create_all for new tables + ALTER TABLE ADD COLUMN for new nullable
         columns). ⚠️ We do NOT run `alembic upgrade head` — there is no
         `command.upgrade(...)` call anywhere in this service. Any schema
         change that is not additive-and-nullable simply never lands.

    On Postgres the same flow works; the recursion bug is Python-version
    sensitive and we keep the same code path for symmetry.
    """
    # Detect whether the DB has ever been initialized + create-if-missing.
    # We intentionally do NOT run `alembic upgrade head` here — Alembic in
    # 1.13.3 has a behavioral quirk with our env.py on Python 3.13 where
    # re-entering the upgrade flow on an already-current DB loops in the
    # migration-context logger. Since phase A has exactly one migration
    # (the initial schema), there's nothing to upgrade once the DB exists.
    # When we add a second migration in phase D, this function gets a
    # version-comparison branch that calls `command.upgrade(...)` only
    # when the on-disk revision != head.
    from sqlalchemy import create_engine, inspect, text

    sync_url = DATABASE_URL.replace("+aiosqlite", "").replace("+asyncpg", "")
    sync_engine = create_engine(sync_url, connect_args={"timeout": 30} if _is_sqlite else {})
    try:
        # PRAGMAs the async engine sets per-connection (above) need to also
        # land on the sync_engine we use here for create_all() / stamp, so
        # the DB file gets WAL mode set at creation time (persistent on disk).
        if _is_sqlite:
            with sync_engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA journal_mode=WAL")
                conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                conn.commit()

        inspector = inspect(sync_engine)
        has_alembic = "alembic_version" in inspector.get_table_names()

        if not has_alembic:
            from .models import Base
            Base.metadata.create_all(bind=sync_engine)
            with sync_engine.begin() as conn:
                conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS alembic_version "
                    "(version_num VARCHAR(32) PRIMARY KEY)"
                ))
                conn.execute(text("DELETE FROM alembic_version"))
                conn.execute(text(
                    "INSERT INTO alembic_version (version_num) VALUES ('0001_initial')"
                ))
        else:
            # Cheap idempotent catch-up for additive schema changes: any new
            # tables defined in models.py that aren't in the DB yet get
            # created. Full Alembic upgrade lands in phase D — until then
            # this covers the saved_replies / future additive cases without
            # making the user wipe their DB.
            from .models import Base
            Base.metadata.create_all(bind=sync_engine)
            # Additive-column catch-up. `create_all()` doesn't ALTER existing
            # tables, so columns added to a model after the table existed
            # would cause SELECTs to 500 ("no such column"). Walk the model
            # metadata against the live DB and ALTER TABLE for missing cols.
            # Only safe for ADDITIVE changes with a default / nullable spec
            # — destructive ALTERs still need Alembic.
            inspector = inspect(sync_engine)
            for table_name, table_obj in Base.metadata.tables.items():
                if table_name not in inspector.get_table_names():
                    continue
                live_cols = {c["name"] for c in inspector.get_columns(table_name)}
                with sync_engine.begin() as conn:
                    for col in table_obj.columns:
                        if col.name in live_cols:
                            continue
                        # Build a minimal ADD COLUMN clause. Only NULLABLE
                        # columns or columns with a server_default are safe
                        # to add online without a default value; skip
                        # anything that would require a non-null backfill.
                        if not col.nullable and col.server_default is None:
                            continue
                        col_type = col.type.compile(dialect=sync_engine.dialect)
                        default_clause = ""
                        if col.server_default is not None:
                            sd = col.server_default
                            sd_text = getattr(sd, "arg", None)
                            if sd_text is not None:
                                default_clause = f" DEFAULT {sd_text}"
                        null_clause = "" if col.nullable else " NOT NULL"
                        conn.execute(text(
                            f"ALTER TABLE {table_name} "
                            f"ADD COLUMN {col.name} {col_type}{default_clause}{null_clause}"
                        ))

            # Additive-INDEX catch-up. `create_all()` adds indexes for
            # newly-created tables but does NOT retroactively add new
            # indexes declared in `__table_args__` on tables that
            # already existed (verified behavior on SQLAlchemy 2.0.x —
            # `create_all` skips the table entirely when present). So
            # we walk every model-side Index and CREATE IF NOT EXISTS
            # via raw SQL using the dialect compiler. Without this, the
            # chatter→employee resolver's race-safety (which depends on
            # the partial unique index uq_employees_chatter_owner)
            # silently degrades on boxes that came up via init_db()
            # before the index was declared.
            from sqlalchemy.schema import CreateIndex
            import logging as _logging
            _log = _logging.getLogger("of-relay.engine")
            inspector = inspect(sync_engine)
            for table_name, table_obj in Base.metadata.tables.items():
                if table_name not in inspector.get_table_names():
                    continue
                live_index_names = {ix["name"] for ix in inspector.get_indexes(table_name)}
                for ix in table_obj.indexes:
                    if ix.name in live_index_names:
                        continue
                    try:
                        with sync_engine.begin() as conn:
                            # CreateIndex emits the dialect-correct DDL
                            # including partial-index WHERE clauses (we
                            # use these for uq_employees_chatter_owner).
                            conn.execute(CreateIndex(ix, if_not_exists=True))
                        _log.info("created missing index %s on %s", ix.name, table_name)
                    except Exception:
                        _log.exception(
                            "failed to create missing index %s on %s",
                            ix.name, table_name,
                        )
            # An index widened under a new name leaves its old one behind
            # (the catch-up above adds by name only): drop the old.
            _drop_retired_indexes(sync_engine)

            # One-way DATA catch-up (10-21 exclude merge): MASSppvEXCLUDE folded
            # into MASSdmEXCLUDE. Idempotent; a no-op once no PPV row is left.
            if _is_sqlite:
                try:
                    merge_ppv_exclude_into_dm(sync_engine)
                except Exception:
                    _log.exception("MASSppvEXCLUDE → MASSdmEXCLUDE merge failed")

        # Both branches: create_all builds no views, and nothing here runs
        # alembic, so the attribution view would otherwise exist only on a box
        # someone upgraded by hand.
        if _is_sqlite:
            try:
                ensure_attribution_view(sync_engine)
            except Exception:
                import logging as _logging
                _logging.getLogger("of-relay.engine").exception(
                    "attribution view catch-up failed")

        try:
            with sync_engine.begin() as conn:
                move_versioned_settings(conn)
        except Exception:
            import logging as _logging
            _logging.getLogger("of-relay.engine").exception("settings versions move failed")

        # Fresh box too: it stamps the marker, so the backfill never runs later.
        try:
            backfill_w7_rules_once(sync_engine)
        except Exception:
            import logging as _logging
            _logging.getLogger("of-relay.engine").exception("w7 rule backfill failed")

        # Planner statistics, once per boot after the schema catch-up. Without
        # them (no sqlite_stat1 existed on any DB we checked) the planner guesses
        # between our 160+ indexes. 0x10002 = analyze every table whose stats are
        # missing or stale; the analysis_limit keeps a first run on a big table
        # to a sample. The periodic pass is server._db_optimize_loop (optimize()).
        if _is_sqlite:
            try:
                with sync_engine.connect() as conn:
                    conn.exec_driver_sql(f"PRAGMA analysis_limit={_ANALYSIS_LIMIT}")
                    conn.exec_driver_sql("PRAGMA optimize=0x10002")
                    conn.commit()
            except Exception:
                import logging as _logging
                _logging.getLogger("of-relay.engine").exception("PRAGMA optimize at boot failed")

        # Last, so its failure skips no step above: the credit columns and the
        # rollups are kept by triggers, which create_all does not build either
        # (both branches, like the view). A failure does not stop the boot
        # (chat and SSE matter more than the stats); it is retried in the
        # background until it succeeds (`_tx_rollup_retry`).
        if _is_sqlite and not _tx_rollup_catch_up(sync_engine):
            import asyncio
            task = asyncio.get_running_loop().create_task(_tx_rollup_retry(sync_url), name="tx-rollup-retry")
            _retry_tasks.add(task)
            task.add_done_callback(_retry_tasks.discard)
    finally:
        sync_engine.dispose()


_retry_tasks: set = set()  # a reference held, so the retry task is not collected
TX_ROLLUP_RETRY_S = (60, 900)  # first delay, cap (doubling between)


def _tx_rollup_catch_up(sync_engine) -> bool:
    """`tx_rollup.ensure` (triggers, then the once-per-box backfill); False,
    logged critical, when it fails. Until it succeeds the stats read
    whatever the rollups held, so they can read low."""
    import logging as _logging

    import tx_rollup
    try:
        tx_rollup.ensure(sync_engine)
        return True
    except Exception:
        _logging.getLogger("of-relay.engine").critical(
            "TX ROLLUP CATCH-UP FAILED: sale credit and the stats rollups may be "
            "incomplete; retrying in the background", exc_info=True)
        return False


async def _tx_rollup_retry(sync_url: str) -> None:
    """`_tx_rollup_catch_up` on its own engine, off the event loop, every
    TX_ROLLUP_RETRY_S[0] seconds doubling to TX_ROLLUP_RETRY_S[1], until it
    succeeds."""
    import asyncio

    from sqlalchemy import create_engine

    delay, cap = TX_ROLLUP_RETRY_S
    while True:
        await asyncio.sleep(delay)
        eng = create_engine(sync_url, connect_args={"timeout": 30})
        try:
            if await asyncio.to_thread(_tx_rollup_catch_up, eng):
                return
        finally:
            eng.dispose()
        delay = min(delay * 2, cap)


_ATTR_VIEW = "per_employee_revenue_with_attribution"
# The view's current revision; its SQL is read from the migration so there is
# one definition, not a second copy here.
_ATTR_VIEW_MIGRATION = "20261016_0300_attr_view_sales_records.py"
# Columns only the current revision has: a view without them is an older one.
_ATTR_VIEW_HEAD_COLS = {"tx_id", "rule"}


def ensure_attribution_view(sync_engine) -> str:
    """Create `per_employee_revenue_with_attribution` when it is missing, or
    rebuild it when it predates revision 0069 (no `tx_id`/`rule`). Stats and
    Sales records read it, and without it they 500 with "no such table". A pure
    view rebuild: no stored row changes. Returns "present" | "created" |
    "rebuilt"."""
    import importlib.util

    from sqlalchemy import inspect, text

    insp = inspect(sync_engine)
    action = "created"
    if _ATTR_VIEW in insp.get_view_names():
        cols = {c["name"] for c in insp.get_columns(_ATTR_VIEW)}
        if _ATTR_VIEW_HEAD_COLS <= cols:
            return "present"
        action = "rebuilt"
    path = HERE / "migrations" / "versions" / _ATTR_VIEW_MIGRATION
    spec = importlib.util.spec_from_file_location("_attr_view_head", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    with sync_engine.begin() as conn:
        conn.execute(text(f"DROP VIEW IF EXISTS {_ATTR_VIEW}"))
        conn.execute(text(mig._NEW_VIEW_SQL))
    import logging as _logging
    _logging.getLogger("of-relay.engine").info("attribution view %s", action)
    return action


# One-shot data steps, by name. A row here = that step already ran on this box
# (so it never re-runs — e.g. never re-creates a rule an operator later deleted).
_DATA_MIGRATIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS data_migrations "
    "(name VARCHAR(64) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
)
_W7_RULE_BACKFILL = "20261018_w7_rule_switch"
# kind → rule name for the backfilled switch.
_W7_RULE_KINDS = {
    "welcome_chatter_for_info": "Get to know fans (Reply Instant)",
    "reply_mass_funnel": "Walk mass-funnel replies (Reply Instant)",
}


def ensure_w7_rule_switches(conn, account_id: str) -> int:
    """For each W7-gated kind (welcome_chatter_for_info, reply_mass_funnel) the
    account has NO rule row of (any state, any legacy name), create an enabled
    cadence-less one (trigger `{}`: the materializer skips it, so it is purely
    the Reply Instant switch — no periodic sweep). Existing rows are never
    touched: a disabled one stays off. `conn` is a sync Connection in the
    caller's transaction. Used by the one-time backfill below (the
    webhook-config PUT that also called it is retired). Returns rules created."""
    from datetime import datetime
    from sqlalchemy import text
    from automation_registry import kind_family

    created = 0
    for kind, name in _W7_RULE_KINDS.items():
        fam = kind_family(kind)
        marks = ", ".join(f":k{i}" for i in range(len(fam)))
        has = conn.execute(text(
            f"SELECT 1 FROM automation_rules WHERE account_id = :a "
            f"AND kind IN ({marks}) LIMIT 1"),
            {"a": account_id, **{f"k{i}": k for i, k in enumerate(fam)}}).first()
        if has is not None:
            continue
        conn.execute(text(
            "INSERT INTO automation_rules "
            "(account_id, name, kind, trigger_json, steps_json, is_enabled, created_at) "
            "VALUES (:a, :n, :k, '{}', '{}', :on, :now)"),
            {"a": account_id, "n": name, "k": kind, "on": True,
             "now": datetime.utcnow()})
        created += 1
    return created


def move_versioned_settings(conn) -> int:
    """Move every `user_settings` blob of a versioned tab (`sales`,
    `time-tracking`; roadmap W6 6.4) into `settings_versions`: as the first
    version, effective from SETTINGS_EPOCH, when that user and tab have none
    yet, so every past sale and shift reads the settings it read before;
    else as a version from its own `updated_at`, so a blob some older code
    wrote there later (after a rollback) lands as the save it was and never
    rewrites the history before it. Runs on every boot, in the caller's
    transaction (`conn`, a sync connection): once moved, no row is left to
    move, so it needs no marker. Migration 0078 runs the same SQL. Returns
    the rows moved."""
    from sqlalchemy import bindparam, text

    from .models import SETTINGS_EPOCH, VERSIONED_SETTINGS_TABS

    tabs = {"tabs": list(VERSIONED_SETTINGS_TABS)}
    conn.execute(text(
        "INSERT INTO settings_versions (user_id, tab, effective_from, config_json, created_at) "
        "SELECT u.user_id, u.tab, CASE WHEN EXISTS (SELECT 1 FROM settings_versions v "
        "  WHERE v.user_id = u.user_id AND v.tab = u.tab) THEN u.updated_at ELSE :epoch END, "
        "u.config_json, u.updated_at FROM user_settings u WHERE u.tab IN :tabs ORDER BY u.user_id, u.tab"
    ).bindparams(bindparam("tabs", expanding=True)),
        # SQLAlchemy's SQLite DateTime text, as the ORM writes the column.
        {**tabs, "epoch": SETTINGS_EPOCH.strftime("%Y-%m-%d %H:%M:%S.%f")})
    moved = conn.execute(text("DELETE FROM user_settings WHERE tab IN :tabs")
                         .bindparams(bindparam("tabs", expanding=True)), tabs).rowcount
    return moved


def backfill_w7_rules_once(sync_engine) -> int:
    """ONE-TIME (2026-10-18): Reply Instant (webhook_dispatch) now wakes
    welcome_chatter_for_info / reply_mass_funnel only while the account has an
    ENABLED rule of that kind. Accounts that had Reply Instant ON with NO rule
    row of the kind at all (any state) were being answered without one — give
    each such (account, kind) an enabled rule so they keep being answered. An
    existing row, even a disabled one, is left alone (that account stays off).

    Same rule as `ensure_w7_rule_switches` (cadence-less: exactly the replies
    the account was already getting, no new periodic sweep).

    Guarded by a `data_migrations` marker, written in the same transaction.
    Returns the number of rules created."""
    import json
    import logging
    from sqlalchemy import text

    log = logging.getLogger("of-relay.engine")
    created = 0
    with sync_engine.begin() as conn:
        conn.execute(text(_DATA_MIGRATIONS_DDL))
        done = conn.execute(text("SELECT 1 FROM data_migrations WHERE name = :n"),
                            {"n": _W7_RULE_BACKFILL}).first()
        if done is not None:
            return 0
        rows = conn.execute(text(
            "SELECT account_id, webhook_config_json FROM account_ai_config "
            "WHERE webhook_config_json IS NOT NULL")).all()
        for account_id, raw in rows:
            try:
                cfg = json.loads(raw or "{}")
            except Exception:
                continue
            if not (isinstance(cfg, dict) and cfg.get("enabled")):
                continue  # the same truthiness webhook_dispatch._load_config reads
            created += ensure_w7_rule_switches(conn, account_id)
        conn.execute(text("INSERT INTO data_migrations (name) VALUES (:n)"),
                     {"n": _W7_RULE_BACKFILL})
    log.info("w7_rule_backfill created=%d rule(s) for Reply-Instant accounts with no "
             "info-gather / funnel-walker rule", created)
    return created
