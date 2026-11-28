from __future__ import annotations

import copy
import os
import time
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import update

from _kind_verdict_seeds import FAN, _NUDGE_CFG, _rows, _rule, _seen
from db.engine import get_session
from db.models import NudgeState
from side_effect_gate import LIVE_CHECK_ENV

VERDICTS = {
    "fansly": {"nudge_online": {"run": "gated:platform_lacks:nudge_online",
                                "incomplete": "gated:platform_lacks:subscribers:incomplete"},
               "nudge_online_fire": {"run": "gated:platform_lacks:nudge_online", "granted": "same"}},
    "onlyfans": {"nudge_online": {"run": "same", "incomplete": "same"},
                 "nudge_online_fire": {"run": "same", "granted": "same"}},
}

_FIRE = {"fan_id": FAN, "with_image": False}
PAYLOADS = {"nudge_online": {"run": {}, "incomplete": {}}, "nudge_online_fire": {"run": _FIRE, "granted": _FIRE}}

SAME_EFFECTS = {
    "fansly": {"nudge_online_fire": {"granted": ("POST /message", "table:chats", "table:messages", "table:nudge_state")}},
    "onlyfans": {"nudge_online": dict.fromkeys(("run", "incomplete"), ("job:nudge_online_fire", "table:nudge_state")),
                 "nudge_online_fire": dict.fromkeys(("run", "granted"), (
                     "send_message", "table:chats", "table:messages", "table:nudge_state"))},
}

DECLARED_WRITES = {
    "fansly": {"nudge_online_fire": {"run": {"table:nudge_state": "the refused fire clears the pending latch its own job holds"}}},
}


def nudge_grant(aid: str, *fans: str):
    return patch.dict(os.environ, {LIVE_CHECK_ENV: ",".join(f"{aid}:nudge_online:fan={f}" for f in fans)})


def _fan_seen_now(fake) -> None:
    fake.profiles[FAN]["lastSeenAt"] = int(time.time() * 1000)


def online_beside(fake, fan_id: str) -> None:
    _fan_seen_now(fake)
    row = copy.deepcopy(fake.subscribers["subscriptions"][0])
    fake.subscribers["subscriptions"].append({**row, "id": fake.mint(), "subscriberId": fan_id})
    fake.subscribers["stats"]["totalActive"] += 1
    fake.profiles[fan_id] = {**copy.deepcopy(fake.profiles[FAN]), "id": fan_id, "username": f"fan{fan_id[-4:]}"}


def _short_roster(fake) -> None:
    fake.subscribers["stats"]["totalActive"] += 1


async def hold_latch(aid: str, job_id: int) -> None:
    async with get_session() as s:
        await s.execute(update(NudgeState).where(NudgeState.account_id == aid, NudgeState.fan_id == int(FAN))
                        .values(pending_job_id=job_id))


SEEDS = {("nudge_online", b): _rows(_NUDGE_CFG, _seen(1, timedelta(days=1))) for b in ("run", "incomplete")} | {
    ("nudge_online_fire", b): _rows(_NUDGE_CFG, _rule("nudge_online"), _seen(int(FAN), timedelta(0)))
    for b in ("run", "granted")}

JOB_SEEDS = {("nudge_online_fire", b): hold_latch for b in ("run", "granted")}

FAKE_STATE = {("nudge_online", "run"): _fan_seen_now, ("nudge_online", "incomplete"): _short_roster}

WORLDS = {("nudge_online", "incomplete"): lambda aid: nudge_grant(aid, FAN),
          ("nudge_online_fire", "granted"): lambda aid: nudge_grant(aid, FAN)}
