"""
The ledger backfill's marker walk (transaction_ingest.run_one_tick's `backfill` mode).

OF's /payouts/transactions under a date-only `startDate` (the floor's day before, see
transaction_ingest_decide.recent_start_date), paged by `marker` (createdAt <= marker,
unix seconds), never by offset: no 600-row cap. The cursor is
`oldest_seen_occurred_at`, saved per page once the page's rows are held, resumed tick
to tick; _BACKFILL_TICK_PAGES a tick. A resumed tick first re-reads the recent rows
(`_backfill_recent_rows`), so new rows never wait out the walk. What a page means is
transaction_ingest_decide.backfill_step's call.

Pages are written by transaction_ingest.write_page (capped: a walk's old rows are no
news) and the scan row through its helpers, looked up on the module at call time.
transaction_ingest imports this module; neither touches the other at import time.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

import transaction_ingest as ti
from db.engine import get_session
from db.models import Transaction
from transaction_ingest_decide import (
    _BACKFILL_FRESH_PAGES,
    _BACKFILL_TICK_PAGES,
    ScanState,
    backfill_step,
    marker_of,
    page_span,
    recent_start_date,
    scan_backfill_page,
    scan_backfill_restart,
)

if TYPE_CHECKING:
    from of_client import OFClient

log = logging.getLogger("of-relay.ingest_tx")


@dataclass
class WalkResult:
    """A tick's walk so far, either walk's (transaction_ingest's offset walk, the marker walk
    here): survives the exception that ends it. `walked`: marker-walk pages durably held
    (pages / inserted / patched count every page, the backfill's recent read too; a
    backfill's are saved page by page). `advanced`: a held page moved the cursor below where
    the tick started it (scan_after_success's `advanced`: a stop then restarts the stall count at 1).
    `complete`: the window read to its end. `stop`: why a backfill's walk ended.
    rows_min / rows_max: the offset walk's createdAt range."""
    pages: int = 0
    inserted: int = 0
    patched: int = 0
    walked: int = 0
    advanced: bool = False
    last_marker: int | None = None
    complete: bool = False
    stop: str | None = None
    rows_min: datetime | None = None
    rows_max: datetime | None = None


async def _save_backfill_page(account_id: str, tick: WalkResult, ins: int, pat: int, *,
                              cursor: datetime | None, newest: datetime | None) -> None:
    """Durable per page, so neither a crash nor a failed later page loses the walk's place."""
    async with get_session() as s:
        row = await ti.scan_state(s, account_id)
        ti.store_scan(row, scan_backfill_page(ti.scan_facts(row), cursor=cursor, newest=newest,
                                               inserted=ins, patched=pat))
    tick.pages += 1
    tick.inserted += ins
    tick.patched += pat


async def _rows_held_since(account_id: str, start: datetime) -> bool:
    """Ledger rows only: a WS pump's tip (no provider id) says nothing about the ledger's answer."""
    async with get_session() as s:
        return (await s.execute(select(Transaction.id).where(
            Transaction.account_id == account_id, Transaction.occurred_at >= start,
            Transaction.provider_transaction_id.is_not(None),
        ).limit(1))).first() is not None


async def _provider_ids_not_held(account_id: str, rows: list[dict]) -> set[str]:
    """The page's provider ids the DB does not hold. `write_page` logs and skips a row
    that fails alone because a re-poll re-serves it, but a cursor past it never would:
    a backfill moves its cursor only over rows actually held."""
    ids = {str(r["id"]) for r in rows if r.get("id")}
    if not ids:
        return ids
    async with get_session() as s:
        held = (await s.execute(select(Transaction.provider_transaction_id).where(
            Transaction.account_id == account_id,
            Transaction.provider_transaction_id.in_(ids),
        ))).scalars().all()
    return ids - set(held)


def _backfill_fetch(client: OFClient, start_date: str, marker: int | None) -> dict:
    """One page of the marker walk. No `start` / `end` (OF ignores them), never an offset."""
    return client.transactions(limit=ti._PAGE_LIMIT, offset=0, start_date=start_date, marker=marker)


async def _window_answered_blank(account_id: str, client: OFClient, window_start: datetime) -> bool:
    """An empty first page with nothing held in the window: a real empty window, or a blank
    answer? No filter, limit=1: OF names the newest row (measured: n=1, hasMore true). A row in
    the window means blank. No row at all means no ledger, unless we hold one: blank too."""
    resp = await asyncio.to_thread(client.transactions, limit=1, offset=0)
    rows = resp.get("list") or []
    if rows:
        return page_span(rows, window_start)[0] is not None
    return await _rows_held_since(account_id, datetime.min)


async def _backfill_recent_rows(account_id: str, client: OFClient, tick: WalkResult,
                                newest_seen: datetime | None) -> str:
    """A resumed tick's recent read, the recent walk's shape: decide_mode says backfill
    until done, so without it new rows would wait out the whole walk. Moves no cursor.
    Back to the newest row seen when that is older (a walk that sat out an outage: the rows
    above its top, which no marker page will read), up to OF's offset cap.

    newest_seen is the walk's claim that all from its cursor up to there is read, so it moves
    only once the read got back to it. Returns `reached`; or `gap`: rows stand between the read
    and newest_seen, the caller re-walks; or `blank` / `rows_not_held`: neither, retry next tick."""
    since = datetime.utcnow() - timedelta(hours=ti._RECENT_WINDOW_H)
    start_date = recent_start_date(min(since, newest_seen) if newest_seen else since)
    seen: set = set()
    offset = 0
    top: datetime | None = None
    reached = False
    for _ in range(_BACKFILL_FRESH_PAGES):
        resp = await asyncio.to_thread(client.transactions, limit=ti._PAGE_LIMIT, offset=offset,
                                       start_date=start_date)
        rows = resp.get("list") or []
        ids = {raw.get("id") for raw in rows if raw.get("id") is not None}
        if not rows or (ids and ids <= seen):
            break
        seen |= ids
        ins, pat = await ti.write_page(account_id, rows, capped=True)
        if await _provider_ids_not_held(account_id, rows):
            await _save_backfill_page(account_id, tick, ins, pat, cursor=None, newest=None)
            return "rows_not_held"
        oldest, newest, _ = page_span(rows, datetime.min)
        top = max(top or newest, newest or top) if top or newest else None
        reached = (reached or resp.get("hasMore") is False
                   or (newest_seen is not None and oldest is not None and oldest <= newest_seen))
        await _save_backfill_page(account_id, tick, ins, pat, cursor=None, newest=top if reached else None)
        if resp.get("hasMore") is not True:
            break
        offset += len(rows)
        await asyncio.sleep(ti._PAGE_SLEEP_S)
    if reached:
        return "reached"
    if not seen:
        return "blank" if newest_seen is not None else "reached"
    log.warning("ingest_tx_backfill_recent_capped account=%s start_date=%s pages=%d newest_seen=%s",
                account_id, start_date, _BACKFILL_FRESH_PAGES, newest_seen)
    return "gap"


async def _backfill_walk(account_id: str, client: OFClient, start_date: str, cursor: datetime | None,
                         tick: WalkResult) -> str:
    """The marker walk, from the cursor (inclusive, ties re-read: provider-id dedupe makes
    overlap free) down to startDate. Returns why it ended; sets `tick.complete` only
    when backfill_step says the window is read. A raise leaves the cursor at the last page held."""
    window_start = datetime.fromisoformat(start_date)
    marker = marker_of(cursor) if cursor is not None else None
    seen: set = set()
    first_page = True
    while True:
        if tick.walked >= _BACKFILL_TICK_PAGES:
            return "tick_cap"
        resp = await asyncio.to_thread(_backfill_fetch, client, start_date, marker)
        rows = resp.get("list") or []
        if resp.get("nextMarker") is not None:
            tick.last_marker = resp.get("nextMarker")
        log.info("ingest_tx_page_fetched account=%s page=%d count=%d marker=%s",
                 account_id, tick.pages, len(rows), resp.get("nextMarker"))
        ids = {raw.get("id") for raw in rows if raw.get("id") is not None}
        if ids and ids <= seen:
            return "repeated_page"
        seen |= ids
        floor_cursor, newest, below = page_span(rows, window_start)
        if rows:
            # One write transaction for the page; row by row only if that fails.
            ins, pat = await ti.write_page(account_id, rows, capped=True)
            if await _provider_ids_not_held(account_id, rows):
                await _save_backfill_page(account_id, tick, ins, pat, cursor=None, newest=newest)
                return "rows_not_held"
            await _save_backfill_page(account_id, tick, ins, pat, cursor=floor_cursor, newest=newest)
            tick.walked += 1
            tick.advanced = tick.advanced or (floor_cursor is not None and (cursor is None or floor_cursor < cursor))
        step = backfill_step(
            rows=len(rows), has_more=resp.get("hasMore"), next_marker=resp.get("nextMarker"),
            sent_marker=marker, first_page=first_page, below_window=below,
            held_since=bool(rows) or await _rows_held_since(account_id, window_start))
        if (step.reason == "empty_window"
                and await _window_answered_blank(account_id, client, window_start)):
            return "blank_first_page"
        first_page = False
        if step.action != "next":
            tick.complete = step.action == "complete"
            return step.reason
        marker = step.marker
        await asyncio.sleep(ti._PAGE_SLEEP_S)


async def backfill_tick(account_id: str, client: OFClient, start_date: str, state: ScanState,
                        tick: WalkResult) -> None:
    """A backfill tick: recent rows first when resuming (the first tick reads them from
    the top anyway), then up to _BACKFILL_TICK_PAGES of the marker walk. Every page under
    the news cap: a walk's flips of old rows are no news. Sets `tick.stop`."""
    cursor = state.oldest_seen_occurred_at
    read = "reached"
    if cursor is not None:
        read = await _backfill_recent_rows(account_id, client, tick, state.newest_seen_occurred_at)
    if read == "gap":
        async with get_session() as s:
            row = await ti.scan_state(s, account_id)
            ti.store_scan(row, scan_backfill_restart(ti.scan_facts(row)))
        cursor = None
    if read in ("blank", "rows_not_held"):
        tick.stop = f"recent_read_{read}"
    else:
        tick.stop = await _backfill_walk(account_id, client, start_date, cursor, tick)
    # The tick's page cap is the walk working; anything else short of done needs a look.
    (log.info if tick.complete or tick.stop == "tick_cap" else log.warning)(
        "ingest_tx_backfill_stop account=%s reason=%s complete=%s walked=%d start_date=%s",
        account_id, tick.stop, tick.complete, tick.walked, start_date)
