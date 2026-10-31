"""
stats_employees.py — Employee reports' reads, split out of stats.py.

  GET /admin/stats/per-employee     → revenue, PPV conversions and messages
                                       sent per Employee, as the Sales
                                       Settings rules credit each sale
  GET /admin/stats/chatting-stats   → Chatting statistics per Employee, or
                                       with `bucket` the charts' time series

stats.py includes this router where these routes stood (route order). The
report zone is read as `stats._report_zone` / `stats._report_prefs` at call
time (imported in the route, no import-time cycle), so a patch on `stats` reaches
these routes as before the split.
"""

from __future__ import annotations

import asyncio
import bisect
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select

import msg_stats
import stats_window
import tx_rollup
from attribution_backfill import PPV_KINDS, TIP_KINDS
from auth import clamp_account_filter, get_request_user
from db.engine import get_session
from db.models import Account, ClockEvent, Employee, Message
from sales_attribution import credited_sales
from shift_time import minutes_up
from stats_window import parse_date as _parse_date, stats_guard

router = APIRouter(dependencies=[Depends(stats_guard)])

_UNATTRIBUTED_BUCKET = "Unattributed"


async def _only_chatters(own: set[int] | None, chatter_only: bool) -> set[int] | None:
    """The Employee ids a report may show (`own`, None for all), narrowed with
    `chatter_only` to the built-in Chatter role's (`permissions.role_holders`):
    Employee reports' "Show employees with chatter role only" (roadmap W5 5.13)."""
    if not chatter_only:
        return own
    from permissions import role_holders
    chatters = await role_holders("chatter")
    return chatters if own is None else own & chatters


def _empty_employee_row(eid: int | None, display_name: str | None) -> dict[str, Any]:
    return {
        "employee_id": eid,
        "display_name": display_name,
        "messages_sent": 0,
        "ppv_conversions": 0,
        "revenue_cents": 0,
        "revenue_by_kind": {"ppv": 0, "tip": 0},
    }


@router.get("/admin/stats/per-employee")
async def per_employee(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    by_account: bool = Query(False),
    chatter_only: bool = Query(False),
) -> dict[str, Any]:
    """Per-employee revenue rollup. Each sale is credited by its Creator's
    Agency's Sales Settings rules (`sales_attribution.credited_sales`), whose
    Converters rule credits the last human chatter who messaged the fan within
    the Agency's window of the sale (1 h by default, materialised on the row);
    summed from the hourly rollup (`grouped=True`).

    Numbers per employee:
      • messages_sent     — count of outbound messages this op wrote by hand
                             in window, no mass or automated ones (S4)
      • ppv_conversions   — PPV sales credited to the op
      • revenue_cents     — SUM(amount_cents) of the sales credited to the op

    Special bucket: a sale credited to no one (no human chatter messaged the
    fan within the Converters window, no manual assignment, or a sale a rule
    leaves Unattributed) lands in an
    "Unattributed" synthetic bucket so the revenue stays visible in the
    per-employee total. `attribution_fallback` carries
    `sales_attribution.FALLBACK_LINE` when an Agency in scope has Shift
    schedule credited by Converters because its Time tracking is off, else null.

    ``by_account=true`` adds a `per_account[]` breakdown per employee.
    ``chatter_only=true`` keeps the Employees holding the Chatter role
    (`permissions.role_holders`), no Unattributed bucket.

    Under Role enforcement a chatter whose Data scope is not "all" gets only
    its own row (`permissions.scoped_employee_ids`), no Unattributed bucket."""
    import stats
    from permissions import scoped_employee_ids
    own = await _only_chatters(await scoped_employee_ids(), chatter_only)
    zone = await stats._report_zone(None)
    start = _parse_date(from_, field="from", zone=zone)
    end = _parse_date(to, field="to", zone=zone)
    # Clamp to the signed-in friend's accounts so per-employee rollups
    # don't mix in other friends' chatter activity.
    account_ids = clamp_account_filter(None)

    # ── Q1: messages_sent per employee: its own sends, no mass or automated
    # ones (`msg_stats.chatter_sends`, roadmap S4). ─────────────────────
    mq = (
        select(
            Message.sent_by_employee_id.label("employee_id"),
            Message.account_id.label("account_id"),
            func.count().label("messages_sent"),
        )
        .where(*await msg_stats.chatter_sends())
    )
    if account_ids is not None:
        mq = mq.where(Message.account_id.in_(account_ids))
    if start:
        mq = mq.where(Message.created_at >= start)
    if end:
        mq = mq.where(Message.created_at <= end)
    if by_account:
        mq = mq.group_by(Message.sent_by_employee_id, Message.account_id)
    else:
        mq = mq.group_by(Message.sent_by_employee_id)

    # ── Q2: each sale credited by its Creator's Agency's Sales Settings
    # rules (sales_attribution; Converters is the attribution view's answer).
    # Nothing is written, so switching a rule back restores the old figures.

    # Each task opens its OWN AsyncSession — a single AsyncSession is not
    # safe for concurrent execute() under asyncio.gather (raises
    # IllegalStateChangeError); the engine's pool hands one connection
    # per task and SQLite WAL handles parallel readers fine.
    async def _run(stmt: Any) -> list[Any]:
        async with get_session() as ss:
            return (await ss.execute(stmt)).all()

    # Label lookup only — display_name isn't sensitive and the actual
    # data isolation already happened via `clamp_account_filter` above
    # (messages/transactions are scoped to the principal's accounts).
    # Filtering this lookup by user_id used to surface bare "Employee
    # #N" labels in the table whenever a message's sent_by_employee_id
    # pointed at a row outside the principal's roster — typically a
    # chatter mirror Employee created under a co-owner, or a legacy row
    # whose owner is no longer the current user. Lookup-everything keeps
    # the table readable; no rows that weren't already visible become
    # visible, since the data join is account-scoped.
    emp_lookup_q = select(Employee.id, Employee.display_name)
    if by_account:
        acct_lookup_q = select(Account.id, Account.nickname)
        if account_ids is not None:
            acct_lookup_q = acct_lookup_q.where(Account.id.in_(account_ids))
        msg_rows, (credited, fallback), emp_rows, acct_rows = await asyncio.gather(
            _run(mq), credited_sales(account_ids, start, end, grouped=True),
            _run(emp_lookup_q), _run(acct_lookup_q),
        )
        account_labels: dict[str, str | None] = {aid: nick for aid, nick in acct_rows}
    else:
        msg_rows, (credited, fallback), emp_rows = await asyncio.gather(
            _run(mq), credited_sales(account_ids, start, end, grouped=True),
            _run(emp_lookup_q),
        )
        account_labels = {}

    names: dict[int, str | None] = {eid: dname for eid, dname in emp_rows}

    # ── Merge ───────────────────────────────────────────────────────────
    # We key by (employee_id, account_id?) so by_account=True produces a
    # per_account[] list per employee. `None` employee_id is the
    # synthetic "Unattributed" bucket holding standalone-tip orphans.
    by_emp: dict[int | None, dict[str, Any]] = {}

    def _bucket(eid: int | None) -> dict[str, Any]:
        if eid in by_emp:
            return by_emp[eid]
        if eid is None:
            row = _empty_employee_row(None, _UNATTRIBUTED_BUCKET)
        else:
            row = _empty_employee_row(eid, names.get(eid))
        if by_account:
            row["per_account"] = {}
        by_emp[eid] = row
        return row

    def _acct_sub(emp_row: dict[str, Any], aid: str | None) -> dict[str, Any]:
        sub_map: dict[str | None, dict[str, Any]] = emp_row["per_account"]
        if aid in sub_map:
            return sub_map[aid]
        sub_map[aid] = {
            "account_id": aid,
            "account_nickname": account_labels.get(aid) if aid else None,
            "messages_sent": 0,
            "ppv_conversions": 0,
            "revenue_cents": 0,
            "revenue_by_kind": {"ppv": 0, "tip": 0},
        }
        return sub_map[aid]

    # Apply message counts. Messages with sent_by_employee_id IS NULL
    # don't appear here (mq filters them out) — those land in
    # /admin/stats/attribution-coverage, not the per-employee revenue
    # rollup. The Unattributed bucket exists only for orphan tip revenue.
    for r in msg_rows:
        eid = int(r.employee_id)
        emp_row = _bucket(eid)
        emp_row["messages_sent"] += int(r.messages_sent or 0)
        if by_account:
            aid = r.account_id
            sub = _acct_sub(emp_row, aid)
            sub["messages_sent"] += int(r.messages_sent or 0)

    # Credited sales → revenue, PPV conversions and the {ppv, tip} split.
    # None-employee rows feed the synthetic "Unattributed" bucket its real
    # split (orphan PPVs and tips, and whatever a rule leaves Unattributed).
    # ASSUMPTION: each Employee sharing a split PPV sale counts it as one
    # conversion. Rung 6. Overturned if a split sale should count once in all.
    for c in credited:
        is_ppv = c.kind in PPV_KINDS
        ppv_c = c.amount_cents if is_ppv else 0
        tip_c = c.amount_cents if c.kind in TIP_KINDS else 0
        targets = [_bucket(c.employee_id)]
        if by_account:
            targets.append(_acct_sub(targets[0], c.account_id))
        for row in targets:
            row["revenue_cents"] += c.amount_cents
            row["ppv_conversions"] += c.sales if is_ppv else 0
            row["revenue_by_kind"]["ppv"] += ppv_c
            row["revenue_by_kind"]["tip"] += tip_c

    # Flatten per_account map → sorted list (highest revenue first).
    if by_account:
        for emp_row in by_emp.values():
            sub_map: dict[str | None, dict[str, Any]] = emp_row["per_account"]
            emp_row["per_account"] = sorted(
                sub_map.values(),
                key=lambda x: x["revenue_cents"],
                reverse=True,
            )

    rows = [r for r in by_emp.values() if own is None or r["employee_id"] in own]
    out = sorted(rows, key=lambda x: x["revenue_cents"], reverse=True)
    return {"employees": out, "attribution_fallback": fallback}


# The counts of a Chatting statistics row, summed over an Employee's Creators.
_CHAT_COUNTS = ("direct_messages_sent", "direct_ppvs_sent", "ppvs_unlocked", "character_count", "fans_chatted",
                "sales_cents", "ppv_sales_cents", "tip_sales_cents", "direct_message_sales_cents",
                "mass_message_sales_cents", "priority_mass_message_sales_cents", "fans_who_spent", "replies")


def _shown(eid: int | None, auto: int | None, own: set[int] | None) -> bool:
    """Whether Chatting statistics show Employee `eid`'s figures: not the
    Unattributed sales (None), not the Automation sentinel, and only the
    Data scope's own Employees when it narrows (`scoped_employee_ids`)."""
    return eid is not None and eid != auto and (own is None or eid in own)


def _pct(num: float, den: float) -> float | None:
    return round(num * 100.0 / den, 2) if den else None


async def _clocked_minutes(employee_ids: list[int], start: datetime, end: datetime) -> dict[int, int]:
    """Each Employee's Clock events clipped to [start, end], an open one
    running to now, rounded up to the minute: the Timesheet's worked time
    (`shifts_api.timesheet`, no call for this: owner-only, at most 42 days,
    and it reads Shifts too)."""
    if not employee_ids:
        return {}
    now = datetime.utcnow()
    async with get_session() as s:
        events = (await s.execute(
            select(ClockEvent.employee_id, ClockEvent.in_utc, ClockEvent.out_utc)
            .where(ClockEvent.employee_id.in_(employee_ids), ClockEvent.in_utc <= end,
                   or_(ClockEvent.out_utc.is_(None), ClockEvent.out_utc > start)))).all()
    seconds: dict[int, float] = {}
    for eid, lo, hi in events:
        worked = (min(hi or now, end) - max(lo, start)).total_seconds()
        if worked > 0:
            seconds[eid] = seconds.get(eid, 0.0) + worked
    return {eid: minutes_up(sec) for eid, sec in seconds.items()}


@router.get("/admin/stats/chatting-stats")
async def chatting_stats(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    chatter_only: bool = Query(False),
    bucket: str | None = Query(None, pattern="^(hour|day|week|month)$"),
) -> dict[str, Any]:
    """Employee reports' Chatting statistics (roadmap W5 5.2): one row per
    Employee, with the Creators it worked on (`per_account[]`), of Infloww's
    chatting metrics over the window (the last 30 days when unbounded).

      • sales_cents, ppv_sales_cents, tip_sales_cents — the sales credited
        by the Sales Settings rules, as `per_employee`'s revenue
      • direct_message_sales_cents, mass_message_sales_cents,
        priority_mass_message_sales_cents — the sales of the messages
        credited to the Employee, direct, in a mass message or in a Priority
        mass message (`msg_stats.channel_sales`)
      • direct_messages_sent, direct_ppvs_sent, ppvs_unlocked,
        character_count, fans_chatted — its own sends (`msg_stats.send_stats`);
        fans chatted add up each Creator's distinct fans
      • fans_who_spent, avg_spend_per_fan_cents — the fans who paid its
        direct messages or tipped in its chats, and their direct and tip spend
      • replies, avg_reply_seconds — `msg_stats.reply_stats`
      • golden_ratio, unlock_rate, fan_cvr — percentages, null on a zero base
      • clocked_minutes and the per-clocked-hour rates of direct and tip
        sales, messages and fans chatted: null with no clocked time, and
        always null for a chatter, as the Timesheet refuses chatters

    The Automation sentinel and the Unattributed sales get no row. Under
    Role enforcement a chatter whose Data scope is not "all" gets only its
    own row (`permissions.scoped_employee_ids`), as `per_employee`, and
    ``chatter_only=true`` keeps the Chatter role's (`permissions.role_holders`).

    `bucket` (hour, day, week or month) answers the charts instead: the
    window's time series (`_chatting_series`), of every Employee in scope
    and of each."""
    import stats
    from chatters import get_request_chatter
    from permissions import scoped_employee_ids
    own = await _only_chatters(await scoped_employee_ids(), chatter_only)
    is_chatter = get_request_user() is None and get_request_chatter() is not None
    zone, week_start = await stats._report_prefs(None)
    end = _parse_date(to, field="to", zone=zone) or datetime.utcnow()
    start = _parse_date(from_, field="from", zone=zone) or end - timedelta(days=30)
    account_ids = clamp_account_filter(None)
    if bucket is not None:
        return await _chatting_series(bucket, start=start, end=end, zone=zone, week_start=week_start, own=own,
                                      account_ids=account_ids)

    async def _read(fn: Any) -> Any:
        async with get_session() as ss:
            return await fn(ss, account_ids=account_ids, start=start, end=end)

    sends, replies, channels, (credited, fallback), auto = await asyncio.gather(
        _read(msg_stats.send_stats), _read(msg_stats.reply_stats), _read(msg_stats.channel_sales),
        credited_sales(account_ids, start, end, grouped=True), msg_stats.automation_id())

    cells: dict[tuple[int, str], dict[str, Any]] = {}

    def _cell(eid: int | None, aid: str) -> dict[str, Any] | None:
        if not _shown(eid, auto, own):
            return None
        return cells.setdefault((int(eid), aid), {**dict.fromkeys(_CHAT_COUNTS, 0), "chat_tip_cents": 0,
                                                  "reply_seconds": 0.0})

    for r in sends:
        if (c := _cell(r.employee_id, r.account_id)) is not None:
            c.update(direct_messages_sent=int(r.messages), direct_ppvs_sent=int(r.ppvs or 0),
                     ppvs_unlocked=int(r.unlocked or 0), character_count=int(r.chars or 0),
                     fans_chatted=int(r.fans))
    for r in replies:
        if (c := _cell(r.employee_id, r.account_id)) is not None:
            c.update(replies=int(r.replies), reply_seconds=float(r.reply_seconds or 0))
    for r in channels:
        if (c := _cell(r.employee_id, r.account_id)) is not None:
            c.update(direct_message_sales_cents=r.direct_cents, mass_message_sales_cents=r.mass_cents,
                     priority_mass_message_sales_cents=r.priority_cents, chat_tip_cents=r.tip_cents,
                     fans_who_spent=r.spenders)
    for cs in credited:
        if (c := _cell(cs.employee_id, cs.account_id)) is not None:
            c["sales_cents"] += cs.amount_cents
            c["ppv_sales_cents"] += cs.amount_cents if cs.kind in PPV_KINDS else 0
            c["tip_sales_cents"] += cs.amount_cents if cs.kind in TIP_KINDS else 0

    emp_ids = sorted({eid for eid, _ in cells})
    async with get_session() as s:
        names = dict((await s.execute(select(Employee.id, Employee.display_name)
                                      .where(Employee.id.in_(emp_ids)))).all()) if emp_ids else {}
        nicks = dict((await s.execute(select(Account.id, Account.nickname)
                                      .where(Account.id.in_({aid for _, aid in cells})))).all()) if cells else {}
    clocked = {} if is_chatter else await _clocked_minutes(emp_ids, start, end)

    by_emp: dict[int, dict[str, Any]] = {}
    for (eid, aid), c in sorted(cells.items(), key=lambda kv: -kv[1]["sales_cents"]):
        row = by_emp.setdefault(eid, {"employee_id": eid, "display_name": names.get(eid), "per_account": [],
                                      **dict.fromkeys(c, 0)})
        for k, v in c.items():
            row[k] += v
        row["per_account"].append({"account_id": aid, "account_nickname": nicks.get(aid)})
    out = []
    for eid, row in by_emp.items():
        tips, seconds = row.pop("chat_tip_cents"), row.pop("reply_seconds")
        spent = row["direct_message_sales_cents"] + tips
        minutes = None if is_chatter else clocked.get(eid, 0)

        def hourly(n: float, minutes: int | None = minutes) -> float | None:
            return round(n * 60 / minutes, 2) if minutes else None
        out.append({
            **row,
            "golden_ratio": _pct(row["direct_ppvs_sent"], row["direct_messages_sent"]),
            "unlock_rate": _pct(row["ppvs_unlocked"], row["direct_ppvs_sent"]),
            "fan_cvr": _pct(row["fans_who_spent"], row["fans_chatted"]),
            "avg_spend_per_fan_cents": spent // row["fans_who_spent"] if row["fans_who_spent"] else None,
            "avg_reply_seconds": round(seconds / row["replies"]) if row["replies"] else None,
            "clocked_minutes": minutes,
            "sales_per_clocked_hour_cents": int(spent * 60 // minutes) if minutes else None,
            "messages_per_clocked_hour": hourly(row["direct_messages_sent"]),
            "fans_chatted_per_clocked_hour": hourly(row["fans_chatted"]),
        })
    out.sort(key=lambda x: x["sales_cents"], reverse=True)
    return {"employees": out, "attribution_fallback": fallback}


# A chart point's figures: Sales, and Message statistics' four lines.
_SERIES = ("sales_cents", "direct_messages_sent", "direct_ppvs_sent", "ppvs_unlocked", "fans_chatted")


async def _chatting_series(bucket: str, *, start: datetime, end: datetime, zone: ZoneInfo | None,
                           week_start: str, own: set[int] | None, account_ids: list[str] | None) -> dict[str, Any]:
    """Employee reports' charts (roadmap W5 5.10, Infloww's Overview and
    Employee performance tabs): `series`, one point per `bucket` of the
    report zone, `start` its local wall time ("YYYY-MM-DDTHH:MM"), with
      • sales_cents — the sales credited by the Sales Settings rules, as
        Chatting statistics' Sales (every tracked status, pending too)
      • direct_messages_sent, direct_ppvs_sent, ppvs_unlocked, fans_chatted —
        Chatting statistics' own sends, fans distinct per Creator and
        Employee within the point
    summed over the Employees Chatting statistics show (`_shown`: the Data
    scope's), and `by_employee`, each one's points (no `start`: the same
    buckets in order). Weeks begin on `week_start`. 400 on a granularity the
    range's calendar days do not allow (`stats_window.bucket_allowed`)."""
    days = stats_window.range_days(start, end)
    if not stats_window.bucket_allowed(bucket, days):
        raise HTTPException(status_code=400, detail=f"Shown by {bucket} does not fit a {days}-day range")
    edges = stats_window.bucket_edges(bucket, start, end, zone, week_start)
    by = "hour" if tx_rollup.whole_hours(zone, start, end) else "minute"

    async def _sends() -> list[Any]:
        async with get_session() as ss:
            return await msg_stats.send_stats(ss, account_ids=account_ids, start=start, end=end, edges=edges)

    sends, (credited, fallback), auto = await asyncio.gather(
        _sends(), credited_sales(account_ids, start, end, grouped=True, bucket=by), msg_stats.automation_id())
    tz = zone or timezone.utc
    points, by_employee = fold_series(edges, sends, credited, auto, own, tz)
    return {"bucket": bucket, "series": points, "by_employee": by_employee, "attribution_fallback": fallback}


def fold_series(edges: list[datetime], sends: list[Any], credited: list[Any], auto: int | None,
                own: set[int] | None, tz: tzinfo) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, int]]]]:
    """`_chatting_series`' fold, pure: the points, one per bucket of `edges`
    (naive UTC, ascending), each's `start` its wall time in `tz`, and each
    Employee's points keyed by its id as a string, in id order. A send names
    its bucket (`r.bucket`); a credited sale lands in the last bucket starting
    at or before `occurred_at` (`bisect`; the first for one before every
    edge), none without it. Only the Employees `_shown` counts: no
    Unattributed (None), no Automation sentinel `auto`, only `own` when the
    Data scope narrows."""
    points = [{"start": e.replace(tzinfo=timezone.utc).astimezone(tz).strftime("%Y-%m-%dT%H:%M"),
               **dict.fromkeys(_SERIES, 0)} for e in edges]
    by_emp: dict[int, list[dict[str, int]]] = {}

    def _add(eid: int, i: int, **figures: int) -> None:
        own_points = by_emp.setdefault(eid, [dict.fromkeys(_SERIES, 0) for _ in edges])
        for k, v in figures.items():
            own_points[i][k] += v
            points[i][k] += v
    for r in sends:
        if _shown(r.employee_id, auto, own):
            _add(int(r.employee_id), r.bucket, direct_messages_sent=int(r.messages), direct_ppvs_sent=int(r.ppvs or 0),
                 ppvs_unlocked=int(r.unlocked or 0), fans_chatted=int(r.fans))
    for cs in credited:
        if _shown(cs.employee_id, auto, own) and cs.occurred_at is not None:
            _add(int(cs.employee_id), max(0, bisect.bisect_right(edges, cs.occurred_at) - 1),
                 sales_cents=cs.amount_cents)
    return points, {str(k): v for k, v in sorted(by_emp.items())}
