"""service/ultra_judge.py — a judge step's one model call (ultra_judge_decide; the run: ultra_run).

One DeepSeek flash call per judge, billed to the owner (user_id, no account), like the planner. Its reply's ids
are clamped to the candidates; fewer than pick_n left fails the step.
"""
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
    ids: list[int] | None   # None: failed (`error`)
    cost_mc: int
    error: str | None = None
    capped: bool = False    # the daily AI cap refused the call → the plan is `capped`


async def ask(step: dict[str, Any], cands: list[dict[str, Any]], owner_user_id: str) -> Verdict:
    """Never raises an Exception: any failure is a failed Verdict (a judge step never ends `uncertain`)."""
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
