from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from time import monotonic

import relay_host

log = logging.getLogger("of-relay")


_RAW_JSON_RETAIN_S = int(os.environ.get("RAW_JSON_RETAIN_S", str(60 * 24 * 60 * 60)))
_RAW_JSON_EVICT_INTERVAL_S = int(os.environ.get("RAW_JSON_EVICT_INTERVAL_S", str(24 * 60 * 60)))

# First pass of a daily sweeper after startup; short enough that a relay restarted twice a day still prunes twice a day.
_EVICT_BOOT_GRACE_S = int(os.environ.get("EVICT_BOOT_GRACE_S", str(5 * 60)))


_RAW_JSON_MAX_BATCH = 500
_RAW_JSON_BATCH = int(os.environ.get("RAW_JSON_BATCH", str(_RAW_JSON_MAX_BATCH)))
_RAW_JSON_BUDGET_S = 60.0


async def _raw_json_sweep() -> None:
    # No index serves this filter: one UPDATE scans every row (3M on AE, ~75 s) under the write lock and every other writer hits busy_timeout. Scan under a WAL read, write in batches.
    from db.engine import get_session
    from sqlalchemy import bindparam, text
    cutoff = _floor_cutoff_str(_RAW_JSON_RETAIN_S)
    scan = text(
        "SELECT rowid FROM messages WHERE rowid > :last AND created_at < :cutoff "
        "AND raw_json IS NOT NULL ORDER BY rowid LIMIT :batch"
    )
    clear = text(
        "UPDATE messages SET raw_json = NULL WHERE rowid IN :ids "
        "AND created_at < :cutoff AND raw_json IS NOT NULL"
    ).bindparams(bindparam("ids", expanding=True))
    last = cleared = 0
    batch = min(_RAW_JSON_MAX_BATCH, max(1, _RAW_JSON_BATCH))
    deadline = monotonic() + _RAW_JSON_BUDGET_S
    while monotonic() < deadline:
        async with get_session() as s:
            ids = (await s.execute(scan, {"last": last, "cutoff": cutoff, "batch": batch})).scalars().all()
        if not ids:
            break
        last = ids[-1]
        async with get_session() as s:
            res = await s.execute(clear, {"ids": ids, "cutoff": cutoff})
            await s.commit()
        cleared += int(res.rowcount or 0)
        if len(ids) < batch:
            break
        await asyncio.sleep(0)
    if cleared:
        log.info("raw_json evictor cleared %d rows (retain=%ds)", cleared, _RAW_JSON_RETAIN_S)


async def _raw_json_evictor_loop() -> None:
    await relay_host.periodic(
        "raw_json evictor", _RAW_JSON_EVICT_INTERVAL_S, _raw_json_sweep,
        first_after_s=_EVICT_BOOT_GRACE_S,
    )


# Row deletes only: prod is auto_vacuum=NONE, so deleted pages go to the freelist and the file never shrinks (_reclaim_freelist no-ops until INCREMENTAL); reclaiming disk needs an offline VACUUM. 0 disables a table.
_AUTOMATION_RUNS_RETAIN_S = int(os.environ.get("AUTOMATION_RUNS_RETAIN_S", str(14 * 24 * 60 * 60)))
_GROK_CALLS_RETAIN_S = int(os.environ.get("GROK_CALLS_RETAIN_S", str(30 * 24 * 60 * 60)))
_SCHEDULED_JOBS_RETAIN_S = int(os.environ.get("SCHEDULED_JOBS_RETAIN_S", str(7 * 24 * 60 * 60)))
_ACTIONS_RETAIN_S = int(os.environ.get("ACTIONS_RETAIN_S", str(90 * 24 * 60 * 60)))
# Only Full AI Chat's Test rows (mode test); shadow/live rows are never swept here.
_FULL_AI_TEST_RETAIN_S = int(os.environ.get("FULL_AI_TEST_RETAIN_S", str(7 * 24 * 60 * 60)))
# Non-test ledger rows are never deleted (ADR-0034), only their bulky JSON NULLed; never a `sending` row nor the newest row of its (account, fan, mode), which the live loader folds. A tease-priced row keeps `{"chat_tease": {"cents": N}}` (full_ai_test.is_tease, teases_sent_of).
_FULL_AI_JSON_RETAIN_S = int(os.environ.get("FULL_AI_JSON_RETAIN_S", str(90 * 24 * 60 * 60)))
_FULL_AI_JSON_BATCH = int(os.environ.get("FULL_AI_JSON_BATCH", "2000"))
_TEASE_KEEP = ("CASE WHEN json_valid({c}) AND json_extract({c}, '$.chat_tease.cents') IS NOT NULL"
               " THEN json_object('chat_tease', json_object('cents', json_extract({c}, '$.chat_tease.cents'))) END")
_FULL_AI_JSON_NULL = (
    f"UPDATE ai_decisions SET jev_json = NULL, reply_json = {_TEASE_KEEP.format(c='reply_json')} WHERE id IN ("
    " SELECT d.id FROM ai_decisions d WHERE d.mode != 'test' AND d.created_at < :cutoff"
    f" AND d.status != 'sending' AND (d.jev_json IS NOT NULL OR d.reply_json IS NOT {_TEASE_KEEP.format(c='d.reply_json')})"
    " AND EXISTS (SELECT 1 FROM ai_decisions n WHERE n.account_id = d.account_id AND n.fan_id = d.fan_id"
    " AND n.mode = d.mode AND (n.created_at, n.id) > (d.created_at, d.id))"
    " LIMIT :batch)")
_AUDIT_EVICT_INTERVAL_S = int(os.environ.get("AUDIT_EVICT_INTERVAL_S", str(24 * 60 * 60)))


async def evict_audit_logs_once() -> dict[str, int]:
    from db.engine import get_session
    from db.models import Action, AiDecision, AutomationRun, GrokCall, ScheduledJob
    from sqlalchemy import delete as sa_delete

    now = datetime.utcnow()
    plan = [
        (AutomationRun, AutomationRun.started_at, _AUTOMATION_RUNS_RETAIN_S, None),
        (GrokCall, GrokCall.called_at, _GROK_CALLS_RETAIN_S, None),
        (ScheduledJob, ScheduledJob.created_at, _SCHEDULED_JOBS_RETAIN_S,
         ScheduledJob.status.in_(("done", "error"))),
        (Action, Action.at, _ACTIONS_RETAIN_S, None),
        (AiDecision, AiDecision.created_at, _FULL_AI_TEST_RETAIN_S, AiDecision.mode == "test"),
    ]
    out: dict[str, int] = {}
    for model, col, retain_s, extra in plan:
        if retain_s <= 0:
            continue
        cutoff = now - timedelta(seconds=retain_s)
        stmt = sa_delete(model).where(col < cutoff)
        if extra is not None:
            stmt = stmt.where(extra)
        async with get_session() as s:
            res = await s.execute(stmt)
            await s.commit()
            out[model.__tablename__] = int(res.rowcount or 0)
    if _FULL_AI_JSON_RETAIN_S > 0:
        out["ai_decisions_json"] = await _null_full_ai_json(now - timedelta(seconds=_FULL_AI_JSON_RETAIN_S))
    return out


async def _null_full_ai_json(cutoff: datetime) -> int:
    from db.engine import get_session
    from sqlalchemy import text
    total, batch = 0, max(1, _FULL_AI_JSON_BATCH)
    # SQLAlchemy's SQLite DateTime text, so the bound cutoff compares as the stored column does.
    params = {"cutoff": cutoff.strftime("%Y-%m-%d %H:%M:%S.%f"), "batch": batch}
    while True:
        async with get_session() as s:
            n = int((await s.execute(text(_FULL_AI_JSON_NULL), params)).rowcount or 0)
            await s.commit()
        total += n
        if n < batch:
            return total


async def _audit_retention_sweep() -> None:
    pruned = {k: v for k, v in (await evict_audit_logs_once()).items() if v}
    if pruned:
        log.info("audit-retention evictor pruned %s", pruned)


async def _audit_retention_evictor_loop() -> None:
    await relay_host.periodic(
        "audit-retention evictor", _AUDIT_EVICT_INTERVAL_S, _audit_retention_sweep,
        first_after_s=_EVICT_BOOT_GRACE_S,
    )


_DB_OPTIMIZE_INTERVAL_S = 6 * 60 * 60


async def _db_optimize_loop() -> None:
    from db.engine import optimize as _db_optimize
    await relay_host.periodic("sqlite optimize", _DB_OPTIMIZE_INTERVAL_S, _db_optimize)


# Cap is driven off logical bytes (SUM(LENGTH)), not file size: auto_vacuum is off so the file plateaus. Never deletes messages/fans/transactions rows, nor anything newer than the retention floor.
_PAYLOAD_BUDGET_BYTES = int(os.environ.get("PAYLOAD_BUDGET_BYTES", str(1_500_000_000)))
_PAYLOAD_RETAIN_FLOOR_S = int(os.environ.get("EVENT_INBOX_RETAIN_FLOOR_S", str(2 * 24 * 60 * 60)))
_PAYLOAD_CAP_INTERVAL_S = int(os.environ.get("PAYLOAD_CAP_INTERVAL_S", str(60 * 60)))
_PAYLOAD_EVICT_BATCH = int(os.environ.get("PAYLOAD_EVICT_BATCH", "2000"))
# Unconditional age cap, every tick: the byte budget never fired while event_inbox accreted 360k rows / 421 MB. 0 = budget-only.
_EVENT_INBOX_MAX_AGE_S = int(os.environ.get("EVENT_INBOX_MAX_AGE_S", str(2 * 24 * 60 * 60)))
# One-time auto_vacuum=INCREMENTAL conversion (heavy full VACUUM): flip on for a single off-peak restart, then unset.
_PAYLOAD_VACUUM_ON_START = os.environ.get("PAYLOAD_VACUUM_ON_START", "0") == "1"
_PAYLOAD_INCR_VACUUM_PAGES = int(os.environ.get("PAYLOAD_INCR_VACUUM_PAGES", "20000"))

# VACUUM/incremental_vacuum are whole-DB write locks: never two at once, never overlapping an eviction pass.
_payload_vacuum_lock = asyncio.Lock()


# Fixed-width string SQLAlchemy stores DateTime in, so a raw `received_at < ?` sorts chronologically.
def _floor_cutoff_str(floor_s: int) -> str:
    return (datetime.utcnow() - timedelta(seconds=floor_s)).strftime("%Y-%m-%d %H:%M:%S.%f")


async def _payload_bytes(conn) -> tuple[int, int]:
    ev = (await conn.exec_driver_sql(
        "SELECT COALESCE(SUM(LENGTH(payload_json)), 0) FROM event_inbox"
    )).scalar() or 0
    rj = (await conn.exec_driver_sql(
        "SELECT COALESCE(SUM(LENGTH(raw_json)), 0) FROM messages"
    )).scalar() or 0
    return int(ev), int(rj)


async def evict_payloads_once(
    *,
    budget_bytes: int | None = None,
    floor_s: int | None = None,
    batch: int | None = None,
) -> dict[str, int]:
    from db.engine import engine, _is_sqlite
    budget = _PAYLOAD_BUDGET_BYTES if budget_bytes is None else budget_bytes
    floor = _PAYLOAD_RETAIN_FLOOR_S if floor_s is None else floor_s
    bsize = _PAYLOAD_EVICT_BATCH if batch is None else batch
    if not _is_sqlite:
        return {"skipped": 1}

    cutoff = _floor_cutoff_str(floor)
    deleted_events = nulled_messages = freed = 0

    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        ev0, rj0 = await _payload_bytes(conn)
        before = ev0 + rj0
        over = before - budget

        if over > 0:
            while freed < over:
                row = (await conn.exec_driver_sql(
                    "SELECT COALESCE(SUM(LENGTH(payload_json)), 0), COUNT(*) FROM "
                    "(SELECT payload_json FROM event_inbox "
                    " WHERE received_at < ? ORDER BY rowid ASC LIMIT ?)",
                    (cutoff, bsize),
                )).first()
                nbytes, cnt = int(row[0] or 0), int(row[1] or 0)
                if cnt == 0:
                    break
                await conn.exec_driver_sql(
                    "DELETE FROM event_inbox WHERE rowid IN "
                    "(SELECT rowid FROM event_inbox WHERE received_at < ? "
                    " ORDER BY rowid ASC LIMIT ?)",
                    (cutoff, bsize),
                )
                deleted_events += cnt
                freed += nbytes
                await asyncio.sleep(0)

            while freed < over:
                row = (await conn.exec_driver_sql(
                    "SELECT COALESCE(SUM(LENGTH(raw_json)), 0), COUNT(*) FROM "
                    "(SELECT raw_json FROM messages "
                    " WHERE raw_json IS NOT NULL AND created_at < ? "
                    " ORDER BY rowid ASC LIMIT ?)",
                    (cutoff, bsize),
                )).first()
                nbytes, cnt = int(row[0] or 0), int(row[1] or 0)
                if cnt == 0:
                    break
                await conn.exec_driver_sql(
                    "UPDATE messages SET raw_json = NULL WHERE rowid IN "
                    "(SELECT rowid FROM messages WHERE raw_json IS NOT NULL "
                    " AND created_at < ? ORDER BY rowid ASC LIMIT ?)",
                    (cutoff, bsize),
                )
                nulled_messages += cnt
                freed += nbytes
                await asyncio.sleep(0)

        ev1, rj1 = await _payload_bytes(conn)

    after = ev1 + rj1
    summary = {
        "before_bytes": before,
        "after_bytes": after,
        "budget_bytes": budget,
        "freed_bytes": freed,
        "deleted_events": deleted_events,
        "nulled_messages": nulled_messages,
        "event_bytes_after": ev1,
        "raw_json_bytes_after": rj1,
        "floor_bound": int(after > budget),
    }
    return summary


async def prune_event_inbox_once(
    *,
    max_age_s: int | None = None,
    batch: int | None = None,
) -> dict[str, int]:
    from db.engine import engine, _is_sqlite
    age = _EVENT_INBOX_MAX_AGE_S if max_age_s is None else max_age_s
    bsize = _PAYLOAD_EVICT_BATCH if batch is None else batch
    if not _is_sqlite or age <= 0:
        return {"deleted_events": 0, "skipped": int(age <= 0)}

    cutoff = _floor_cutoff_str(age)
    deleted = 0
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        while True:
            res = await conn.exec_driver_sql(
                "DELETE FROM event_inbox WHERE rowid IN "
                "(SELECT rowid FROM event_inbox WHERE received_at < ? "
                " ORDER BY rowid ASC LIMIT ?)",
                (cutoff, bsize),
            )
            n = int(res.rowcount or 0)
            deleted += n
            if n < bsize:
                break
            # Yield between batches so the pump's writes get the lock.
            await asyncio.sleep(0)
    return {"deleted_events": deleted, "cutoff": cutoff}


async def _maybe_convert_to_incremental_autovacuum() -> None:
    from db.engine import engine, _is_sqlite
    if not _is_sqlite or not _PAYLOAD_VACUUM_ON_START:
        return
    async with _payload_vacuum_lock:
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                mode = (await conn.exec_driver_sql("PRAGMA auto_vacuum")).scalar()
                if int(mode or 0) == 2:
                    log.info("payload-cap: auto_vacuum already INCREMENTAL")
                    return
                log.warning("payload-cap: converting auto_vacuum→INCREMENTAL via full VACUUM "
                            "(heavy, whole-DB lock) — this runs once")
                await conn.exec_driver_sql("PRAGMA auto_vacuum=INCREMENTAL")
                await conn.exec_driver_sql("VACUUM")
                mode2 = (await conn.exec_driver_sql("PRAGMA auto_vacuum")).scalar()
                log.warning("payload-cap: auto_vacuum now=%s (2=INCREMENTAL)", mode2)
        except Exception:
            log.warning("payload-cap: auto_vacuum conversion failed", exc_info=True)


async def _reclaim_freelist() -> None:
    from db.engine import engine, _is_sqlite
    if not _is_sqlite:
        return
    async with _payload_vacuum_lock:
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                if int((await conn.exec_driver_sql("PRAGMA auto_vacuum")).scalar() or 0) != 2:
                    return
                free0 = int((await conn.exec_driver_sql("PRAGMA freelist_count")).scalar() or 0)
                if free0 <= 0:
                    return
                await conn.exec_driver_sql(f"PRAGMA incremental_vacuum({_PAYLOAD_INCR_VACUUM_PAGES})")
                free1 = int((await conn.exec_driver_sql("PRAGMA freelist_count")).scalar() or 0)
                if free0 != free1:
                    log.info("payload-cap: reclaimed %d freelist pages (%d→%d)",
                             free0 - free1, free0, free1)
        except Exception:
            log.warning("payload-cap: incremental_vacuum failed", exc_info=True)


async def _payload_size_cap_sweep() -> None:
    pruned = await prune_event_inbox_once()
    if pruned.get("deleted_events"):
        log.info("event-inbox prune: deleted %d rows older than %ds",
                 pruned["deleted_events"], _EVENT_INBOX_MAX_AGE_S)
    summary = await evict_payloads_once()
    if summary.get("freed_bytes"):
        log.info(
            "payload-cap: %d→%d MB (budget %d MB) — deleted %d events, "
            "nulled %d raw_json%s",
            summary["before_bytes"] // 1_000_000,
            summary["after_bytes"] // 1_000_000,
            summary["budget_bytes"] // 1_000_000,
            summary["deleted_events"],
            summary["nulled_messages"],
            " (floor-bound)" if summary.get("floor_bound") else "",
        )
    await _reclaim_freelist()


async def _payload_size_cap_loop() -> None:
    await _maybe_convert_to_incremental_autovacuum()
    await relay_host.periodic("payload-cap", _PAYLOAD_CAP_INTERVAL_S, _payload_size_cap_sweep)
