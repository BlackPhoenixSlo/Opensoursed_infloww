#!/usr/bin/env python3
"""
Pending (uncleared) sales count in every earnings read — owner rule.

OF writes every sale `loading` (our `pending`) and clears it ~7 days later, so a
read filtered to `status='cleared'` drops the whole last week. The Dashboard,
per-model, per-employee and Creator Reports reads already count
`TRACKED_STATUSES` (locked by test_stats_revenue.py). These are the reads that
still filtered cleared-only until 2026-10-20 — each case was RED before:

  case_tips_list_counts_pending        /admin/tips-list (Message dashboard › Tips)
  case_top_tippers_counts_pending      /admin/top-tippers (Top tippers card)
  case_fan_spend_counts_pending        fan_data._load_spend →
                                       /admin/stats/per-fan-data's total_spend
  case_orphan_tips_counts_pending      /admin/ingest/transactions/orphan-tips (the
                                       Unattributed tips list)

Each also proves a chargeback stays out: "count pending" must not become "count
every status".

Run: ./venv/bin/python service/tests/test_pending_in_earnings.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Transaction  # noqa: E402

A = "2000001"
FAN = 555001
CLEARED, PENDING, CHARGEDBACK = 1_000, 2_000, 4_000


def _tip(cents: int, when: str, status: str) -> Transaction:
    return Transaction(
        account_id=A, fan_id=FAN, kind="tip", amount_cents=cents,
        net_cents=cents * 8 // 10, occurred_at=datetime.fromisoformat(when),
        status=status, currency="USD", source="ledger",
    )


async def _seed() -> None:
    async with get_session() as s:
        s.add(Account(id=A, nickname="Pending Co"))
        s.add(Fan(account_id=A, fan_id=FAN, of_username="pendingfan"))
        s.add(_tip(CLEARED, "2026-10-06T10:00:00", "cleared"))
        s.add(_tip(PENDING, "2026-10-18T01:28:09", "pending"))
        s.add(_tip(CHARGEDBACK, "2026-10-08T10:00:00", "chargedback"))
        await s.commit()


asyncio.run(_seed())

FROM, TO = "2026-10-01", "2026-10-31"
WANT = CLEARED + PENDING


def case_tips_list_counts_pending():
    import transactions
    out = asyncio.run(transactions.tips_list(
        from_=FROM, to=TO, account_id=A, employee_id=None, fan_query=None,
        limit=50, before_id=None,
    ))
    amounts = sorted(r["amount_cents"] for r in out["rows"])
    assert amounts == [CLEARED, PENDING], f"tips list must hold cleared + pending only: {amounts}"


def case_top_tippers_counts_pending():
    import transactions
    out = asyncio.run(transactions.top_tippers(
        from_=FROM, to=TO, account_id=A, employee_id=None, limit=20,
    ))
    rows = out.get("rows") or out.get("tippers") or []
    assert len(rows) == 1, rows
    assert rows[0]["total_cents"] == WANT, f"top tipper total must include pending: {rows[0]}"
    assert rows[0]["tip_count"] == 2, rows[0]


def case_fan_spend_counts_pending():
    from fan_data import _load_spend
    spend = asyncio.run(_load_spend(A))
    assert spend.get(FAN) == WANT, f"fan total_spend must include pending: {spend}"


def case_orphan_tips_counts_pending():
    import tx_ingest_admin_api
    out = asyncio.run(tx_ingest_admin_api.admin_ingest_tx_orphan_tips(
        account_id=A, from_=FROM, to=TO, include_assigned=False, limit=100,
    ))
    amounts = sorted(r["amount_cents"] for r in out["rows"])
    assert amounts == [CLEARED, PENDING], f"Unattributed tips must list pending too: {amounts}"


_harness.run()
