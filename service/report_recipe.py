from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, AsyncIterator, Awaitable, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

import csv_export
import msg_stats
import of_stats_daily
import report_files
import report_recipe_decide as rd
import tx_rollup
import xlsx_io
from agency_context import AgencyContext
from agency_scope import agency_account_ids
from attribution_backfill import TRACKED_STATUSES
from db.engine import get_session
from db.models import Account, Employee, Fan, User, UserAccount
from stats_employees import bucket_of
from stats_window import bucket_edges, parse_bound
from tenant_keys import billable_owners

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_running: set[str] = set()
MAX_FILE_BYTES = report_files.MAX_BYTES_PER_USER


class RecipeError(Exception):

    def __init__(self, errors: dict[str, str], status: int = 400):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors
        self.status = status


@dataclass
class Table:
    columns: list[str]
    rows: list[list[Any]]
    frm: date
    to: date
    tz: str
    dataset: str
    notes: list[str]


@dataclass(frozen=True)
class AgencyScope:
    nicknames: dict[str, str]
    co_owned: frozenset[str]
    employees: dict[int, str]
    zone: ZoneInfo | None
    week_start: str
    today: date


@dataclass
class _Scope:
    ids: list[str]
    start: datetime
    end: datetime
    zone: ZoneInfo | None
    week_start: str
    employees: dict[int, str]


def _zone(name: Any) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if name else None
    except (ValueError, KeyError):
        return None


async def agency_scope(s: AsyncSession, user_id: str, now: datetime) -> AgencyScope:
    from settings_api import applied_blob
    prefs = await applied_blob(s, user_id, "preferences")
    owned = sorted(await agency_account_ids(s, user_id))
    links: dict[str, list[tuple[str, bool]]] = {}
    if owned:
        for aid, uid, is_admin in (await s.execute(
                select(UserAccount.account_id, UserAccount.user_id, User.is_admin)
                .join(User, User.id == UserAccount.user_id).where(UserAccount.account_id.in_(owned)))).all():
            links.setdefault(aid, []).append((uid, bool(is_admin)))
    co_owned = frozenset(a for a, ls in links.items() if any(o != user_id for o in billable_owners(ls)))
    nick = dict((await s.execute(
        select(Account.id, Account.nickname).where(Account.id.in_(owned)))).all()) if owned else {}
    emps = (await s.execute(select(Employee.id, Employee.display_name).where(Employee.user_id == user_id))).all()
    zone = _zone(prefs.get("report_tz"))
    return AgencyScope(nicknames={a: nick.get(a) or a for a in owned}, co_owned=co_owned,
                       employees={int(i): nm or f"Employee {i}" for i, nm in emps}, zone=zone,
                       week_start=prefs.get("week_start") or "monday", today=rd.today_in(zone, now))


Cells = tuple[list[dict[str, Any]], dict[str, dict[Any, str]], list[str]]


def history_note(gaps: int) -> str:
    return (f"{gaps} Creator-day{'' if gaps == 1 else 's'} before a Creator was added have no OnlyFans figure "
            "stored: totals there are our ledger's only and may be low")


async def _sales(r: rd.Recipe, sc: _Scope) -> Cells:
    import stats
    of_cells, gaps = await of_stats_daily.earnings_window(sc.ids, sc.start, sc.end)
    async with get_session() as s:
        cells = await stats._day_sums(s, ("account_id", "kind"), sc.zone, account_ids=sc.ids, start=sc.start,
                                      end=sc.end, where={"status": TRACKED_STATUSES})
        top = await stats._of_top_ups(s, of_cells, ("account_id", "day"))
    if top:
        cells = stats._plus(cells, top, ("day", "account_id", "kind"))
    unit = rd.time_unit(r.group_by)
    out = []
    for c in cells:
        kind = rd.sales_kind(c["kind"])
        if r.kinds and kind not in r.kinds:
            continue
        cell = {**c, "creator": c["account_id"], "kind": kind}
        if unit:
            cell[unit] = rd.period_label(c["day"], unit, sc.week_start)
        out.append(cell)
    return out, {}, [history_note(gaps)] if gaps else []


async def _employee_sales(r: rd.Recipe, sc: _Scope) -> Cells:
    from sales_attribution import credited_sales
    bucket = "hour" if tx_rollup.whole_hours(sc.zone, sc.start, sc.end) else "minute"
    sales, fallback = await credited_sales(sc.ids, sc.start, sc.end, grouped=True, bucket=bucket)
    unit = rd.time_unit(r.group_by)
    edges = bucket_edges(unit, sc.start, sc.end, sc.zone, sc.week_start) if unit else []
    out = []
    for c in sales:
        eid = c.employee_id or None
        if eid is not None and eid not in sc.employees:
            continue
        if r.employees and eid not in r.employees:
            continue
        kind = rd.ledger_kind(c.kind)
        if r.kinds and kind not in r.kinds:
            continue
        cell = {"employee": eid, "creator": c.account_id, "kind": kind, "amount_cents": c.amount_cents,
                "sales": c.sales}
        if unit:
            if c.occurred_at is None:
                continue
            cell[unit] = rd.edge_label(edges[bucket_of(edges, c.occurred_at)], sc.zone, unit)
        out.append(cell)
    return out, {}, [fallback] if fallback else []


async def _chat_activity(r: rd.Recipe, sc: _Scope) -> Cells:
    unit = rd.time_unit(r.group_by)
    edges = bucket_edges(unit, sc.start, sc.end, sc.zone, sc.week_start) if unit else None
    async with get_session() as s:
        rows = await msg_stats.send_stats(s, account_ids=sc.ids, start=sc.start, end=sc.end, edges=edges)
    out = []
    for row in rows:
        if row.employee_id not in sc.employees or (r.employees and row.employee_id not in r.employees):
            continue
        cell = {"employee": row.employee_id, "creator": row.account_id, "messages": int(row.messages or 0),
                "ppvs": int(row.ppvs or 0), "unlocked": int(row.unlocked or 0), "chars": int(row.chars or 0)}
        if unit:
            cell[unit] = rd.edge_label(edges[int(row.bucket)], sc.zone, unit)
        out.append(cell)
    return out, {}, []


async def _fan_spend(r: rd.Recipe, sc: _Scope) -> Cells:
    from stats_fans import fan_spend_q
    ds = rd.CATALOGUE["fan_spend"]
    spend = fan_spend_q(sc.ids, sc.start, sc.end,
                        kinds=rd.ledger_kinds(r.kinds) if r.kinds else None).subquery()
    by = rd.sort_key(r)
    q = (select(spend, Fan.of_display_name, Fan.of_username)
         .outerjoin(Fan, and_(Fan.account_id == spend.c.account_id, Fan.fan_id == spend.c.fan_id))
         .order_by(spend.c[ds.metrics[by].source[0]].desc(), spend.c.total_cents.desc(), spend.c.fan_id)
         .limit(min(r.limit or rd.MAX_LIMIT + 1, rd.MAX_LIMIT + 1)))
    async with get_session() as s:
        rows = (await s.execute(q)).all()
    out, fans = [], {}
    for row in rows:
        key = (row.account_id, int(row.fan_id))
        fans[key] = row.of_display_name or (f"@{row.of_username}" if row.of_username else f"fan {row.fan_id}")
        out.append({"creator": row.account_id, "fan": key,
                    **{k: int(getattr(row, k) or 0) for k in
                       ("total_cents", "net_or_80_cents", "tips_cents", "ppv_cents", "subs_cents")}})
    return out, {"fan": fans}, []


ENGINES: dict[str, Callable[[rd.Recipe, _Scope], Awaitable[Cells]]] = {
    "sales": _sales, "employee_sales": _employee_sales, "chat_activity": _chat_activity, "fan_spend": _fan_spend}


async def table(ctx: AgencyContext, raw: Any, *, now: datetime | None = None) -> Table:
    recipe, errors = rd.parse_recipe(raw)
    if recipe is None:
        raise RecipeError(errors)
    async with get_session() as s:
        ag = await agency_scope(s, ctx.agency_user_id, now or datetime.utcnow())
    days, err = rd.resolve_window(recipe, ag.today, ag.week_start)
    if days is None:
        raise RecipeError({"window": err})
    ids, err = rd.clamp_creators(recipe.creators, set(ag.nicknames), co_owned=ag.co_owned,
                                 refuse_co_owned=rd.CATALOGUE[recipe.dataset].refuses_co_owned)
    if ids is None:
        raise RecipeError({"creators": err})
    if foreign := [e for e in recipe.employees if e not in ag.employees]:
        raise RecipeError({"employees": f"not one of your Employees: {foreign[0]}"})
    frm, to = days
    zone = ag.zone
    sc = _Scope(ids=ids, start=parse_bound(frm.isoformat(), "from", zone), end=parse_bound(to.isoformat(), "to", zone),
                zone=zone, week_start=ag.week_start, employees=ag.employees)
    names: dict[str, dict[Any, str]] = {"creator": dict(ag.nicknames), "employee": dict(ag.employees)}
    cells: list[dict[str, Any]] = []
    notes: list[str] = []
    if ids:
        cells, more, notes = await ENGINES[recipe.dataset](recipe, sc)
        names.update(more)
    cols, rows = rd.shape(recipe, cells, names)
    return Table(columns=cols, rows=rows, frm=frm, to=to, tz=zone.key if zone else "UTC",
                 dataset=recipe.dataset, notes=notes)


async def _aiter(rows: list[list[Any]]) -> AsyncIterator[list[Any]]:
    for row in rows:
        yield row


def _cell(v: Any) -> Any:
    return "" if v is None else v


def _note_rows(t: Table) -> list[list[Any]]:
    return [[f"# {n}"] + [""] * (len(t.columns) - 1) for n in t.notes]


@dataclass(frozen=True)
class ReportFile:
    filename: str
    media_type: str
    body: bytes


async def _guarded_table(ctx: AgencyContext, recipe: Any, now: datetime | None) -> Table:
    if ctx.agency_user_id in _running:
        raise RecipeError({"run": "a report is already running for your Agency; try again when it ends"}, 429)
    _running.add(ctx.agency_user_id)
    try:
        return await table(ctx, recipe, now=now)
    finally:
        _running.discard(ctx.agency_user_id)


async def build_file(ctx: AgencyContext, recipe: Any, fmt: str, *, now: datetime | None = None) -> ReportFile:
    t = await _guarded_table(ctx, recipe, now)
    name = rd.filename(t.dataset, t.frm, t.to, fmt)
    if fmt == "csv":
        # A POST's StreamingResponse trips the middleware stack (it listens for a disconnect on a consumed body).
        chunks, size = [], 0
        async for c in csv_export.stream_csv(_aiter(t.rows), t.columns, lambda r: [_cell(v) for v in r]):
            size += len(c)
            if size > MAX_FILE_BYTES:
                raise _too_large()
            chunks.append(c)
        body = b"".join(chunks)
        if t.notes:
            buf = io.StringIO()
            csv.writer(buf).writerows(_note_rows(t))
            body += buf.getvalue().encode("utf-8")
    else:
        cap = csv_export.CSV_MAX_ROWS
        rows = [[_cell(v) for v in r] for r in t.rows[:cap]]
        if len(t.rows) > cap:
            rows.append([csv_export.TRUNCATED_LINE] + [""] * (len(t.columns) - 1))
        body = xlsx_io.write_xlsx([t.columns, *rows, *_note_rows(t)], "Report")
    if len(body) > MAX_FILE_BYTES:
        raise _too_large()
    return ReportFile(name, "text/csv" if fmt == "csv" else XLSX_TYPE, body)


def _too_large() -> RecipeError:
    return RecipeError({"file": f"report file over {MAX_FILE_BYTES // (1024 * 1024)} MB; narrow the window, "
                                "the Creators or the rows"}, 413)


async def run(ctx: AgencyContext, recipe: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """The recipe's report as json `{columns, rows (at most 200), row_count, truncated,
    window{from,to,tz}, notes}`; files: `build_file`."""
    t = await _guarded_table(ctx, recipe, now)
    return {"columns": t.columns, "rows": t.rows[:rd.JSON_MAX_ROWS], "row_count": len(t.rows),
            "truncated": len(t.rows) > rd.JSON_MAX_ROWS,
            "window": {"from": t.frm.isoformat(), "to": t.to.isoformat(), "tz": t.tz}, "notes": t.notes}
