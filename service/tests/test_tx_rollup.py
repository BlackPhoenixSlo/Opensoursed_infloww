#!/usr/bin/env python3
"""Materialised attribution and the hourly and daily rollups (roadmap W2 2.1, 2.2; service/tx_rollup.py).

The triggers keep `transactions.credit_*` equal to the attribution view's row for every sale the view
carries, and `tx_hourly` / `tx_daily` equal to the ledger summed per bucket, across every kind of write the writers make:
a sale inserted before or after its message, a relink (message_id repointed), a late lookback message, a
sender changed, a message deleted (placeholder adoption), a manual reassign and its undo, a status flip, an
amount, net, fee or VAT corrected, a sale deleted. The oracle is the view itself (revision 0069) and a GROUP BY over
the ledger, compared after every step of a seeded random history. `window_sums` over any window equals the
same sums read straight off the ledger rows. The once-per-box backfill credits a ledger written before the
triggers existed, chunk by chunk, and resumes where an interrupted run stopped. The triggers install in one
transaction, only the missing or changed ones. A row whose `occurred_at` SQLite cannot parse, or one inserted
with its credit already set, keeps both exact; hard-deleting an Employee (the FK's ON DELETE SET NULL on
their messages) recredits their sales.

Seeded straight into the temp DB through a plain sync connection (the triggers fire on any writer); no
network. Lookback messages get distinct timestamps: the view leaves a tie's order undefined.

Run: ./venv/bin/python service/tests/test_tx_rollup.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from sqlalchemy import text  # noqa: E402

import tx_rollup  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account  # noqa: E402

ENGINE = sa.create_engine(os.environ["CHATTERLY_DB_URL"])
ACCOUNTS = ("9100001", "9100002")
KINDS = ("ppv_message", "ppv_post", "tip", "tip_post", "custom", "subscription", "tip_stream")
STATUSES = ("cleared", "pending", "refunded")
EMPLOYEES = (None, 11, 12, 13)
AUTOMATIONS = (None, None, "welcome_new_sub", "reply_mass_funnel")
T0 = datetime(2026, 3, 1, 9, 0)
_TS = "%Y-%m-%d %H:%M:%S.%f"


def _sql(stmt: str, **params):
    with ENGINE.begin() as conn:
        res = conn.execute(text(stmt), params)
        return res.all() if res.returns_rows else None


def _ts(at: datetime) -> str:
    return at.strftime(_TS)




async def _seed_accounts() -> None:
    async with get_session() as s:
        for aid in ACCOUNTS:
            s.add(Account(id=aid, nickname=f"rollup_{aid}", color="#aaaaaa"))


asyncio.run(_seed_accounts())


def _triggers() -> dict[str, str]:
    return dict(_sql("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND " + tx_rollup._OURS))


def _assert_exact(where: str) -> None:
    with ENGINE.connect() as conn:
        bad = tx_rollup.credit_mismatches(conn)
        assert not bad, f"{where}: credit differs from the view (tx, view emp/rule/ak, stored emp/rule/ak): {bad}"
        bad = tx_rollup.rollup_mismatches(conn)
        assert not bad, f"{where}: a rollup differs from the ledger: {bad[:6]}"


class History:
    """A random ledger and message history, mutated one write at a time."""

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.next_mid = 70_000_000 + seed * 100_000
        self.minute = 0
        self.msgs: list[tuple[str, int, int]] = []
        self.txs: list[int] = []

    def _at(self) -> datetime:
        # Distinct, increasing timestamps with a random offset (no lookback ties).
        self.minute += self.rng.randint(1, 600)
        return T0 + timedelta(minutes=self.minute, seconds=self.rng.randint(0, 59),
                              microseconds=self.rng.randint(0, 999_999))

    def message(self) -> None:
        r = self.rng
        aid, fan, mid = r.choice(ACCOUNTS), r.randint(1, 4), self.next_mid
        self.next_mid += 1
        _sql("INSERT INTO messages (account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
             "media_count, price_cents, is_tip, is_unsent, is_promise, sent_by_employee_id, automation_kind, "
             "created_at, ingested_at) VALUES (:a, :f, :m, :d, '', '', '[]', 0, 0, 0, 0, 0, :e, :k, :c, :c)",
             a=aid, f=fan, m=mid, d=r.choice(("out", "out", "out", "in")), e=r.choice(EMPLOYEES),
             k=r.choice(AUTOMATIONS), c=_ts(self._at()))
        self.msgs.append((aid, fan, mid))

    def sale(self) -> None:
        r = self.rng
        linked = self.msgs and r.random() < 0.5
        if linked:
            aid, fan, mid = r.choice(self.msgs)
        else:
            aid, fan, mid = r.choice(ACCOUNTS), r.randint(1, 4), None
            if r.random() < 0.1:
                mid = self.next_mid  # a sale whose message is not here yet
                self.next_mid += 1
        if mid is not None and _sql("SELECT 1 FROM transactions WHERE account_id = :a AND fan_id = :f "
                                    "AND message_id = :m", a=aid, f=fan, m=mid):
            mid = None
        amount = r.randint(1, 50_000)
        tid = _sql("INSERT INTO transactions (account_id, fan_id, kind, message_id, amount_cents, currency, "
                   "occurred_at, status, source, attributed_employee_id, net_cents, fee_cents, vat_cents) "
                   "VALUES (:a, :f, :k, :m, :c, 'USD', :o, :s, 'ledger', :e, :n, :fee, :vat) RETURNING id",
                   a=aid, f=fan, k=r.choice(KINDS), m=mid, c=amount, o=_ts(self._at()), s=r.choice(STATUSES),
                   e=r.choice((None, None, None, 12)), n=r.choice((None, amount * 8 // 10)),
                   fee=r.choice((None, amount // 5)), vat=r.choice((None, 0, amount // 10)))[0][0]
        self.txs.append(tid)

    def mutate(self) -> str:
        r = self.rng
        step = r.choice(("message", "message", "sale", "sale", "relink", "sender", "delete_message",
                         "reassign", "status", "amount", "delete_sale", "move_message"))
        if step == "message" or (step in ("sender", "delete_message", "relink", "move_message") and not self.msgs):
            self.message()
            return "message"
        if step == "sale" or not self.txs:
            self.sale()
            return "sale"
        tid = r.choice(self.txs)
        if step == "relink":
            aid, fan, mid = r.choice(self.msgs)
            taken = _sql("SELECT 1 FROM transactions WHERE account_id = :a AND fan_id = :f AND message_id = :m",
                         a=aid, f=fan, m=mid)
            _sql("UPDATE transactions SET account_id = :a, fan_id = :f, message_id = :m WHERE id = :t",
                 a=aid, f=fan, m=None if taken else mid, t=tid)
        elif step == "sender":
            aid, fan, mid = r.choice(self.msgs)
            _sql("UPDATE messages SET sent_by_employee_id = :e, automation_kind = :k WHERE account_id = :a "
                 "AND fan_id = :f AND message_id = :m", e=r.choice(EMPLOYEES), k=r.choice(AUTOMATIONS),
                 a=aid, f=fan, m=mid)
        elif step == "move_message":
            aid, fan, mid = r.choice(self.msgs)
            _sql("UPDATE messages SET created_at = :c WHERE account_id = :a AND fan_id = :f AND message_id = :m",
                 c=_ts(self._at() - timedelta(days=r.randint(0, 9))), a=aid, f=fan, m=mid)
        elif step == "delete_message":
            msg = r.choice(self.msgs)
            self.msgs.remove(msg)
            _sql("DELETE FROM messages WHERE account_id = :a AND fan_id = :f AND message_id = :m",
                 a=msg[0], f=msg[1], m=msg[2])
        elif step == "reassign":
            # 0 is the "No one" override (sales_attribution.NO_ONE).
            _sql("UPDATE transactions SET attributed_employee_id = :e WHERE id = :t", e=r.choice(EMPLOYEES + (0,)),
                 t=tid)
        elif step == "status":
            _sql("UPDATE transactions SET status = :s WHERE id = :t", s=r.choice(STATUSES), t=tid)
        elif step == "amount":
            _sql("UPDATE transactions SET amount_cents = :c, net_cents = :n, fee_cents = :fee, vat_cents = :vat "
                 "WHERE id = :t", c=r.randint(1, 9_999), n=r.choice((None, r.randint(0, 9_000))),
                 fee=r.choice((None, r.randint(0, 2_000))), vat=r.choice((None, r.randint(0, 900))), t=tid)
        else:
            self.txs.remove(tid)
            _sql("DELETE FROM transactions WHERE id = :t", t=tid)
        return step


def case_credit_and_rollup_stay_exact_across_every_write():
    hist = History(seed=1)
    for _ in range(40):
        hist.message()
    for _ in range(80):
        hist.sale()
    _assert_exact("after the seed")
    for i in range(400):
        step = hist.mutate()
        if i % 10 == 0:
            _assert_exact(f"after write {i} ({step})")
    _assert_exact("after the history")
    with ENGINE.connect() as conn:
        rules = {r for (r,) in conn.execute(text(
            "SELECT DISTINCT rule FROM per_employee_revenue_with_attribution"))}
        n = conn.execute(text("SELECT COUNT(*) FROM per_employee_revenue_with_attribution")).scalar()
    assert rules == {"manual", "message", "tip_lookback", "unassigned"}, f"every rule exercised, got {rules}"
    assert n > 50, f"the view carried {n} sales; the history is too thin to prove anything"


def case_one_message_moves_every_sale_it_credits():
    """The named writes, one at a time, with the credit written out by hand."""
    aid, fan = ACCOUNTS[0], 99

    def credit(tid):
        return tuple(_sql("SELECT credit_employee_id, credit_rule, credit_automation_kind FROM transactions "
                          "WHERE id = :t", t=tid)[0])

    def tx(kind, at, mid=None):
        return _sql("INSERT INTO transactions (account_id, fan_id, kind, message_id, amount_cents, currency, "
                    "occurred_at, status, source) VALUES (:a, :f, :k, :m, 500, 'USD', :o, 'cleared', 'ledger') "
                    "RETURNING id", a=aid, f=fan, k=kind, m=mid, o=_ts(at))[0][0]

    def msg(mid, at, emp, kind=None):
        _sql("INSERT INTO messages (account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
             "media_count, price_cents, is_tip, is_unsent, is_promise, sent_by_employee_id, automation_kind, "
             "created_at, ingested_at) VALUES (:a, :f, :m, 'out', '', '', '[]', 0, 0, 0, 0, 0, :e, :k, :c, :c)",
             a=aid, f=fan, m=mid, e=emp, k=kind, c=_ts(at))

    day = datetime(2026, 4, 10, 12, 0)
    ppv = tx("ppv_message", day, mid=555)
    tip = tx("tip", day + timedelta(hours=5))
    assert credit(ppv) == (None, "unassigned", None) and credit(tip) == (None, "unassigned", None)
    msg(555, day - timedelta(minutes=1), 11, "welcome_new_sub")      # the PPV's message arrives late
    assert credit(ppv) == (11, "message", "welcome_new_sub"), credit(ppv)
    assert credit(tip) == (11, "tip_lookback", "welcome_new_sub"), "the same message is the tip's lookback"
    msg(556, day + timedelta(hours=1), 13)                            # a later outbound: the tip's lookback now
    assert credit(tip) == (13, "tip_lookback", None) and credit(ppv)[0] == 11
    _sql("UPDATE messages SET sent_by_employee_id = 12 WHERE account_id = :a AND fan_id = :f AND message_id = 556",
         a=aid, f=fan)
    assert credit(tip) == (12, "tip_lookback", None)
    _sql("UPDATE transactions SET attributed_employee_id = 13 WHERE id = :t", t=ppv)  # manual reassign
    assert credit(ppv) == (13, "manual", "welcome_new_sub")
    _sql("UPDATE transactions SET attributed_employee_id = NULL WHERE id = :t", t=ppv)
    assert credit(ppv) == (11, "message", "welcome_new_sub")
    _sql("DELETE FROM messages WHERE account_id = :a AND fan_id = :f AND message_id = 556", a=aid, f=fan)
    assert credit(tip) == (11, "tip_lookback", "welcome_new_sub"), "back to the earlier lookback"
    _sql("DELETE FROM messages WHERE account_id = :a AND fan_id = :f AND message_id = 555", a=aid, f=fan)
    assert credit(ppv) == (None, "unassigned", None) and credit(tip) == (None, "unassigned", None)
    msg(557, day - timedelta(days=8), 11)                             # outside the 7-day lookback
    assert credit(tip) == (None, "unassigned", None)
    _sql("UPDATE transactions SET message_id = 557 WHERE id = :t", t=ppv)  # relink
    assert credit(ppv) == (11, "message", None)
    _assert_exact("after the named writes")


def _raw_sums(account_ids, start, end):
    conds, params = ["1 = 1"], {}
    if account_ids is not None:
        conds.append("account_id IN (" + ", ".join(f":a{i}" for i in range(len(account_ids))) + ")")
        params.update({f"a{i}": a for i, a in enumerate(account_ids)})
    if start is not None:
        conds.append("occurred_at >= :s")
        params["s"] = _ts(start)
    if end is not None:
        conds.append("occurred_at <= :e")
        params["e"] = _ts(end)
    # 0, the "No one" override, is nobody, as in the rollups.
    rows = _sql("SELECT kind, NULLIF(credit_employee_id, 0), SUM(amount_cents), SUM(COALESCE(net_cents, 0)), "
                "SUM(net_cents IS NULL), SUM(COALESCE(net_cents, amount_cents * 8 / 10)), COUNT(*), "
                "SUM(COALESCE(fee_cents, 0)), SUM(COALESCE(vat_cents, 0)) "
                f"FROM transactions WHERE {' AND '.join(conds)} GROUP BY 1, 2", **params)
    return {(r[0], r[1]): tuple(r[2:]) for r in rows}


def case_window_sums_equal_the_ledger_for_any_window():
    rng = random.Random(7)
    span = _sql("SELECT MIN(occurred_at), MAX(occurred_at) FROM transactions")[0]
    lo, hi = (datetime.fromisoformat(x) for x in span)

    async def go(account_ids, start, end):
        async with get_session() as s:
            rows = await tx_rollup.window_sums(s, ("kind", "employee_id"), account_ids=account_ids,
                                               start=start, end=end)
        return {(r.kind, r.employee_id): (r.gross_cents, r.net_cents, r.net_missing, r.net_or_80_cents, r.sales,
                                          r.fee_cents, r.vat_cents)
                for r in rows}

    windows = [(None, None, None), (list(ACCOUNTS[:1]), None, None)]
    for _ in range(25):
        a = lo + (hi - lo) * rng.random()
        b = a + timedelta(minutes=rng.choice((3, 59, 61, 600, 5_000, 40_000)), seconds=rng.random())
        windows.append((rng.choice((None, list(ACCOUNTS), [ACCOUNTS[1]])), a, b))
    windows.append((None, lo, lo))                                        # one sale's instant
    windows.append((None, lo.replace(minute=0, second=0, microsecond=0), None))  # starts on an hour
    midnight = lo.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    windows.append((None, midnight, midnight + timedelta(days=20) - timedelta(microseconds=1)))  # whole days
    windows.append((None, None, midnight + timedelta(days=9, hours=5)))   # open start, ends mid-day
    for account_ids, start, end in windows:
        got = asyncio.run(go(account_ids, start, end))
        want = _raw_sums(account_ids, start, end)
        assert got == want, f"window {account_ids} {start} {end}: rollup {got} != ledger {want}"


def case_hour_buckets_land_on_the_zones_local_day():
    """S8: each hour is placed by the zone's offset at that hour, so the hours either side of a DST change
    land on the right local day."""
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    # 2026-03-08: New York springs forward at 07:00 UTC (EST -5 -> EDT -4).
    days = tx_rollup.local_days(["2026-03-08 04:00:00", "2026-03-09 03:00:00", "2026-03-09 04:00:00",
                                 "2026-11-02 04:00:00", "2026-11-02 05:00:00"], ny)
    assert days == {"2026-03-08 04:00:00": "2026-03-07", "2026-03-09 03:00:00": "2026-03-08",
                    "2026-03-09 04:00:00": "2026-03-09", "2026-11-02 04:00:00": "2026-11-01",
                    "2026-11-02 05:00:00": "2026-11-02"}, days
    assert tx_rollup.local_days(["2026-03-08 04:00:00"], None) == {"2026-03-08 04:00:00": "2026-03-08"}
    assert tx_rollup.local_days(["2026-03-08 04:00:00"], ZoneInfo("Asia/Kolkata")) is None, \
        "a half-hour zone asks for minute buckets"
    assert tx_rollup.local_days(["2026-03-08 18:30:00", "2026-03-08 18:29:00"], ZoneInfo("Asia/Kolkata"),
                                hourly=False) == {"2026-03-08 18:30:00": "2026-03-09",
                                                  "2026-03-08 18:29:00": "2026-03-08"}


def case_triggers_install_in_one_transaction_and_only_when_changed():
    want = {name: f"CREATE TRIGGER {name} {body}" for name, body in tx_rollup.TRIGGERS.items()}
    assert _triggers() == want
    with tx_rollup._immediate(ENGINE) as conn:
        assert tx_rollup._install(conn) == 0, "a current box touches no trigger"
    _sql("DROP TRIGGER trg_tx_rollup_del")
    _sql("DROP TRIGGER trg_tx_credit_upd")
    _sql("CREATE TRIGGER trg_tx_credit_upd AFTER UPDATE ON transactions BEGIN SELECT 1; END")
    _sql("CREATE TRIGGER trg_tx_rollup_ins AFTER INSERT ON transactions BEGIN SELECT 1; END")  # retired
    stale = _triggers()
    # A definition that fails to create rolls back the whole install: no trigger dropped meanwhile is lost.
    original = dict(tx_rollup.TRIGGERS)
    tx_rollup.TRIGGERS["trg_tx_zz_broken"] = "AFTER INSERT ON no_such_table BEGIN SELECT 1; END"
    try:
        tx_rollup.ensure(ENGINE)
        raise AssertionError("a broken trigger must fail the install")
    except sa.exc.OperationalError:
        pass
    finally:
        tx_rollup.TRIGGERS.clear()
        tx_rollup.TRIGGERS.update(original)
    assert _triggers() == stale, "the failed install left the triggers as they were"
    with tx_rollup._immediate(ENGINE) as conn:
        assert tx_rollup._install(conn) == 3, "one missing, one changed, one retired"
    assert _triggers() == want


def case_no_emptied_bucket_is_left_whichever_trigger_fires_first():
    """A relink changes a sale's credit (trg_tx_credit_upd's UPDATE) and its `linked` bucket key
    (trg_tx_rollup_upd) in one statement. Each trigger recreated last fires in a different order; every
    order leaves exactly the ledger's buckets, no zero row behind."""
    aid, fan = ACCOUNTS[1], 55
    for i, recreate in enumerate((None, "trg_tx_credit_upd", "trg_tx_rollup_upd", "trg_tx_credit_upd")):
        if recreate:
            _sql(f"DROP TRIGGER {recreate}")
            _sql(f"CREATE TRIGGER {recreate} {tx_rollup.TRIGGERS[recreate]}")
        at, mid = datetime(2027, 1, 1 + i, 10), 88_900_000 + i
        _sql("INSERT INTO messages (account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
             "media_count, price_cents, is_tip, is_unsent, is_promise, sent_by_employee_id, created_at, "
             "ingested_at) VALUES (:a, :f, :m, 'out', '', '', '[]', 0, 0, 0, 0, 0, 11, :c, :c)",
             a=aid, f=fan, m=mid, c=_ts(at))
        tid = _sql("INSERT INTO transactions (account_id, fan_id, kind, amount_cents, currency, occurred_at, "
                   "status, source) VALUES (:a, :f, 'ppv_message', 600, 'USD', :o, 'cleared', 'ledger') "
                   "RETURNING id", a=aid, f=fan, o=_ts(at + timedelta(minutes=3)))[0][0]
        _sql("UPDATE transactions SET message_id = :m WHERE id = :t", m=mid, t=tid)
        assert _sql("SELECT credit_rule FROM transactions WHERE id = :t", t=tid) == [("message",)]
        _assert_exact(f"after a relink, {recreate or 'install order'} last")
        _sql("UPDATE transactions SET message_id = NULL WHERE id = :t", t=tid)
        _assert_exact(f"after an unlink, {recreate or 'install order'} last")


def case_a_failed_catch_up_boots_on_after_every_other_step_and_heals_in_the_background():
    import sys
    eng_mod = sys.modules["db.engine"]  # `db.engine` the attribute is the AsyncEngine
    real_ensure, real_w7, real_delays = tx_rollup.ensure, eng_mod.backfill_w7_rules_once, eng_mod.TX_ROLLUP_RETRY_S
    calls, w7 = [], []

    def flaky(sync_engine):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("database is locked")
        return real_ensure(sync_engine)

    def w7_spy(sync_engine):
        w7.append(len(calls))
        return real_w7(sync_engine)

    async def boot():
        await eng_mod.init_db()
        assert calls == [1], "init_db returned after one failed catch-up"
        assert w7 == [0], "the w7 backfill ran, before the catch-up"
        assert eng_mod._retry_tasks, "a retry is scheduled"
        await asyncio.gather(*eng_mod._retry_tasks)

    tx_rollup.ensure, eng_mod.backfill_w7_rules_once, eng_mod.TX_ROLLUP_RETRY_S = flaky, w7_spy, (0, 0)
    try:
        asyncio.run(boot())
    finally:
        tx_rollup.ensure, eng_mod.backfill_w7_rules_once, eng_mod.TX_ROLLUP_RETRY_S = real_ensure, real_w7, real_delays
    assert len(calls) == 3, "retried until it succeeded"
    _assert_exact("after the healed boot")


def case_an_unparseable_occurred_at_breaks_no_write():
    aid = ACCOUNTS[1]
    tid = _sql("INSERT INTO transactions (account_id, fan_id, kind, amount_cents, currency, occurred_at, status, "
               "source) VALUES (:a, 1, 'tip', 700, 'USD', 'not a time', 'cleared', 'ledger') RETURNING id",
               a=aid)[0][0]
    assert _sql("SELECT credit_rule FROM transactions WHERE id = :t", t=tid) == [("unassigned",)]
    assert _sql("SELECT gross_cents FROM tx_hourly WHERE hour = '' AND account_id = :a", a=aid) == [(700,)]
    assert _sql("SELECT gross_cents FROM tx_daily WHERE day = '' AND account_id = :a", a=aid) == [(700,)]
    _assert_exact("with a dirty occurred_at")

    import stats

    async def days():
        async with get_session() as s:
            return await stats._day_sums(s, ("kind",), None, account_ids=[aid], start=None, end=None)
    assert all(r["day"] for r in asyncio.run(days())), "the dirty row is in no day, and fails no read"
    _sql("UPDATE transactions SET occurred_at = :o WHERE id = :t", o=_ts(T0), t=tid)
    _assert_exact("after its occurred_at is fixed")
    assert not _sql("SELECT 1 FROM tx_hourly WHERE hour = ''")
    _sql("DELETE FROM transactions WHERE id = :t", t=tid)
    _assert_exact("after it is deleted")


def case_a_row_inserted_with_its_credit_set_is_counted_once():
    tid = _sql("INSERT INTO transactions (account_id, fan_id, kind, amount_cents, currency, occurred_at, status, "
               "source, credit_employee_id, credit_rule) VALUES (:a, 1, 'ppv_post', 900, 'USD', :o, 'cleared', "
               "'ledger', 13, 'manual') RETURNING id", a=ACCOUNTS[0], o=_ts(T0))[0][0]
    assert _sql("SELECT credit_employee_id, credit_rule FROM transactions WHERE id = :t", t=tid) == [
        (None, "unassigned")], "recomputed from the row's keys, not kept"
    _assert_exact("after a row inserted with a stale credit")


def case_hard_deleting_an_employee_recredits_their_sales():
    """messages.sent_by_employee_id is ON DELETE SET NULL: SQLite runs that action as an UPDATE of each
    message, which fires trg_msg_credit_upd, so the Employee's sales fall back to unassigned."""
    eid = _sql("INSERT INTO employees (display_name, color, is_active, created_at) "
               "VALUES ('rollup_gone', '#cccccc', 1, :c) RETURNING id", c=_ts(T0))[0][0]
    aid, fan, at = ACCOUNTS[0], 77, datetime(2026, 9, 1, 12)
    _sql("INSERT INTO messages (account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
         "media_count, price_cents, is_tip, is_unsent, is_promise, sent_by_employee_id, created_at, ingested_at) "
         "VALUES (:a, :f, 88800001, 'out', '', '', '[]', 0, 0, 0, 0, 0, :e, :c, :c)", a=aid, f=fan, e=eid, c=_ts(at))
    ppv = _sql("INSERT INTO transactions (account_id, fan_id, kind, message_id, amount_cents, currency, "
               "occurred_at, status, source) VALUES (:a, :f, 'ppv_message', 88800001, 300, 'USD', :o, 'cleared', "
               "'ledger') RETURNING id", a=aid, f=fan, o=_ts(at + timedelta(minutes=5)))[0][0]
    tip = _sql("INSERT INTO transactions (account_id, fan_id, kind, amount_cents, currency, occurred_at, status, "
               "source) VALUES (:a, :f, 'tip', 400, 'USD', :o, 'cleared', 'ledger') RETURNING id",
               a=aid, f=fan, o=_ts(at + timedelta(hours=2)))[0][0]
    credited = "SELECT credit_employee_id FROM transactions WHERE id IN (:p, :t) ORDER BY id"
    assert _sql(credited, p=ppv, t=tip) == [(eid,), (eid,)]
    with ENGINE.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON")  # as every app connection runs
        conn.execute(text("DELETE FROM employees WHERE id = :e"), {"e": eid})
    assert _sql("SELECT sent_by_employee_id FROM messages WHERE message_id = 88800001") == [(None,)]
    assert _sql(credited, p=ppv, t=tip) == [(None,), (None,)]
    _assert_exact("after an Employee is hard-deleted")


def case_backfill_credits_a_ledger_written_before_the_triggers_and_resumes():
    with ENGINE.begin() as conn:
        for name in tx_rollup.TRIGGERS:
            conn.execute(text(f"DROP TRIGGER {name}"))
        conn.execute(text("UPDATE transactions SET credit_employee_id = NULL, credit_rule = NULL, "
                          "credit_automation_kind = NULL"))
        conn.execute(text("UPDATE tx_hourly SET gross_cents = gross_cents + 1"))
        conn.execute(text("DELETE FROM tx_daily"))
    assert tx_rollup.ensure(ENGINE) is False, "the marker is set: no second backfill"
    with ENGINE.connect() as conn:
        assert tx_rollup.credit_mismatches(conn), "without the backfill the rows stay pending"
    _sql("DELETE FROM data_migrations WHERE name = :n", n=tx_rollup._BACKFILL)
    pending = _sql("SELECT COUNT(*) FROM transactions")[0][0]

    # Interrupted after its first chunk: that chunk stays credited, the marker unset.
    chunk, real, calls = tx_rollup._CHUNK, tx_rollup._credit_chunk, []

    def flaky(conn, lo, hi):
        if calls:
            raise RuntimeError("killed mid-backfill")
        calls.append(lo)
        real(conn, lo, hi)
    tx_rollup._CHUNK, tx_rollup._credit_chunk = 40, flaky
    try:
        tx_rollup.ensure(ENGINE)
        raise AssertionError("the interrupted backfill must raise")
    except RuntimeError:
        pass
    finally:
        tx_rollup._credit_chunk = real
    left = _sql("SELECT COUNT(*) FROM transactions WHERE credit_rule IS NULL")[0][0]
    assert 0 < left < pending and pending - left <= 40, (pending, left)
    assert not _sql("SELECT 1 FROM data_migrations WHERE name = :n", n=tx_rollup._BACKFILL)
    History(seed=3).sale()  # the triggers are live while it is pending

    try:
        assert tx_rollup.ensure(ENGINE) is True, "the next boot resumes"
    finally:
        tx_rollup._CHUNK = chunk
    assert not _sql("SELECT 1 FROM transactions WHERE credit_rule IS NULL")
    _assert_exact("after the backfill")
    History(seed=4).sale()
    _assert_exact("the triggers keep it after the backfill")


def case_a_box_backfilled_before_fee_and_vat_rebuilds_them_once():
    """A box whose rollups predate the fee and VAT sums (the old marker set, the new columns all 0 from
    init_db's ADD COLUMN default) rebuilds them on its next boot, once."""
    assert _sql("SELECT SUM(fee_cents) + SUM(vat_cents) FROM tx_hourly")[0][0], "the history carries fees"
    _sql("UPDATE tx_hourly SET fee_cents = 0, vat_cents = 0")
    _sql("UPDATE tx_daily SET fee_cents = 0, vat_cents = 0")
    _sql("DELETE FROM data_migrations WHERE name = :n", n=tx_rollup._BACKFILL)
    _sql("INSERT OR IGNORE INTO data_migrations (name) VALUES ('20261019_tx_credit_rollup')")
    assert tx_rollup.ensure(ENGINE) is True, "the renamed marker rebuilds"
    _assert_exact("after the fee and VAT rebuild")
    assert tx_rollup.ensure(ENGINE) is False, "and only once"


_harness.run()
