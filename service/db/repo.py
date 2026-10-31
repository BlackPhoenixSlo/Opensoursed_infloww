"""
Small async repository helpers — the bits of SQL we need now.

This is intentionally NOT a generic ORM facade. Each function here exists
because something in the relay/UI calls it; we add new functions when we
add new callers. Resist the temptation to predict "what else might need
a `get_account_by_proxy_label` someday" — that abstraction can wait until
the second caller appears.

Two access patterns supported:
  • Async (FastAPI handlers, SSE writer, WS pump):
        async with get_session() as s: ...
  • Sync (one-shot tools, the legacy importer):
        from sqlalchemy.orm import Session
        with Session(sync_engine) as s: ...

The async path is preferred everywhere; sync exists only for tools that
can't easily switch (subprocess scripts, ad-hoc REPL).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from jsonsafe import dump_capped
from .engine import get_session
from .models import (
    Account,
    EventInbox,
    UserAccount,
)

log = logging.getLogger("of-relay.db")


# ── Account ownership ────────────────────────────────────────────────

async def ensure_user_account_link(user_id: str, account_id: str) -> None:
    """Give a freshly captured OF account its owner. Idempotent.

    The caller MUST have synced the registry into SQL first — `accounts` is
    this row's parent and `PRAGMA foreign_keys=ON` is wired at connect, so
    linking ahead of the import is a FOREIGN KEY violation, not a duplicate.
    The bootstrap path used to fire the import and this link as two racing
    tasks and swallow the resulting IntegrityError as though it could only
    mean "already linked" — which is how a captured account reached HTTP 200
    owned by nobody (2026-08-22: Blake1, Blake2 and 80000112 all landed that
    way). Ordering the two is the fix; this function stays a plain insert and
    deliberately does NOT create the parent, because inventing an `accounts`
    row the importer never wrote is how you get a DB account with no registry
    folder — see the 21-vs-6 divergence in scripts/purge_stale.py.

    Anything that goes wrong here raises. Silence is the bug this replaces.
    """
    async with get_session() as s:
        if await s.get(UserAccount, (user_id, account_id)) is not None:
            return
        s.add(UserAccount(user_id=user_id, account_id=account_id))
        import events  # lazy: events imports this module
        events.on_commit(s, "assignment_changed", agency=user_id)


# ── Event inbox ──────────────────────────────────────────────────────

async def insert_events(rows: list[dict[str, Any]]) -> None:
    """Persist raw events in ONE transaction, in list order. Each row carries
    `account_id`, `source`, `event_type`, `payload` and `provider_event_id`.

    Idempotent on (source, provider_event_id) when that pair is set: a
    re-delivery is skipped. The conflict target names the partial index's
    WHERE, without which SQLite refuses the statement outright ("ON CONFLICT
    clause does not match any PRIMARY KEY or UNIQUE constraint") — every row
    that carried a provider id used to fail that way.

    RAISES on failure, so the caller can tell a bad batch from a good one and
    retry its rows one at a time (events_persist._persist_batch).

    Goes through the OF-cache writer (db/of_writer): event_inbox is raw OF
    frames, so it shares the transaction of the transcodes queued with it.
    """
    if not rows:
        return
    values = [{
        "account_id": r["account_id"],
        "source": r["source"],
        "provider_event_id": r["provider_event_id"],
        "event_type": r["event_type"],
        "payload_json": dump_capped(r["payload"]),
    } for r in rows]
    account_ids = sorted({r["account_id"] for r in rows if r["account_id"]})
    from db import of_writer
    await of_writer.write(_insert_events_on, (account_ids, values))


async def _insert_events_on(s, items: list) -> list:
    """of_writer op: each item is one `insert_events` call's (accounts, rows)."""
    for account_ids, values in items:
        # Ensure each parent accounts row exists. An account can be set up on
        # disk (sessions/accounts/<id>/) + bound to a proxy in proxies.json
        # without ever being inserted into the accounts table — its events
        # would FK-violate. Idempotent ON CONFLICT no-op.
        if account_ids:
            await s.execute(
                sqlite_insert(Account).on_conflict_do_nothing(index_elements=["id"]),
                [{"id": a, "is_active_default": False} for a in account_ids],
            )
        await s.execute(
            sqlite_insert(EventInbox).on_conflict_do_nothing(
                index_elements=["source", "provider_event_id"],
                index_where=EventInbox.provider_event_id.isnot(None),
            ),
            values,
        )
    return [None] * len(items)


async def mark_event_processed(
    event_id: int, *, status: str = "ok", error: str | None = None,
) -> None:
    """Mark a row processed. Called by the worker that drains event_inbox
    into canonical tables (chats / messages / fans / transactions). Phase A
    doesn't ship that worker — but the column is filled by manual hands too
    (debug tools, dry-run scripts)."""
    try:
        async with get_session() as s:
            await s.execute(
                update(EventInbox)
                .where(EventInbox.id == event_id)
                .values(
                    processed_at=datetime.utcnow(),
                    processed_status=status,
                    processed_error=error,
                )
            )
    except Exception:
        log.exception("mark_event_processed failed (id=%s)", event_id)


# ── Account / proxy reads ────────────────────────────────────────────
# Sparse on purpose. accounts.py + proxies.py are still the source of truth
# for writes in phase A; these reads are for the new code paths (SSE
# subscriber count by account, etc.) that prefer
# typed rows over JSON files.


# ── Grok cost rollup (used by the soft-cap gate in service/ai/grok.py) ──


# ── JSON ↔ SQL sync ─────────────────────────────────────────────────
#
# Phase A keeps the legacy JSON files (accounts.py / proxies.py / session
# bootstrapping) as the *write source of truth* — we don't refactor those
# to SQL yet because the existing UI reads from them. To bring SQL in line
# with whatever the JSON files say, we call `sync_from_disk()` after every
# mutating admin endpoint.
#
# Implementation: re-runs the legacy importer's logic. The importer is
# already idempotent so calling it on every save is correct — and cheap,
# since you have 2 accounts + 3 proxies. A future Phase B will reverse the
# direction (SQL writes → JSON shims for back-compat) and eventually drop
# the JSON files entirely.

async def sync_from_disk() -> dict[str, int]:
    """Re-run the legacy → SQL importer. Idempotent. Fire-and-forget safe.

    Runs the importer's `import_proxies` + `import_accounts_and_sessions`
    in a thread so the SQLAlchemy sync engine doesn't block the event
    loop. Returns counts for log/debug.
    """
    import asyncio
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SyncSession

    from .engine import DATABASE_URL
    from .import_legacy import import_proxies, import_accounts_and_sessions

    def _run() -> dict[str, int]:
        sync_url = DATABASE_URL.replace("+aiosqlite", "").replace("+asyncpg", "")
        eng = create_engine(sync_url)
        try:
            with SyncSession(eng) as s:
                proxies_n = import_proxies(s, dry_run=False)
                accounts_n, sessions_n = import_accounts_and_sessions(s, dry_run=False)
                s.commit()
                return {"proxies": proxies_n, "accounts": accounts_n, "sessions": sessions_n}
        finally:
            eng.dispose()

    try:
        return await asyncio.get_running_loop().run_in_executor(None, _run)
    except Exception:
        log.exception("sync_from_disk failed")
        return {"proxies": -1, "accounts": -1, "sessions": -1}
