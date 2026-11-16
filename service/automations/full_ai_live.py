"""automations/full_ai_live.py — Full AI Chat's live I/O twin of `full_ai_test` (Mode `live`, 04a).

A Creator whose enabled `full_ai_chat` rule says `trigger_json.mode == "live"` answers a Fan's DM on
OnlyFans with the Test chat's Turn (`full_ai_turn.run_turn(facts, io)`). The job (`full_ai_chat.run`
dispatches here) leases the Fan, loads fresh facts (his newest unanswered run is the Turn), runs the
Turn and sends its text bubbles one by one. Never double-send (ticket 65): just before the first OF
call the row is INSERTed `sending` on the Turn key (`_reserve`; no id back = another run owns the
Turn, send nothing); `record` then UPDATEs only its `status`, `reply_json`, `writer_model`
(and writes the Turn's facts to `fans`). A run
that dies after the reserve leaves `sending`, which the next run's `reap` turns `unconfirmed`:
never sent again (`load` finds the row). Last look (ticket 66): `LAST_LOOK`, one ordered check
list, runs as the pre-look before the Router and again before each bubble; the first reason stands
the Turn down. Each bubble goes out through its kind's `BUBBLE_SENDERS` entry.

  live_rule(account_id)              id of the enabled full_ai_chat rule in Mode live, else None
  due(config, dm)                    when the reply to `dm` may go: its time + the drawn reply speed
  enqueue(account, fan, mid, rule)   the Fan's job at `due` (hook + sweep); False = one is pending
  load(account_id, fan_id, client)   TurnFacts | None (no unanswered Turn, or its row exists)
  reap(account_id, mine)             `sending` rows -> `unconfirmed`, the Creator's full_ai_chat leases dropped,
                                     but a Fan whose job runs in this process (`_running`, not `mine`)
  run(account_id, payload, *, run_id)   reap -> cooldown -> scrape wait -> lease -> load -> pre-look -> run_turn
                                     -> cooldown 10 s + release; busy -> the same payload at +20 s,
                                     3 runs at most (ticket 67); his one-Fan scrape still queued
                                     (`_scrape_pending`) -> the same payload at +20 s, no try spent
                                     (bounded by SCRAPE_WAIT_S); no anchor (the interval job) -> sweep;
                                     the reserve takes a shutdown-drain slot (`ax.begin_send`, held to
                                     the end: holds go 0 s while draining, a running one ends); refused (the relay
                                     drains) -> nothing sent, no row, the same payload at +20 s
  sweep(account_id)                  missed DMs: due Turn ends with no row / job / cooldown and a clear
                                     pre-look (no OF read) -> enqueue, 20 per pass
  catchup_queue(account, fans, ...)  full_ai_catchup's waiting Fans: the sweep's checks over just them
  catchup_client(account)            full_ai_catchup's OF client (reads only)

The only Full AI module that may import the OF client factory, the lease, the DM rate or the OF
write seam (AST scan in test_full_ai_live.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import delete, func, or_, select, true, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax
import dm_rate
import run_slot
from env_knob import env_float
from attribution import write_outbound_attribution
from automations import (
    _info_jev, cat_stickers, full_ai_chat, full_ai_owned, full_ai_owner, full_ai_owner_io, full_ai_photo,
    full_ai_ppv, full_ai_settle, full_ai_test, full_ai_turn,
)
from automations import _router_jev as router
from automations.full_ai_scene import saved_scene, scene_words
from automations._send_failure import quarantine_if_undeliverable, skip_unreachable_fan
from automations._typing_hold import (
    hold_with_typing, load_typing_indicator, load_typing_wpm, typing_delay_seconds,
)
from automations.rhythm import INLINE_MAX_S
from db.engine import get_session
from db.models import AiDecision, AutomationRule, Fan, FanLease, Message, ScheduledJob

log = logging.getLogger("of-relay.automation.full_ai_live")

MODE, KIND, TRIGGER_KIND = "live", "full_ai_chat", "inbound"
SEND_PURPOSE = "gated"                 # audience_include.AUDIENCE_SENDER_CLASSIFICATION["full_ai_live"]
COOLDOWN_S = 10                        # after a send; never shortens a longer pause
# `fans` columns the loader reads as `fan_info` (empty ones left out); `record` writes back only
# the extract's fields, never the two name-only ones.
FACT_FIELDS = tuple(_info_jev._EXTRACT_FIELDS)
FAN_INFO_FIELDS = (*FACT_FIELDS, "generated_nickname", "of_display_name")
WELCOME = "welcome"                    # send_welcome's automation_kind: never answers his DM
_TURN_KEY = ["account_id", "fan_id", "mode", "trigger_key"]
BUSY_RETRY_S, BUSY_RUNS = 20, 3        # a busy Fan: same payload at +20 s; after 3 runs the sweep (68)
SCRAPE_WAIT_S = 900                    # a one-Fan scrape queued longer ago than this no longer holds his Turn (stuck row)
SWEEP_WINDOW_S, SWEEP_MAX = 86400, 20  # the sweep answers DMs of the last 24 h, 20 Turns per pass
# A Full AI DM lets the account's next write start this soon after it (the write gate's gap; every
# other sender keeps of_write's 11 s). Measured 2026-11-15 on OF: 10 DMs each way (fan -> Creator,
# Creator -> fan) 1.0-2.8 s apart, none refused. The DM window (dm_rate, OF_DM_PER_MIN) still caps
# the minute. FULL_AI_WRITE_GAP_S=11 is the old spacing.


def _write_gap() -> float:
    """FULL_AI_WRITE_GAP_S, 0..11 s (of_write's gap the ceiling); unset, malformed, inf / nan or negative -> 2.0
    (`env_knob`): a typo must neither stop Full AI at import nor close the account's write gate."""
    return min(11.0, env_float("FULL_AI_WRITE_GAP_S", 2.0, lo=0.0))


WRITE_GAP_S = _write_gap()
# (account, Fan) whose live job runs in this process now: jobs for different Fans of one Creator
# overlap (automation_executor `_PER_FAN_KINDS`), so `reap` leaves these and the sweep skips them.
_running: set[tuple[str, int]] = set()
# One `reap` per Creator at a time: a Turn joins `_running` before its own reap and writes its lease /
# row only after it, so it waits out a reap whose `_running` read missed it.
_reap_locks: dict[str, asyncio.Lock] = {}


def _is_live(raw: str | None) -> bool:
    try:
        return (json.loads(raw or "{}") or {}).get("mode") == MODE
    except (ValueError, TypeError, AttributeError):
        return False


async def live_rule(account_id: str) -> int | None:
    """The enabled `full_ai_chat` rule whose `trigger_json.mode` is "live", else None."""
    async with get_session() as s:
        rules = (await s.execute(select(AutomationRule.id, AutomationRule.trigger_json).where(
            AutomationRule.account_id == str(account_id), AutomationRule.kind == KIND,
            AutomationRule.is_enabled.is_(True)).order_by(AutomationRule.id))).all()
    return next((int(rid) for rid, raw in rules if _is_live(raw)), None)


async def live_accounts() -> set[str]:
    """Creators with an enabled `full_ai_chat` rule in Mode live (05's fast purchases poll)."""
    async with get_session() as s:
        rules = (await s.execute(select(AutomationRule.account_id, AutomationRule.trigger_json).where(
            AutomationRule.kind == KIND, AutomationRule.is_enabled.is_(True)))).all()
    return {str(aid) for aid, raw in rules if _is_live(raw)}


def due(config: dict, dm) -> datetime:
    """When the reply to `dm` may go: its time + the Test chat's reply-speed draw, seeded by its id
    (the same Anchor and config give the same time on any DB). The wait is the job's `run_at`."""
    return dm.created_at + timedelta(seconds=full_ai_test.hold(config, str(dm.message_id)))


async def enqueue(account_id: str, fan_id: int, message_id: int, rule_id: int, *,
                  not_before: datetime | None = None) -> bool:
    """Queue the Fan's job at `due(config, his DM)` (or `not_before`, if later). A pending `full_ai_chat`
    job for the Fan absorbs this DM (it loads facts when it fires): False, nothing queued; so is a DM
    not in `messages`. The supervisor is woken at `run_at`, not at its next 30 s tick."""
    from webhook_dispatch import _FULL_AI_PENDING_S, _imminent_pending_job   # lazy: imports widely
    aid, fan, mid = str(account_id), int(fan_id), int(message_id)
    if await _imminent_pending_job(aid, KIND, fan, _FULL_AI_PENDING_S) is not None:
        return False
    cfg = (await full_ai_turn.stored_config(aid))["checkpoint"]
    async with get_session() as s:
        dm = await s.get(Message, (aid, fan, mid))
    if dm is None:
        log.warning("full_ai_live_enqueue_no_dm account=%s fan=%s msg=%s", aid, fan, mid)
        return False
    run_at = due(cfg, dm)
    await _queue(aid, {"only_fan_ids": [fan], "anchor": mid, "_rule_id": int(rule_id), "tries": 0},
                 max(run_at, not_before) if not_before is not None else run_at)
    return True


async def _queue(account_id: str, payload: dict, run_at: datetime) -> None:
    """One `full_ai_chat` job at `run_at`, and a supervisor wake then."""
    from webhook_dispatch import _schedule_wake   # lazy: imports widely
    await ax.enqueue_job(account_id, KIND, payload=payload, run_at=run_at)
    _schedule_wake(max(0.0, (run_at - datetime.utcnow()).total_seconds()))


async def _scrape_pending(account_id: str, fan_id: int) -> bool:
    """A one-Fan `scrape_fan` job of the Fan (e.g. full_ai_catchup's), pending or running, created within
    `SCRAPE_WAIT_S`: his chat is still being read, and a Turn loaded now could answer what she already answered."""
    since = datetime.utcnow() - timedelta(seconds=SCRAPE_WAIT_S)
    async with get_session() as s:
        payloads = (await s.execute(select(ScheduledJob.payload_json).where(
            ScheduledJob.account_id == str(account_id), ScheduledJob.kind == "scrape_fan",
            ScheduledJob.status.in_(("pending", "running")), ScheduledJob.created_at >= since))).scalars().all()
    for pj in payloads:
        try:
            if int(fan_id) in {int(f) for f in json.loads(pj or "{}").get("fan_ids") or ()}:
                return True
        except (ValueError, TypeError, AttributeError):
            continue
    return False


async def _busy(account_id: str, payload: dict) -> dict:
    """Fan on cooldown or leased by another Lane: the same payload at +`BUSY_RETRY_S` with
    `tries + 1`; the `BUSY_RUNS`-th busy run ends here (the sweep picks the Turn up)."""
    tries = int(payload.get("tries") or 0) + 1
    if tries >= BUSY_RUNS:
        return {"skipped": "busy"}
    await _queue(account_id, {**payload, "tries": tries}, datetime.utcnow() + timedelta(seconds=BUSY_RETRY_S))
    return {"skipped": "busy", "tries": tries}


def _not_welcome():
    return or_(Message.automation_kind.is_(None), Message.automation_kind != WELCOME)


async def load(account_id: str, fan_id: int, client) -> full_ai_turn.TurnFacts | None:
    """The Fan's open Turn: his run after her newest non-welcome outbound (Anchor = its last
    inbound), its thread (`full_ai_chat._reads`), `fan_info` from `fans` (`FAN_INFO_FIELDS`, empty
    values left out), `asked` / `typo_state` from the Fan's newest live row whatever its status,
    and the sell / scene folds over his live rows (`_folds`), the checkpoint config. None when
    there is no such run or its live row exists.
    `client` is the job's OF client: with `describe_fan_photos` on or her dare standing or due (`looks_of`), `full_ai_photo.describe_turn`
    reads his newest undescribed photo through it (no DB session open: a vision call)."""
    aid, fan = str(account_id), int(fan_id)
    cfg = await full_ai_turn.stored_config(aid)
    side = cfg["checkpoint"]
    chat = (Message.account_id == aid, Message.fan_id == fan)
    async with get_session() as s:
        cut = (await s.execute(full_ai_chat._newest_out((*chat, _not_welcome()), true()))).first()
        q = select(Message).where(*chat, Message.direction.in_(("in", "out")),
                                  or_(Message.direction == "in", _not_welcome()))
        if cut is not None:
            q = q.where(full_ai_chat._after(*cut))
        runs = full_ai_chat.cut_runs((await s.execute(q.order_by(Message.created_at, Message.message_id))).scalars(),
                                     tuple(cut) if cut is not None else None)
        if not runs:
            return None
        run_cut, turn = runs[-1]
        anchor = turn[-1]
        if (await s.execute(select(AiDecision.id).where(
                AiDecision.account_id == aid, AiDecision.fan_id == fan, AiDecision.mode == MODE,
                AiDecision.trigger_key == str(anchor.message_id)))).first() is not None:
            return None
        rows = list((await s.execute(select(AiDecision).where(
            AiDecision.account_id == aid, AiDecision.fan_id == fan, AiDecision.mode == MODE)
            .order_by(AiDecision.id))).scalars())
    # Her standing dare promised to look (NEW-156): his photo is read with the key off too.
    dared, due = full_ai_test.dared_of(rows), full_ai_test.dare_due_of(rows, anchor.created_at)
    photos = bool(side[full_ai_photo.KEY]) or dared or due
    photo = await full_ai_photo.describe_turn(aid, turn, client) if photos else None
    async with get_session() as s:
        thread_rows, _other_lane, _tx = await full_ai_chat._reads(s, aid, fan, run_cut, turn)
        f = await s.get(Fan, (aid, fan))
        info = {k: v for k in FAN_INFO_FIELDS
                if f is not None and isinstance(v := getattr(f, k), str) and v.strip()}
    sold = await full_ai_owned.load_sold(aid, fan)
    k = _folds(rows, sold, anchor.created_at, tuple(cut) if cut is not None else None)
    st, _ = full_ai_chat.build_state(turn, thread_rows, k["bought"], k["offer"], pending=k["pending"],
                                     photos=photos)
    st = {**st, **_state_keys(side, rows, anchor.created_at, info, k["scene"])}
    fold = full_ai_test._loads(rows[-1].reply_json) if rows else {}
    return full_ai_turn.TurnFacts(
        account_id=aid, fan_id=fan, mode=MODE, anchor_key=str(anchor.message_id), state=st,
        cut_rows=[*thread_rows, *turn], bought=k["bought"], offer=k["offer"], fan_info=info,
        asked=dict(fold.get("asked") or {}), typo_state=dict(fold.get("typo_state") or {}),
        config=side, side="checkpoint", config_rev=cfg["rev"], owned=k["owned"], spent=k["spent"],
        tips=k["tips"], sent=k["sent"], tease=k["tease"], offer_piece=k["offer_piece"], scene=k["scene"],
        purchases=full_ai_test.purchases_of(rows) if side.get("chat_tease") else [], photo=photo,
        dared=dared, dare_due=due)


def _folds(rows, sold: full_ai_owned.Sold, now: datetime, newest_out: tuple | None) -> dict:
    """05's map over his live rows (oldest first) and `sold` at `now` (his Anchor): Full AI's own
    open Offer (`open_offer_live`: <= 24 h, priced only once on OF) as the Pending offer and
    `offer_piece`; the Pending tease (`pending_tease_of`, and her newest non-welcome outbound
    `newest_out` is one of its bubbles: a human or another Lane wrote since -> none); spend / tips /
    last purchase from `purchases_live` (any Lane); Owned / sent across Lanes; the saved scene.
    Pure."""
    open_offer = full_ai_owned.open_offer_live(rows, now)
    offer = full_ai_test.offer_line(open_offer)
    tease = full_ai_test.pending_tease_of(rows, now)
    if tease is not None and (newest_out is None or newest_out[1] not in {
            p.get("message_id") for p in full_ai_test._loads(tease.reply_json).get("parts") or []}):
        tease = None
    pending = (" ".join(p["text"] for p in full_ai_test._loads(tease.reply_json).get("parts") or [] if p.get("text"))
               if tease is not None else router.pending_offer(offer))   # as `pending_offer_text`
    bought = full_ai_owned.purchases_live(sold.paid_msgs, sold.txs)
    return {"offer": offer, "pending": pending, "offer_piece": full_ai_test.teased_of(open_offer),
            "tease": full_ai_test.teased_of(tease), "bought": bought[-1] if bought else None,
            "spent": [p for p in bought if p.kind == "ppv_message"],
            "tips": [p.amount_cents for p in bought if p.kind == "tip"],
            "owned": full_ai_owned.owned_live(rows, sold.cross),
            "sent": full_ai_owned.sent_live(rows, sold.vault_media),
            "scene": saved_scene(rows, now, full_ai_test.SITTING_GAP_S)}


def _state_keys(config: dict, rows, now: datetime, info: dict, scene) -> dict:
    """The config-gated Router state keys `full_ai_test.fetch` adds, over live rows. Pure."""
    st: dict = {}
    if config.get("sext_scene"):
        st |= {"purchases": full_ai_test.purchases_of(rows), "scene": scene_words(scene)}
    tease = bool(config.get("chat_tease"))
    if config.get("sell_spacing") or tease:
        st |= full_ai_test.spacing_of(rows, now, free=tease)
    if tease:
        st |= full_ai_test.chat_tease_of(rows, now)
    if config.get("he_likes"):
        st |= {"he_likes": full_ai_test.likes_of(info)}
    return st


def fan_updates(loaded: dict, got: dict) -> dict[str, str]:
    """The Turn's new or changed `FACT_FIELDS` values (`got` = the row's `reply_json.fan_info`)
    against what `load` read (`loaded`): `.strip()[:200]`, never an empty one. Pure."""
    out = {}
    for k in FACT_FIELDS:
        v = got.get(k)
        if isinstance(v, str) and v.strip() and v.strip()[:200] != (loaded.get(k) or "").strip():
            out[k] = v.strip()[:200]
    return out


async def _write_facts(s, account_id: str, fan_id: int, updates: dict[str, str]) -> None:
    """wcfi `_extract_and_fill`'s upsert shape, in the caller's transaction."""
    if not updates:
        return
    now = datetime.utcnow()
    await s.execute(sqlite_insert(Fan).values(
        account_id=str(account_id), fan_id=int(fan_id), grok_facts_updated_at=now, updated_at=now,
        **updates).on_conflict_do_update(index_elements=["account_id", "fan_id"],
                                         set_={**updates, "grok_facts_updated_at": now, "updated_at": now}))


@dataclass
class _Run:
    """One job's send state, shared by its `send` and `record`."""
    taken: bool = False                   # the reserve found another run's row: send nothing, write nothing
    lost: run_slot.SlotLost | None = None  # lost the slot after >= 1 bubble: re-raise once recorded
    landed: int = 0                       # bubbles on OF (the job's finally rests the Fan when > 0)


class _Draining(Exception):
    """The relay drains (`ax.begin_send` False) before the reserve: nothing sent, no row."""


def _values(row: dict, anchor: Message, status: str) -> dict:
    """The row dict (not yet reserved: no `id`) as `ai_decisions` columns."""
    return {**row, "status": status,
            "anchor_message_id": anchor.message_id, "anchor_created_at": anchor.created_at,
            "reply_json": json.dumps(row["reply_json"], ensure_ascii=False),
            "jev_json": json.dumps(row["jev_json"], ensure_ascii=False)}


async def _reserve(row: dict, anchor: Message) -> int | None:
    """INSERT the full row `sending` on the Turn key (`uq_ai_decisions_turn`) just before the
    Turn's first OF call; sets `row["id"]`. None: another run owns the Turn."""
    async with get_session() as s:
        rid = (await s.execute(sqlite_insert(AiDecision).values(**_values(row, anchor, "sending"))
                               .on_conflict_do_nothing(index_elements=_TURN_KEY)
                               .returning(AiDecision.id))).scalar_one_or_none()
    if rid is not None:
        row["id"] = int(rid)
    return rid


async def _row_id(row: dict) -> int:
    async with get_session() as s:
        return int((await s.execute(select(AiDecision.id).where(
            AiDecision.account_id == row["account_id"], AiDecision.fan_id == row["fan_id"],
            AiDecision.mode == MODE, AiDecision.trigger_key == row["trigger_key"]))).scalar_one())


@dataclass(frozen=True)
class Look:
    """What a last-look check reads; checks do no I/O (spec 04a › Interfaces)."""
    account_id: str
    fan_id: int
    anchor: tuple[datetime, int]         # the Turn's Anchor (created_at, message_id)
    client: Any | None                   # the job's OF client; None on the sweep's pre-look
    row: dict | None                     # the Turn's row dict, row["id"] set once reserved; None on the pre-look
    bubble: dict | None                  # {"text"} | {"text","ppv":{...}} | {"gif","tag"}; None on the pre-look
    index: int                           # bubble index; -1 on the pre-look
    sent: int                            # bubbles of this Turn already on OF
    facts: dict[str, Any] = field(default_factory=dict)   # each loader's result, keyed by check name


Check = Callable[[Look], "str | None"]          # None = go; str = stand-down reason
Loader = Callable[[Look], Awaitable[Any]]       # reads only; the one write allowed is 05's settle_pull


async def _newest_inbound(look: Look) -> tuple[datetime, int] | None:
    """His newest inbound DM in `messages` (created_at, message_id)."""
    async with get_session() as s:
        got = (await s.execute(select(Message.created_at, Message.message_id).where(
            Message.account_id == look.account_id, Message.fan_id == look.fan_id,
            Message.direction == "in").order_by(Message.created_at.desc(), Message.message_id.desc())
            .limit(1))).first()
    return tuple(got) if got is not None else None


def overtaken(look: Look) -> str | None:
    """He wrote again after the Anchor and none of her bubbles is out yet: the next Turn answers both."""
    newest = look.facts.get("overtaken")
    return "overtaken" if look.sent == 0 and newest is not None and tuple(newest) > tuple(look.anchor) else None


async def _owner(look: Look) -> full_ai_owner.OwnerFacts:
    """04b's facts (`full_ai_owner_io.load`), once per look. The OF-app read (a client needed, so never
    the sweep's): the job's pre-look, the look before the Turn's first bubble out, and the look before
    its `ppv` bubble (a human may answer while the Writer runs: measured 2026-11-16); every other
    bubble's look reads the DB only. This Turn's sent bubbles (`message_id` on its parts) count as ours."""
    read = look.client is not None and (look.sent == 0 or "ppv" in (look.bubble or {}))
    ours = {int(p["message_id"]) for p in ((look.row or {}).get("reply_json") or {}).get("parts") or ()
            if isinstance(p, dict) and p.get("message_id")}
    return await full_ai_owner_io.load(look.account_id, look.fan_id, look.anchor[0], client=look.client,
                                       live_read=read, ours=ours)


def _owned_by(look: Look, mine) -> str | None:
    """`who_owns`' reason over the off_switch slot's facts, when `mine(reason)`."""
    stop = full_ai_owner.who_owns(look.facts["off_switch"])
    return stop.reason if stop is not None and mine(stop.reason) else None


def off_switch(look: Look) -> str | None:
    return _owned_by(look, full_ai_owner.OFF_REASONS.__contains__)


def fans_list(look: Look) -> str | None:
    return _owned_by(look, "not_listed".__eq__)


def who_owns(look: Look) -> str | None:
    """Every other `who_owns` reason (the complement: a new reason stops the Turn here)."""
    return _owned_by(look, lambda r: r not in (*full_ai_owner.OFF_REASONS, "not_listed", *full_ai_owner.HUMAN_REASONS))


def human_yield(look: Look) -> str | None:
    return _owned_by(look, full_ai_owner.HUMAN_REASONS.__contains__)


async def _offer_facts(look: Look) -> tuple[list, full_ai_owned.Sold] | None:
    """05's facts, for the bubble that carries `ppv` only: settle first (a landed unconfirmed
    Offer links and stops blocking), then the Fan's fresh live rows and what he bought anywhere."""
    if not look.bubble or "ppv" not in look.bubble:
        return None
    await full_ai_settle.settle_pull(look.account_id, look.fan_id)
    async with get_session() as s:
        rows = list((await s.execute(select(AiDecision).where(
            AiDecision.account_id == look.account_id, AiDecision.fan_id == look.fan_id,
            AiDecision.mode == MODE).order_by(AiDecision.id))).scalars())
    return rows, await full_ai_owned.load_sold(look.account_id, look.fan_id)


def offer_valid(look: Look) -> str | None:
    """"owned" (he came to own a piece of it) | "unconfirmed" (a priced Offer of ours may be on
    OF unseen) | None. This Turn's own row (reserved from bubble 1 on) is not read: a Free item's
    row would count its own media as Owned (`owned_of`)."""
    got = look.facts.get("offer_valid")
    if got is None:
        return None
    own = (look.row or {}).get("id")
    rows, sold = [r for r in got[0] if r.id != own], got[1]
    return full_ai_owned.offer_still_valid(look.bubble["ppv"], full_ai_owned.owned_live(rows, sold.cross), rows,
                                           datetime.utcnow(), own)


# Ordered; first reason wins. Pinned slots (spec 04a seam 4): off_switch, fans_list, who_owns,
# human_yield (04b), overtaken (here), offer_valid (05). Others add one tuple at their slot.
LAST_LOOK: list[tuple[str, Loader | None, Check]] = [
    ("off_switch", _owner, off_switch),
    ("fans_list", None, fans_list),
    ("who_owns", None, who_owns),
    ("human_yield", None, human_yield),
    ("overtaken", _newest_inbound, overtaken),
    ("offer_valid", _offer_facts, offer_valid),
]


async def _look(look: Look) -> tuple[str, str] | None:
    """Run `LAST_LOOK` in order: each loader (fresh every call) into `look.facts[name]`, then its
    check; the first reason wins. A loader or check that raises stands down with reason "error"
    (fail closed: never a bubble on a broken read); a lost Run slot still propagates."""
    for name, loader, check in LAST_LOOK:
        try:
            if loader is not None:
                look.facts[name] = await loader(look)
            reason = check(look)
        except run_slot.SlotLost:
            raise
        except Exception:  # noqa: BLE001 — a broken check never lets a bubble through
            log.warning("full_ai_live last look failed account=%s fan=%s check=%s",
                        look.account_id, look.fan_id, name, exc_info=True)
            reason = "error"
        if reason:
            return name, str(reason)
    return None


async def _dm(client, look: Look, text: str, **kw) -> dict:
    """One DM on OF; writes its own `messages` row with OF's text and time (attributed)."""
    res = await ax.of_write_paced(look.account_id, lambda: client.send_message(look.fan_id, text, **kw),
                                  send_purpose=SEND_PURPOSE, tries=1, dm=True,
                                  min_gap_s=WRITE_GAP_S)
    mid = res.get("id") if isinstance(res, dict) else None
    if mid:
        await write_outbound_attribution(
            account_id=look.account_id, fan_id=look.fan_id, message_id=int(mid), sent_by_employee_id=None,
            body=str(res.get("text") or text), price_cents=0,
            created_at=ax._parse_iso(res.get("createdAt")) or datetime.utcnow(),
            automation_kind=KIND, emit_live=True)
    return {"id": int(mid) if mid else None, "attributed": bool(mid), "offer_dropped": None, "unknown": False}


async def _send_text(client, look: Look) -> dict:
    return await _dm(client, look, look.bubble["text"])


async def _send_gif(client, look: Look) -> dict:
    """Her `{gif, tag}` part as OF's GIF-only DM; the shared no-same-reaction-twice memory records it."""
    res = await _dm(client, look, "", giphy_id=look.bubble["gif"])
    if res["id"]:
        cat_stickers.mark_sent(look.account_id, look.fan_id, tag=look.bubble.get("tag"), gif_id=look.bubble["gif"])
    return res


# bubble kind -> (client, look) -> {"id", "attributed", "offer_dropped", "unknown"}; "ppv"
# (`send_ppv`, ticket 90) is added below its definition. A kind with no sender stands down
# `("sender", "<kind>_unbuilt")`.
BUBBLE_SENDERS: dict[str, Callable[[Any, Look], Awaitable[dict]]] = {
    "text": _send_text,
    "gif": _send_gif,
}

_OFFER_COLS = ("offer_price_cents", "offer_list_cents", "offer_media_json", "offer_item_ref")


def _kind(bubble: dict) -> str:
    return "ppv" if "ppv" in bubble else "gif" if "gif" in bubble else "text"


async def _drop_offer(row: dict, why: str) -> None:
    """The Offer's carrier never went out: no Offer stands (columns NULL, the loop is their writer)."""
    row["reply_json"]["offer_dropped"] = why
    row.update(dict.fromkeys(_OFFER_COLS))
    if row.get("id") is not None:
        async with get_session() as s:
            await s.execute(update(AiDecision).where(AiDecision.id == row["id"])
                            .values(**dict.fromkeys(_OFFER_COLS)))


def _io(account_id: str, fan_id: int, anchor: Message, client, state: _Run,
        loaded: dict | None = None, config: dict | None = None) -> full_ai_turn.TurnIO:
    """The live `TurnIO` of one job: the Test chat's hold, a sender that walks the bubbles on OF
    behind the last look and the reserve, a record that UPDATEs the reserved row (else INSERTs it)
    and, in that transaction, writes the Turn's new facts (`fan_updates` against `loaded`, the
    fan_info `load` read) back to `fans`. `config` (the checkpoint side): `typing_sign` off = no
    type-time hold, `typing_notification` off = no "typing" frame."""
    config = config or {}
    aid, fan = str(account_id), int(fan_id)
    at = (anchor.created_at, int(anchor.message_id))

    async def send(row: dict, parts: list[str], pick=None, *, over=None, desc=None, gif=None) -> None:
        # The row and bubble shapes of the Test chat (Offer columns included, the gif part last).
        full_ai_test.send(row, parts, pick, over=over, desc=desc)
        if gif:
            row["reply_json"]["parts"].append(gif)
        reply, landed, unknown, stop = row["reply_json"], 0, False, None
        wpm = await load_typing_wpm(aid) if config.get("typing_sign") else None
        frame = bool(config.get("typing_notification")) and await load_typing_indicator(aid)
        for i, part in enumerate(reply["parts"]):
            sender = BUBBLE_SENDERS.get(_kind(part))
            if sender is None:                 # e.g. an unbuilt PPV never goes out as plain text
                stop = ("sender", f"{_kind(part)}_unbuilt", i)
                break
            try:
                # The relay drains (SIGTERM): no type-time hold left and a running one ends, so the
                # Turn ends inside RELAY_DRAIN_S.
                secs = (typing_delay_seconds(part["text"], wpm)
                        if wpm is not None and "gif" not in part and not ax.draining() else 0)
                await hold_with_typing(aid, fan, secs, typing_indicator=frame, cut=ax.draining)
                await dm_rate.turn(aid, release_budget_s=INLINE_MAX_S)
            except run_slot.SlotLost as e:     # before the reserve: the retry reruns the whole Turn
                if not landed:
                    raise
                reply["cut"] = {"check": "slot_lost", "reason": "slot_lost", "index": i}
                state.lost = e
                break
            look = Look(aid, fan, at, client, row, part, i, landed)
            if (why := await _look(look)) is not None:
                dm_rate.release(aid)
                if why == ("human_yield", "human_of_app"):   # as `_run`'s pre-look: the next Turns rest too
                    try:
                        await full_ai_owner_io.start_human_yield(aid, fan, look.facts["off_switch"].human_at)
                    except Exception:  # noqa: BLE001 — the row still records the stop
                        log.warning("full_ai_live human yield failed account=%s fan=%s", aid, fan, exc_info=True)
                stop = (*why, i)
                break
            if row.get("id") is None and not ax.begin_send():
                dm_rate.release(aid)           # the relay drains: nothing sent, no row; `_run` re-queues
                raise _Draining
            if row.get("id") is None and await _reserve(row, anchor) is None:
                dm_rate.release(aid)           # another run owns this Turn
                state.taken = True
                log.warning("full_ai_live turn taken account=%s fan=%s key=%s", aid, fan, row["trigger_key"])
                return
            try:
                res = await sender(client, look)
            except Exception as e:  # noqa: BLE001 — stop the Turn, never retry a send
                await skip_unreachable_fan(aid, fan, e, log=log)
                log.warning("full_ai_live send failed account=%s fan=%s", aid, fan, exc_info=True)
                reply["cut"] = {"check": "send_error", "reason": type(e).__name__, "index": i}
                break
            if res.get("offer_dropped"):       # its sender already cleared the Offer columns
                reply["offer_dropped"] = res["offer_dropped"]
            if res.get("unknown"):             # may be on OF: no retry, Offer columns kept
                unknown = True
                reply["cut"] = {"check": "send_error", "reason": f"{_kind(part)}_unconfirmed", "index": i}
                break
            mid = res.get("id")
            if not mid:
                if not landed:
                    await quarantine_if_undeliverable(client, aid, fan, log=log)
                reply["cut"] = {"check": "send_error", "reason": "no_id", "index": i}
                break
            part["message_id"] = int(mid)
            if not res.get("attributed"):
                await write_outbound_attribution(
                    account_id=aid, fan_id=fan, message_id=int(mid), sent_by_employee_id=None,
                    body=str(part.get("text") or ""), price_cents=0, created_at=datetime.utcnow(),
                    automation_kind=KIND, emit_live=True)
            landed += 1
            state.landed = landed
        if stop is not None:
            check, reason, i = stop
            log.info("full_ai_live_stood_down account=%s fan=%s check=%s reason=%s index=%d",
                     aid, fan, check, reason, i)
            if landed:
                reply["cut"] = {"check": check, "reason": reason, "index": i}
            else:
                reply["stood_down"] = {"check": check, "reason": reason, "index": i}
        # The Offer's carrier: the `ppv` bubble, else (a tease) the reply itself. Not out = no Offer.
        ppv = next((p for p in reply["parts"] if "ppv" in p), None)
        missed = "message_id" not in ppv if ppv is not None else not landed
        if (missed and not unknown and "offer_dropped" not in reply
                and any(row.get(c) is not None for c in _OFFER_COLS)):
            await _drop_offer(row, "send" if stop is None else stop[1] if stop[0] == "offer_valid" else "stood_down")
        row["status"] = ("sent" if landed else "unconfirmed" if unknown
                         else "no_send" if stop is not None else "failed")
        if landed:                             # clear his unread badge; never undoes the send
            try:
                await asyncio.to_thread(client.mark_chat_read, fan)
            except Exception:  # noqa: BLE001
                log.warning("full_ai_live mark_chat_read failed account=%s fan=%s", aid, fan, exc_info=True)

    async def record(row: dict) -> int:
        async with get_session() as s:
            if row.get("id") is not None:      # reserved: the Offer columns have their own writers now
                rid = row["id"]
                await s.execute(update(AiDecision).where(AiDecision.id == rid).values(
                    status=row["status"], writer_model=row["writer_model"], updated_at=datetime.utcnow(),
                    reply_json=json.dumps(row["reply_json"], ensure_ascii=False)))
            else:
                rid = (await s.execute(sqlite_insert(AiDecision).values(**_values(row, anchor, row["status"]))
                                       .on_conflict_do_nothing(index_elements=_TURN_KEY)
                                       .returning(AiDecision.id))).scalar_one_or_none()
                if rid is None:                # another run's row (`taken` included): not ours to write
                    if not state.taken:
                        log.warning("full_ai_live duplicate row account=%s fan=%s key=%s",
                                    aid, fan, row["trigger_key"])
                    return await _row_id(row)
            await _write_facts(s, aid, fan, fan_updates(loaded or {}, row["reply_json"].get("fan_info") or {}))
        return int(rid)

    return full_ai_turn.TurnIO(TRIGGER_KIND, full_ai_test.hold, send, record)


async def reap(account_id: str, mine: int | None = None) -> int:
    """A dead run's leftovers, at the top of every live run: the Creator's `sending` rows become
    `unconfirmed` (a bubble may be on OF: never re-sent) and their full_ai_chat leases go, except
    for a Fan whose job is running in this process (`_running`; `mine`, the caller's own Fan, is
    reaped). Valid because one relay process runs a Creator's jobs, one job per Fan at a time
    (the executor's (account, kind, fan) run lock), and one reap per Creator at a time
    (`_reap_locks`). Returns the rows reaped."""
    aid = str(account_id)
    async with _reap_locks.setdefault(aid, asyncio.Lock()):
        live = [f for a, f in _running if a == aid and f != mine]
        async with get_session() as s:
            n = (await s.execute(update(AiDecision).where(
                AiDecision.account_id == aid, AiDecision.mode == MODE, AiDecision.status == "sending",
                AiDecision.fan_id.not_in(live))
                .values(status="unconfirmed", updated_at=datetime.utcnow()))).rowcount or 0
            await s.execute(delete(FanLease).where(FanLease.account_id == aid, FanLease.automation_kind == KIND,
                                                   FanLease.fan_id.not_in(live)))
    if n:
        log.warning("full_ai_live_reaped account=%s rows=%d", aid, n)
    return n


async def _over_message_id(account_id: str, row: dict) -> int | None:
    """A haggle row's superseded Offer (`offer_item_ref.over`, a row id) as its OF message id."""
    over = full_ai_test._loads(row.get("offer_item_ref")).get("over")
    if over is None:
        return None
    async with get_session() as s:
        mid = (await s.execute(select(AiDecision.offer_message_id).where(
            AiDecision.id == int(over), AiDecision.account_id == str(account_id),
            AiDecision.fan_id == int(row["fan_id"]), AiDecision.mode == MODE))).scalar_one_or_none()
    return int(mid) if mid is not None else None


async def send_ppv(client, look) -> dict:
    """`BUBBLE_SENDERS["ppv"]` (05, ticket 90): the priced bubble through `full_ai_ppv.send_priced`
    on the reserved row (`look.row["id"]`), its `Sent` as 04a's result dict: SENT ->
    {id, attributed}; CLEAR -> {id (a Free item's text may have landed), attributed when an id,
    offer_dropped}; UNCONFIRMED -> {id None, unknown} (never retried). A raise inside `send_priced`
    may follow the OF call (its row write, attribution): unknown too, so the Offer columns stay and
    settle_pull links it; only its no-reserved-row LookupError (nothing sent) stops as a send error."""
    b, row = look.bubble, look.row
    over = await _over_message_id(look.account_id, row)
    out = {"id": None, "attributed": False, "offer_dropped": None, "unknown": False}
    try:
        sent = await full_ai_ppv.send_priced(
            client, row_id=int(row["id"]), account_id=look.account_id, fan_id=look.fan_id, text=b["text"],
            ppv=b["ppv"], over_message_id=over, send_purpose=SEND_PURPOSE)
    except LookupError:
        raise
    except Exception:  # noqa: BLE001 — may be on OF: never retried, never dropped
        log.warning("full_ai_live ppv raised account=%s fan=%s row=%s", look.account_id, look.fan_id,
                    row["id"], exc_info=True)
        return {**out, "unknown": True}
    if sent.outcome == full_ai_ppv.SENT:
        return {**out, "id": sent.message_id, "attributed": True}
    if sent.outcome == full_ai_ppv.CLEAR:
        return {**out, "id": sent.message_id, "attributed": sent.message_id is not None, "offer_dropped": sent.dropped}
    return {**out, "unknown": True}


BUBBLE_SENDERS["ppv"] = send_ppv


async def _cooldown(account_id: str, fan_id: int) -> None:
    """`COOLDOWN_S` after a send, unless a longer pause already stands (e.g. a Human yield)."""
    async with get_session() as s:
        until = (await s.execute(select(Fan.automation_paused_until).where(
            Fan.account_id == str(account_id), Fan.fan_id == int(fan_id)))).scalar_one_or_none()
    if until is not None and until >= datetime.utcnow() + timedelta(seconds=COOLDOWN_S):
        return
    await ax.start_fan_cooldown(account_id, fan_id, cooldown_s=COOLDOWN_S)


async def sweep(account_id: str) -> dict:
    """The live rule's interval job (`anchor` None; `run` has reaped): each Turn end of a Fan who wrote in
    the last `SWEEP_WINDOW_S` (his newest chat row inbound, chat as `load` reads it: welcome outbounds
    are not answers) with `now >= due`, no live row on its key, no pending job, not on cooldown and a
    clear pre-look (`Look.client` None: no OF read) gets `enqueue`, at most `SWEEP_MAX` per pass,
    oldest first. Sends nothing, holds no lease. Stats: `swept` Turn ends found, `queued`."""
    aid, now = str(account_id), datetime.utcnow()
    rule_id = await live_rule(aid)
    if rule_id is None:
        return {"swept": 0, "queued": 0}
    try:                                           # 05: every Fan's purchases, also without a new DM
        await full_ai_settle.settle_pull(aid)
    except Exception:  # noqa: BLE001 — a failed settle never costs the missed-DM recovery
        log.warning("full_ai_live sweep settle_pull failed account=%s", aid, exc_info=True)
    since = now - timedelta(seconds=SWEEP_WINDOW_S)
    # From `messages`, not `fans.last_message_received_at`: a DM saved by a chat read or a reconcile
    # (missed on the socket) never bumps that column, and its Fan would wait for the catch-up.
    fans = select(Message.fan_id).where(Message.account_id == aid, Message.direction == "in",
                                        Message.created_at >= since)
    swept, queued = await _queue_ends(aid, rule_id, now, fans, since, SWEEP_MAX)
    if swept:
        log.info("full_ai_live_sweep account=%s swept=%d queued=%d", aid, swept, queued)
    return {"swept": swept, "queued": queued}


async def catchup_client(account_id: str):
    """`full_ai_catchup`'s OF client (reads only: the chat list, the Fans list)."""
    return await asyncio.to_thread(ax._make_client, str(account_id))


async def catchup_queue(account_id: str, fan_ids: list[int], *, max_age_s: int, cap: int,
                        late: set[int], not_before: datetime) -> dict:
    """`full_ai_catchup`'s waiting Fans (their DMs saved): the sweep's checks over just them, Turn ends
    up to `max_age_s` old, `cap` per pass (no socket-date gate); a Fan in `late` (his DM only just
    saved, his chat's scrape queued) is queued no sooner than `not_before`. Stats: `swept`, `queued`."""
    aid, now = str(account_id), datetime.utcnow()
    rule_id = await live_rule(aid)
    if rule_id is None or not fan_ids:
        return {"swept": 0, "queued": 0}
    swept, queued = await _queue_ends(aid, rule_id, now, [int(f) for f in fan_ids],
                                      now - timedelta(seconds=max_age_s), cap, late, not_before)
    return {"swept": swept, "queued": queued}


async def _queue_ends(aid: str, rule_id: int, now: datetime, fans, since: datetime, cap: int,
                      late: set[int] = frozenset(), not_before: datetime | None = None) -> tuple[int, int]:
    """The sweep's body over `fans` (a fan-id select or list): each due Turn end since `since` with no
    live row, job or cooldown and a clear pre-look -> `enqueue`, `cap` at most, oldest first."""
    from webhook_dispatch import _FULL_AI_PENDING_S, _imminent_pending_job   # lazy: imports widely
    cfg = (await full_ai_turn.stored_config(aid))["checkpoint"]
    chat = (Message.account_id == aid, Message.direction.in_(("in", "out")),
            or_(Message.direction == "in", _not_welcome()))
    rn = func.row_number().over(partition_by=Message.fan_id,
                                order_by=(Message.created_at.desc(), Message.message_id.desc())).label("rn")
    ends = select(Message.fan_id, Message.message_id, Message.created_at, Message.direction, rn).where(
        *chat, Message.fan_id.in_(fans)).subquery()
    async with get_session() as s:
        rows = (await s.execute(select(ends.c.fan_id, ends.c.message_id, ends.c.created_at).where(
            ends.c.rn == 1, ends.c.direction == "in", ends.c.created_at >= since)
            .order_by(ends.c.created_at, ends.c.message_id))).all()
        done = {(int(f), k) for f, k in (await s.execute(select(AiDecision.fan_id, AiDecision.trigger_key).where(
            AiDecision.account_id == aid, AiDecision.mode == MODE,
            AiDecision.trigger_key.in_([str(r.message_id) for r in rows])))).all()} if rows else set()
    swept = queued = 0
    for r in rows:
        if due(cfg, r) > now or (int(r.fan_id), str(r.message_id)) in done:
            continue
        if await _imminent_pending_job(aid, KIND, r.fan_id, _FULL_AI_PENDING_S) is not None:
            continue
        if (aid, int(r.fan_id)) in _running or await ax.fan_on_cooldown(aid, r.fan_id):
            continue
        swept += 1
        if queued >= cap:
            continue
        stood = await _look(Look(aid, int(r.fan_id), (r.created_at, int(r.message_id)), None, None, None, -1, 0, {}))
        if stood is not None:
            log.debug("full_ai_live_sweep_stood_down account=%s fan=%s check=%s reason=%s", aid, r.fan_id, *stood)
            continue
        queued += await enqueue(aid, int(r.fan_id), int(r.message_id), rule_id,
                                not_before=not_before if int(r.fan_id) in late else None)
    return swept, queued


async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """One Fan's live Turn (`payload["only_fan_ids"]`). Stats: the row, or `skipped` with why.
    Raises `run_slot.SlotLost` (lost before the reserve: the retry reruns the Turn; after a bubble:
    recorded `sent` + `cut slot_lost` first). The Fan is in `_running` from before the reap to the
    end; a second job of his while one runs here is busy."""
    if payload.get("anchor") is None:      # the rule's interval tick (or Run now): the sweep
        await reap(account_id)
        return await sweep(account_id)
    key = (str(account_id), int(payload["only_fan_ids"][0]))
    if key in _running:
        return await _busy(key[0], payload)
    _running.add(key)
    try:
        return await _run(account_id, payload)
    finally:
        _running.discard(key)


async def _run(account_id: str, payload: dict) -> dict:
    aid, fan = str(account_id), int(payload["only_fan_ids"][0])
    await reap(aid, fan)
    cfg = (await full_ai_turn.stored_config(aid))["checkpoint"]
    ttl = int(max(900, full_ai_turn.turn_bound_s(cfg) + 600))
    if await ax.fan_on_cooldown(aid, fan):
        return await _busy(aid, payload)
    # His one-Fan scrape still queued: the same payload at +BUSY_RETRY_S, `tries` untouched (the Turn stays
    # queued until the scrape lands; `_scrape_pending`'s SCRAPE_WAIT_S job-age cap bounds the wait).
    if await _scrape_pending(aid, fan):
        await _queue(aid, payload, datetime.utcnow() + timedelta(seconds=BUSY_RETRY_S))
        return {"skipped": "scrape_pending"}
    if not await ax.acquire_fan_lease(aid, fan, KIND, ttl_s=ttl):
        return await _busy(aid, payload)
    state = _Run()
    try:
        client = await asyncio.to_thread(ax._make_client, aid)
        await full_ai_settle.settle_pull(aid, fan)      # 05: purchases settle before the folds read
        facts = await load(aid, fan, client)
        if facts is None:
            return {"skipped": "no_turn"}
        anchor = facts.cut_rows[-1]
        pre = Look(aid, fan, (anchor.created_at, int(anchor.message_id)), client, None, None, -1, 0)
        if (why := await _look(pre)) is not None:
            log.info("full_ai_live_stood_down account=%s fan=%s check=%s reason=%s", aid, fan, *why)
            if why == ("human_yield", "human_of_app"):    # `_human` gives this reason only with its time
                await full_ai_owner_io.start_human_yield(aid, fan, pre.facts["off_switch"].human_at)
            return {"skipped": "%s:%s" % why}   # the pre-look: no Router / Writer call, no row
        res = await full_ai_turn.run_turn(facts, _io(aid, fan, anchor, client, state,
                                                     dict(facts.fan_info), facts.config))
        if state.taken:
            return {"skipped": "taken"}
        log.info("full_ai_turn account=%s fan=%s mode=live route=%s status=%s", aid, fan,
                 res.decision.route, res.status)
        if state.lost is not None:         # recorded `sent` + cut; the finally rests the Fan
            raise state.lost
        return {"row_id": res.row_id, "route": res.decision.route, "row_status": res.status,
                "sent": sum("message_id" in p for p in res.parts)}
    except _Draining:                      # the same payload after the restart, `tries` untouched
        log.info("full_ai_live_draining account=%s fan=%s: re-queued", aid, fan)
        await _queue(aid, payload, datetime.utcnow() + timedelta(seconds=BUSY_RETRY_S))
        return {"skipped": "draining"}
    except run_slot.SlotLost:              # the executor's retry path, not a failure: no failed log
        raise
    except Exception:
        log.warning("full_ai_live_failed account=%s fan=%s", aid, fan, exc_info=True)
        raise
    finally:
        try:
            if state.landed:               # a bubble is on OF, however the run ended
                await _cooldown(aid, fan)
            await ax.release_fan_lease(aid, fan, holder=KIND)
        finally:
            ax.end_send()                  # recorded and rested: drain() stops waiting (no-op if never claimed)
