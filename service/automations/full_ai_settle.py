"""automations/full_ai_settle.py — a real purchase settles the live Offer row (phase 05, ticket 85).

Settle = pull: the same row state the Test chat's fake Buy leaves (`full_ai_test._settle`), from
`messages.is_paid` (flipped by `purchase_notifications.poll_purchases` or any other writer).

  settle_plan(rows, msgs, notices, claimed) -> list[Settle]   pure, one Fan:
      1. row with `offer_message_id`, that message `is_paid` -> bought; `outcome_at` = the notice's
         `notified_at`, else `purchased_at`, else now; `join_src` = notice | is_paid
      2. row without id: candidates = messages at its price, created no earlier than
         `LOOKUP_SLACK_S` before the row and no later than `LINK_MAX_S` after it, not another
         lane's (`automation_kind` set to another kind, or a chatter's), id not claimed (nor sole
         candidate of another such row).
         Exactly one -> link it (`join_src` heuristic when paid; link only, `join_src` None, when
         unpaid). Zero or several -> nothing.
  settle_pull(account_id, fan_id=None) -> int   rows changed; each Settle is one UPDATE under the
      fake Buy's guard (`outcome IS NULL AND offer_price_cents > 0`), so a rerun or a concurrent
      call changes nothing twice.

No Mode filter (only live rows hold an `offer_message_id`; a test row's Fan id is negative, so it
has no messages), no `already_owned` refusal (he paid), no Turn triggered, no OF call.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from automations import send_marker_decide
from db.engine import get_session
from db.models import AiDecision, Message, PurchaseNotice

log = logging.getLogger("of-relay.full_ai_settle")

LOOKUP_SLACK_S = 60
# OF stamps the PPV within seconds of the reserve; a same-price PPV sent later is another send
# (a mass copy days on must not become Full AI's sale). = 05's UNCONFIRMED_S.
LINK_MAX_S = send_marker_decide.IN_FLIGHT_MAX_S
# An unlinked row older than this is no longer looked at (its message row would have landed).
LINK_LOAD_S = 7 * 86400
OUTCOME = "bought"


class Settle(NamedTuple):
    row_id: int
    message_id: int
    outcome_at: datetime | None     # None: link only (rule 2, message not paid yet)
    join_src: str | None            # notice | is_paid | heuristic; None on a link only


def _ours(m) -> bool:
    """Not another lane's: unattributed (a scrape of our own send) or Full AI's."""
    kind = getattr(m, "automation_kind", None)
    return kind in (None, "full_ai_chat") and getattr(m, "sent_by_employee_id", None) is None


def _open(r) -> bool:
    return r.outcome is None and (r.offer_price_cents or 0) > 0


def settle_plan(rows, msgs, notices: dict[int, datetime], claimed: set[int]) -> list[Settle]:
    """One Fan's plan: `rows` his `ai_decisions` rows, `msgs` his outbound priced messages,
    `notices` purchase notice time by message id, `claimed` message ids already on a row. Pure
    but for "now" when a paid message has neither a notice nor `purchased_at`."""
    by_id = {m.message_id: m for m in msgs}
    taken = set(claimed) | {r.offer_message_id for r in rows if r.offer_message_id is not None}
    out: list[Settle] = []

    def bought(r, m, heuristic: bool) -> Settle:
        at = notices.get(m.message_id)
        src = "heuristic" if heuristic else "notice" if at is not None else "is_paid"
        return Settle(r.id, m.message_id, at or m.purchased_at or datetime.utcnow(), src)

    cands = {}
    for r in rows:
        if not _open(r):
            continue
        if r.offer_message_id is not None:
            m = by_id.get(r.offer_message_id)
            if m is not None and m.is_paid:
                out.append(bought(r, m, False))
            continue
        floor = r.created_at - timedelta(seconds=LOOKUP_SLACK_S)
        ceil = r.created_at + timedelta(seconds=LINK_MAX_S)
        cands[r.id] = (r, [m for m in msgs if m.price_cents == r.offer_price_cents
                           and floor <= m.created_at <= ceil and _ours(m)
                           and m.message_id not in taken])
    sole = [c[0].message_id for _, c in cands.values() if len(c) == 1]
    for r, c in cands.values():
        if len(c) != 1 or sole.count(c[0].message_id) > 1:
            continue
        m = c[0]
        out.append(bought(r, m, True) if m.is_paid else Settle(r.id, m.message_id, None, None))
    return out


async def _load(account_id: str, fan_id: int | None):
    """The account's (or one Fan's) unsettled priced rows (unlinked ones only for `LINK_LOAD_S`),
    their Fans' outbound priced messages in the unlinked rows' link windows plus the linked ids,
    notices of those messages, claimed ids."""
    acc = str(account_id)
    async with get_session() as s:
        q = select(AiDecision).where(
            AiDecision.account_id == acc, AiDecision.outcome.is_(None), AiDecision.offer_price_cents > 0,
            or_(AiDecision.offer_message_id.is_not(None),
                AiDecision.created_at >= datetime.utcnow() - timedelta(seconds=LINK_LOAD_S)))
        if fan_id is not None:
            q = q.where(AiDecision.fan_id == int(fan_id))
        rows = list((await s.execute(q.order_by(AiDecision.id))).scalars().all())
        if not rows:
            return [], [], {}, set()
        fans = {r.fan_id for r in rows}
        linked = [r.offer_message_id for r in rows if r.offer_message_id is not None]
        unlinked = [r for r in rows if r.offer_message_id is None]
        window = Message.message_id.in_(linked)
        if unlinked:
            window = or_(window, Message.created_at.between(
                min(r.created_at for r in unlinked) - timedelta(seconds=LOOKUP_SLACK_S),
                max(r.created_at for r in unlinked) + timedelta(seconds=LINK_MAX_S)))
        msgs = list((await s.execute(select(Message).where(
            Message.account_id == acc, Message.fan_id.in_(fans), Message.direction == "out",
            Message.price_cents > 0, window))).scalars().all())
        paid = [m.message_id for m in msgs if m.is_paid]
        notices = dict((await s.execute(select(PurchaseNotice.message_id, PurchaseNotice.notified_at).where(
            PurchaseNotice.account_id == acc, PurchaseNotice.message_id.in_(paid)))).all()) if paid else {}
        claimed = set((await s.execute(select(AiDecision.offer_message_id).where(
            AiDecision.account_id == acc, AiDecision.fan_id.in_(fans),
            AiDecision.offer_message_id.is_not(None)))).scalars().all())
    return rows, msgs, notices, claimed


async def settle_pull(account_id: str, fan_id: int | None = None) -> int:
    """Settle every planned row of the account (or one Fan); returns rows changed."""
    rows, msgs, notices, claimed = await _load(account_id, fan_id)
    plan: list[Settle] = []
    for fan in sorted({r.fan_id for r in rows}):
        plan += settle_plan([r for r in rows if r.fan_id == fan], [m for m in msgs if m.fan_id == fan],
                            notices, claimed)
    n = 0
    for p in plan:
        # The fake Buy's guard; a link only also needs the row still unlinked.
        guard = [AiDecision.id == p.row_id, AiDecision.outcome.is_(None), AiDecision.offer_price_cents > 0]
        if p.join_src is None:
            guard.append(AiDecision.offer_message_id.is_(None))
            values = {"offer_message_id": p.message_id}
        else:
            guard.append(or_(AiDecision.offer_message_id.is_(None), AiDecision.offer_message_id == p.message_id))
            values = {"offer_message_id": p.message_id, "outcome": OUTCOME,
                      "outcome_at": p.outcome_at, "join_src": p.join_src}
        async with get_session() as s:
            try:
                res = await s.execute(update(AiDecision).where(*guard).values(**values))
                await s.commit()
            except IntegrityError:          # another row took the message meanwhile
                await s.rollback()
                continue
        if res.rowcount:
            n += res.rowcount
            log.info("full_ai_settle account=%s row=%s msg=%s src=%s", account_id, p.row_id,
                     p.message_id, p.join_src or "link")
    return n
