"""Full AI live: the priced bubble (phase 05 › Contracts › `send_priced` / `send_outcome`, ticket 86).

The row is already reserved (Offer columns committed by `full_ai_test.send`, before the Turn's first
OF call); hold, `dm_rate.turn` and last-look ran in the live sender before this is called. One OF
call lands the row in one of three derived states (ADR-0034, no marker columns):
  SENT         `offer_message_id` = OF's id, the outbound `messages` row, one `vault_sends` row per
               locked media (`was_purchased` NULL; the purchase stamp flips them by message id)
  CLEAR        Offer columns NULL; `Sent.dropped` = `media` | `send` (04a's loop writes
               `reply_json.offer_dropped`)
  UNCONFIRMED  row untouched (05's unconfirmed Offer: columns set, id NULL), one log line
The outbound `messages` row is written whenever OF returned an id (a Free item whose media OF
refused still lands its text).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, NamedTuple

from sqlalchemy import select, update

import audience_include
import automation_executor as ax
from attribution import write_outbound_attribution
from automations._send_failure import (
    is_media_rejected_error, is_unreachable_fan_error, send_dropping_bad_media, skip_unreachable_fan,
)
from automations._ppv_readback import sent_ppv
from db.engine import get_session
from db.models import AiDecision, VaultSend

log = logging.getLogger(__name__)

KIND = "full_ai_chat"
SENT, CLEAR, UNCONFIRMED = "SENT", "CLEAR", "UNCONFIRMED"
_OFFER_NULL = dict(offer_price_cents=None, offer_list_cents=None, offer_media_json=None,
                   offer_item_ref=None)


class Sent(NamedTuple):
    outcome: str                # SENT | CLEAR | UNCONFIRMED
    message_id: int | None      # OF's id when it returned one (a CLEAR Free item's text too)
    dropped: str | None         # CLEAR's reason: media | send


def send_outcome(msg_id, exc: BaseException | None, readback_id) -> tuple[str, str | None]:
    """`send_marker_decide.failure_outcome`'s rules, no marker: an id is SENT; a media reject
    (OF created nothing) is CLEAR `media`; an unreachable fan CLEAR `send`; an id-less 200 or any
    other raise is SENT when the read-back found it, else UNCONFIRMED (never retried). Pure."""
    if exc is None and msg_id:
        return SENT, None
    if exc is not None and is_media_rejected_error(exc):
        return CLEAR, "media"
    if exc is not None and is_unreachable_fan_error(exc):
        return CLEAR, "send"
    return (SENT, None) if readback_id else (UNCONFIRMED, None)


async def send_priced(client: Any, *, row_id: int, account_id: str, fan_id: int, text: str,
                      ppv: dict, over_message_id: int | None = None, send_purpose: str) -> Sent:
    """Send `text` as row `row_id`'s Offer (`ppv` = `{ref, price_cents, media, previews}`) and
    land the row (module doc). Price > 0: one `client.send_message` locked at the price, the
    previews free among the media; never a text-only retry. Price 0 (Free item):
    `send_dropping_bad_media`, unlocked. A row that already has `offer_message_id` sends nothing.
    After SENT with `over_message_id` (a haggle): unsend that old PPV, best effort."""
    async with get_session() as s:
        row = (await s.execute(select(AiDecision.offer_message_id, AiDecision.offer_item_ref).where(
            AiDecision.id == int(row_id), AiDecision.account_id == str(account_id),
            AiDecision.fan_id == int(fan_id)))).one_or_none()
    if row is None or row.offer_item_ref is None:
        raise LookupError(f"no reserved Offer on ai_decisions row {row_id}")    # never a PPV with no row
    if row.offer_message_id is not None:
        return Sent(SENT, int(row.offer_message_id), None)
    cents = int(ppv["price_cents"])
    locked = [int(m) for m in ppv.get("media") or []]
    previews = [int(m) for m in ppv.get("previews") or []]
    media = list(dict.fromkeys(locked + previews))      # OF frees `previews` from among `mediaFiles`
    audience_include.audit_send_purpose(send_purpose, where="full_ai_ppv")
    result, exc, landed = None, None, True
    since = datetime.utcnow()
    try:
        if cents > 0:
            result = await asyncio.to_thread(client.send_message, fan_id, text, price=cents / 100,
                                             media_files=media, previews=previews)
        else:
            result, landed = await send_dropping_bad_media(
                client, fan_id, text, media, log=log, send_purpose=send_purpose, price_cents=0)
    except Exception as e:      # noqa: BLE001 — every raise is classified below
        exc = e
    msg_id = result.get("id") if isinstance(result, dict) else None
    outcome, dropped = send_outcome(msg_id, exc, None)
    if outcome == UNCONFIRMED and cents > 0:   # price 0 would match any free message of ours
        found = await sent_ppv(client, fan_id, since, cents)
        outcome, dropped = send_outcome(msg_id, exc, found.get("id"))
        if found:
            result, msg_id = found, found["id"]
    if outcome == SENT and not landed:      # a Free item's text went alone
        outcome, dropped = CLEAR, "media"

    if outcome == UNCONFIRMED:
        log.warning("full_ai_ppv_unconfirmed account=%s fan=%s row=%s (%s)", account_id, fan_id,
                    row_id, f"{type(exc).__name__}: {exc}"[:160] if exc else "no id")
        return Sent(UNCONFIRMED, None, None)
    async with get_session() as s:
        if outcome == SENT:
            res = await s.execute(update(AiDecision).where(
                AiDecision.id == int(row_id), AiDecision.offer_message_id.is_(None)).values(
                offer_message_id=int(msg_id)))
            if res.rowcount != 1:       # settle_pull linked it meanwhile: its id stands
                log.warning("full_ai_ppv_already_linked account=%s fan=%s row=%s msg=%s", account_id,
                            fan_id, row_id, msg_id)
            else:
                s.add_all(VaultSend(account_id=str(account_id), fan_id=int(fan_id), media_id=m,
                                    message_id=int(msg_id), price_cents=cents, was_purchased=None)
                          for m in locked)
        else:
            await s.execute(update(AiDecision).where(
                AiDecision.id == int(row_id), AiDecision.offer_message_id.is_(None)).values(**_OFFER_NULL))
        await s.commit()
    if msg_id:
        await write_outbound_attribution(
            account_id=str(account_id), fan_id=int(fan_id), message_id=int(msg_id),
            sent_by_employee_id=None, automation_kind=KIND, body=str(result.get("text") or text),
            price_cents=cents, created_at=ax._parse_iso(result.get("createdAt")) or datetime.utcnow(),
            emit_live=True)
    if outcome == CLEAR:
        log.info("full_ai_ppv_cleared account=%s fan=%s row=%s dropped=%s", account_id, fan_id,
                 row_id, dropped)
        if dropped == "send":
            await skip_unreachable_fan(account_id, fan_id, exc, log=log)
        return Sent(CLEAR, int(msg_id) if msg_id else None, dropped)
    if over_message_id is not None:
        try:
            await asyncio.to_thread(client.unsend_message, int(over_message_id), int(fan_id))
            log.info("full_ai_ppv_unsent_over account=%s fan=%s old=%s new=%s", account_id, fan_id,
                     over_message_id, msg_id)
        except Exception:       # noqa: BLE001 — best effort: the new PPV stands
            log.warning("full_ai_ppv_unsend_failed account=%s fan=%s old=%s", account_id, fan_id,
                        over_message_id, exc_info=True)
    return Sent(SENT, int(msg_id), None)
