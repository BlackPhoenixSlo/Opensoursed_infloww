from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from automations import send_marker_decide
from db.engine import get_session
from db.models import AiDecision, Message, PurchaseNotice, VaultSend
from of_shapes import queue_id

log = logging.getLogger("of-relay.full_ai_settle")

# OF stamps the PPV within seconds of the attempt; a later same-price PPV (e.g. a mass copy) is another send.
LINK_MAX_S = send_marker_decide.IN_FLIGHT_MAX_S
OUTCOME = "bought"


class Settle(NamedTuple):
    row_id: int
    message_id: int
    outcome_at: datetime | None
    join_src: str | None


def _ours(m) -> bool:
    kind = getattr(m, "automation_kind", None)
    return kind in (None, "full_ai_chat") and getattr(m, "sent_by_employee_id", None) is None


def _open(r) -> bool:
    return r.outcome is None and (r.offer_price_cents or 0) > 0


def _ids(raw, *keys: str) -> set[int]:
    try:
        v = json.loads(raw or "null")
    except (TypeError, ValueError):
        return set()
    if isinstance(v, dict):
        v = [x for k in keys for x in v.get(k) or []]
    out = set()
    for x in v if isinstance(v, list) else []:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out


def attempted(r) -> bool:
    return getattr(r, "offer_attempt_at", None) is not None or getattr(r, "status", None) == "unconfirmed"


def link_window(r) -> tuple[datetime, datetime]:
    at = getattr(r, "offer_attempt_at", None) or r.created_at
    return at.replace(microsecond=0), at + timedelta(seconds=LINK_MAX_S)


def _mass(m) -> bool:
    if getattr(m, "mass_run_id", None) is not None:
        return True
    try:
        raw = json.loads(getattr(m, "raw_json", None) or "{}")
    except (TypeError, ValueError):
        return False
    return isinstance(raw, dict) and queue_id(raw) is not None


def settle_plan(rows, msgs, notices: dict[int, datetime], claimed: set[int]) -> list[Settle]:
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
        media = _ids(r.offer_media_json, "locked", "previews")
        if not attempted(r) or not media:
            continue
        floor, ceil = link_window(r)
        cands[r.id] = (r, [m for m in msgs if m.price_cents == r.offer_price_cents
                           and floor <= m.created_at <= ceil and _ours(m) and not _mass(m)
                           and _ids(m.media_ids) == media and m.message_id not in taken])
    sole = [c[0].message_id for _, c in cands.values() if len(c) == 1]
    for r, c in cands.values():
        if len(c) != 1 or sole.count(c[0].message_id) > 1:
            continue
        m = c[0]
        out.append(bought(r, m, True) if m.is_paid else Settle(r.id, m.message_id, None, None))
    return out


_OR_TERMS = 200  # SQLite caps an OR chain's depth (1000)


async def _load(account_id: str, fan_id: int | None):
    acc = str(account_id)
    async with get_session() as s:
        q = select(AiDecision).where(
            AiDecision.account_id == acc, AiDecision.outcome.is_(None), AiDecision.offer_price_cents > 0,
            or_(AiDecision.offer_message_id.is_not(None), AiDecision.offer_attempt_at.is_not(None),
                AiDecision.status == "unconfirmed"))
        if fan_id is not None:
            q = q.where(AiDecision.fan_id == int(fan_id))
        rows = list((await s.execute(q.order_by(AiDecision.id))).scalars().all())
        if not rows:
            return [], [], {}, set()
        fans = {r.fan_id for r in rows}
        linked = [r.offer_message_id for r in rows if r.offer_message_id is not None]
        terms = [Message.message_id.in_(linked)] if linked else []
        terms += [and_(Message.fan_id == r.fan_id, Message.created_at.between(*link_window(r)))
                  for r in rows if r.offer_message_id is None]
        got: dict[tuple, Message] = {}
        for i in range(0, len(terms), _OR_TERMS):
            for m in (await s.execute(select(Message).where(
                    Message.account_id == acc, Message.fan_id.in_(fans), Message.direction == "out",
                    Message.price_cents > 0, or_(*terms[i:i + _OR_TERMS])))).scalars():
                got[(m.fan_id, m.message_id)] = m
        msgs = list(got.values())
        paid = [m.message_id for m in msgs if m.is_paid]
        notices = dict((await s.execute(select(PurchaseNotice.message_id, PurchaseNotice.notified_at).where(
            PurchaseNotice.account_id == acc, PurchaseNotice.message_id.in_(paid)))).all()) if paid else {}
        claimed = set((await s.execute(select(AiDecision.offer_message_id).where(
            AiDecision.account_id == acc, AiDecision.fan_id.in_(fans),
            AiDecision.offer_message_id.is_not(None)))).scalars().all())
    return rows, msgs, notices, claimed


async def record_vault_sends(s, account_id: str, fan_id: int, message_id: int, row, *, bought: bool = False) -> None:
    locked = sorted(_ids(row.offer_media_json, "locked"))
    if not locked:
        return
    mine = (VaultSend.account_id == str(account_id), VaultSend.fan_id == int(fan_id),
            VaultSend.message_id == int(message_id))
    have = set((await s.execute(select(VaultSend.media_id).where(*mine))).scalars())
    if bought and have:
        await s.execute(update(VaultSend).where(*mine, VaultSend.was_purchased.is_not(True)).values(was_purchased=True))
    s.add_all(VaultSend(account_id=str(account_id), fan_id=int(fan_id), media_id=m, message_id=int(message_id),
                        price_cents=int(row.offer_price_cents or 0), was_purchased=True if bought else None)
              for m in locked if m not in have)


async def settle_pull(account_id: str, fan_id: int | None = None) -> int:
    rows, msgs, notices, claimed = await _load(account_id, fan_id)
    plan: list[Settle] = []
    for fan in sorted({r.fan_id for r in rows}):
        plan += settle_plan([r for r in rows if r.fan_id == fan], [m for m in msgs if m.fan_id == fan],
                            notices, claimed)
    by_row = {r.id: r for r in rows}
    n = 0
    for p in plan:
        # Same guard as the fake Buy: a rerun or concurrent call changes nothing twice.
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
                if res.rowcount:
                    r = by_row[p.row_id]
                    await record_vault_sends(s, r.account_id, r.fan_id, p.message_id, r, bought=p.join_src is not None)
                await s.commit()
            except IntegrityError:  # another row took the message meanwhile
                await s.rollback()
                continue
        if res.rowcount:
            n += res.rowcount
            log.info("full_ai_settle account=%s row=%s msg=%s src=%s", account_id, p.row_id,
                     p.message_id, p.join_src or "link")
    return n
