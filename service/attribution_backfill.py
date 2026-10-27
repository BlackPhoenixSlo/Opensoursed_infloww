"""attribution_backfill — the revenue kind and status sets every sales reader
shares (stats, Sales attribution, Smart lists and the rest import them).

It used to also hold the orphan sweep (`attribute_orphans`), which wrote a
manual `transactions.attributed_employee_id` for a sale the attribution view
credited to nobody when exactly one sender (the Automation Employee included)
had chatted the fan 1:1 in the last 7 days; transaction_ingest ran it after
each scan, and db/backfills/backfill_orphan_attribution.py over all history.
Converters now credits such a sale by rule (the last human chatter within the
Agency's window, sales_attribution and tx_rollup.converter_lookback), so the
sweep's overrides would beat the rule: outside the window a sale must stay
Unattributed. The sweep is gone; overrides it wrote earlier stay manual.
"""

from __future__ import annotations

# Revenue kinds the attribution view splits per employee (mirrors the
# `message_linked` CTE in migration 0038). Subscriptions/rebills are excluded —
# they aren't chatter-driven and never enter the per-employee view.
REVENUE_KINDS: tuple[str, ...] = (
    "ppv", "ppv_message", "ppv_post", "ppv_stream",
    "tip", "tip_post", "tip_stream", "custom",
)
TIP_KINDS: tuple[str, ...] = ("tip", "tip_post", "tip_stream")
# The whole ppv family counts as PPV: `kind='ppv'` alone is dead in practice,
# as real unlocks arrive from the payouts ledger as ppv_message/ppv_post.
PPV_KINDS: tuple[str, ...] = ("ppv", "ppv_message", "ppv_post", "ppv_stream")
# The statuses stats counts, too (stats imports this): pending is real
# revenue that clears in ~7d, so we attribute it now rather than waiting.
TRACKED_STATUSES: tuple[str, ...] = ("cleared", "pending")
# The reversals: a sale OF took back (`chargedback`), refunded, or is
# returning (`refund_pending`). Never revenue; Creator reports' Refunds and
# Chargebacks read them.
# `SETTLED_REVERSALS` are the two whose money is gone (ingest moves a fan's
# spend back on the flip to one of them); a returning sale is not settled yet.
SETTLED_REVERSALS: tuple[str, ...] = ("chargedback", "refunded")
REVERSED_STATUSES: tuple[str, ...] = (*SETTLED_REVERSALS, "refund_pending")
