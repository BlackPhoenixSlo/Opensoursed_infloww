from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import NamedTuple

from sqlalchemy import select

import ownership
from automations import send_marker_decide
from automations.full_ai_settle import attempted
from automations.full_ai_test import _media, _offers, open_offer_of, owned_of, sent_media_of
from db.engine import get_session
from db.models import Message, Transaction, VaultSend

OFFER_OPEN_S = 86400
UNCONFIRMED_S = send_marker_decide.IN_FLIGHT_MAX_S
TX_KINDS = ("tip", "ppv_post")
TX_STATUSES = ("cleared", "pending")


class Sold(NamedTuple):
    cross: set[int]
    vault_media: set[int]
    paid_msgs: list
    txs: list


def owned_live(rows, cross: set[int]) -> set[int]:
    return owned_of([r for r in rows if r.offer_price_cents != 0 or r.offer_message_id is not None]) | set(cross)


def reserved_of(rows) -> set[int]:
    return {x for r in _offers(rows) if r.offer_price_cents > 0 and r.offer_message_id is None
            and r.outcome is None and attempted(r) for x in _media(r, "locked", "previews")}


def sent_live(rows, vault_media: set[int]) -> set[int]:
    return sent_media_of(rows) | set(vault_media)


# Ledger `ppv_message` rows are skipped (TX_KINDS): the paid message already counts it and is fresher by seconds.
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
    ids = {int(x) for x in (ppv.get("media") or [])} | {int(x) for x in (ppv.get("previews") or [])}
    if ids & set(owned_now):
        return "owned"
    if ids & reserved_of([r for r in rows_now if r.id != row_id]):
        return "unconfirmed"
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
