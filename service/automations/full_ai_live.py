"""automations/full_ai_live.py — Full AI Chat's live I/O twin of `full_ai_test` (Mode `live`, 04a).

A Creator whose enabled `full_ai_chat` rule says `trigger_json.mode == "live"` answers a Fan's DM on
OnlyFans with the Test chat's Turn (`full_ai_turn.run_turn(facts, io)`). The job (`full_ai_chat.run`
dispatches here) leases the Fan, loads fresh facts (his newest unanswered run is the Turn), runs the
Turn and sends its text bubbles one by one; the row is INSERTed once at the end.

  live_rule(account_id)              id of the enabled full_ai_chat rule in Mode live, else None
  load(account_id, fan_id, client)   TurnFacts | None (no unanswered Turn, or its row exists)
  run(account_id, payload, *, run_id)   cooldown -> lease -> load -> run_turn -> cooldown 10 s + release

The only Full AI module that may import the OF client factory, the lease, the DM rate or the OF
write seam (AST scan in test_full_ai_live.py). Ticket 63 is the tracer: no wait, no last-look, no
reserve, no sell or fold fields (tickets 65-71).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import or_, select, true
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax
import dm_rate
from attribution import write_outbound_attribution
from automations import full_ai_chat, full_ai_photo, full_ai_test, full_ai_turn
from automations._typing_hold import hold_with_typing, load_typing_wpm, typing_delay_seconds
from automations.rhythm import INLINE_MAX_S
from db.engine import get_session
from db.models import AiDecision, AutomationRule, Fan, Message

log = logging.getLogger("of-relay.automation.full_ai_live")

MODE, KIND, TRIGGER_KIND = "live", "full_ai_chat", "inbound"
SEND_PURPOSE = "gated"                 # audience_include.AUDIENCE_SENDER_CLASSIFICATION["full_ai_live"]
COOLDOWN_S = 10                        # after a send; never shortens a longer pause
NAME_FIELDS = ("real_name", "generated_nickname", "of_display_name")   # the rest: ticket 69
WELCOME = "welcome"                    # send_welcome's automation_kind: never answers his DM
_TURN_KEY = ["account_id", "fan_id", "mode", "trigger_key"]


async def live_rule(account_id: str) -> int | None:
    """The enabled `full_ai_chat` rule whose `trigger_json.mode` is "live", else None."""
    async with get_session() as s:
        rules = (await s.execute(select(AutomationRule.id, AutomationRule.trigger_json).where(
            AutomationRule.account_id == str(account_id), AutomationRule.kind == KIND,
            AutomationRule.is_enabled.is_(True)).order_by(AutomationRule.id))).all()
    for rid, raw in rules:
        try:
            if (json.loads(raw or "{}") or {}).get("mode") == MODE:
                return int(rid)
        except (ValueError, TypeError, AttributeError):
            continue
    return None


def _not_welcome():
    return or_(Message.automation_kind.is_(None), Message.automation_kind != WELCOME)


async def load(account_id: str, fan_id: int, client) -> full_ai_turn.TurnFacts | None:
    """The Fan's open Turn: his run after her newest non-welcome outbound (Anchor = its last
    inbound), its thread, Pending offer and last purchase (`full_ai_chat._reads`), his name fields
    from `fans`, the checkpoint config. None when there is no such run or its live row exists.
    `client` is the job's OF client (unused until ticket 71's photo read)."""
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
        thread_rows, offer, bought = await full_ai_chat._reads(s, aid, fan, run_cut, turn)
        st, _ = full_ai_chat.build_state(turn, thread_rows, bought, offer,
                                         photos=bool(side[full_ai_photo.KEY]))
        f = await s.get(Fan, (aid, fan))
        names = {k: getattr(f, k) for k in NAME_FIELDS if f is not None and getattr(f, k)}
    return full_ai_turn.TurnFacts(
        account_id=aid, fan_id=fan, mode=MODE, anchor_key=str(anchor.message_id), state=st,
        cut_rows=[*thread_rows, *turn], bought=bought, offer=offer, fan_info=names, asked={},
        config=side, side="checkpoint", config_rev=cfg["rev"])


def _io(account_id: str, fan_id: int, anchor: Message, client) -> full_ai_turn.TurnIO:
    """The live `TurnIO` of one job: the Test chat's hold, a sender that walks the text bubbles
    on OF, a record that INSERTs the row once with its Anchor."""
    aid, fan = str(account_id), int(fan_id)

    async def send(row: dict, parts: list[str], pick=None, *, over=None, desc=None, gif=None) -> None:
        # The row and bubble shapes of the Test chat (Offer columns included); the gif waits for 71.
        full_ai_test.send(row, parts, pick, over=over, desc=desc)
        reply, landed = row["reply_json"], 0
        wpm = await load_typing_wpm(aid)
        for i, part in enumerate(reply["parts"]):
            if set(part) != {"text"}:          # a PPV bubble never goes out as plain text (66 / 90)
                reply["cut"] = {"check": "sender", "reason": "ppv_unbuilt", "index": i}
                break
            await hold_with_typing(aid, fan, typing_delay_seconds(part["text"], wpm))
            await dm_rate.turn(aid, release_budget_s=INLINE_MAX_S)
            try:
                res = await ax.of_write_paced(aid, lambda t=part["text"]: client.send_message(fan, t),
                                              send_purpose=SEND_PURPOSE, tries=1)
            except Exception as e:  # noqa: BLE001 — stop the Turn, never retry a send
                log.warning("full_ai_live send failed account=%s fan=%s", aid, fan, exc_info=True)
                reply["cut"] = {"check": "send_error", "reason": type(e).__name__, "index": i}
                break
            mid = res.get("id") if isinstance(res, dict) else None
            if not mid:
                reply["cut"] = {"check": "send_error", "reason": "no_id", "index": i}
                break
            part["message_id"] = int(mid)
            await write_outbound_attribution(
                account_id=aid, fan_id=fan, message_id=int(mid), sent_by_employee_id=None,
                body=str(res.get("text") or part["text"]), price_cents=0,
                created_at=ax._parse_iso(res.get("createdAt")) or datetime.utcnow(),
                automation_kind=KIND, emit_live=True)
            landed += 1
        row["status"] = "sent" if landed else "failed"

    async def record(row: dict) -> int:
        values = dict(row, anchor_message_id=anchor.message_id, anchor_created_at=anchor.created_at,
                      reply_json=json.dumps(row["reply_json"], ensure_ascii=False),
                      jev_json=json.dumps(row["jev_json"], ensure_ascii=False))
        async with get_session() as s:
            rid = (await s.execute(sqlite_insert(AiDecision).values(**values)
                                   .on_conflict_do_nothing(index_elements=_TURN_KEY)
                                   .returning(AiDecision.id))).scalar_one_or_none()
            if rid is None:
                log.warning("full_ai_live duplicate row account=%s fan=%s key=%s", aid, fan, row["trigger_key"])
                rid = (await s.execute(select(AiDecision.id).where(
                    AiDecision.account_id == aid, AiDecision.fan_id == fan, AiDecision.mode == MODE,
                    AiDecision.trigger_key == row["trigger_key"]))).scalar_one()
        return int(rid)

    return full_ai_turn.TurnIO(TRIGGER_KIND, full_ai_test.hold, send, record)


async def _cooldown(account_id: str, fan_id: int) -> None:
    """`COOLDOWN_S` after a send, unless a longer pause already stands (e.g. a Human yield)."""
    async with get_session() as s:
        until = (await s.execute(select(Fan.automation_paused_until).where(
            Fan.account_id == str(account_id), Fan.fan_id == int(fan_id)))).scalar_one_or_none()
    if until is not None and until >= datetime.utcnow() + timedelta(seconds=COOLDOWN_S):
        return
    await ax.start_fan_cooldown(account_id, fan_id, cooldown_s=COOLDOWN_S)


async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """One Fan's live Turn (`payload["only_fan_ids"]`). Stats: the row, or `skipped` with why."""
    if payload.get("anchor") is None:      # the rule's interval tick: the sweep is ticket 68
        return {"skipped": "unanchored"}
    aid, fan = str(account_id), int(payload["only_fan_ids"][0])
    cfg = (await full_ai_turn.stored_config(aid))["checkpoint"]
    ttl = int(max(900, full_ai_turn.turn_bound_s(cfg) + 600))
    if await ax.fan_on_cooldown(aid, fan) or not await ax.acquire_fan_lease(aid, fan, KIND, ttl_s=ttl):
        return {"skipped": "busy"}         # the +20 s retry is ticket 67
    sent = False
    try:
        client = await asyncio.to_thread(ax._make_client, aid)
        facts = await load(aid, fan, client)
        if facts is None:
            return {"skipped": "no_turn"}
        res = await full_ai_turn.run_turn(facts, _io(aid, fan, facts.cut_rows[-1], client))
        sent = any("message_id" in p for p in res.parts)
        log.info("full_ai_turn account=%s fan=%s mode=live route=%s status=%s", aid, fan,
                 res.decision.route, res.status)
        return {"row_id": res.row_id, "route": res.decision.route, "row_status": res.status,
                "sent": sum("message_id" in p for p in res.parts)}
    except Exception:
        log.warning("full_ai_live_failed account=%s fan=%s", aid, fan, exc_info=True)
        raise
    finally:
        if sent:
            await _cooldown(aid, fan)
        await ax.release_fan_lease(aid, fan, holder=KIND)
