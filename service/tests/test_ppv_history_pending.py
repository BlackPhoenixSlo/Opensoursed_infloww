#!/usr/bin/env python3
"""fan_ppv_history shows GROSS-PAID, not settled-only.

OF holds new PPV payments in a ~7-day pending payout window, so a fresh
purchase sits at status='pending' for days. The drawer chart must show it
immediately (it's the "what did this fan just buy" question), and only drop
it back off on a real chargeback/refund.

Contract under test (both the chart `items` and the `summary` breakdown):
  • a pending ppv_message row        → appears in items + counts in messages_cents
  • a cleared ppv_message row        → appears (unchanged behavior)
  • a chargedback / refunded row     → excluded from both
  • a pending tip                    → counts in tips_cents, never in PPV items

Run: ./venv/bin/python service/tests/test_ppv_history_pending.py  (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

from datetime import datetime, timedelta  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Account, Transaction  # noqa: E402
from fans import fan_ppv_history  # noqa: E402

_AID = "990"
_FID = 55501


async def _seed() -> None:
    async with get_session() as s:
        if await s.get(Account, _AID) is None:
            s.add(Account(id=_AID))
        now = datetime.utcnow()
        rows = [
            # (provider, kind, amount_cents, status, age_days)
            ("c-cleared",  "ppv_message", 5000, "cleared",     10),
            ("c-pending",  "ppv_message", 2400, "pending",      0),  # bought 10h-ish ago
            ("c-charged",  "ppv_message", 9900, "chargedback",  2),
            ("c-refunded", "ppv_message", 4000, "refunded",     3),
            ("c-tip",      "tip",         1500, "pending",       1),
        ]
        for prov, kind, cents, status, age in rows:
            s.add(Transaction(
                account_id=_AID,
                fan_id=_FID,
                kind=kind,
                amount_cents=cents,
                currency="USD",
                occurred_at=now - timedelta(days=age),
                status=status,
                provider_transaction_id=prov,
                source="ledger",
            ))


async def case_pending_ppv_shows_and_refunds_excluded():
    await _seed()
    resp = await fan_ppv_history(_AID, _FID, limit=12)

    prices = sorted(it["price_cents"] for it in resp["items"])
    # cleared 5000 + pending 2400 present; chargeback/refund/tip absent.
    assert prices == [2400, 5000], f"expected [2400, 5000], got {prices}"

    summary = resp["summary"]
    assert summary["count"] == 2, summary
    assert summary["max_cents"] == 5000, summary
    # breakdown: gross-paid PPV = cleared + pending; chargeback/refund excluded.
    assert summary["messages_cents"] == 7400, summary
    # the pending tip counts toward tips, never toward PPV items.
    assert summary["tips_cents"] == 1500, summary
    assert summary["posts_cents"] == 0, summary


_harness.run(
    case_pending_ppv_shows_and_refunds_excluded,
)
