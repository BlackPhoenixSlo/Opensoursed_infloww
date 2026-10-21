"""tx_rollup — attribution materialised on `transactions`, and the hourly and
daily rollups `tx_hourly` / `tx_daily`, kept exact by SQLite triggers (roadmap
W2 2.1, 2.2).

Why triggers. A sale's credit depends on rows several writers touch: the
ledger ingest, the WS pump, the Fansly ingest, the PPV relink, the orphan
sweep, the owner's reassign, outbound message writes, placeholder adoption.
A trigger runs inside each of those writes' own transaction, so no writer can
forget it and the stored answer is never stale.

1. Attribution (`transactions.credit_employee_id`, `credit_rule`,
   `credit_automation_kind`): the row of the view
   `per_employee_revenue_with_attribution` (revision 0069) for this sale,
   computed per row by the view's own three branches:
     message-linked  the linked message's sender (`message`);
     standalone tip  the 7-day lookback's latest outbound sender (`tip_lookback`);
     otherwise       nobody;
   the manual override `attributed_employee_id` wins every branch (`manual`),
   and a branch that finds nobody is `unassigned`. It is computed for every
   row, any kind or status; readers keep the view's rows (REVENUE_KINDS,
   TRACKED_STATUSES) where they mean the view. The view stays in the schema
   as the oracle `credit_mismatches` checks against.
   Recomputed when the sale's own keys change, and when a message it links to
   or could look back to is inserted, updated or deleted.

2. Rollups (`tx_hourly`, `tx_daily`): every row's money summed per (account,
   UTC hour or day, kind, status, linked, credited Employee, rule, automation
   kind), over the rows whose credit is set (`credit_rule` NULL is pending,
   until the once-per-box `backfill` credits it). Stats bucket UTC hours into
   the report zone's days with zoneinfo per hour, so a daylight-saving change
   moves no sale across a day edge (roadmap S8); a zone whose offset is not a
   whole hour falls back to the ledger rows by minute. `window_sums` reads any window: whole UTC days from `tx_daily`
   (when no hour buckets are asked), whole hours from `tx_hourly`, the partial
   hours at either edge from the ledger rows.

ASSUMPTION: ties in the lookback (two messages at the same `created_at`) break
by the higher message id; the view leaves that order undefined. Rung 5.
Overturned if a tie should credit someone else.
"""
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

_TIPS = "('tip', 'tip_post', 'tip_stream')"

# The view's branches, for the `transactions` row named `transactions`.
# `+m.direction` keeps the lookback off ix_messages_dir_created: with no
# sqlite_stat1, SQLite otherwise picks it (account, direction, created_at) and
# walks every outbound message of the Creator's 7 days for each sale, where
# ix_messages_chat_seq walks one fan's.
_LINKED = ("FROM messages m WHERE m.account_id = transactions.account_id "
           "AND m.fan_id = transactions.fan_id AND m.message_id = transactions.message_id")
_LOOKBACK = ("FROM messages m WHERE m.account_id = transactions.account_id "
             "AND m.fan_id = transactions.fan_id AND +m.direction = 'out' "
             "AND m.sent_by_employee_id IS NOT NULL AND m.created_at <= transactions.occurred_at "
             "AND m.created_at > datetime(transactions.occurred_at, '-7 days') "
             "ORDER BY m.created_at DESC, m.message_id DESC LIMIT 1")
_IS_LINKED = f"(transactions.message_id IS NOT NULL AND EXISTS (SELECT 1 {_LINKED}))"
_IS_TIP = f"(transactions.kind IN {_TIPS} AND transactions.message_id IS NULL)"


def _branch(col: str) -> str:
    return (f"(CASE WHEN {_IS_LINKED} THEN (SELECT m.{col} {_LINKED}) "
            f"WHEN {_IS_TIP} THEN (SELECT m.{col} {_LOOKBACK}) END)")


_AUTO = _branch("sent_by_employee_id")
_SET_CREDIT = (
    "UPDATE transactions SET "
    f"credit_employee_id = COALESCE(transactions.attributed_employee_id, {_AUTO}), "
    "credit_rule = CASE WHEN transactions.attributed_employee_id IS NOT NULL THEN 'manual' "
    f"WHEN {_AUTO} IS NOT NULL THEN (CASE WHEN {_IS_LINKED} THEN 'message' ELSE 'tip_lookback' END) "
    "ELSE 'unassigned' END, "
    f"credit_automation_kind = {_branch('automation_kind')} "
)


def _recredit_for_message(r: str) -> list[str]:
    """Statements recomputing the sales message `r` (NEW or OLD) links to or,
    when it is an Employee's outbound message, could be the lookback of."""
    return [
        _SET_CREDIT + f"WHERE account_id = {r}.account_id AND fan_id = {r}.fan_id "
                      f"AND message_id = {r}.message_id",
        _SET_CREDIT + f"WHERE {r}.direction = 'out' AND {r}.sent_by_employee_id IS NOT NULL "
                      f"AND account_id = {r}.account_id AND fan_id = {r}.fan_id "
                      f"AND message_id IS NULL AND kind IN {_TIPS} "
                      f"AND occurred_at >= {r}.created_at "
                      f"AND occurred_at <= datetime({r}.created_at, '+8 days')",
    ]


# Each rollup table: its time bucket column and that bucket of a timestamp.
# An `occurred_at` SQLite cannot parse buckets as '' rather than failing the
# write (the bucket is part of the primary key, NOT NULL).
_GRAINS = {
    "tx_hourly": ("hour", "COALESCE(strftime('%Y-%m-%d %H:00:00', {}), '')"),
    "tx_daily": ("day", "COALESCE(date({}), '')"),
}
_SUMS = ("gross_cents", "net_cents", "net_missing", "net_or_80_cents", "sales", "fee_cents", "vat_cents")


def net_or_80_sql(row: str | None = None) -> str:
    """SQL of a sale's amount under "Exclude the 20% OnlyFans fee"
    (`sales_attribution.net_or_80`): `net_cents`, else 80% of `amount_cents`
    rounded down as Python's `//`; `row` qualifies the columns."""
    p = f"{row}." if row else ""
    return f"COALESCE({p}net_cents, ({p}amount_cents * 8 - ((({p}amount_cents * 8) % 10) + 10) % 10) / 10)"


def _key(table: str) -> tuple[str, ...]:
    return ("account_id", _GRAINS[table][0], "kind", "status", "linked", "employee_id", "rule", "automation_kind")


def _upsert(table: str, r: str, sign: str) -> str:
    """Add (`+`) or take back (`-`) row `r`'s money in its `table` bucket; a
    row whose credit is pending (`credit_rule` NULL) is in no bucket."""
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
    """Row `r`'s `table` bucket dropped when it holds no sale. Run for every
    bucket a trigger touched, after all its writes, so whatever order nested
    triggers fire in (one may take a sale back from a bucket before another
    adds it there) no emptied bucket is left."""
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
             "automation_kind")

# The rollups hold exactly the rows whose credit is set. A new row enters them
# through its own credit write (trg_tx_credit_ins's UPDATE fires
# trg_tx_rollup_upd, whose OLD half is skipped while OLD.credit_rule is NULL);
# one inserted with its credit already set is added by trg_tx_credit_ins
# itself first. No trigger relies on another's firing order.
TRIGGERS: dict[str, str] = {
    "trg_tx_credit_ins": ("AFTER INSERT ON transactions BEGIN "
                          + "; ".join(_upsert(t, "NEW", "+") for t in _GRAINS) + "; "
                          + _SET_CREDIT + "WHERE id = NEW.id; END"),
    "trg_tx_credit_upd": (f"AFTER UPDATE OF {', '.join(_CREDIT_KEYS)} ON transactions "
                          f"WHEN {_changed(_CREDIT_KEYS)} BEGIN "
                          + _SET_CREDIT + "WHERE id = NEW.id; END"),
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

# Unset on a box: credit every pending row (`credit_rule` NULL: every row the
# columns were added to) and rebuild the rollups from the credited rows. Renamed
# when the rollups gain a sum (was 20261019_tx_credit_rollup; fee and VAT came
# 2026-10-20), so each box rebuilds them once with the new column filled.
_BACKFILL = "20261020_tx_rollup_fee_vat"
_CHUNK = 20_000  # ids per backfill transaction


def _ledger_buckets(table: str) -> str:
    """The credited ledger rows summed into `table`'s buckets, in its column
    order."""
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
    """A connection in one `BEGIN IMMEDIATE` transaction, committed on exit
    and rolled back on error. Explicit, because Python's sqlite3 opens its
    implicit transaction only before DML: each DROP/CREATE TRIGGER would
    otherwise commit on its own."""
    with sync_engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        yield conn
        conn.commit()


def _install(conn) -> int:
    """Create the missing triggers and replace the changed ones (compared by
    their `sqlite_master` text), dropping ours no longer defined. Returns how
    many it touched."""
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
    """Credit the pending rows with `lo <= id < hi`."""
    conn.execute(text(_SET_CREDIT + "WHERE id >= :lo AND id < :hi AND credit_rule IS NULL"), {"lo": lo, "hi": hi})


def backfill(sync_engine) -> bool:
    """Once per box (the `_BACKFILL` marker): credit the pending rows by id
    range, one transaction per chunk, so an interrupted run resumes where it
    stopped; then, in one transaction, rebuild both rollups from the credited
    rows and set the marker. The triggers are already live, so a row written
    meanwhile is credited by them. Returns whether it ran."""
    with sync_engine.connect() as conn:
        if conn.execute(text("SELECT 1 FROM data_migrations WHERE name = :n"), {"n": _BACKFILL}).first():
            return False
        lo, hi = conn.execute(text("SELECT MIN(id), MAX(id) FROM transactions WHERE credit_rule IS NULL")).one()
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
    """Install the triggers in one transaction (creating only the missing or
    changed ones), then `backfill` once per box. Raises on failure; init_db
    logs it critical, boots on, and retries in the background until it
    succeeds (db.engine `_tx_rollup_retry`), so a failed install leaves the
    previous triggers and an interrupted backfill resumes. Returns whether it
    backfilled."""
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
    """Rows where the materialised credit disagrees with the attribution view
    (verification; the view itself scans all history, so not for a request)."""
    return conn.execute(text(
        "SELECT t.id, v.sent_by_employee_id, v.rule, v.automation_kind, "
        "t.credit_employee_id, t.credit_rule, t.credit_automation_kind "
        "FROM per_employee_revenue_with_attribution v JOIN transactions t ON t.id = v.tx_id "
        "WHERE v.sent_by_employee_id IS NOT t.credit_employee_id OR v.rule IS NOT t.credit_rule "
        "OR v.automation_kind IS NOT t.credit_automation_kind LIMIT :n"), {"n": limit}).all()


def rollup_mismatches(conn) -> list[Any]:
    """Buckets where a rollup disagrees with the ledger rows (verification)."""
    out: list[Any] = []
    for table in _GRAINS:
        raw, cols = _ledger_buckets(table), ", ".join(_key(table) + _SUMS)
        out += conn.execute(text(
            f"SELECT 'ledger', '{table}', * FROM ({raw} EXCEPT SELECT {cols} FROM {table}) "
            f"UNION ALL SELECT 'rollup', '{table}', * FROM (SELECT {cols} FROM {table} EXCEPT {raw})")).all()
    return out


# ── Reading ──────────────────────────────────────────────────────────────

# Each logical column: its expression over `tx_hourly` and over `transactions`.
_DIMS = {
    "account_id": ("account_id", "account_id"),
    "kind": ("kind", "kind"),
    "status": ("status", "status"),
    "linked": ("linked", "message_id IS NOT NULL"),
    # 0 is nobody on both sides: the rollups' "none" and the "No one" override (sales_attribution.NO_ONE).
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
    # OnlyFans' own fee and VAT per sale, 0 where the row has none (a WS-pumped
    # sale the ledger has not backfilled: `net_missing` counts those).
    "fee_cents": ("SUM(fee_cents)", "SUM(COALESCE(fee_cents, 0))"),
    "vat_cents": ("SUM(vat_cents)", "SUM(COALESCE(vat_cents, 0))"),
}
TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"  # SQLAlchemy's SQLite DateTime storage format


class Binds(dict):
    """The bound parameters of one `text()` query, named as they are added."""

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
    """Every measure in `MEASURES`, grouped by `dims` (and by `bucket`:
    "hour" = the UTC hour, "minute" = the UTC minute, read from the ledger
    rows), over the sales with `start <= occurred_at <= end` (naive UTC; either
    open) and each `where` dim in its values. Rows carry the dims by name,
    then `bucket` when asked, then the measures."""
    params = Binds()
    # The scope's conditions over the rollups [0] and over the ledger rows [1].
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
        """`table`'s buckets in [lo, hi) (either open)."""
        col, fmt = _GRAINS[table][0], ("%Y-%m-%d %H:00:00" if table == "tx_hourly" else "%Y-%m-%d")
        conds = [] if lo is None else [f"{col} >= {params.bind(lo.strftime(fmt))}"]
        conds += [] if hi is None else [f"{col} < {params.bind(hi.strftime(fmt))}"]
        parts.append(_select(table, conds))

    # Whole UTC days [d0, d1) from tx_daily (no hour buckets asked), the whole
    # hours around them from tx_hourly, the partial hours at either edge from
    # the ledger.
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
    """Whether `zone` (UTC when None) is a whole hour off UTC at each naive
    UTC instant given (now when none is) and at January and July of their
    years, either side of any daylight-saving rule: a zone that is not is
    read by the minute (`local_days` still checks every hour)."""
    if zone is None:
        return True
    at = [i for i in instants if i is not None] or [datetime.utcnow()]
    probes = at + [datetime(i.year, m, 1) for i in at for m in (1, 7)]
    return all(not p.replace(tzinfo=timezone.utc).astimezone(zone).utcoffset().total_seconds() % 3600
               for p in probes)


def local_days(buckets: Iterable[str | None], zone: ZoneInfo | None, *,
               hourly: bool = True, fmt: str = "%Y-%m-%d") -> dict[str, str] | None:
    """`{UTC bucket start: its 'YYYY-MM-DD' in zone}` (UTC when None), each by
    the zone's offset at that instant; a bucket of an `occurred_at` SQLite
    could not parse ('' or NULL) is in no day. For `hourly` buckets, None
    when an offset is not a whole hour (the hour would straddle a day edge
    there); read by minute then. `fmt` (strftime) names another local unit,
    as '%Y-%m-%dT%H:00' its hour or "%u %H" its weekday and hour."""
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
