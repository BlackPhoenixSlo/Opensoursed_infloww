from __future__ import annotations

from datetime import datetime, timedelta

from _kind_verdict_seeds import FAN, PLATFORM_MESSAGE, SEEDS as _BASE_SEEDS, _rows
from db.models import PurchaseFollowupClaim

VERDICTS = {
    "fansly": {"purchase_followup": {
        "run": "gated:platform_lacks:purchase_linkage",
        "fold": "gated:platform_lacks:purchase_linkage",
    }},
    "onlyfans": {"purchase_followup": {"run": "same", "fold": "same"}},
}

PAYLOADS = {"purchase_followup": {"run": {}, "fold": {}}}

SAME_EFFECTS = {"onlyfans": {"purchase_followup": {
    "run": ("send_message", "table:chats", "table:fans", "table:messages", "table:purchase_followup_claims"),
    "fold": ("table:purchase_followup_claims",),
}}}


def _thanked(aid, platform):
    return PurchaseFollowupClaim(account_id=aid, fan_id=int(FAN), purchased_message_id=PLATFORM_MESSAGE[platform] + 5,
                                 silent=False, created_at=datetime.utcnow() - timedelta(minutes=30))


async def _seed_fold(aid: str, platform: str) -> None:
    await _BASE_SEEDS[("purchase_followup", "run")](aid, platform)
    await _rows(_thanked)(aid, platform)


SEEDS = {("purchase_followup", "fold"): _seed_fold}
