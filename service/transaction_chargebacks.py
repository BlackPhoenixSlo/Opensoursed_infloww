from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Iterable, Literal

from sqlalchemy import select

import of_pacing
import transaction_ingest as ti
from db.engine import get_session
from db.models import Transaction
from transaction_ingest_decide import (
    _FINGERPRINT_WINDOW,
    _NON_REVENUE_STATUSES,
    _parse_iso,
    _to_cents,
)

log = logging.getLogger("of-relay.ingest_tx")

# OF's page cap: limit=500 still answers 100.
CB_LIMIT = 100
# 500 disputes per 90 d; the busiest account had 81 (measured).
CB_MAX_PAGES = 5
# Disputes land up to 89 d after the sale (measured), beyond the ledger walk's ~600 rows.
CB_WINDOW_DAYS = 90
PAYMENT_KINDS = {
    "tips": frozenset({"tip", "tip_post", "tip_stream"}),
    "chat_messages": frozenset({"ppv_message"}),
    "subscribes": frozenset({"subscription", "rebill"}),
}
_error_traced: set[str] = set()
_CHARGEDBACK = "chargedback"



@dataclass(frozen=True)
class Held:
    id: int
    provider_id: str
    fan_id: int
    kind: str
    amount_cents: int
    occurred_at: datetime
    status: str
    currency: str | None = None


Outcome = Literal["applied", "already", "open", "unmatched", "ambiguous"]


@dataclass(frozen=True)
class CbOp:
    outcome: Outcome
    dispute: dict
    target: Held | None = None
    lifetime_delta: int = 0
    candidates: int = 0

    @property
    def writes(self) -> bool:
        return self.outcome == "applied"


def parse_dispute(item: dict) -> dict:
    pay = item.get("payment") or {}
    return {
        "fan_id": (pay.get("user") or {}).get("id"),
        "amount_cents": _to_cents(pay.get("amount")) or 0,
        "sale_at": _parse_iso(pay.get("createdAt")),
        "dispute_at": _parse_iso(item.get("createdAt")),
        "payment_type": item.get("paymentType"),
        "currency": pay.get("currency"),
        "undo": pay.get("status") == "undo",
    }


def _candidates(d: dict, rows: Iterable[Held]) -> list[Held]:
    fan, amount, sale, cur = d["fan_id"], d["amount_cents"], d["sale_at"], d["currency"]
    if not fan or sale is None:
        return []
    kinds = PAYMENT_KINDS.get(d["payment_type"])
    same = [r for r in rows if r.fan_id == fan and r.amount_cents == amount
            and (kinds is None or r.kind in kinds)
            and (not cur or not r.currency or r.currency == cur)]
    exact = [r for r in same if r.occurred_at == sale]
    if exact or d["payment_type"] != "tips":
        return exact
    return [r for r in same if r.kind == "tip" and abs(r.occurred_at - sale) <= _FINGERPRINT_WINDOW]


def plan_chargebacks(disputes: list[dict], held: Iterable[Held]) -> list[CbOp]:
    rows = {h.id: h for h in held}
    ops: list[CbOp] = []
    for d in disputes:
        if not d["undo"]:
            ops.append(CbOp("open", d))
            continue
        found = _candidates(d, rows.values())
        if len(found) != 1:
            ops.append(CbOp("unmatched" if not found else "ambiguous", d, candidates=len(found)))
            continue
        h = found[0]
        if h.status in _NON_REVENUE_STATUSES:
            ops.append(CbOp("already", d, target=h, candidates=1))
            continue
        ops.append(CbOp("applied", d, target=h, lifetime_delta=-h.amount_cents, candidates=1))
        rows[h.id] = replace(h, status=_CHARGEDBACK)
    return ops


def poll_window(now: datetime) -> tuple[str, str]:
    return ((now - timedelta(days=CB_WINDOW_DAYS)).date().isoformat(),
            (now + timedelta(days=1)).date().isoformat())



async def _read_held(s, account_id: str, fans: set[int]) -> dict[int, Transaction]:
    if not fans:
        return {}
    return {tx.id: tx for tx in (await s.execute(select(Transaction).where(
        Transaction.account_id == account_id,
        Transaction.provider_transaction_id.is_not(None),
        Transaction.fan_id.in_(fans),
    ))).scalars()}


def _snap(tx: Transaction) -> Held:
    return Held(tx.id, str(tx.provider_transaction_id), tx.fan_id, tx.kind, tx.amount_cents,
                tx.occurred_at, tx.status, tx.currency)


async def _announce(account_id: str, ops: list[CbOp]) -> None:
    from events import announce_transaction
    for op in ops:
        h = op.target
        try:
            await announce_transaction(account_id, h.fan_id, occurred_at=h.occurred_at, capped=False,
                                       kind=h.kind, status=_CHARGEDBACK, reason="status_flip")
        except Exception:
            log.warning("ingest_tx_after_commit_failed account=%s provider=%s",
                        account_id, h.provider_id, exc_info=True)


def _log_ops(account_id: str, ops: list[CbOp]) -> None:
    for op in ops:
        d = op.dispute
        sale = d["sale_at"].isoformat() if d["sale_at"] else None
        dispute = d["dispute_at"].isoformat() if d["dispute_at"] else None
        if op.outcome == "applied":
            log.info("ingest_cb_applied account=%s fan=%s provider=%s amount=%d dispute_at=%s",
                     account_id, d["fan_id"], op.target.provider_id, d["amount_cents"], dispute)
        elif op.outcome in ("open", "unmatched", "ambiguous"):
            log.debug("ingest_cb_%s account=%s fan=%s amount=%d sale_at=%s dispute_at=%s candidates=%d",
                      op.outcome, account_id, d["fan_id"], d["amount_cents"], sale, dispute,
                      op.candidates)


async def apply_chargebacks(account_id: str, items: list[dict]) -> dict:
    disputes = [parse_dispute(i) for i in items]
    fans = {d["fan_id"] for d in disputes if d["undo"] and d["fan_id"]}
    async with get_session() as s:
        ops = plan_chargebacks(disputes, [_snap(tx) for tx in (await _read_held(s, account_id, fans)).values()])
    if any(op.writes for op in ops):
        async with ti.ledger_txn("ledger-chargebacks") as s:
            held = await _read_held(s, account_id, fans)
            ops = plan_chargebacks(disputes, [_snap(tx) for tx in held.values()])
            for op in ops:
                if op.writes:
                    held[op.target.id].status = _CHARGEDBACK
                    await ti.apply_lifetime_delta(s, account_id, op.target.fan_id, op.lifetime_delta)
        await _announce(account_id, [op for op in ops if op.writes])
    _log_ops(account_id, ops)
    counts = {k: sum(op.outcome == k for op in ops)
              for k in ("applied", "already", "open", "unmatched", "ambiguous")}
    sample = [(op.dispute["fan_id"], op.dispute["amount_cents"],
               op.dispute["sale_at"].isoformat() if op.dispute["sale_at"] else None)
              for op in ops if op.outcome == "unmatched"][:3]
    return {"items": len(items), **counts, "unmatched_sample": sample}



async def _fetch(account_id: str, client, now: datetime) -> tuple[list[dict], int]:
    start, end = poll_window(now)
    items: list[dict] = []
    pages = 0
    while pages < CB_MAX_PAGES:
        resp = await asyncio.to_thread(client.chargebacks, start=start, end=end,
                                       limit=CB_LIMIT, offset=pages * CB_LIMIT)
        page = (resp or {}).get("list") or []
        items += page
        pages += 1
        if len(page) < CB_LIMIT:
            break
    else:
        log.warning("ingest_cb_page_cap account=%s pages=%d", account_id, pages)
    return items, pages


async def poll_chargebacks(account_id: str, client) -> dict:
    items, pages = await of_pacing.walk(
        account_id, "chargebacks", lambda: _fetch(account_id, client, datetime.utcnow()))
    r = await apply_chargebacks(account_id, items)
    log.info("ingest_cb_poll account=%s items=%d applied=%d open=%d unmatched=%d ambiguous=%d "
             "already=%d pages=%d unmatched_sample=%s", account_id, r["items"], r["applied"], r["open"],
             r["unmatched"], r["ambiguous"], r["already"], pages,
             ";".join(f"{f},{a},{at}" for f, a, at in r["unmatched_sample"]) or "-")
    return r


async def poll_after_walk(account_id: str, client) -> dict | None:
    try:
        return await poll_chargebacks(account_id, client)
    except Exception as e:
        first = account_id not in _error_traced
        _error_traced.add(account_id)
        log.warning("ingest_cb_error account=%s err=%s", account_id, repr(e)[:200], exc_info=first)
        return None
