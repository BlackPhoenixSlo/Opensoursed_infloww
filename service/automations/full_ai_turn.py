"""automations/full_ai_turn.py — Full AI Chat's shared Turn pipeline, one for every Mode.

  load_turn_facts(account, fan, anchor, mode, *, session=None, side=None, photo=None) -> TurnFacts
  TurnIO                 one Mode's I/O: trigger_kind, hold, send (None = records only), record
  run_turn(facts, io=None) -> TurnResult   io None = full_ai_test.IO (the Test chat)

`run_turn`, in order: Router Jev (`_router_jev.ask`; a `GateError` is chat at Heat 1, row
`jev_failed`) and `decide_turn` with the side's route flags; on a speaking Route the info stage
(`_info_jev`: what he stated, the fired fields' extract, the next question, or with the side's
`info_questions: "list"` wcfi's whole still-need list and its ask call; a failure sets
`reply_json.info_error` and the reply is still written); the Route's Writer
(`full_ai_writers.write`); the shared reply chain `finalize_draft` -> `shape_parts` ->
`apply_typo_throttle` (docs/prompts/post-processing.md); then the Mode's sender and its record.
`reply_json.asked` counts the fact her text's `ASKED:` line named (NEW-168) once every part landed;
asks only on route chat, which no rewrite check touches.
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
swap or a dropped turn sends no PPV (`reply_json.offer_dropped` `leak` | `shape`, the fallback caption
dropped by the chain too; `claim`: a ride whose text failed the Claim audit twice). One Pick per Turn
at most. A text bubble set riding a Pick then passes the Claim audit + price check (`_claim_audit`,
ticket 45): one rewrite through the same chain, then `full_ai_sell.fallback_caption` through the
chain (`reply_json.caption_fallback`).
On a Route sext Turn with `floor_on` the Heat check (`_heat_check`, spec 06) scores her final text
(`_heat_jev`, one Score) against the Heat the Writer got and rewrites it once when over
(`reply_json.heat_check`); no Mode check, never a dropped reply.
On row `offer_details` (spec offer-details D) the Offer answer check (`full_ai_offer_turn.offer_check`) runs on her
final text instead: one rewrite, then `full_ai_offer_details.offer_fallback` through the chain, also
when the Writer walk or the chain left no text; `reply_json.offer_details` records the resolved
Offer and the outcome.
`hold_with_typing` and the DM rate are the Mode's transport's to call, and test calls neither.
A `STICKER: <tag>` line is always stripped from the Writer's text before the chain
(`cat_stickers.parse_marker`); with `config.gifs` on, its tag becomes a `{gif, tag}` part after her
text bubbles (or the whole reply), the giphy id from `cat_stickers.pick_gif`.

Guard set, declared at the one `finalize_draft` call: no consistency check and
`strip_emoji=strip_emoji_on`: the side's `strip_emojis` (every Mode) or else the account-wide flag
(autoreply's `(False, "flag")`, pinned in test_outbound.py). Every other style switch comes from the
side's config (`style`), never from `_style_flags`, so a draft-only style change reaches only the
draft window.

Sends nothing itself: no direct import of an OF client, executor, lease, DM rate or OF write module
(AST scan + runtime send traps in test_full_ai_test_chat.py; shared helpers load them transitively).
"""
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
    tips: list[int] = field(default_factory=list)   # his tips, cents (live: `transactions` kind tip); spend line only, never pricing
    sent: set[int] = field(default_factory=set)     # media an Offer showed him (test: `sent_media_of`)
    # The Pending tease's piece, else None (test: `full_ai_test.teased_of`). `offer` is the open
    # priced Offer's line; the two are separate.
    tease: Teased | None = None
    # The open priced Offer's piece with its list price, else None (test: `teased_of(open_offer_of)`):
    # what a haggle re-offers (ticket 47).
    offer_piece: Teased | None = None
    # His attached image in test (`full_ai_test.fetch`), landing on the row as `reply_json.fan_photo`.
    photo: dict | None = None
    # One of her last `DARED_ROWS` replies carried her dare (`full_ai_test.dared_of`): his
    # picture is read whatever `describe_fan_photos` says, and she does not dare twice (NEW-156).
    dared: bool = False
    # Her newest reply was the bot-check joke and no dare stands (`full_ai_test.dare_due_of`): this
    # Turn dares (NEW-160), and his picture is read as under `dared`.
    dare_due: bool = False
    # Sext scene (config `sext_scene`, test Mode): the saved scene the newest row left
    # (`full_ai_test.fetch`), and this Turn's (`full_ai_scene.scene_next`, set by `run_turn`).
    scene: dict | None = None
    scene_now: dict | None = None
    # Chat tease (config `chat_tease`, test Mode): his settled Offers in words (`full_ai_test.purchases_of`),
    # read by the tease price Jev; [] without the flag.
    purchases: list = field(default_factory=list)
    # The Offer ask (`full_ai_offer_details.OfferAsk`, spec offer-details B): what the Offer
    # resolver reads; built by both loaders, read by `run_turn` on row `offer_details`.
    offer_ask: OfferAsk = field(default_factory=OfferAsk)
    # Row `offer_details` (spec C): the resolved Offer's facts the Writer answers from, set by
    # `run_turn` (`full_ai_offer_turn.offer_resolved`); None when no Offer resolved.
    offer_facts: OfferFacts | None = None


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
    dropped_reason: str | None = None   # why no text shipped: empty | echo | banned (chain) | leak | claim (`_claim_audit`)
    heat_check: dict | None = None  # `reply_json.heat_check` (`_heat_check`): her level vs the Turn's Heat


async def stored_config(account_id: str) -> dict:
    """The Creator's Full AI config through the pure merge: an empty store gives `DEFAULTS` on
    both sides. A blob that will not read (`full_ai_config.loaded`) raises ValueError (live claims nobody
    then: `full_ai_owner_io._checkpoint`)."""
    async with get_session() as s:
        row = await s.get(AccountAiConfig, str(account_id))
    got = loaded(row.full_ai_config_json if row is not None else None)
    if got is None:
        raise ValueError(f"unreadable Full AI config account={account_id}")
    return got


async def load_turn_facts(account, fan, anchor, mode, *, session=None, side=None, photo=None,
                          reply_to_n=None) -> TurnFacts:
    """The Turn's facts. Test: `fan` is the pair, `anchor` his line, `side` the config side;
    read off the session's own rows (`full_ai_test.fetch`) with that side of the stored config;
    `reply_to_n` the owner's Quote-reply mark (the Offer ask's `quote_row_id`).
    The Test chat's loader only (live loads with `full_ai_live.load`)."""
    if mode == "test":
        cfg = await stored_config(account)
        facts = await full_ai_test.fetch(account, fan, side, anchor, cfg[side], photo, reply_to_n=reply_to_n)
        facts.config_rev = cfg["rev"]
        return facts
    raise NotImplementedError(f"load_turn_facts: Test chat only, not {mode!r}")


@dataclass(frozen=True)
class TurnIO:
    """One Mode's I/O (04a seam): the spine calls it, never imports the Mode's module."""
    trigger_kind: str                    # test | inbound
    hold: Callable[[dict, str], float]   # (config, anchor_key) -> reply wait in s; drawn, never slept
    send: Callable[..., Awaitable[None]] | None   # (row, parts, pick, *, over=None, desc=None, gif=None); None = records only
    record: Callable[[dict], Awaitable[int]]      # row dict -> ai_decisions.id


# The price Jevs stop this long before the Turn deadline, so their own timeout (a GateError: the
# Pick keeps its list price, the row says why) fires before `run_turn`'s sell cap (rwl-a N4).
_PRICE_MARGIN_S = 0.5


def _freed(aw):
    """A provider wait (Router / Jev ask, Writer walk, extract) off the Run slot (`run_slot.freed`):
    a live Turn holds a slot for its reads, shaping and sends only, so Fans waiting on a model do
    not pin the fleet's slots. A plain await in the Test chat (no slot)."""
    return run_slot.freed(aw, budget_s=INLINE_MAX_S)


async def _capped(call, deadline: float) -> WriteResult:
    """A Writer walk (`write` / `full_ai_caption.write`) cancelled at `deadline`: then it reads as
    no Writer answering (one `turn` / `timeout` attempt), never a late text. With no time left the
    walk itself makes no try (`walk`)."""
    left = deadline - time.monotonic()
    if left <= 0:
        return await call
    try:
        return await _freed(asyncio.wait_for(call, left))
    except asyncio.TimeoutError:
        return WriteResult(None, None, [{"writer": "turn", "outcome": "timeout", "ms": int(left * 1000)}])
    finally:
        call.close()    # a lost slot never started the walk: no "never awaited" warning (done: a no-op)


async def _route(facts: TurnFacts, deadline: float) -> tuple[Decision, dict, str | None, int | None, str | None]:
    """Router Jev (wall-clock capped at `router.WALL_S` and `deadline`) and the Route table:
    (decision, jev_json, router model, Jev ms, Jev error)."""
    try:
        jev = await _freed(router.ask(facts.state, facts.account_id, mode=facts.mode, scene=scene_flag(facts),
                                      spacing=spacing_flag(facts), likes=likes_flag(facts),
                                      tease=tease_flag(facts), implied=implied_flag(facts),
                                      timeout_s=deadline - time.monotonic()))
        fired, intensity, error = router.fired(jev.answers, facts.mode), jev.intensity, None
        answers, score, model, ms = jev.answers, {"score": jev.intensity, "p": jev.intensity_p}, jev.model, jev.ms
        choices = jev.choices
    except router.GateError as e:                   # never a "no": chat, Heat 1
        fired, intensity, error = frozenset(), 0.0, str(e) or type(e).__name__
        answers, score, model, ms = None, None, None, None
        choices = None
    cfg = facts.config
    # DRAFT gate (ticket 47): test / live (`full`) and the side's `draft_questions`; Shadow never.
    d = decide_turn(Facts(fired=fired, intensity=intensity, pending_offer=facts.offer is not None,
                          pending_tease=facts.tease is not None, jev_ok=error is None,
                          sell_on=bool(cfg["sell_on"]), sext_on=bool(cfg["sext_on"]),
                          open_offer=facts.offer_piece is not None,
                          draft_on=full(facts.mode) and bool(cfg["draft_questions"]),
                          scene=scene_flag(facts), chat_tease=tease_flag(facts),
                          offer_details=full(facts.mode)))
    jev_json = {"answers": answers, "intensity": score, "fired": sorted(fired), "state": facts.state,
                "choices": choices}   # 03b: test Mode's Choices, read by `_sell` only
    return d, jev_json, model, ms, error


async def _info(facts: TurnFacts, route: str, deadline: float, jev_json: dict, *,
                ask: bool = True) -> str | None:
    """`_info_stage`, then with `info_questions: "list"` on chat `facts.ask_list` over the fold it
    left (Jev failed or out of time included: the list needs no Jev), recorded on `jev_json.info`.
    `ask=False` (row `offer_details`): what he stated is still extracted, nothing is asked."""
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
    """The info stage on a speaking Turn: Jev's `stated_*` (and, on chat, the `next_question`
    Choice: only the chat Writer asks) within the time left, then the fired fields' extract within
    `min(writer_timeout_s, time left)`. Sets `facts.fan_info` (a new dict, newer values win) and
    `facts.next_question`: Jev's pick while it is still missing after the extract (so the pick is
    exactly what the Writer asks, and what `asked` counts). Returns `info_error` (None when all
    ran). `lead_flag` (`lead_in`, test Mode): the lead wording (in `info_version(lead, likes)`) and fetishes
    is never offered (`_info_jev.askable`): a pick of it fails the Choice (`jev_failed`, no ask).
    `likes_flag` (`he_likes`, test Mode): the extract carries `LIKES_EXTRACT`, in the digest too.
    `wide_flag` (`info_wide`, test Mode): `stated_hobbies` takes `STATED_WIDE`'s wording and the
    extract carries `HOBBIES_EXTRACT`, in the digest too."""
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
        facts.next_question = None              # he just told her: nothing left to ask
    return None


async def _chain(raw: str, facts: TurnFacts, reply: dict, *, single: bool = False,
                 typos: bool = True) -> list[str]:
    """The shared reply chain over the Writer's text; [] when it drops the draft
    (`reply["dropped_reason"]` says why). `single`: the separate caption, one bubble, never split
    (`force_single`). `typos` False: no typo pass (the disclosing fallback caption)."""
    aid, fid = facts.account_id, facts.fan_id
    # The side's `strip_emojis` (every Mode), else the one account-wide style read.
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
    if flags["typo_on"] and typos:
        protect = name_protect + (list(NONNATIVE_OUTPUTS) if flags["nonnative_on"] else [])
        # A PPV rides the last bubble: on a Turn with a Pick the cap is the shaped count, so the
        # slip still rides but no `*fix` bubble is added after her last real text (rwl fa3 S1).
        cap = len(parts) if isinstance(facts.pick, Pick) else max_bubbles
        parts = await apply_typo_throttle(aid, fid, parts, random.Random(f"{fid}:{text}"),
                                          protect=protect, max_bubbles=cap,
                                          state=reply["typo_state"], reply_rate=typo_rate(facts.config))
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
    own and costs at most it. A final folder price wins after (`hold_folder_price` in `_sell`). Pure."""
    base = min(piece.list_cents, p.list_cents) if same else piece.list_cents   # never above today's list
    quote = full_ai_sell.clamp_quote(base, full_ai_sell.quoted_cents("\n".join(his)))
    list_cents = base if same else p.list_cents
    return replace(p, price_cents=min(list_cents, quote), list_cents=list_cents)


def _told_format(got: Pick | Refusal, choices: dict[str, dict[str, float]] | None, reply: dict,
                 free: bool, mode: str | None) -> Pick | Refusal:
    """A final Pick none of whose locked items is of this Turn's `asks_format` (photo / video;
    `full_ai_sell.real_formats`, so a photo + video set asked as a video is no miss) is tagged as
    not what he asked for (client rule 2026-11-16, M1): `facts["asked"]` = {subject: this Turn's
    `asks_subject`, format: the asked one}, `facts["nearest"]` "format", recorded on
    `reply["nearest"]` as the nearest path does. Test / live Mode only (Shadow unchanged). Never on
    a Refusal, a ride, a Free item, or a Pick already tagged. Pure apart from `reply`."""
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
    """A yes to the open card that names nothing else (M2 2026-11-16): test / live Mode, row sell,
    an open Offer (`facts.offer_piece`), says_yes_to_offer fired, and this Turn's ask names no other
    piece: `asks_subject` "anything" or the card's subject, `asks_format` "any" or the card's
    (`full_ai_sell.kind_of`: photo / video, a moving kind being video, a voice note neither).
    wants_content does not matter (the Router counts "send it" / "how do i unlock it" as an ask).
    "yes send me a feet video" over a photo card names another piece: today's path. Pure."""
    piece = facts.offer_piece
    if not (full(facts.mode) and d.row == "sell" and piece and "says_yes_to_offer" in d.fired):
        return False
    subject, fmt = router.choice_of(choices, "asks_subject"), router.choice_of(choices, "asks_format")
    card = full_ai_sell.kind_of(piece.format)          # a voice note is neither photo nor video
    return subject in ("anything", piece.subject) and fmt in ("any", card)


async def _sell(facts: TurnFacts, d: Decision, choices: dict[str, dict[str, float]],
                reply: dict | None = None, deadline: float | None = None) -> None:
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
    A fresh sell_now Pick (no Chat tease) also skips the open Offer's media (`facts.offer_piece`): a yes
    to it never re-sends the same piece (ticket 90); a tease may still re-tease it.

    Owned media is `facts.owned` (the pool expands it through the dupe groups).
    ASSUMPTION: the Free item's "unseen" drops dupe copies of seen media too (`facts.sent` goes
    through the same dupe expansion as Owned media). Overturned if a dupe of a seen item may be gifted.
    ASSUMPTION: an error past `load_rows` (the pool, shoots or the draw) is inventory_unknown, never a
    broken Turn, as `load_rows` itself fails closed. Overturned if such errors should surface.
    Sext scene (config `sext_scene`): the ask's Heat is the saved scene's (`facts.scene_now`) and a
    fresh Pick (no haggle, tease piece or Free item) aims at Jev's `offer_level` lane
    (`LEVEL_CENTS`; "any" keeps the heat target), recorded as `reply["level"]`; a Chat tease aims at
    "soft" instead (recorded so).
    Nearest piece (config `sell_nearest` "plain" / "note", `nearest_flag`): a fresh sell_now Pick
    (no haggle, tease piece or Free item) whose ask nothing matches sells the nearest piece
    (`pick(nearest=True)`), recorded as `reply["nearest"]` = {asked_subject, asked_format, step}.
    Bundle (config `sell_bundle`, `bundle_of`, 03d): the same fresh Pick passes `bundle="fill"` (up to
    5 photos, filled to 3); everything else keeps `"shoot"`, today's Pick.
    Asked count (config `sell_count`, `count_flag`): the same fresh sell_now Pick asks with
    `count=full_ai_sell.asked_count` over his new messages (the Turn's `fan_new_messages`, as
    `_haggled` reads them): a clip sells with more clips at their summed list, a filled photo set fills
    to it (`pick`); recorded as `reply["asked_count"]` when one was read. Everything else asks with none.
    Chat tease (config `chat_tease`, `tease_turn`: row chat_tease, or a not-hot offer_moment), on a
    fresh Pick (no Pending tease; with one the teased piece is re-sold at its price as today): first
    the tease price Jev (`_tease_price`, before the pick: the photo count depends on the price),
    then always a ride (`pick(ride=True)`, photos only) drawn only from soft-lane photos (list at
    most `LEVEL_CENTS["soft"]`; at price 0 only ones passing the free guard `_free_safe`; none:
    Refusal("no_match")) of up to `full_ai_sell.tease_photos(cents)` photos (one when free) at Jev's
    price (0 = free, sent unlocked as a Free item; the vault list kept in `facts["vault_list_cents"]`),
    recorded as `reply["ride"]` = True (kept if the Offer is later dropped, as `reply["nearest"]`
    is); never the Offer price Jev. Jev failing:
    Refusal("no_match"), a plain chat reply (`messages_for` adds no need-line on a tease Turn).
    The Offer price Jev (`_price`) runs here, last, on a fresh priced sell_now Pick only.
    `deadline`: the Turn's; both price Jevs stop `_PRICE_MARGIN_S` before it. A ride whose text fails the Claim audit twice
    sends only its bubbles claiming no media and no price, without the photos (`_claim_audit`).
    Not what he asked for (client rule 2026-11-16): a final priced Pick on any path (haggle, tease
    piece, fresh), never a ride or a Free item, test / live only, holding no item of this Turn's
    photo / video `asks_format` is tagged `facts["asked"]` / `facts["nearest"]` "format" and recorded on
    `reply["nearest"]` (`_told_format`), so the Writer tells him and the Claim audit checks it.
    A yes to the open card naming nothing else (`_yes_to_open`, test / live Mode): Refusal("offer_open")
    before any vault load, `reply["offer_open"]` = that Offer's row id; the Writer points him at the
    locked card and nothing new is sent."""
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
    fresh = not (haggle or teased or free)     # a new piece: no haggle, tease piece or Free item
    if fresh and _yes_to_open(d, facts, choices):
        # A yes to the open card: point him at it, never a different piece (M2 2026-11-16).
        facts.pick = Refusal("offer_open")
        reply["offer_open"] = facts.offer_piece.row_id
        return
    owned = facts.owned | facts.sent if free else facts.owned
    if fresh and facts.offer_piece and d.route == "sell_now" and not tease_turn(d, facts):   # a yes never re-sends it
        owned = owned | set(facts.offer_piece.locked) | set(facts.offer_piece.previews)
    # One lane: a Chat tease takes the soft lane over Jev's `offer_level`.
    level = router.choice_of(choices, "offer_level") if scene_flag(facts) and fresh else None
    if fresh and tease_turn(d, facts):
        level = "soft"
    if scene_flag(facts) and fresh:
        reply["level"] = level                                  # the lane used
    level_target = full_ai_sell.LEVEL_CENTS.get(level) if level else None   # "any" -> the heat target
    tease_cents = None
    if tease_turn(d, facts) and fresh:
        tease_cents = await _tease_price(facts, heat, reply, jev_by)
        if tease_cents is None:                 # the tease price Jev failed: no tease this Turn
            facts.pick = Refusal("no_match")
            return
    if fresh and d.route == "sell_now" and tease_cents is None and count_flag(facts):   # never on a ride
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
            if tease_cents is not None:     # a Chat tease rides soft photos only; free ones pass the free guard
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
        got = full_ai_sell.hold_folder_price(got)   # the one folder-price-final clamp (rwl3 A9)
        got = _told_format(got, choices, reply, free, facts.mode)
        facts.pick = got
    except Exception:  # noqa: BLE001 — fail closed: chat, never a half-built offer
        log.exception("full_ai sell step failed account=%s", aid)
        facts.pick = Refusal("inventory_unknown")
        return
    if (scene_flag(facts) and fresh and d.route == "sell_now" and tease_cents is None
            and isinstance(facts.pick, Pick) and facts.pick.price_cents):
        # Rows here: sell, offer_moment, scene_offer. He asked (wants_content, or yes to a Pending
        # offer) exactly on row sell: its Pending-tease case is not fresh, later rows mean sell missed.
        await _price(facts, reply, jev_by, d.heat, d.row == "sell")


async def _tease_price(facts: TurnFacts, heat: int, reply: dict, deadline: float) -> int | None:
    """The tease price Jev (`_price_jev.ask_tease`, config `chat_tease`) over the side's
    `chat_tease_prices`: the price in cents, or None on any failure (never fails the Turn). Sets
    `reply["chat_tease"]` = {cents, p (option -> probability), ms, error, version, options (the
    prices offered, in cents)}."""
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
    """The price Jev (`_price_jev`, config `sext_scene`) on a fresh priced sell_now Pick (`_sell` calls
    it: no haggle, Pending tease piece, Free item, Chat tease or ride): Jev's price
    becomes the Pick's price and list (what a later haggle and the WAS price measure against), the
    vault's list kept in `facts["vault_list_cents"]`. Any failure keeps the list price; never fails
    the Turn. Sets `reply["price"]` = {list_cents, jev_cents, score, p, ms, error, version, he_asked,
    bought_before}. Price signals (03d): `he_asked` is the caller's (row sell: wants_content fired,
    or says_yes_to_offer with a Pending offer); he bought before once any Offer was bought."""
    p = facts.pick
    if (saved := full_ai_sell.folder_price(p)) is not None:   # final: `_sell` already clamped it
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
    """The Claim audit + price check on the chain's final text (ticket 45): pass -> `parts`; fail ->
    one rewrite by the Writer that answered (same messages, `write` with `min(its own, remaining)`)
    through the same chain, its attempts appended with `rewrite: true`; a second failure, or less
    than one `writer_timeout_s` left before the Turn deadline -> `fallback_caption` through the chain
    as one bubble (no typo pass on a Pick not what he asked for: its disclosure ships intact; dropped by it -> [] and `reply["offer_dropped"]` "shape" | "leak": no PPV); on a
    ride Pick (`is_ride`, a Chat tease) instead her first text's bubbles that claim no media and no
    price, as a plain chat reply with no PPV (`reply["offer_dropped"]` = "claim": the caller sends no
    Pick; `fallback_caption` would name the photos and the price). Sets
    `reply["caption_fallback"]` and `reply["claim_fail"]` (one `{check: claim|price|disclose, text}` per
    failed check of the first text and the rewrite; [] on a first pass; `disclose` =
    `full_ai_sell.discloses`: a Pick not what he asked for must say so). A caption not sent leaves no trace on the row: `leak` /
    `dropped_reason` stay as the first chain set them, and `typo_state` is the state the shipped
    text's chain left; but when nothing ships `dropped_reason` says why: the fallback's chain
    reason (`leak` on a leak), or `claim` on a ride with no bubble left.
    ASSUMPTION: the rewrite regenerates with the same messages (no correction note): story 32 says
    "regenerated once" and no old claim-correction wording exists. Overturned if the owner wants
    the house re-ask shape (old ai_chatter's assistant + user correction turn).
    ASSUMPTION: "too little time" is less than one `writer_timeout_s` left (the ticket's deadline
    case). Overturned if a shorter rewrite window should still be tried."""
    kind = "free" if not pick.price_cents else "tease" if d.route == "tease" else "offer"
    price = pick.price_cents if kind == "offer" else None

    def ok(ps: list[str]) -> bool:
        text = "\n".join(ps)
        fails = full_ai_sell.caption_fails(text, pick, price, differs=False)   # rides chat bubbles: no "terms"
        reply["claim_fail"] = reply["claim_fail"] + [{"check": c, "text": text} for c in fails]
        return not fails

    reply["caption_fallback"], reply["claim_fail"] = False, []
    if ok(parts):
        return parts
    if deadline - time.monotonic() >= float(facts.config["writer_timeout_s"]):
        again = await _capped(write(d, facts, deadline=deadline, writers=[writer]), deadline)
        reply["attempts"] = reply["attempts"] + [{**a, "rewrite": True} for a in again.attempts]
        if again.text is not None:
            # A scratch reply: the rewrite's chain marks the row only if its text ships.
            scratch = {"leak": [], "dropped_reason": None, "typo_state": dict(facts.typo_state)}
            text = cat_stickers.parse_marker(again.text)[0]     # the first reply's gif stays
            redo = await _chain(text, facts, scratch) if text else []
            if redo and not scratch["leak"] and ok(redo):
                reply.update(scratch)
                return redo
    if is_ride(pick):       # no photos: only her bubbles claiming no media and no price ship
        reply["offer_dropped"] = "claim"
        none = replace(pick, media=(), previews=(), subject="anything",
                       facts={"kinds": {}, "description": ""})
        kept = [x for x in parts if full_ai_sell.claim_ok(x, none) and full_ai_sell.price_ok(x, None)]
        if not kept:
            reply["dropped_reason"] = "claim"
        return kept
    # The fallback caption runs the shared chain too (one bubble); dropped -> no text, no PPV.
    scratch = {"leak": [], "dropped_reason": None, "typo_state": dict(facts.typo_state)}
    # A Pick not what he asked for: no typo pass, a slip in "not" / "pics" would void the disclosure.
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
    """The Heat check (spec 06 › Contracts › Heat check) on a Route sext Turn's final text: Jev's
    `reply_level` Score (`_heat_jev`) over the parts joined; cap = the Heat the Writer was given
    (`scene_of`'s heat, else `d.heat`). Not over -> `parts`. Over, and at least one
    `writer_timeout_s` left -> one rewrite by the Writer that answered (same messages, `write`)
    through `_chain` on a scratch reply (the Claim audit's shape), its attempts appended with
    `rewrite: true`, the first reply's gif kept; asked again; it ships only when not over. Anything
    else (still over, no text, chain drop, leak, second ask failed, no time) ships `parts`; so does
    a failed first ask. Sets `reply["heat_check"]` = {cap, score, level, outcome (ok | regen_ok |
    over_sent | error), ms, version} + `redo_score` and `first_level` when a rewrite ran + `error`
    on error; `score` / `level` are the shipped text's, `ms` both asks'. No Mode check."""
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
    # A scratch reply: the rewrite's chain marks the row only if its text ships.
    scratch = {"leak": [], "dropped_reason": None, "typo_state": dict(facts.typo_state)}
    text = cat_stickers.parse_marker(again.text)[0]     # the first reply's gif stays
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
    """The Turn sends a PPV the separate caption may write: a priced sell_now Pick or make_right's
    Free item, in a Mode that sends (shadow records only and stays on today's path). Never on a
    ride Pick (`is_ride`): its PPV rides her ordinary reply's last bubble."""
    p = facts.pick
    return (facts.config.get("caption_writer") == "caption" and full(facts.mode)
            and not is_ride(p)
            and isinstance(p, Pick)
            and ((d.route == "sell_now" and p.price_cents > 0) or (d.route == "make_right" and not p.price_cents)))


async def _caption(d: Decision, facts: TurnFacts, reply: dict, pick: Pick, deadline: float,
                   differs: bool) -> str | None:
    """`caption_writer` "caption": the separate caption call (`full_ai_caption`), keeping one
    `writer_timeout_s` of the Turn for the chat Writer, through the shared chain as one bubble
    (`_chain(single=True)`), then the Claim audit's checks (claim_ok + price_ok + discloses; `differs`, a
    Pick not what he asked for, `states_terms` too: "terms"). Fail -> one rewrite
    by the Writer that answered (same messages) when two `writer_timeout_s` are left; still failing
    -> None, and the Turn runs today's path (the chat Writer's caption). Sets `reply["caption"]` =
    {writer: caption | chat, model, outcome, ms, attempts, rejected?} (`rejected`: one {checks, text}
    per refused text, "chain" when the chain dropped / split / guarded it; no typo pass on a Pick not
    what he asked for, as the fallback caption) and, on a pass, `reply["typo_state"]`
    to the state the caption's chain left (the chat bubbles' chain then starts from it).
    Outcomes: ok | rewrite_ok | no_description | no_writer | failed | late; `run_turn` sets "alone"
    when it ships without chat bubbles. `differs` (`run_turn`: `nearest_line` set, W30 #4c) decides
    the "terms" check and the alone ship alike; the typo pass is off on any tagged Pick (`facts["asked"]`,
    "plain" too: W30 #21). A passed caption on a Pick not what he
    asked for is the only message: the chat Writer is not called (its lead-in said yes to his
    ask over a caption saying no); a failed one leaves today's path (NEAREST_NOTE in the sell block).
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
        # A Pick not what he asked for (tagged, "plain" too, W30 #21): no typo pass ("phtoo" / "fete"
        # voided its disclosure). With `differs` it ships alone, so it states the deal (the locked count, the price).
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
    """The chat bubbles, then the separate caption (the PPV rides it, `parts[-1]`). Their joined
    text must pass the Claim audit's checks too; when it doesn't the chat bubbles are dropped and
    the caption ships alone (`reply["caption"]["outcome"]` "alone", `typo_state` back to the
    caption's chain left, `typo_state`). Sets `reply["caption_fallback"]` False (the audit's flag: no fallback caption).
    Never reached on a Pick not what he asked for: there the caption is the only message (`_caption`).
    ASSUMPTION: a failed chat bubble drops itself, not the passed caption (no third LLM call).
    Overturned if the owner prefers today's path then."""
    reply["caption_fallback"] = False
    joined = "\n".join([*parts, caption])
    if not full_ai_sell.caption_fails(joined, pick, pick.price_cents or None, differs=False):
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


async def run_turn(facts: TurnFacts, io: TurnIO | None = None) -> TurnResult:
    """Decide, write, shape and record one Turn through `io` (None: the Test chat's
    `full_ai_test.IO`, which raises `full_ai_test.Conflict` when the Turn is not the session's
    next one or already has its row)."""
    io = io or full_ai_test.IO
    t0 = time.perf_counter()
    # One Turn deadline every LLM stage shares (spec › Contracts › One Turn bound). The SDK's
    # timeout is per HTTP operation (retried), so the Router (`router.WALL_S`, 20 s) and every
    # Writer walk (`_capped`) are also wall-clock capped at the time left.
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
        reply["reply_to_n"] = facts.offer_ask.reply_to_n     # the Test chat's Quote-reply mark
    details = d.row == "offer_details"      # an answer only: tease, scene, Offer and Asked held
    if details and facts.tease is not None:
        reply["held_tease"] = facts.tease.row_id   # live `_folds` keeps the tease past its bubbles
    if scene_flag(facts):
        # The saved scene (owner-ordered save state, ADR-0032 named exception): Jev's `scene_stage`
        # (None on its default or a tie) folded over the newest row's; None ends it. An Offer-details
        # answer leaves it as it stood.
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
        # An Offer-details answer extracts what he stated but asks nothing (no Choice, no list).
        reply["info_error"] = await _info(facts, d.route, deadline, jev_json, ask=not details)
        reply["fan_info"] = facts.fan_info
        if details:
            got, facts.offer_facts = await offer_resolved(facts, deadline)
            reply["offer_details"] = diagnostics(got, facts.offer_facts)
        if _sells(d.route, facts):
            # The sell step gets the Turn's time left (03b: min(own, remaining), no own bound).
            # ASSUMPTION: a cut dupe read's `asyncio.to_thread` clustering finishes in the background
            # (read-only, one per cut Turn). Overturned if cut Turns pile up executor threads.
            try:
                await asyncio.wait_for(_sell(facts, d, jev_json["choices"], reply, deadline),
                                       deadline - time.monotonic())
            except asyncio.TimeoutError:
                log.warning("full_ai sell step past the Turn deadline account=%s", facts.account_id)
                facts.pick = Refusal("inventory_unknown")
            if isinstance(facts.pick, Refusal):
                reply["refusal"] = facts.pick.reason
        pick = facts.pick if isinstance(facts.pick, Pick) else None
        # A Pick not what he asked for (one test: the terms check, the alone ship)
        differs = nearest_line(facts, pick) is not None
        caption = await _caption(d, facts, reply, pick, deadline, differs) if _ppv_turn(d, facts) else None
        caption_typos = dict(reply["typo_state"])
        # A Pick not what he asked for: its passed caption says so and ships alone, no chat Writer
        # call (owner 2026-11-17: a lead-in "u got it babe" over "not the feet vid you asked for").
        alone = caption is not None and differs
        res = (WriteResult(None, reply["caption"]["model"]) if alone
               else await _capped(write(d, facts, deadline=deadline, plain=caption is not None), deadline))
        reply["attempts"], reply["floor_reason"] = res.attempts, res.floor_reason
        if res.asked_ids:                   # an ask Turn: her marker as written (NEW-168)
            reply["asked_marker"] = res.asked_marker
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
        elif pick is not None and caption is not None and res.text is None:   # no chat Writer / differs: alone
            reply["caption_fallback"], reply["caption"]["outcome"], reply["typo_state"] = False, "alone", caption_typos
            parts = [caption]
        elif pick is not None and parts:            # her text must claim only what the PPV holds
            parts = await _claim_audit(d, facts, reply, res.writer, parts, pick, deadline)
            if reply.get("offer_dropped"):          # a ride failed twice / fallback dropped: no PPV
                pick = None
        if details:         # the Offer answer check, never another row's (no Pick here)
            parts = await offer_check(
                facts, reply, res.writer, parts, deadline, chain=_chain,
                rewrite=lambda w: _capped(write(d, facts, deadline=deadline, writers=[w]), deadline))
        if parts and d.route == "sext" and facts.config["floor_on"]:   # Heat check (spec 06), no Mode check
            parts = await _heat_check(d, facts, reply, res.writer, parts, deadline)
        if parts or (gif and not text):            # a dropped draft fails, gif or not
            writer = res.writer
            row["writer_model"] = writer
            reply["wait_s"] = io.hold(facts.config, facts.anchor_key)
            if io.send is not None:                 # None records only
                over = facts.offer_piece.row_id if d.row == "haggle" and facts.offer_piece else None
                desc = (str(pick.facts.get("description") or "") or None
                        if pick is not None and scene_flag(facts) else None)
                await io.send(row, parts, pick, over=over, desc=desc, gif=gif)
            landed = bool(parts) and row["status"] == "sent" and "cut" not in reply   # cut: none
            if (k := res.asked) is not None and landed:     # NEW-168: the fact her text named
                reply["asked"] = {**facts.asked, k: facts.asked.get(k, 0) + 1}
    reply["turn_ms"] = int((time.perf_counter() - t0) * 1000)
    row_id = await io.record(row)
    return TurnResult(row_id, d, reply["parts"], writer, reply["attempts"], reply["wait_s"],
                      row["status"], full_ai_test.offer_of(row), reply.get("caption"),
                      reply.get("scene"), reply.get("price"), reply.get("dropped_reason"),
                      reply.get("heat_check"))
