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

Chat tease price (config `chat_tease`, test Mode, owner 2026-11-14 "jev puts the price no leader just
pass info to jev"): on a Chat tease Turn, before the pick, `full_ai_turn._tease_price` asks ONE Choice
`chat_tease_price` in its own request: which of config `chat_tease_prices` (`tease_options`: "free",
"$3", "$10", ...) the tease costs him, over his Turn, the thread, heat, what he bought and spent, and
the teases he already got (`tease_state`). The answer is the most probable option; code attaches no
order or climb to the list. Any failure (`GateError`) means no tease this Turn. Wording: new, DRAFT
docs/prompts NEW-153. `TEASE_PRICE_VERSION` (wording, model, state keys; the options come from config
and go on the row) goes on the row.

  - `TEASE_PRICE`, `TEASE_PRICE_STATE_KEYS`, `TEASE_PRICE_VERSION`.
  - `tease_options(prices)`, `tease_state(...)`: pure. `ask_tease(state, options, account_id, *,
    timeout_s)`: one request; `TeasePrice`, or `GateError`.

The key is `_router_jev`'s (`tenant_keys.typesafe_key_for`). `_client` is the tests' fake seam.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, NamedTuple

from automations import _jev
from automations._router_jev import GateError
from automations.full_ai_sell import MAX_CENTS, MIN_CENTS, Pick, tease_photos

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
    try:
        res, ms = await _jev.ask_one(_client, account_id, st, _questions(), MODEL,
                                     min(TIMEOUT_S, timeout_s), GateError)
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


# ── Chat tease price (config `chat_tease`, test Mode) ──────────────────────
# DRAFT wording (owner edits it; docs/prompts NEW-153). An option's description is built from its
# price (`free` / `paid`, `{n}` = `tease_photos`, `{price}` its label), so Jev sees what each holds.
TEASE_PRICE = {
    "instructions": (
        "She is about to slip a teasing photo of herself in with her normal chat reply; he did not "
        "ask for it. What should it cost him? Go by who he is. A first tease (`teases_sent` says none "
        "yet) to a fan who never paid her (`bought_before` no) is free or the lowest price. Free is "
        "only for that first one: once `teases_sent` holds a free photo, the next costs something, "
        "starting low. After he "
        "bought a tease or anything else (`teases_sent`, `purchases`, `spent_so_far`), go higher, but "
        "not far above what he has already shown he pays. After a tease he did not buy or said no to, "
        "stay at that price or go lower. A fan who is cold or short with her gets the cheap "
        "end; a warm or turned on fan (`heat`) who keeps spending gets the "
        "high end."),
    "free": "One photo of her, free for him to see",
    "paid": "Up to {n} teasing photos of her, locked: he pays {price} to see them",
}
TEASE_PRICE_STATE_KEYS = ("fan_new_messages", "thread", "heat", "bought_before", "purchases", "spent_so_far",
                          "teases_sent", "his_lines_this_sitting")
TEASE_QID = "chat_tease_price"


def tease_price_version() -> str:
    """A short digest of what changes what Jev answers on the tease price: model, wording, state
    keys (the options come from config and are recorded on the row)."""
    return hashlib.sha256(json.dumps(
        {"model": MODEL, "tease_price": TEASE_PRICE, "state_keys": TEASE_PRICE_STATE_KEYS},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


TEASE_PRICE_VERSION = tease_price_version()


class TeasePrice(NamedTuple):
    cents: int                      # the most probable option's price
    option: str                     # its label ("free", "$10")
    p: dict[str, float]             # option -> probability
    ms: int


def tease_options(prices: list[int]) -> dict[str, int]:
    """Config `chat_tease_prices` as the Choice's options, in config order: label -> cents ("free"
    for 0, else "$10" / "$12.50"). Pure."""
    return {("free" if c == 0 else _dollars(c)): int(c) for c in prices}


def _tease_criteria(options: dict[str, int]) -> dict[str, str]:
    return {k: TEASE_PRICE["free"] if c == 0 else TEASE_PRICE["paid"].format(n=tease_photos(c), price=k)
            for k, c in options.items()}


def tease_state(router_state: dict, heat: int, purchases: list[str], spent_cents: list[int]) -> dict[str, Any]:
    """His Turn and the thread as the Router reads them, the heat, whether and what he bought
    (`purchases` in words, `spent_so_far` the session's total), and the Router's Chat tease keys
    (`teases_sent`, `his_lines_this_sitting`). Pure."""
    total = sum(spent_cents)
    return {"fan_new_messages": router_state.get("fan_new_messages"),
            "thread": router_state.get("thread"), "heat": f"{int(heat)} of 4",
            "bought_before": "yes" if spent_cents else "no", "purchases": list(purchases),
            "spent_so_far": _dollars(total) if total else "nothing yet",
            "teases_sent": router_state.get("teases_sent"),
            "his_lines_this_sitting": router_state.get("his_lines_this_sitting")}


async def ask_tease(st: dict[str, Any], options: dict[str, int], account_id: str, *,
                    timeout_s: float) -> TeasePrice:
    """The `chat_tease_price` Choice over `options` (`tease_options`) in one request within
    `min(TIMEOUT_S, timeout_s)`; the answer is the most probable option. Raises `GateError` on any
    failure (no key, no SDK, timeout, HTTP, no answer, a tie at the top or an unoffered label)."""
    if timeout_s <= 0:
        raise GateError("deadline")
    if not options:
        raise GateError("no chat_tease_prices")
    try:
        from typesafe_sdk import Choice
        q = {TEASE_QID: Choice(instructions=TEASE_PRICE["instructions"], criteria=_tease_criteria(options))}
        res, ms = await _jev.ask_one(_client, account_id, st, q, MODEL, min(TIMEOUT_S, timeout_s), GateError)
        p = {str(k): float(v) for k, v in (res.choices[TEASE_QID].probabilities or {}).items()}
    except GateError:
        raise
    except Exception as e:      # SDK missing, HTTP, timeout, a missing answer
        raise GateError(f"{type(e).__name__}: {e}"[:300]) from e
    top = max(p.values(), default=None)
    best = [k for k, v in p.items() if v == top]
    if len(best) != 1 or best[0] not in options:
        raise GateError(f"no clear option: {p}"[:300])
    return TeasePrice(options[best[0]], best[0], p, ms)
