#!/usr/bin/env python3
"""Sales amend (roadmap W6 6.5): "No one", the three-way assigned filter and the batch reassign.

- "No one" (`employee_id: "no_one"`, the override `sales_attribution.NO_ONE`) credits a sale to nobody
  whatever the Rules say: its Sales record reads rule `manual`, no Employee, "Assigned by" Owner, it is listed
  as unassigned, and Employee reports (read from the rollups) move its revenue to Unattributed; clearing
  (`null`) hands it back to the Rules.
- `assigned=all|assigned|unassigned` on `GET /admin/stats/sales-records`.
- `POST /admin/ingest/transactions/attribute` moves many sales at once, by `tx_ids` or by one Clock event's
  sales (`clock_event_id`, the shares credited to its Employee inside its time on the Creator, pending sales
  included), every sale or none, one `sales.reassign` action each; a Clock event's split sale (Shift schedule
  shares) is left as it is and counted in `skipped_split`. The Master may batch any Agency's sales, to an
  Employee of the sale's Agency only.

The seam is the Relay over HTTP with the shared two-Agency fixture's session cookies, over transactions and
messages seeded straight into the temp DB with fixed past timestamps, on Creators this file owns.

Run: ./venv/bin/python service/tests/test_sales_amend.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
from _clock_fixtures import IDS, employee as _employee, event as _event  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Action, Message, Transaction, UserAccount  # noqa: E402

DAY = "2026-05-04"
ONE = "/admin/ingest/transactions/{}/attribute"
BATCH = "/admin/ingest/transactions/attribute"

OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
MASTER = fx.login_owner("agency_master")
CHATTER_A = fx.login_chatter("chatter_a")
ANON = _harness.make_client()


def _at(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{DAY}T{hhmm}:00")


def _creator(aid: str, owner: str = "agency_a_owner") -> str:
    async def _seed():
        async with get_session() as s:
            s.add(Account(id=aid, nickname=f"amend_creator_{aid[-2:]}", color="#aaaaaa"))
        async with get_session() as s:
            s.add(UserAccount(user_id=IDS[owner], account_id=aid))
    (account_registry.ACCOUNTS_DIR / aid).mkdir()
    asyncio.run(_seed())
    return aid


_next_mid = iter(range(8_200_001, 8_300_000))


def _message(aid: str, fan: int, sender: int, at: datetime) -> int:
    mid = next(_next_mid)

    async def _seed():
        async with get_session() as s:
            s.add(Message(account_id=aid, fan_id=fan, message_id=mid, direction="out", body="x",
                          sent_by_employee_id=sender, created_at=at, ingested_at=at))
    asyncio.run(_seed())
    return mid


def _sale(aid: str, kind: str, cents: int, at: datetime, fan: int = 1, message_id: int | None = None,
          manual: int | None = None, status: str = "cleared") -> int:
    async def _seed():
        async with get_session() as s:
            tx = Transaction(account_id=aid, fan_id=fan, kind=kind, message_id=message_id, amount_cents=cents,
                             occurred_at=at, status=status, currency="USD", source="ledger",
                             attributed_employee_id=manual, net_cents=cents)
            s.add(tx)
            await s.flush()
            return tx.id
    return asyncio.run(_seed())


def _override(tx: int):
    async def _read():
        async with get_session() as s:
            return (await s.execute(select(Transaction.attributed_employee_id).where(Transaction.id == tx))).scalar()
    return asyncio.run(_read())


def _reassigns(tx: int) -> list[dict]:
    async def _read():
        async with get_session() as s:
            rows = (await s.execute(select(Action).where(Action.action == "sales.reassign",
                                                         Action.target_id == str(tx)).order_by(Action.id))).scalars()
            return [json.loads(a.payload_json) for a in rows]
    return asyncio.run(_read())


def _records(query: str, client=OWNER_A) -> dict:
    r = client.get(f"/admin/stats/sales-records?{query}")
    assert r.status_code == 200, f"{query}: {r.status_code} {r.text}"
    return {row["tx_id"]: (row["rule"], row["employee_id"], row["assigned_by"]) for row in r.json()["rows"]}


def _reports(aid: str) -> dict:
    """Employee reports' revenue on one Creator by Employee (None is Unattributed), over the whole day, so read
    from the rollups."""
    r = OWNER_A.get(f"/admin/stats/per-employee?from={DAY}&to={DAY}&by_account=true")
    assert r.status_code == 200, r.text
    return {e["employee_id"]: sub["revenue_cents"] for e in r.json()["employees"] for sub in e["per_account"]
            if sub["account_id"] == aid and sub["revenue_cents"]}


def _post(client, path: str, body: dict, status: int = 200):
    r = client.post(path, json=body)
    assert r.status_code == status, f"{path} {body}: {r.status_code} {r.text}"
    return r.json() if status == 200 else None


OWNER_ACTOR = f"owner:{IDS['agency_a_owner']}"
E1, E2 = _employee("amend_emp_1"), _employee("amend_emp_2")
E_B = _employee("amend_emp_b", owner="agency_b_owner")


# ── "No one" and the three-way filter ───────────────────────────────────────────────────────────────────────

C1 = _creator("3100001")
C1_DAY = f"account_id={C1}&from={DAY}&to={DAY}"
T_MSG = _sale(C1, "ppv_message", 1000, _at("10:00"), fan=11, message_id=_message(C1, 11, E1, _at("09:00")))
T_NOBODY = _sale(C1, "tip", 300, _at("10:05"), fan=12)
T_MANUAL = _sale(C1, "tip", 200, _at("10:10"), fan=13, manual=E2)


def case_the_three_way_filter_splits_assigned_from_unassigned():
    every = _records(C1_DAY)
    assert set(every) == {T_MSG, T_NOBODY, T_MANUAL}, every
    assert set(_records(f"{C1_DAY}&assigned=all")) == set(every)
    assert set(_records(f"{C1_DAY}&assigned=assigned")) == {T_MSG, T_MANUAL}
    assert set(_records(f"{C1_DAY}&assigned=unassigned")) == {T_NOBODY}
    r = OWNER_A.get(f"/admin/stats/sales-records?{C1_DAY}&assigned=nobody")
    assert r.status_code == 422, r.text


def case_no_one_credits_nobody_until_cleared_and_moves_the_reports_revenue_to_unattributed():
    assert _reports(C1) == {E1: 1000, None: 300, E2: 200}, _reports(C1)
    body = _post(OWNER_A, ONE.format(T_MSG), {"employee_id": "no_one"})
    assert body["attributed_employee_id"] == 0, body
    assert _override(T_MSG) == 0
    assert _records(C1_DAY)[T_MSG] == ("manual", None, "Owner"), _records(C1_DAY)
    assert set(_records(f"{C1_DAY}&assigned=unassigned")) == {T_MSG, T_NOBODY}
    assert set(_records(f"{C1_DAY}&assigned=assigned")) == {T_MANUAL}
    assert _reports(C1) == {None: 1300, E2: 200}, _reports(C1)
    assert _reassigns(T_MSG)[-1] == {"actor": OWNER_ACTOR, "before": {"employee_id": None},
                                     "after": {"employee_id": 0}, "shown_before": {"employee_id": E1}}

    _post(OWNER_A, ONE.format(T_MSG), {"employee_id": None})  # cleared: the message's sender again
    assert _override(T_MSG) is None
    assert _records(C1_DAY)[T_MSG] == ("message", E1, "Auto"), _records(C1_DAY)
    assert _reports(C1) == {E1: 1000, None: 300, E2: 200}, _reports(C1)
    assert _reassigns(T_MSG)[-1]["before"] == {"employee_id": 0}


def case_a_bad_employee_id_is_400_and_writes_nothing():
    for body in ({}, {"employee_id": 0}, {"employee_id": True}, {"employee_id": "someone"}, {"employee_id": [1]}):
        _post(OWNER_A, ONE.format(T_NOBODY), body, status=400)
    assert _override(T_NOBODY) is None and not _reassigns(T_NOBODY)


# ── The batch ───────────────────────────────────────────────────────────────────────────────────────────────

C2 = _creator("3100002")
C2_DAY = f"account_id={C2}&from={DAY}&to={DAY}"
BATCH_TXS = [_sale(C2, "tip", 100 + i, _at(f"11:0{i}"), fan=20 + i) for i in range(3)]
T_B = _sale(IDS["creator_b"], "tip", 700, _at("11:00"), fan=41)


def case_a_batch_moves_every_sale_with_one_action_each():
    body = _post(OWNER_A, BATCH, {"employee_id": E1, "tx_ids": BATCH_TXS + BATCH_TXS[:1]})
    assert body == {"updated": 3, "attributed_employee_id": E1, "tx_ids": BATCH_TXS, "skipped_split": 0}, body
    assert {tx: _records(C2_DAY)[tx] for tx in BATCH_TXS} == {tx: ("manual", E1, "Owner") for tx in BATCH_TXS}
    for tx in BATCH_TXS:
        assert _reassigns(tx) == [{"actor": OWNER_ACTOR, "before": {"employee_id": None},
                                   "after": {"employee_id": E1}, "shown_before": {"employee_id": None}}]
    _post(OWNER_A, BATCH, {"employee_id": "no_one", "tx_ids": BATCH_TXS})
    assert [_override(tx) for tx in BATCH_TXS] == [0, 0, 0]
    _post(OWNER_A, BATCH, {"employee_id": None, "tx_ids": BATCH_TXS})
    assert [_override(tx) for tx in BATCH_TXS] == [None, None, None]
    assert all(len(_reassigns(tx)) == 3 for tx in BATCH_TXS)


def case_a_batch_with_one_refused_sale_writes_nothing():
    before = [len(_reassigns(tx)) for tx in BATCH_TXS]
    _post(OWNER_A, BATCH, {"employee_id": E1, "tx_ids": BATCH_TXS + [T_B]}, status=404)
    _post(OWNER_A, BATCH, {"employee_id": E1, "tx_ids": BATCH_TXS + [99_999_999]}, status=404)
    _post(OWNER_A, BATCH, {"employee_id": E_B, "tx_ids": BATCH_TXS}, status=400)
    _post(OWNER_B, BATCH, {"employee_id": E_B, "tx_ids": BATCH_TXS}, status=404)
    assert [_override(tx) for tx in BATCH_TXS] == [None, None, None]
    assert [len(_reassigns(tx)) for tx in BATCH_TXS] == before


def case_the_master_batches_any_agencys_sales_to_that_agencys_employees():
    before = [len(_reassigns(tx)) for tx in BATCH_TXS]
    _post(MASTER, BATCH, {"employee_id": E_B, "tx_ids": BATCH_TXS}, status=400)
    _post(MASTER, BATCH, {"employee_id": E1, "tx_ids": BATCH_TXS + [T_B]}, status=400)
    assert [len(_reassigns(tx)) for tx in BATCH_TXS] == before, "a refused Master batch writes nothing"
    body = _post(MASTER, BATCH, {"employee_id": E2, "tx_ids": BATCH_TXS})
    assert body["updated"] == 3 and [_override(tx) for tx in BATCH_TXS] == [E2, E2, E2], body
    assert all(_reassigns(tx)[-1]["actor"].startswith("master:") for tx in BATCH_TXS)
    assert {tx: _records(C2_DAY)[tx][2] for tx in BATCH_TXS} == {tx: "Master" for tx in BATCH_TXS}
    _post(MASTER, BATCH, {"employee_id": None, "tx_ids": BATCH_TXS})
    assert [_override(tx) for tx in BATCH_TXS] == [None, None, None]


def case_a_malformed_batch_is_400_and_a_chatter_403():
    for body in ({"employee_id": E1}, {"employee_id": E1, "tx_ids": BATCH_TXS, "clock_event_id": 1},
                 {"employee_id": E1, "tx_ids": []}, {"employee_id": E1, "tx_ids": "1"},
                 {"employee_id": E1, "tx_ids": [True]}, {"employee_id": E1, "tx_ids": ["1"]},
                 {"employee_id": E1, "tx_ids": list(range(1, 502))}, {"tx_ids": BATCH_TXS}):
        _post(OWNER_A, BATCH, body, status=400)
    _post(CHATTER_A, BATCH, {"employee_id": E1, "tx_ids": BATCH_TXS}, status=403)
    _post(ANON, BATCH, {"employee_id": E1, "tx_ids": BATCH_TXS}, status=401)
    assert [_override(tx) for tx in BATCH_TXS] == [None, None, None]


# ── One shift's sales ───────────────────────────────────────────────────────────────────────────────────────

C3 = _creator("3100003")
C3_DAY = f"account_id={C3}&from={DAY}&to={DAY}"
EV = _event(E1, _at("12:00"), _at("14:00"), account_id=C3)
T_IN = _sale(C3, "ppv_message", 500, _at("12:30"), fan=31, message_id=_message(C3, 31, E1, _at("12:10")))
T_IN_MANUAL = _sale(C3, "tip", 50, _at("13:59"), fan=32, manual=E1)
T_OTHER = _sale(C3, "tip", 70, _at("13:00"), fan=33, message_id=_message(C3, 33, E2, _at("12:20")))
T_AFTER = _sale(C3, "ppv_message", 90, _at("14:30"), fan=34, message_id=_message(C3, 34, E1, _at("14:20")))
T_IN_PENDING = _sale(C3, "ppv_message", 40, _at("13:30"), fan=35, message_id=_message(C3, 35, E1, _at("13:20")),
                     status="pending")


def case_a_clock_events_sales_move_together_and_a_repeat_finds_none():
    body = _post(OWNER_A, BATCH, {"employee_id": E2, "clock_event_id": EV})
    assert body == {"updated": 3, "attributed_employee_id": E2, "tx_ids": [T_IN, T_IN_MANUAL, T_IN_PENDING],
                    "skipped_split": 0}, body
    rows = _records(C3_DAY)
    assert {tx: rows[tx] for tx in (T_IN, T_IN_MANUAL, T_IN_PENDING, T_OTHER, T_AFTER)} == {
        T_IN: ("manual", E2, "Owner"), T_IN_MANUAL: ("manual", E2, "Owner"), T_IN_PENDING: ("manual", E2, "Owner"),
        T_OTHER: ("message", E2, "Auto"), T_AFTER: ("message", E1, "Auto")}, rows
    assert _post(OWNER_A, BATCH, {"employee_id": E2, "clock_event_id": EV}) == {
        "updated": 0, "attributed_employee_id": E2, "tx_ids": [], "skipped_split": 0}


C4 = _creator("3100004")
EV_SOLO = _event(E1, _at("15:00"), _at("17:00"), account_id=C4)
EV_JOIN = _event(E2, _at("16:00"), _at("17:00"), account_id=C4)
T_SOLO = _sale(C4, "tip", 600, _at("15:30"), fan=51)
T_SPLIT = _sale(C4, "tip", 800, _at("16:30"), fan=52)
SINCE_THE_START = {"effective_from": "1970-01-01T00:00:00Z"}


def _put(tab: str, blob: dict) -> None:
    r = OWNER_A.put(f"/admin/settings/{tab}", json=blob, params=SINCE_THE_START)
    assert r.status_code == 200, f"PUT {tab}: {r.status_code} {r.text}"


def case_a_clock_events_reassign_leaves_a_split_sale_to_its_sharers():
    _put("sales", {"attribution": {"messages": "sender", "posts_tips": "shift", "subscriptions_chatter_opt_in": False}})
    _put("time-tracking", {"enabled": True})
    try:
        day = f"account_id={C4}&from={DAY}&to={DAY}"
        split = [(r["employee_id"], r["earnings_cents"]) for r in OWNER_A.get(
            f"/admin/stats/sales-records?{day}").json()["rows"] if r["tx_id"] == T_SPLIT]
        assert sorted(split) == [(E1, 400), (E2, 400)], split
        body = _post(OWNER_A, BATCH, {"employee_id": "no_one", "clock_event_id": EV_SOLO})
        assert body == {"updated": 1, "attributed_employee_id": 0, "tx_ids": [T_SOLO], "skipped_split": 1}, body
        assert _override(T_SOLO) == 0 and _override(T_SPLIT) is None and not _reassigns(T_SPLIT)
    finally:
        _put("sales", {})
        _put("time-tracking", {})


def case_another_agencys_or_a_missing_clock_event_is_404():
    ev_b = _event(E_B, _at("12:00"), _at("14:00"), owner="agency_b_owner")
    _post(OWNER_A, BATCH, {"employee_id": E1, "clock_event_id": ev_b}, status=404)
    _post(OWNER_A, BATCH, {"employee_id": E1, "clock_event_id": 99_999_999}, status=404)
    _post(OWNER_A, BATCH, {"employee_id": E1, "clock_event_id": "x"}, status=404)



_harness.run()
