#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fansly"))

from sqlalchemy import select  # noqa: E402

import event_transcoder as et  # noqa: E402
import webhook_dispatch  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Message  # noqa: E402
from fansly_ws import FanslyWebSocket  # noqa: E402

_AID = "700237824869654528"
_FAN = "500251712226222080"
_MID = "900544249226047488"



_dispatched: list[tuple] = []


async def _fake_on_inbound_message(account_id, fan_id, message_id):
    _dispatched.append((account_id, fan_id, message_id))


webhook_dispatch.on_inbound_message = _fake_on_inbound_message  # type: ignore[assignment]



_INBOUND = {"type": 1, "message": {
    "type": 1, "senderId": _FAN,
    "groupId": "900544249083420672", "id": _MID,
    "correlationId": "900544249037303808",
    "attachments": [],
    "interactions": [{"groupId": "900544249083420672", "userId": _AID,
                      "readAt": 0, "deliveredAt": 0, "messageId": _MID}],
    "createdAt": 1788288661.818, "embeds": [], "content": "hey there"}}

_ECHO = {"type": 1, "message": {
    "type": 1, "attachments": [], "content": "our reply",
    "groupId": "900544249083420672", "senderId": _AID, "inReplyTo": "",
    "interactions": [], "id": "900528581705445378",
    "createdAt": 1788284926.39, "embeds": []}}


class _FakeSession:
    token = "SECRET-TOKEN"
    user_agent = "Mozilla/5.0 (captured)"
    account_id = _AID


class _FakeClient:
    session = _FakeSession()
    account_id = _AID
    user_agent = _FakeSession.user_agent
    proxy_url = None


def _wire(service_id: int, event: dict) -> dict:
    return {"t": 10000,
            "d": json.dumps({"serviceId": service_id,
                             "event": json.dumps(event)})}


async def _seed_account() -> None:
    async with get_session() as s:
        if await s.get(Account, _AID) is None:
            s.add(Account(id=_AID))


async def _drain_tasks() -> None:
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _rows() -> list:
    async with get_session() as s:
        return (await s.execute(
            select(Message).where(Message.account_id == _AID)
        )).scalars().all()



async def case_inbound_frame_persists_and_triggers():
    await _seed_account()
    _dispatched.clear()
    ws = FanslyWebSocket(_FakeClient())

    event = ws._translate(_wire(5, _INBOUND))
    assert event is not None, "the captured inbound frame must translate"
    assert list(event) == ["api2_chat_message"], (
        "must yield the exact key transcode routes on", list(event))

    await et.transcode({"__account_id": _AID, "__account_name": "test", **event})
    await _drain_tasks()

    rows = await _rows()
    assert len(rows) == 1, ("one frame → exactly one row", len(rows))
    r = rows[0]
    assert r.direction == "in", ("senderId != us ⇒ inbound", r.direction)
    assert r.message_id == int(_MID), r.message_id
    assert r.fan_id == int(_FAN), r.fan_id
    assert r.body == "hey there", r.body

    assert len(_dispatched) == 1, ("the trigger lane fires exactly once", _dispatched)
    assert _dispatched[0] == (_AID, int(_FAN), int(_MID)), _dispatched[0]


async def case_duplicate_frame_persists_once():
    await _seed_account()
    ws = FanslyWebSocket(_FakeClient())
    first = ws._translate(_wire(5, _INBOUND))
    second = ws._translate(_wire(5, _INBOUND))
    assert first is not None
    assert second is None, "a duplicate is dropped before the transcoder sees it"

    await et.transcode({"__account_id": _AID, **first})
    await _drain_tasks()
    assert len(await _rows()) == 1, "a duplicate must not double-persist"


async def case_outbound_echo_does_not_persist():
    await _seed_account()
    ws = FanslyWebSocket(_FakeClient())
    event = ws._translate(_wire(5, _ECHO))
    assert event is not None, (
        "the echo reaches the transcoder — direction is ITS call, not the pump's")
    assert event["api2_chat_message"]["fromUser"]["id"] == _AID

    before = len(await _rows())
    await et.transcode({"__account_id": _AID, **event})
    await _drain_tasks()
    after = len(await _rows())
    assert after == before, ("an outbound echo must not persist here", before, after)



@contextmanager
def _captured_info(logger_name: str):
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append          # type: ignore[method-assign]
    log = logging.getLogger(logger_name)
    prior = log.level
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        yield records
    finally:
        log.removeHandler(handler)
        log.setLevel(prior)


async def case_inbound_frame_logs_once():
    ws = FanslyWebSocket(_FakeClient())

    with _captured_info("fansly-ws") as records:
        assert ws._translate(_wire(5, _INBOUND)) is not None
        assert ws._translate(_wire(5, _INBOUND)) is None, "second is a duplicate"

    pump = [r for r in records
            if r.getMessage().startswith("ws-pump inbound message frame")]
    assert len(pump) == 1, (
        "a fresh frame logs once and a duplicate stays silent",
        [r.getMessage() for r in pump])
    assert pump[0].levelno == logging.INFO, (
        "debug is invisible in the running relay", pump[0].levelname)

    # Equality, not a blocklist: a DM is a real person's words and the relay log is not gitignored.
    assert pump[0].getMessage() == f"ws-pump inbound message frame id={_MID}", (
        "the id and nothing else", pump[0].getMessage())


if __name__ == "__main__":
    _harness.run(
        case_inbound_frame_persists_and_triggers,
        case_duplicate_frame_persists_once,
        case_outbound_echo_does_not_persist,
        case_inbound_frame_logs_once,
    )
