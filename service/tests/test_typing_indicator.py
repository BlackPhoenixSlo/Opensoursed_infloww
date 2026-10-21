"""Regression tests for the live "...is typing" indicator wiring.

Covers the automation-side seam (_common.hold_with_typing) + the of_ws pump
registry (register_pump / emit_typing / send_typing) WITHOUT any network:
a fake pump records the frames hold_with_typing pushes.

Run: ./venv/bin/python service/tests/test_typing_indicator.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB + TEST_MODE
import asyncio

import of_ws
from automations import _common

_harness.bootstrap()

AVA = "8000149"
FAN = 80000112


class FakePump:
    """Stands in for a live OFWebSocket: records every typing frame."""
    def __init__(self):
        self.sent: list[int] = []

    async def send_typing(self, fan_id: int) -> bool:
        self.sent.append(int(fan_id))
        return True


def _fast_reemit():
    """Shrink the re-emit gap so the test doesn't actually wait seconds."""
    _common._TYPING_REEMIT_S = 0.01


async def case_emits_through_registered_pump():
    _fast_reemit()
    pump = FakePump()
    of_ws.register_pump(AVA, pump)
    try:
        await _common.hold_with_typing(AVA, FAN, 0.05, typing_indicator=True)
    finally:
        of_ws.unregister_pump(AVA, pump)
    # 0.05s / 0.01s re-emit → several frames, all to the right fan.
    assert len(pump.sent) >= 2, ("expected re-emitted typing frames", pump.sent)
    assert set(pump.sent) == {FAN}, pump.sent


async def case_indicator_off_emits_nothing():
    _fast_reemit()
    pump = FakePump()
    of_ws.register_pump(AVA, pump)
    try:
        await _common.hold_with_typing(AVA, FAN, 0.05, typing_indicator=False)
    finally:
        of_ws.unregister_pump(AVA, pump)
    assert pump.sent == [], ("flag off must not emit", pump.sent)


async def case_no_pump_degrades_to_sleep():
    _fast_reemit()
    of_ws.unregister_pump(AVA)  # ensure none registered
    # Must complete cleanly even though emit_typing finds no socket.
    await _common.hold_with_typing(AVA, FAN, 0.03, typing_indicator=True)
    assert await of_ws.emit_typing(AVA, FAN) is False


async def case_zero_seconds_is_noop():
    pump = FakePump()
    of_ws.register_pump(AVA, pump)
    try:
        await _common.hold_with_typing(AVA, FAN, 0.0, typing_indicator=True)
    finally:
        of_ws.unregister_pump(AVA, pump)
    assert pump.sent == [], pump.sent


async def case_send_typing_no_socket_returns_false():
    # OFWebSocket with no live connection must no-op, not raise.
    ws = of_ws.OFWebSocket.__new__(of_ws.OFWebSocket)
    ws._live_ws = None
    assert await ws.send_typing(FAN) is False


if __name__ == "__main__":
    _harness.run(
        case_emits_through_registered_pump,
        case_indicator_off_emits_nothing,
        case_no_pump_degrades_to_sleep,
        case_zero_seconds_is_noop,
        case_send_typing_no_socket_returns_false,
    )
