#!/usr/bin/env python3
"""
attribution_backfill — orphan revenue attribution via last-toucher.

Covers the backfill that drains the per-employee stats "Unattributed" bucket by
stamping transactions.attributed_employee_id with the most recent outbound
message sender (human OR the Automation sentinel) to the same (account, fan).

  case_sole_chatter_credited:
      a PPV orphan whose fan had exactly ONE 1:1 chatter (Automation) in the
      window is auto-credited to it.
  case_ambiguous_left_for_manual:
      a PPV orphan whose fan had TWO distinct 1:1 chatters is NOT auto-credited
      (ambiguous) — it stays Unattributed for the manual panel.
  case_standalone_tip_beyond_window_stays_null:
      a tip whose only touch is 10 days old (> 7d window) is LEFT Unattributed
      — no unbounded fallback, we never force-credit a stale touch.
  case_mass_toucher_ignored:
      the fan's most-recent touch is a MASS blast; it is ignored and the sale
      is credited to the real 1:1 chatter — verified in the tx column AND in
      the live attribution view (not just the override column).
  case_already_attributed_untouched:
      a PPV whose message already carries a sender, and a tx with an explicit
      attributed_employee_id, are BOTH left alone (idempotent, no override).
  case_unresolved_stays_null:
      an orphan whose fan was never touched by an attributable sender is left
      NULL and counted as unresolved — we never invent a chatter.
  case_dry_run_writes_nothing:
      dry_run reports what it WOULD do but commits no changes.
  case_view_reflects_backfill:
      end-to-end — after the sweep the attribution view moves the revenue out
      of the NULL (Unattributed) bucket onto the credited employee.

Run: ./venv/bin/python service/tests/test_attribution_backfill.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import asyncio  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import func, select, text  # noqa: E402

from attribution_backfill import attribute_orphans  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Employee, MassRun, Message, Transaction  # noqa: E402

AID = "acc1"
AUTOMATION = 2   # the system "Automation" sentinel employee
HUMAN = 10       # a human chatter mirror employee
SALE = datetime(2026, 6, 20, 12, 0, 0)


def _ok(name: str) -> None:
    print(f"  ✓ {name}")


async def _seed_base() -> None:
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID, nickname="Acc 1"))
        if await s.get(Employee, AUTOMATION) is None:
            s.add(Employee(id=AUTOMATION, display_name="Automation", is_active=True))
        if await s.get(Employee, HUMAN) is None:
            s.add(Employee(id=HUMAN, display_name="santan1", is_active=True))


def _msg(fan_id: int, message_id: int, when: datetime, sender: int | None,
         *, price_cents: int = 0, is_paid=None, direction: str = "out",
         mass_run_id: int | None = None) -> Message:
    return Message(
        account_id=AID, fan_id=fan_id, message_id=message_id, direction=direction,
        body="x", media_count=0, price_cents=price_cents, is_paid=is_paid,
        sent_by_employee_id=sender, mass_run_id=mass_run_id,
        created_at=when, ingested_at=when,
    )


async def _tx_attr(fan_id: int) -> int | None:
    async with get_session() as s:
        return (await s.execute(
            select(Transaction.attributed_employee_id)
            .where(Transaction.account_id == AID, Transaction.fan_id == fan_id)
        )).scalar_one()


async def case_sole_chatter_credited() -> None:
    await _seed_base()
    fan = 101
    async with get_session() as s:
        # PPV orphan (null sender); exactly ONE 1:1 chatter (Automation) in window.
        s.add(_msg(fan, 5001, SALE - timedelta(days=2), None,
                   price_cents=20000, is_paid=True))
        s.add(_msg(fan, 4002, SALE - timedelta(days=1), AUTOMATION))
        s.add(Transaction(
            account_id=AID, fan_id=fan, message_id=5001, kind="ppv_message",
            amount_cents=20000, currency="USD", occurred_at=SALE, status="pending",
        ))
    await attribute_orphans(account_id=AID)
    assert await _tx_attr(fan) == AUTOMATION, "sole 1:1 chatter should be credited"
    _ok("case_sole_chatter_credited")


async def case_ambiguous_left_for_manual() -> None:
    await _seed_base()
    fan = 109
    async with get_session() as s:
        # TWO distinct 1:1 chatters (human + Automation) in window → AMBIGUOUS →
        # NOT auto-credited; it goes to the manual panel instead.
        s.add(_msg(fan, 5090, SALE - timedelta(days=2), None,
                   price_cents=20000, is_paid=True))
        s.add(_msg(fan, 4091, SALE - timedelta(days=3), HUMAN))
        s.add(_msg(fan, 4092, SALE - timedelta(days=1), AUTOMATION))
        s.add(Transaction(
            account_id=AID, fan_id=fan, message_id=5090, kind="ppv_message",
            amount_cents=20000, currency="USD", occurred_at=SALE, status="pending",
        ))
    await attribute_orphans(account_id=AID)
    assert await _tx_attr(fan) is None, "two chatters → ambiguous → left for manual"
    _ok("case_ambiguous_left_for_manual")


async def case_standalone_tip_beyond_window_stays_null() -> None:
    await _seed_base()
    fan = 102
    async with get_session() as s:
        # Only touch is 10 days before the tip — outside the 7-day window. With
        # no unbounded fallback, a sale nobody chatted within a week stays
        # Unattributed (ops' choice); v1 used to force-credit this.
        s.add(_msg(fan, 4100, SALE - timedelta(days=10), HUMAN))
        s.add(Transaction(
            account_id=AID, fan_id=fan, message_id=None, kind="tip",
            amount_cents=7500, currency="USD", occurred_at=SALE, status="cleared",
        ))

    await attribute_orphans(account_id=AID)
    assert await _tx_attr(fan) is None, "touch older than 7d must NOT be credited"
    _ok("case_standalone_tip_beyond_window_stays_null")


async def case_mass_toucher_ignored() -> None:
    await _seed_base()
    await _create_view()
    fan = 108
    async with get_session() as s:
        if await s.get(MassRun, 77) is None:
            s.add(MassRun(id=77, account_id=AID, status="ok"))
        # The purchased PPV message — no sender (the orphan).
        s.add(_msg(fan, 5800, SALE - timedelta(days=2), None,
                   price_cents=13579, is_paid=True))
        # Most-recent touch is a MASS blast by Automation (1d back) — must be
        # IGNORED. The real 1:1 chatter is the human 3d back.
        s.add(_msg(fan, 4801, SALE - timedelta(days=1), AUTOMATION, mass_run_id=77))
        s.add(_msg(fan, 4802, SALE - timedelta(days=3), HUMAN))
        s.add(Transaction(
            account_id=AID, fan_id=fan, message_id=5800, kind="ppv_message",
            amount_cents=13579, currency="USD", occurred_at=SALE, status="pending",
        ))

    await attribute_orphans(account_id=AID)
    # Column: the non-mass 1:1 human wins, not the more-recent mass Automation.
    assert await _tx_attr(fan) == HUMAN, "mass blast must be ignored; 1:1 human wins"

    # AND the live VIEW must credit the human, not the mass sender (isolate this
    # sale by its unique amount, since the view exposes no fan_id).
    async def _view_amt(emp: int) -> int:
        async with get_session() as s:
            return int((await s.execute(
                select(func.coalesce(func.sum(text("amount_cents")), 0))
                .select_from(text("per_employee_revenue_with_attribution"))
                .where(text("account_id = :a").bindparams(a=AID))
                .where(text("amount_cents = :c").bindparams(c=13579))
                .where(text("sent_by_employee_id = :e").bindparams(e=emp))
            )).scalar_one())
    assert await _view_amt(HUMAN) == 13579, "view must credit the human"
    assert await _view_amt(AUTOMATION) == 0, "view must NOT credit the mass sender"
    _ok("case_mass_toucher_ignored")


async def case_already_attributed_untouched() -> None:
    await _seed_base()
    # (a) PPV whose linked message already has a sender → not an orphan.
    fan_a = 103
    # (b) tx with an explicit override already set → must not be re-touched.
    fan_b = 104
    async with get_session() as s:
        s.add(_msg(fan_a, 5200, SALE - timedelta(days=1), HUMAN,
                   price_cents=1000, is_paid=True))
        s.add(Transaction(
            account_id=AID, fan_id=fan_a, message_id=5200, kind="ppv_message",
            amount_cents=1000, currency="USD", occurred_at=SALE, status="cleared",
        ))
        # fan_b: linked msg has no sender, but the tx already carries an override.
        s.add(_msg(fan_b, 5300, SALE - timedelta(days=1), None,
                   price_cents=1000, is_paid=True))
        s.add(_msg(fan_b, 4300, SALE - timedelta(days=2), AUTOMATION))
        s.add(Transaction(
            account_id=AID, fan_id=fan_b, message_id=5300, kind="ppv_message",
            amount_cents=1000, currency="USD", occurred_at=SALE, status="cleared",
            attributed_employee_id=HUMAN,
        ))

    await attribute_orphans(account_id=AID)
    # fan_a stays NULL on the tx (attribution flows from the message's sender,
    # not the override column) — the sweep must not pin it.
    assert await _tx_attr(fan_a) is None, "already-attributed message must not be overridden"
    assert await _tx_attr(fan_b) == HUMAN, "explicit override must be preserved"
    _ok("case_already_attributed_untouched")


async def case_unresolved_stays_null() -> None:
    await _seed_base()
    fan = 105
    async with get_session() as s:
        # Orphan PPV, and the fan's ONLY other outbound also has no sender →
        # nothing attributable to fall back to.
        s.add(_msg(fan, 5400, SALE - timedelta(days=1), None,
                   price_cents=500, is_paid=True))
        s.add(Transaction(
            account_id=AID, fan_id=fan, message_id=5400, kind="ppv_message",
            amount_cents=500, currency="USD", occurred_at=SALE, status="cleared",
        ))

    stats = await attribute_orphans(account_id=AID)
    assert stats["unresolved"] >= 1, stats
    assert await _tx_attr(fan) is None, "no toucher → left NULL, not invented"
    _ok("case_unresolved_stays_null")


async def case_dry_run_writes_nothing() -> None:
    await _seed_base()
    fan = 106
    async with get_session() as s:
        s.add(_msg(fan, 5500, SALE - timedelta(days=1), None,
                   price_cents=3000, is_paid=True))
        s.add(_msg(fan, 4500, SALE - timedelta(days=1, hours=1), AUTOMATION))
        s.add(Transaction(
            account_id=AID, fan_id=fan, message_id=5500, kind="ppv_message",
            amount_cents=3000, currency="USD", occurred_at=SALE, status="cleared",
        ))

    stats = await attribute_orphans(account_id=AID, dry_run=True)
    assert stats["attributed"] >= 1, stats
    assert await _tx_attr(fan) is None, "dry run must not write"
    # And a real run then commits it.
    await attribute_orphans(account_id=AID)
    assert await _tx_attr(fan) == AUTOMATION
    _ok("case_dry_run_writes_nothing")


async def _create_view() -> None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "db", "migrations", "versions",
                        "20260710_0200_attr_view_orphan_rows.py")
    spec = importlib.util.spec_from_file_location("mig0042", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    async with get_session() as s:
        await s.execute(text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
        await s.execute(text(mig._NEW_VIEW_SQL))


async def case_view_reflects_backfill() -> None:
    await _seed_base()
    await _create_view()
    fan = 107
    async with get_session() as s:
        s.add(_msg(fan, 5600, SALE - timedelta(days=1), None,
                   price_cents=20000, is_paid=True))
        s.add(_msg(fan, 4600, SALE - timedelta(days=1, hours=2), AUTOMATION))
        s.add(Transaction(
            account_id=AID, fan_id=fan, message_id=5600, kind="ppv_message",
            amount_cents=20000, currency="USD", occurred_at=SALE, status="pending",
        ))

    async def _view_rev(emp) -> int:
        async with get_session() as s:
            clause = (
                text("sent_by_employee_id IS NULL") if emp is None
                else text("sent_by_employee_id = :e").bindparams(e=emp)
            )
            return int((await s.execute(
                select(func.coalesce(func.sum(text("amount_cents")), 0))
                .select_from(text("per_employee_revenue_with_attribution"))
                .where(text("account_id = :a").bindparams(a=AID))
                .where(clause)
            )).scalar_one())

    before_null = await _view_rev(None)
    await attribute_orphans(account_id=AID)
    after_null = await _view_rev(None)
    after_emp = await _view_rev(AUTOMATION)
    assert before_null >= 20000, before_null
    assert after_null == before_null - 20000, (before_null, after_null)
    assert after_emp >= 20000, after_emp
    _ok("case_view_reflects_backfill")


async def main() -> None:
    await case_sole_chatter_credited()
    await case_ambiguous_left_for_manual()
    await case_standalone_tip_beyond_window_stays_null()
    await case_mass_toucher_ignored()
    await case_already_attributed_untouched()
    await case_unresolved_stays_null()
    await case_dry_run_writes_nothing()
    await case_view_reflects_backfill()
    print("ALL PASS — test_attribution_backfill")


if __name__ == "__main__":
    asyncio.run(main())
