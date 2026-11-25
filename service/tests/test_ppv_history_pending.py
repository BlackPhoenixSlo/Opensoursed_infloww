#!/usr/bin/env python3
import _harness

_harness.bootstrap()

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
            ("c-cleared",  "ppv_message", 5000, "cleared",     10),
            ("c-pending",  "ppv_message", 2400, "pending",      0),
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
    assert prices == [2400, 5000], f"expected [2400, 5000], got {prices}"

    summary = resp["summary"]
    assert summary["count"] == 2, summary
    assert summary["max_cents"] == 5000, summary
    assert summary["messages_cents"] == 7400, summary
    assert summary["tips_cents"] == 1500, summary
    assert summary["posts_cents"] == 0, summary


_harness.run(
    case_pending_ppv_shows_and_refunds_excluded,
)
