from __future__ import annotations

# Subscriptions/rebills are excluded: not chatter-driven.
REVENUE_KINDS: tuple[str, ...] = (
    "ppv", "ppv_message", "ppv_post", "ppv_stream",
    "tip", "tip_post", "tip_stream", "custom",
)
TIP_KINDS: tuple[str, ...] = ("tip", "tip_post", "tip_stream")
# kind='ppv' alone is dead in practice; real unlocks arrive from the payouts ledger as ppv_message/ppv_post.
PPV_KINDS: tuple[str, ...] = ("ppv", "ppv_message", "ppv_post", "ppv_stream")
# Pending is real revenue (clears in ~7d), attributed now.
TRACKED_STATUSES: tuple[str, ...] = ("cleared", "pending")
# Settled = money gone; refund_pending is returning, not settled yet.
SETTLED_REVERSALS: tuple[str, ...] = ("chargedback", "refunded")
REVERSED_STATUSES: tuple[str, ...] = (*SETTLED_REVERSALS, "refund_pending")
