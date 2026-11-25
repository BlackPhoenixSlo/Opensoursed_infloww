from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, NamedTuple

from sqlalchemy import select, update

import automation_executor as ax
from attribution import write_outbound_attribution
from automations._send_failure import (
    is_media_rejected_error, is_unreachable_fan_error, schedule_recheck_rejected_media,
    send_dropping_bad_media, skip_unreachable_fan,
)
from automations._ppv_readback import sent_ppv
from automations.full_ai_settle import record_vault_sends
from db.engine import get_session
from db.models import AiDecision

log = logging.getLogger(__name__)

KIND = "full_ai_chat"
SENT, CLEAR, UNCONFIRMED = "SENT", "CLEAR", "UNCONFIRMED"
OFFER_COLS = ("offer_price_cents", "offer_list_cents", "offer_media_json", "offer_item_ref")
OFFER_NULL = dict.fromkeys(OFFER_COLS)


class MaybeSent(Exception):

    def __init__(self, message_id: int | None, cause: BaseException):
        super().__init__(f"PPV may be on OF (id {message_id}): {type(cause).__name__}: {cause}"[:200])
        self.message_id = message_id


class _Claimed(Exception):
    pass


class Sent(NamedTuple):
    outcome: str                # SENT | CLEAR | UNCONFIRMED
    message_id: int | None      # OF's id when it returned one (a CLEAR Free item's text too)
    dropped: str | None         # CLEAR's reason: media | send


def send_outcome(msg_id, exc: BaseException | None, readback_id) -> tuple[str, str | None]:
    if exc is None and msg_id:
        return SENT, None
    if exc is not None and is_media_rejected_error(exc):
        return CLEAR, "media"
    if exc is not None and is_unreachable_fan_error(exc):
        return CLEAR, "send"
    return (SENT, None) if readback_id else (UNCONFIRMED, None)


async def send_priced(client: Any, *, row_id: int, account_id: str, fan_id: int, text: str,
                      ppv: dict, over_message_id: int | None = None, send_purpose: str,
                      min_gap_s: float, before_write=None) -> Sent:
    """Send `text` as row `row_id`'s Offer (`ppv` = `{ref, price_cents, media, previews}`) and
    land the row (module doc). Price > 0: one `client.send_message` locked at the price, the
    previews free among the media; never a text-only retry. Price 0 (Free item):
    `send_dropping_bad_media`, unlocked. A row that already has `offer_message_id` sends nothing; one
    already attempted sends nothing either (UNCONFIRMED). `before_write` (awaited after the write
    gate's grant, before the claim) may raise to stop: nothing sent, its raise propagates.
    `min_gap_s`: the write gate's gap (`full_ai_live.WRITE_GAP_S`); `send_purpose` is audited by the
    write seam before any OF call. After SENT on OF's own
    returned id with `over_message_id` (a haggle): unsend that old PPV, best effort (never on a
    read-back match)."""
    async with get_session() as s:
        row = (await s.execute(select(AiDecision.offer_message_id, AiDecision.offer_item_ref,
                                      AiDecision.offer_attempt_at).where(
            AiDecision.id == int(row_id), AiDecision.account_id == str(account_id),
            AiDecision.fan_id == int(fan_id)))).one_or_none()
    if row is None or row.offer_item_ref is None:
        raise LookupError(f"no reserved Offer on ai_decisions row {row_id}")
    if row.offer_message_id is not None:
        return Sent(SENT, int(row.offer_message_id), None)
    if row.offer_attempt_at is not None:
        log.warning("full_ai_ppv_already_attempted account=%s fan=%s row=%s", account_id, fan_id, row_id)
        return Sent(UNCONFIRMED, None, None)
    cents = int(ppv["price_cents"])
    locked = [int(m) for m in ppv.get("media") or []]
    previews = [int(m) for m in ppv.get("previews") or []]
    media = list(dict.fromkeys(locked + previews))
    result, exc, landed, attempted = None, None, True, False
    since = datetime.utcnow()

    async def claim():
        nonlocal attempted, since
        if before_write is not None:
            await before_write()
        since = datetime.utcnow()
        async with get_session() as s:
            res = await s.execute(update(AiDecision).where(
                AiDecision.id == int(row_id), AiDecision.offer_message_id.is_(None),
                AiDecision.offer_attempt_at.is_(None)).values(offer_attempt_at=since))
        if res.rowcount != 1:  # conditional UPDATE: a row already attempted sends nothing
            raise _Claimed
        attempted = True

    if cents > 0:
        def post():
            return client.send_message(fan_id, text, price=cents / 100, media_files=media,
                                       previews=previews), True
    else:
        async def post():
            return tuple(await send_dropping_bad_media(
                client, fan_id, text, media, log=log, send_purpose=send_purpose, price_cents=0))

    try:
        result, landed = await ax.of_write_paced(account_id, post, send_purpose=send_purpose, tries=1,
                                                 dm=True, min_gap_s=min_gap_s, before_write=claim)
    except _Claimed:
        log.warning("full_ai_ppv_already_attempted account=%s fan=%s row=%s", account_id, fan_id, row_id)
        return Sent(UNCONFIRMED, None, None)
    except Exception as e:      # noqa: BLE001 — every raise after the claim is classified below
        if not attempted:
            raise
        exc = e
    msg_id = result.get("id") if isinstance(result, dict) else None
    try:
        return await _land(client, row_id=row_id, account_id=account_id, fan_id=fan_id, text=text,
                           cents=cents, media=media, since=since, result=result, msg_id=msg_id, exc=exc,
                           landed=landed, over_message_id=over_message_id)
    except asyncio.CancelledError:
        raise
    except Exception as e:      # noqa: BLE001 — bookkeeping after the POST: it may be on OF
        raise MaybeSent(int(msg_id) if msg_id else None, e) from e


async def _land(client, *, row_id, account_id, fan_id, text, cents, media, since, result, msg_id, exc,
                landed, over_message_id) -> Sent:
    direct = bool(msg_id) and exc is None
    outcome, dropped = send_outcome(msg_id, exc, None)
    if outcome == UNCONFIRMED and exc is not None and not ax._may_have_sent(exc):
        outcome, dropped = CLEAR, "send"
    if outcome == UNCONFIRMED and cents > 0:   # price 0 would match any free message of ours
        found = await sent_ppv(client, fan_id, since, cents, media=media)
        outcome, dropped = send_outcome(msg_id, exc, found.get("id"))
        if found:
            result, msg_id = found, found["id"]
    if outcome == SENT and not landed:
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
            if res.rowcount != 1:
                log.warning("full_ai_ppv_already_linked account=%s fan=%s row=%s msg=%s", account_id,
                            fan_id, row_id, msg_id)
            row = (await s.execute(select(AiDecision).where(AiDecision.id == int(row_id)))).scalar_one()
            if row.offer_message_id is not None:
                await record_vault_sends(s, account_id, fan_id, int(row.offer_message_id), row)
        else:
            await s.execute(update(AiDecision).where(
                AiDecision.id == int(row_id), AiDecision.offer_message_id.is_(None)).values(
                **OFFER_NULL, offer_attempt_at=None))
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
        elif dropped == "media" and exc is not None:
            schedule_recheck_rejected_media(account_id, client, media, log=log)
        return Sent(CLEAR, int(msg_id) if msg_id else None, dropped)
    if over_message_id is not None and direct:
        try:
            await asyncio.to_thread(client.unsend_message, int(over_message_id), int(fan_id))
            log.info("full_ai_ppv_unsent_over account=%s fan=%s old=%s new=%s", account_id, fan_id,
                     over_message_id, msg_id)
        except Exception:       # noqa: BLE001 — best effort: the new PPV stands
            log.warning("full_ai_ppv_unsend_failed account=%s fan=%s old=%s", account_id, fan_id,
                        over_message_id, exc_info=True)
    return Sent(SENT, int(msg_id), None)
