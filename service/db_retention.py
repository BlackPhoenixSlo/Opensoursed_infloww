"""DB retention loops: raw_json, audit/log tables, sqlite optimize, payload size
cap; started by server.py startup; no routes.

`server._periodic` is reached through relay_host at call time, never `from server import`.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta

import relay_host

log = logging.getLogger("of-relay")


# ── messages.raw_json retention ───────────────────────────────────────
#
# `raw_json` stores the full OF message payload per row (avg ~8 KB, mostly
# the media[] array nobody reads back — it's only a migration safety-net).
# Left unbounded it grew the DB to ~1.9 GB. We keep a recent window so a
# future backfill still has fresh payloads to read, and NULL anything older.
#
# This is a NULL-out, not a row delete — message rows stay intact, only the
# heavy column is cleared. auto_vacuum is off, so freed pages return to the
# freelist and are reused by new inserts; the file plateaus rather than
# growing. To actually shrink the file on disk, run VACUUM manually.
_RAW_JSON_RETAIN_S = int(os.environ.get("RAW_JSON_RETAIN_S", str(60 * 24 * 60 * 60)))
_RAW_JSON_EVICT_INTERVAL_S = int(os.environ.get("RAW_JSON_EVICT_INTERVAL_S", str(24 * 60 * 60)))

# How long after startup a DAILY sweeper takes its first pass (see `server._periodic`
# for why the daily ones need one at all). Long enough to stay out of startup's
# way — index creation, the pumps connecting, the first ingest walk — and short
# enough that a relay restarted twice a day still prunes twice a day. A restart
# loop therefore re-sweeps, which is harmless: after the first pass these
# deletes match nothing and cost only their scan.
_EVICT_BOOT_GRACE_S = int(os.environ.get("EVICT_BOOT_GRACE_S", str(5 * 60)))


async def _raw_json_sweep() -> None:
    from db.engine import get_session
    from db.models import Message
    from sqlalchemy import update as sa_update
    cutoff = datetime.utcnow() - timedelta(seconds=_RAW_JSON_RETAIN_S)
    async with get_session() as s:
        res = await s.execute(
            sa_update(Message)
            .where(Message.created_at < cutoff, Message.raw_json.isnot(None))
            .values(raw_json=None)
        )
        await s.commit()
        if (res.rowcount or 0) > 0:
            log.info("raw_json evictor cleared %d rows (retain=%ds)", res.rowcount, _RAW_JSON_RETAIN_S)


async def _raw_json_evictor_loop() -> None:
    """Periodic NULL-out of messages.raw_json older than _RAW_JSON_RETAIN_S.
    Caps DB growth (the payloads are a write-only migration buffer). Runs
    daily by default; tune via RAW_JSON_RETAIN_S / RAW_JSON_EVICT_INTERVAL_S."""
    await relay_host.periodic(
        "raw_json evictor", _RAW_JSON_EVICT_INTERVAL_S, _raw_json_sweep,
        # Daily interval, sub-daily uptime — see server._periodic. 3,668 rows were
        # still holding payloads past a 60-day window when this was measured.
        first_after_s=_EVICT_BOOT_GRACE_S,
    )


# ── audit / log table retention ──────────────────────────────────────
#
# Four append-only tables had NO prune and grew unbounded — so the DB crept
# back toward bloat from the audit side even after the raw-payload columns were
# capped. Each gets a retention window; one daily sweep DELETEs rows past it.
# These are ROW-deletes only. ⚠️ Prod is auto_vacuum=NONE (measured 2026-08-04:
# `PRAGMA auto_vacuum` → 0, freelist 97782 pages), so deleted pages go to the
# freelist and the FILE NEVER SHRINKS — `_reclaim_freelist()` early-returns
# until the DB is converted to INCREMENTAL. This comment previously claimed the
# opposite, which is precisely why grok_calls was allowed to reach 1.3 GB while
# looking self-healing. Reclaiming disk needs a deliberate offline VACUUM.
# Set any window to 0 to disable that table.
_AUTOMATION_RUNS_RETAIN_S = int(os.environ.get("AUTOMATION_RUNS_RETAIN_S", str(14 * 24 * 60 * 60)))
_GROK_CALLS_RETAIN_S = int(os.environ.get("GROK_CALLS_RETAIN_S", str(30 * 24 * 60 * 60)))
_SCHEDULED_JOBS_RETAIN_S = int(os.environ.get("SCHEDULED_JOBS_RETAIN_S", str(7 * 24 * 60 * 60)))
_ACTIONS_RETAIN_S = int(os.environ.get("ACTIONS_RETAIN_S", str(90 * 24 * 60 * 60)))
# Full AI Chat's Test chat rows (`ai_decisions` mode test): the owner's own scratch Turns, 7 days
# (spec phase-03a › Retention). Shadow and later live rows are never swept here.
_FULL_AI_TEST_RETAIN_S = int(os.environ.get("FULL_AI_TEST_RETAIN_S", str(7 * 24 * 60 * 60)))
_AUDIT_EVICT_INTERVAL_S = int(os.environ.get("AUDIT_EVICT_INTERVAL_S", str(24 * 60 * 60)))


async def evict_audit_logs_once() -> dict[str, int]:
    """One retention sweep of the append-only audit/log tables that otherwise
    grow unbounded: automation_runs (run audit), grok_calls (LLM-call audit),
    scheduled_jobs (only the TERMINAL done/error rows), actions (mutation audit),
    ai_decisions (only Full AI Chat's Test chat rows, mode test). Deletes rows older than each table's own window. grok_daily_cost (the cap
    rollup) is a SEPARATE, tiny, un-pruned table, so spend/cap history survives
    the grok_calls per-call prune. Returns {tablename: deleted_count}."""
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
    return out


async def _audit_retention_sweep() -> None:
    pruned = {k: v for k, v in (await evict_audit_logs_once()).items() if v}
    if pruned:
        log.info("audit-retention evictor pruned %s", pruned)


async def _audit_retention_evictor_loop() -> None:
    """Daily retention sweep of the unbounded audit/log tables. Tune each window
    via AUTOMATION_RUNS_RETAIN_S / GROK_CALLS_RETAIN_S / SCHEDULED_JOBS_RETAIN_S
    / ACTIONS_RETAIN_S / FULL_AI_TEST_RETAIN_S (0 disables a table). See evict_audit_logs_once.

    Sweeps after a boot grace rather than after a full day — this loop's own
    interval used to exceed the process's typical uptime, so it had never run.
    See server._periodic for the measurements. The delete is one statement per table on
    purpose: measured on a snapshot of the live DB, the two big ones clear 137k
    and 133k rows in 798ms and 931ms, so the write lock is held for about a
    second, once a day. Batching that would be machinery bought against a cost
    nobody is paying."""
    await relay_host.periodic(
        "audit-retention evictor", _AUDIT_EVICT_INTERVAL_S, _audit_retention_sweep,
        first_after_s=_EVICT_BOOT_GRACE_S,
    )


# SQLite's advice for long-lived connections: `PRAGMA optimize` every few hours
# (init_db runs it once at boot). Refreshes planner stats only for tables whose
# row counts moved, sampled (analysis_limit), so a pass is milliseconds.
_DB_OPTIMIZE_INTERVAL_S = 6 * 60 * 60


async def _db_optimize_loop() -> None:
    from db.engine import optimize as _db_optimize
    await relay_host.periodic("sqlite optimize", _DB_OPTIMIZE_INTERVAL_S, _db_optimize)


# ── raw-OF-payload SIZE cap (event_inbox + messages.raw_json) ─────────
#
# Two columns hoard raw OnlyFans payloads we receive but read back only for
# a short window:
#   • event_inbox.payload_json — the raw WS/SSE event firehose. Every event
#     is already transcoded into permanent tables (DMs → messages, subs →
#     fans, tips → transactions); the envelope is re-read ONLY for SSE
#     Last-Event-ID reconnect replay (minutes–hours) and provider_event_id
#     idempotency. It was NEVER pruned → the real leak.
#   • messages.raw_json — the full OF message JSON (mostly the media[] array
#     nobody reads back). The real message lives in its own columns. The
#     time-based _raw_json_evictor_loop (60d) already trims it; this size
#     cap is the hard ceiling on top, for when volume — not age — is the
#     problem.
#
# The time-based evictors above bound the trailing window; THIS bounds the
# absolute footprint so the SQLite file stays well under ~2 GB.
#
# Two facts shape the design:
#   1. auto_vacuum is OFF on the prod DB, so DELETE / NULL only moves pages
#      to the freelist — the FILE plateaus at its high-water mark, it does
#      not shrink. So a "if file > 2 GB, delete" cap would never shrink
#      anything. We therefore drive the cap off LOGICAL content bytes
#      (SUM(LENGTH(...))), and reclaim disk separately via incremental_vacuum
#      once the DB has been converted to auto_vacuum=INCREMENTAL (a one-time
#      full VACUUM — gated behind PAYLOAD_VACUUM_ON_START so it only runs on
#      a deliberately-scheduled off-peak restart).
#   2. We must lose ZERO fan data. The cap NEVER deletes messages/fans/
#      transactions ROWS — it deletes spent event_inbox envelopes and NULLs
#      the duplicate raw_json column, and NEVER touches anything newer than
#      the retention floor (the last EVENT_INBOX_RETAIN_FLOOR_S stays intact
#      for debugging + SSE replay).
#
# Default budget 1.5 GB of payload bytes keeps total DB < 2 GB (the rest —
# message columns, fans, txns, indexes — is ~0.4 GB and grows slowly).
_PAYLOAD_BUDGET_BYTES = int(os.environ.get("PAYLOAD_BUDGET_BYTES", str(1_500_000_000)))
_PAYLOAD_RETAIN_FLOOR_S = int(os.environ.get("EVENT_INBOX_RETAIN_FLOOR_S", str(2 * 24 * 60 * 60)))
_PAYLOAD_CAP_INTERVAL_S = int(os.environ.get("PAYLOAD_CAP_INTERVAL_S", str(60 * 60)))
_PAYLOAD_EVICT_BATCH = int(os.environ.get("PAYLOAD_EVICT_BATCH", "2000"))
# Unconditional age cap on the event_inbox landing table — runs EVERY tick,
# independent of the byte budget above. event_inbox is a spent-envelope log:
# the WS transcoder writes the real message/chat/transaction rows synchronously,
# so nothing reads an envelope older than a couple days. The budget-driven cap
# only trims event_inbox once LOGICAL payload exceeds PAYLOAD_BUDGET_BYTES
# (1.5 GB) — which the envelope + raw_json bytes can sit under for a month while
# the table still accretes hundreds of thousands of rows (the exact failure we
# saw: 360k rows / 421 MB with the budget cap never firing). This hard age floor
# holds event_inbox at a fixed ~2-day window no matter what the budget is doing.
# Set to 0 to disable (fall back to budget-only behavior).
_EVENT_INBOX_MAX_AGE_S = int(os.environ.get("EVENT_INBOX_MAX_AGE_S", str(2 * 24 * 60 * 60)))
# One-time conversion of an existing auto_vacuum=NONE DB to INCREMENTAL +
# the heavy full VACUUM that makes it take effect. Off by default; flip on
# for a single off-peak restart (via a deploy), then unset. After conversion,
# incremental_vacuum each tick returns freed pages to the OS for free.
_PAYLOAD_VACUUM_ON_START = os.environ.get("PAYLOAD_VACUUM_ON_START", "0") == "1"
# Pages reclaimed per tick once auto_vacuum=INCREMENTAL. Bounded so each tick
# holds the write lock only briefly (default ~80 MB at 4 KiB pages).
_PAYLOAD_INCR_VACUUM_PAGES = int(os.environ.get("PAYLOAD_INCR_VACUUM_PAGES", "20000"))

# VACUUM / incremental_vacuum are whole-DB write locks; never let two run at
# once, and never overlap a full VACUUM with an eviction pass.
_payload_vacuum_lock = asyncio.Lock()


def _floor_cutoff_str(floor_s: int) -> str:
    """Retention-floor cutoff as the fixed-width string SQLAlchemy stores
    DateTime in ('YYYY-MM-DD HH:MM:SS.ffffff'), so a raw `received_at < ?`
    comparison sorts chronologically. Rows newer than this are never touched."""
    return (datetime.utcnow() - timedelta(seconds=floor_s)).strftime("%Y-%m-%d %H:%M:%S.%f")


async def _payload_bytes(conn) -> tuple[int, int]:
    """(event_inbox.payload_json bytes, messages.raw_json bytes) via SUM(LENGTH).
    This is the LOGICAL content size the cap is driven off — not file size."""
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
    """Size-driven eviction of raw OF payloads. SQLite only (no-op elsewhere —
    Postgres autovacuums and has no rowid).

    Frees logical payload bytes until
        SUM(LENGTH(event_inbox.payload_json)) + SUM(LENGTH(messages.raw_json))
    is under `budget_bytes`, deleting the OLDEST event_inbox rows first (the
    real leak, lowest value — a spent envelope), then NULLing the OLDEST
    messages.raw_json — but NEVER touching any row whose timestamp is within
    `floor_s` of now. Eviction happens in autocommit batches so the write
    lock is released between batches and the WS pump keeps flowing.

    Touches ONLY the two raw envelope columns; messages / fans / transactions
    ROWS are left fully intact. Idempotent: a no-op once under budget, and a
    no-op once everything older than the floor is gone (it will not breach the
    floor to reach budget — it logs that it's floor-bound instead).

    Returns a summary dict (also used by the test to assert before/after)."""
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
            # 1) event_inbox — delete oldest spent envelopes older than floor.
            while freed < over:
                row = (await conn.exec_driver_sql(
                    "SELECT COALESCE(SUM(LENGTH(payload_json)), 0), COUNT(*) FROM "
                    "(SELECT payload_json FROM event_inbox "
                    " WHERE received_at < ? ORDER BY rowid ASC LIMIT ?)",
                    (cutoff, bsize),
                )).first()
                nbytes, cnt = int(row[0] or 0), int(row[1] or 0)
                if cnt == 0:
                    break  # nothing left older than the floor
                await conn.exec_driver_sql(
                    "DELETE FROM event_inbox WHERE rowid IN "
                    "(SELECT rowid FROM event_inbox WHERE received_at < ? "
                    " ORDER BY rowid ASC LIMIT ?)",
                    (cutoff, bsize),
                )
                deleted_events += cnt
                freed += nbytes
                await asyncio.sleep(0)  # yield between batches

            # 2) messages.raw_json — NULL oldest duplicates older than floor.
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
        "floor_bound": int(after > budget),  # 1 = floor stopped us short of budget
    }
    return summary


async def prune_event_inbox_once(
    *,
    max_age_s: int | None = None,
    batch: int | None = None,
) -> dict[str, int]:
    """Unconditional age-based prune of the event_inbox landing table. Deletes
    EVERY row older than `max_age_s` (default _EVENT_INBOX_MAX_AGE_S = 2 days),
    regardless of the size budget — unlike evict_payloads_once, which only trims
    event_inbox when total LOGICAL payload exceeds PAYLOAD_BUDGET_BYTES.

    event_inbox is a spent-envelope log: by the time a row lands here the WS
    transcoder has already written the real message/chat/transaction rows, so an
    envelope older than a couple days is dead weight (kept only for short-window
    debugging + SSE replay). Touches ONLY event_inbox — messages / fans /
    transactions are never referenced. Batched autocommit deletes so the WS
    pump's write lock is released between batches and the firehose keeps flowing.
    SQLite only (no-op elsewhere — Postgres has no rowid and autovacuums).

    Returns {"deleted_events": N} (0 = nothing older than the cutoff)."""
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
            await asyncio.sleep(0)  # yield between batches — let the pump write
    return {"deleted_events": deleted, "cutoff": cutoff}


async def _maybe_convert_to_incremental_autovacuum() -> None:
    """One-time: convert an existing auto_vacuum=NONE DB to INCREMENTAL so the
    freelist can be returned to the OS. The conversion itself requires a full
    VACUUM (rewrites the whole file — a heavy, whole-DB write lock), so it is
    gated behind PAYLOAD_VACUUM_ON_START and runs at most once per boot. No-op
    if already INCREMENTAL or not SQLite."""
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
    """Return up to _PAYLOAD_INCR_VACUUM_PAGES freelist pages to the OS. Cheap
    and bounded (unlike full VACUUM); only does anything once the DB is in
    auto_vacuum=INCREMENTAL mode — otherwise it is a silent no-op. Guarded by
    the vacuum lock so it never overlaps the one-time full VACUUM."""
    from db.engine import engine, _is_sqlite
    if not _is_sqlite:
        return
    async with _payload_vacuum_lock:
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                if int((await conn.exec_driver_sql("PRAGMA auto_vacuum")).scalar() or 0) != 2:
                    return  # NONE/FULL mode: incremental_vacuum is a no-op
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
    """Periodic size cap on the raw OF payload columns. Each tick:
      1. prune event_inbox to a hard ~2-day age window (unconditional — this is
         what keeps the landing table from accreting a month-long backlog while
         the byte budget sits idle);
      2. evict raw payloads down to PAYLOAD_BUDGET_BYTES (honoring the floor);
      3. return freed pages to the OS (once auto_vacuum=INCREMENTAL).
    Hourly by default; tune via EVENT_INBOX_MAX_AGE_S / PAYLOAD_* env vars.

    The autovacuum conversion runs ONCE, before the cadence starts — it is a
    one-time migration of the DB's page layout, not part of the sweep."""
    await _maybe_convert_to_incremental_autovacuum()
    await relay_host.periodic("payload-cap", _PAYLOAD_CAP_INTERVAL_S, _payload_size_cap_sweep)
