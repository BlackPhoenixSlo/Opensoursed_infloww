#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select, text  # noqa: E402

import attribution  # noqa: E402
import stats  # noqa: E402
import messages as messages_mod  # noqa: E402
from attribution import (  # noqa: E402
    mass_placeholder_message_id,
    write_mass_optimistic_rows,
    write_outbound_attribution,
)
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    Employee,
    GrokCall,
    MassMessageFunnel,
    MassRun,
    Message,
    Transaction,
)

AID = "acc1"
WIN_FROM = "2026-06-01"
WIN_TO = "2026-06-30"
T = datetime(2026, 6, 10, 12, 0, 0)


def _ok(name: str) -> None:
    print(f"  ✓ {name}")


async def _create_view() -> None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(
        here, "db", "migrations", "versions", "20261027_0100_converters_window.py"
    )
    spec = importlib.util.spec_from_file_location("mig0042", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    async with get_session() as s:
        await s.execute(text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
        await s.execute(text(mig._NEW_VIEW_SQL))


async def _seed_account() -> None:
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID, nickname="Acc 1"))
        if await s.get(Employee, 7) is None:
            s.add(Employee(id=7, display_name="Automation", is_active=True))
        if await s.get(MassRun, 5) is None:
            s.add(MassRun(id=5, account_id=AID,
                          automation_kind="send_mass_message", status="ok"))


async def case_stamps_automation_kind() -> None:
    await _seed_account()
    await write_outbound_attribution(
        account_id=AID, fan_id=11, message_id=9001,
        sent_by_employee_id=7, body="hey", price_cents=0,
        created_at=T, automation_kind="welcome_chatter_for_info",
    )
    await write_mass_optimistic_rows(
        account_id=AID, fan_ids=[21, 22], mass_run_id=5,
        sent_by_employee_id=7, body="promo", price_cents=0,
        created_at=T, automation_kind="send_mass_message",
    )
    async with get_session() as s:
        chat = await s.get(Message, (AID, 11, 9001))
        assert chat is not None and chat.automation_kind == "welcome_chatter_for_info", chat
        placeholder_id = mass_placeholder_message_id(5)
        m21 = await s.get(Message, (AID, 21, placeholder_id))
        assert m21 is not None and m21.automation_kind == "send_mass_message", m21
    _ok("case_stamps_automation_kind")


async def case_mass_collapse() -> None:
    async with get_session() as s:
        s.add(MassMessageFunnel(
            id=1, name="Strokes", opening_message="hey babe", steps_json="[]"))
        s.add(MassRun(
            id=77, account_id=AID, funnel_id=1, automation_kind="send_mass_message",
            recipient_count=3, status="ok",
        ))
        await s.flush()
        run_msg_id = mass_placeholder_message_id(77)
        for fid in (31, 32, 33):
            s.add(Message(
                account_id=AID, fan_id=fid, message_id=run_msg_id,
                direction="out", body="big promo", media_count=0, price_cents=0,
                mass_run_id=77, automation_kind="send_mass_message",
                sent_by_employee_id=7, created_at=T, ingested_at=T,
            ))
        s.add(Message(
            account_id=AID, fan_id=40, message_id=12345, direction="out",
            body="hi babe", media_count=0, price_cents=0,
            automation_kind="welcome_chatter_for_info", sent_by_employee_id=7,
            created_at=T, ingested_at=T,
        ))

    start = messages_mod._parse_date(WIN_FROM, field="from")
    end = messages_mod._parse_date(WIN_TO, field="to")
    async with get_session() as s:
        summaries = await messages_mod._collapsed_mass_rows(
            s=s, start=start, end=end, account_ids=[AID], employee_id=None,
            type_="all", before=None, limit=50,
        )
    runs = [r for r in summaries if r["mass_run_id"] == 77]
    assert len(runs) == 1, f"expected exactly one summary row, got {summaries}"
    row = runs[0]
    assert row["is_mass_summary"] is True
    assert row["recipient_count"] == 3, row
    assert row["automation_kind"] == "send_mass_message", row
    assert row["funnel_name"] == "Strokes", row
    assert row["message_id"] == mass_placeholder_message_id(77), row
    _ok("case_mass_collapse")


async def case_per_automation_stats() -> None:
    await _create_view()
    async with get_session() as s:
        s.add(Message(
            account_id=AID, fan_id=50, message_id=70001, direction="out",
            body="ppv", media_count=1, price_cents=500, is_paid=True,
            automation_kind="welcome_chatter_for_info", sent_by_employee_id=7,
            created_at=T, ingested_at=T,
        ))
        s.add(Transaction(
            account_id=AID, fan_id=50, message_id=70001, kind="ppv",
            amount_cents=500, currency="USD", occurred_at=T, status="cleared",
        ))
        s.add(Message(
            account_id=AID, fan_id=51, message_id=70002, direction="out",
            body="mass ppv", media_count=1, price_cents=2000, is_paid=True,
            automation_kind="send_mass_message",
            sent_by_employee_id=7, created_at=T, ingested_at=T,
        ))
        s.add(Transaction(
            account_id=AID, fan_id=51, message_id=70002, kind="ppv",
            amount_cents=2000, currency="USD", occurred_at=T, status="cleared",
        ))
        s.add(GrokCall(
            purpose="welcome_chatter_for_info", account_id=AID, model="deepseek-v4-flash",
            endpoint="chat", prompt_json="[]", provider="deepseek",
            tokens_in=1000, tokens_out=200, cost_cents=150, status="done",
            called_at=T,
        ))
        s.add(GrokCall(
            purpose="gen_info", account_id=AID, model="deepseek-v4-flash",
            endpoint="chat", prompt_json="[]", provider="deepseek",
            tokens_in=4000, tokens_out=400, cost_cents=600, status="done",
            called_at=T,
        ))

    resp = await stats.per_automation(from_=WIN_FROM, to=WIN_TO, account_id=AID)
    by = {r["automation"]: r for r in resp["rows"]}

    assert "welcome_chatter_for_info" in by, by
    assert by["welcome_chatter_for_info"]["revenue_cents"] == 500, by["welcome_chatter_for_info"]
    assert by["welcome_chatter_for_info"]["llm_calls"] == 1, by["welcome_chatter_for_info"]
    assert by["welcome_chatter_for_info"]["cost_millicents"] == 150, by["welcome_chatter_for_info"]
    assert by["welcome_chatter_for_info"]["messages_sent"] >= 1, by["welcome_chatter_for_info"]

    assert by["send_mass_message"]["revenue_cents"] == 2000, by["send_mass_message"]
    assert by["send_mass_message"]["llm_calls"] == 0, by["send_mass_message"]
    assert by["send_mass_message"]["messages_sent"] >= 1, by["send_mass_message"]

    assert by["gen_info"]["cost_millicents"] == 600, by["gen_info"]
    assert by["gen_info"]["messages_sent"] == 0, by["gen_info"]
    assert by["gen_info"]["revenue_cents"] == 0, by["gen_info"]

    assert resp["rows"][0]["automation"] == "send_mass_message", resp["rows"]
    assert resp["totals"]["revenue_cents"] == 2500, resp["totals"]
    _ok("case_per_automation_stats")


async def case_mass_ppv_no_overcount() -> None:
    await _create_view()
    RUN = 88
    placeholder_id = mass_placeholder_message_id(RUN)
    async with get_session() as s:
        if await s.get(MassRun, RUN) is None:
            s.add(MassRun(id=RUN, account_id=AID,
                          automation_kind="ppv_send", status="ok"))
    await write_mass_optimistic_rows(
        account_id=AID, fan_ids=[61, 62, 63], mass_run_id=RUN,
        sent_by_employee_id=7, body="ppv babe", price_cents=1000,
        created_at=T, automation_kind="ppv_send",
    )
    # The unlock tx carries the shared placeholder id (mirrors transaction_ingest._link_ppv_message).
    async with get_session() as s:
        s.add(Transaction(
            account_id=AID, fan_id=61, message_id=placeholder_id, kind="ppv",
            amount_cents=1000, currency="USD", occurred_at=T, status="cleared",
        ))

    resp = await stats.per_automation(from_=WIN_FROM, to=WIN_TO, account_id=AID)
    by = {r["automation"]: r for r in resp["rows"]}
    assert by["ppv_send"]["revenue_cents"] == 1000, by.get("ppv_send")
    _ok("case_mass_ppv_no_overcount")


async def case_pump_wins_the_race_and_we_still_tag_it() -> None:
    await _seed_account()
    async with get_session() as s:
        s.add(Message(account_id=AID, fan_id=31, message_id=9101, direction="out",
                      sender_name="", body="<p>real OF body</p>", media_ids="[1,2]",
                      media_count=2, price_cents=0, is_tip=False, is_unsent=False,
                      raw_json='{"from":"ws"}', created_at=T))
    await write_outbound_attribution(
        account_id=AID, fan_id=31, message_id=9101,
        sent_by_employee_id=7, body="placeholder", price_cents=0,
        created_at=T, automation_kind="ai_chatter",
    )
    async with get_session() as s:
        m = await s.get(Message, (AID, 31, 9101))
    assert m.automation_kind == "ai_chatter", f"tag lost: {m.automation_kind!r}"
    assert m.sent_by_employee_id == 7, m.sent_by_employee_id
    assert m.body == "<p>real OF body</p>", m.body
    assert m.media_ids == "[1,2]" and m.media_count == 2, (m.media_ids, m.media_count)
    assert m.raw_json == '{"from":"ws"}', m.raw_json

    await write_outbound_attribution(
        account_id=AID, fan_id=31, message_id=9101,
        sent_by_employee_id=9, body="placeholder", price_cents=0,
        created_at=T, automation_kind="send_welcome",
    )
    async with get_session() as s:
        m = await s.get(Message, (AID, 31, 9101))
    assert m.automation_kind == "ai_chatter", f"relabelled to {m.automation_kind!r}"
    assert m.sent_by_employee_id == 7, m.sent_by_employee_id
    _ok("case_pump_wins_the_race_and_we_still_tag_it")


async def main() -> None:
    await case_stamps_automation_kind()
    await case_mass_collapse()
    await case_per_automation_stats()
    await case_mass_ppv_no_overcount()
    await case_pump_wins_the_race_and_we_still_tag_it()
    print("ALL PASS — test_automation_attribution")


if __name__ == "__main__":
    asyncio.run(main())
