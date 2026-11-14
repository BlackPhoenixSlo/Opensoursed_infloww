"""automations/full_ai_turn.py — Full AI Chat's shared Turn pipeline, one for every Mode.

  load_turn_facts(account, fan, anchor, mode, *, session=None, side=None, photo=None) -> TurnFacts
  sender_for(mode)       test: full_ai_test.send | shadow: None (records only) | live: 04a
  run_turn(facts) -> TurnResult

`run_turn`, in order: Router Jev (`_router_jev.ask`; a `GateError` is chat at Heat 1, row
`jev_failed`) and `decide_turn` with the side's route flags; on a speaking Route the info stage
(`_info_jev`: what he stated, the fired fields' extract, the next question, or with the side's
`info_questions: "list"` wcfi's whole still-need list and its ask call; a failure sets
`reply_json.info_error` and the reply is still written); the Route's Writer
(`full_ai_writers.write`); the shared reply chain `finalize_draft` -> `shape_parts` ->
`apply_typo_throttle` (docs/prompts/post-processing.md); then the Mode's sender and its record.
On sell_now and tease (only reachable with the side's `sell_on`) the Sell executor runs after the
info stage and before the Writer, inside the same Turn deadline (03b, `_sell`; out of time is
inventory_unknown): a Pick reaches the Writer and lands on the row (`full_ai_test.send`: on
sell_now it rides the last text bubble as its PPV, a tease row keeps it priceless with no PPV); a
Refusal gives chat + its need-line (`reply_json.refusal`). A sell inside a Pending tease
(`TurnFacts.tease`) sells the teased piece, else its subject and format, never another. A haggle
row (DRAFT `counter_offer`, test Mode with `draft_questions` only) re-offers the open Offer's piece
(`TurnFacts.offer_piece`), else the Pending tease's, at his clamped quote. On
make_right after a Buy in the session (`TurnFacts.spent`) it picks one unseen Free item (price 0,
row kind `free`, its PPV on the last bubble); a Refusal there keeps the apology with no item. A leak
swap or a dropped turn sends no PPV (`reply_json.offer_dropped` `leak` | `shape`). One Pick per Turn at most. A text bubble set riding a Pick then passes the Claim
audit + price check (`_claim_audit`, ticket 45): one rewrite through the same chain, then
`full_ai_sell.fallback_caption` (`reply_json.caption_fallback`).
`hold_with_typing` and the DM rate are the Mode's transport's to call, and test calls neither.
A `STICKER: <tag>` line is always stripped from the Writer's text before the chain
(`cat_stickers.parse_marker`); with `config.gifs` on, its tag becomes a `{gif, tag}` part after her
text bubbles (or the whole reply), the giphy id from `cat_stickers.pick_gif`.

Guard set, declared at the one `finalize_draft` call: no consistency check and
`strip_emoji=strip_emoji_on`, the account-wide flag (autoreply's `(False, "flag")`, pinned in
test_outbound.py). Every other style switch comes from the side's config (`style`), never
from `_style_flags`, so a draft-only style change reaches only the draft window.

Sends nothing itself: no direct import of an OF client, executor, lease, DM rate or OF write module
(AST scan + runtime send traps in test_full_ai_test_chat.py; shared helpers load them transitively).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable

import llm_client
from automations import _info_jev, _price_jev, _reply_shape, _voice, cat_stickers
from automations import _router_jev as router
from automations import full_ai_caption, full_ai_sell, full_ai_test
from automations._nonnative import NONNATIVE_OUTPUTS
from automations._outbound import finalize_draft
from automations._prompt_rules import STYLE_MAX_BUBBLES
from automations._style_flags import load_strip_emojis
from automations._typos import apply_typo_throttle
from automations._wordfilter import load_banned_words
from automations.full_ai_sell import Pick, Refusal, Teased
from automations.full_ai_decide import SALT_VER, Decision, Facts, arm_of, decide_turn
from automations.full_ai_scene import scene_next, scene_words
from automations.full_ai_writers import (
    PURPOSE, _outcome, gif_offered, lead_flag, nearest_flag, scene_flag, scene_of, scene_turn, style_flags, was_cents_of, write,
)
from automations.full_ai_config import merged, turn_bound_s
from automations.welcome_chatter_for_info import _HISTORY_TAIL, _REPLY_MAX_CHARS
from db.engine import get_session
from db.models import AccountAiConfig

log = logging.getLogger(__name__)

# Formal: two bubbles at most, autoreply's no-style split (autoreply.py `max_bubbles`).
_FORMAL_MAX_BUBBLES = 2


@dataclass
class TurnFacts:
    account_id: str
    fan_id: int
    mode: str                       # test | shadow | live
    anchor_key: str                 # the row's trigger_key
    state: dict                     # the Jev state (`_router_jev.state`)
    cut_rows: list                  # the thread rows then his Turn, oldest first
    bought: Any                     # his last purchase row, or None
    offer: Any                      # the Pending offer row, or None
    fan_info: dict                  # what he stated (the session fold in test)
    asked: dict                     # field -> times asked
    config: dict                    # the side's config (checkpoint or draft)
    side: str | None                # "checkpoint" | "draft" in test, else None
    typo_state: dict = field(default_factory=dict)   # the `*fix` throttle state (test fold)
    config_rev: int = 0             # the stored config's rev the Turn ran on
    next_question: str | None = None    # the info Jev's pick (`_info_jev`), set by `run_turn`
    ask_list: Any = None                # `info_questions: "list"` on chat: `_info_jev.AskList`
    pick: Pick | Refusal | None = None  # the sell step's result (03b, `_sell`), set by `run_turn`
    owned: set[int] = field(default_factory=set)    # Owned media, raw ids (test: `full_ai_test.owned_of`)
    spent: list = field(default_factory=list)       # his purchases, oldest first (`bought_of`): the spend line
    sent: set[int] = field(default_factory=set)     # media an Offer showed him (test: `sent_media_of`)
    # The Pending tease's piece, else None (test: `full_ai_test.teased_of`). `offer` is the open
    # priced Offer's line; the two are separate.
    tease: Teased | None = None
    # The open priced Offer's piece with its list price, else None (test: `teased_of(open_offer_of)`):
    # what a haggle re-offers (ticket 47).
    offer_piece: Teased | None = None
    # His attached image in test (`full_ai_test.fetch`), landing on the row as `reply_json.fan_photo`.
    photo: dict | None = None
    # Sext scene (config `sext_scene`, test Mode): the saved scene the newest row left
    # (`full_ai_test.fetch`), and this Turn's (`full_ai_scene.scene_next`, set by `run_turn`).
    scene: dict | None = None
    scene_now: dict | None = None


@dataclass
class TurnResult:
    row_id: int
    decision: Decision
    parts: list[dict]
    writer: str | None
    attempts: list[dict]
    wait_s: float | None
    status: str                     # sent | failed | no_send
    offer: dict | None = None       # the Offer the row carries (`full_ai_test.offer_of`), else None
    caption: dict | None = None     # `reply_json.caption` (`caption_writer` "caption" on a PPV Turn)
    scene: dict | None = None       # `reply_json.scene` (config `sext_scene`): the saved scene
    price: dict | None = None       # `reply_json.price` (config `sext_scene`): the price Jev
    dropped_reason: str | None = None   # why the reply chain dropped her text: empty | banned


async def stored_config(account_id: str) -> dict:
    """The Creator's Full AI config through the pure merge: an empty store gives `DEFAULTS` on
    both sides."""
    async with get_session() as s:
        row = await s.get(AccountAiConfig, str(account_id))
    raw = row.full_ai_config_json if row is not None else None
    return merged(json.loads(raw) if raw else {})


async def load_turn_facts(account, fan, anchor, mode, *, session=None, side=None, photo=None) -> TurnFacts:
    """The Turn's facts. Test: `fan` is the pair, `anchor` his line, `side` the config side;
    read off the session's own rows (`full_ai_test.fetch`) with that side of the stored config.
    Shadow and live read the DB (`full_ai_chat._state`) from 04a; `session` is theirs."""
    if mode == "test":
        cfg = await stored_config(account)
        facts = await full_ai_test.fetch(account, fan, side, anchor, cfg[side], photo)
        facts.config_rev = cfg["rev"]
        return facts
    raise NotImplementedError(f"load_turn_facts: mode {mode!r} lands with 04a")


def sender_for(mode: str) -> Callable | None:
    if mode == "test":
        return full_ai_test.send
    if mode == "shadow":
        return None
    raise NotImplementedError(f"sender_for: mode {mode!r} lands with 04a")


async def _route(facts: TurnFacts) -> tuple[Decision, dict, str | None, int | None, str | None]:
    """Router Jev and the Route table: (decision, jev_json, router model, Jev ms, Jev error)."""
    try:
        jev = await router.ask(facts.state, facts.account_id, mode=facts.mode, scene=scene_flag(facts))
        fired, intensity, error = router.fired(jev.answers, facts.mode), jev.intensity, None
        answers, score, model, ms = jev.answers, {"score": jev.intensity, "p": jev.intensity_p}, jev.model, jev.ms
        choices = jev.choices
    except router.GateError as e:                   # never a "no": chat, Heat 1
        fired, intensity, error = frozenset(), 0.0, str(e) or type(e).__name__
        answers, score, model, ms = None, None, None, None
        choices = None
    cfg = facts.config
    # DRAFT gate (ticket 47): test Mode and the side's `draft_questions`; Shadow / live never.
    d = decide_turn(Facts(fired=fired, intensity=intensity, pending_offer=facts.offer is not None,
                          pending_tease=facts.tease is not None, jev_ok=error is None,
                          sell_on=bool(cfg["sell_on"]), sext_on=bool(cfg["sext_on"]),
                          open_offer=facts.offer_piece is not None,
                          draft_on=facts.mode == "test" and bool(cfg["draft_questions"]),
                          scene=scene_flag(facts)))
    jev_json = {"answers": answers, "intensity": score, "fired": sorted(fired), "state": facts.state,
                "choices": choices}   # 03b: test Mode's Choices, read by `_sell` only
    return d, jev_json, model, ms, error


async def _info(facts: TurnFacts, route: str, deadline: float, jev_json: dict) -> str | None:
    """`_info_stage`, then with `info_questions: "list"` on chat `facts.ask_list` over the fold it
    left (Jev failed or out of time included: the list needs no Jev), recorded on `jev_json.info`."""
    err = await _info_stage(facts, route, deadline, jev_json)
    if route == "chat" and facts.config["info_questions"] == "list":
        history = [(m.direction, router.line_text(m)) for m in facts.cut_rows[-_HISTORY_TAIL:]]
        al = _info_jev.ask_list(facts.config, facts.fan_info, facts.asked, history,
                                random.Random(f"full_ai:ask:{facts.anchor_key}"))
        if lead_flag(facts):                    # boobs_ass is never led to: not listed, not marked
            keep = [i for i, k in enumerate(al.keys) if k != "boobs_ass"]
            al = _info_jev.AskList([al.keys[i] for i in keep], [al.lines[i] for i in keep],
                                   al.ask and bool(keep))
        facts.ask_list = al
        jev_json.setdefault("info", {}).update(info_questions="list", still_needed=al.keys,
                                               presented=al.presented)
    return err


async def _info_stage(facts: TurnFacts, route: str, deadline: float, jev_json: dict) -> str | None:
    """The info stage on a speaking Turn: Jev's `stated_*` (and, on chat, the `next_question`
    Choice: only the chat Writer asks) within the time left, then the fired fields' extract within
    `min(writer_timeout_s, time left)`. Sets `facts.fan_info` (a new dict, newer values win) and
    `facts.next_question`: Jev's pick while it is still missing after the extract (so the pick is
    exactly what the Writer asks, and what `asked` counts). Returns `info_error` (None when all
    ran). `lead_flag` (`lead_in`, test Mode): the lead wording (`INFO_VERSION_LEAD`) and fetishes
    is never offered (`_info_jev.askable`): a pick of it fails the Choice (`jev_failed`, no ask)."""
    lead = lead_flag(facts)
    jev_json["info_version"] = _info_jev.INFO_VERSION_LEAD if lead else _info_jev.INFO_VERSION
    left = deadline - time.monotonic()
    if left <= 0:
        return "deadline"
    choice_on = route == "chat" and facts.config["info_questions"] == "pick"
    offered = _info_jev.askable(facts.config, facts.fan_info, lead) if choice_on else []
    st = _info_jev.state(facts.state, facts.asked, offered)
    try:
        info = await _info_jev.ask(st, facts.account_id, offered, timeout_s=left, lead=lead)
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
        got = await _info_jev.extract(facts, info.fired,
                                      timeout_s=min(float(facts.config["writer_timeout_s"]), left))
    except llm_client.LLMError as e:
        return f"extract:{_outcome(e)}"
    except _info_jev.ExtractError as e:
        return f"extract:{e}"
    facts.fan_info = {**facts.fan_info, **got}
    if info.pick not in _info_jev.missing(facts.config, facts.fan_info):
        facts.next_question = None              # he just told her: nothing left to ask
    return None


async def _chain(raw: str, facts: TurnFacts, reply: dict, *, single: bool = False) -> list[str]:
    """The shared reply chain over the Writer's text; [] when it drops the draft
    (`reply["dropped_reason"]` says why). `single`: the separate caption, one bubble, never split
    (`force_single`)."""
    aid, fid = facts.account_id, facts.fan_id
    strip_emoji_on = await load_strip_emojis(aid)   # the one account-wide style read
    text, leak = await finalize_draft(raw, account_id=aid, fan_id=fid, purpose=PURPOSE,
                                      strip_emoji=strip_emoji_on, v=_voice.HER)
    reply["leak"] = leak
    if not text:
        reply["dropped_reason"] = "empty"
        return []
    flags = style_flags(facts.config)
    max_bubbles = 1 if single else STYLE_MAX_BUBBLES if flags["style_on"] else _FORMAL_MAX_BUBBLES
    words, mode = await load_banned_words(aid)
    # autoreply's protected names (autoreply.py `name_protect`), from the session fold.
    name_protect = [n for n in (facts.fan_info.get(k) for k in
                                ("real_name", "generated_nickname", "of_display_name")) if n]
    rows = facts.cut_rows
    # No echo pass (owner 2026-11-14): `_looks_like_echo` dropped natural answers that repeat his
    # words ("happy halloween" -> "happy halloween to u too"), so he got no reply. wcfi keeps its own.
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
    if flags["typo_on"]:
        protect = name_protect + (list(NONNATIVE_OUTPUTS) if flags["nonnative_on"] else [])
        # A PPV rides the last bubble: on a Turn with a Pick the cap is the shaped count, so the
        # slip still rides but no `*fix` bubble is added after her last real text (rwl fa3 S1).
        cap = len(parts) if isinstance(facts.pick, Pick) else max_bubbles
        parts = await apply_typo_throttle(aid, fid, parts, random.Random(f"{fid}:{text}"),
                                          protect=protect, max_bubbles=cap,
                                          state=reply["typo_state"])
    return parts


def _sells(route: str, facts: TurnFacts) -> bool:
    """The Turn runs the sell step: sell_now and tease (both need `sell_on`), and make_right once
    he bought something in this session (the Free item, D52: never farmed by complaining).
    ASSUMPTION: the Free item also needs the side's `sell_on` (the Sell executor's switch; with
    selling off nothing from the vault goes out). Overturned if a complaint after a Buy made with
    selling on should still get its item after selling is switched off."""
    if route in ("sell_now", "tease"):
        return True
    return route == "make_right" and bool(facts.spent) and bool(facts.config["sell_on"])


def _haggled(p: Pick, piece: Teased, same: bool, his: list[str]) -> Pick:
    """The haggle's re-offer (ticket 47): his one amount (`quoted_cents` over `his`, the Turn's
    `fan_new_messages`) clamped against the haggled row's list (`piece.list_cents`, never an earlier
    quote). The same piece records that list; a re-pick (capped at that list by `_sell`) keeps its
    own and costs at most it. Pure."""
    base = min(piece.list_cents, p.list_cents) if same else piece.list_cents   # never above today's list
    quote = full_ai_sell.clamp_quote(base, full_ai_sell.quoted_cents("\n".join(his)))
    list_cents = base if same else p.list_cents
    return replace(p, price_cents=min(list_cents, quote), list_cents=list_cents)


async def _sell(facts: TurnFacts, d: Decision, choices: dict[str, dict[str, float]],
                reply: dict | None = None) -> None:
    """The Sell executor on a sell_now, tease or Free-item make_right Turn (`_sells`): the vault (`load_rows`), the pool over the
    side's `folders` (config; empty include = all, exclude wins), the shoots and one seeded Pick
    (replayable per Turn). The ask is the Router's `asks_subject` / `asks_format` Choices
    (`choice_of`: a tie, an unoffered label or none is anything / any) at the Turn's Heat. Sets
    `facts.pick` (a Pick, or the Refusal whose need-line the Writer gets).
    A sell_now inside a Pending tease (`facts.tease`) asks for the teased subject and format
    instead: the teased piece if still in the pool (`same_piece`, at its list price), else a
    re-pick of that subject and format, else that Refusal; never an unrelated piece (ticket 07 r3).
    A `haggle` row (ticket 47) does the same for the open Offer's piece (`facts.offer_piece`), else
    the Pending tease's, and prices it `_haggled`: his one amount clamped against that row's list
    price (`offer_list_cents`, never an earlier quote). A re-pick draws only from pieces listed at
    or under that list, so a haggle never prices above what he haggled over.
    ASSUMPTION: "his newest message(s)" is the Turn's `fan_new_messages` (what Jev judged
    `counter_offer` on), so two lines naming one amount each read as two amounts (the floor).
    Overturned if only his last line counts.
    ASSUMPTION: a haggle re-pick asks at the haggle Turn's Heat (capped by that list). Overturned
    if it should reuse the haggled Offer's Heat.
    make_right draws the Free item (`pick(..., free=True)`): one item at price 0 from the pool minus
    Owned media and every media an Offer already showed him (`facts.sent`).

    Owned media is `facts.owned` (the pool expands it through the dupe groups).
    ASSUMPTION: the Free item's "unseen" drops dupe copies of seen media too (`facts.sent` goes
    through the same dupe expansion as Owned media). Overturned if a dupe of a seen item may be gifted.
    ASSUMPTION: an error past `load_rows` (the pool, shoots or the draw) is inventory_unknown, never a
    broken Turn, as `load_rows` itself fails closed. Overturned if such errors should surface.
    Sext scene (config `sext_scene`): the ask's Heat is the saved scene's (`facts.scene_now`) and a
    fresh Pick (no haggle, tease piece or Free item) aims at Jev's `offer_level` lane
    (`LEVEL_CENTS`; "any" keeps the heat target), recorded as `reply["level"]`.
    Nearest piece (config `sell_nearest` "plain" / "note", `nearest_flag`): a fresh sell_now Pick
    (no haggle, tease piece or Free item) whose ask nothing matches sells the nearest piece
    (`pick(nearest=True)`), recorded as `reply["nearest"]` = {asked_subject, asked_format, step}."""
    reply = {} if reply is None else reply
    aid = facts.account_id
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
    owned = facts.owned | facts.sent if free else facts.owned
    level_target = None
    if scene_flag(facts) and not (haggle or teased or free):
        level = router.choice_of(choices, "offer_level")
        reply["level"] = level
        level_target = full_ai_sell.LEVEL_CENTS.get(level)    # "any" -> the heat target
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
            shoots = await full_ai_sell.shoots_for(aid, pool, prints)
            got = full_ai_sell.pick(pool, shoots, ask, free=free, target=level_target,
                                    seed=full_ai_sell.seed_for(aid, str(facts.fan_id), facts.anchor_key),
                                    nearest=(nearest_flag(facts) and d.route == "sell_now"
                                             and not (haggle or teased)))
            if isinstance(got, Pick) and "asked" in got.facts:
                reply["nearest"] = {"asked_subject": ask.subject, "asked_format": ask.format,
                                    "step": got.facts["nearest"]}
        if haggle and isinstance(got, Pick):
            got = _haggled(got, teased, same is not None, facts.state["fan_new_messages"])
        facts.pick = got
    except Exception:  # noqa: BLE001 — fail closed: chat, never a half-built offer
        log.exception("full_ai sell step failed account=%s", aid)
        facts.pick = Refusal("inventory_unknown")


async def _price(facts: TurnFacts, reply: dict, deadline: float, heat: int) -> None:
    """The price Jev (`_price_jev`, config `sext_scene`) on a fresh priced sell_now Pick: Jev's price
    becomes the Pick's price and list (what a later haggle and the WAS price measure against), the
    vault's list kept in `facts["vault_list_cents"]`. Any failure keeps the list price; never fails
    the Turn. Sets `reply["price"]` = {list_cents, jev_cents, score, p, ms, error, version}."""
    p = facts.pick
    out: dict[str, Any] = {"list_cents": p.list_cents, "jev_cents": None, "score": None, "p": None,
                           "ms": None, "error": None, "version": _price_jev.PRICE_VERSION}
    reply["price"] = out
    heat = facts.scene_now["heat"] if facts.scene_now else heat
    st = _price_jev.state(facts.state, heat, scene_words(facts.scene_now),
                          facts.state.get("purchases") or [], p)
    try:
        got = await _price_jev.ask(st, facts.account_id, timeout_s=deadline - time.monotonic())
    except router.GateError as e:
        out["error"] = str(e)[:300] or "GateError"
        return
    out.update(jev_cents=got.cents, score=got.score, p=got.p, ms=got.ms)
    facts.pick = replace(p, price_cents=got.cents, list_cents=got.cents,
                         facts={**(p.facts or {}), "vault_list_cents": p.list_cents})


async def _claim_audit(d: Decision, facts: TurnFacts, reply: dict, writer: str, parts: list[str],
                       pick: Pick, deadline: float) -> list[str]:
    """The Claim audit + price check on the chain's final text (ticket 45): pass -> `parts`; fail ->
    one rewrite by the Writer that answered (same messages, `write` with `min(its own, remaining)`)
    through the same chain, its attempts appended with `rewrite: true`; a second failure, or less
    than one `writer_timeout_s` left before the Turn deadline -> `fallback_caption`. Sets
    `reply["caption_fallback"]` and `reply["claim_fail"]` (one `{check: claim|price, text}` per
    failed check of the first text and the rewrite; [] on a first pass). A caption not sent leaves no trace on the row: `leak` /
    `dropped_reason` stay as the first chain set them, and `typo_state` is the state the shipped
    text's chain left (the Turn's starting state for the fallback caption, which has no typos).
    ASSUMPTION: the rewrite regenerates with the same messages (no correction note): story 32 says
    "regenerated once" and no old claim-correction wording exists. Overturned if the owner wants
    the house re-ask shape (old ai_chatter's assistant + user correction turn).
    ASSUMPTION: "too little time" is less than one `writer_timeout_s` left (the ticket's deadline
    case). Overturned if a shorter rewrite window should still be tried."""
    kind = "free" if not pick.price_cents else "tease" if d.route == "tease" else "offer"
    price = pick.price_cents if kind == "offer" else None

    def ok(ps: list[str]) -> bool:
        text = "\n".join(ps)
        fails = [c for c, good in (("claim", full_ai_sell.claim_ok(text, pick)),
                                   ("price", full_ai_sell.price_ok(text, price))) if not good]
        reply["claim_fail"] = reply["claim_fail"] + [{"check": c, "text": text} for c in fails]
        return not fails

    reply["caption_fallback"], reply["claim_fail"] = False, []
    if ok(parts):
        return parts
    if deadline - time.monotonic() >= float(facts.config["writer_timeout_s"]):
        again = await write(d, facts, deadline=deadline, writers=[writer])
        reply["attempts"] = reply["attempts"] + [{**a, "rewrite": True} for a in again.attempts]
        if again.text is not None:
            # A scratch reply: the rewrite's chain marks the row only if its text ships.
            scratch = {"leak": [], "dropped_reason": None, "typo_state": dict(facts.typo_state)}
            text = cat_stickers.parse_marker(again.text)[0]     # the first reply's gif stays
            redo = await _chain(text, facts, scratch) if text else []
            if redo and not scratch["leak"] and ok(redo):
                reply.update(scratch)
                return redo
    reply["typo_state"] = dict(facts.typo_state)
    reply["caption_fallback"] = True
    return [full_ai_sell.fallback_caption(pick, kind)]


def _ppv_turn(d: Decision, facts: TurnFacts) -> bool:
    """The Turn sends a PPV the separate caption may write: a priced sell_now Pick or make_right's
    Free item, in a Mode that sends (shadow records only and stays on today's path)."""
    p = facts.pick
    return (facts.config.get("caption_writer") == "caption" and sender_for(facts.mode) is not None
            and isinstance(p, Pick)
            and ((d.route == "sell_now" and p.price_cents > 0) or (d.route == "make_right" and not p.price_cents)))


async def _caption(d: Decision, facts: TurnFacts, reply: dict, pick: Pick, deadline: float) -> str | None:
    """`caption_writer` "caption": the separate caption call (`full_ai_caption`), keeping one
    `writer_timeout_s` of the Turn for the chat Writer, through the shared chain as one bubble
    (`_chain(single=True)`), then the Claim audit's checks (claim_ok + price_ok). Fail -> one rewrite
    by the Writer that answered (same messages) when two `writer_timeout_s` are left; still failing
    -> None, and the Turn runs today's path (the chat Writer's caption). Sets `reply["caption"]` =
    {writer: caption | chat, model, outcome, ms, attempts} and, on a pass, `reply["typo_state"]`
    to the state the caption's chain left (the chat bubbles' chain then starts from it).
    Outcomes: ok | rewrite_ok | no_description | no_writer | failed | late.
    ASSUMPTION: "no Writer answered" goes straight to today's path (no rewrite: nothing to redo).
    Overturned if the owner wants a second walk."""
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
        parts = await _chain(text, facts, scratch, single=True)
        line = parts[0] if len(parts) == 1 and not scratch["leak"] else None
        if line is not None and not (full_ai_sell.claim_ok(line, pick) and full_ai_sell.price_ok(line, price)):
            line = None
        return line, scratch

    msgs = full_ai_caption.messages(facts, pick, was)
    if msgs is None:
        return done("no_description")
    res = await full_ai_caption.write(facts, msgs, deadline=deadline - budget)
    cap["attempts"], cap["model"] = res.attempts, res.writer
    if res.text is None:
        return done("no_writer")
    line, scratch = await shaped(res.text)
    outcome = "ok"
    if line is None:
        if deadline - time.monotonic() < 2 * budget:
            return done("late")
        again = await full_ai_caption.write(facts, msgs, deadline=deadline - budget, writers=[res.writer])
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
    """The chat bubbles, then the separate caption (the PPV rides it, `parts[-1]`). Their joined
    text must pass the Claim audit's checks too; when it doesn't the chat bubbles are dropped and
    the caption ships alone (`reply["caption"]["outcome"]` "alone", `typo_state` back to the
    caption's chain left, `typo_state`). Sets `reply["caption_fallback"]` False (the audit's flag: no fallback caption).
    ASSUMPTION: a failed chat bubble drops itself, not the passed caption (no third LLM call).
    Overturned if the owner prefers today's path then."""
    reply["caption_fallback"] = False
    joined = "\n".join([*parts, caption])
    if full_ai_sell.claim_ok(joined, pick) and full_ai_sell.price_ok(joined, pick.price_cents or None):
        return [*parts, caption]
    reply["caption"]["outcome"] = "alone"
    reply["typo_state"] = typo_state
    return [caption]


def _gif_part(raw: str, facts: TurnFacts, offered: bool = True) -> tuple[str, dict | None]:
    """The Writer's text with every sticker marker stripped, and its `{gif, tag}` part when GIFs
    are on, the prompt offered the sticker block (`offered`, `gif_offered`) and the tag has a gif
    (seeded per Turn, so a replay picks the same one)."""
    text, tag = cat_stickers.parse_marker(raw)
    if not facts.config.get("gifs") or not offered:
        return text, None
    # The shared no-same-reaction-twice rule; it bites once a sender records the gif
    # (`mark_sent`, live 04a). Test records none, so a test session may repeat a tag.
    tag = cat_stickers.keep_tag(facts.account_id, facts.fan_id, tag, has_text=bool(text))
    if tag is None:
        return text, None
    gid = cat_stickers.pick_gif(tag, random.Random(f"gif:{facts.account_id}:{facts.fan_id}:{facts.anchor_key}"),
                                account_id=facts.account_id, fan_id=facts.fan_id,
                                voice=_voice.VOICE_HER)
    return text, ({"gif": gid, "tag": tag} if gid else None)


async def run_turn(facts: TurnFacts) -> TurnResult:
    """Decide, write, shape and record one Turn. Raises `full_ai_test.Conflict` when the Turn
    is not the session's next one or already has its row."""
    t0 = time.perf_counter()
    # One Turn deadline every LLM stage shares (spec › Contracts › One Turn bound). The Router
    # runs first, so its own 10 s always fits the >= 30 s bound; later stages are capped by it.
    deadline = time.monotonic() + turn_bound_s(facts.config)
    d, jev_json, model, ms, error = await _route(facts)
    reply: dict[str, Any] = {
        "parts": [], "attempts": [], "floor_reason": None, "dropped_reason": None, "leak": [],
        "side": facts.side, "config_rev": facts.config_rev, "wait_s": None, "turn_ms": None,
        "fan_info": facts.fan_info, "asked": facts.asked, "typo_state": dict(facts.typo_state),
        "info_error": None}
    if facts.photo is not None:
        reply["fan_photo"] = facts.photo
    if scene_flag(facts):
        # The saved scene (owner-ordered save state, ADR-0032 named exception): Jev's `scene_stage`
        # (None on its default or a tie) folded over the newest row's; None ends it.
        on = scene_turn(d, facts)
        facts.scene_now = scene_next(facts.scene, on, router.choice_or_none(jev_json["choices"], "scene_stage"),
                                     d.heat)
        reply["scene"] = facts.scene_now
    row: dict[str, Any] = {
        "account_id": facts.account_id, "fan_id": facts.fan_id, "mode": facts.mode,
        "trigger_kind": full_ai_test.TRIGGER_KIND, "trigger_key": facts.anchor_key,
        "arm": arm_of(facts.account_id, facts.fan_id), "salt_ver": SALT_VER,
        "route": d.route, "heat": d.heat, "route_row": d.row,
        "question_version": router.question_version(facts.mode), "router_model": model, "writer_model": None,
        "jev_json": jev_json, "jev_ms": ms, "jev_error": error, "status": "failed",
        "reply_json": reply}
    writer, parts = None, []
    if d.route == "no_send":
        row["status"] = "no_send"
    else:
        reply["info_error"] = await _info(facts, d.route, deadline, jev_json)
        reply["fan_info"] = facts.fan_info
        if _sells(d.route, facts):
            # The sell step gets the Turn's time left (03b: min(own, remaining), no own bound).
            # ASSUMPTION: a cut dupe read's `asyncio.to_thread` clustering finishes in the background
            # (read-only, one per cut Turn). Overturned if cut Turns pile up executor threads.
            try:
                await asyncio.wait_for(_sell(facts, d, jev_json["choices"], reply),
                                       deadline - time.monotonic())
            except asyncio.TimeoutError:
                log.warning("full_ai sell step past the Turn deadline account=%s", facts.account_id)
                facts.pick = Refusal("inventory_unknown")
            if isinstance(facts.pick, Refusal):
                reply["refusal"] = facts.pick.reason
            elif scene_flag(facts) and d.route == "sell_now" and d.row != "haggle" and facts.pick.price_cents:
                await _price(facts, reply, deadline, d.heat)
        pick = facts.pick if isinstance(facts.pick, Pick) else None
        caption = await _caption(d, facts, reply, pick, deadline) if _ppv_turn(d, facts) else None
        caption_typos = dict(reply["typo_state"])
        res = await write(d, facts, deadline=deadline, plain=caption is not None)
        reply["attempts"], reply["floor_reason"] = res.attempts, res.floor_reason
        gif = None
        if res.text is not None:
            text, gif = _gif_part(res.text, facts, gif_offered(d, facts))
            # A sticker-only reply skips the chain: the gif is the whole reply.
            parts = await _chain(text, facts, reply) if text or gif is None else []
        if pick is not None and reply["leak"]:      # a guarded reply never carries a paid attachment
            reply["offer_dropped"], pick = "leak", None
        elif pick is not None and res.text is not None and not parts:
            reply["offer_dropped"] = "shape"        # the reply chain dropped her text, or a lone gif
        elif pick is not None and parts and caption is not None:
            parts = _with_caption(reply, parts, caption, pick, caption_typos)
        elif pick is not None and parts:            # her text must claim only what the PPV holds
            parts = await _claim_audit(d, facts, reply, res.writer, parts, pick, deadline)
        if parts or (gif and not text):            # a dropped draft fails, gif or not
            writer = res.writer
            row["writer_model"] = writer
            reply["wait_s"] = full_ai_test.hold(facts.config, facts.anchor_key)
            send = sender_for(facts.mode)
            if send is not None:                    # shadow records only
                over = facts.offer_piece.row_id if d.row == "haggle" and facts.offer_piece else None
                desc = (str(pick.facts.get("description") or "") or None
                        if pick is not None and scene_flag(facts) else None)
                send(row, parts, pick, over=over, **({"desc": desc} if desc else {}))
                if gif:
                    reply["parts"].append(gif)
            if facts.next_question and parts:       # the ask went out in her text (not a lone gif)
                reply["asked"] = {**facts.asked,
                                  facts.next_question: facts.asked.get(facts.next_question, 0) + 1}
            elif facts.ask_list is not None and parts:
                reply["asked"] = _info_jev.mark_asked(facts.asked, facts.ask_list)
    reply["turn_ms"] = int((time.perf_counter() - t0) * 1000)
    row_id = await full_ai_test.record(row)
    return TurnResult(row_id, d, reply["parts"], writer, reply["attempts"], reply["wait_s"],
                      row["status"], full_ai_test.offer_of(row), reply.get("caption"),
                      reply.get("scene"), reply.get("price"), reply.get("dropped_reason"))
