# Why triggers: a trigger runs inside each writer's own transaction, so no writer can forget it and the stored answer is never stale.
# The stored credit is Converters' answer under the default window (what the rollups sum); a Creator under another window is read sale by sale from the touch columns in the read path.
# Rollups cover rows whose credit is set (credit_rule NULL is pending until backfill). A whole-hour zone buckets by UTC hours so a DST change moves no sale across a day edge; any other zone falls back to ledger rows by minute.
from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

log = logging.getLogger("of-relay.tx_rollup")

CONVERTERS_WINDOW_DEFAULT_S = 3600
CONVERTERS_WINDOW_MIN_S = 60
CONVERTERS_WINDOW_MAX_S = 999 * 3600 + 59 * 60

_REVENUE = "('ppv', 'ppv_message', 'ppv_post', 'ppv_stream', 'tip', 'tip_post', 'tip_stream', 'custom')"


def _shift(ts: str, seconds: int) -> str:
    return f"strftime('%Y-%m-%d %H:%M:%f', {ts}, '{seconds:+d} seconds')"


def within_window(occurred_at: datetime | None, converter_at: datetime | None, window_s: int) -> bool:
    if occurred_at is None or converter_at is None:
        return False
    return occurred_at - converter_at <= timedelta(seconds=window_s)


# planner_hint writes +m.direction to keep a per-fan lookup off ix_messages_dir_created: with no sqlite_stat1 SQLite otherwise walks every outbound message of the window per sale.
def human_send(m: str, *, planner_hint: bool = False) -> str:
    return (f"{'+' if planner_hint else ''}{m}.direction = 'out' AND {m}.sent_by_employee_id IS NOT NULL "
            f"AND {m}.mass_run_id IS NULL AND {m}.automation_kind IS NULL "
            f"AND {m}.sent_by_employee_id NOT IN "
            "(SELECT e.id FROM employees e WHERE e.display_name = 'Automation' AND e.is_active = 0)")


def converter_lookback(t: str) -> str:
    return (f"FROM messages m WHERE m.account_id = {t}.account_id AND m.fan_id = {t}.fan_id "
            f"AND {human_send('m', planner_hint=True)} AND m.created_at <= {t}.occurred_at "
            f"AND m.created_at >= {_shift(f'{t}.occurred_at', -CONVERTERS_WINDOW_MAX_S)} "
            "ORDER BY m.created_at DESC, m.message_id DESC LIMIT 1")


_LINKED = ("FROM messages m WHERE m.account_id = transactions.account_id "
           "AND m.fan_id = transactions.fan_id AND m.message_id = transactions.message_id")
_CONVERTER = converter_lookback("transactions")
_IS_REVENUE = f"transactions.kind IN {_REVENUE}"
_IN_DEFAULT = (f"{_shift('transactions.credit_converter_at', 0)} >= "
               f"{_shift('transactions.occurred_at', -CONVERTERS_WINDOW_DEFAULT_S)}")

_SET_TOUCH = (
    "UPDATE transactions SET "
    f"credit_sender_id = (SELECT m.sent_by_employee_id {_LINKED}), "
    f"credit_automation_kind = (SELECT m.automation_kind {_LINKED}), "
    f"credit_converter_id = CASE WHEN {_IS_REVENUE} THEN (SELECT m.sent_by_employee_id {_CONVERTER}) END, "
    f"credit_converter_at = CASE WHEN {_IS_REVENUE} THEN (SELECT m.created_at {_CONVERTER}) END "
)
_SET_CREDIT = (
    "UPDATE transactions SET "
    "credit_employee_id = COALESCE(transactions.attributed_employee_id, "
    f"CASE WHEN {_IN_DEFAULT} THEN transactions.credit_converter_id END), "
    "credit_rule = CASE WHEN transactions.attributed_employee_id IS NOT NULL THEN 'manual' "
    f"WHEN {_IN_DEFAULT} THEN 'converters' ELSE 'unassigned' END "
)


def _credit(where: str) -> list[str]:
    return [_SET_TOUCH + where, _SET_CREDIT + where]


def _recredit_for_message(r: str) -> list[str]:
    return (_credit(f"WHERE account_id = {r}.account_id AND fan_id = {r}.fan_id "
                    f"AND message_id = {r}.message_id")
            + _credit(f"WHERE {human_send(r)} AND account_id = {r}.account_id AND fan_id = {r}.fan_id "
                      f"AND kind IN {_REVENUE} AND occurred_at >= {r}.created_at "
                      f"AND occurred_at <= {_shift(f'{r}.created_at', CONVERTERS_WINDOW_MAX_S)}"))


# An occurred_at SQLite cannot parse buckets as '' rather than failing the write (the bucket is part of the NOT NULL primary key).
_GRAINS = {
    "tx_hourly": ("hour", "COALESCE(strftime('%Y-%m-%d %H:00:00', {}), '')"),
    "tx_daily": ("day", "COALESCE(date({}), '')"),
}
_SUMS = ("gross_cents", "net_cents", "net_missing", "net_or_80_cents", "sales", "fee_cents", "vat_cents")


def net_or_80_sql(row: str | None = None) -> str:
    # "Exclude the 20% OnlyFans fee": net_cents, else 80% of amount_cents rounded down as Python's `//`.
    p = f"{row}." if row else ""
    return f"COALESCE({p}net_cents, ({p}amount_cents * 8 - ((({p}amount_cents * 8) % 10) + 10) % 10) / 10)"


def _key(table: str) -> tuple[str, ...]:
    return ("account_id", _GRAINS[table][0], "kind", "status", "linked", "employee_id", "rule", "automation_kind")


def _upsert(table: str, r: str, sign: str) -> str:
    return (
        f"INSERT INTO {table} ({', '.join(_key(table) + _SUMS)}) SELECT "
        f"{r}.account_id, {_GRAINS[table][1].format(f'{r}.occurred_at')}, {r}.kind, {r}.status, "
        f"{r}.message_id IS NOT NULL, COALESCE({r}.credit_employee_id, 0), {r}.credit_rule, "
        f"COALESCE({r}.credit_automation_kind, ''), "
        f"{sign}{r}.amount_cents, {sign}COALESCE({r}.net_cents, 0), {sign}({r}.net_cents IS NULL), "
        f"{sign}{net_or_80_sql(r)}, {sign}1, {sign}COALESCE({r}.fee_cents, 0), "
        f"{sign}COALESCE({r}.vat_cents, 0) WHERE {r}.credit_rule IS NOT NULL "
        f"ON CONFLICT ({', '.join(_key(table))}) DO UPDATE SET "
        + ", ".join(f"{c} = {c} + excluded.{c}" for c in _SUMS)
    )


def _drop_empty(table: str, r: str) -> str:
    # Run after all of a trigger's writes: nested triggers may take a sale back from a bucket before another adds it there, so no emptied bucket is left.
    bucket, expr = _GRAINS[table]
    return (f"DELETE FROM {table} WHERE sales = 0 AND account_id = {r}.account_id "
            f"AND {bucket} = {expr.format(f'{r}.occurred_at')} AND kind = {r}.kind "
            f"AND status = {r}.status AND linked = ({r}.message_id IS NOT NULL) "
            f"AND employee_id = COALESCE({r}.credit_employee_id, 0) AND rule = {r}.credit_rule "
            f"AND automation_kind = COALESCE({r}.credit_automation_kind, '')")


def _changed(cols: Iterable[str]) -> str:
    return " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in cols)


_CREDIT_KEYS = ("account_id", "fan_id", "kind", "message_id", "occurred_at", "attributed_employee_id")
_ROLLUP_COLS = ("account_id", "occurred_at", "kind", "status", "message_id", "amount_cents", "net_cents",
                "fee_cents", "vat_cents", "credit_employee_id", "credit_rule", "credit_automation_kind")
_MSG_COLS = ("account_id", "fan_id", "message_id", "direction", "created_at", "sent_by_employee_id",
             "automation_kind", "mass_run_id")

# No trigger relies on another's firing order.
TRIGGERS: dict[str, str] = {
    "trg_tx_credit_ins": ("AFTER INSERT ON transactions BEGIN "
                          + "; ".join(_upsert(t, "NEW", "+") for t in _GRAINS) + "; "
                          + "; ".join(_credit("WHERE id = NEW.id")) + "; END"),
    "trg_tx_credit_upd": (f"AFTER UPDATE OF {', '.join(_CREDIT_KEYS)} ON transactions "
                          f"WHEN {_changed(_CREDIT_KEYS)} BEGIN "
                          + "; ".join(_credit("WHERE id = NEW.id")) + "; END"),
    "trg_msg_credit_ins": "AFTER INSERT ON messages BEGIN "
                          + "; ".join(_recredit_for_message("NEW")) + "; END",
    "trg_msg_credit_upd": (f"AFTER UPDATE OF {', '.join(_MSG_COLS)} ON messages "
                           f"WHEN {_changed(_MSG_COLS)} BEGIN "
                           + "; ".join(_recredit_for_message("OLD") + _recredit_for_message("NEW")) + "; END"),
    "trg_msg_credit_del": "AFTER DELETE ON messages BEGIN "
                          + "; ".join(_recredit_for_message("OLD")) + "; END",
    "trg_tx_rollup_upd": (f"AFTER UPDATE OF {', '.join(_ROLLUP_COLS)} ON transactions "
                          f"WHEN {_changed(_ROLLUP_COLS)} BEGIN "
                          + "; ".join(f"{_upsert(t, 'OLD', '-')}; {_upsert(t, 'NEW', '+')}; "
                                      f"{_drop_empty(t, 'OLD')}; {_drop_empty(t, 'NEW')}" for t in _GRAINS)
                          + "; END"),
    "trg_tx_rollup_del": ("AFTER DELETE ON transactions BEGIN "
                          + "; ".join(f"{_upsert(t, 'OLD', '-')}; {_drop_empty(t, 'OLD')}" for t in _GRAINS)
                          + "; END"),
}
_OURS = "(name GLOB 'trg_tx_*' OR name GLOB 'trg_msg_credit_*')"

_BACKFILL = "20261027_tx_credit_converters"
_CHUNK = 20_000


def _ledger_buckets(table: str) -> str:
    bucket, expr = _GRAINS[table]
    return (
        f"SELECT account_id, {expr.format('occurred_at')} AS {bucket}, kind, status, "
        "message_id IS NOT NULL AS linked, COALESCE(credit_employee_id, 0) AS employee_id, "
        "credit_rule AS rule, COALESCE(credit_automation_kind, '') AS automation_kind, "
        "SUM(amount_cents) AS gross_cents, SUM(COALESCE(net_cents, 0)) AS net_cents, "
        f"SUM(net_cents IS NULL) AS net_missing, SUM({net_or_80_sql()}) AS net_or_80_cents, "
        "COUNT(*) AS sales, SUM(COALESCE(fee_cents, 0)) AS fee_cents, SUM(COALESCE(vat_cents, 0)) AS vat_cents "
        "FROM transactions WHERE credit_rule IS NOT NULL GROUP BY 1, 2, 3, 4, 5, 6, 7, 8")


@contextmanager
def _immediate(sync_engine) -> Iterator[Any]:
    with sync_engine.connect() as conn:
        # Explicit: Python's sqlite3 opens its implicit transaction only before DML, so each DROP/CREATE TRIGGER would otherwise commit on its own.
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        yield conn
        conn.commit()


def _install(conn) -> int:
    have = dict(conn.execute(text(f"SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND {_OURS}")).all())
    touched = 0
    for name in have.keys() - TRIGGERS.keys():
        conn.execute(text(f"DROP TRIGGER {name}"))
        touched += 1
    for name, body in TRIGGERS.items():
        sql = f"CREATE TRIGGER {name} {body}"
        if have.get(name) != sql:
            if name in have:
                conn.execute(text(f"DROP TRIGGER {name}"))
            conn.execute(text(sql))
            touched += 1
    return touched


def _credit_chunk(conn, lo: int, hi: int) -> None:
    for stmt in _credit("WHERE id >= :lo AND id < :hi"):
        conn.execute(text(stmt), {"lo": lo, "hi": hi})


def backfill(sync_engine) -> bool:
    with sync_engine.connect() as conn:
        if conn.execute(text("SELECT 1 FROM data_migrations WHERE name = :n"), {"n": _BACKFILL}).first():
            return False
        lo, hi = conn.execute(text("SELECT MIN(id), MAX(id) FROM transactions")).one()
    started = time.monotonic()
    if lo is not None:
        for at in range(lo, hi + 1, _CHUNK):
            with _immediate(sync_engine) as conn:
                _credit_chunk(conn, at, at + _CHUNK)
    with _immediate(sync_engine) as conn:
        for table in _GRAINS:
            conn.execute(text(f"DELETE FROM {table}"))
            conn.execute(text(f"INSERT INTO {table} ({', '.join(_key(table) + _SUMS)}) {_ledger_buckets(table)}"))
        conn.execute(text("INSERT INTO data_migrations (name) VALUES (:n)"), {"n": _BACKFILL})
    log.info("tx credit + rollups backfilled in %.1fs", time.monotonic() - started)
    return True


def ensure(sync_engine) -> bool:
    from db.engine import _DATA_MIGRATIONS_DDL

    with _immediate(sync_engine) as conn:
        conn.execute(text(_DATA_MIGRATIONS_DDL))
        if touched := _install(conn):
            log.info("tx credit + rollup triggers: %d installed or replaced", touched)
    ran = backfill(sync_engine)
    with sync_engine.connect() as conn:
        if dirty := conn.execute(text("SELECT SUM(sales) FROM tx_hourly WHERE hour = ''")).scalar():
            log.warning("%d sale(s) have an occurred_at SQLite cannot parse: counted in no hour or day", dirty)
    return ran


def credit_mismatches(conn, limit: int = 20) -> list[Any]:
    pairs = (("sent_by_employee_id", "credit_employee_id"), ("rule", "credit_rule"),
             ("automation_kind", "credit_automation_kind"), ("sender_id", "credit_sender_id"),
             ("converter_id", "credit_converter_id"), ("converter_at", "credit_converter_at"))
    return conn.execute(text(
        f"SELECT t.id, {', '.join(f'v.{a}' for a, _ in pairs)}, {', '.join(f't.{b}' for _, b in pairs)} "
        "FROM per_employee_revenue_with_attribution v JOIN transactions t ON t.id = v.tx_id "
        f"WHERE {' OR '.join(f'v.{a} IS NOT t.{b}' for a, b in pairs)} LIMIT :n"), {"n": limit}).all()


def rollup_mismatches(conn) -> list[Any]:
    out: list[Any] = []
    for table in _GRAINS:
        raw, cols = _ledger_buckets(table), ", ".join(_key(table) + _SUMS)
        out += conn.execute(text(
            f"SELECT 'ledger', '{table}', * FROM ({raw} EXCEPT SELECT {cols} FROM {table}) "
            f"UNION ALL SELECT 'rollup', '{table}', * FROM (SELECT {cols} FROM {table} EXCEPT {raw})")).all()
    return out



_DIMS = {
    "account_id": ("account_id", "account_id"),
    "kind": ("kind", "kind"),
    "status": ("status", "status"),
    "linked": ("linked", "message_id IS NOT NULL"),
    "employee_id": ("NULLIF(employee_id, 0)", "NULLIF(credit_employee_id, 0)"),
    "rule": ("rule", "credit_rule"),
    "automation_kind": ("NULLIF(automation_kind, '')", "credit_automation_kind"),
}
MEASURES = {
    "gross_cents": ("SUM(gross_cents)", "SUM(amount_cents)"),
    "net_cents": ("SUM(net_cents)", "SUM(COALESCE(net_cents, 0))"),
    "net_missing": ("SUM(net_missing)", "SUM(net_cents IS NULL)"),
    "net_or_80_cents": ("SUM(net_or_80_cents)", f"SUM({net_or_80_sql()})"),
    "sales": ("SUM(sales)", "COUNT(*)"),
    # OF's own fee and VAT per sale, 0 where the row has none (a WS-pumped sale the ledger has not backfilled: net_missing counts those).
    "fee_cents": ("SUM(fee_cents)", "SUM(COALESCE(fee_cents, 0))"),
    "vat_cents": ("SUM(vat_cents)", "SUM(COALESCE(vat_cents, 0))"),
}
TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


class Binds(dict):

    def bind(self, value: Any) -> str:
        key = f"p{len(self)}"
        self[key] = value
        return f":{key}"

    def in_(self, expr: str, values: Sequence[Any]) -> str:
        return f"{expr} IN ({', '.join(self.bind(v) for v in values) or 'NULL'})"


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


async def window_sums(s, dims: Sequence[str], *, account_ids: list[str] | None, start: datetime | None,
                      end: datetime | None, where: dict[str, Sequence[Any]] | None = None,
                      bucket: str | None = None) -> list[Any]:
    params = Binds()
    scope: list[list[str]] = [[], []]
    for side in (0, 1):
        if account_ids is not None:
            scope[side].append(params.in_("account_id", account_ids))
        scope[side] += [params.in_(_DIMS[d][side], values) for d, values in (where or {}).items()]

    def _select(table: str, extra: list[str]) -> str:
        side = int(table == "transactions")
        cols = [f"{_DIMS[d][side]} AS {d}" for d in dims]
        if bucket == "hour":
            cols.append("hour AS bucket" if side == 0 else "strftime('%Y-%m-%d %H:00:00', occurred_at) AS bucket")
        elif bucket == "minute":
            cols.append("strftime('%Y-%m-%d %H:%M:00', occurred_at) AS bucket")
        cols += [f"{MEASURES[m][side]} AS {m}" for m in MEASURES]
        conds = list(extra) + scope[side]
        groups = list(dims) + (["bucket"] if bucket else [])
        return (f"SELECT {', '.join(cols)} FROM {table}"
                + (f" WHERE {' AND '.join(conds)}" if conds else "")
                + (f" GROUP BY {', '.join(groups)}" if groups else ""))

    def _span(table: str, lo: datetime | None, hi: datetime | None) -> None:
        col, fmt = _GRAINS[table][0], ("%Y-%m-%d %H:00:00" if table == "tx_hourly" else "%Y-%m-%d")
        conds = [] if lo is None else [f"{col} >= {params.bind(lo.strftime(fmt))}"]
        conds += [] if hi is None else [f"{col} < {params.bind(hi.strftime(fmt))}"]
        parts.append(_select(table, conds))

    h0 = None if start is None else _floor_hour(start + timedelta(hours=1) - timedelta(microseconds=1))
    h1 = None if end is None else _floor_hour(end + timedelta(microseconds=1))
    s_ = None if start is None else f"occurred_at >= {params.bind(start.strftime(TS_FORMAT))}"
    e_ = None if end is None else f"occurred_at <= {params.bind(end.strftime(TS_FORMAT))}"
    parts: list[str] = []
    if bucket == "minute" or (h0 is not None and h1 is not None and h0 >= h1):
        parts.append(_select("transactions", [c for c in (s_, e_) if c]))
    else:
        if h0 is not None:
            parts.append(_select("transactions", [s_, f"occurred_at < {params.bind(h0.strftime(TS_FORMAT))}"]))
        if h1 is not None:
            parts.append(_select("transactions", [f"occurred_at >= {params.bind(h1.strftime(TS_FORMAT))}", e_]))
        d0 = None if h0 is None else (h0 + timedelta(hours=23)).replace(hour=0)
        d1 = None if h1 is None else h1.replace(hour=0)
        if bucket is None and (d0 is None or d1 is None or d0 < d1):
            if h0 is not None and h0 < d0:
                _span("tx_hourly", h0, d0)
            if h1 is not None and d1 < h1:
                _span("tx_hourly", d1, h1)
            _span("tx_daily", d0, d1)
        else:
            _span("tx_hourly", h0, h1)
    out_dims = list(dims) + (["bucket"] if bucket else [])
    outer = ", ".join(out_dims + [f"SUM({m}) AS {m}" for m in MEASURES])
    sql = (f"SELECT {outer} FROM ({' UNION ALL '.join(parts)})"
           + (f" GROUP BY {', '.join(out_dims)}" if out_dims else ""))
    return (await s.execute(text(sql), params)).all()


def whole_hours(zone: ZoneInfo | None, *instants: datetime | None) -> bool:
    if zone is None:
        return True
    at = [i for i in instants if i is not None] or [datetime.utcnow()]
    probes = at + [datetime(i.year, m, 1) for i in at for m in (1, 7)]
    return all(not p.replace(tzinfo=timezone.utc).astimezone(zone).utcoffset().total_seconds() % 3600
               for p in probes)


def local_days(buckets: Iterable[str | None], zone: ZoneInfo | None, *,
               hourly: bool = True, fmt: str = "%Y-%m-%d") -> dict[str, str] | None:
    out: dict[str, str] = {}
    for b in buckets:
        if not b:
            continue
        at = datetime.fromisoformat(b).replace(tzinfo=timezone.utc)
        if zone is None:
            out[b] = at.strftime(fmt)
            continue
        local = at.astimezone(zone)
        if hourly and local.utcoffset().total_seconds() % 3600:
            return None
        out[b] = local.strftime(fmt)
    return out
