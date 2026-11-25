from __future__ import annotations

import hashlib
import json
import math
from typing import Any, NamedTuple

from automations import _jev
from automations._router_jev import GateError

MODEL = "jev-1.14.0"
TIMEOUT_S = 10.0
MAX_RETRIES = 1
QID = "reply_level"

REPLY_LEVEL: dict[str, Any] = {
    "instructions": "How sexual is what she writes in `her_reply`?",
    "criteria": [
        "She writes about everyday things, with no flirting",
        "She flirts or compliments his looks, with nothing sexual",
        "She is suggestive: she hints at sex or teases without saying it outright",
        "She talks explicitly about sex: what she wants to do with him or to show him",
        "She describes graphic sex acts in detail",
    ],
}


def heat_version() -> str:
    return hashlib.sha256(json.dumps({"model": MODEL, "reply_level": REPLY_LEVEL},
                                     sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


HEAT_VERSION = heat_version()


class Level(NamedTuple):
    score: float
    p: dict[str, float]
    ms: int


def level_of(score: float) -> int:
    return max(0, math.floor(float(score) + 0.5))


def over(score: float, cap: int) -> bool:
    return level_of(score) > int(cap)


def _client(key: str) -> Any:
    return _jev.client(key, MODEL, TIMEOUT_S, MAX_RETRIES)


def _questions() -> dict[str, Any]:
    from typesafe_sdk import Score
    return {QID: Score(instructions=REPLY_LEVEL["instructions"], criteria=list(REPLY_LEVEL["criteria"]))}


async def ask(text: str, account_id: str, *, timeout_s: float) -> Level:
    if timeout_s <= 0:
        raise GateError("deadline")
    try:
        res, ms = await _jev.ask_one(_client, account_id, {"her_reply": text}, _questions(), MODEL,
                                     min(TIMEOUT_S, timeout_s), GateError)
        sc = res.scores[QID]
        score = float(sc.score)
        if not 0.0 <= score <= len(REPLY_LEVEL["criteria"]) - 1:
            raise GateError(f"reply_level score out of range: {score}")
        p = {str(k): float(v) for k, v in (sc.probabilities or {}).items()}
    except GateError:
        raise
    except Exception as e:
        raise GateError(f"{type(e).__name__}: {e}"[:300]) from e
    return Level(score, p, ms)
