"""Full AI live: the priced bubble (phase 05 › Contracts › `send_priced` / `send_outcome`, ticket 86).

The row is already reserved (Offer columns committed by `full_ai_test.send`, before the Turn's first
OF call); hold and `dm_rate.turn` ran in the live sender before this is called. The POST goes through
the account's write gate (`ax.of_write_paced`, `dm=True`, one try); once the turn is granted the
caller's `before_write` (the live last look) runs, then the carrier attempt is claimed on the row
(`offer_attempt_at`, a conditional UPDATE: a row already attempted sends nothing), then the POST. One
OF call lands the row in one of three derived states (ADR-0034, no marker columns):
  SENT         `offer_message_id` = OF's id, the outbound `messages` row, one `vault_sends` row per
               locked media (`was_purchased` NULL; the purchase stamp flips them by message id)
  CLEAR        Offer columns and `offer_attempt_at` NULL; `Sent.dropped` = `media` | `send` (04a's
               loop writes `reply_json.offer_dropped`); `send` also for a raise OF surely did not take
               (`ax._may_have_sent` False: a refusal, a 4xx), with no read-back (an older card of the
               same Offer must not be taken for it)
  UNCONFIRMED  row kept attempted (05's unconfirmed Offer: columns set, id NULL), one log line; the
               read-back took no message (none, or not exactly this one: its media, no mass copy,
               created after the attempt)
The outbound `messages` row is written whenever OF returned an id (a Free item whose media OF
refused still lands its text). A raise after the attempt is `MaybeSent` (never "nothing sent").
"""
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
OFFER_NULL = dict.fromkeys(OFFER_COLS)      # no Offer stands (every writer of the columns clears with this)


class MaybeSent(Exception):
    """`send_priced` raised after its carrier POST was attempted: the PPV may be on OF (never resent).
    `message_id`: OF's id when it returned one before the raise."""

    def __init__(self, message_id: int | None, cause: BaseException):
        super().__init__(f"PPV may be on OF (id {message_id}): {type(cause).__name__}: {cause}"[:200])
        self.message_id = message_id


class _Claimed(Exception):
    """The carrier attempt was already claimed (another run): nothing sent."""


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
        raise LookupError(f"no reserved Offer on ai_decisions row {row_id}")    # never a PPV with no row
    if row.offer_message_id is not None:
        return Sent(SENT, int(row.offer_message_id), None)
    if row.offer_attempt_at is not None:
        log.warning("full_ai_ppv_already_attempted account=%s fan=%s row=%s", account_id, fan_id, row_id)
        return Sent(UNCONFIRMED, None, None)
    cents = int(ppv["price_cents"])
    locked = [int(m) for m in ppv.get("media") or []]
    previews = [int(m) for m in ppv.get("previews") or []]
    media = list(dict.fromkeys(locked + previews))      # OF frees `previews` from among `mediaFiles`
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
        if res.rowcount != 1:
            raise _Claimed
        attempted = True

    if cents > 0:
        def post():             # a plain callable: the seam runs it off-thread
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
            raise               # before the POST: nothing sent
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
    """`send_priced` after its attempted POST: classify, read back, write the row (module doc)."""
    direct = bool(msg_id) and exc is None
    outcome, dropped = send_outcome(msg_id, exc, None)
    if outcome == UNCONFIRMED and exc is not None and not ax._may_have_sent(exc):
        outcome, dropped = CLEAR, "send"    # OF surely took nothing (of_write's rule): no read-back
    if outcome == UNCONFIRMED and cents > 0:   # price 0 would match any free message of ours
        found = await sent_ppv(client, fan_id, since, cents, media=media)
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
            row = (await s.execute(select(AiDecision).where(AiDecision.id == int(row_id)))).scalar_one()
            if row.offer_message_id is not None:    # the linked id's media, once (idempotent)
                await record_vault_sends(s, account_id, fan_id, int(row.offer_message_id), row)
        else:
            await s.execute(update(AiDecision).where(
                AiDecision.id == int(row_id), AiDecision.offer_message_id.is_(None)).values(
                **OFFER_NULL, offer_attempt_at=None))       # nothing of it on OF: its media is free again
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
        elif dropped == "media" and exc is not None:   # a priced media reject (Free: send_dropping_bad_media)
            schedule_recheck_rejected_media(account_id, client, media, log=log)
        return Sent(CLEAR, int(msg_id) if msg_id else None, dropped)
    if over_message_id is not None and direct:     # a read-back match never unsends the old Offer
        try:
            await asyncio.to_thread(client.unsend_message, int(over_message_id), int(fan_id))
            log.info("full_ai_ppv_unsent_over account=%s fan=%s old=%s new=%s", account_id, fan_id,
                     over_message_id, msg_id)
        except Exception:       # noqa: BLE001 — best effort: the new PPV stands
            log.warning("full_ai_ppv_unsend_failed account=%s fan=%s old=%s", account_id, fan_id,
                        over_message_id, exc_info=True)
    return Sent(SENT, int(msg_id), None)
