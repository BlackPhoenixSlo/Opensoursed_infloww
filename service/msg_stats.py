"""msg_stats — the message side of chatting statistics, read from `messages` at
query time (roadmap W5 5.1; feeds Employee reports' Chatting statistics, 5.2,
and the Creator reports' engagement columns, 5.3).

Every figure counts an Employee's own sends (`chatter_sends`): no message of a
mass message, none an automation sent, none stamped with the Automation
sentinel, as Infloww's "Does not include priority and OF mass messages or
automated messages". A message that was later unsent still counts: it was
sent, and the fan saw it until then.

  send_stats     per Creator and Employee: direct messages, direct PPVs
                 (priced), the PPVs among them unlocked (by send date: an
                 unlock today of a PPV sent last month counts last month),
                 characters, and fans chatted (distinct within the group).
  creator_sends  per Creator: direct messages, direct PPVs and fans chatted
                 (each fan once), no body read.
  reply_stats   per Creator and Employee: the number of replies and their
                 summed seconds.
  channel_sales  per Creator and Employee: the sales of direct messages, of
                 mass messages, of Priority mass messages and the chat tips,
                 and the fans who spent.

No rollup: sends are read through `ix_messages_chatter_sends`, replies
through `ix_messages_chat_seq`, which covers them.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import text

import tx_rollup
from attribution_backfill import REVENUE_KINDS, TRACKED_STATUSES
from db.models import Message
from sales_attribution import rules_at, rules_by_account

# How far before the window a reply's wait may have begun: a fan who wrote at
# 23:50 and was answered at 00:10 counts in the window that holds 00:10. A wait
# longer than this is measured from the first inbound inside the lookback.
REPLY_LOOKBACK = timedelta(hours=24)


async def automation_id() -> int | None:
    from employees import get_automation_employee_id
    try:
        return await get_automation_employee_id()
    except LookupError:
        return None


async def chatter_sends() -> list[Any]:
    """Outbound messages an Employee wrote by hand: not part of a mass
    message, not sent by an automation, not stamped with the Automation
    sentinel (Infloww's "Messages sent" excludes mass and automated
    messages; roadmap S4). A box without the sentinel excludes none."""
    out = [Message.direction == "out", Message.sent_by_employee_id.is_not(None),
           Message.mass_run_id.is_(None), Message.automation_kind.is_(None)]
    if (auto := await automation_id()) is not None:
        out.append(Message.sent_by_employee_id != auto)
    return out


async def _own_sql(p: tx_rollup.Binds) -> str:
    """`chatter_sends` as SQL over `messages`."""
    auto = await automation_id()
    return ("direction = 'out' AND sent_by_employee_id IS NOT NULL AND mass_run_id IS NULL "
            "AND automation_kind IS NULL" + ("" if auto is None else f" AND sent_by_employee_id != {p.bind(auto)}"))


async def send_stats_sql(*, account_ids: list[str] | None, start: datetime, end: datetime,
                         edges: list[datetime] | None = None) -> tuple[str, tx_rollup.Binds]:
    """`send_stats`' statement and its binds. The body is not in the index,
    so each send is read from the table: through the partial index, which
    holds only hand-written sends, where SQLite's planner would take
    ix_messages_dir_created and read every outbound message."""
    p = tx_rollup.Binds()
    fmt = tx_rollup.TS_FORMAT
    acct = "" if account_ids is None else f" AND {p.in_('account_id', account_ids)}"
    # Bucket i holds edges[i] <= created_at < edges[i + 1], the last one to `end`.
    whens = " ".join(f"WHEN created_at < {p.bind(e.strftime(fmt))} THEN {i}" for i, e in enumerate((edges or [])[1:]))
    bucket = f"CASE {whens} ELSE {len(edges) - 1} END" if whens else "0"
    sql = (f"SELECT {bucket + ' AS bucket, ' if edges else ''}account_id, sent_by_employee_id AS employee_id, "
           "COUNT(*) AS messages, SUM(price_cents > 0) AS ppvs, SUM(price_cents > 0 AND is_paid = 1) AS unlocked, "
           "COALESCE(SUM(LENGTH(body)), 0) AS chars, COUNT(DISTINCT fan_id) AS fans "
           f"FROM messages INDEXED BY ix_messages_chatter_sends WHERE {await _own_sql(p)}{acct} "
           f"AND created_at >= {p.bind(start.strftime(fmt))} AND created_at <= {p.bind(end.strftime(fmt))} "
           f"GROUP BY {'bucket, ' if edges else ''}account_id, sent_by_employee_id")
    return sql, p


async def send_stats(s, *, account_ids: list[str] | None, start: datetime, end: datetime,
                     edges: list[datetime] | None = None) -> list[Any]:
    """Rows of `account_id`, `employee_id` with `messages`, `ppvs`,
    `unlocked`, `chars` and `fans`, over the sends with `start <= created_at
    <= end` (naive UTC). With `edges` (the
    ascending UTC starts of time buckets, the first at or before `start`)
    each row also carries `bucket`, the index of the edge it falls after:
    fans are distinct within a bucket then."""
    sql, p = await send_stats_sql(account_ids=account_ids, start=start, end=end, edges=edges)
    return (await s.execute(text(sql), p)).all()


async def creator_sends_sql(*, account_ids: list[str] | None, start: datetime,
                            end: datetime) -> tuple[str, tx_rollup.Binds]:
    """`creator_sends`' statement and its binds: `send_stats`' figures per
    Creator alone, leaving out its unlocks and characters, so no body is
    read."""
    p = tx_rollup.Binds()
    fmt = tx_rollup.TS_FORMAT
    acct = "" if account_ids is None else f" AND {p.in_('account_id', account_ids)}"
    sql = ("SELECT account_id, COUNT(*) AS messages, SUM(price_cents > 0) AS ppvs, COUNT(DISTINCT fan_id) AS fans "
           f"FROM messages INDEXED BY ix_messages_chatter_sends WHERE {await _own_sql(p)}{acct} "
           f"AND created_at >= {p.bind(start.strftime(fmt))} AND created_at <= {p.bind(end.strftime(fmt))} "
           "GROUP BY account_id")
    return sql, p


async def creator_sends(s, *, account_ids: list[str] | None, start: datetime, end: datetime) -> list[Any]:
    """Rows of `account_id` with `messages`, `ppvs` and `fans` (each fan once
    per Creator, however many Employees chatted it), over the sends with
    `start <= created_at <= end` (naive UTC): Creator reports' engagement
    columns (roadmap W5 5.3)."""
    sql, p = await creator_sends_sql(account_ids=account_ids, start=start, end=end)
    return (await s.execute(text(sql), p)).all()


async def reply_stats_sql(*, account_ids: list[str] | None, start: datetime, end: datetime,
                          lookback: timedelta = REPLY_LOOKBACK) -> tuple[str, tx_rollup.Binds]:
    """`reply_stats`' statement and its binds."""
    p = tx_rollup.Binds()
    fmt = tx_rollup.TS_FORMAT
    acct = "" if account_ids is None else f" AND {p.in_('account_id', account_ids)}"
    scan, lo, hi = (p.bind((start - lookback).strftime(fmt)), p.bind(start.strftime(fmt)),
                    p.bind(end.strftime(fmt)))
    own = await _own_sql(p)
    by_chat = "PARTITION BY account_id, fan_id ORDER BY created_at, message_id"
    # `seq`: each message of a chat with an Employee's own send in the window
    # (the rest can hold no reply), with the direction of the one before it.
    # `edges`: only where a wait begins (a fan's message after ours) or ends
    # (ours after a fan's); in a chat they alternate, so the edge before an
    # end is its wait's beginning.
    sql = (
        "WITH seq AS (SELECT account_id, fan_id, message_id, direction, created_at, sent_by_employee_id, "
        f"mass_run_id, automation_kind, LAG(direction) OVER ({by_chat}) AS prev_dir FROM messages "
        f"WHERE direction IN ('in', 'out') AND created_at >= {scan} AND created_at <= {hi}{acct} "
        "AND (account_id, fan_id) IN (SELECT account_id, fan_id FROM messages "
        f"WHERE {own} AND created_at >= {lo} AND created_at <= {hi}{acct})), "
        f"edges AS (SELECT *, LAG(created_at) OVER ({by_chat}) AS waited_from FROM seq "
        "WHERE (direction = 'in' AND prev_dir IS NOT 'in') OR (direction = 'out' AND prev_dir = 'in')) "
        "SELECT account_id, sent_by_employee_id AS employee_id, COUNT(*) AS replies, "
        "SUM((julianday(created_at) - julianday(waited_from)) * 86400.0) AS reply_seconds FROM edges "
        f"WHERE created_at >= {lo} AND {own} GROUP BY account_id, sent_by_employee_id")
    return sql, p


async def reply_stats(s, *, account_ids: list[str] | None, start: datetime, end: datetime,
                      lookback: timedelta = REPLY_LOOKBACK) -> list[Any]:
    """Rows of `account_id`, `employee_id` with `replies` and
    `reply_seconds` (their sum) over the replies sent in [start, end].

    A wait begins at a fan's message after one of ours (or the first we see)
    and ends at our next message of any kind; `system` rows are skipped. It
    counts only when that message is an Employee's own send (`chatter_sends`):
    a mass message or an automation that answers first ends the wait for
    nobody. A fan who never got an answer adds nothing (Infloww: "Calculations
    do not include unreplied messages")."""
    sql, p = await reply_stats_sql(account_ids=account_ids, start=start, end=end, lookback=lookback)
    return (await s.execute(text(sql), p)).all()


class ChannelSales(NamedTuple):
    account_id: str
    employee_id: int
    direct_cents: int
    mass_cents: int
    priority_cents: int
    tip_cents: int
    spenders: int


_CHANNELS = ("direct", "mass", "priority", "tip")
# `messages.automation_kind` of a Priority mass message's sends (automations/priority_mass), which a sale of one
# carries as `transactions.credit_automation_kind`, reassigned by hand or not.
PRIORITY_MASS_KIND = "priority_mass"


async def channel_sales(s, *, account_ids: list[str] | None, start: datetime,
                        end: datetime) -> list[ChannelSales]:
    """Per Creator and credited Employee (`transactions.credit_employee_id`),
    the cents of the sales in the window by channel — `direct` (a sale of a
    message, credited by its sender or by hand), `mass` (the same, of a mass
    message), `priority` (the same, of a Priority mass message: one direct
    message per fan, sent by `automations/priority_mass` in the name of the
    Employee who launched it) and `tip` (a chat tip with no message, credited
    by the 7-day lookback or by hand) — and `spenders`, the fans who paid a
    direct message or tipped. Not by the Sales Settings rules: Infloww's
    "Direct message sales" is the sales of the messages an employee sent. A sale of an
    automation's message, or of an OnlyFans-native mass message (it carries
    no sender), is in none unless reassigned by hand.

    "Exclude the 20% OnlyFans fee" applies as each sale's Rules
    (`rules_at`): summed in SQL on a Creator whose Rules hold for the whole
    window, read sale by sale on one whose Rules change in it (as
    `sales_attribution.credited_sales`)."""
    rules = await rules_by_account(s, account_ids, start, end)
    per_row = sorted(a for a, tl in rules.items() if len(tl) > 1)
    fee_off = sorted(a for a, tl in rules.items() if len(tl) == 1 and rules_at(tl, None).exclude_of_fee)
    p = tx_rollup.Binds()
    fmt = tx_rollup.TS_FORMAT
    conds = [p.in_("t.status", TRACKED_STATUSES), p.in_("t.kind", REVENUE_KINDS), "t.credit_employee_id IS NOT NULL",
             f"t.occurred_at >= {p.bind(start.strftime(fmt))}", f"t.occurred_at <= {p.bind(end.strftime(fmt))}"]
    if account_ids is not None:
        conds.append(p.in_("t.account_id", account_ids))
    if (auto := await automation_id()) is not None:
        conds.append(f"t.credit_employee_id != {p.bind(auto)}")
    # Credited by hand, or by `rule` to a human (not an automation's send).
    def by(rule: str) -> str:
        return f"(t.credit_rule = 'manual' OR (t.credit_rule = '{rule}' AND t.credit_automation_kind IS NULL))"
    # The same credit fields as `by`: a Priority mass message's sale reassigned by hand stays one.
    priority = f"(t.credit_rule IN ('manual', 'message') AND t.credit_automation_kind = {p.bind(PRIORITY_MASS_KIND)})"
    channel = (f"CASE WHEN t.message_id IS NOT NULL THEN (CASE WHEN {priority} THEN 'priority' WHEN {by('message')} "
               "THEN (CASE WHEN m.mass_run_id IS NULL THEN 'direct' ELSE 'mass' END) END) "
               f"WHEN t.kind = 'tip' AND {by('tip_lookback')} THEN 'tip' END")
    sales = (f"SELECT t.account_id, t.credit_employee_id AS employee_id, t.fan_id, t.occurred_at, "
             f"t.amount_cents AS gross, {tx_rollup.net_or_80_sql('t')} AS net, {channel} AS channel "
             "FROM transactions t LEFT JOIN messages m ON m.account_id = t.account_id AND m.fan_id = t.fan_id "
             f"AND m.message_id = t.message_id WHERE {' AND '.join(conds)}")
    out: list[ChannelSales] = []
    if per_row:
        p_rows = tx_rollup.Binds(p)
        sql = f"SELECT * FROM ({sales}) WHERE channel IS NOT NULL AND {p_rows.in_('account_id', per_row)}"
        sums: dict[tuple[str, int], dict[str, Any]] = defaultdict(lambda: {**dict.fromkeys(_CHANNELS, 0),
                                                                           "fans": set()})
        for r in (await s.execute(text(sql), p_rows)).all():
            at = datetime.fromisoformat(r.occurred_at) if isinstance(r.occurred_at, str) else r.occurred_at
            acc = sums[(r.account_id, r.employee_id)]
            acc[r.channel] += r.net if rules_at(rules[r.account_id], at).exclude_of_fee else r.gross
            if r.channel in ("direct", "tip"):
                acc["fans"].add(r.fan_id)
        out.extend(ChannelSales(aid, eid, a["direct"], a["mass"], a["priority"], a["tip"], len(a["fans"]))
                   for (aid, eid), a in sums.items())
    amount = f"CASE WHEN {p.in_('account_id', fee_off)} THEN net ELSE gross END" if fee_off else "gross"
    rest = f" AND NOT {p.in_('account_id', per_row)}" if per_row else ""
    cents = ", ".join(f"SUM(CASE WHEN channel = '{c}' THEN {amount} ELSE 0 END) AS {c}_cents" for c in _CHANNELS)
    sql = (f"SELECT account_id, employee_id, {cents}, "
           "COUNT(DISTINCT CASE WHEN channel IN ('direct', 'tip') THEN fan_id END) AS spenders "
           f"FROM ({sales}) WHERE channel IS NOT NULL{rest} GROUP BY account_id, employee_id")
    out.extend(ChannelSales(r.account_id, r.employee_id, int(r.direct_cents), int(r.mass_cents),
                            int(r.priority_cents), int(r.tip_cents), int(r.spenders))
               for r in (await s.execute(text(sql), p)).all())
    return out
