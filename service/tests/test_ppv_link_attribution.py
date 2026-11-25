#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select, text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Employee, Message, Transaction, UserAccount  # noqa: E402
from transaction_ingest import _link_ppv_message, relink_orphan_ppvs  # noqa: E402

_IDS = fx.seed_two_agencies()
_OWNER = "agency_a_owner"

AID = "acc1"
AUTOMATION = 2
BILL = 21
SALE = datetime(2026, 6, 20, 12, 0, 0)


def _ok(name: str) -> None:
    print(f"  ✓ {name}")


async def _seed_base() -> None:
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID, nickname="Acc 1"))
        if await s.get(Employee, AUTOMATION) is None:
            s.add(Employee(id=AUTOMATION, display_name="Automation", is_active=False))
        if await s.get(Employee, BILL) is None:
            s.add(Employee(id=BILL, display_name="Bill", is_active=True,
                           user_id=_IDS[_OWNER]))
    async with get_session() as s:
        if await s.get(UserAccount, (_IDS[_OWNER], AID)) is None:
            s.add(UserAccount(user_id=_IDS[_OWNER], account_id=AID))


async def _create_view() -> None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "db", "migrations", "versions",
                        "20261027_0100_converters_window.py")
    spec = importlib.util.spec_from_file_location("mig0099", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    async with get_session() as s:
        await s.execute(text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
        await s.execute(text(mig._NEW_VIEW_SQL))


def _msg(fan_id: int, message_id: int, when: datetime, sender: int | None,
         *, price_cents: int = 0, is_paid=None,
         mass_run_id: int | None = None) -> Message:
    return Message(
        account_id=AID, fan_id=fan_id, message_id=message_id, direction="out",
        body="x", media_count=0, price_cents=price_cents, is_paid=is_paid,
        sent_by_employee_id=sender, mass_run_id=mass_run_id,
        created_at=when, ingested_at=when,
    )


def _tx(fan_id: int, *, kind: str = "ppv_message", cents: int = 3000,
        occurred: datetime = SALE, message_id: int | None = None,
        attributed: int | None = None, status: str = "cleared") -> Transaction:
    return Transaction(
        account_id=AID, fan_id=fan_id, kind=kind, message_id=message_id,
        amount_cents=cents, currency="USD", occurred_at=occurred,
        status=status, attributed_employee_id=attributed,
    )


async def _link_inline(tx_row: Transaction) -> bool:
    async with get_session() as s:
        tx = (await s.execute(
            select(Transaction).where(Transaction.id == tx_row.id)
        )).scalar_one()
        return await _link_ppv_message(
            s, account_id=AID, fan_id=tx.fan_id,
            amount_cents=tx.amount_cents, occurred_at=tx.occurred_at, tx=tx,
        )


async def _tx_state(tx_id: int) -> tuple[int | None, int | None]:
    async with get_session() as s:
        row = (await s.execute(
            select(Transaction.message_id, Transaction.attributed_employee_id)
            .where(Transaction.id == tx_id)
        )).one()
    return (
        int(row.message_id) if row.message_id is not None else None,
        int(row.attributed_employee_id) if row.attributed_employee_id is not None else None,
    )


async def _msg_state(fan_id: int, message_id: int) -> tuple[bool | None, datetime | None]:
    async with get_session() as s:
        row = (await s.execute(
            select(Message.is_paid, Message.purchased_at).where(
                Message.account_id == AID,
                Message.fan_id == fan_id,
                Message.message_id == message_id,
            )
        )).one()
    return row.is_paid, row.purchased_at



async def case_race_paid_message_still_links() -> None:
    await _seed_base()
    fan = 201
    async with get_session() as s:
        s.add(_msg(fan, 20101, SALE - timedelta(days=3), AUTOMATION, price_cents=3000))
        s.add(_msg(fan, 20102, SALE - timedelta(minutes=5), BILL,
                   price_cents=3000, is_paid=True))
        tx = _tx(fan)
        s.add(tx)
        await s.flush()
        tx_id = tx.id
    async with get_session() as s:
        tx = (await s.execute(select(Transaction).where(Transaction.id == tx_id))).scalar_one()
        linked = await _link_ppv_message(
            s, account_id=AID, fan_id=fan, amount_cents=3000,
            occurred_at=SALE, tx=tx,
        )
        assert linked, "flipped-paid message must be linkable"
    mid, _ = await _tx_state(tx_id)
    assert mid == 20102, f"must link Bill's flipped message, got {mid}"
    _ok("case_race_paid_message_still_links")


async def case_automation_keeps_its_own_sale() -> None:
    await _seed_base()
    fan = 202
    async with get_session() as s:
        s.add(_msg(fan, 20201, SALE - timedelta(days=2), AUTOMATION,
                   price_cents=3000, is_paid=True))
        s.add(_msg(fan, 20202, SALE - timedelta(minutes=10), BILL, price_cents=3000))
        tx = _tx(fan)
        s.add(tx)
        await s.flush()
        tx_id = tx.id
    async with get_session() as s:
        tx = (await s.execute(select(Transaction).where(Transaction.id == tx_id))).scalar_one()
        assert await _link_ppv_message(
            s, account_id=AID, fan_id=fan, amount_cents=3000,
            occurred_at=SALE, tx=tx,
        )
    mid, _ = await _tx_state(tx_id)
    assert mid == 20201, f"automation's flipped message must win, got {mid}"
    _ok("case_automation_keeps_its_own_sale")


async def case_sequential_double_unlock_links_two_messages() -> None:
    await _seed_base()
    fan = 203
    async with get_session() as s:
        s.add(_msg(fan, 20301, SALE - timedelta(hours=2), BILL,
                   price_cents=3000, is_paid=True))
        s.add(_msg(fan, 20302, SALE - timedelta(hours=1), BILL,
                   price_cents=3000, is_paid=True))
    async with get_session() as s:
        m2 = (await s.execute(select(Message).where(
            Message.account_id == AID, Message.fan_id == fan,
            Message.message_id == 20302,
        ))).scalar_one()
        m2.is_paid = None
    tx1 = _tx(fan, occurred=SALE - timedelta(minutes=50))
    async with get_session() as s:
        s.add(tx1)
        await s.flush()
        tx1_id = tx1.id
    assert await _link_inline(tx1)
    mid1, _ = await _tx_state(tx1_id)
    assert mid1 == 20301, f"tick 1 links the flipped first message, got {mid1}"
    async with get_session() as s:
        m2 = (await s.execute(select(Message).where(
            Message.account_id == AID, Message.fan_id == fan,
            Message.message_id == 20302,
        ))).scalar_one()
        m2.is_paid = True
    tx2 = _tx(fan)
    async with get_session() as s:
        s.add(tx2)
        await s.flush()
        tx2_id = tx2.id
    assert await _link_inline(tx2)
    mid2, _ = await _tx_state(tx2_id)
    assert mid2 == 20302, f"tick 2 links the remaining message, got {mid2}"
    _ok("case_sequential_double_unlock_links_two_messages")


async def case_ambiguous_left_unlinked() -> None:
    await _seed_base()
    fan_a = 204
    async with get_session() as s:
        s.add(_msg(fan_a, 20401, SALE - timedelta(hours=3), BILL,
                   price_cents=3000, is_paid=True))
        s.add(_msg(fan_a, 20402, SALE - timedelta(hours=1), AUTOMATION,
                   price_cents=3000, is_paid=True))
        tx_a = _tx(fan_a)
        s.add(tx_a)
        await s.flush()
        tx_a_id = tx_a.id
    assert not await _link_inline(tx_a), "two paid candidates → must refuse"
    assert (await _tx_state(tx_a_id))[0] is None
    fan_b = 205
    async with get_session() as s:
        s.add(_msg(fan_b, 20501, SALE - timedelta(hours=3), BILL, price_cents=3000))
        s.add(_msg(fan_b, 20502, SALE - timedelta(hours=1), AUTOMATION, price_cents=3000))
        tx_b = _tx(fan_b)
        s.add(tx_b)
        await s.flush()
        tx_b_id = tx_b.id
    assert not await _link_inline(tx_b), "two unpaid candidates → must refuse"
    assert (await _tx_state(tx_b_id))[0] is None
    _ok("case_ambiguous_left_unlinked")



async def case_relink_dry_run_is_read_only() -> None:
    await _seed_base()
    fan = 206
    async with get_session() as s:
        s.add(_msg(fan, 20601, SALE - timedelta(minutes=5), BILL, price_cents=3000))
        tx = _tx(fan)
        s.add(tx)
        await s.flush()
        tx_id = tx.id
    stats = await relink_orphan_ppvs(account_id=AID, dry_run=True)
    assert stats["linked"] >= 1, stats
    assert any(j["tx_id"] == tx_id for j in stats["journal"]), stats["journal"]
    assert (await _tx_state(tx_id))[0] is None, "dry run must not write"
    paid, purchased = await _msg_state(fan, 20601)
    assert not paid and purchased is None, "dry run must not flip the message"
    _ok("case_relink_dry_run_is_read_only")


async def case_relink_fill_only_idempotent_and_stamp_paid() -> None:
    await _seed_base()
    fan = 206
    stats = await relink_orphan_ppvs(account_id=AID, stamp_paid=False)
    linked_ids = {j["tx_id"] for j in stats["journal"]}
    async with get_session() as s:
        tx_id = (await s.execute(
            select(Transaction.id).where(
                Transaction.account_id == AID, Transaction.fan_id == fan,
            )
        )).scalar_one()
    assert tx_id in linked_ids, (stats, tx_id)
    mid, _ = await _tx_state(tx_id)
    assert mid == 20601
    paid, purchased = await _msg_state(fan, 20601)
    assert not paid and purchased is None, "bulk mode must not mutate the message"
    again = await relink_orphan_ppvs(account_id=AID)
    assert all(j["tx_id"] != tx_id for j in again["journal"]), again
    _ok("case_relink_fill_only_idempotent_and_stamp_paid")


async def case_relink_same_price_race_two_orphans() -> None:
    await _seed_base()
    fan = 207
    t1 = SALE - timedelta(minutes=30)
    async with get_session() as s:
        s.add(_msg(fan, 20701, SALE - timedelta(hours=2), BILL,
                   price_cents=4500, is_paid=True))
        s.add(_msg(fan, 20702, SALE - timedelta(hours=1), BILL,
                   price_cents=4500))
        s.add(_tx(fan, cents=4500, occurred=t1))
        s.add(_tx(fan, cents=4500, occurred=SALE))
    stats = await relink_orphan_ppvs(account_id=AID, newest_first=False)
    assert stats["linked"] == 2, stats
    assert stats["conflict_skipped"] == 0, stats
    async with get_session() as s:
        mids = {int(m) for (m,) in (await s.execute(
            select(Transaction.message_id).where(
                Transaction.account_id == AID, Transaction.fan_id == fan,
            )
        )).all()}
    assert mids == {20701, 20702}, mids
    _ok("case_relink_same_price_race_two_orphans")



async def case_view_exactly_once() -> None:
    await _seed_base()
    await _create_view()
    fan = 208
    async with get_session() as s:
        s.add(_msg(fan, 20801, SALE - timedelta(hours=2), BILL,
                   price_cents=777, is_paid=True))
        s.add(_tx(fan, cents=777, message_id=20801))
        s.add(_tx(fan, kind="tip", cents=778))
        s.add(_tx(fan, cents=779))
        s.add(_tx(fan, cents=780, message_id=999_999_001))
        s.add(_tx(fan, kind="tip", cents=781, message_id=999_999_002,
                  attributed=BILL))
    async with get_session() as s:
        n = (await s.execute(text(
            "SELECT COUNT(*) FROM per_employee_revenue_with_attribution "
            "WHERE account_id = :a AND amount_cents BETWEEN 777 AND 781"
        ).bindparams(a=AID))).scalar_one()
    assert n == 5, f"each tx must emit exactly once, got {n}"
    _ok("case_view_exactly_once")


async def case_view_orphan_ppv_visibility_and_manual_assign() -> None:
    await _seed_base()
    await _create_view()
    fan = 209
    async with get_session() as s:
        tx = _tx(fan, cents=8888)
        s.add(tx)
        await s.flush()
        tx_id = tx.id

    async def _bucket_amount(emp: int | None) -> int:
        clause = ("sent_by_employee_id IS NULL" if emp is None
                  else "sent_by_employee_id = :e")
        stmt = text(
            "SELECT COALESCE(SUM(amount_cents), 0) "
            "FROM per_employee_revenue_with_attribution "
            f"WHERE account_id = :a AND amount_cents = 8888 AND {clause}"
        )
        stmt = stmt.bindparams(a=AID) if emp is None else stmt.bindparams(a=AID, e=emp)
        async with get_session() as s:
            return int((await s.execute(stmt)).scalar_one())

    assert await _bucket_amount(None) == 8888, "orphan ppv must show as Unattributed"
    assert await _bucket_amount(BILL) == 0
    async with get_session() as s:
        row = (await s.execute(
            select(Transaction).where(Transaction.id == tx_id)
        )).scalar_one()
        row.attributed_employee_id = BILL
    assert await _bucket_amount(BILL) == 8888, "manual assign must credit Bill"
    assert await _bucket_amount(None) == 0
    _ok("case_view_orphan_ppv_visibility_and_manual_assign")



async def case_per_employee_endpoint() -> None:
    await _seed_base()
    await _create_view()
    client = fx.login_owner(_OWNER)
    r = client.get("/admin/stats/per-employee?from=2026-06-01&to=2026-06-30")
    assert r.status_code == 200, r.text
    rows = r.json()["employees"]
    by_id = {row["employee_id"]: row for row in rows}
    bill = by_id.get(BILL)
    assert bill is not None, f"Bill row missing: {list(by_id)}"
    assert bill["ppv_conversions"] >= 1, bill
    unattr = by_id.get(None)
    assert unattr is not None, "Unattributed bucket missing"
    assert unattr["revenue_by_kind"]["ppv"] > 0, (
        f"orphan PPV revenue must show a real by-kind split: {unattr}"
    )
    for row in rows:
        folded = row["revenue_by_kind"]["ppv"] + row["revenue_by_kind"]["tip"]
        assert row["revenue_cents"] == folded, (row["employee_id"], row)
    _ok("case_per_employee_endpoint")


async def case_panel_lists_orphan_ppv() -> None:
    await _seed_base()
    fan = 210
    async with get_session() as s:
        tx = _tx(fan, cents=9999)
        s.add(tx)
        await s.flush()
        tx_id = tx.id
    client = fx.login_owner(_OWNER)
    url = ("/admin/ingest/transactions/sales-needing-attribution"
           "?from=2026-06-01&to=2026-06-30")
    rows = client.get(url).json()["rows"]
    mine = [r for r in rows if r["id"] == tx_id]
    assert mine, "unlinked PPV must appear in the manual panel (arm 3)"
    assert mine[0]["kind"] == "ppv_message"
    r = client.post(f"/admin/ingest/transactions/{tx_id}/attribute",
                    json={"employee_id": BILL})
    assert r.status_code == 200, r.text
    rows = client.get(url).json()["rows"]
    assert not [r for r in rows if r["id"] == tx_id], "assigned → hidden by default"
    rows = client.get(url + "&include_assigned=true").json()["rows"]
    got = [r for r in rows if r["id"] == tx_id]
    assert got and got[0]["attributed_employee_id"] == BILL, "reappears when included"
    _ok("case_panel_lists_orphan_ppv")


async def main() -> None:
    await case_race_paid_message_still_links()
    await case_automation_keeps_its_own_sale()
    await case_sequential_double_unlock_links_two_messages()
    await case_ambiguous_left_unlinked()
    await case_relink_dry_run_is_read_only()
    await case_relink_fill_only_idempotent_and_stamp_paid()
    await case_relink_same_price_race_two_orphans()
    await case_view_exactly_once()
    await case_view_orphan_ppv_visibility_and_manual_assign()
    await case_per_employee_endpoint()
    await case_panel_lists_orphan_ppv()
    print("ALL PASS — test_ppv_link_attribution")


if __name__ == "__main__":
    asyncio.run(main())
