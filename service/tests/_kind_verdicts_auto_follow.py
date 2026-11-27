from __future__ import annotations

from sqlalchemy import select

from _kind_verdict_seeds import CHAT_RULES, FAN, SPEND_RULE, _fan, _lists, _rows
from db.engine import get_session
from db.models import Fan, SmartList

VERDICTS = {
    "fansly": {
        "auto_follow": {"run": "same",
                        "expired": "gated:platform_lacks:recent_expired_subscribers",
                        "refused_list": "gated:platform_lacks:tip_ledger",
                        "full_pool": "gated:platform_lacks:tip_ledger",
                        "chat_list": "same"},
    },
    "onlyfans": {
        "auto_follow": {"run": "same", "expired": "same", "refused_list": "same", "full_pool": "same",
                        "chat_list": "same"},
    },
}

_FOLLOW = {"action": "follow", "dry_run": False}

PAYLOADS = {"auto_follow": {"run": _FOLLOW, "expired": {**_FOLLOW, "targets": {"source": "expired"}},
                            "refused_list": _FOLLOW, "full_pool": {**_FOLLOW, "daily_cap": 1},
                            "chat_list": _FOLLOW}}

_FANSLY = ("POST /account/900000000000000002/followers", "table:follow_log", "table:follow_ping_state")
_OF = ("follow_user", "table:follow_log", "table:follow_ping_state")

SAME_EFFECTS = {
    "fansly": {"auto_follow": {"run": _FANSLY, "chat_list": _FANSLY}},
    "onlyfans": {"auto_follow": dict.fromkeys(("run", "expired", "refused_list", "full_pool", "chat_list"), _OF)},
}


def follow_list(rules: tuple[dict, ...], *sources: str, stored: int = 0):
    async def seed(aid: str, platform: str) -> dict:
        await _lists(("Follow", rules, {}))(aid, platform)
        async with get_session() as s:
            s.add_all([Fan(account_id=aid, fan_id=int(FAN) + 100 + i) for i in range(stored)])
            sid = (await s.execute(select(SmartList.id).where(SmartList.account_id == aid))).scalar_one()
        return {"targets": {"source": list(sources), "smart_list_id": sid}}
    return seed


SEEDS = {
    ("auto_follow", "run"): _rows(_fan()),
    ("auto_follow", "refused_list"): follow_list((SPEND_RULE,), "all_stored", "smart_list"),
    ("auto_follow", "full_pool"): follow_list((SPEND_RULE,), "all_stored", "smart_list", stored=5),
    ("auto_follow", "chat_list"): follow_list(CHAT_RULES, "smart_list"),
}
