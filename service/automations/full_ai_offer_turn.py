from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from automations import cat_stickers, full_ai_test
from automations.full_ai_offer_details import (
    OfferFacts, Resolved, load_offer_vault, offer_answer_ok, offer_facts, offer_fallback, resolve_offer,
)

if TYPE_CHECKING:
    from automations.full_ai_turn import TurnFacts

log = logging.getLogger(__name__)


async def offer_resolved(facts: TurnFacts, deadline: float) -> tuple[Resolved, OfferFacts | None]:
    got = resolve_offer(facts.offer_ask)
    if got.row is None:
        return got, None
    ids = full_ai_test._media(got.row, "locked", "previews")
    try:
        vault = await asyncio.wait_for(load_offer_vault(facts.account_id, ids), deadline - time.monotonic())
    except asyncio.TimeoutError:
        vault = {}
    except Exception:
        log.exception("full_ai offer vault read failed account=%s", facts.account_id)
        vault = {}
    cands = facts.offer_ask.candidates
    return got, offer_facts(got.row, vault, cands[:cands.index(got.row)])


def _offer_rules(text: str, facts: TurnFacts) -> list[str]:
    try:
        return list(offer_answer_ok(text, facts.offer_facts))
    except Exception:
        log.exception("full_ai offer check failed account=%s", facts.account_id)
        return ["error"]


async def offer_check(facts: TurnFacts, reply: dict, writer: str | None, parts: list[str],
                      deadline: float, *, rewrite: Callable[[str], Awaitable[Any]],
                      chain: Callable[..., Awaitable[list[str]]]) -> list[str]:
    of, out = facts.offer_facts, reply["offer_details"]
    if parts:
        out["failed"] = _offer_rules("\n".join(parts), facts)
        if not out["failed"]:
            return parts
        if (out["failed"] != ["error"] and writer is not None
                and deadline - time.monotonic() >= float(facts.config["writer_timeout_s"])):
            again = await rewrite(writer)
            reply["attempts"] = reply["attempts"] + [{**a, "rewrite": True} for a in again.attempts]
            if again.text is not None:
                scratch = {"leak": [], "dropped_reason": None, "typo_state": dict(facts.typo_state)}
                text = cat_stickers.parse_marker(again.text)[0]
                redo = await chain(text, facts, scratch) if text else []
                if redo and not scratch["leak"] and not _offer_rules("\n".join(redo), facts):
                    reply.update(scratch)
                    out["check"] = "rewrite"
                    return redo
    raw = offer_fallback(of)
    scratch = {"leak": [], "dropped_reason": None, "typo_state": dict(facts.typo_state)}
    line = await chain(raw, facts, scratch, single=True)
    if scratch["leak"] or scratch["dropped_reason"] == "banned":
        out["check"], reply["dropped_reason"] = "dropped", "leak" if scratch["leak"] else "banned"
        return []
    out["check"], reply["typo_state"] = "fallback", scratch["typo_state"]
    return line or [raw]
