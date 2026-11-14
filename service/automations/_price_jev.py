"""automations/_price_jev.py — Full AI Chat's price Jev: one Score, the Offer's price (test Mode).

Not a stream (`_info_jev`'s shape). With config `sext_scene` on a sell_now Turn with a fresh priced
Pick (not a `haggle` row: its clamp stays), `full_ai_turn._price` asks Jev ONE Score `price` over
the Offer's contents, its list price, his heat, the saved scene and his purchases; the Pick then
carries Jev's price (`cents_of`) as both price and list (owner 2026-11-14: "Jev picks the price
from full info"). 03d: the state carries the Price signals `he_asked` and `bought_before`. No
other code rule: only MIN_CENTS..MAX_CENTS clamp it. Any failure keeps the vault's list price
(`GateError`, the caller records why). Wording: new, DRAFT docs/prompts NEW-134 (03d rewrite);
not probed yet. `PRICE_VERSION` (`price_version()`) goes on the row.

  - `PRICE`, `PRICE_LADDER_CENTS`, `PRICE_VERSION`.
  - `cents_of(score)`: pure, the ladder interpolated at Jev's expected level, nearest $5, clamped.
  - `offer_state(pick)`: the Offer as Jev reads it. `state(...)`: the whole request state.
  - `ask(state, account_id, *, timeout_s)`: one request; `Price`, or `GateError` on any failure.

The key is `_router_jev`'s (`tenant_keys.typesafe_key_for`). `_client` is the tests' fake seam.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, NamedTuple

from automations import _jev
from automations._router_jev import GateError
from automations.full_ai_sell import MAX_CENTS, MIN_CENTS, Pick

MODEL = "jev-1.14.0"
TIMEOUT_S = 10.0
MAX_RETRIES = 1
STATE_KEYS = ("fan_new_messages", "thread", "heat", "he_asked", "bought_before", "scene", "purchases", "offer")

PRICE = {
    "instructions": (
        "What price should she put on `offer` for this fan right now? Start from who he is. "
        "`bought_before` no: he has never paid her, and a first buy happens at $15 to $35; go to "
        "$50 only when `heat` is 3 or 4 of 4 and `offer` is nude or explicit. `bought_before` yes: "
        "the next piece costs about one and a half times the last price he paid in `purchases`, "
        "never more than double it and never under one and a quarter times it; for a fan who keeps buying that lands at "
        "$50 to $75. If the newest line of `purchases` is a no, go under the price he refused. "
        "`he_asked` yes: he asked to see this, so take the higher of two prices that fit; no: she "
        "offers it without being asked, so take the lower. Then fit it to what `offer` holds (how "
        "many photos or videos, how long, how explicit `shows` is, its usual price `list_price`): "
        "never price a small or soft set like a big explicit one."),
    "criteria": [
        "$10: only one or two soft photos for a fan who is barely warm, or he just said no to a higher price",
        "$20: he has never bought and is warm, flirty or turned on, for soft or topless photos; or he last paid $10",
        "$35: he has never bought and is turned on, for nude or explicit content; or he last paid about $20",
        "$50: he has never bought, is very turned on (heat 3 or 4 of 4) and it is explicit; or he last paid $25 to $35",
        "$75: he last paid $40 to $55, for several explicit photos or a longer explicit video",
        "$100: he last paid $60 to $75, for her most explicit content (toys, touching herself, sex)",
        "$150: he last paid $80 or more, for a long, most explicit video",
    ],
}
PRICE_LADDER_CENTS = (1000, 2000, 3500, 5000, 7500, 10000, 15000)   # one per criterion, same order


def price_version() -> str:
    """A short digest of what changes what Jev answers: model, wording, ladder, state keys."""
    return hashlib.sha256(json.dumps(
        {"model": MODEL, "price": PRICE, "ladder": PRICE_LADDER_CENTS, "state_keys": STATE_KEYS},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


PRICE_VERSION = price_version()


class Price(NamedTuple):
    cents: int                      # `cents_of(score)`
    score: float                    # Jev's expected level, 0..len(ladder)-1
    p: dict[str, float]             # level -> probability
    ms: int


def cents_of(score: float) -> int:
    """The ladder linearly interpolated at `score` (0 = first rung), rounded to the nearest $5,
    clamped to MIN_CENTS..MAX_CENTS. Pure."""
    top = len(PRICE_LADDER_CENTS) - 1
    s = min(max(float(score), 0.0), float(top))
    lo = int(s)
    hi = min(lo + 1, top)
    raw = PRICE_LADDER_CENTS[lo] + (PRICE_LADDER_CENTS[hi] - PRICE_LADDER_CENTS[lo]) * (s - lo)
    return min(MAX_CENTS, max(MIN_CENTS, int(raw / 500 + 0.5) * 500))


def _dollars(cents: int) -> str:
    return f"${cents // 100}" if cents % 100 == 0 else f"${cents / 100:.2f}"


def offer_state(pick: Pick) -> dict[str, Any]:
    """The Offer as Jev reads it: counts, clip lengths, free previews, each locked item's
    description, its lane and the vault's list price."""
    facts = pick.facts or {}
    kinds = facts.get("kinds") or {}
    shown = facts.get("shown_kinds") or {}
    secs = [int(i["seconds"]) for i in facts.get("items") or []
            if isinstance(i, dict) and i.get("seconds")] if pick.format == "video" else []
    return {"photos": int(kinds.get("photo", 0)), "videos": int(kinds.get("video", 0)),
            "video_seconds": secs,
            "free_previews": int(sum(shown.values()) - sum(kinds.values())),
            "shows": [d for d in facts.get("descriptions") or [] if d],
            "level": pick.lane, "list_price": _dollars(pick.list_cents)}


def state(router_state: dict, heat: int, scene: str, purchases: list[str], pick: Pick, *,
          he_asked: bool, bought_before: bool) -> dict[str, Any]:
    """His Turn and the thread as the Router reads them, the folded heat, the Price signals (03d:
    he asked for this Piece, he bought before; "yes"/"no"), the saved scene and purchases in words,
    and the Offer."""
    return {"fan_new_messages": router_state.get("fan_new_messages"),
            "thread": router_state.get("thread"), "heat": f"{int(heat)} of 4",
            "he_asked": "yes" if he_asked else "no", "bought_before": "yes" if bought_before else "no",
            "scene": scene,
            "purchases": list(purchases), "offer": offer_state(pick)}


def _client(key: str) -> Any:
    return _jev.client(key, MODEL, TIMEOUT_S, MAX_RETRIES)


def _questions() -> dict[str, Any]:
    from typesafe_sdk import Score
    return {"price": Score(instructions=PRICE["instructions"], criteria=list(PRICE["criteria"]))}


async def ask(st: dict[str, Any], account_id: str, *, timeout_s: float) -> Price:
    """The `price` Score in one request within `min(TIMEOUT_S, timeout_s)`. Raises `GateError` on
    any failure (no key, no SDK, timeout, HTTP, a missing or out-of-range answer)."""
    from tenant_keys import typesafe_key_for
    if timeout_s <= 0:
        raise GateError("deadline")
    try:
        key = await typesafe_key_for(account_id)
        if not key:
            raise GateError("no TypeSafe key (agency or TYPESAFE_API_KEY)")
        t0 = time.perf_counter()
        res = await asyncio.wait_for(_client(key).system_one(st, _questions(), model=MODEL),
                                     min(TIMEOUT_S, timeout_s))
        ms = int((time.perf_counter() - t0) * 1000)
        sc = res.scores["price"]
        score = float(sc.score)
        if not 0.0 <= score <= len(PRICE_LADDER_CENTS) - 1:
            raise GateError(f"price score out of range: {score}")
        p = {str(k): float(v) for k, v in (sc.probabilities or {}).items()}
    except GateError:
        raise
    except Exception as e:      # SDK missing, HTTP, timeout, a missing answer
        raise GateError(f"{type(e).__name__}: {e}"[:300]) from e
    return Price(cents_of(score), score, p, ms)
