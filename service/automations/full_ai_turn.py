from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable

import llm_client
import run_slot
from automations import _heat_jev, _info_jev, _price_jev, _reply_shape, _voice, cat_stickers
from automations import _router_jev as router
from automations import full_ai_caption, full_ai_sell, full_ai_test
from automations._nonnative import NONNATIVE_OUTPUTS
from automations.full_ai_mode import full
from automations._outbound import finalize_draft
from automations._prompt_rules import STYLE_MAX_BUBBLES
from automations._style_flags import load_strip_emojis
from automations._typos import apply_typo_throttle
from automations._wordfilter import load_banned_words
from automations.full_ai_sell import Pick, Refusal, Teased
from automations.full_ai_offer_details import OfferAsk, OfferFacts, diagnostics
from automations.full_ai_offer_turn import offer_check, offer_resolved
from automations.full_ai_decide import SALT_VER, Decision, Facts, arm_of, decide_turn
from automations.full_ai_scene import scene_next, scene_words
from automations.full_ai_writers import (
    PURPOSE, WriteResult, _outcome, bundle_of, count_flag, gif_offered, lead_flag, nearest_flag, nearest_line, scene_flag, scene_of, scene_turn, style_flags, typo_rate, was_cents_of, write,
)
from automations.full_ai_writers import (
    implied_flag, is_ride, likes_flag, spacing_flag, tease_flag, tease_turn, wide_flag,
)
from automations.full_ai_config import loaded, turn_bound_s
from automations.rhythm import INLINE_MAX_S
from automations.welcome_chatter_for_info import _HISTORY_TAIL, _REPLY_MAX_CHARS
from db.engine import get_session
from db.models import AccountAiConfig

log = logging.getLogger(__name__)

_FORMAL_MAX_BUBBLES = 2


@dataclass
class TurnFacts:
    account_id: str
    fan_id: int
    mode: str
    anchor_key: str
    state: dict
    cut_rows: list
    bought: Any
    offer: Any
    fan_info: dict
    asked: dict
    config: dict
    side: str | None
    typo_state: dict = field(default_factory=dict)
    config_rev: int = 0
    next_question: str | None = None
    ask_list: Any = None
    pick: Pick | Refusal | None = None
    owned: set[int] = field(default_factory=set)
    spent: list = field(default_factory=list)
    tips: list[int] = field(default_factory=list)
    sent: set[int] = field(default_factory=set)
    tease: Teased | None = None
    offer_piece: Teased | None = None
    photo: dict | None = None
    # One of her recent replies carried her dare: his picture is read regardless, and she does not dare twice.
    dared: bool = False
    dare_due: bool = False
    scene: dict | None = None
    scene_now: dict | None = None
    purchases: list = field(default_factory=list)
    offer_ask: OfferAsk = field(default_factory=OfferAsk)
    offer_facts: OfferFacts | None = None


@dataclass
class TurnResult:
    row_id: int
    decision: Decision
    parts: list[dict]
    writer: str | None
    attempts: list[dict]
    wait_s: float | None
    status: str
    offer: dict | None = None
    caption: dict | None = None
    scene: dict | None = None
    price: dict | None = None
    dropped_reason: str | None = None
    heat_check: dict | None = None


async def stored_config(account_id: str) -> dict:
    async with get_session() as s:
        row = await s.get(AccountAiConfig, str(account_id))
    got = loaded(row.full_ai_config_json if row is not None else None)
    if got is None:
        raise ValueError(f"unreadable Full AI config account={account_id}")
    return got


async def load_turn_facts(account, fan, anchor, mode, *, session=None, side=None, photo=None,
                          reply_to_n=None) -> TurnFacts:
    if mode == "test":
        cfg = await stored_config(account)
        facts = await full_ai_test.fetch(account, fan, side, anchor, cfg[side], photo, reply_to_n=reply_to_n)
        facts.config_rev = cfg["rev"]
        return facts
    raise NotImplementedError(f"load_turn_facts: Test chat only, not {mode!r}")


@dataclass(frozen=True)
class TurnIO:
    trigger_kind: str
    hold: Callable[[dict, str], float]
    send: Callable[..., Awaitable[None]] | None
    record: Callable[[dict], Awaitable[int]]


# price Jevs stop this long before the Turn deadline so their own timeout fires before run_turn's sell cap
_PRICE_MARGIN_S = 0.5


def _freed(aw):
    return run_slot.freed(aw, budget_s=INLINE_MAX_S)


# One Turn deadline for every LLM stage: the SDK timeout is per HTTP op (retried), so Router and Writer walks are also wall-clock capped.
async def _capped(call, deadline: float) -> WriteResult:
    left = deadline - time.monotonic()
    if left <= 0:
        return await call
    try:
        return await _freed(asyncio.wait_for(call, left))
    except asyncio.TimeoutError:
        return WriteResult(None, None, [{"writer": "turn", "outcome": "timeout", "ms": int(left * 1000)}])
    finally:
        call.close()


async def _route(facts: TurnFacts, deadline: float) -> tuple[Decision, dict, str | None, int | None, str | None]:
    try:
        jev = await _freed(router.ask(facts.state, facts.account_id, mode=facts.mode, scene=scene_flag(facts),
                                      spacing=spacing_flag(facts), likes=likes_flag(facts),
                                      tease=tease_flag(facts), implied=implied_flag(facts),
                                      timeout_s=deadline - time.monotonic()))
        fired, intensity, error = router.fired(jev.answers, facts.mode), jev.intensity, None
        answers, score, model, ms = jev.answers, {"score": jev.intensity, "p": jev.intensity_p}, jev.model, jev.ms
        choices = jev.choices
    except router.GateError as e:
        fired, intensity, error = frozenset(), 0.0, str(e) or type(e).__name__
        answers, score, model, ms = None, None, None, None
        choices = None
    cfg = facts.config
    d = decide_turn(Facts(fired=fired, intensity=intensity, pending_offer=facts.offer is not None,
                          pending_tease=facts.tease is not None, jev_ok=error is None,
                          sell_on=bool(cfg["sell_on"]), sext_on=bool(cfg["sext_on"]),
                          open_offer=facts.offer_piece is not None,
                          draft_on=full(facts.mode) and bool(cfg["draft_questions"]),
                          scene=scene_flag(facts), chat_tease=tease_flag(facts),
                          offer_details=full(facts.mode)))
    jev_json = {"answers": answers, "intensity": score, "fired": sorted(fired), "state": facts.state,
                "choices": choices}
    return d, jev_json, model, ms, error


async def _info(facts: TurnFacts, route: str, deadline: float, jev_json: dict, *,
                ask: bool = True) -> str | None:
    err = await _info_stage(facts, route, deadline, jev_json, ask=ask)
    if ask and route == "chat" and facts.config["info_questions"] == "list":
        history = [(m.direction, router.line_text(m)) for m in facts.cut_rows[-_HISTORY_TAIL:]]
        al = _info_jev.ask_list(facts.config, facts.fan_info, facts.asked, history,
                                random.Random(f"full_ai:ask:{facts.anchor_key}"))
        facts.ask_list = al = _info_jev.unled(al) if lead_flag(facts) else al
        jev_json.setdefault("info", {}).update(info_questions="list", still_needed=al.keys,
                                               presented=al.presented)
    return err


async def _info_stage(facts: TurnFacts, route: str, deadline: float, jev_json: dict, *,
                      ask: bool = True) -> str | None:
    lead, likes, wide = lead_flag(facts), likes_flag(facts), wide_flag(facts)
    jev_json["info_version"] = _info_jev.info_version(lead, likes, wide)
    left = deadline - time.monotonic()
    if left <= 0:
        return "deadline"
    choice_on = ask and route == "chat" and facts.config["info_questions"] == "pick"
    offered = _info_jev.askable(facts.config, facts.fan_info, lead) if choice_on else []
    st = _info_jev.state(facts.state, facts.asked, offered)
    try:
        info = await _freed(_info_jev.ask(st, facts.account_id, offered, timeout_s=left, lead=lead, wide=wide))
    except router.GateError as e:
        return f"jev_failed: {e}"[:300]
    jev_json["info"] = {"stated": info.stated, "pick": info.pick, "fired": info.fired,
                        "asked": st["asked"]}
    facts.next_question = info.pick
    if not info.fired:
        return None
    left = deadline - time.monotonic()
    if left <= 0:
        return "deadline"
    try:
        got = await _freed(_info_jev.extract(facts, info.fired,
                                             timeout_s=min(float(facts.config["writer_timeout_s"]), left),
                                             likes=likes, wide=wide))
    except llm_client.LLMError as e:
        return f"extract:{_outcome(e)}"
    except _info_jev.ExtractError as e:
        return f"extract:{e}"
    facts.fan_info = {**facts.fan_info, **got}
    if info.pick not in _info_jev.missing(facts.config, facts.fan_info):
        facts.next_question = None
    return None


async def _chain(raw: str, facts: TurnFacts, reply: dict, *, single: bool = False,
                 typos: bool = True) -> list[str]:
    aid, fid = facts.account_id, facts.fan_id
    strip_emoji_on = bool(facts.config.get("strip_emojis")) or await load_strip_emojis(aid)
    text, leak = await finalize_draft(raw, account_id=aid, fan_id=fid, purpose=PURPOSE,
                                      strip_emoji=strip_emoji_on, v=_voice.HER)
    reply["leak"] = leak
    if not text:
        reply["dropped_reason"] = "empty"
        return []
    flags = style_flags(facts.config)
    max_bubbles = 1 if single else STYLE_MAX_BUBBLES if flags["style_on"] else _FORMAL_MAX_BUBBLES
    words, mode = await load_banned_words(aid)
    name_protect = [n for n in (facts.fan_info.get(k) for k in
                                ("real_name", "generated_nickname", "of_display_name")) if n]
    rows = facts.cut_rows
    # no echo pass: dropping answers that repeat his words ("happy halloween" -> "... to u too") left him unanswered
    shaped = _reply_shape.shape_parts(text, _reply_shape.ShapeCtx(
        seed_id=fid, max_bubbles=max_bubbles, max_chars=_REPLY_MAX_CHARS, lang=None,
        echo_of=None, style_on=flags["style_on"],
        recent_out=[router.line_text(m) for m in rows if m.direction == "out"], allow_empty=False,
        banned_words=words, banned_mode=mode, nonnative_on=flags["nonnative_on"],
        spacing_on=flags["spacing_on"], name_protect=name_protect, force_single=single))
    if shaped.dropped_reason is not None:
        reply["dropped_reason"] = shaped.dropped_reason
        return []
    parts = shaped.parts
    # no typo pass on a Pick that is not what he asked for: a typo in "not"/"pics" would void the disclosure
    if flags["typo_on"] and typos:
        protect = name_protect + (list(NONNATIVE_OUTPUTS) if flags["nonnative_on"] else [])
        # A Pick's cap is the shaped count: the slip rides but no *fix bubble follows her last real text (PPV rides the last bubble).
        cap = len(parts) if isinstance(facts.pick, Pick) else max_bubbles
        parts = await apply_typo_throttle(aid, fid, parts, random.Random(f"{fid}:{text}"),
                                          protect=protect, max_bubbles=cap,
                                          state=reply["typo_state"], reply_rate=typo_rate(facts.config))
    return parts


def _sells(route: str, facts: TurnFacts) -> bool:
    if route in ("sell_now", "tease"):
        return True
    return route == "make_right" and bool(facts.spent) and bool(facts.config["sell_on"])


def _haggled(p: Pick, piece: Teased, same: bool, his: list[str]) -> Pick:
    base = min(piece.list_cents, p.list_cents) if same else piece.list_cents
    quote = full_ai_sell.clamp_quote(base, full_ai_sell.quoted_cents("\n".join(his)))
    list_cents = base if same else p.list_cents
    return replace(p, price_cents=min(list_cents, quote), list_cents=list_cents)


def _told_format(got: Pick | Refusal, choices: dict[str, dict[str, float]] | None, reply: dict,
                 free: bool, mode: str | None) -> Pick | Refusal:
    if (not full(mode) or not isinstance(got, Pick) or free or is_ride(got) or not got.price_cents
            or "asked" in got.facts):
        return got
    fmt = router.choice_of(choices, "asks_format")
    if fmt not in ("photo", "video") or fmt in full_ai_sell.real_formats(got):
        return got
    subject = router.choice_of(choices, "asks_subject")
    reply["nearest"] = {"asked_subject": subject, "asked_format": fmt, "step": "format"}
    return replace(got, facts={**got.facts, "asked": {"subject": subject, "format": fmt}, "nearest": "format"})


def _yes_to_open(d: Decision, facts: TurnFacts, choices: dict[str, dict[str, float]] | None) -> bool:
    piece = facts.offer_piece
    if not (full(facts.mode) and d.row == "sell" and piece and "says_yes_to_offer" in d.fired):
        return False
    subject, fmt = router.choice_of(choices, "asks_subject"), router.choice_of(choices, "asks_format")
    card = full_ai_sell.kind_of(piece.format)
    return subject in ("anything", piece.subject) and fmt in ("any", card)


async def _sell(facts: TurnFacts, d: Decision, choices: dict[str, dict[str, float]],
                reply: dict | None = None, deadline: float | None = None) -> None:
    reply = {} if reply is None else reply
    aid = facts.account_id
    jev_by = (time.monotonic() + _price_jev.TIMEOUT_S if deadline is None else deadline) - _PRICE_MARGIN_S
    heat = max(1, min(4, int(facts.scene_now["heat"] if facts.scene_now else d.heat)))
    haggle = d.row == "haggle"
    if haggle:
        teased = facts.offer_piece or facts.tease
    elif d.route == "sell_now":
        teased = facts.tease
    else:
        teased = None
    if teased:
        ask = full_ai_sell.Ask(teased.subject, teased.format, heat)
    else:
        ask = full_ai_sell.Ask(router.choice_of(choices, "asks_subject"),
                               router.choice_of(choices, "asks_format"), heat)
    free = d.route == "make_right"
    fresh = not (haggle or teased or free)
    if fresh and _yes_to_open(d, facts, choices):
        facts.pick = Refusal("offer_open")
        reply["offer_open"] = facts.offer_piece.row_id
        return
    owned = facts.owned | facts.sent if free else facts.owned
    if fresh and facts.offer_piece and d.route == "sell_now" and not tease_turn(d, facts):
        owned = owned | set(facts.offer_piece.locked) | set(facts.offer_piece.previews)
    level = router.choice_of(choices, "offer_level") if scene_flag(facts) and fresh else None
    if fresh and tease_turn(d, facts):
        level = "soft"
    if scene_flag(facts) and fresh:
        reply["level"] = level
    level_target = full_ai_sell.LEVEL_CENTS.get(level) if level else None
    tease_cents = None
    if tease_turn(d, facts) and fresh:
        tease_cents = await _tease_price(facts, heat, reply, jev_by)
        if tease_cents is None:
            facts.pick = Refusal("no_match")
            return
    if fresh and d.route == "sell_now" and tease_cents is None and count_flag(facts):
        count = full_ai_sell.asked_count("\n".join(facts.state.get("fan_new_messages") or []))
        if count:
            ask = replace(ask, count=count)
            reply["asked_count"] = count
    loaded = await full_ai_sell.load_rows(aid)
    if isinstance(loaded, Refusal):
        facts.pick = loaded
        return
    rows, groups, prints = loaded
    try:
        pool = full_ai_sell.pool(rows, groups, owned, facts.config["folders"], ask)
        if isinstance(pool, Refusal):
            facts.pick = pool
            return
        same = full_ai_sell.same_piece(pool, teased.locked, teased.previews, ask) if teased else None
        if same is not None:
            got = same
        else:
            if haggle:
                pool = [r for r in pool if r["list_cents"] <= teased.list_cents]
            if tease_cents is not None:
                pool = [r for r in pool if r["list_cents"] <= full_ai_sell.LEVEL_CENTS["soft"]
                        and (tease_cents or full_ai_sell._free_safe(r))]
                if not pool:
                    facts.pick = Refusal("no_match")
                    return
            shoots = await full_ai_sell.shoots_for(aid, pool, prints)
            sell = fresh and d.route == "sell_now"
            got = full_ai_sell.pick(pool, shoots, ask, free=free, target=level_target,
                                    seed=full_ai_sell.seed_for(aid, str(facts.fan_id), facts.anchor_key),
                                    nearest=nearest_flag(facts) and sell,
                                    bundle=bundle_of(facts) if sell else "shoot", ride=tease_cents is not None,
                                    ride_max=2 if tease_cents is None else full_ai_sell.tease_photos(tease_cents))
            if is_ride(got):
                reply["ride"] = True
            if tease_cents is not None and isinstance(got, Pick):
                got = full_ai_sell.tease_price(got, tease_cents)
            if isinstance(got, Pick) and "asked" in got.facts:
                reply["nearest"] = {"asked_subject": ask.subject, "asked_format": ask.format,
                                    "step": got.facts["nearest"]}
        if haggle and isinstance(got, Pick):
            got = _haggled(got, teased, same is not None, facts.state["fan_new_messages"])
        got = full_ai_sell.hold_folder_price(got)
        got = _told_format(got, choices, reply, free, facts.mode)
        facts.pick = got
    except Exception:  # noqa: BLE001 — fail closed: chat, never a half-built offer
        log.exception("full_ai sell step failed account=%s", aid)
        facts.pick = Refusal("inventory_unknown")
        return
    if (scene_flag(facts) and fresh and d.route == "sell_now" and tease_cents is None
            and isinstance(facts.pick, Pick) and facts.pick.price_cents):
        await _price(facts, reply, jev_by, d.heat, d.row == "sell")


async def _tease_price(facts: TurnFacts, heat: int, reply: dict, deadline: float) -> int | None:
    prices = list(facts.config["chat_tease_prices"])
    out: dict[str, Any] = {"cents": None, "p": None, "ms": None, "error": None,
                           "version": _price_jev.TEASE_PRICE_VERSION, "options": prices}
    reply["chat_tease"] = out
    st = _price_jev.tease_state(facts.state, heat, facts.purchases, [b.amount_cents for b in facts.spent])
    try:
        got = await _freed(_price_jev.ask_tease(st, _price_jev.tease_options(prices), facts.account_id,
                                                timeout_s=deadline - time.monotonic()))
    except router.GateError as e:
        out["error"] = str(e)[:300] or "GateError"
        return None
    out.update(cents=got.cents, p=got.p, ms=got.ms)
    return got.cents


async def _price(facts: TurnFacts, reply: dict, deadline: float, heat: int, he_asked: bool) -> None:
    p = facts.pick
    if (saved := full_ai_sell.folder_price(p)) is not None:
        reply["price"] = {"source": "folder", "list_cents": saved, "jev_cents": None}
        return
    heat = facts.scene_now["heat"] if facts.scene_now else heat
    st = _price_jev.state(facts.state, heat, scene_words(facts.scene_now),
                          facts.state.get("purchases") or [], p,
                          he_asked=he_asked, bought_before=bool(facts.spent))
    out: dict[str, Any] = {"list_cents": p.list_cents, "jev_cents": None, "score": None, "p": None,
                           "ms": None, "error": None, "version": _price_jev.PRICE_VERSION,
                           "he_asked": st["he_asked"], "bought_before": st["bought_before"]}
    reply["price"] = out
    try:
        got = await _freed(_price_jev.ask(st, facts.account_id, timeout_s=deadline - time.monotonic()))
    except router.GateError as e:
        out["error"] = str(e)[:300] or "GateError"
        return
    out.update(jev_cents=got.cents, score=got.score, p=got.p, ms=got.ms)
    facts.pick = replace(p, price_cents=got.cents, list_cents=got.cents,
                         facts={**(p.facts or {}), "vault_list_cents": p.list_cents})


async def _claim_audit(d: Decision, facts: TurnFacts, reply: dict, writer: str, parts: list[str],
                       pick: Pick, deadline: float) -> list[str]:
    kind = "free" if not pick.price_cents else "tease" if d.route == "tease" else "offer"
    price = pick.price_cents if kind == "offer" else None

    def ok(ps: list[str]) -> bool:
        text = "\n".join(ps)
        fails = full_ai_sell.caption_fails(text, pick, price, differs=False)
        reply["claim_fail"] = reply["claim_fail"] + [{"check": c, "text": text} for c in fails]
        return not fails

    reply["caption_fallback"], reply["claim_fail"] = False, []
    if ok(parts):
        return parts
    if deadline - time.monotonic() >= float(facts.config["writer_timeout_s"]):
        again = await _capped(write(d, facts, deadline=deadline, writers=[writer]), deadline)
        reply["attempts"] = reply["attempts"] + [{**a, "rewrite": True} for a in again.attempts]
        if again.text is not None:
            scratch = {"leak": [], "dropped_reason": None, "typo_state": dict(facts.typo_state)}
            text = cat_stickers.parse_marker(again.text)[0]
            redo = await _chain(text, facts, scratch) if text else []
            if redo and not scratch["leak"] and ok(redo):
                reply.update(scratch)
                return redo
    if is_ride(pick):
        reply["offer_dropped"] = "claim"
        none = replace(pick, media=(), previews=(), subject="anything",
                       facts={"kinds": {}, "description": ""})
        kept = [x for x in parts if full_ai_sell.claim_ok(x, none) and full_ai_sell.price_ok(x, None)]
        if not kept:
            reply["dropped_reason"] = "claim"
        return kept
    scratch = {"leak": [], "dropped_reason": None, "typo_state": dict(facts.typo_state)}
    line = await _chain(full_ai_sell.fallback_caption(pick, kind), facts, scratch, single=True,
                        typos="asked" not in pick.facts)
    if not line or scratch["leak"]:
        reply["offer_dropped"] = "leak" if scratch["leak"] else "shape"
        reply["dropped_reason"] = "leak" if scratch["leak"] else scratch["dropped_reason"]
        return []
    reply["typo_state"] = scratch["typo_state"]
    reply["caption_fallback"] = True
    return line


async def _heat_check(d: Decision, facts: TurnFacts, reply: dict, writer: str, parts: list[str],
                      deadline: float) -> list[str]:
    scene = scene_of(d, facts)
    cap = int(scene["heat"] if scene else d.heat)
    out: dict[str, Any] = {"cap": cap, "score": None, "level": None, "outcome": "error", "ms": None,
                           "version": _heat_jev.HEAT_VERSION}
    reply["heat_check"] = out
    try:
        got = await _freed(_heat_jev.ask("\n".join(parts), facts.account_id,
                                         timeout_s=deadline - time.monotonic()))
    except router.GateError as e:
        out["error"] = str(e)[:300] or "GateError"
        return parts
    out.update(score=got.score, level=_heat_jev.level_of(got.score), ms=got.ms, outcome="ok")
    if not _heat_jev.over(got.score, cap):
        return parts
    out["outcome"] = "over_sent"
    if deadline - time.monotonic() < float(facts.config["writer_timeout_s"]):
        return parts
    out["redo_score"], out["first_level"] = None, out["level"]
    again = await _capped(write(d, facts, deadline=deadline, writers=[writer]), deadline)
    reply["attempts"] = reply["attempts"] + [{**a, "rewrite": True} for a in again.attempts]
    if again.text is None:
        return parts
    scratch = {"leak": [], "dropped_reason": None, "typo_state": dict(facts.typo_state)}
    text = cat_stickers.parse_marker(again.text)[0]
    redo = await _chain(text, facts, scratch) if text else []
    if not redo or scratch["leak"]:
        return parts
    try:
        got2 = await _freed(_heat_jev.ask("\n".join(redo), facts.account_id,
                                          timeout_s=deadline - time.monotonic()))
    except router.GateError:
        return parts
    out["redo_score"], out["ms"] = got2.score, got.ms + got2.ms
    if _heat_jev.over(got2.score, cap):
        return parts
    reply.update(scratch)
    out.update(score=got2.score, level=_heat_jev.level_of(got2.score), outcome="regen_ok")
    return redo


def _ppv_turn(d: Decision, facts: TurnFacts) -> bool:
    p = facts.pick
    return (facts.config.get("caption_writer") == "caption" and full(facts.mode)
            and not is_ride(p)
            and isinstance(p, Pick)
            and ((d.route == "sell_now" and p.price_cents > 0) or (d.route == "make_right" and not p.price_cents)))


async def _caption(d: Decision, facts: TurnFacts, reply: dict, pick: Pick, deadline: float,
                   differs: bool) -> str | None:
    t0, budget = time.perf_counter(), float(facts.config["writer_timeout_s"])
    cap: dict[str, Any] = {"writer": "chat", "model": None, "outcome": "", "ms": 0, "attempts": []}
    reply["caption"] = cap
    price = pick.price_cents or None
    was = was_cents_of(d.row, pick, facts.offer_piece) if price else None

    def done(outcome: str, line: str | None = None) -> str | None:
        cap.update(outcome=outcome, ms=int((time.perf_counter() - t0) * 1000))
        if line is not None:
            cap["writer"] = "caption"
        return line

    async def shaped(text: str) -> tuple[str | None, dict]:
        scratch = {"leak": [], "dropped_reason": None, "typo_state": dict(facts.typo_state)}
        parts = await _chain(text, facts, scratch, single=True, typos="asked" not in pick.facts)
        line = parts[0] if len(parts) == 1 and not scratch["leak"] else None
        fails = ["chain"] if line is None else full_ai_sell.caption_fails(line, pick, price, differs=differs)
        if fails:
            cap["rejected"] = cap.get("rejected", []) + [{"checks": fails, "text": (line or text)[:400]}]
        return (None if fails else line), scratch

    msgs = full_ai_caption.messages(facts, pick, was)
    if msgs is None:
        return done("no_description")
    res = await _capped(full_ai_caption.write(facts, msgs, deadline=deadline - budget), deadline - budget)
    cap["attempts"], cap["model"] = res.attempts, res.writer
    if res.text is None:
        return done("no_writer")
    line, scratch = await shaped(res.text)
    outcome = "ok"
    if line is None:
        if deadline - time.monotonic() < 2 * budget:
            return done("late")
        again = await _capped(full_ai_caption.write(facts, msgs, deadline=deadline - budget, writers=[res.writer]),
                              deadline - budget)
        cap["attempts"] = cap["attempts"] + [{**a, "rewrite": True} for a in again.attempts]
        if again.text is None:
            return done("failed")
        line, scratch = await shaped(again.text)
        if line is None:
            return done("failed")
        outcome = "rewrite_ok"
    reply["typo_state"] = scratch["typo_state"]
    return done(outcome, line)


def _with_caption(reply: dict, parts: list[str], caption: str, pick: Pick, typo_state: dict) -> list[str]:
    reply["caption_fallback"] = False
    joined = "\n".join([*parts, caption])
    if not full_ai_sell.caption_fails(joined, pick, pick.price_cents or None, differs=False):
        return [*parts, caption]
    reply["caption"]["outcome"] = "alone"
    reply["typo_state"] = typo_state
    return [caption]


def _gif_part(raw: str, facts: TurnFacts, offered: bool = True) -> tuple[str, dict | None]:
    text, tag = cat_stickers.parse_marker(raw)
    if not facts.config.get("gifs") or not offered:
        return text, None
    tag = cat_stickers.keep_tag(facts.account_id, facts.fan_id, tag, has_text=bool(text))
    if tag is None:
        return text, None
    gid = cat_stickers.pick_gif(tag, random.Random(f"gif:{facts.account_id}:{facts.fan_id}:{facts.anchor_key}"),
                                account_id=facts.account_id, fan_id=facts.fan_id,
                                voice=_voice.VOICE_HER)
    return text, ({"gif": gid, "tag": tag} if gid else None)


async def run_turn(facts: TurnFacts, io: TurnIO | None = None) -> TurnResult:
    io = io or full_ai_test.IO
    t0 = time.perf_counter()
    deadline = time.monotonic() + turn_bound_s(facts.config)
    d, jev_json, model, ms, error = await _route(facts, deadline)
    reply: dict[str, Any] = {
        "parts": [], "attempts": [], "floor_reason": None, "dropped_reason": None, "leak": [],
        "side": facts.side, "config_rev": facts.config_rev, "wait_s": None, "turn_ms": None,
        "fan_info": facts.fan_info, "asked": facts.asked, "typo_state": dict(facts.typo_state),
        "info_error": None}
    if facts.photo is not None:
        reply["fan_photo"] = facts.photo
    if facts.offer_ask.reply_to_n is not None:
        reply["reply_to_n"] = facts.offer_ask.reply_to_n
    details = d.row == "offer_details"
    if details and facts.tease is not None:
        reply["held_tease"] = facts.tease.row_id
    if scene_flag(facts):
        on = scene_turn(d, facts)
        facts.scene_now = facts.scene if details else scene_next(
            facts.scene, on, router.choice_or_none(jev_json["choices"], "scene_stage"), d.heat)
        reply["scene"] = facts.scene_now
    row: dict[str, Any] = {
        "account_id": facts.account_id, "fan_id": facts.fan_id, "mode": facts.mode,
        "trigger_kind": io.trigger_kind, "trigger_key": facts.anchor_key,
        "arm": arm_of(facts.account_id, facts.fan_id), "salt_ver": SALT_VER,
        "route": d.route, "heat": d.heat, "route_row": d.row,
        "question_version": router.question_version(facts.mode), "router_model": model, "writer_model": None,
        "jev_json": jev_json, "jev_ms": ms, "jev_error": error, "status": "failed",
        "reply_json": reply}
    writer, parts = None, []
    if d.route == "no_send":
        row["status"] = "no_send"
    else:
        reply["info_error"] = await _info(facts, d.route, deadline, jev_json, ask=not details)
        reply["fan_info"] = facts.fan_info
        if details:
            got, facts.offer_facts = await offer_resolved(facts, deadline)
            reply["offer_details"] = diagnostics(got, facts.offer_facts)
        if _sells(d.route, facts):
            try:
                await asyncio.wait_for(_sell(facts, d, jev_json["choices"], reply, deadline),
                                       deadline - time.monotonic())
            except asyncio.TimeoutError:
                log.warning("full_ai sell step past the Turn deadline account=%s", facts.account_id)
                facts.pick = Refusal("inventory_unknown")
            if isinstance(facts.pick, Refusal):
                reply["refusal"] = facts.pick.reason
        pick = facts.pick if isinstance(facts.pick, Pick) else None
        differs = nearest_line(facts, pick) is not None
        caption = await _caption(d, facts, reply, pick, deadline, differs) if _ppv_turn(d, facts) else None
        caption_typos = dict(reply["typo_state"])
        alone = caption is not None and differs
        res = (WriteResult(None, reply["caption"]["model"]) if alone
               else await _capped(write(d, facts, deadline=deadline, plain=caption is not None), deadline))
        reply["attempts"], reply["floor_reason"] = res.attempts, res.floor_reason
        if res.asked_ids:
            reply["asked_marker"] = res.asked_marker
        gif = None
        if res.text is not None:
            text, gif = _gif_part(res.text, facts, gif_offered(d, facts))
            parts = await _chain(text, facts, reply) if text or gif is None else []
        if pick is not None and reply["leak"]:
            reply["offer_dropped"], pick = "leak", None
        elif pick is not None and res.text is not None and not parts:
            reply["offer_dropped"] = "shape"
        elif pick is not None and parts and caption is not None:
            parts = _with_caption(reply, parts, caption, pick, caption_typos)
        elif pick is not None and caption is not None and res.text is None:
            reply["caption_fallback"], reply["caption"]["outcome"], reply["typo_state"] = False, "alone", caption_typos
            parts = [caption]
        elif pick is not None and parts:
            parts = await _claim_audit(d, facts, reply, res.writer, parts, pick, deadline)
            if reply.get("offer_dropped"):
                pick = None
        if details:
            parts = await offer_check(
                facts, reply, res.writer, parts, deadline, chain=_chain,
                rewrite=lambda w: _capped(write(d, facts, deadline=deadline, writers=[w]), deadline))
        if parts and d.route == "sext" and facts.config["floor_on"]:
            parts = await _heat_check(d, facts, reply, res.writer, parts, deadline)
        if parts or (gif and not text):
            writer = res.writer
            row["writer_model"] = writer
            reply["wait_s"] = io.hold(facts.config, facts.anchor_key)
            if io.send is not None:
                over = facts.offer_piece.row_id if d.row == "haggle" and facts.offer_piece else None
                desc = (str(pick.facts.get("description") or "") or None
                        if pick is not None and scene_flag(facts) else None)
                await io.send(row, parts, pick, over=over, desc=desc, gif=gif)
            landed = bool(parts) and row["status"] == "sent" and "cut" not in reply
            if (k := res.asked) is not None and landed:
                reply["asked"] = {**facts.asked, k: facts.asked.get(k, 0) + 1}
    reply["turn_ms"] = int((time.perf_counter() - t0) * 1000)
    row_id = await io.record(row)
    return TurnResult(row_id, d, reply["parts"], writer, reply["attempts"], reply["wait_s"],
                      row["status"], full_ai_test.offer_of(row), reply.get("caption"),
                      reply.get("scene"), reply.get("price"), reply.get("dropped_reason"),
                      reply.get("heat_check"))
