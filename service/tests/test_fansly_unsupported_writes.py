#!/usr/bin/env python3
"""Writes Fansly does not have answer 501 on a Fansly account, not a fake success.

The Fansly shim keeps pin / unpin / mark-unread as `@fansly_unsupported` no-ops (success without effect, for any
automation caller). Through the Relay's routes that success made the app show a pin or an unread dot the next read
took back; `server._platform_write` turns the marker into a 501, which the
app's error paths roll back. On OnlyFans the same routes still reach the client.

  case_fansly_pin_unpin_answer_501
  case_fansly_mark_unread_answers_501_and_flips_nothing_locally
  case_of_client_still_reaches_the_writes
  case_shim_methods_carry_the_marker

Run: ./venv/bin/python service/tests/test_fansly_unsupported_writes.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import read_flip  # noqa: E402
import server  # noqa: E402
from fansly_shim import FanslyShimClient  # noqa: E402

_AID = "8802101"
FAN = 9101

# The real shim class, no session: the marked methods never touch `self`.
_shim = FanslyShimClient.__new__(FanslyShimClient)
_local: list[tuple] = []


class _FakeOF:
    def __init__(self) -> None:
        self.writes: list[tuple] = []

    def pin_message(self, message_id, user_id):
        self.writes.append(("pin", message_id, user_id))
        return {"success": True}

    def unpin_message(self, message_id, user_id):
        self.writes.append(("unpin", message_id, user_id))
        return {"success": True}

    def mark_chat_unread(self, chat_id):
        self.writes.append(("unread", chat_id))
        return {"success": True}


async def _record_local(account_id, *, fan_id, value):
    _local.append((account_id, fan_id, value))

server._resolve_account_id = lambda _req=None: _AID  # type: ignore[assignment]
read_flip.set_local_unread = _record_local          # type: ignore[assignment]
server._bust_chat_detail = lambda *a, **k: None      # type: ignore[assignment]


def _status(call) -> int:
    try:
        call()
    except server.HTTPException as e:
        return e.status_code
    return 200


async def _astatus(coro) -> int:
    try:
        await coro
    except server.HTTPException as e:
        return e.status_code
    return 200


def case_fansly_pin_unpin_answer_501():
    server._get_client = lambda *a, **k: _shim  # type: ignore[assignment]
    assert _status(lambda: server.of_pin_message(77, FAN)) == 501
    assert _status(lambda: server.of_unpin_message(77, FAN)) == 501


async def case_fansly_mark_unread_answers_501_and_flips_nothing_locally():
    server._get_client = lambda *a, **k: _shim  # type: ignore[assignment]
    _local.clear()
    assert await _astatus(server.of_mark_chat_unread(FAN)) == 501
    assert _local == [], f"a 501 still flipped the local unread badge: {_local}"


async def case_of_client_still_reaches_the_writes():
    fake = _FakeOF()
    server._get_client = lambda *a, **k: fake  # type: ignore[assignment]
    _local.clear()
    assert server.of_pin_message(77, FAN) == {"success": True}
    assert server.of_unpin_message(77, FAN) == {"success": True}
    assert await server.of_mark_chat_unread(FAN) == {"success": True}
    assert fake.writes == [("pin", 77, FAN), ("unpin", 77, FAN), ("unread", FAN)], fake.writes
    assert _local == [(_AID, FAN, 1)], _local


def case_shim_methods_carry_the_marker():
    # Automation callers still get the no-op's success, never the network.
    for name in ("pin_message", "unpin_message", "mark_chat_unread"):
        assert getattr(getattr(FanslyShimClient, name), "fansly_unsupported", None), name
        assert getattr(_shim, name)(77, FAN) == {"success": True}, name


_harness.run()
