#!/usr/bin/env python3
"""Ledger ingest → SSE bridge — a new revenue row written by
transaction_ingest._write_one must emit a `transaction_recorded` event so the
browser drops the fan drawer's revenue caches (chart / Sales / spend stats).
Without it the drawer sits on 5-30 min staleTimes after a sale.

Contract under test:
  • fresh insert of a recent row         → exactly one event, reason="insert"
  • re-poll of the same row (no change)  → silent (fires every 5-min tick!)
  • status flip (pending → cleared)      → one event, reason="status_flip"
  • backfill INSERT older than 48h       → silent (cold 90-day walks)
  • status flip on a row older than 48h  → still broadcasts (held PPVs settle
    days after purchase; the 48h recency cap is for inserts only)
  • neither the insert nor the patch keeps OF's row in `raw_json` (nothing
    reads it; it was most of each row's width)

Run: ./venv/bin/python service/tests/test_tx_recorded_sse.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import events  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Transaction  # noqa: E402
from sqlalchemy import select  # noqa: E402
from transaction_ingest import _write_one  # noqa: E402


def _ppv_row(provider_id: str, fan_id: int, *, created_at: datetime,
             status: str = "done", amount: float = 18.0) -> dict:
    """Minimal OF /payouts/transactions row that _parse_row classifies as a
    ppv_message unlock."""
    return {
        "id": provider_id,
        "amount": amount,
        "net": amount * 0.8,
        "fee": amount * 0.2,
        "createdAt": created_at.isoformat() + "Z",
        "status": status,
        "user": {"id": fan_id},
        "description": "Payment for message from Buyer",
    }


async def _mint_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _drain(q) -> list:
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except asyncio.QueueEmpty:
            break
    return out


async def case_fresh_insert_broadcasts():
    await _mint_account("710")
    q = await events.subscribe("model:710")
    try:
        ins, pat = await _write_one("710", _ppv_row(
            "prov-1", 4001, created_at=datetime.utcnow() - timedelta(minutes=3)))
        evs = await _drain(q)
    finally:
        await events.unsubscribe("model:710", q)

    assert (ins, pat) == (1, 0), (ins, pat)
    assert len(evs) == 1, f"fresh insert must broadcast once, got {len(evs)}"
    tx = evs[0]["transaction_recorded"]
    assert evs[0]["__account_id"] == "710", evs[0]
    assert tx["fan_id"] == 4001 and tx["kind"] == "ppv_message", tx
    assert tx["reason"] == "insert", tx
    # Every session of the Creator gets it, chatters too, whose role may hide revenue: no amount.
    assert "amount_cents" not in tx, tx


async def case_repoll_is_silent():
    """Every 5-min tick re-walks the 7-day window — an unchanged row must NOT
    re-fire or the browser would refetch the whole drawer every tick."""
    await _mint_account("711")
    row = _ppv_row("prov-2", 4002,
                   created_at=datetime.utcnow() - timedelta(minutes=3))
    await _write_one("711", row)  # initial insert (broadcasts; not under test)

    q = await events.subscribe("model:711")
    try:
        ins, pat = await _write_one("711", row)  # identical re-poll
        evs = await _drain(q)
    finally:
        await events.unsubscribe("model:711", q)

    assert (ins, pat) == (0, 1), (ins, pat)
    assert evs == [], f"unchanged re-poll must be silent, got {len(evs)} event(s)"


async def case_status_flip_broadcasts():
    """pending → cleared settles a held PPV's payout — the drawer must hear
    about the flip so net/fee fields and settled accounting catch up."""
    await _mint_account("712")
    when = datetime.utcnow() - timedelta(minutes=3)
    await _write_one("712", _ppv_row("prov-3", 4003, created_at=when,
                                     status="loading"))

    q = await events.subscribe("model:712")
    try:
        await _write_one("712", _ppv_row("prov-3", 4003, created_at=when,
                                         status="done"))
        evs = await _drain(q)
    finally:
        await events.unsubscribe("model:712", q)

    assert len(evs) == 1, f"status flip must broadcast once, got {len(evs)}"
    tx = evs[0]["transaction_recorded"]
    assert tx["reason"] == "status_flip" and tx["status"] == "cleared", tx


async def case_old_backfill_row_is_silent():
    """A 90-day cold backfill inserts hundreds of historical rows — none of
    them is news to an open drawer, so the recency gate must hold."""
    await _mint_account("713")
    q = await events.subscribe("model:713")
    try:
        ins, _ = await _write_one("713", _ppv_row(
            "prov-4", 4004, created_at=datetime.utcnow() - timedelta(days=30)))
        evs = await _drain(q)
    finally:
        await events.unsubscribe("model:713", q)

    assert ins == 1, "row must still be inserted"
    assert evs == [], f"backfill-age row must be silent, got {len(evs)} event(s)"


async def case_old_row_status_flip_broadcasts():
    """OF holds PPV payouts pending for ~7 days, so a purchase often settles
    long after `occurred_at`. The 48h recency cap must NOT swallow that
    settle-flip — it's exactly the update the drawer is waiting on. (Before
    the fix the cap applied to every reason, so flips on rows >2 days old
    were silently dropped.)"""
    await _mint_account("714")
    when = datetime.utcnow() - timedelta(days=5)  # older than the 48h cap
    # Initial pending insert is itself silent (old + reason='insert') — not
    # under test here; we subscribe only for the flip.
    await _write_one("714", _ppv_row("prov-5", 4005, created_at=when,
                                     status="loading"))

    q = await events.subscribe("model:714")
    try:
        await _write_one("714", _ppv_row("prov-5", 4005, created_at=when,
                                         status="done"))
        evs = await _drain(q)
    finally:
        await events.unsubscribe("model:714", q)

    assert len(evs) == 1, (
        f"settle-flip on an old row must still broadcast, got {len(evs)}")
    tx = evs[0]["transaction_recorded"]
    assert tx["reason"] == "status_flip" and tx["status"] == "cleared", tx


async def case_ledger_rows_store_no_raw_json():
    await _mint_account("715")
    when = datetime.utcnow() - timedelta(minutes=3)
    await _write_one("715", _ppv_row("prov-6", 4006, created_at=when, status="loading"))
    await _write_one("715", _ppv_row("prov-6", 4006, created_at=when, status="done"))
    async with get_session() as s:
        rows = (await s.execute(select(Transaction.status, Transaction.raw_json).where(
            Transaction.account_id == "715"))).all()
    assert [r.status for r in rows] == ["cleared"], rows
    assert rows[0].raw_json is None, len(rows[0].raw_json)


_harness.run(
    case_fresh_insert_broadcasts,
    case_repoll_is_silent,
    case_status_flip_broadcasts,
    case_old_backfill_row_is_silent,
    case_old_row_status_flip_broadcasts,
    case_ledger_rows_store_no_raw_json,
)
