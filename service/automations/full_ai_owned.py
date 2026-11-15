"""automations/full_ai_owned.py — what a live Fan owns, was sent and spent, across every lane
(phase 05, ticket 87).

Pure over `rows` (the Fan's `ai_decisions` rows of the Turn's Mode, oldest first); the folds are
`full_ai_test`'s, unchanged. One loader, `load_sold`, reads the other lanes.

  owned_live(rows, cross)          owned_of(rows) | cross (`ownership.owned_or_seen_media`)
  sent_live(rows, vault_media)     sent_media_of(rows) | every `vault_sends.media_id` of the Fan
  purchases_live(paid_msgs, txs)   ns(kind, amount_cents, occurred_at), oldest first: paid outbound
                                   priced messages (`ppv_message`, any lane) + `tip` / `ppv_post`
                                   transactions cleared or pending (the ledger's `ppv_message` rows
                                   are skipped: the paid message already counts it, seconds fresh)
  open_offer_live(rows, now)       open_offer_of(rows) unless older than OFFER_OPEN_S, or priced
                                   with no `offer_message_id` (never confirmed on OF)
  unconfirmed_of(rows, now, but)   newest priced row, id NULL, outcome NULL, <= UNCONFIRMED_S old,
                                   not row `but`
  offer_still_valid(...)           the last look: None | "owned" | "unconfirmed"
  load_sold(account, fan) -> Sold  the one loader

A Free item is Owned for Full AI only (`owned_of`, price 0); nothing here stamps `vault_sends`
(spec ASSUMPTION: Free item Owned is lane-local).
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import NamedTuple

from sqlalchemy import select

import ownership
from automations import send_marker_decide
from automations.full_ai_test import _offers, open_offer_of, owned_of, sent_media_of
from db.engine import get_session
from db.models import Message, Transaction, VaultSend

OFFER_OPEN_S = 86400                                   # the probe's Pending-offer bound (ticket 07:86)
UNCONFIRMED_S = send_marker_decide.IN_FLIGHT_MAX_S     # 900
TX_KINDS = ("tip", "ppv_post")
TX_STATUSES = ("cleared", "pending")


class Sold(NamedTuple):
    cross: set[int]          # ownership.owned_or_seen_media: bought in any lane
    vault_media: set[int]    # every vault_sends.media_id of the Fan, bought or not
    paid_msgs: list          # paid outbound priced messages (message_id, price_cents, purchased_at, created_at)
    txs: list                # tip / ppv_post transactions cleared or pending (kind, amount_cents, occurred_at, status)


def owned_live(rows, cross: set[int]) -> set[int]:
    return owned_of(rows) | set(cross)


def sent_live(rows, vault_media: set[int]) -> set[int]:
    return sent_media_of(rows) | set(vault_media)


def purchases_live(paid_msgs, txs) -> list[SimpleNamespace]:
    out = [SimpleNamespace(kind="ppv_message", amount_cents=int(m.price_cents),
                           occurred_at=m.purchased_at or m.created_at)
           for m in paid_msgs if m.is_paid and (m.price_cents or 0) > 0]
    out += [SimpleNamespace(kind=t.kind, amount_cents=int(t.amount_cents), occurred_at=t.occurred_at)
            for t in txs if t.kind in TX_KINDS and t.status in TX_STATUSES]
    return sorted(out, key=lambda p: p.occurred_at)


def _age_s(r, now: datetime) -> float:
    return (now - r.created_at).total_seconds()


def open_offer_live(rows, now: datetime):
    r = open_offer_of(rows)
    if r is None or _age_s(r, now) > OFFER_OPEN_S:
        return None
    if r.offer_price_cents and r.offer_message_id is None:
        return None
    return r


def unconfirmed_of(rows, now: datetime, but: int | None):
    return next((r for r in reversed(_offers(rows))
                 if r.offer_price_cents > 0 and r.offer_message_id is None and r.outcome is None
                 and r.id != but and _age_s(r, now) <= UNCONFIRMED_S), None)


def offer_still_valid(ppv: dict, owned_now: set[int], rows_now, now: datetime, row_id) -> str | None:
    """`ppv` = the bubble's `{ref, price_cents, media, previews}`. Zero-owned: any locked or
    preview id in `owned_now` drops it (raw ids). The unconfirmed rule binds priced bubbles only."""
    ids = {int(x) for x in (ppv.get("media") or [])} | {int(x) for x in (ppv.get("previews") or [])}
    if ids & set(owned_now):
        return "owned"
    if (ppv.get("price_cents") or 0) > 0 and unconfirmed_of(rows_now, now, row_id) is not None:
        return "unconfirmed"
    return None


async def load_sold(account_id: str, fan_id: int) -> Sold:
    cross = await ownership.owned_or_seen_media(account_id, fan_id)
    a, f = str(account_id), int(fan_id)
    async with get_session() as s:
        vault = (await s.execute(select(VaultSend.media_id).where(
            VaultSend.account_id == a, VaultSend.fan_id == f))).scalars().all()
        paid = (await s.execute(select(
            Message.message_id, Message.price_cents, Message.is_paid, Message.purchased_at,
            Message.created_at).where(
            Message.account_id == a, Message.fan_id == f, Message.direction == "out",
            Message.is_paid.is_(True), Message.price_cents > 0))).all()
        txs = (await s.execute(select(
            Transaction.kind, Transaction.amount_cents, Transaction.occurred_at,
            Transaction.status).where(
            Transaction.account_id == a, Transaction.fan_id == f,
            Transaction.kind.in_(TX_KINDS), Transaction.status.in_(TX_STATUSES)))).all()
    return Sold(set(cross), {int(x) for x in vault}, list(paid), list(txs))
