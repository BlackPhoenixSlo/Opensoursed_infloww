#!/usr/bin/env python3
"""`chat_responded` from a person's send (server._record_fan_send): carries OF's answer cut to the row's preview
and an `at`, so every other tab moves the fan's row in its cached chat lists without a read (app
hooks/useInboxRealtime.ts). The chat-list cache is busted BEFORE it goes out: a list read served after the event
(a page whose `askedAt` is past `at`, left alone by the app) already holds the reply.

Run: venv/bin/python -m pytest service/tests/test_chat_responded_sse.py -q
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # pytest: tests/ is a package
import _harness  # noqa: E402  (first: temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402

import events  # noqa: E402
import server  # noqa: E402

AID, FAN = "acct-reply", 9101


def _send(result):
    """`_record_fan_send(result)`; returns the ordered log of busts and published events."""
    log: list = []
    orig = (events.publish, server._bust_chat_list_and_badges)
    events.publish = lambda e: log.append(("publish", e))
    server._bust_chat_list_and_badges = lambda aid, fan=None: log.append(("bust", aid, fan))
    try:
        asyncio.run(server._record_fan_send(AID, FAN, result, employee_id=None, price=0))
    finally:
        events.publish, server._bust_chat_list_and_badges = orig
    return log


def test_reply_carries_message_after_bust():
    log = _send({"id": 501, "text": "hey you", "createdAt": "2026-11-20T10:00:00+00:00", "mediaCount": 2,
                 "price": 0, "fromUser": {"id": 1}})
    kinds = [x[0] for x in log if x[0] == "bust" or "chat_responded" in x[1]]
    assert kinds == ["bust", "publish"], log
    ev = next(x[1] for x in log if x[0] == "publish" and "chat_responded" in x[1])
    assert ev["__account_id"] == AID, ev
    body = ev["chat_responded"]
    assert isinstance(body.pop("at"), int), body
    assert body == {"fan_id": FAN, "by": "", "message": {
        "id": 501, "text": "hey you", "createdAt": "2026-11-20T10:00:00+00:00", "mediaCount": 2, "price": 0.0}}, body


def test_reply_without_an_answer_body_still_announces():
    """A non-dict answer (a shim's odd shape) keeps the bell's announcement; tabs then have no row to patch."""
    log = _send(None)
    ev = next(x[1] for x in log if x[0] == "publish" and "chat_responded" in x[1])
    assert "message" not in ev["chat_responded"] and ev["chat_responded"]["fan_id"] == FAN, ev


if __name__ == "__main__":
    test_reply_carries_message_after_bust()
    test_reply_without_an_answer_body_still_announces()
    print("ok")
