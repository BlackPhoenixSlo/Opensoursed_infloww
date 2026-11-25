from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, NamedTuple

from sqlalchemy import and_, or_, select

import tx_rollup
from attribution_backfill import REVENUE_KINDS, TRACKED_STATUSES
from db.engine import get_session
from db.models import ClockEvent, Transaction, User, UserAccount
from shift_time import creator_spans

FALLBACK_LINE = "Shift schedule needs Time tracking on; credited by Converters."

# Employee ids start at 1, so 0 (NO_ONE) is never one; triggers store it as the credit and rollups read 0 as nobody.
NO_ONE = 0

SUBSCRIPTION_KINDS = ("subscription", "rebill", "ppv_stream", "tip_stream", "referral")
WELCOME_KINDS = ("send_welcome", "welcome", "welcome_chatter_for_info")
_NEVER_REPORTED = ("subscription", "rebill", "referral")


class CreditedSale(NamedTuple):
    employee_id: int | None
    account_id: str
    kind: str
    amount_cents: int
    occurred_at: datetime | None
    sales: int = 1
    tx_id: int | None = None
    split: bool = False


class Rules(NamedTuple):
    messages: str
    posts_tips: str
    subscriptions: str | None
    fell_back: bool
    exclude_welcome: bool
    exclude_of_fee: bool
    window_s: int = tx_rollup.CONVERTERS_WINDOW_DEFAULT_S

    @property
    def per_row(self) -> bool:
        return ("shift" in (self.messages, self.posts_tips, self.subscriptions) or self.messages == "sender"
                or self.window_s != tx_rollup.CONVERTERS_WINDOW_DEFAULT_S)


# A Creator with no owning Agency is credited by Converters with the opt-in and both toggles off, no fallback line.
_NO_AGENCY = Rules("converters", "converters", None, False, False, False)

Timeline = list[tuple[datetime, Rules]]


def _timeline(sales: list[tuple[datetime, dict[str, Any]]], tracking: list[tuple[datetime, dict[str, Any]]],
              start: datetime | None, end: datetime | None) -> Timeline:
    from clock_api import time_tracking_of
    from settings_api import blob_at

    out: Timeline = []
    for at in sorted({datetime.min} | {at for at, _ in sales + tracking}):
        rules = rules_for(blob_at(sales, at), time_tracking_of(blob_at(tracking, at)).enabled)
        if not out or out[-1][1] != rules:
            out.append((at, rules))
    return [(at, r) for i, (at, r) in enumerate(out)
            if (end is None or at <= end) and (start is None or i + 1 == len(out) or out[i + 1][0] > start)]


def rules_at(timeline: Timeline | None, at: datetime | None) -> Rules:
    if not timeline:
        return _NO_AGENCY
    found = timeline[0][1]
    for since, rules in timeline:
        if at is not None and since > at:
            break
        found = rules
    return found


def rules_for(sales: dict[str, Any], time_tracking_on: bool) -> Rules:
    attribution = sales.get("attribution") or {}
    messages = attribution.get("messages", "shift")
    posts_tips = attribution.get("posts_tips", "shift")
    subscriptions = "shift" if attribution.get("subscriptions_chatter_opt_in") is True else None
    asked = (messages, posts_tips, subscriptions)
    if not time_tracking_on:
        messages, posts_tips, subscriptions = (
            "converters" if r == "shift" else r for r in asked)
    return Rules(messages, posts_tips, subscriptions, not time_tracking_on and "shift" in asked,
                 sales.get("exclude_welcome") is True, sales.get("exclude_of_fee") is True,
                 attribution.get("converters_window_seconds", tx_rollup.CONVERTERS_WINDOW_DEFAULT_S))


async def _rules_by_account(
    s, account_ids: list[str] | None, start: datetime | None, end: datetime | None,
) -> tuple[dict[str, Timeline], dict[str, str]]:
    # A Creator linked to two non-Master Agencies takes the rules of the first by user id.
    from settings_api import applied_versions
    from tenant_keys import billable_owners

    q = (select(UserAccount.account_id, UserAccount.user_id, User.is_admin)
         .join(User, User.id == UserAccount.user_id)
         .order_by(UserAccount.account_id, UserAccount.user_id))
    if account_ids is not None:
        q = q.where(UserAccount.account_id.in_(account_ids))
    links: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for aid, uid, is_admin in (await s.execute(q)).all():
        links[aid].append((uid, bool(is_admin)))
    by_agency: dict[str, Timeline] = {}
    out: dict[str, Timeline] = {}
    owner: dict[str, str] = {}
    for aid, owner_links in links.items():
        agency = billable_owners(owner_links)[0]
        if agency not in by_agency:
            by_agency[agency] = _timeline(await applied_versions(s, agency, "sales"),
                                          await applied_versions(s, agency, "time-tracking"), start, end)
        out[aid] = by_agency[agency]
        owner[aid] = agency
    return out, owner


async def rules_by_account(s, account_ids: list[str] | None, start: datetime | None,
                           end: datetime | None) -> dict[str, Timeline]:
    return (await _rules_by_account(s, account_ids, start, end))[0]


def _group(kind: str, linked: bool) -> str | None:
    if kind in ("ppv", "ppv_message") or (kind == "tip" and linked):
        return "messages"
    if kind in ("ppv_post", "tip_post", "tip"):
        return "posts_tips"
    if kind in SUBSCRIPTION_KINDS:
        return "subscriptions"
    return None


def split_evenly(amount_cents: int, employee_ids: list[int]) -> list[tuple[int, int]]:
    ids = sorted(employee_ids)
    share, rest = divmod(amount_cents, len(ids))
    return [(eid, share + (rest if i == 0 else 0)) for i, eid in enumerate(ids)]


def net_or_80(amount_cents: int, net_cents: int | None) -> int:
    return net_cents if net_cents is not None else amount_cents * 8 // 10


class Context(NamedTuple):
    rules: dict[str, Timeline]
    clock: dict[str, list[tuple[int, datetime, datetime]]]
    shift_accounts: list[str]
    per_row: list[str]

    @property
    def fallback(self) -> str | None:
        return FALLBACK_LINE if any(r.fell_back for tl in self.rules.values() for _, r in tl) else None


async def credit_context(s, account_ids: list[str] | None, start: datetime | None,
                         end: datetime | None) -> Context:
    rules, owner = await _rules_by_account(s, account_ids, start, end)
    shift_accounts = [a for a, tl in rules.items()
                      if any("shift" in (r.messages, r.posts_tips, r.subscriptions) for _, r in tl)]
    clock: dict[str, list[tuple[int, datetime, datetime]]] = defaultdict(list)
    if shift_accounts:
        agencies = sorted({owner[aid] for aid in shift_accounts})
        cq = select(ClockEvent).where(
            or_(ClockEvent.account_id.in_(shift_accounts),
                and_(ClockEvent.account_id.is_(None), ClockEvent.agency_user_id.in_(agencies))),
            ClockEvent.employee_id.is_not(None))
        if end:
            cq = cq.where(ClockEvent.in_utc <= end)
        if start:
            cq = cq.where(or_(ClockEvent.out_utc.is_(None), ClockEvent.out_utc > start))
        events = (await s.execute(cq)).scalars().all()
        for ev, aid, lo, hi in await creator_spans(s, events, datetime.utcnow()):
            if owner.get(aid) == ev.agency_user_id:
                clock[aid].append((ev.employee_id, lo, hi))
    return Context(rules, clock, shift_accounts,
                   [a for a, tl in rules.items() if len(tl) > 1 or any(r.per_row for _, r in tl)])


def credit(ctx: Context, account_id: str, kind: str, linked: bool, employee_id: int | None, rule: str | None,
           automation_kind: str | None, gross_cents: int, net_or_80_cents: int,
           occurred_at: datetime | None, *, sender_id: int | None = None, converter_id: int | None = None,
           converter_at: datetime | None = None) -> list[tuple[int | None, int, str]]:
    agency_rules = rules_at(ctx.rules.get(account_id), occurred_at)
    group = _group(kind, linked)
    by = "converters" if group is None else getattr(agency_rules, group)
    manual = rule == "manual"
    if not manual and by is None and kind in _NEVER_REPORTED:
        return []
    if agency_rules.exclude_welcome and linked and automation_kind in WELCOME_KINDS:
        return []
    amount = net_or_80_cents if agency_rules.exclude_of_fee else gross_cents
    if manual:
        return [(employee_id or None, amount, "manual")]
    if by == "converters" and kind in REVENUE_KINDS:
        if agency_rules.window_s == tx_rollup.CONVERTERS_WINDOW_DEFAULT_S:
            if rule == "converters":
                return [(employee_id, amount, rule)]
        elif tx_rollup.within_window(occurred_at, converter_at, agency_rules.window_s):
            return [(converter_id, amount, "converters")]
    if by == "sender" and linked and sender_id is not None:
        return [(sender_id, amount, "message")]
    if by == "shift":
        on = {eid for eid, lo, hi in ctx.clock[account_id] if lo <= occurred_at < hi}
        if on:
            return [(eid, cents, "shift") for eid, cents in split_evenly(amount, list(on))]
    return [(None, amount, "unassigned")]


def credit_row(ctx: Context, r: Any) -> list[tuple[int | None, int, str]]:
    return credit(ctx, r.account_id, r.kind, r.message_id is not None, r.credit_employee_id, r.credit_rule,
                  r.credit_automation_kind, r.amount_cents, net_or_80(r.amount_cents, r.net_cents), r.occurred_at,
                  sender_id=r.credit_sender_id, converter_id=r.credit_converter_id,
                  converter_at=r.credit_converter_at)


CREDITED_KINDS = REVENUE_KINDS + SUBSCRIPTION_KINDS


async def credited_sales(account_ids: list[str] | None, start: datetime | None,
                         end: datetime | None, *, grouped: bool = False,
                         bucket: str | None = None) -> tuple[list[CreditedSale], str | None]:
    t = Transaction
    out: list[CreditedSale] = []
    async with get_session() as s:
        ctx = await credit_context(s, account_ids, start, end)
        if grouped:
            sums = await tx_rollup.window_sums(
                s, ("account_id", "kind", "linked", "employee_id", "rule", "automation_kind"),
                account_ids=account_ids, start=start, end=end,
                where={"status": TRACKED_STATUSES, "kind": CREDITED_KINDS}, bucket=bucket)
            for r in sums:
                if r.account_id in ctx.per_row:
                    continue
                at = (datetime.fromisoformat(r.bucket) if r.bucket else None) if bucket else None
                out.extend(CreditedSale(eid, r.account_id, r.kind, cents, at, r.sales)
                           for eid, cents, _ in credit(ctx, r.account_id, r.kind, bool(r.linked), r.employee_id,
                                                       r.rule, r.automation_kind, r.gross_cents,
                                                       r.net_or_80_cents, None))
        per_row = ctx.per_row if grouped else account_ids
        if per_row is None or per_row:
            q = (select(t.id, t.account_id, t.kind, t.message_id, t.credit_employee_id, t.credit_rule,
                        t.credit_automation_kind, t.credit_sender_id, t.credit_converter_id,
                        t.credit_converter_at, t.amount_cents, t.net_cents, t.occurred_at)
                 .where(t.status.in_(TRACKED_STATUSES), t.kind.in_(CREDITED_KINDS))
                 .order_by(t.id))
            if per_row is not None:
                q = q.where(t.account_id.in_(per_row))
            if start:
                q = q.where(t.occurred_at >= start)
            if end:
                q = q.where(t.occurred_at <= end)
            for r in (await s.execute(q)).all():
                shares = credit_row(ctx, r)
                out.extend(CreditedSale(eid, r.account_id, r.kind, cents, r.occurred_at, tx_id=r.id,
                                        split=len(shares) > 1)
                           for eid, cents, _ in shares)
    return out, ctx.fallback


async def event_sales(s, events: list[ClockEvent], now: datetime,
                      spans: list[tuple[ClockEvent, str, datetime, datetime]] | None = None,
                      ) -> dict[int, list[CreditedSale]]:
    out: dict[int, list[CreditedSale]] = {ev.id: [] for ev in events}
    if spans is None:
        spans = await creator_spans(s, events, now)
    spans = [(ev, acc, lo, hi) for ev, acc, lo, hi in spans if ev.employee_id is not None and lo < hi]
    if not spans:
        return out
    held: dict[tuple[int, str], list[tuple[datetime, datetime, int]]] = {}
    for ev, acc, lo, hi in spans:
        held.setdefault((ev.employee_id, acc), []).append((lo, hi, ev.id))
    credited, _ = await credited_sales(sorted({acc for _, acc, _, _ in spans}),
                                       min(lo for _, _, lo, _ in spans), max(hi for _, _, _, hi in spans))
    for c in credited:
        for lo, hi, ev_id in held.get((c.employee_id, c.account_id), ()):
            if lo <= c.occurred_at < hi:
                out[ev_id].append(c)
                break
    return out
