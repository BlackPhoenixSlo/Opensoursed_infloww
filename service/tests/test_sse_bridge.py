#!/usr/bin/env python3
"""WORKER→SSE bridge — a worker that writes an outbound `messages` row must emit
a synthetic `api2_chat_message` SSE event so an open chat updates live (the OF-WS
pump skips outbound, so there's no live path otherwise).

Covers the guardrail's named requirement ("assert an SSE event fires after a
worker write") plus the gating that keeps the HUMAN send path silent (it relies
on optimistic UI; a second live row would duplicate on the sender's screen).

Run: ./venv/bin/python service/tests/test_sse_bridge.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime  # noqa: E402

import events  # noqa: E402
from attribution import (  # noqa: E402
    write_mass_optimistic_rows,
    write_outbound_attribution,
)
from db.engine import get_session  # noqa: E402
from db.models import Account, Chat, Employee, MassRun  # noqa: E402

_NOW = datetime(2026, 6, 4, 12, 0, 0)


async def _drain(q) -> list:
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except asyncio.QueueEmpty:
            break
    return out


async def case_publish_db_message_outbound_shape():
    """The synthetic event carries the recipient (__fan_id) and marks the bubble
    outbound (fromUser.id == account_id) — the shape useInboxRealtime consumes."""
    q = await events.subscribe("all")
    try:
        await events.publish_db_message(
            account_id="555", fan_id=777, message_id=9001,
            body="hi", created_at=_NOW, price_cents=300,
        )
        evs = await _drain(q)
    finally:
        await events.unsubscribe("all", q)

    assert len(evs) == 1, f"expected 1 event, got {len(evs)}"
    e = evs[0]
    assert e["__account_id"] == "555" and e["__fan_id"] == 777, e
    m = e["api2_chat_message"]
    assert m["id"] == 9001 and m["text"] == "hi", m
    assert str(m["fromUser"]["id"]) == "555", "outbound: fromUser.id must equal the account"
    assert m["toUser"]["id"] == 777, m
    assert m["price"] == 3.0, m["price"]


async def case_worker_write_emits_live():
    """write_outbound_attribution(emit_live=True) → exactly one SSE event,
    routed to the per-account scope."""
    q = await events.subscribe("model:606")
    try:
        await write_outbound_attribution(
            account_id="606", fan_id=888, message_id=9100,
            sent_by_employee_id=None, body="welcome!", price_cents=0,
            created_at=_NOW, emit_live=True,
        )
        evs = await _drain(q)
    finally:
        await events.unsubscribe("model:606", q)

    assert len(evs) == 1, f"expected 1 SSE event from worker write, got {len(evs)}"
    assert evs[0]["__fan_id"] == 888 and evs[0]["api2_chat_message"]["id"] == 9100


async def case_human_path_is_silent_by_default():
    """Default (emit_live omitted) MUST NOT emit — the human send path relies on
    optimistic UI; a live row would duplicate on the sender's screen."""
    q = await events.subscribe("model:607")
    try:
        await write_outbound_attribution(
            account_id="607", fan_id=889, message_id=9200,
            sent_by_employee_id=None, body="human send", price_cents=0,
            created_at=_NOW,
        )
        evs = await _drain(q)
    finally:
        await events.unsubscribe("model:607", q)

    assert evs == [], f"default write must be silent, got {len(evs)} event(s)"


async def case_mass_optimistic_emits_per_recipient():
    """One SSE event per UNIQUE known recipient of a broadcast."""
    # messages.mass_run_id FKs mass_runs.id, and mass_runs.account_id FKs
    # accounts.id — mint both parents first (A10 does the same chain).
    async with get_session() as s:
        if await s.get(Account, "608") is None:
            s.add(Account(id="608"))
        mr = MassRun(account_id="608", status="running")
        s.add(mr)
        await s.flush()
        run_id = int(mr.id)

    q = await events.subscribe("model:608")
    try:
        n = await write_mass_optimistic_rows(
            account_id="608", fan_ids=[111, 222, 111], mass_run_id=run_id,
            sent_by_employee_id=None, body="mass!", price_cents=0,
            created_at=_NOW, emit_live=True,
        )
        evs = await _drain(q)
    finally:
        await events.unsubscribe("model:608", q)

    assert n == 2, f"dedup → 2 rows, got {n}"
    fan_ids = sorted(e["__fan_id"] for e in evs)
    assert fan_ids == [111, 222], f"expected one event per unique recipient, got {fan_ids}"


async def case_outbound_send_advances_chat_preview():
    """An automation/human outbound send advances the local `chats` preview so
    the inbox seed (/admin/chats/recent) shows the just-sent text instead of
    lagging on the fan's last inbound. Forward-only: an OLDER send can't clobber
    the newer preview."""
    async with get_session() as s:
        if await s.get(Account, "609") is None:
            s.add(Account(id="609"))

    # First send lands as the preview.
    await write_outbound_attribution(
        account_id="609", fan_id=900, message_id=9300,
        sent_by_employee_id=None, body="<p>newest reply</p>", price_cents=0,
        created_at=_NOW,
    )
    async with get_session() as s:
        chat = await s.get(Chat, ("609", 900))
    assert chat is not None, "outbound send must create the chats row"
    assert chat.last_message_preview == "newest reply", chat.last_message_preview
    assert chat.last_message_id == 9300, chat.last_message_id

    # An OLDER send (earlier created_at) must NOT overwrite the newer preview.
    older = datetime(2026, 6, 4, 11, 0, 0)
    await write_outbound_attribution(
        account_id="609", fan_id=900, message_id=9250,
        sent_by_employee_id=None, body="stale", price_cents=0,
        created_at=older,
    )
    async with get_session() as s:
        chat = await s.get(Chat, ("609", 900))
    assert chat.last_message_preview == "newest reply", (
        f"forward-only guard failed: {chat.last_message_preview}")


async def case_human_send_announces_chat_responded():
    """A person's DM is announced as `chat_responded` (who answered which fan),
    to that Creator's sessions only — never as a second chat message."""
    async with get_session() as s:
        e = Employee(display_name="Kingsley", user_id="owner-1")
        s.add(e)
        await s.flush()
        emp_id = e.id
    mine, other = await events.subscribe("model:610"), await events.subscribe("model:611")
    try:
        await events.publish_chat_responded(account_id="610", fan_id=901, employee_id=emp_id)
        await events.publish_chat_responded(account_id="610", fan_id=902, employee_id=None)
        evs, leaked = await _drain(mine), await _drain(other)
    finally:
        await events.unsubscribe("model:610", mine)
        await events.unsubscribe("model:611", other)

    assert leaked == [], f"another Creator's session got {leaked}"
    assert [(e["__account_id"], e["chat_responded"]) for e in evs] == [
        ("610", {"fan_id": 901, "by": "Kingsley"}),
        ("610", {"fan_id": 902, "by": ""}),
    ], evs


_harness.run(
    case_publish_db_message_outbound_shape,
    case_worker_write_emits_live,
    case_human_path_is_silent_by_default,
    case_mass_optimistic_emits_per_recipient,
    case_outbound_send_advances_chat_preview,
    case_human_send_announces_chat_responded,
)
