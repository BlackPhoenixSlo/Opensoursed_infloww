# Gross only: Fansly never states its cut, so net/fee/vat stay NULL (stats count NULL nets as missing) rather than imputed.
# Refunds are invisible and uncorrectable: writes are idempotent-forever, so a reversed sale stays banked and totals stay overstated; no fix at this API.
# Currency assumed USD: no currency field, and accountMediaPrice is presumably in the creator's payout currency (a non-US creator would be mislabelled).
# /notifications has no date cursor: a row seen once stays banked (uq_tx_provider_id makes re-seeing a no-op), so this must run on a cadence.
# status="cleared": there is no pending lifecycle to observe.
# Purchases only: no live tip (7001) or stream ticket (45012) ever captured, and a kind inferred from an unverified code books revenue that never happened.
from __future__ import annotations

import asyncio
import functools as _functools
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, NamedTuple

from sqlalchemy import select

import fansly_backend
from db.engine import get_session
from db.models import Transaction, TransactionScanHistory

log = logging.getLogger("of-relay.fansly_revenue")


@_functools.lru_cache(maxsize=1)
def _log_unbanked_codes(codes: frozenset) -> None:
    if codes:
        log.info("fansly_revenue_unbanked_purchase_codes codes=%s", sorted(codes))

_KIND = "ppv_message"


def _cents(price_usd: Any) -> int | None:
    # None (not 0) on junk or zero: a $0.00 ledger row is indistinguishable from a real free unlock.
    # Decimal, not round(x * 100): that rounds half-to-even ($0.015 and $0.025 both 2c); money rounds up.
    try:
        d = Decimal(str(price_usd))
    except (InvalidOperation, TypeError, ValueError):
        return None
    # NaN/Infinity survive Decimal() but raise on compare/quantize: reject explicitly so a junk price can't take down the tick.
    if not d.is_finite() or d <= 0:
        return None
    try:
        cents = int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        # >= ~1e26 overflows the 28-digit Decimal context; caught here because _cents runs outside the tick's feed-failure try/except.
        return None
    return cents or None


def _occurred_at(raw: Any) -> datetime | None:
    # Naive to match other writers (tz-aware compares unequal to stats date filters); None, not now: a fabricated time files a sale under the wrong day forever.
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _fan_id(raw: Any) -> int | None:
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


class TickResult(NamedTuple):
    rows_inserted: int
    error: str | None = None


class Sale(NamedTuple):
    provider_id: str
    fan_id: int
    amount_cents: int
    occurred_at: datetime
    description: str
    # Keep the source row verbatim: the notification scrolls off the feed, so this is the only copy to audit the money row against.
    raw_json: str


def parse_purchase(row: dict) -> Sale | None:
    provider_id = str(row.get("id") or "").strip()
    fan_id = _fan_id(row.get("fan_id"))
    amount_cents = _cents(row.get("price_usd"))
    occurred_at = _occurred_at(row.get("created_at"))
    if not provider_id or fan_id is None or amount_cents is None or occurred_at is None:
        return None
    return Sale(
        provider_id=provider_id,
        fan_id=fan_id,
        amount_cents=amount_cents,
        occurred_at=occurred_at,
        # The grant bought goes in description, not message_id: that column joins OUR messages table and would silently match the wrong PPV row.
        description=f"Fansly media purchase (grant {row.get('grant_id') or '?'})",
        raw_json=json.dumps(row, default=str)[:32 * 1024],
    )


def _bump_lifetime_fn():
    # Resolved at call time: transaction_ingest imports this module at top level, so a module-level import would be circular.
    from transaction_ingest import _bump_lifetime
    return _bump_lifetime



async def _mark_scanned(account_id: str, *, inserted: int) -> None:
    # Don't clear paused_until here: that disabled the failure backoff; an expiring backoff clears it, as on OF.
    # Stamp the shared scan row: _decide_mode reads fully_backfilled, and an unstamped Fansly account would sit at "backfilling" forever.
    async with get_session() as s:
        row = await s.get(TransactionScanHistory, account_id)
        if row is None:
            row = TransactionScanHistory(account_id=account_id)
            s.add(row)
        row.last_scan_at = datetime.utcnow()
        row.fully_backfilled = True
        row.current_status = "ok"
        row.consecutive_failures = 0
        row.last_error = None
        row.rows_inserted_total = (row.rows_inserted_total or 0) + inserted
        row.updated_at = datetime.utcnow()


async def run_one_tick(account_id: str) -> TickResult:
    inserted = 0
    try:
        client = await asyncio.to_thread(fansly_backend.get_client, account_id)
    except FileNotFoundError:
        return TickResult(rows_inserted=0, error="no_session")
    _log_unbanked_codes(frozenset(client.unbanked_purchase_codes()))

    try:
        # to_thread: the shim is synchronous requests and this holds the per-account tick lock; inline it stalls the relay event loop.
        rows = await asyncio.to_thread(client.purchases)
    except Exception:
        # Raise, don't swallow: the supervisor's own except records the failure, so recording here would double-count and trip the 3-strike pause after 2.
        log.warning("fansly_revenue_feed_failed account=%s", account_id, exc_info=True)
        raise

    sales = [x for x in (parse_purchase(r) for r in rows) if x is not None]
    if not sales:
        await _mark_scanned(account_id, inserted=0)
        return TickResult(rows_inserted=0)

    banked: list[Sale] = []
    async with get_session() as s:
        known = set((await s.execute(
            select(Transaction.provider_transaction_id).where(
                Transaction.account_id == account_id,
                Transaction.provider_transaction_id.in_(
                    [x.provider_id for x in sales]),
            )
        )).scalars().all())

        for sale in sales:
            if sale.provider_id in known:
                continue
            # Absorb what this loop banks: a repeated notification id on one page would hit the unique index at commit and roll back the whole page.
            known.add(sale.provider_id)
            s.add(Transaction(
                account_id=account_id,
                fan_id=sale.fan_id,
                kind=_KIND,
                message_id=None,
                amount_cents=sale.amount_cents,
                currency="USD",
                occurred_at=sale.occurred_at,
                raw_json=sale.raw_json,
                provider_transaction_id=sale.provider_id,
                status="cleared",
                source="ledger",
                description=sale.description,
            ))
            # Also roll up fans.lifetime_spend_cents (same session): automations read it for live money decisions; without it every Fansly buyer reads $0 forever.
            await _bump_lifetime_fn()(s, account_id, sale.fan_id, sale.amount_cents)
            inserted += 1
            banked.append(sale)
            log.info("fansly_revenue_banked account=%s fan=%s cents=%d notif=%s",
                     account_id, sale.fan_id, sale.amount_cents, sale.provider_id)

    await _mark_scanned(account_id, inserted=inserted)
    await _announce(account_id, banked)
    return TickResult(rows_inserted=inserted)


async def _announce(account_id: str, sales: list[Sale]) -> None:
    from events import announce_transaction
    for sale in sales:
        await announce_transaction(
            account_id, sale.fan_id, occurred_at=sale.occurred_at, capped=True,
            kind=_KIND, status="cleared", reason="insert")
