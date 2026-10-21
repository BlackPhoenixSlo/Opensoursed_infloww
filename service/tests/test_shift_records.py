#!/usr/bin/env python3
"""Shift records (roadmap W6 6.6): `GET /admin/shifts/records` and the Owner delete of a Clock event.

- Records are the Agency's Clock events intersecting [from, to), newest clock-in first, every Employee's unless
  `employee_id` narrows them, each with its sales: the shares credited to its Employee inside its time on its
  Creator (the Timesheet's Recorded earnings rule), as `sales_cents` and `sales` (how many).
- `DELETE /admin/shifts/clock-events/{id}` removes the event and writes one `clock.owner_delete` action holding
  it; another Agency's event or a missing one is 404.
- Owner or Master only: a chatter 403, no session 401.

The seam is the Relay over HTTP with the shared two-Agency fixture's sessions, over Clock events, messages and
transactions seeded straight into the temp DB with fixed past timestamps on a Creator this file owns.

Run: ./venv/bin/python service/tests/test_shift_records.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
from _clock_fixtures import IDS, employee as _employee, event as _event, utc_now  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Action, ClockEvent, Message, Transaction, UserAccount  # noqa: E402

DAY = "2026-05-04"
RANGE = f"from={DAY}T00:00:00Z&to=2026-05-05T00:00:00Z"
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
CHATTER_A = fx.login_chatter("chatter_a")
ANON = _harness.make_client()


def _at(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{DAY}T{hhmm}:00")


async def _seed_creator(aid: str) -> None:
    async with get_session() as s:
        s.add(Account(id=aid, nickname="records_creator", color="#aaaaaa"))
    async with get_session() as s:
        s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=aid))


C = "3200001"
(account_registry.ACCOUNTS_DIR / C).mkdir()
asyncio.run(_seed_creator(C))


def _sale(cents: int, at: datetime, fan: int, sender: int | None = None, manual: int | None = None,
          status: str = "cleared") -> int:
    async def _seed():
        async with get_session() as s:
            mid = None
            if sender is not None:
                mid = 8_300_000 + fan
                s.add(Message(account_id=C, fan_id=fan, message_id=mid, direction="out", body="x",
                              sent_by_employee_id=sender, created_at=at, ingested_at=at))
            tx = Transaction(account_id=C, fan_id=fan, kind="ppv_message" if mid else "tip", message_id=mid,
                             amount_cents=cents, occurred_at=at, status=status, currency="USD", source="ledger",
                             attributed_employee_id=manual, net_cents=cents)
            s.add(tx)
            await s.flush()
            return tx.id
    return asyncio.run(_seed())


E1, E2 = _employee("records_emp_1"), _employee("records_emp_2")
EV1 = _event(E1, _at("09:00"), _at("11:00"), account_id=C)
EV2 = _event(E2, _at("10:00"), _at("12:00"), account_id=C)
EV_OLD = _event(E1, _at("01:00"), _at("02:00"), account_id=C)  # no sales
_sale(1000, _at("09:30"), fan=1, sender=E1)
_sale(200, _at("10:59"), fan=2, manual=E1)
_sale(300, _at("11:30"), fan=3, sender=E1)   # after E1's clock-out: no shift's
_sale(400, _at("11:00"), fan=4, sender=E2)
_sale(25, _at("11:15"), fan=5, sender=E2, status="pending")  # an uncleared sale counts too
EV_B = _event(_employee("records_emp_b", owner="agency_b_owner"), _at("09:00"), _at("11:00"),
              owner="agency_b_owner")


def _records(client=OWNER_A, query: str = RANGE, status: int = 200):
    r = client.get(f"/admin/shifts/records?{query}")
    assert r.status_code == status, f"{query}: {r.status_code} {r.text}"
    return r.json()["records"] if status == 200 else None


def _mine(records: list[dict]) -> list[tuple]:
    return [(r["clock_event_id"], r["employee_id"], r["minutes"], r["sales_cents"], r["sales"])
            for r in records if r["account_id"] == C]


def case_each_clock_event_is_a_record_with_the_sales_credited_inside_it():
    assert _mine(_records()) == [(EV2, E2, 120, 425, 2), (EV1, E1, 120, 1200, 2), (EV_OLD, E1, 60, 0, 0)]
    row = next(r for r in _records() if r["clock_event_id"] == EV1)
    assert row == {"clock_event_id": EV1, "employee_id": E1, "account_id": C, "shift_id": None,
                   "in_utc": f"{DAY}T09:00:00Z", "out_utc": f"{DAY}T11:00:00Z", "close_reason": "manual",
                   "minutes": 120, "edited": False, "sales_cents": 1200, "sales": 2}, row


def case_employee_id_and_the_range_narrow_the_records():
    assert _mine(_records(query=f"{RANGE}&employee_id={E1}")) == [(EV1, E1, 120, 1200, 2), (EV_OLD, E1, 60, 0, 0)]
    assert _mine(_records(query=f"from={DAY}T08:00:00Z&to={DAY}T09:30:00Z")) == [(EV1, E1, 120, 1200, 2)]
    _records(query=f"{RANGE}&employee_id=x", status=422)
    _records(query=f"{RANGE}&employee_id=99999999", status=404)
    _records(query="from=x&to=y", status=422)


def case_another_agencys_records_never_appear_and_a_chatter_is_refused():
    assert EV_B not in {r["clock_event_id"] for r in _records()}
    assert {r["clock_event_id"] for r in _records(OWNER_B)} == {EV_B}
    _records(CHATTER_A, status=403)
    _records(ANON, status=401)


def _delete(client, ev, status: int = 200):
    r = client.delete(f"/admin/shifts/clock-events/{ev}")
    assert r.status_code == status, f"delete {ev}: {r.status_code} {r.text}"
    return r.json() if status == 200 else None


def _audit(ev: int) -> list[dict]:
    async def _read():
        async with get_session() as s:
            rows = (await s.execute(select(Action).where(Action.action == "clock.owner_delete",
                                                         Action.target_id == str(ev)))).scalars().all()
            return [{"account_id": a.account_id, "target_type": a.target_type, **json.loads(a.payload_json)}
                    for a in rows]
    return asyncio.run(_read())


def _exists(ev: int) -> bool:
    async def _read():
        async with get_session() as s:
            return (await s.execute(select(ClockEvent.id).where(ClockEvent.id == ev))).scalar() is not None
    return asyncio.run(_read())


def case_an_owner_delete_removes_the_event_with_one_audit_row():
    for client, ev, status in ((OWNER_A, EV_B, 404), (OWNER_A, 99_999_999, 404), (OWNER_A, "x", 404),
                               (CHATTER_A, EV_OLD, 403), (ANON, EV_OLD, 401)):
        _delete(client, ev, status)
    assert _exists(EV_OLD) and _exists(EV_B) and not _audit(EV_OLD)

    assert _delete(OWNER_A, EV_OLD) == {"deleted": EV_OLD}
    assert not _exists(EV_OLD)
    assert EV_OLD not in {r["clock_event_id"] for r in _records()}
    assert _audit(EV_OLD) == [{
        "account_id": C, "target_type": "clock_event", "actor": f"owner:{IDS['agency_a_owner']}", "after": None,
        "before": {"clock_event_id": EV_OLD, "employee_id": E1, "account_id": C, "shift_id": None,
                   "in_utc": f"{DAY}T01:00:00Z", "out_utc": f"{DAY}T02:00:00Z", "close_reason": "manual"}}]
    _delete(OWNER_A, EV_OLD, 404)


def case_an_open_event_can_be_deleted():
    ev = _event(E2, utc_now(), account_id=C)  # now, so no auto clock-out closes it first
    _delete(OWNER_A, ev)
    assert not _exists(ev), ev
    assert _audit(ev)[0]["before"]["out_utc"] is None, _audit(ev)


_harness.run()
