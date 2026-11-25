from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import llm_client
import ultra_judge_decide as uj
import ultra_plan_decide as upd

log = logging.getLogger("of-relay.ultra")


@dataclass(frozen=True)
class Verdict:
    ids: list[int] | None
    cost_mc: int
    error: str | None = None
    capped: bool = False


async def ask(step: dict[str, Any], cands: list[dict[str, Any]], owner_user_id: str) -> Verdict:
    try:
        res = await llm_client.chat(model=upd.MODEL, messages=uj.messages(step["question"], step["pick_n"], cands),
                                    purpose=uj.PURPOSE, account_id=None, user_id=owner_user_id,
                                    response_format={"type": "json_object"}, temperature=0.2)
        cost = res.cost_cents or 0
        ids = uj.picks(res.parsed, cands, step["pick_n"])
    except Exception as e:
        if (fail := llm_client.failure(e, **upd.FAILURE_TEXT)) is None:
            log.exception("ultra judge %s: no answer", step.get("id"))
            return Verdict(None, 0, uj.NO_ANSWER)
        return Verdict(None, 0, fail[1], capped=fail[0])
    return Verdict(ids, cost, None if ids is not None else uj.TOO_FEW.format(n=step["pick_n"]))
