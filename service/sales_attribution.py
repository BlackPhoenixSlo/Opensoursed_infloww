"""
sales_attribution.py — Sales attribution in the read path.

Each sale is credited by its Creator's own Agency's `sales` Settings blob
(docs/spec/phase-04-apply-stored-settings.md, "Sales attribution rules";
stories 41-48 and 52-54), in this order:

  1. A manual `transactions.attributed_employee_id` wins; `NO_ONE` there is the
     owner's explicit "No one" (roadmap W6 6.5), credited to nobody whatever
     the rules say, where NULL is no override.
  2. Otherwise the rule Sales Settings sets for the sale's revenue kind:
     Messages (`ppv`, `ppv_message`, `tip` with a message), Posts and Tips
     (`ppv_post`, `tip_post`, `tip` without one), Subscriptions, Streams &
     Referrals (`subscription`, `rebill`, `ppv_stream`, `tip_stream`,
     `referral`; credited by Shift schedule while "Opt in to chatters" is
     on; with it off `subscription`, `rebill` and `referral` stay out of the
     report and `ppv_stream`, `tip_stream` are Unattributed). Any other kind
     the attribution view carries (`custom`) keeps the view's answer.
       - Converters (Infloww: "Sale is attributed to the last Chatter who
         messaged the fan within X hours and Y minutes of the sale"): the
         last human chatter's send to the fan at or before the sale, when it
         is within the Agency's window (`attribution.converters_window_seconds`,
         1 h by default, in effect at the sale's `occurred_at` like every
         rule), else Unattributed. For every kind it rules: message PPV, a
         tip linked to a message, a standalone tip, a post purchase or tip.
         A human chatter's send is an Employee's own outbound 1:1 message:
         no mass message, no automation, not the Automation Employee
         (`tx_rollup.human_send`). The linked message's sender is not
         credited as such: a PPV sent by A and bought after B chatted is B's.
       - Message sender: the linked message's sender, else Unattributed.
         Story 43's "the stricter rule is visibly stricter" holds: Message
         sender never credits a sale without a linked message, and credits
         the sender where Converters credits the last chatter.
       - Shift schedule: the Employees with an open Clock event on that
         Creator at `occurred_at`, or an agency-wide one (w4-a) whose
         Employee holds that Creator in an occurrence containing it
         (`shift_time.creator_spans`), split evenly in whole cents with the
         remainder to the lowest Employee id; none means Unattributed.
  3. While the Agency's Time tracking is off, Shift schedule is credited by
     Converters, and the report carries FALLBACK_LINE.

Both Settings tabs are versioned (settings_api, roadmap W6 6.4): each sale is
credited by the Sales and Time tracking versions in effect at its
`occurred_at`, so a later change never recredits an earlier sale unless it was
saved backdated to before it. Each Creator carries its Agency's Rules over the
window as a `Timeline`.

Then the two toggles (stories 49 and 50):
  - "Exclude welcome messages" drops each sale whose linked message's
    `automation_kind` is one of WELCOME_KINDS.
  - "Exclude the 20% OnlyFans fee" credits each sale at `net_cents` where
    OnlyFans reported it, else 80% of `amount_cents` rounded down, before any
    Shift schedule split.

Nothing is written: `messages.sent_by_employee_id` and
`transactions.attributed_employee_id` are only read (ADR-0012, story 52).
`stats.per_employee` and `event_sales` (the Timesheet's Recorded earnings,
`shifts_api.timesheet`, and Shift records' sales, `clock_api.shift_records`)
are the callers, so all credit by the same rules and toggles (story 51);
`event_sales` keeps only the shares inside the credited Employee's Clock
event (its ASSUMPTION for Needs-the-human).

ASSUMPTION: "Exclude welcome messages" drops a welcome-linked sale even when
it was reassigned by hand, since the toggle names the sale's message, not its
credit. Rung 4 (nothing is written; turning the toggle off restores it).
Overturned if the owner wants a manual reassignment to keep the sale.

The touches a rule reads are materialised on the row at write time
(`transactions.credit_*`, kept by the triggers in tx_rollup.py, which
test_tx_rollup proves equal to the attribution view): the linked message's
sender, and the converter candidate (the last human chatter's send within
999 h 59 min, `tx_rollup.converter_lookback`, the one lookback), with the
credit under the default 1 h window. So no read computes a lookback: `credit`
narrows the candidate to the Agency's window (`tx_rollup.within_window`).
Employee reports sum the rollups (`tx_daily`, `tx_hourly`) for every Creator
no Shift schedule rule reaches, whose Rules do not change inside the window,
keep Converters' default window and use no Message sender (`grouped=True`);
any other Creator's sales are read one by one, since the Clock events, the
Rules, or the touches at each sale's instant decide its credit. Sales records lists the same shares
row by row (`credit_context` and `credit`), so both pages credit each sale to
the same Employees for the same amount (roadmap S7).

ASSUMPTION: with the opt-in off, a `subscription`, `rebill` or `referral`
sale with no manual override stays out of Employee reports, as it always has
(the attribution view never carried those kinds), rather than appearing in
the Unattributed bucket; a manual override still credits its Employee. The
spec's "stay Unattributed, as today" (phase-04 spec, Sales attribution rules)
contradicts itself across the group, so this reads "as today" for these
kinds. Rung 4: no Agency's figures for these kinds change on upgrade, and
showing them as Unattributed later is one line. Overturned if the owner wants
opt-in-off subscription revenue visible in the Unattributed bucket.

ASSUMPTION (for Needs-the-human): with the opt-in off, `ppv_stream` and
`tip_stream` sales, credited by the view's answer until now, move to the
Unattributed bucket, per the spec's kind map (Subscriptions, Streams &
Referrals). This changes Employee report figures on upgrade day for any
Agency with stream sales. Rung 4: nothing is written, so turning the opt-in
on, or a one-line map change, restores the credit. Overturned if the owner
wants streams kept on the Converters answer while the opt-in is off.
"""

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

# The override that names no Employee: Sales records' "No one". Employee ids
# start at 1, so 0 is never one; the triggers store it as the credit too
# (`credit_employee_id` 0, `credit_rule` "manual", the attribution view's own
# COALESCE answer), and the rollups already read 0 as nobody.
NO_ONE = 0

SUBSCRIPTION_KINDS = ("subscription", "rebill", "ppv_stream", "tip_stream", "referral")
# `messages.automation_kind` of the welcome automations (spec, Sales attribution rules).
WELCOME_KINDS = ("send_welcome", "welcome", "welcome_chatter_for_info")
# Kinds the view never carried: left out while Subscriptions are Unattributed.
_NEVER_REPORTED = ("subscription", "rebill", "referral")


class CreditedSale(NamedTuple):
    """One sale, or one Employee's share of a split sale, net of the fee when
    "Exclude the 20% OnlyFans fee" is on.

    ASSUMPTION: each row also carries the sale's `occurred_at`, which the
    spec's row shape leaves out, so the Timesheet can keep Recorded earnings
    to worked intervals. Rung 5 (one additive field, no second query).
    Overturned if a caller needs the spec's four fields exactly."""
    employee_id: int | None
    account_id: str
    kind: str
    amount_cents: int
    occurred_at: datetime | None  # None for a rollup sum (`grouped=True`), its bucket's start with `bucket`
    sales: int = 1  # how many sales a rollup sum holds
    tx_id: int | None = None  # None for a rollup sum
    split: bool = False  # one of a split sale's shares (another Employee holds the rest)


class Rules(NamedTuple):
    """An Agency's effective rule per revenue group ("converters", "sender",
    "shift"; None is Unattributed), whether Shift schedule fell back, its
    two toggles: "Exclude welcome messages" and "Exclude the 20% OnlyFans
    fee", and Converters' window in seconds."""
    messages: str
    posts_tips: str
    subscriptions: str | None
    fell_back: bool
    exclude_welcome: bool
    exclude_of_fee: bool
    window_s: int = tx_rollup.CONVERTERS_WINDOW_DEFAULT_S

    @property
    def per_row(self) -> bool:
        """Whether a rollup sum cannot credit these Rules' sales: a Shift
        schedule or Message sender rule, or a Converters window other than
        the default the stored credit was computed with."""
        return ("shift" in (self.messages, self.posts_tips, self.subscriptions) or self.messages == "sender"
                or self.window_s != tx_rollup.CONVERTERS_WINDOW_DEFAULT_S)


# ASSUMPTION: a Creator with no owning Agency has no Sales Settings and is
# credited by Converters with the opt-in and both toggles off, with no
# fallback line. Rung 4: its Messages and Posts and Tips figures do not
# change; its `ppv_stream` and `tip_stream` sales move to Unattributed like
# every Agency's (the stream ASSUMPTION in the module docstring). Overturned if orphan Creators should
# follow the never-saved defaults (Shift schedule) instead.
_NO_AGENCY = Rules("converters", "converters", None, False, False, False)

# One Agency's Rules over a window: `(from, Rules)` in time order, each in
# effect from its `from` until the next one's; the first is in effect at the
# window's start. Consecutive equal Rules are merged.
Timeline = list[tuple[datetime, Rules]]


def _timeline(sales: list[tuple[datetime, dict[str, Any]]], tracking: list[tuple[datetime, dict[str, Any]]],
              start: datetime | None, end: datetime | None) -> Timeline:
    """The Rules an Agency's Sales and Time tracking versions
    (`settings_api.applied_versions`) put in effect over [start, end]
    (either open): one entry from each version's `effective_from` on."""
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
    """The Rules in effect at `at`; a rollup sum (`at` None) is only ever
    read for a Timeline of one entry. A Creator with no Agency gets
    _NO_AGENCY."""
    if not timeline:
        return _NO_AGENCY
    found = timeline[0][1]
    for since, rules in timeline:
        if at is not None and since > at:
            break
        found = rules
    return found


def rules_for(sales: dict[str, Any], time_tracking_on: bool) -> Rules:
    """The effective Rules from an Applied `sales` blob. A never-saved rule is
    "shift" and the opt-in off, the Sales Settings Panel's defaults
    (app/components/settings/SalesSettingsTab.tsx DEFAULT)."""
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
    """`{account_id: Timeline}` over [start, end] for each Creator with an
    owning Agency, read from that Agency's Settings versions, and
    `{account_id: owning Agency's user id}`. The owner is `tenant_keys.billable_owners`' first
    (a Master link only when no Agency owns it), so each Creator is credited
    by its own Agency's rules even when the Master reads several.

    ASSUMPTION: a Creator linked to two non-Master Agencies takes the rules of
    the first by user id. Rung 6 (the deployment has no such Creator, per
    tenant_keys.owners_of). Overturned by a rule for co-owned Creators."""
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
    """Each Creator's Rules over [start, end], `Context.rules` without the
    Clock read: for a caller that applies a toggle itself (`rules_at`)."""
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
    """Whole-cent shares, the remainder to the lowest Employee id."""
    ids = sorted(employee_ids)
    share, rest = divmod(amount_cents, len(ids))
    return [(eid, share + (rest if i == 0 else 0)) for i, eid in enumerate(ids)]


def net_or_80(amount_cents: int, net_cents: int | None) -> int:
    """A sale's amount under "Exclude the 20% OnlyFans fee"."""
    return net_cents if net_cents is not None else amount_cents * 8 // 10


class Context(NamedTuple):
    """What crediting a sale reads besides the sale: each Creator's Rules over
    the window, and each Shift schedule Creator's Clock spans `(employee_id,
    lo, hi)`. `per_row` are the Creators whose sales a rollup sum cannot
    credit: Rules that change in the window, or any `Rules.per_row`."""
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
        # Only the owning Agency's Clock events, as the Timesheet reads
        # them (shifts_api.py, ClockEvent.agency_user_id), each on the
        # Creators `creator_spans` puts its time on: an agency-wide one
        # only where its Employee holds the Creator in an occurrence.
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
    """One sale's shares `(employee_id, cents, rule)` under its Agency's
    rules, from its materialised credit (`employee_id`, `rule`,
    `automation_kind`, `sender_id`, `converter_id` and `converter_at` are
    `transactions.credit_*`, `linked` is `message_id IS NOT NULL`); empty
    when a rule or toggle leaves it out of the reports. A share's `rule`
    names what credited it: `manual`, `message` (the linked message's
    sender), `converters`, `shift` or `unassigned`. The Rules are those in
    effect at `occurred_at` (`rules_at`). A rollup sum (no touches, `at`
    None) is only credited here for Rules that are not `per_row`, where the
    stored credit is Converters' answer. A "No one" override (`NO_ONE`; a
    rollup sum reads it as None) is one share to nobody, rule `manual`.

    ASSUMPTION: a "No one" sale whose kind Employee reports leave out
    (`_NEVER_REPORTED` with the opt-in off) is listed in the Unattributed
    bucket, as any override is listed, since the owner named its credit.
    Rung 5. Overturned if "No one" should leave such a sale out instead."""
    agency_rules = rules_at(ctx.rules.get(account_id), occurred_at)
    group = _group(kind, linked)
    by = "converters" if group is None else getattr(agency_rules, group)
    manual = rule == "manual"
    if not manual and by is None and kind in _NEVER_REPORTED:
        return []
    # A sale's `automation_kind` is its linked message's.
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
    """`credit` of a `transactions` row `r` (its account_id, kind, message_id,
    credit_* columns, amount_cents, net_cents and occurred_at)."""
    return credit(ctx, r.account_id, r.kind, r.message_id is not None, r.credit_employee_id, r.credit_rule,
                  r.credit_automation_kind, r.amount_cents, net_or_80(r.amount_cents, r.net_cents), r.occurred_at,
                  sender_id=r.credit_sender_id, converter_id=r.credit_converter_id,
                  converter_at=r.credit_converter_at)


CREDITED_KINDS = REVENUE_KINDS + SUBSCRIPTION_KINDS


async def credited_sales(account_ids: list[str] | None, start: datetime | None,
                         end: datetime | None, *, grouped: bool = False,
                         bucket: str | None = None) -> tuple[list[CreditedSale], str | None]:
    """Every tracked sale in the window on these Creators (all when None),
    credited by its Agency's rules (a split sale yields one row per share),
    and FALLBACK_LINE when any Agency owning a Creator in scope has Shift
    schedule credited by Converters because its Time tracking is off.

    `grouped=True` sums the sales of every Creator whose Rules hold for the
    whole window and are not `Rules.per_row` from the hourly rollup
    (`occurred_at` None, `sales` the count), and still lists the other
    Creators' sales one by one (`Context.per_row`). With `bucket` ("hour" or
    "minute", `tx_rollup.window_sums`) the sums are per UTC hour or minute,
    `occurred_at` its start."""
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
    """Each Clock event's sales, by event id: the shares `credited_sales`
    credits to its Employee (Employee reports' rules and toggles) whose
    `occurred_at` falls in the event's time on a Creator (`creator_spans`;
    an open event runs to `now`). The one Recorded earnings rule: Shift
    records' sales (clock_api.shift_records) and the Timesheet (shifts_api.timesheet, which passes the
    `spans` it already read) both count these. Each share carries its sale's
    `tx_id`, and `split` when other Employees hold the rest of the sale."""
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
