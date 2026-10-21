#!/usr/bin/env python3
"""
fansly_revenue — the Fansly purchase feed becomes `transactions` rows.

Fansly has no creator-side money ledger (every sales endpoint 404s), so the
ONLY signal that a fan paid is a purchase row in `GET /notifications`. This
file pins the two things that makes safe:

  PARSING — what is and, more importantly, what is NOT a bankable sale. Every
  refusal case here is a way to invent revenue that nobody paid, which is the
  worst failure this module could have. A row that cannot supply a field is
  dropped, never defaulted.

      case_live_capture_shape_parses     the exact 2026-09-02 $3 row
      case_price_unit_is_thousandths     3000 units == 300 cents, not 3000
      case_rounding_is_half_up_and_exact half-cent rounds UP, not to even, and
          stays exact on large amounts (integer math, not a float divide)
      case_only_proven_codes_are_money   an unmapped code banks nothing
      case_junk_metadata_banks_nothing   unparseable/absent price -> skip
      case_zero_price_is_not_a_sale      a free unlock is not a transaction
      case_missing_buyer_banks_nothing   a row with no buyer is unbankable
      case_snowflake_buyer_survives      64-bit fan id is not truncated

  WRITING — the ledger contract.

      case_tick_banks_the_sale           gross, cleared, ppv_message
      case_tick_is_idempotent            re-seeing the same notification (the
          feed re-reads every tick for as long as the row is visible) must
          never double-count the money
      case_net_is_null_not_imputed       Fansly never discloses its cut, so
          net/fee/vat stay NULL rather than being guessed from gross
      case_ppv_message_reaches_the_ppv_bucket  the kind must land in stats'
          `startswith("ppv")` bucket, which is what the dashboard's "Message
          earnings" card reads. A kind that parses but buckets wrong is a
          silent $0.00 on the home page — the original symptom.

Run: ./venv/bin/python service/tests/test_fansly_revenue.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

import fansly_revenue  # noqa: E402
import stats  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Transaction, TransactionScanHistory  # noqa: E402

ACCT = "700237824869654528"
FAN = "900604711209099264"

# One `purchases()` row, as the shim emits it for the real 2026-09-02 $3 sale.
# Ids are strings (64-bit snowflakes), `created_at` is epoch SECONDS, and the
# price has already been converted to dollars by the shim.
LIVE_ROW = {
    "id": "900642430324908036",
    "fan_id": FAN,
    "grant_id": "900640044332167168",
    "price_usd": 3.0,
    "created_at": 1788335912,
    "code": 2007,
}


class _FeedStub:
    """Stands in for the shim client at its PUBLIC boundary.

    The lane consumes `purchases()` — already filtered to proven codes and
    already priced in dollars — so the stub speaks that shape. Which
    notification codes count as a sale, and where in `metadata` the price
    hides, is the shim's knowledge and is tested in fansly/test_shim_shapes.py.
    """

    def __init__(self, rows):
        self._rows = rows
        self.calls = 0

    def purchases(self):
        self.calls += 1
        return list(self._rows)

    def unbanked_purchase_codes(self):
        return set()


class _quiet_lane_errors:
    """Suppress the lane's `fansly_revenue_feed_failed` traceback.

    Two cases below break the feed ON PURPOSE to prove the raise reaches the
    caller. The lane logs that at WARNING with `exc_info=True` — correct in
    production, where a dead session is exactly what you want a traceback for —
    but on a green test run it prints an alarming RuntimeError that looks like
    a real failure. Hushed here rather than weakened there.
    """

    def __enter__(self):
        self._log = logging.getLogger("of-relay.fansly_revenue")
        self._was = self._log.disabled
        self._log.disabled = True
        return self

    def __exit__(self, *exc):
        self._log.disabled = self._was
        return False


async def _seed_account() -> None:
    async with get_session() as s:
        if await s.get(Account, ACCT) is None:
            s.add(Account(id=ACCT, nickname="founderfansly"))


def _install(monkey_rows):
    """Point the module at a stub feed for one case."""
    stub = _FeedStub(monkey_rows)
    fansly_revenue.fansly_backend = type(
        "_B", (), {"get_client": staticmethod(lambda _aid: stub),
                   "is_fansly": staticmethod(lambda _aid: True)}
    )
    return stub


# ── parsing ─────────────────────────────────────────────────────────

def case_live_capture_shape_parses():
    sale = fansly_revenue.parse_purchase(LIVE_ROW)
    assert sale is not None, "the live $3 capture must parse"
    assert sale.provider_id == "900642430324908036", sale
    assert sale.fan_id == int(FAN), sale
    assert sale.amount_cents == 300, sale
    # epoch SECONDS -> naive UTC, matching every other writer of this column.
    assert sale.occurred_at == datetime(2026, 9, 2, 7, 58, 32), sale.occurred_at
    # The grant belongs in the description, NOT message_id: that column joins
    # onto OUR messages table and a Fansly accountMedia id would match wrong.
    assert "900640044332167168" in sale.description, sale.description


def case_rounding_is_half_up_and_exact():
    """Money must not round half-to-EVEN, and must not lose precision in a
    float multiply. `round(usd * 100)` failed both: $0.015 -> 2c and
    $0.025 -> 2c, inconsistent on the same boundary."""
    for usd, want in [(3.0, 300), (101.0, 10100),
                      (0.005, 1), (0.015, 2), (0.025, 3), (0.035, 4),
                      (0.004, None),            # below half a cent: not a sale
                      (0.999, 100), (1.005, 101), (1.015, 102),
                      (10 ** 9, 10 ** 11)]:     # exact, no float drift
        got = fansly_revenue._cents(usd)
        assert got == want, f"${usd} -> {got}, want {want}"


def case_an_absurd_price_drops_its_row_not_the_page():
    """`Decimal.quantize` overflows the default 28-digit context at ~1e26 and
    raises. `_cents` is called OUTSIDE the tick's feed-failure try/except, so
    an uncaught raise would take down the whole page — losing every other real
    sale on it — over one corrupt row."""
    for usd in (1e300, 10 ** 26, 10 ** 40):
        assert fansly_revenue._cents(usd) is None, f"{usd} did not drop"
        assert fansly_revenue.parse_purchase(dict(LIVE_ROW, price_usd=usd)) is None

    async def go():
        await _seed_account()
        good = dict(LIVE_ROW, id="900642430324909555", price_usd=6.0)
        rotten = dict(LIVE_ROW, id="900642430324909666", price_usd=1e300)
        _install([rotten, good])
        res = await fansly_revenue.run_one_tick(ACCT)
        assert res.rows_inserted == 1, res
        assert len(await _rows_for(good["id"])) == 1, "a real sale died with the corrupt row"
        assert len(await _rows_for(rotten["id"])) == 0, "an unusable price was banked"
    asyncio.run(go())


def case_a_zero_or_negative_amount_is_not_a_sale():
    """A $0 row is a free unlock. Banking it writes a transaction
    indistinguishable from a real sale of nothing."""
    for usd in (0, 0.0, -3.0, None, "", "abc", float("nan")):
        row = dict(LIVE_ROW, price_usd=usd)
        assert fansly_revenue.parse_purchase(row) is None, f"price {usd!r} banked"


def case_missing_buyer_or_id_banks_nothing():
    for buyer in (None, "", "0", "not-a-number"):
        row = dict(LIVE_ROW, fan_id=buyer)
        assert fansly_revenue.parse_purchase(row) is None, f"buyer {buyer!r} banked"
    # The notification id IS the dedup key: without one, every tick would
    # re-insert the same sale.
    for bad_id in (None, "", "   "):
        assert fansly_revenue.parse_purchase(dict(LIVE_ROW, id=bad_id)) is None


def case_an_unreadable_timestamp_is_dropped_not_faked():
    """The one place this module could invent data. A fabricated `now` files a
    real sale under the wrong day forever, so an unreadable stamp drops the
    row instead — same rule as every other field."""
    for ts in (None, "", "not-a-number", float("inf")):
        row = dict(LIVE_ROW, created_at=ts)
        assert fansly_revenue.parse_purchase(row) is None, f"timestamp {ts!r} was faked"


def case_snowflake_buyer_survives():
    """Fansly ids exceed 2^53. Python ints are arbitrary-precision, so the
    round trip must be exact — a truncated fan id attributes the money to a
    fan who does not exist."""
    sale = fansly_revenue.parse_purchase(LIVE_ROW)
    assert str(sale.fan_id) == FAN, f"{sale.fan_id} != {FAN}"
    assert sale.fan_id > 2 ** 53


def case_the_source_row_is_kept_for_audit():
    """The notification scrolls off the feed permanently, so the row stored
    with the transaction is the only surviving evidence for it."""
    sale = fansly_revenue.parse_purchase(LIVE_ROW)
    assert "900642430324908036" in sale.raw_json, sale.raw_json


# ── writing ─────────────────────────────────────────────────────────

async def _spend() -> int:
    """The buyer's current lifetime spend (0 when the Fan row doesn't exist)."""
    async with get_session() as s:
        fan = await s.get(Fan, (ACCT, int(FAN)))
        return (fan.lifetime_spend_cents or 0) if fan else 0


async def _count_of(provider_id: str) -> int:
    """How many ledger rows exist for ONE notification id. Cases share a single
    temp DB, so every write assertion scopes itself this way rather than
    counting the whole account."""
    async with get_session() as s:
        return len((await s.execute(
            select(Transaction.id).where(
                Transaction.account_id == ACCT,
                Transaction.provider_transaction_id == provider_id)
        )).scalars().all())


async def _amount_of(provider_id: str) -> int:
    async with get_session() as s:
        return (await s.execute(
            select(Transaction.amount_cents).where(
                Transaction.account_id == ACCT,
                Transaction.provider_transaction_id == provider_id)
        )).scalar_one()


async def _rows_for(provider_id: str):
    """The ledger rows for ONE notification id. Cases share a single temp DB,
    so every write assertion scopes itself rather than counting the account —
    otherwise a case would silently depend on which cases ran before it."""
    async with get_session() as s:
        return (await s.execute(
            select(Transaction).where(
                Transaction.account_id == ACCT,
                Transaction.provider_transaction_id == provider_id)
        )).scalars().all()


def case_tick_banks_the_sale():
    async def go():
        await _seed_account()
        _install([LIVE_ROW])
        _install([dict(LIVE_ROW, id="900642430324908555")])
        res = await fansly_revenue.run_one_tick(ACCT)
        assert res.rows_inserted == 1, res
        rows = await _rows_for("900642430324908555")
        assert len(rows) == 1, rows
        t = rows[0]
        assert t.amount_cents == 300, t.amount_cents
        assert t.kind == "ppv_message", t.kind
        assert t.status == "cleared", t.status
        assert t.currency == "USD", t.currency
        assert t.fan_id == int(FAN), t.fan_id
        assert t.provider_transaction_id == "900642430324908555"
        # The grant id belongs in the description, NOT message_id: that column
        # joins onto OUR messages table and a Fansly accountMedia id would
        # match the wrong row.
        assert t.message_id is None, t.message_id
        assert "900640044332167168" in (t.description or "")
    asyncio.run(go())


def case_tick_is_idempotent():
    """The feed is re-read every tick for as long as the row stays visible.
    Re-seeing a sale must never bank it twice."""
    async def go():
        await _seed_account()
        _install([dict(LIVE_ROW, id="900642430324908777")])
        await fansly_revenue.run_one_tick(ACCT)
        second = await fansly_revenue.run_one_tick(ACCT)
        third = await fansly_revenue.run_one_tick(ACCT)
        assert second.rows_inserted == 0, second
        assert third.rows_inserted == 0, third
        rows = await _rows_for("900642430324908777")
        assert len(rows) == 1, f"the same sale was banked {len(rows)} times"
        assert rows[0].amount_cents == 300
    asyncio.run(go())


def case_net_is_null_not_imputed():
    """Fansly never tells the creator its cut. Imputing net from gross would
    label gross as net; stats already reports NULL nets as `net_missing`."""
    async def go():
        await _seed_account()
        _install([dict(LIVE_ROW, id="900642430324908666")])
        await fansly_revenue.run_one_tick(ACCT)
        t = (await _rows_for("900642430324908666"))[0]
        assert t.net_cents is None, t.net_cents
        assert t.fee_cents is None, t.fee_cents
        assert t.vat_cents is None, t.vat_cents
    asyncio.run(go())


async def _ppv_total() -> int:
    """What /admin/stats/revenue reports in the `ppv` bucket for this account —
    the exact number behind the dashboard's "Message earnings" card."""
    r = await stats.revenue(account_id=ACCT, from_=None, to=None,
                            group_by="kind", include_net=False, by_kind=False, status="tracked")
    return sum(row["total_cents"] for row in r["rows"]
               if str(row["kind"]).startswith("ppv"))


def case_ppv_message_reaches_the_ppv_bucket():
    """The bug this whole lane fixes: the home page reads
    `revenue_by_kind.ppv`. A kind that parses but buckets elsewhere leaves the
    dashboard at $0.00 with the money sitting in the table."""
    assert stats._kind_bucket("ppv_message") == "ppv", stats._kind_bucket("ppv_message")

    async def go():
        await _seed_account()
        before = await _ppv_total()
        _install([dict(LIVE_ROW, id="900642430324908888", price_usd=4.0)])
        await fansly_revenue.run_one_tick(ACCT)
        moved = await _ppv_total() - before
        assert moved == 400, f"the ppv bucket moved by {moved}, want 400"

    asyncio.run(go())


def case_lifetime_spend_is_bumped():
    """The ledger row is only half the write. `fans.lifetime_spend_cents` is
    what the automations read to make live money decisions — autoreply's whale
    gate, _customs' proven-spend floor, gen_info's tiers. Without the bump a
    Fansly buyer reads $0 forever and the AI keeps hard-selling someone who
    already paid. The Fan row must also be CREATED: a PPV-only buyer never
    triggers the inbound-DM path that would otherwise make one."""
    async def go():
        await _seed_account()
        before = await _spend()
        _install([dict(LIVE_ROW, id="900642430324908333")])
        await fansly_revenue.run_one_tick(ACCT)
        async with get_session() as s:
            fan = await s.get(Fan, (ACCT, int(FAN)))
        assert fan is not None, "no Fan row was created for a PPV-only buyer"
        assert (fan.lifetime_spend_cents or 0) - before == 300, \
            f"spend moved by {(fan.lifetime_spend_cents or 0) - before}, want 300"
    asyncio.run(go())


def case_lifetime_spend_is_not_double_bumped():
    """The rollup must follow the same once-only rule as the insert: re-seeing
    the sale on the feed may not inflate the fan's spend."""
    async def go():
        await _seed_account()
        before = await _spend()
        _install([dict(LIVE_ROW, id="900642430324908444")])
        await fansly_revenue.run_one_tick(ACCT)
        await fansly_revenue.run_one_tick(ACCT)
        await fansly_revenue.run_one_tick(ACCT)
        moved = await _spend() - before
        assert moved == 300, f"one sale seen 3x moved spend by {moved}, want 300"
    asyncio.run(go())


def case_a_broken_feed_raises_so_backoff_can_work():
    """A feed read that fails must RAISE. The supervisor's `except` is what
    calls _record_failure, which drives consecutive_failures and the pause
    backoff; swallowing the error into a return value looks like a clean tick,
    so a dead session would never be counted, paused, or shown on the admin
    dashboard — while sales scroll off the single-page feed unrecoverably."""
    class _Boom:
        def purchases(self):
            raise RuntimeError("fansly 500")

        def unbanked_purchase_codes(self):
            return set()

    async def go():
        await _seed_account()
        fansly_revenue.fansly_backend = type(
            "_B", (), {"get_client": staticmethod(lambda _aid: _Boom()),
                       "is_fansly": staticmethod(lambda _aid: True)})
        with _quiet_lane_errors():
            try:
                await fansly_revenue.run_one_tick(ACCT)
            except RuntimeError:
                return
        raise AssertionError("a broken feed returned cleanly instead of raising")
    asyncio.run(go())


def case_a_missing_session_is_reported_not_raised():
    """No captured session is a KNOWN state, not a fault — the OF lane reports
    it the same way, and it must not burn the failure budget."""
    async def go():
        await _seed_account()
        def _raise(_aid):
            raise FileNotFoundError("no session")
        fansly_revenue.fansly_backend = type(
            "_B", (), {"get_client": staticmethod(_raise),
                       "is_fansly": staticmethod(lambda _aid: True)})
        res = await fansly_revenue.run_one_tick(ACCT)
        assert res.error == "no_session", res
        assert res.rows_inserted == 0, res
    asyncio.run(go())


def case_a_mixed_page_banks_only_the_new_rows():
    """The dedup is a batched SELECT of known provider ids followed by inserts.
    The interesting case is a page where SOME rows are already banked — an
    all-known page (idempotency) does not exercise the filter."""
    async def go():
        await _seed_account()
        first = dict(LIVE_ROW, id="900642430324908111")
        second = dict(LIVE_ROW, id="900642430324908222", price_usd=7.0)
        _install([first])
        await fansly_revenue.run_one_tick(ACCT)           # bank the first
        _install([first, second])                          # 1 known + 1 new
        res = await fansly_revenue.run_one_tick(ACCT)
        assert res.rows_inserted == 1, f"the known row was re-banked: {res}"
        assert await _count_of(first["id"]) == 1
        assert await _count_of(second["id"]) == 1
        assert await _amount_of(second["id"]) == 700
    asyncio.run(go())


def case_a_banked_sale_survives_leaving_the_feed():
    """The module's central durability claim: the feed is one page with no
    cursor, so a sale scrolls off permanently. A row observed ONCE while it was
    visible must stay banked — and must not be re-inserted if it reappears."""
    async def go():
        await _seed_account()
        _install([LIVE_ROW])
        # Its own notification id: cases share one DB, so count only this sale.
        sale = dict(LIVE_ROW, id="900642430324908777")
        _install([sale])
        await fansly_revenue.run_one_tick(ACCT)
        _install([])                     # the sale scrolls off the one-page feed
        await fansly_revenue.run_one_tick(ACCT)
        assert await _count_of(sale["id"]) == 1, "a banked sale was lost when it scrolled off"
        _install([sale])                 # ...and later reappears
        await fansly_revenue.run_one_tick(ACCT)
        assert await _count_of(sale["id"]) == 1, "a reappearing sale was banked twice"
    asyncio.run(go())


def case_scan_state_records_success_without_disarming_backoff():
    """The success stamp must clear the failure counters (that is what success
    means) but must NOT force `paused_until` to None: doing that on every tick
    turned a one-off repair into permanently disabled backoff."""
    async def go():
        await _seed_account()
        async with get_session() as s:
            row = await s.get(TransactionScanHistory, ACCT)
            if row is None:
                row = TransactionScanHistory(account_id=ACCT)
                s.add(row)
            row.consecutive_failures = 3
            row.last_error = "boom"
            row.paused_until = datetime(2099, 1, 1)
        _install([LIVE_ROW])
        await fansly_revenue.run_one_tick(ACCT)
        async with get_session() as s:
            row = await s.get(TransactionScanHistory, ACCT)
        assert row.current_status == "ok", row.current_status
        assert row.consecutive_failures == 0, row.consecutive_failures
        assert row.last_error is None, row.last_error
        assert row.fully_backfilled is True, row.fully_backfilled
        assert row.paused_until == datetime(2099, 1, 1), \
            "a successful tick force-cleared paused_until, disarming backoff"
    asyncio.run(go())


def case_one_id_repeated_in_a_page_is_banked_once():
    """A notification id repeated WITHIN one feed page must bank once — and
    must not take the rest of the page down with it. The unique index alone
    prevents the double-count, but as an IntegrityError at flush: the whole
    tick dies, the other sales on that page are lost, and the account burns a
    failure strike over a data quirk."""
    async def go():
        await _seed_account()
        dup = dict(LIVE_ROW, id="900642430324909333", price_usd=3.0)
        other = dict(LIVE_ROW, id="900642430324909444", price_usd=5.0)
        before = await _spend()
        _install([dict(dup), dict(dup), other])
        res = await fansly_revenue.run_one_tick(ACCT)
        assert res.rows_inserted == 2, res
        assert len(await _rows_for(dup["id"])) == 1, "the repeated id banked twice"
        assert len(await _rows_for(other["id"])) == 1, "a later sale was lost"
        assert await _spend() - before == 800, "spend disagrees with the ledger"
    asyncio.run(go())


def case_the_fast_poll_seam_banks_too():
    """The 30s loop is a SECOND entry point (run_fast_tick), not covered by
    the supervisor seam. It was a permanently dead path for Fansly — it built
    an OFClient, got none, and returned `no_session` forever — so a Fansly
    seller sat on the 5-minute cadence while the loop that exists to close an
    open offer in seconds did nothing."""
    async def go():
        await _seed_account()
        import transaction_ingest as ti
        ti.fansly_backend = type("_B", (), {"is_fansly": staticmethod(lambda _a: True)})
        _install([dict(LIVE_ROW, id="900642430324909111", price_usd=2.0)])
        res = await ti.run_fast_tick(ACCT)
        assert res["rows_inserted"] == 1, res
        rows = await _rows_for("900642430324909111")
        assert len(rows) == 1 and rows[0].amount_cents == 200, rows
        # ...and it dedups against the supervisor lane, sharing one ledger.
        again = await ti.run_fast_tick(ACCT)
        assert again["rows_inserted"] == 0, again
        assert len(await _rows_for("900642430324909111")) == 1
    asyncio.run(go())


def case_a_fresh_banked_sale_is_announced_once():
    """Each recent sale the tick banks is a `transaction_recorded` SSE event,
    as the OF lane's, so the fan drawer and the live dashboards refetch; the
    fan id stays a string (a snowflake is past JS's 2^53). A row older than
    48h, or one already banked, announces nothing."""
    import events
    sent: list[dict] = []

    async def _capture(event):
        sent.append(event)
        return 1

    async def go():
        await _seed_account()
        now = int(datetime.utcnow().timestamp())
        fresh = dict(LIVE_ROW, id="900642430399000001", created_at=now - 60)
        _install([fresh, dict(LIVE_ROW, id="900642430399000002")])
        real, events.broadcast = events.broadcast, _capture
        try:
            first = await fansly_revenue.run_one_tick(ACCT)
            assert first.rows_inserted == 2, first
            await fansly_revenue.run_one_tick(ACCT)
        finally:
            events.broadcast = real
        assert sent == [{"transaction_recorded": {
            "fan_id": FAN, "kind": "ppv_message", "status": "cleared", "reason": "insert"},
            "__account_id": ACCT}], sent
    asyncio.run(go())


def case_a_failed_tick_is_counted_exactly_once_on_both_paths():
    """Failure accounting is the CALLER's job, and both callers must do it
    exactly once. The lane deliberately does not self-report: the supervisor
    already records, so recording here too would double-count and trip the
    3-strike pause after 2 real failures. The fast-poll loop used to only
    `log.debug`, so a dead session failed 120x an hour and recorded nothing."""
    class _Boom:
        def purchases(self):
            raise RuntimeError("fansly 500")

        def unbanked_purchase_codes(self):
            return set()

    async def go():
        await _seed_account()
        import transaction_ingest as ti
        ti.fansly_backend = type("_B", (), {"is_fansly": staticmethod(lambda _a: True)})
        fansly_revenue.fansly_backend = type(
            "_B", (), {"get_client": staticmethod(lambda _a: _Boom()),
                       "is_fansly": staticmethod(lambda _a: True)})

        async def failures():
            async with get_session() as s:
                row = await s.get(TransactionScanHistory, ACCT)
                return row.consecutive_failures or 0

        async with get_session() as s:
            row = await s.get(TransactionScanHistory, ACCT)
            if row is None:
                row = TransactionScanHistory(account_id=ACCT)
                s.add(row)
            row.consecutive_failures = 0
            row.paused_until = None
        # Both entry points must RAISE so their caller can record.
        for run in (lambda: ti.run_one_tick(ACCT, mode="refresh"),
                    lambda: ti.run_fast_tick(ACCT)):
            before = await failures()
            with _quiet_lane_errors():
                try:
                    await run()
                except Exception as e:
                    await ti._record_failure(ACCT, e)
                else:
                    raise AssertionError(
                        "a broken feed returned cleanly instead of raising")
            moved = await failures() - before
            assert moved == 1, f"one failed tick counted {moved} times"
    asyncio.run(go())


# No argument list: the harness runs every `case_*` in definition order. A
# hand-maintained list is bookkeeping whose failure mode is a test that
# silently never runs.
_harness.run()
