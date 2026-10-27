#!/usr/bin/env python3
"""
Orphan sales: credited by Converters' rule, never by a written override.

A sale whose linked message carries no sender, or a tip with no message, used
to be filled by `attribution_backfill.attribute_orphans` (run after each
ingest scan): a manual `transactions.attributed_employee_id` for the fan's
sole 1:1 sender of 7 days, the Automation Employee included. Converters now
credits such a sale by rule (the last human chatter who messaged the fan
within the window, 1 h by default; `tx_rollup.converter_lookback`), and an
override would beat the rule, so the sweep is gone. These cases prove, on the
stored credit (`transactions.credit_*`, written by the triggers) and on the
attribution view, that what the sweep used to fill is now the rule's answer:

  case_orphan_ppv_credited_to_the_last_chatter_in_the_hour:
      a PPV whose message has no sender goes to the human chatter who wrote
      20 min before; the override stays NULL.
  case_several_chatters_the_last_one_wins:
      two humans in the hour: the later one (the sweep left this ambiguous).
  case_the_automation_employee_and_a_mass_blast_are_no_touch:
      the Automation Employee's 1:1 send and a mass blast after the human's
      chat leave the human credited; with only them, nobody.
  case_a_stale_touch_credits_nobody:
      a tip whose only touch is 2 h old stays Unattributed (the sweep
      credited 7 days back).
  case_an_override_still_wins:
      a sale reassigned by hand keeps its Employee.
  case_ingest_writes_no_override:
      transaction_ingest no longer imports or runs a sweep.

Run: ./venv/bin/python service/tests/test_attribution_backfill.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select, text  # noqa: E402

import attribution_backfill  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Employee, MassRun, Message, Transaction  # noqa: E402

AID = "acc1"
AUTOMATION = 2   # the system "Automation" sentinel employee (inactive, as employees creates it)
HUMAN = 10       # a human chatter mirror employee
HUMAN_2 = 11
SALE = datetime(2026, 6, 20, 12, 0, 0)


def _ok(name: str) -> None:
    print(f"  ✓ {name}")


async def _seed_base() -> None:
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID, nickname="Acc 1"))
        if await s.get(Employee, AUTOMATION) is None:
            s.add(Employee(id=AUTOMATION, display_name="Automation", is_active=False))
        for eid, name in ((HUMAN, "santan1"), (HUMAN_2, "santan2")):
            if await s.get(Employee, eid) is None:
                s.add(Employee(id=eid, display_name=name, is_active=True))
        if await s.get(MassRun, 77) is None:
            s.add(MassRun(id=77, account_id=AID, status="ok"))


def _msg(fan_id: int, message_id: int, when: datetime, sender: int | None,
         *, price_cents: int = 0, mass_run_id: int | None = None) -> Message:
    return Message(
        account_id=AID, fan_id=fan_id, message_id=message_id, direction="out",
        body="x", media_count=0, price_cents=price_cents, is_paid=bool(price_cents) or None,
        sent_by_employee_id=sender, mass_run_id=mass_run_id,
        created_at=when, ingested_at=when,
    )


def _sale(fan_id: int, cents: int, message_id: int | None = None, kind: str = "ppv_message",
          manual: int | None = None) -> Transaction:
    return Transaction(account_id=AID, fan_id=fan_id, message_id=message_id, kind=kind, amount_cents=cents,
                       currency="USD", occurred_at=SALE, status="pending", attributed_employee_id=manual)


async def _credit(fan_id: int) -> tuple:
    """(override, credited Employee, rule) of the fan's sale, and the view's Employee and rule for it."""
    async with get_session() as s:
        t = (await s.execute(
            select(Transaction.id, Transaction.attributed_employee_id, Transaction.credit_employee_id,
                   Transaction.credit_rule)
            .where(Transaction.account_id == AID, Transaction.fan_id == fan_id))).one()
        v = (await s.execute(text(
            "SELECT sent_by_employee_id, rule FROM per_employee_revenue_with_attribution WHERE tx_id = :t"),
            {"t": t.id})).one()
    assert (t.credit_employee_id, t.credit_rule) == tuple(v), ("stored credit != view", t, v)
    return t.attributed_employee_id, t.credit_employee_id, t.credit_rule


async def case_orphan_ppv_credited_to_the_last_chatter_in_the_hour() -> None:
    await _seed_base()
    fan = 101
    async with get_session() as s:
        s.add(_msg(fan, 5001, SALE - timedelta(days=2), None, price_cents=20000))  # the PPV: no sender
        s.add(_msg(fan, 4001, SALE - timedelta(minutes=20), HUMAN))
        s.add(_sale(fan, 20000, 5001))
    assert await _credit(fan) == (None, HUMAN, "converters")
    _ok("case_orphan_ppv_credited_to_the_last_chatter_in_the_hour")


async def case_several_chatters_the_last_one_wins() -> None:
    await _seed_base()
    fan = 109
    async with get_session() as s:
        s.add(_msg(fan, 5090, SALE - timedelta(days=2), None, price_cents=20000))
        s.add(_msg(fan, 4091, SALE - timedelta(minutes=50), HUMAN))
        s.add(_msg(fan, 4092, SALE - timedelta(minutes=5), HUMAN_2))
        s.add(_sale(fan, 20000, 5090))
    assert await _credit(fan) == (None, HUMAN_2, "converters")
    _ok("case_several_chatters_the_last_one_wins")


async def case_the_automation_employee_and_a_mass_blast_are_no_touch() -> None:
    await _seed_base()
    fan, alone = 108, 110
    async with get_session() as s:
        s.add(_msg(fan, 5800, SALE - timedelta(days=2), None, price_cents=13579))
        s.add(_msg(fan, 4802, SALE - timedelta(minutes=40), HUMAN))
        s.add(_msg(fan, 4801, SALE - timedelta(minutes=10), AUTOMATION, mass_run_id=77))
        s.add(_msg(fan, 4803, SALE - timedelta(minutes=5), AUTOMATION))
        s.add(_sale(fan, 13579, 5800))
        s.add(_msg(alone, 4811, SALE - timedelta(minutes=10), HUMAN, mass_run_id=77))
        s.add(_msg(alone, 4812, SALE - timedelta(minutes=5), AUTOMATION))
        s.add(_sale(alone, 300, kind="tip"))
    assert await _credit(fan) == (None, HUMAN, "converters")
    assert await _credit(alone) == (None, None, "unassigned")
    _ok("case_the_automation_employee_and_a_mass_blast_are_no_touch")


async def case_a_stale_touch_credits_nobody() -> None:
    await _seed_base()
    fan = 102
    async with get_session() as s:
        s.add(_msg(fan, 4201, SALE - timedelta(hours=2), HUMAN))
        s.add(_sale(fan, 900, kind="tip"))
    assert await _credit(fan) == (None, None, "unassigned")
    _ok("case_a_stale_touch_credits_nobody")


async def case_an_override_still_wins() -> None:
    await _seed_base()
    fan = 104
    async with get_session() as s:
        s.add(_msg(fan, 5300, SALE - timedelta(days=1), None, price_cents=1000))
        s.add(_msg(fan, 4300, SALE - timedelta(minutes=2), HUMAN_2))
        s.add(_sale(fan, 1000, 5300, manual=HUMAN))
    assert await _credit(fan) == (HUMAN, HUMAN, "manual")
    _ok("case_an_override_still_wins")


async def case_ingest_writes_no_override() -> None:
    import transaction_ingest
    assert not hasattr(attribution_backfill, "attribute_orphans")
    assert not hasattr(transaction_ingest, "attribute_orphans")
    async with get_session() as s:
        overrides = (await s.execute(text(
            "SELECT COUNT(*) FROM transactions WHERE attributed_employee_id IS NOT NULL"))).scalar()
    assert overrides == 1, f"only the hand-set override exists, got {overrides}"
    _ok("case_ingest_writes_no_override")


async def main() -> None:
    await case_orphan_ppv_credited_to_the_last_chatter_in_the_hour()
    await case_several_chatters_the_last_one_wins()
    await case_the_automation_employee_and_a_mass_blast_are_no_touch()
    await case_a_stale_touch_credits_nobody()
    await case_an_override_still_wins()
    await case_ingest_writes_no_override()
    print("ALL PASS — test_attribution_backfill")


if __name__ == "__main__":
    asyncio.run(main())
