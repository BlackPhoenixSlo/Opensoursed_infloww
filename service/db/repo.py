from __future__ import annotations

import json
import logging
import threading
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



async def ensure_user_account_link(user_id: str, account_id: str) -> None:
    # Caller must sync the registry into SQL first: accounts is the parent (FK on), so linking earlier raises.
    async with get_session() as s:
        if await s.get(UserAccount, (user_id, account_id)) is not None:
            return
        s.add(UserAccount(user_id=user_id, account_id=account_id))
        # lazy: events imports this module
        import events
        events.on_commit(s, "assignment_changed", agency=user_id)



async def insert_events(rows: list[dict[str, Any]]) -> None:
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
    for account_ids, values in items:
        if account_ids:
            # An account can exist on disk/proxies.json without an accounts row; its events would FK-violate.
            await s.execute(
                sqlite_insert(Account).on_conflict_do_nothing(index_elements=["id"]),
                [{"id": a, "is_active_default": False} for a in account_ids],
            )
        await s.execute(
            sqlite_insert(EventInbox).on_conflict_do_nothing(
                index_elements=["source", "provider_event_id"],
                # index_where must name the partial index's WHERE, or SQLite rejects the ON CONFLICT.
                index_where=EventInbox.provider_event_id.isnot(None),
            ),
            values,
        )
    return [None] * len(items)


async def mark_event_processed(
    event_id: int, *, status: str = "ok", error: str | None = None,
) -> None:
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







_SYNC_LOCK = threading.Lock()


async def sync_from_disk() -> dict[str, int]:
    import asyncio
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SyncSession

    from .engine import DATABASE_URL
    from .import_legacy import import_proxies, import_accounts_and_sessions

    def _run() -> dict[str, int]:
        sync_url = DATABASE_URL.replace("+aiosqlite", "").replace("+asyncpg", "")
        eng = create_engine(sync_url)
        try:
            # Serial: two admin saves in a row both inserted the new proxy label (UNIQUE proxies.label).
            with _SYNC_LOCK, SyncSession(eng) as s:
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
