#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import csv  # noqa: E402
import io  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import csv_export  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Employee, Fan, Message, Transaction  # noqa: E402
from transactions import _TIPS_CSV_HEADER, _TOP_TIPPERS_CSV_HEADER, tips_list, top_tippers  # noqa: E402

_NOW = datetime(2026, 6, 12, 12, 0, 0)
_FROM = (_NOW - timedelta(days=30)).isoformat()
_TO = (_NOW + timedelta(days=1)).isoformat()
AID = "tipcsv"
EMP = 9101


async def _seed() -> None:
    async with get_session() as s:
        s.add(Account(id=AID))
        s.add(Employee(id=EMP, display_name="Ana"))
        s.add(Fan(account_id=AID, fan_id=1, of_username="whale", of_display_name="Big, Spender"))
        s.add(Fan(account_id=AID, fan_id=2, of_username="minnow", of_display_name="Small"))
        s.add(Message(account_id=AID, fan_id=1, message_id=501, direction="out",
                      body="thanks babe", created_at=_NOW - timedelta(days=3),
                      sent_by_employee_id=EMP))
        tips = [
            (8001, 1, 5000, 3, 501),
            (8002, 2, 500, 2, None),
# 8003 is pending: pending always counts (TRACKED_STATUSES)
            (8003, 1, 2500, 1, None),
            (8004, 3, 100, 1, None),
        ]
        for tx_id, fan, cents, days, msg in tips:
            s.add(Transaction(id=tx_id, account_id=AID, fan_id=fan, kind="tip", amount_cents=cents,
                              occurred_at=_NOW - timedelta(days=days), message_id=msg,
                              status="pending" if tx_id == 8003 else "cleared"))
        s.add(Transaction(id=8005, account_id=AID, fan_id=2, kind="tip", amount_cents=9999,
                          occurred_at=_NOW - timedelta(days=1), status="refunded"))
        s.add(Transaction(id=8006, account_id=AID, fan_id=2, kind="ppv", amount_cents=9999,
                          occurred_at=_NOW - timedelta(days=1)))


async def _csv(resp) -> list[list[str]]:
    assert resp.media_type == "text/csv", resp.media_type
    assert resp.headers["x-row-count"] == str(csv_export.CSV_MAX_ROWS)
    body = b"".join([chunk async for chunk in resp.body_iterator]).decode()
    return list(csv.reader(io.StringIO(body)))


async def _tips(**kw):
    args = dict(from_=_FROM, to=_TO, account_id=AID, employee_id=None, fan_query=None,
                limit=1, before_id=None, format="csv")
    return await _csv(await tips_list(**(args | kw)))


async def _tippers(**kw):
    args = dict(from_=_FROM, to=_TO, account_id=AID, employee_id=None, limit=1, format="csv")
    return await _csv(await top_tippers(**(args | kw)))


async def case_tips_csv_is_every_filtered_tip_newest_first():
    lines = await _tips(before_id=8003)
    assert lines[0] == list(_TIPS_CSV_HEADER), lines[0]
    assert [r[0] for r in lines[1:]] == ["8004", "8003", "8002", "8001"], lines
    assert lines[4] == [
        "8001", (_NOW - timedelta(days=3)).isoformat(), AID, "1", "whale", "Big, Spender",
        "5000", "501", "thanks babe", str(EMP), "Ana", "tip_message",
    ], lines[4]
    assert lines[3][7:] == ["", "", "", "", ""], "a standalone tip has no message, note or Employee"
    assert [r[0] for r in (await _tips(fan_query="whale"))[1:]] == ["8003", "8001"]


async def case_top_tippers_csv_ranks_every_tipper():
    lines = await _tippers()
    assert lines[0] == list(_TOP_TIPPERS_CSV_HEADER), lines[0]
    assert [r[:7] for r in lines[1:]] == [
        ["1", AID, "1", "whale", "Big, Spender", "7500", "2"],
        ["2", AID, "2", "minnow", "Small", "500", "1"],
        ["3", AID, "3", "", "", "100", "1"],
    ], lines
    assert lines[1][7] == (_NOW - timedelta(days=1)).isoformat()
    page = await top_tippers(from_=_FROM, to=_TO, account_id=AID, employee_id=None, limit=2, format="json")
    assert [(r["rank"], r["fan"]["username"], r["total_cents"]) for r in page["rows"]] == [
        (1, "whale", 7500), (2, "minnow", 500),
    ], page
    assert page["rows"][0]["fan"] == {"username": "whale", "display_name": "Big, Spender", "avatar_url": None}


async def case_csv_stops_at_the_row_cap():
    cap = csv_export.CSV_MAX_ROWS
    csv_export.CSV_MAX_ROWS = 2
    try:
        for lines in (await _tips(), await _tippers()):
            assert len(lines) == 4, lines
            assert lines[-1][0] == csv_export.TRUNCATED_LINE, lines[-1]
    finally:
        csv_export.CSV_MAX_ROWS = cap


async def case_tip_note_needs_the_tips_fan_and_message():
    aid = "tipnote"
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(Message(account_id=aid, fan_id=1, message_id=601, direction="in", body="for you",
                      created_at=_NOW - timedelta(days=2)))
        for tx_id, fan, msg in ((8101, 1, 601), (8103, None, None), (8104, None, 601)):
            s.add(Transaction(id=tx_id, account_id=aid, fan_id=fan, kind="tip", amount_cents=100,
                              occurred_at=_NOW - timedelta(days=1), message_id=msg, status="cleared"))
    page = await tips_list(from_=_FROM, to=_TO, account_id=aid, employee_id=None, fan_query=None,
                           limit=10, before_id=None, format="json")
    got = {r["transaction_id"]: (r["fan_id"], r["message_id"], r["tip_note"]) for r in page["rows"]}
    assert got == {8101: (1, 601, "for you"), 8103: (None, None, None), 8104: (None, 601, None)}, got


async def case_formula_cells_open_as_text():
    async def rows():
        yield ["=HYPERLINK(\"http://x\")", "+1", "-cmd", "--", "@SUM(A1)", "\tx", "\rx", -5, "-12.50", "-",
               "a=b", ""]

    body = b"".join([c async for c in csv_export.stream_csv(rows(), ["c"] * 12, lambda r: r)]).decode()
    assert list(csv.reader(io.StringIO(body)))[1] == [
        "'=HYPERLINK(\"http://x\")", "+1", "'-cmd", "'--", "'@SUM(A1)", "'\tx", "'\rx", "-5", "-12.50", "-",
        "a=b", "",
    ], body


asyncio.run(_seed())
_harness.run()
