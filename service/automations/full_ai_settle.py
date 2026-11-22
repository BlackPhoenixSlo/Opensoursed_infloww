"""automations/full_ai_settle.py — a real purchase settles the live Offer row (phase 05, ticket 85).

Settle = pull: the same row state the Test chat's fake Buy leaves (`full_ai_test._settle`), from
`messages.is_paid` (flipped by `purchase_notifications.poll_purchases` or any other writer).

  settle_plan(rows, msgs, notices, claimed) -> list[Settle]   pure, one Fan:
      1. row with `offer_message_id`, that message `is_paid` -> bought; `outcome_at` = the notice's
         `notified_at`, else `purchased_at`, else now; `join_src` = notice | is_paid
      2. row without id whose carrier POST was attempted (`offer_attempt_at`, or a legacy
         `unconfirmed` row), at any age: candidates = messages at its price carrying exactly its media
         (`messages.media_ids` = locked + previews), created in `link_window` (from the attempt's
         whole second, else the row's, to `LINK_MAX_S` after it), not another lane's (`automation_kind` set
         to another kind, or a chatter's), not a mass copy (`mass_run_id` / OF `queueId`), id not
         claimed (nor sole candidate of another such row).
         Exactly one -> link it (`join_src` heuristic when paid; link only, `join_src` None, when
         unpaid). Zero or several -> nothing.
  settle_pull(account_id, fan_id=None) -> int   rows changed; each Settle is one UPDATE under the
      fake Buy's guard (`outcome IS NULL AND offer_price_cents > 0`), so a rerun or a concurrent
      call changes nothing twice. A row linked here gets its `vault_sends` (`record_vault_sends`, bought
      when `join_src` is set).
  attempted(r)         the carrier may be on OF (until settle links it, at any age)
  link_window(r)       rule 2's (floor, ceil) for row `r`
  record_vault_sends(s, ..., bought=)   one `vault_sends` row per locked media of a linked Offer, once

No Mode filter (only live rows hold an `offer_message_id`; a test row's Fan id is negative, so it
has no messages), no `already_owned` refusal (he paid), no Turn triggered, no OF call.
"""
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

# OF stamps the PPV within seconds of the attempt; a same-price PPV sent later is another send
# (a mass copy days on must not become Full AI's sale). = 05's UNCONFIRMED_S.
LINK_MAX_S = send_marker_decide.IN_FLIGHT_MAX_S
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


def _ids(raw, *keys: str) -> set[int]:
    """Media ids off a JSON list (`messages.media_ids`) or dict of lists (`offer_media_json`)."""
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
    """The row's carrier POST was attempted (`offer_attempt_at`), or a legacy row (before 0130) the
    reaper left `unconfirmed`: it may be on OF."""
    return getattr(r, "offer_attempt_at", None) is not None or getattr(r, "status", None) == "unconfirmed"


def link_window(r) -> tuple[datetime, datetime]:
    """Rule 2's candidate window: from the carrier's attempt (`offer_attempt_at`; a legacy row's
    `created_at`), cut to OF's whole second, to `LINK_MAX_S` after it. A card from before the
    attempt is another send. `_ppv_readback.sent_ppv`'s Full AI floor is the same second."""
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


_OR_TERMS = 200     # windows per message read: SQLite caps an OR chain's depth (1000)


async def _load(account_id: str, fan_id: int | None):
    """The account's (or one Fan's) unsettled priced rows (unlinked ones only when attempted, at any
    age), their Fans' outbound priced messages: the linked ids, and each unlinked row's own Fan and
    `link_window` (`_OR_TERMS` of them per read); notices of those messages, claimed ids."""
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
    """In session `s`: one `vault_sends` row per locked media of Offer row `row` (`offer_media_json`,
    `offer_price_cents`) sent as OF message `message_id`, the ones missing only: every link path (the
    direct id, the race branch, settle_pull) may call it. `was_purchased` NULL, True when `bought` (settled
    paid: the purchase stamp may have run before these rows existed), which also flips the existing ones."""
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
    """Settle every planned row of the account (or one Fan); returns rows changed."""
    rows, msgs, notices, claimed = await _load(account_id, fan_id)
    plan: list[Settle] = []
    for fan in sorted({r.fan_id for r in rows}):
        plan += settle_plan([r for r in rows if r.fan_id == fan], [m for m in msgs if m.fan_id == fan],
                            notices, claimed)
    by_row = {r.id: r for r in rows}
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
                if res.rowcount:
                    r = by_row[p.row_id]
                    await record_vault_sends(s, r.account_id, r.fan_id, p.message_id, r, bought=p.join_src is not None)
                await s.commit()
            except IntegrityError:          # another row took the message meanwhile
                await s.rollback()
                continue
        if res.rowcount:
            n += res.rowcount
            log.info("full_ai_settle account=%s row=%s msg=%s src=%s", account_id, p.row_id,
                     p.message_id, p.join_src or "link")
    return n
