from __future__ import annotations

import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy import exc as sqla_exc
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy.util import queue as sqla_queue

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent / ".env", override=False)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{HERE.parent / 'chatterly.db'}",
)


def sync_database_url(url: str | None = None) -> str:
    return (DATABASE_URL if url is None else url).replace("+aiosqlite", "").replace("+asyncpg", "")

_is_sqlite = DATABASE_URL.startswith("sqlite")

# Bounded pool: unbounded overflow under a request pile-up opened a thread + schema parse per session (measured 200+ connections, p95 1-6 s); SQLite has one writer anyway.
POOL_SIZE = int(os.environ.get("CHATTERLY_DB_POOL_SIZE", "8"))
SPILL_AFTER_S = float(os.environ.get("CHATTERLY_DB_SPILL_AFTER_S", "2.0"))
# Spills are capped: uncapped, a flood spilled 2,856 connections/threads with no plateau.
MAX_SPILL = int(os.environ.get("CHATTERLY_DB_MAX_SPILL", "24"))
WAIT_MAX_S = float(os.environ.get("CHATTERLY_DB_WAIT_MAX_S", "30"))


# Set only in the OF-cache writer task: it spills past the cap, since a timeout there drops inbound OF frames whose SSE already went out.
UNCAPPED: ContextVar[bool] = ContextVar("db_checkout_uncapped", default=False)


class _SpillQueuePool(AsyncAdaptedQueuePool):

    def _do_get(self):
        if self._overflow >= 0:
            try:
                return self._pool.get(True, self._timeout)
            except sqla_queue.Empty:
                pass
            if self._inc_overflow():
                self.spills += 1
            elif UNCAPPED.get():
                with self._overflow_lock:
                    self._overflow += 1
                self.uncapped += 1
            else:
                self.capped += 1
                try:
                    return self._pool.get(True, WAIT_MAX_S)
                except sqla_queue.Empty:
                    pass
                raise sqla_exc.TimeoutError(
                    f"DB pool busy: {self.size()} + {self._max_overflow} spill connections out, "
                    f"waited {self._timeout + WAIT_MAX_S:.0f} s", code="3o7r")
        else:
            try:
                return self._pool.get(False)
            except sqla_queue.Empty:
                pass
            self._inc_overflow()
        try:
            return self._create_connection()
        except BaseException:
            self._dec_overflow()
            raise

    spills = 0
    capped = 0
    uncapped = 0


_POOL_ARGS = {"poolclass": _SpillQueuePool, "pool_size": POOL_SIZE, "max_overflow": MAX_SPILL,
              "pool_timeout": SPILL_AFTER_S}
_pooled = (
    _is_sqlite
    and ":memory:" not in DATABASE_URL
    and "mode=memory" not in DATABASE_URL
    and os.environ.get("CHATTERLY_DB_NULLPOOL") != "1"
)


def _set_sqlite_pragmas(dbapi_conn, _connection_record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA cache_size=-64000")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.execute("PRAGMA mmap_size=268435456")
    cur.execute("PRAGMA temp_store=MEMORY")
    cur.close()


def _make_engine(url: str, pooled: bool) -> AsyncEngine:
    made = create_async_engine(
        url,
        echo=os.environ.get("DB_ECHO") == "1",
        # A failed statement's text carries bound values and the 500 handler stores str(exc): a 2FA seed or key would leak.
        hide_parameters=True,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        future=True,
        **(_POOL_ARGS if pooled else {}),
    )
    if url.startswith("sqlite"):
        event.listen(made.sync_engine, "connect", _set_sqlite_pragmas)
    return made


engine: AsyncEngine = _make_engine(DATABASE_URL, _pooled)
from . import write_telemetry as _write_telemetry  # noqa: E402
_write_telemetry.instrument(engine)

async_session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Drop each only once its replacement exists, so a failed CREATE never leaves the table without both.
_RETIRED_INDEXES = {
    "ix_messages_account_fan_time": ("messages", "ix_messages_chat_seq"),
    "ix_tracking_clicks_link_time": ("tracking_clicks", "ix_tracking_clicks_stats"),
}


def _drop_retired_indexes(sync_engine) -> None:
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


# Without a limit the first ANALYZE of a big table scans all of it under a read transaction; 400 is SQLite's suggested value.
_ANALYSIS_LIMIT = 400


async def optimize() -> None:
    if not _is_sqlite:
        return
    from sqlalchemy import text
    async with engine.connect() as conn:
        await conn.execute(text(f"PRAGMA analysis_limit={_ANALYSIS_LIMIT}"))
        await conn.execute(text("PRAGMA optimize"))


async def init_db() -> None:
    from sqlalchemy import create_engine, inspect, text

    sync_url = sync_database_url()
    sync_engine = create_engine(sync_url, connect_args={"timeout": 30} if _is_sqlite else {})
    try:
        if _is_sqlite:
            with sync_engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA journal_mode=WAL")
                conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                conn.commit()

        inspector = inspect(sync_engine)
        has_alembic = "alembic_version" in inspector.get_table_names()
        added: set[tuple[str, str]] = set()

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
            from .models import Base
            Base.metadata.create_all(bind=sync_engine)
            inspector = inspect(sync_engine)
            # alembic upgrade is never run: only additive nullable (or defaulted) columns and indexes land here; create_all skips existing tables.
            for table_name, table_obj in Base.metadata.tables.items():
                if table_name not in inspector.get_table_names():
                    continue
                live_cols = {c["name"] for c in inspector.get_columns(table_name)}
                with sync_engine.begin() as conn:
                    for col in table_obj.columns:
                        if col.name in live_cols:
                            continue
                        # A NOT NULL column with no default would need a backfill: skipped.
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
                        added.add((table_name, col.name))

            from sqlalchemy.schema import CreateIndex
            import logging as _logging
            _log = _logging.getLogger("of-relay.engine")
            inspector = inspect(sync_engine)
            # A legacy Creator with several Kept campaigns keeps its last ticked one, or the unique index cannot build.
            if "promo_campaigns" in inspector.get_table_names() and "uq_promo_keep_one" not in {
                    ix["name"] for ix in inspector.get_indexes("promo_campaigns")}:
                try:
                    with sync_engine.begin() as conn:
                        n = conn.execute(text(PROMO_KEPT_DEDUPE)).rowcount
                    if n:
                        _log.warning("promo_keep_dedupe: %s duplicate Kept campaign(s) unticked", n)
                except Exception:
                    _log.exception("promo_keep_dedupe failed")
            for table_name, table_obj in Base.metadata.tables.items():
                if table_name not in inspector.get_table_names():
                    continue
                live_index_names = {ix["name"] for ix in inspector.get_indexes(table_name)}
                for ix in table_obj.indexes:
                    if ix.name in live_index_names:
                        continue
                    try:
                        with sync_engine.begin() as conn:
                            conn.execute(CreateIndex(ix, if_not_exists=True))
                        _log.info("created missing index %s on %s", ix.name, table_name)
                    except Exception:
                        _log.exception(
                            "failed to create missing index %s on %s",
                            ix.name, table_name,
                        )
            _drop_retired_indexes(sync_engine)

            try:
                # One-way idempotent DATA catch-up: turns from before assistant_turns.thread_id get a legacy thread.
                from .assistant_threads import backfill_thread_ids
                with sync_engine.begin() as conn:
                    n = backfill_thread_ids(conn)
                if n:
                    _log.info("assistant thread backfill: %s turn(s) given a thread", n)
            except Exception:
                _log.exception("assistant thread backfill failed")

            if _is_sqlite:
                try:
                    # One-way idempotent DATA catch-up: MASSppvEXCLUDE folded into MASSdmEXCLUDE.
                    merge_ppv_exclude_into_dm(sync_engine)
                except Exception:
                    _log.exception("MASSppvEXCLUDE → MASSdmEXCLUDE merge failed")

        # Both branches — one-way DATA catch-up (11-17 Twin OOM): vault_response_cache
        # wiped, vault_items.raw_json listStates cut to the hasMedia entries.
        # Marker-guarded, batched. A fresh (empty) DB only gets the marker, so its
        # second boot keeps the cache its first run filled; a populated DB with no
        # alembic stamp still compacts (W30 F15/F24).
        if _is_sqlite:
            try:
                # One-way DATA catch-up: OF listStates blobs OOM-killed the relay when a large vault opened.
                compact_vault_list_states_once(sync_engine)
            except Exception:
                import logging as _logging
                _logging.getLogger("of-relay.engine").exception("vault listStates compact failed")

        if _is_sqlite:
            try:
                # create_all builds no views and nothing here runs alembic.
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

        try:
            backfill_w7_rules_once(sync_engine)
        except Exception:
            import logging as _logging
            _logging.getLogger("of-relay.engine").exception("w7 rule backfill failed")

        try:
            heal_keep_running_rules_once(sync_engine)
        except Exception:
            import logging as _logging
            _logging.getLogger("of-relay.engine").exception("keep running rules heal failed")

        try:
            backfill_offer_attempt_once(sync_engine, ("ai_decisions", "offer_attempt_at") in added)
        except Exception:
            import logging as _logging
            _logging.getLogger("of-relay.engine").exception("full ai offer attempt backfill failed")

        try:
            scrub_audit_credentials_once(sync_engine)
        except Exception:
            import logging as _logging
            _logging.getLogger("of-relay.engine").exception("audit credential scrub failed")

        if _is_sqlite:
            try:
                with sync_engine.connect() as conn:
                    conn.exec_driver_sql(f"PRAGMA analysis_limit={_ANALYSIS_LIMIT}")
                    # 0x10002 = analyze every table whose stats are missing or stale.
                    conn.exec_driver_sql("PRAGMA optimize=0x10002")
                    conn.commit()
            except Exception:
                import logging as _logging
                _logging.getLogger("of-relay.engine").exception("PRAGMA optimize at boot failed")

        # Last, so its failure skips no step above; a failure does not stop the boot (chat and SSE matter more than stats) and is retried in the background.
        if _is_sqlite and not _tx_rollup_catch_up(sync_engine):
            import asyncio
            task = asyncio.get_running_loop().create_task(_tx_rollup_retry(sync_url), name="tx-rollup-retry")
            _retry_tasks.add(task)
            task.add_done_callback(_retry_tasks.discard)
    finally:
        sync_engine.dispose()


_retry_tasks: set = set()
TX_ROLLUP_RETRY_S = (60, 900)


def _tx_rollup_catch_up(sync_engine) -> bool:
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
_ATTR_VIEW_MIGRATION = "20261027_0100_converters_window.py"
_ATTR_VIEW_HEAD_COLS = {"tx_id", "rule", "converter_id", "converter_at"}


def ensure_attribution_view(sync_engine) -> str:
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


# A row here means that step already ran on this box: it never re-runs (e.g. never re-creates a rule an operator later deleted).
_DATA_MIGRATIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS data_migrations "
    "(name VARCHAR(64) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
)
_W7_RULE_BACKFILL = "20261018_w7_rule_switch"
_W7_RULE_KINDS = {
    "welcome_chatter_for_info": "Get to know fans (Reply Instant)",
    "reply_mass_funnel": "Walk mass-funnel replies (Reply Instant)",
}


def ensure_w7_rule_switches(conn, account_id: str) -> int:
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


# A blob written later by older code (after a rollback) lands as a version from its own updated_at, never rewriting earlier history.
def move_versioned_settings(conn) -> int:
    from sqlalchemy import bindparam, text

    from .models import SETTINGS_EPOCH, VERSIONED_SETTINGS_TABS

    tabs = {"tabs": list(VERSIONED_SETTINGS_TABS)}
    conn.execute(text(
        "INSERT INTO settings_versions (user_id, tab, effective_from, config_json, created_at) "
        "SELECT u.user_id, u.tab, CASE WHEN EXISTS (SELECT 1 FROM settings_versions v "
        "  WHERE v.user_id = u.user_id AND v.tab = u.tab) THEN u.updated_at ELSE :epoch END, "
        "u.config_json, u.updated_at FROM user_settings u WHERE u.tab IN :tabs ORDER BY u.user_id, u.tab"
    ).bindparams(bindparam("tabs", expanding=True)),
        {**tabs, "epoch": SETTINGS_EPOCH.strftime("%Y-%m-%d %H:%M:%S.%f")})
    moved = conn.execute(text("DELETE FROM user_settings WHERE tab IN :tabs")
                         .bindparams(bindparam("tabs", expanding=True)), tabs).rowcount
    return moved


def backfill_w7_rules_once(sync_engine) -> int:
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
                continue
            created += ensure_w7_rule_switches(conn, account_id)
        conn.execute(text("INSERT INTO data_migrations (name) VALUES (:n)"),
                     {"n": _W7_RULE_BACKFILL})
    log.info("w7_rule_backfill created=%d rule(s) for Reply-Instant accounts with no "
             "info-gather / funnel-walker rule", created)
    return created


_KEEP_RULES_HEAL = "20261121_keep_running_rules_heal"
_KEEP_RULES_HEAL_MIGRATION = "20261121_0100_keep_running_rules_heal.py"


def _data_step_once(sync_engine, marker: str, migration: str, step: str, done: str, run: bool = True) -> int:
    import importlib.util
    import logging
    from sqlalchemy import text

    with sync_engine.begin() as conn:
        conn.execute(text(_DATA_MIGRATIONS_DDL))
        if conn.execute(text("SELECT 1 FROM data_migrations WHERE name = :n"), {"n": marker}).first() is not None:
            return 0
        n = 0
        if run:
            spec = importlib.util.spec_from_file_location(
                "_data_step_" + step, HERE / "migrations" / "versions" / migration)
            mig = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mig)
            n = getattr(mig, step)(conn)
        conn.execute(text("INSERT INTO data_migrations (name) VALUES (:n)"), {"n": marker})
    logging.getLogger("of-relay.engine").info(done, n)
    return n


def heal_keep_running_rules_once(sync_engine) -> int:
    return _data_step_once(sync_engine, _KEEP_RULES_HEAL, _KEEP_RULES_HEAL_MIGRATION, "heal",
                           "keep running rules heal: %d rule(s) created or fixed")


_OFFER_ATTEMPT_BACKFILL = "20261122_full_ai_offer_attempt"
_OFFER_ATTEMPT_MIGRATION = "20261122_0100_ai_decisions_offer_attempt.py"


# Only the boot whose column catch-up added the column stamps rows: a DB that already had it holds no legacy row.
def backfill_offer_attempt_once(sync_engine, column_added: bool) -> int:
    return _data_step_once(sync_engine, _OFFER_ATTEMPT_BACKFILL, _OFFER_ATTEMPT_MIGRATION, "backfill",
                           "full ai offer attempt backfill: %d row(s) stamped", run=column_added)


_AUDIT_CREDENTIAL_SCRUB = "20261122_audit_credential_scrub"
_AUDIT_CREDENTIAL_SCRUB_MIGRATION = "20261122_0400_audit_credential_scrub.py"


def scrub_audit_credentials_once(sync_engine) -> int:
    return _data_step_once(sync_engine, _AUDIT_CREDENTIAL_SCRUB, _AUDIT_CREDENTIAL_SCRUB_MIGRATION, "scrub",
                           "audit credential scrub: %d row(s) scrubbed")


_VAULT_LIST_STATES_COMPACT = "20261117_vault_list_states_compact"
_VAULT_COMPACT_BATCH = 200  # measured peak RSS (~111 KB rows): +160 MB at 100, +235 at 200, +290 at 500


# Batched per transaction (a kill mid-way keeps finished batches); writes raw_json only, so no derived column or updated_at moves.
def compact_vault_list_states_once(sync_engine, batch: int = _VAULT_COMPACT_BATCH) -> int:
    import json
    import logging
    from sqlalchemy import inspect, text
    from vault_mirror import compact_list_states

    log = logging.getLogger("of-relay.engine")
    with sync_engine.begin() as conn:
        conn.execute(text(_DATA_MIGRATIONS_DDL))
        if conn.execute(text("SELECT 1 FROM data_migrations WHERE name = :n"),
                        {"n": _VAULT_LIST_STATES_COMPACT}).first() is not None:
            return 0
        tables = set(inspect(conn).get_table_names())
        if "vault_response_cache" in tables:
            wiped = conn.execute(text("DELETE FROM vault_response_cache")).rowcount or 0
            log.info("vault listStates compact: %d cached vault response(s) dropped", wiped)
        has_table = "vault_items" in tables
    changed, last = 0, 0
    while has_table:
        with sync_engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT rowid, raw_json FROM vault_items WHERE rowid > :r "
                "AND raw_json IS NOT NULL ORDER BY rowid LIMIT :n"),
                {"r": last, "n": batch}).all()
            if not rows:
                break
            last = rows[-1][0]
            for rid, raw in rows:
                try:
                    m = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(m, dict):
                    continue
                new = compact_list_states(m)
                if new is m:
                    continue
                conn.execute(text("UPDATE vault_items SET raw_json = :j WHERE rowid = :r"),
                             {"j": json.dumps(new, ensure_ascii=False, default=str), "r": rid})
                changed += 1
    with sync_engine.begin() as conn:
        conn.execute(text("INSERT OR IGNORE INTO data_migrations (name) VALUES (:n)"),
                     {"n": _VAULT_LIST_STATES_COMPACT})
    log.info("vault listStates compact: %d row(s) rewritten", changed)
    return changed


PROMO_KEPT_DEDUPE = (
    "UPDATE promo_campaigns SET auto_reactivate = 0, keep_warning = 'kept_duplicate', "
    "keep_warning_at = CURRENT_TIMESTAMP WHERE auto_reactivate = 1 AND id <> ("
    "SELECT k.id FROM promo_campaigns k WHERE k.account_id = promo_campaigns.account_id "
    "AND k.auto_reactivate = 1 ORDER BY COALESCE(k.keep_ticked_at, k.created_at) DESC, k.id DESC LIMIT 1)")
