from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import text

import tx_rollup
from attribution_backfill import REVENUE_KINDS, TRACKED_STATUSES
from db.models import Message
from sales_attribution import rules_at, rules_by_account

REPLY_LOOKBACK = timedelta(hours=24)


async def automation_id() -> int | None:
    from employees import get_automation_employee_id
    try:
        return await get_automation_employee_id()
    except LookupError:
        return None


async def chatter_sends() -> list[Any]:
    out = [Message.direction == "out", Message.sent_by_employee_id.is_not(None),
           Message.mass_run_id.is_(None), Message.automation_kind.is_(None)]
    if (auto := await automation_id()) is not None:
        out.append(Message.sent_by_employee_id != auto)
    return out


async def _own_sql(p: tx_rollup.Binds) -> str:
    auto = await automation_id()
    return ("direction = 'out' AND sent_by_employee_id IS NOT NULL AND mass_run_id IS NULL "
            "AND automation_kind IS NULL" + ("" if auto is None else f" AND sent_by_employee_id != {p.bind(auto)}"))


async def send_stats_sql(*, account_ids: list[str] | None, start: datetime, end: datetime,
                         edges: list[datetime] | None = None) -> tuple[str, tx_rollup.Binds]:
    p = tx_rollup.Binds()
    fmt = tx_rollup.TS_FORMAT
    acct = "" if account_ids is None else f" AND {p.in_('account_id', account_ids)}"
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
    sql, p = await send_stats_sql(account_ids=account_ids, start=start, end=end, edges=edges)
    return (await s.execute(text(sql), p)).all()


async def creator_sends_sql(*, account_ids: list[str] | None, start: datetime,
                            end: datetime) -> tuple[str, tx_rollup.Binds]:
    p = tx_rollup.Binds()
    fmt = tx_rollup.TS_FORMAT
    acct = "" if account_ids is None else f" AND {p.in_('account_id', account_ids)}"
    sql = ("SELECT account_id, COUNT(*) AS messages, SUM(price_cents > 0) AS ppvs, COUNT(DISTINCT fan_id) AS fans "
           f"FROM messages INDEXED BY ix_messages_chatter_sends WHERE {await _own_sql(p)}{acct} "
           f"AND created_at >= {p.bind(start.strftime(fmt))} AND created_at <= {p.bind(end.strftime(fmt))} "
           "GROUP BY account_id")
    return sql, p


async def creator_sends(s, *, account_ids: list[str] | None, start: datetime, end: datetime) -> list[Any]:
    sql, p = await creator_sends_sql(account_ids=account_ids, start=start, end=end)
    return (await s.execute(text(sql), p)).all()


async def reply_stats_sql(*, account_ids: list[str] | None, start: datetime, end: datetime,
                          lookback: timedelta = REPLY_LOOKBACK) -> tuple[str, tx_rollup.Binds]:
    p = tx_rollup.Binds()
    fmt = tx_rollup.TS_FORMAT
    acct = "" if account_ids is None else f" AND {p.in_('account_id', account_ids)}"
    scan, lo, hi = (p.bind((start - lookback).strftime(fmt)), p.bind(start.strftime(fmt)),
                    p.bind(end.strftime(fmt)))
    own = await _own_sql(p)
    by_chat = "PARTITION BY account_id, fan_id ORDER BY created_at, message_id"
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
PRIORITY_MASS_KIND = "priority_mass"


async def channel_sales(s, *, account_ids: list[str] | None, start: datetime,
                        end: datetime) -> list[ChannelSales]:
    rules = await rules_by_account(s, account_ids, start, end)
    per_row = sorted(a for a, tl in rules.items() if len(tl) > 1)
    fee_off = sorted(a for a, tl in rules.items() if len(tl) == 1 and rules_at(tl, None).exclude_of_fee)
    p = tx_rollup.Binds()
    fmt = tx_rollup.TS_FORMAT
    emp = ("(CASE WHEN t.credit_rule = 'manual' THEN t.credit_employee_id "
           "WHEN t.message_id IS NOT NULL THEN t.credit_sender_id "
           "WHEN t.credit_rule = 'converters' THEN t.credit_employee_id END)")
    conds = [p.in_("t.status", TRACKED_STATUSES), p.in_("t.kind", REVENUE_KINDS), f"{emp} IS NOT NULL",
             f"t.occurred_at >= {p.bind(start.strftime(fmt))}", f"t.occurred_at <= {p.bind(end.strftime(fmt))}"]
    if account_ids is not None:
        conds.append(p.in_("t.account_id", account_ids))
    if (auto := await automation_id()) is not None:
        conds.append(f"{emp} != {p.bind(auto)}")
    priority = f"t.credit_automation_kind = {p.bind(PRIORITY_MASS_KIND)}"
    channel = (f"CASE WHEN t.message_id IS NOT NULL THEN (CASE WHEN {priority} THEN 'priority' "
               "WHEN t.credit_rule = 'manual' OR t.credit_automation_kind IS NULL "
               "THEN (CASE WHEN m.mass_run_id IS NULL THEN 'direct' ELSE 'mass' END) END) "
               "WHEN t.kind = 'tip' THEN 'tip' END")
    sales = (f"SELECT t.account_id, {emp} AS employee_id, t.fan_id, t.occurred_at, "
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
