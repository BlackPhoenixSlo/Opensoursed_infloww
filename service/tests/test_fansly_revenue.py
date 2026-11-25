#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import select  # noqa: E402

import accounts as account_registry  # noqa: E402
import fansly_backend  # noqa: E402
import fansly_revenue  # noqa: E402
import platforms  # noqa: E402
import transaction_ingest  # noqa: E402
import stats  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Transaction, TransactionScanHistory  # noqa: E402
from fansly_shim import FanslyShimClient  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="fansly_revenue_")
account_registry.SESSIONS_DIR = Path(_TMP.name)
account_registry.ACCOUNTS_DIR = Path(_TMP.name) / "accounts"
account_registry.ACTIVE_FILE = Path(_TMP.name) / "active.json"
account_registry.MIGRATED_MARKER = Path(_TMP.name) / ".migrated"

ACCT = "700237824869654528"
FAN = "900604711209099264"

LIVE_ROW = {
    "id": "900642430324908036",
    "fan_id": FAN,
    "grant_id": "900640044332167168",
    "price_usd": 3.0,
    "created_at": 1788335912,
    "code": 2007,
}


class _FeedStub:

    def __init__(self, rows):
        self._rows = rows
        self.calls = 0

    def purchases(self):
        self.calls += 1
        return {"sales": list(self._rows), "unbanked_seen": {}}


class _quiet_lane_errors:

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


@contextlib.contextmanager
def _fansly_in_registry():
    real = platforms.for_account
    platforms.for_account = lambda _aid: platforms.FANSLY
    try:
        yield
    finally:
        platforms.for_account = real


def _install(monkey_rows):
    stub = _FeedStub(monkey_rows)
    fansly_revenue.fansly_backend = type(
        "_B", (), {"get_client": staticmethod(lambda _aid: stub)}
    )
    return stub



def case_live_capture_shape_parses():
    sale = fansly_revenue.parse_purchase(LIVE_ROW)
    assert sale is not None, "the live $3 capture must parse"
    assert sale.provider_id == "900642430324908036", sale
    assert sale.fan_id == int(FAN), sale
    assert sale.amount_cents == 300, sale
    assert sale.occurred_at == datetime(2026, 9, 2, 7, 58, 32), sale.occurred_at
    assert "900640044332167168" in sale.description, sale.description


def case_rounding_is_half_up_and_exact():
    for usd, want in [(3.0, 300), (101.0, 10100),
                      (0.005, 1), (0.015, 2), (0.025, 3), (0.035, 4),
                      (0.004, None),
                      (0.999, 100), (1.005, 101), (1.015, 102),
                      (10 ** 9, 10 ** 11)]:
        got = fansly_revenue._cents(usd)
        assert got == want, f"${usd} -> {got}, want {want}"


def case_an_absurd_price_drops_its_row_not_the_page():
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
    for usd in (0, 0.0, -3.0, None, "", "abc", float("nan")):
        row = dict(LIVE_ROW, price_usd=usd)
        assert fansly_revenue.parse_purchase(row) is None, f"price {usd!r} banked"


def case_missing_buyer_or_id_banks_nothing():
    for buyer in (None, "", "0", "not-a-number"):
        row = dict(LIVE_ROW, fan_id=buyer)
        assert fansly_revenue.parse_purchase(row) is None, f"buyer {buyer!r} banked"
    for bad_id in (None, "", "   "):
        assert fansly_revenue.parse_purchase(dict(LIVE_ROW, id=bad_id)) is None


def case_an_unreadable_timestamp_is_dropped_not_faked():
    for ts in (None, "", "not-a-number", float("inf")):
        row = dict(LIVE_ROW, created_at=ts)
        assert fansly_revenue.parse_purchase(row) is None, f"timestamp {ts!r} was faked"


def case_snowflake_buyer_survives():
    sale = fansly_revenue.parse_purchase(LIVE_ROW)
    assert str(sale.fan_id) == FAN, f"{sale.fan_id} != {FAN}"
    assert sale.fan_id > 2 ** 53


def case_the_source_row_is_kept_for_audit():
    sale = fansly_revenue.parse_purchase(LIVE_ROW)
    assert "900642430324908036" in sale.raw_json, sale.raw_json



async def _spend() -> int:
    async with get_session() as s:
        fan = await s.get(Fan, (ACCT, int(FAN)))
        return (fan.lifetime_spend_cents or 0) if fan else 0


async def _count_of(provider_id: str) -> int:
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
        # grant id goes in description, not message_id: that column joins onto OUR messages table
        assert t.message_id is None, t.message_id
        assert "900640044332167168" in (t.description or "")
    asyncio.run(go())


def case_tick_is_idempotent():
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
    r = await stats.revenue(account_id=ACCT, from_=None, to=None,
                            group_by="kind", include_net=False, by_kind=False, status="tracked")
    return sum(row["total_cents"] for row in r["rows"]
               if str(row["kind"]).startswith("ppv"))


def case_ppv_message_reaches_the_ppv_bucket():
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
    class _Boom:
        def purchases(self):
            raise RuntimeError("fansly 500")

    async def go():
        await _seed_account()
        fansly_revenue.fansly_backend = type(
            "_B", (), {"get_client": staticmethod(lambda _aid: _Boom())})
        with _quiet_lane_errors():
            try:
                await fansly_revenue.run_one_tick(ACCT)
            except RuntimeError:
                return
        raise AssertionError("a broken feed returned cleanly instead of raising")
    asyncio.run(go())


def case_a_missing_session_is_reported_not_raised():
    async def go():
        await _seed_account()
        def _raise(_aid):
            raise FileNotFoundError("no session")
        fansly_revenue.fansly_backend = type(
            "_B", (), {"get_client": staticmethod(_raise)})
        res = await fansly_revenue.run_one_tick(ACCT)
        assert res.error == "no_session", res
        assert res.rows_inserted == 0, res
    asyncio.run(go())


def case_a_mixed_page_banks_only_the_new_rows():
    async def go():
        await _seed_account()
        first = dict(LIVE_ROW, id="900642430324908111")
        second = dict(LIVE_ROW, id="900642430324908222", price_usd=7.0)
        _install([first])
        await fansly_revenue.run_one_tick(ACCT)
        _install([first, second])
        res = await fansly_revenue.run_one_tick(ACCT)
        assert res.rows_inserted == 1, f"the known row was re-banked: {res}"
        assert await _count_of(first["id"]) == 1
        assert await _count_of(second["id"]) == 1
        assert await _amount_of(second["id"]) == 700
    asyncio.run(go())


def case_a_banked_sale_survives_leaving_the_feed():
    async def go():
        await _seed_account()
        _install([LIVE_ROW])
        sale = dict(LIVE_ROW, id="900642430324908777")
        _install([sale])
        await fansly_revenue.run_one_tick(ACCT)
        _install([])
        await fansly_revenue.run_one_tick(ACCT)
        assert await _count_of(sale["id"]) == 1, "a banked sale was lost when it scrolled off"
        _install([sale])
        await fansly_revenue.run_one_tick(ACCT)
        assert await _count_of(sale["id"]) == 1, "a reappearing sale was banked twice"
    asyncio.run(go())


def case_scan_state_records_success_without_disarming_backoff():
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
    async def go():
        await _seed_account()
        import purchase_poll as pp
        _install([dict(LIVE_ROW, id="900642430324909111", price_usd=2.0)])
        with _fansly_in_registry():
            res = await pp.run_fast_tick(ACCT)
            assert res["rows_inserted"] == 1, res
            rows = await _rows_for("900642430324909111")
            assert len(rows) == 1 and rows[0].amount_cents == 200, rows
            again = await pp.run_fast_tick(ACCT)
        assert again["rows_inserted"] == 0, again
        assert len(await _rows_for("900642430324909111")) == 1
    asyncio.run(go())


def case_a_fresh_banked_sale_is_announced_once():
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
    class _Boom:
        def purchases(self):
            raise RuntimeError("fansly 500")

    async def go():
        await _seed_account()
        import purchase_poll as pp
        import transaction_ingest as ti
        fansly_revenue.fansly_backend = type(
            "_B", (), {"get_client": staticmethod(lambda _a: _Boom())})

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
        for run in (lambda: ti.run_one_tick(ACCT, mode="refresh"),
                    lambda: pp.run_fast_tick(ACCT)):
            before = await failures()
            with _quiet_lane_errors(), _fansly_in_registry():
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


BUYER = "900604711209099999"


class _NotificationFeed(FanslyShimClient):
    def __init__(self, rows, acct):
        self.rows = rows
        self.session = type("_S", (), {"account_id": acct})()

    def _request(self, method, path, **_kw):
        assert (method, path) == ("GET", "/notifications"), (method, path)
        return {"notifications": [dict(r) for r in self.rows]}


def _raw(nid, code, meta=None, grant="900640044332160000"):
    row = {"id": nid, "type": code, "correlationId": grant,
           "correlationGroupId": BUYER, "createdAt": 1788335912}
    if meta is not None:
        row["metadata"] = json.dumps(meta)
    return row


def _seen_line(acct, counts):
    return f"fansly_revenue_unbanked_seen account={acct} counts={counts}"


async def _shim_tick(acct, rows):
    account_registry.save_meta(acct, {"id": acct, "nickname": acct, "platform": "fansly"})
    async with get_session() as s:
        if await s.get(Account, acct) is None:
            s.add(Account(id=acct, nickname="shimfeed"))
    feed = _NotificationFeed(rows, acct)
    fansly_revenue.fansly_backend = fansly_backend
    fansly_backend._pool[acct] = feed
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    lg = logging.getLogger("of-relay.fansly_revenue")
    prior = lg.level
    lg.addHandler(handler)
    lg.setLevel(logging.INFO)
    try:
        res = await transaction_ingest.run_one_tick(acct, mode="refresh")
    finally:
        lg.removeHandler(handler)
        lg.setLevel(prior)
    seen = [r.getMessage() for r in records
            if r.getMessage().startswith("fansly_revenue_unbanked_seen")]
    return res, seen, feed


async def _shim_rows(acct, *ids):
    async with get_session() as s:
        return (await s.execute(select(Transaction).where(
            Transaction.account_id == acct,
            Transaction.provider_transaction_id.in_(ids)))).scalars().all()


def case_unlock_codes_bank_nothing_and_still_unlock():
    async def go():
        acct = "700237824869654771"
        rows = [_raw("900999000000002008", 2008, {"price": 3000}, grant="g2008"),
                _raw("900999000000032007", 32007, {"amount": 3000}, grant="g32007")]
        res, seen, feed = await _shim_tick(acct, rows)
        assert res["rows_inserted"] == 0, res
        assert await _shim_rows(acct, *(r["id"] for r in rows)) == []
        assert seen == [_seen_line(acct, '{"2008": 1, "32007": 1}')], seen
        assert feed._purchases_by_fan()[BUYER] == {"g2008", "g32007"}
    asyncio.run(go())


def case_a_2007_without_account_media_price_banks_nothing():
    async def go():
        acct = "700237824869654772"
        rows = [_raw("900999000000012007", 2007, {"price": 3000}),
                _raw("900999000000022007", 2007, {"amount": 3000}),
                _raw("900999000000042007", 2007),
                _raw("900999000000062007", 2007, {"accountMediaPrice": -3000}),
                _raw("900999000000072007", 2007, {"accountMediaPrice": "abc"})]
        res, seen, _ = await _shim_tick(acct, rows)
        assert res["rows_inserted"] == 0, res
        assert await _shim_rows(acct, *(r["id"] for r in rows)) == []
        assert seen == [_seen_line(acct, '{"2007_unpriced": 5}')], seen
    asyncio.run(go())


def case_a_priced_2007_banks_once_across_two_ticks():
    async def go():
        acct = "700237824869654773"
        nid = "900999000000052007"
        rows = [_raw(nid, 2007, {"accountMediaPrice": 3000})]
        first, seen, _ = await _shim_tick(acct, rows)
        second, _, _ = await _shim_tick(acct, rows)
        assert (first["rows_inserted"], second["rows_inserted"]) == (1, 0), (first, second)
        assert seen == [], seen
        txs = await _shim_rows(acct, nid)
        assert [(t.kind, t.amount_cents, t.net_cents, t.fee_cents, t.status, t.currency)
                for t in txs] == [("ppv_message", 300, None, None, "cleared", "USD")], txs
        async with get_session() as s:
            fan = await s.get(Fan, (acct, int(BUYER)))
        assert fan.lifetime_spend_cents == 300, fan.lifetime_spend_cents
    asyncio.run(go())


def case_a_page_without_sales_logs_its_seen_codes():
    async def go():
        acct = "700237824869654774"
        rows = [_raw("900999000000017001", 7001, {"amount": 500}),
                _raw("900999000000027001", 7001),
                _raw("900999000000015016", 15016, {"subscriptionStreak": 0}),
                _raw("900999000000013003", 3003)]
        res, seen, _ = await _shim_tick(acct, rows)
        assert res["rows_inserted"] == 0, res
        assert await _shim_rows(acct, *(r["id"] for r in rows)) == []
        assert seen == [_seen_line(acct, '{"15016": 1, "7001": 2}')], seen
    asyncio.run(go())


def case_seen_counts_log_only_when_they_change_per_account():
    async def go():
        acct, other = "700237824869654775", "700237824869654776"
        tip = [_raw("900999000000037001", 7001)]
        two = tip + [_raw("900999000000047001", 7001)]
        social = [_raw("900999000000033003", 3003)]
        logged = [(await _shim_tick(acct, page))[1]
                  for page in (tip, tip, two, two, social, social)]
        assert logged == [[_seen_line(acct, '{"7001": 1}')], [],
                          [_seen_line(acct, '{"7001": 2}')], [],
                          [_seen_line(acct, "{}")], []], logged
        assert (await _shim_tick(other, tip))[1] == [_seen_line(other, '{"7001": 1}')]
    asyncio.run(go())


_harness.run()
