"""automations/_heat_jev.py — Full AI Chat's Heat check Jev: one Score, how sexual her reply is.

The Heat check (spec 06 › Contracts › Heat check; `full_ai_turn._heat_check`): with config
`floor_on`, on a Route sext Turn whose chain left text, Jev scores ONE Score `reply_level` over
`{"her_reply": <the parts joined>}`: the Router's `intensity` scale (0-4) turned on her. Her level
above the Turn's Heat (the Heat the Writer was given) -> one rewrite. Any failure is `GateError`
(the caller ships the text). No Mode check: it runs wherever a Writer writes. Wording: new,
docs/prompts NEW-155 (owner OK 2026-11-15); not probed yet. `HEAT_VERSION` goes on the row.

  - `REPLY_LEVEL`, `HEAT_VERSION`.
  - `level_of(score)`, `over(score, cap)`: pure.
  - `ask(text, account_id, *, timeout_s)`: one request; `Level`, or `GateError` on any failure.

The key is `_router_jev`'s (`tenant_keys.typesafe_key_for`). `_client` is the tests' fake seam.
"""
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

# Wording (owner OK 2026-11-15; docs/prompts NEW-155): `_router_jev.INTENSITY` turned on her.
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
    """A short digest of what changes what Jev answers: model and wording."""
    return hashlib.sha256(json.dumps({"model": MODEL, "reply_level": REPLY_LEVEL},
                                     sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


HEAT_VERSION = heat_version()


class Level(NamedTuple):
    score: float                    # Jev's expected level, 0..4
    p: dict[str, float]             # level -> probability
    ms: int


def level_of(score: float) -> int:
    """Her level: the Score rounded to the nearest level, a tie up (`full_ai_decide.heat_of`'s
    rounding). Pure."""
    return max(0, math.floor(float(score) + 0.5))


def over(score: float, cap: int) -> bool:
    """Her level above the Turn's Heat. Pure."""
    return level_of(score) > int(cap)


def _client(key: str) -> Any:
    return _jev.client(key, MODEL, TIMEOUT_S, MAX_RETRIES)


def _questions() -> dict[str, Any]:
    from typesafe_sdk import Score
    return {QID: Score(instructions=REPLY_LEVEL["instructions"], criteria=list(REPLY_LEVEL["criteria"]))}


async def ask(text: str, account_id: str, *, timeout_s: float) -> Level:
    """The `reply_level` Score over `text` in one request within `min(TIMEOUT_S, timeout_s)`.
    Raises `GateError` on any failure (no key, no SDK, timeout, HTTP, a missing or out-of-range
    answer)."""
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
    except Exception as e:      # SDK missing, HTTP, timeout, a missing answer
        raise GateError(f"{type(e).__name__}: {e}"[:300]) from e
    return Level(score, p, ms)
