"""automations/full_ai_offer_turn.py — `run_turn`'s row `offer_details` steps (spec offer-details C,
D), moved out of full_ai_turn.py as-is:

  offer_resolved(facts, deadline) -> (Resolved, OfferFacts | None)   the Offer and its facts
  offer_check(facts, reply, writer, parts, deadline, *, rewrite, chain) -> parts   the check

`rewrite(writer)` / `chain(text, facts, scratch, single=False)` are `run_turn`'s own Writer rewrite
(`write` capped at the Turn deadline) and reply chain (`full_ai_turn._chain`), passed in so this
module imports nothing from full_ai_turn. Sends nothing.
"""
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
    """Row `offer_details`: the Offer his question names (`resolve_offer` over `facts.offer_ask`)
    and its facts, the vault read inside the Turn deadline (out of time: the row's own facts
    only); facts None when none resolved."""
    got = resolve_offer(facts.offer_ask)
    if got.row is None:
        return got, None
    ids = full_ai_test._media(got.row, "locked", "previews")
    try:
        vault = await asyncio.wait_for(load_offer_vault(facts.account_id, ids), deadline - time.monotonic())
    except asyncio.TimeoutError:
        vault = {}
    except Exception:           # a failed read answers from the row's own facts, never drops the Turn
        log.exception("full_ai offer vault read failed account=%s", facts.account_id)
        vault = {}
    cands = facts.offer_ask.candidates
    return got, offer_facts(got.row, vault, cands[:cands.index(got.row)])


def _offer_rules(text: str, facts: TurnFacts) -> list[str]:
    """`offer_answer_ok` on `text` against `facts.offer_facts`; a raise is the failed rule "error"."""
    try:
        return list(offer_answer_ok(text, facts.offer_facts))
    except Exception:
        log.exception("full_ai offer check failed account=%s", facts.account_id)
        return ["error"]


async def offer_check(facts: TurnFacts, reply: dict, writer: str | None, parts: list[str],
                      deadline: float, *, rewrite: Callable[[str], Awaitable[Any]],
                      chain: Callable[..., Awaitable[list[str]]]) -> list[str]:
    """The Offer answer check (spec offer-details D) on row `offer_details`, mirrored on
    `full_ai_turn._claim_audit`: her parts joined through `offer_answer_ok` against
    `facts.offer_facts`; pass -> `parts`. Fail -> `reply["offer_details"]["failed"]` = the first
    text's rule names and one rewrite by the Writer that answered (`rewrite(writer)`: same messages,
    at least one `writer_timeout_s` left) through the chain on a scratch reply, its attempts
    appended with `rewrite: true`; it ships (`check: rewrite`) only with text, no leak and a pass.
    Else, and when the Writer walk or the chain left no `parts` at all, `offer_fallback` through the
    chain as one bubble (`check: fallback`; dropped for empty / echo -> the raw fallback as one
    part). Its chain dropping it for banned words, or a leak -> [] (`check: dropped`,
    `dropped_reason` banned | leak): the one no-reply case. No Pick on this row, so nothing rides
    it. Like the Claim audit, a shipped fallback leaves `leak` / `dropped_reason` as the first chain
    set them. A raise inside the pure check is a failed check (`failed: ["error"]`, no rewrite: the
    fallback); `rewrite` / `chain` errors propagate as in the sibling checks.
    ASSUMPTION: a bug in `offer_answer_ok` sends the coded fact fallback rather than no
    reply (rung 2: spec D keeps banned / leak the one no-reply case). Overturned if the owner wants
    a check error to send nothing."""
    of, out = facts.offer_facts, reply["offer_details"]
    if parts:
        out["failed"] = _offer_rules("\n".join(parts), facts)
        if not out["failed"]:
            return parts
        # Parts come only from a Writer's text, so `writer` is the one that answered.
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
