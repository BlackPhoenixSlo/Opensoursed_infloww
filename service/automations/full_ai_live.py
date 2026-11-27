"""automations/full_ai_live.py — Full AI Chat's live I/O twin of `full_ai_test` (Mode `live`, 04a).

A Creator whose enabled `full_ai_chat` rule says `trigger_json.mode == "live"` answers a Fan's DM on
OnlyFans with the Test chat's Turn (`full_ai_turn.run_turn(facts, io)`). The job (`full_ai_chat.run`
dispatches here) leases the Fan, loads fresh facts (his newest unanswered run is the Turn), runs the
Turn and sends its text bubbles one by one. Never double-send (ticket 65): just before the first OF
call the row is INSERTed `sending` on the Turn key (`_reserve`; no id back = another run owns the
Turn, send nothing); `record` then UPDATEs only its `status`, `reply_json`, `writer_model`
(and writes the Turn's facts to `fans`). A run
that dies after the reserve leaves `sending`, which the next run's `reap` turns `unconfirmed`:
never sent again (`load` finds the row). Last look (ticket 66, `full_ai_look`): `LAST_LOOK`, one
ordered check list, runs as the pre-look before the Router and again before each bubble; the first
reason stands the Turn down. Each bubble goes out through its kind's `BUBBLE_SENDERS` entry, on the
account's write gate (`ax.of_write_paced`); once the gate grants the write, `full_ai_look.gate` re-runs
the switch, owner and anchor slots (DB only) right before the POST. A DM he sent before her first bubble stands the
Turn down (`overtaken`, also off the OF read); one during the burst lets it finish (ticket 66), keeps
his read badge and queues his job, whose `load` takes the DMs that landed mid-burst as its Turn.

  live_rule(account_id)              id of the enabled full_ai_chat rule in Mode live, else None
  due(config, dm)                    when the reply to `dm` may go: its time + the drawn reply speed
  enqueue(account, fan, mid, rule)   the Fan's job at `due` (hook + sweep); False = one is pending
  load(account_id, fan_id, client)   TurnFacts | None (no unanswered Turn, or its row exists)
  reap(account_id, mine)             `sending` rows -> `unconfirmed`, the Creator's full_ai_chat leases dropped,
                                     but a Fan whose job runs in this process (`_running`, not `mine`)
  run(account_id, payload, *, run_id)   reap -> off switch -> cooldown -> scrape wait -> lease -> load -> pre-look -> run_turn
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

The only Full AI module that may import the OF client factory, the lease or the DM rate;
`full_ai_ppv` also writes through the OF write seam (`ax.of_write_paced`) (AST scan in
test_full_ai_live.py; `full_ai_look` imports none of them).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import delete, func, or_, select, true, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax
import dm_rate
import read_flip
import run_decide
import run_slot
import send_ops
from env_knob import env_float
from attribution import write_outbound_attribution
from automations import (
    _info_jev, cat_stickers, full_ai_chat, full_ai_look, full_ai_owned, full_ai_owner_io, full_ai_photo,
    full_ai_ppv, full_ai_settle, full_ai_test, full_ai_turn,
)
from automations import _router_jev as router
from automations import full_ai_offer_details
from automations.full_ai_look import Look
from automations.full_ai_scene import saved_scene, scene_words
from automations._send_failure import quarantine_if_undeliverable, skip_unreachable_fan
from automations._typing_hold import (
    hold_with_typing, load_typing_indicator, load_typing_wpm, typing_delay_seconds,
)
from automations.rhythm import INLINE_MAX_S
from db.engine import get_session
from db.models import AiDecision, AutomationRule, Fan, FanLease, Message, ScheduledJob

log = logging.getLogger("of-relay.automation.full_ai_live")

MODE, KIND, TRIGGER_KIND = full_ai_look.MODE, "full_ai_chat", "inbound"
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


# Measured on OF: DMs 1.0-2.8 s apart, none refused; the DM window still caps the minute. 11 s is the shared write gap.
def _write_gap() -> float:
    return min(11.0, env_float("FULL_AI_WRITE_GAP_S", 2.0, lo=0.0))


WRITE_GAP_S = _write_gap()
_running: set[tuple[str, int]] = set()
_reap_locks: dict[str, asyncio.Lock] = {}
_sweep_after: dict[str, tuple] = {}


def _is_live(raw: str | None) -> bool:
    try:
        return (json.loads(raw or "{}") or {}).get("mode") == MODE
    except (ValueError, TypeError, AttributeError):
        return False


async def live_rule(account_id: str) -> int | None:
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
    return dm.created_at + timedelta(seconds=full_ai_test.hold(config, str(dm.message_id)))


def _restore_parked(aid, fan, mid):
    payload = ScheduledJob.payload_json
    return select(ScheduledJob.id).where(
        ScheduledJob.account_id == aid, ScheduledJob.kind == KIND, ScheduledJob.status == "error",
        ScheduledJob.last_error == run_decide.RESTORE_REASON,
        ax._json_field(payload, "only_fan_ids[0]") == fan,
        ax._json_field(payload, "anchor") == mid,
    ).exists()


async def enqueue(account_id: str, fan_id: int, message_id: int, rule_id: int, *,
                  not_before: datetime | None = None) -> bool:
    from webhook_dispatch import _FULL_AI_PENDING_S, _imminent_pending_job
    aid, fan, mid = str(account_id), int(fan_id), int(message_id)
    if await _imminent_pending_job(aid, KIND, fan, _FULL_AI_PENDING_S) is not None:
        return False
    cfg = (await full_ai_turn.stored_config(aid))["checkpoint"]
    async with get_session() as s:
        if send_ops.cells() and await s.scalar(select(_restore_parked(aid, fan, mid))):
            return False
        dm = await s.get(Message, (aid, fan, mid))
    if dm is None:
        log.warning("full_ai_live_enqueue_no_dm account=%s fan=%s msg=%s", aid, fan, mid)
        return False
    run_at = due(cfg, dm)
    await _queue(aid, {"only_fan_ids": [fan], "anchor": mid, "_rule_id": int(rule_id), "tries": 0},
                 max(run_at, not_before) if not_before is not None else run_at)
    return True


async def _queue(account_id: str, payload: dict, run_at: datetime) -> None:
    from webhook_dispatch import _schedule_wake
    await ax.enqueue_job(account_id, KIND, payload=payload, run_at=run_at)
    _schedule_wake(max(0.0, (run_at - datetime.utcnow()).total_seconds()))


async def _scrape_pending(account_id: str, fan_id: int) -> bool:
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
    tries = int(payload.get("tries") or 0) + 1
    if tries >= BUSY_RUNS:
        return {"skipped": "busy"}
    await _queue(account_id, {**payload, "tries": tries}, datetime.utcnow() + timedelta(seconds=BUSY_RETRY_S))
    return {"skipped": "busy", "tries": tries}


def _not_welcome():
    return or_(Message.automation_kind.is_(None), Message.automation_kind != WELCOME)


async def load(account_id: str, fan_id: int, client) -> full_ai_turn.TurnFacts | None:
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
        tail = []
        if not runs and cut is not None:
            runs, tail = await _mid_burst_runs(s, aid, fan, chat)
        if not runs:
            return None
        run_cut, turn = runs[-1]
        anchor = turn[-1]
        if send_ops.cells() and await s.scalar(select(_restore_parked(aid, fan, anchor.message_id))):
            return None
        if (await s.execute(select(AiDecision.id).where(
                AiDecision.account_id == aid, AiDecision.fan_id == fan, AiDecision.mode == MODE,
                AiDecision.trigger_key == str(anchor.message_id)))).first() is not None:
            return None
        rows = list((await s.execute(select(AiDecision).where(
            AiDecision.account_id == aid, AiDecision.fan_id == fan, AiDecision.mode == MODE)
            .order_by(AiDecision.id))).scalars())
    dared, due = full_ai_test.dared_of(rows), full_ai_test.dare_due_of(rows, anchor.created_at)
    photos = bool(side[full_ai_photo.KEY]) or dared or due
    photo = await full_ai_photo.describe_turn(aid, turn, client) if photos else None
    async with get_session() as s:
        thread_rows, _other_lane, _tx = await full_ai_chat._reads(s, aid, fan, run_cut, turn)
        thread_rows = [*thread_rows, *tail]     # a mid-burst Turn: her bubbles already out after his DM
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
        dared=dared, dare_due=due,
        offer_ask=full_ai_offer_details.live_ask(rows, anchor.created_at, k["tease"], turn))


async def _mid_burst_runs(s, aid: str, fan: int, chat) -> tuple[list[tuple[tuple, list]], list]:
    key = (await s.execute(select(AiDecision.trigger_key).where(
        AiDecision.account_id == aid, AiDecision.fan_id == fan, AiDecision.mode == MODE)
        .order_by(AiDecision.id.desc()).limit(1))).scalar()
    a = await s.get(Message, (aid, fan, int(key))) if key and str(key).isdigit() else None
    if a is None:
        return [], []
    later = list((await s.execute(select(Message).where(
        *chat, Message.direction.in_(("in", "out")), or_(Message.direction == "in", _not_welcome()),
        full_ai_chat._after(a.created_at, a.message_id)).order_by(Message.created_at, Message.message_id))).scalars())
    if any(m.direction == "out" and m.automation_kind != KIND for m in later):
        return [], []
    turn = [m for m in later if m.direction == "in"]
    if not turn:
        return [], []
    first = (turn[0].created_at, turn[0].message_id)
    before = [m for m in later if m.direction == "out" and (m.created_at, m.message_id) < first]
    tail = [m for m in later if m.direction == "out" and (m.created_at, m.message_id) > first]
    return [((before[-1].created_at, before[-1].message_id) if before else (a.created_at, a.message_id), turn)], tail


def _folds(rows, sold: full_ai_owned.Sold, now: datetime, newest_out: tuple | None) -> dict:
    open_offer = full_ai_owned.open_offer_live(rows, now)
    offer = full_ai_test.offer_line(open_offer)
    tease = full_ai_test.pending_tease_of(rows, now)
    if tease is not None and (newest_out is None or newest_out[1] not in full_ai_test.tease_bubble_ids(rows, tease)):
        tease = None
    pending = (" ".join(p["text"] for p in full_ai_test._loads(tease.reply_json).get("parts") or [] if p.get("text"))
               if tease is not None else router.pending_offer(offer))
    bought = full_ai_owned.purchases_live(sold.paid_msgs, sold.txs)
    return {"offer": offer, "pending": pending, "offer_piece": full_ai_test.teased_of(open_offer),
            "tease": full_ai_test.teased_of(tease), "bought": bought[-1] if bought else None,
            "spent": [p for p in bought if p.kind == "ppv_message"],
            "tips": [p.amount_cents for p in bought if p.kind == "tip"],
            # reserved: an attempted, unresolved priced Offer's media is not offered again until settle links it
            "owned": full_ai_owned.owned_live(rows, sold.cross) | full_ai_owned.reserved_of(rows),
            "sent": full_ai_owned.sent_live(rows, sold.vault_media),
            "scene": saved_scene(rows, now, full_ai_test.SITTING_GAP_S)}


def _state_keys(config: dict, rows, now: datetime, info: dict, scene) -> dict:
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
    lost: Exception | None = None  # an interruption after a bubble lands is raised after recording
    landed: int = 0                       # bubbles on OF (the job's finally rests the Fan when > 0)


class _Draining(Exception):
    pass


def _values(row: dict, anchor: Message, status: str) -> dict:
    return {**row, "status": status,
            "anchor_message_id": anchor.message_id, "anchor_created_at": anchor.created_at,
            "reply_json": json.dumps(row["reply_json"], ensure_ascii=False),
            "jev_json": json.dumps(row["jev_json"], ensure_ascii=False)}


# Never double-send: the row is INSERTed `sending` on the Turn key before the first OF call; no id back means another run owns the Turn.
async def _reserve(row: dict, anchor: Message) -> int | None:
    async with get_session() as s:
        rid = (await s.execute(sqlite_insert(AiDecision).values(**_values(row, anchor, "sending"))
                               .on_conflict_do_nothing(index_elements=_TURN_KEY)
                               .returning(AiDecision.id))).scalar_one_or_none()
    if rid is not None:
        row["id"] = int(rid)
    return rid


async def _unreserve(row: dict) -> None:
    async with get_session() as s:
        await s.execute(delete(AiDecision).where(AiDecision.id == row["id"]))


async def _row_id(row: dict) -> int:
    async with get_session() as s:
        return int((await s.execute(select(AiDecision.id).where(
            AiDecision.account_id == row["account_id"], AiDecision.fan_id == row["fan_id"],
            AiDecision.mode == MODE, AiDecision.trigger_key == row["trigger_key"]))).scalar_one())


async def _attribute(account_id: str, fan_id: int, mid: int, body: str, created_at: datetime) -> bool:
    try:
        await write_outbound_attribution(
            account_id=account_id, fan_id=fan_id, message_id=int(mid), sent_by_employee_id=None,
            body=body, price_cents=0, created_at=created_at, automation_kind=KIND, emit_live=True)
    except Exception:  # noqa: BLE001 — OF has it: never a send error
        log.warning("full_ai_live attribution failed account=%s fan=%s msg=%s", account_id, fan_id, mid,
                    exc_info=True)
        return False
    return True


async def _dm(client, look: Look, text: str, **kw) -> dict | send_ops.Reconciled:
    """One DM on OF; writes its own `messages` row with OF's text and time (attributed)."""
    turn = f"{MODE}:{look.row['trigger_key']}"
    res = await ax.of_write_paced(
        look.account_id,
        lambda: send_ops.automated_sync(look.account_id, "full_ai_live", look.fan_id, turn,
                                        lambda: client.send_message(look.fan_id, text, **kw), part=look.index),
        send_purpose=SEND_PURPOSE, tries=1, dm=True,
        min_gap_s=WRITE_GAP_S, before_write=look.before_write)
    if send_ops.is_reconciled(res):
        return send_ops.RECONCILED
    mid = res.get("id") if isinstance(res, dict) else None
    ok = bool(mid) and await _attribute(look.account_id, look.fan_id, int(mid), str(res.get("text") or text),
                                        ax._parse_iso(res.get("createdAt")) or datetime.utcnow())
    return {"id": int(mid) if mid else None, "attributed": ok, "offer_dropped": None, "unknown": False}


async def _send_text(client, look: Look) -> dict:
    return await _dm(client, look, look.bubble["text"])


async def _send_gif(client, look: Look) -> dict:
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


def _kind(bubble: dict) -> str:
    return "ppv" if "ppv" in bubble else "gif" if "gif" in bubble else "text"


async def _drop_offer(row: dict, why: str) -> None:
    row["reply_json"]["offer_dropped"] = why
    row.update(full_ai_ppv.OFFER_NULL)
    if row.get("id") is not None:
        async with get_session() as s:
            await s.execute(update(AiDecision).where(AiDecision.id == row["id"]).values(**full_ai_ppv.OFFER_NULL))


async def _after_burst(aid: str, fan: int, at: tuple[datetime, int], client, landed: int) -> None:
    try:
        newest = await full_ai_look.newest_inbound(aid, fan)
        if newest is not None and tuple(newest) > tuple(at):
            rule_id = await live_rule(aid)
            if rule_id is not None:
                await enqueue(aid, fan, int(newest[1]), rule_id)
            log.info("full_ai_live_new_dm account=%s fan=%s msg=%s: badge kept, queued", aid, fan, newest[1])
            return
        if not landed:
            return
        read, read_at = await read_flip.write(aid, fan, lambda: client.mark_chat_read(fan), only_if_unread=True)
    except Exception:  # noqa: BLE001 — the burst stands; the badge is cosmetic
        log.warning("full_ai_live after-burst failed account=%s fan=%s", aid, fan, exc_info=True)
        return
    try:
        await read_flip.after_write(aid, fan, 0, read, at=read_at)
    except Exception:  # noqa: BLE001
        log.warning("full_ai_live read flip failed account=%s fan=%s", aid, fan, exc_info=True)


def _io(account_id: str, fan_id: int, anchor: Message, client, state: _Run,
        loaded: dict | None = None, config: dict | None = None) -> full_ai_turn.TurnIO:
    config = config or {}
    aid, fan = str(account_id), int(fan_id)
    at = (anchor.created_at, int(anchor.message_id))

    async def send(row: dict, parts: list[str], pick=None, *, over=None, desc=None, gif=None) -> None:
        # The row and bubble shapes of the Test chat (Offer columns included, the gif part last).
        full_ai_test.send(row, parts, pick, over=over, desc=desc)
        if gif:
            row["reply_json"]["parts"].append(gif)
        reply, landed, unknown, stop = row["reply_json"], 0, False, None
        ppv = next((part for part in reply["parts"] if "ppv" in part), None)
        ppv_reconciled = False
        wpm = await load_typing_wpm(aid) if config.get("typing_sign") else None
        frame = bool(config.get("typing_notification")) and await load_typing_indicator(aid)

        for i, part in enumerate(reply["parts"]):
            sender = BUBBLE_SENDERS.get(_kind(part))
            if sender is None:
                stop = ("sender", f"{_kind(part)}_unbuilt", i)
                break
            try:
                # The relay drains (SIGTERM): no type-time hold left and a running one ends, so the
                # Turn ends inside RELAY_DRAIN_S.
                secs = (typing_delay_seconds(part["text"], wpm)
                        if wpm is not None and "gif" not in part and not ax.draining() else 0)
                await hold_with_typing(aid, fan, secs, typing_indicator=frame, cut=ax.draining)
                await dm_rate.turn(aid, release_budget_s=INLINE_MAX_S)
                look = Look(aid, fan, at, client, row, part, i, landed)
                why = await full_ai_look.last_look(look)
                await full_ai_look.after_look(look, why)
            except run_slot.SlotLost as e:
                # Nothing landed yet: re-raise so the retry reruns the whole Turn.
                if not landed:
                    raise
                reply["cut"] = {"check": "slot_lost", "reason": "slot_lost", "index": i}
                state.lost = e
                break
            except Exception as e:
                if not landed:
                    raise
                dm_rate.release(aid)
                log.warning("full_ai_live bubble prep failed account=%s fan=%s", aid, fan, exc_info=True)
                reply["cut"] = {"check": "error", "reason": type(e).__name__, "index": i}
                break
            if why is not None:
                dm_rate.release(aid)
                stop = (*why, i)
                break
            if row.get("id") is None and not ax.begin_send():
                dm_rate.release(aid)
                raise _Draining
            if row.get("id") is None and await _reserve(row, anchor) is None:
                dm_rate.release(aid)
                state.taken = True
                log.warning("full_ai_live turn taken account=%s fan=%s key=%s", aid, fan, row["trigger_key"])
                return
            look = replace(look, before_write=lambda look=look: full_ai_look.gate(look))
            try:
                res = await sender(client, look)
            except full_ai_look.Stand as e:
                dm_rate.release(aid)
                await full_ai_look.after_look(e.look, e.why)
                stop = (*e.why, i)
                break
            except Exception as e:  # noqa: BLE001 — stop the Turn, never retry a send
                dm_rate.release(aid)           # frees only an unused place (nothing reached OF)
                if send_ops.refusal_reason(e) == "cell_held":
                    if not landed:
                        await _unreserve(row)
                        raise
                    reply["cut"] = {"check": "cell_held", "reason": "cell_held", "index": i}
                    state.lost = e
                    break
                await skip_unreachable_fan(aid, fan, e, log=log)
                log.warning("full_ai_live send failed account=%s fan=%s", aid, fan, exc_info=True)
                reply["cut"] = {"check": "send_error", "reason": type(e).__name__, "index": i}
                break
            if send_ops.is_reconciled(res):
                if part is ppv:
                    ppv_reconciled = True
                landed += 1
                state.landed = landed
                continue
            if res.get("offer_dropped"):       # its sender already cleared the Offer columns
                reply["offer_dropped"] = res["offer_dropped"]
            # May be on OF: never retried, Offer columns kept.
            if res.get("unknown"):
                unknown = True
                reply["cut"] = {"check": "send_error", "reason": f"{_kind(part)}_unconfirmed", "index": i}
                break
            mid = res.get("id")
            if not mid:
                dm_rate.release(aid)
                if not landed and not res.get("offer_dropped"):
                    await quarantine_if_undeliverable(client, aid, fan, log=log)
                reply["cut"] = {"check": "send_error", "reason": "no_id", "index": i}
                break
            part["message_id"] = int(mid)
            if not res.get("attributed"):
                await _attribute(aid, fan, int(mid), str(part.get("text") or ""), datetime.utcnow())
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
        missed = not (ppv.get("message_id") or ppv_reconciled) if ppv is not None else not landed
        if (missed and not unknown and "offer_dropped" not in reply
                and any(row.get(c) is not None for c in full_ai_ppv.OFFER_COLS)):
            await _drop_offer(row, "send" if stop is None else stop[1] if stop[0] == "offer_valid" else "stood_down")
        row["status"] = ("sent" if landed else "unconfirmed" if unknown
                         else "no_send" if stop is not None else "failed")
        if landed or (stop is not None and stop[0] == "overtaken"):
            await _after_burst(aid, fan, at, client, landed)

    async def record(row: dict) -> int:
        async with get_session() as s:
            if row.get("id") is not None:
                rid = row["id"]
                await s.execute(update(AiDecision).where(AiDecision.id == rid).values(
                    status=row["status"], writer_model=row["writer_model"], updated_at=datetime.utcnow(),
                    reply_json=json.dumps(row["reply_json"], ensure_ascii=False)))
            else:
                rid = (await s.execute(sqlite_insert(AiDecision).values(**_values(row, anchor, row["status"]))
                                       .on_conflict_do_nothing(index_elements=_TURN_KEY)
                                       .returning(AiDecision.id))).scalar_one_or_none()
                if rid is None:
                    if not state.taken:
                        log.warning("full_ai_live duplicate row account=%s fan=%s key=%s",
                                    aid, fan, row["trigger_key"])
                    return await _row_id(row)
            await _write_facts(s, aid, fan, fan_updates(loaded or {}, row["reply_json"].get("fan_info") or {}))
        return int(rid)

    return full_ai_turn.TurnIO(TRIGGER_KIND, full_ai_test.hold, send, record)


# `sending` rows of a dead run become `unconfirmed`: a bubble may be on OF, so never re-sent.
async def reap(account_id: str, mine: int | None = None) -> int:
    aid = str(account_id)
    # A Turn joins _running before its own reap and writes its lease/row after it, so it must wait out a reap whose _running read missed it.
    async with _reap_locks.setdefault(aid, asyncio.Lock()):
        live = [f for a, f in _running if a == aid and f != mine]
        dead = (AiDecision.account_id == aid, AiDecision.mode == MODE, AiDecision.status == "sending",
                AiDecision.fan_id.not_in(live))
        async with get_session() as s:
            await s.execute(update(AiDecision).where(
                *dead, AiDecision.offer_attempt_at.is_(None), AiDecision.offer_message_id.is_(None),
                AiDecision.offer_price_cents.is_not(None)).values(**full_ai_ppv.OFFER_NULL))
            n = (await s.execute(update(AiDecision).where(*dead)
                .values(status="unconfirmed", updated_at=datetime.utcnow()))).rowcount or 0
            await s.execute(delete(FanLease).where(FanLease.account_id == aid, FanLease.automation_kind == KIND,
                                                   FanLease.fan_id.not_in(live)))
    if n:
        log.warning("full_ai_live_reaped account=%s rows=%d", aid, n)
    return n


async def _over_message_id(account_id: str, row: dict) -> int | None:
    over = full_ai_test._loads(row.get("offer_item_ref")).get("over")
    if over is None:
        return None
    async with get_session() as s:
        mid = (await s.execute(select(AiDecision.offer_message_id).where(
            AiDecision.id == int(over), AiDecision.account_id == str(account_id),
            AiDecision.fan_id == int(row["fan_id"]), AiDecision.mode == MODE))).scalar_one_or_none()
    return int(mid) if mid is not None else None


async def send_ppv(client, look) -> dict | send_ops.Reconciled:
    b, row = look.bubble, look.row
    over = await _over_message_id(look.account_id, row)
    out = {"id": None, "attributed": False, "offer_dropped": None, "unknown": False}
    try:
        sent = await full_ai_ppv.send_priced(
            client, row_id=int(row["id"]), account_id=look.account_id, fan_id=look.fan_id, text=b["text"],
            ppv=b["ppv"], over_message_id=over, send_purpose=SEND_PURPOSE, before_write=look.before_write,
            min_gap_s=WRITE_GAP_S)
    except full_ai_ppv.MaybeSent as e:  # may be on OF: never retried, never dropped
        log.warning("full_ai_live ppv raised account=%s fan=%s row=%s", look.account_id, look.fan_id,
                    row["id"], exc_info=True)
        return {**out, "id": e.message_id} if e.message_id else {**out, "unknown": True}
    if send_ops.is_reconciled(sent):
        return send_ops.RECONCILED
    if sent.outcome == full_ai_ppv.SENT:
        return {**out, "id": sent.message_id, "attributed": True}
    if sent.outcome == full_ai_ppv.CLEAR:
        return {**out, "id": sent.message_id, "attributed": sent.message_id is not None, "offer_dropped": sent.dropped}
    return {**out, "unknown": True}


BUBBLE_SENDERS["ppv"] = send_ppv


async def _cooldown(account_id: str, fan_id: int) -> None:
    async with get_session() as s:
        until = (await s.execute(select(Fan.automation_paused_until).where(
            Fan.account_id == str(account_id), Fan.fan_id == int(fan_id)))).scalar_one_or_none()
    if until is not None and until >= datetime.utcnow() + timedelta(seconds=COOLDOWN_S):
        return
    await ax.start_fan_cooldown(account_id, fan_id, cooldown_s=COOLDOWN_S)


async def sweep(account_id: str) -> dict:
    aid, now = str(account_id), datetime.utcnow()
    rule_id = await live_rule(aid)
    if rule_id is None:
        return {"swept": 0, "queued": 0}
    try:
        await full_ai_settle.settle_pull(aid)
    except Exception:  # noqa: BLE001 — a failed settle never costs the missed-DM recovery
        log.warning("full_ai_live sweep settle_pull failed account=%s", aid, exc_info=True)
    since = now - timedelta(seconds=SWEEP_WINDOW_S)
    # From `messages`, not `fans.last_message_received_at`: a DM saved by a chat read or reconcile never bumps that column.
    fans = select(Message.fan_id).where(Message.account_id == aid, Message.direction == "in",
                                        Message.created_at >= since)
    swept, queued, last = await _queue_ends(aid, rule_id, now, fans, since, SWEEP_MAX, after=_sweep_after.get(aid))
    if last is None:
        _sweep_after.pop(aid, None)
    else:
        _sweep_after[aid] = last
    if swept:
        log.info("full_ai_live_sweep account=%s swept=%d queued=%d", aid, swept, queued)
    return {"swept": swept, "queued": queued}


async def catchup_client(account_id: str):
    return await asyncio.to_thread(ax._make_client, str(account_id))


async def catchup_queue(account_id: str, fan_ids: list[int], *, max_age_s: int, cap: int,
                        late: set[int], not_before: datetime) -> dict:
    aid, now = str(account_id), datetime.utcnow()
    rule_id = await live_rule(aid)
    if rule_id is None or not fan_ids:
        return {"swept": 0, "queued": 0}
    swept, queued, _ = await _queue_ends(aid, rule_id, now, [int(f) for f in fan_ids],
                                      now - timedelta(seconds=max_age_s), cap, late, not_before)
    return {"swept": swept, "queued": queued}


async def _queue_ends(aid: str, rule_id: int, now: datetime, fans, since: datetime, cap: int,
                      late: set[int] = frozenset(), not_before: datetime | None = None,
                      after: tuple | None = None) -> tuple[int, int, tuple | None]:
    from webhook_dispatch import _FULL_AI_PENDING_S, _imminent_pending_jobs
    try:
        cfg = (await full_ai_turn.stored_config(aid))["checkpoint"]
    except ValueError:
        log.warning("full_ai_live_sweep_config_failed account=%s: no Turn queued", aid, exc_info=True)
        return 0, 0, None
    chat = (Message.account_id == aid, Message.direction.in_(("in", "out")),
            or_(Message.direction == "in", _not_welcome()))
    rn = func.row_number().over(partition_by=Message.fan_id,
                                order_by=(Message.created_at.desc(), Message.message_id.desc())).label("rn")
    ends = select(Message.fan_id, Message.message_id, Message.created_at, Message.direction, rn).where(
        *chat, Message.fan_id.in_(fans)).subquery()
    unparked = (~_restore_parked(aid, ends.c.fan_id, ends.c.message_id),) if send_ops.cells() else ()
    async with get_session() as s:
        rows = (await s.execute(select(ends.c.fan_id, ends.c.message_id, ends.c.created_at).where(
            ends.c.rn == 1, ends.c.direction == "in", ends.c.created_at >= since, *unparked)
            .order_by(ends.c.created_at, ends.c.message_id))).all()
        done = {(int(f), k) for f, k in (await s.execute(select(AiDecision.fan_id, AiDecision.trigger_key).where(
            AiDecision.account_id == aid, AiDecision.mode == MODE,
            AiDecision.trigger_key.in_([str(r.message_id) for r in rows])))).all()} if rows else set()
    rows = [r for r in rows if due(cfg, r) <= now and (int(r.fan_id), str(r.message_id)) not in done
            and (aid, int(r.fan_id)) not in _running]
    if not rows:
        return 0, 0, None
    fan_ids = {int(r.fan_id) for r in rows}
    busy = (set(await _imminent_pending_jobs(aid, KIND, fan_ids, _FULL_AI_PENDING_S))
            | await ax.fans_on_cooldown(aid, fan_ids))
    rows = [r for r in rows if int(r.fan_id) not in busy]
    swept = len(rows)
    claimed = await full_ai_owner_io.claimed_ids(aid, {int(r.fan_id) for r in rows}) if rows else set()
    if after is not None:
        rows = ([r for r in rows if (r.created_at, int(r.message_id)) > after]
                + [r for r in rows if (r.created_at, int(r.message_id)) <= after])
    queued = looked = 0
    last = None
    for r in rows:
        if int(r.fan_id) not in claimed:
            continue
        if looked >= cap:
            break
        looked += 1
        last = (r.created_at, int(r.message_id))
        stood = await full_ai_look.last_look(Look(aid, int(r.fan_id), (r.created_at, int(r.message_id)),
                                                  None, None, None, -1, 0, {}))
        if stood is not None:
            log.debug("full_ai_live_sweep_stood_down account=%s fan=%s check=%s reason=%s", aid, r.fan_id, *stood)
            continue
        queued += await enqueue(aid, int(r.fan_id), int(r.message_id), rule_id,
                                not_before=not_before if int(r.fan_id) in late else None)
    else:
        last = None
    return swept, queued, last


async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """One Fan's live Turn (`payload["only_fan_ids"]`). Stats: the row, or `skipped` with why.
    Raises `run_slot.SlotLost` (lost before the reserve: the retry reruns the Turn; after a bubble:
    recorded `sent` + `cut slot_lost` first). The Fan is in `_running` from before the reap to the
    end; a second job of his while one runs here is busy."""
    if payload.get("anchor") is None:
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
    if (off := await full_ai_owner_io.off_reason(aid)) is not None:
        log.info("full_ai_live_stood_down account=%s fan=%s check=off_switch reason=%s", aid, fan, off)
        return {"skipped": f"off_switch:{off}"}
    try:
        cfg = (await full_ai_turn.stored_config(aid))["checkpoint"]
    except ValueError:
        log.warning("full_ai_live_stood_down account=%s fan=%s check=config reason=unreadable", aid, fan)
        return {"skipped": "bad_config"}
    ttl = int(max(900, full_ai_turn.turn_bound_s(cfg) + 600))
    if await ax.fan_on_cooldown(aid, fan):
        return await _busy(aid, payload)
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
        why = await full_ai_look.last_look(pre)
        await full_ai_look.after_look(pre, why)
        if why is not None:
            log.info("full_ai_live_stood_down account=%s fan=%s check=%s reason=%s", aid, fan, *why)
            return {"skipped": "%s:%s" % why}   # the pre-look: no Router / Writer call, no row
        res = await full_ai_turn.run_turn(facts, _io(aid, fan, anchor, client, state,
                                                     dict(facts.fan_info), facts.config))
        if state.taken:
            return {"skipped": "taken"}
        log.info("full_ai_turn account=%s fan=%s mode=live route=%s status=%s", aid, fan,
                 res.decision.route, res.status)
        if state.lost is not None:
            raise state.lost
        return {"row_id": res.row_id, "route": res.decision.route, "row_status": res.status,
                "sent": sum("message_id" in p for p in res.parts)}
    except _Draining:
        log.info("full_ai_live_draining account=%s fan=%s: re-queued", aid, fan)
        await _queue(aid, payload, datetime.utcnow() + timedelta(seconds=BUSY_RETRY_S))
        return {"skipped": "draining"}
    except run_slot.SlotLost:
        raise
    except Exception:
        log.warning("full_ai_live_failed account=%s fan=%s", aid, fan, exc_info=True)
        raise
    finally:
        try:
            if state.landed:
                await _cooldown(aid, fan)
            await ax.release_fan_lease(aid, fan, holder=KIND)
        finally:
            ax.end_send()
