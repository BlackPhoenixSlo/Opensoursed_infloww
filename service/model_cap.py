# Jev requests never enter the cap: its 10 s timeout would fail first under saturation, a silent selling change.
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import AsyncIterator

import lane_config
import run_slot

log = logging.getLogger("of-relay.model_cap")

ENV = "AUTOMATION_MAX_MODEL_CALLS"
DEFAULT = 50  # ~one call in flight per Creator at the 50-Creator target (reasoned, not measured)
WAIT_S = 20.0
LONG_WAIT_S = 5.0

_pool = run_slot.SlotPool(lane_config.resolve_live(ENV, DEFAULT))


class ModelCapTimeout(Exception):

    def __init__(self, waited_s: float, cap: int):
        self.waited_s, self.cap = waited_s, cap
        super().__init__(f"model-call cap: waited {waited_s:.1f}s (cap {cap})")


def applies() -> bool:
    r = run_slot.run_of_task()
    return r is not None and not r.operator and not r.held


def in_flight() -> int:
    return _pool.n - _pool.free


def queued() -> int:
    return sum(_pool.queued())


def _log(outcome: str, purpose: str, waited_s: float, cap: int) -> None:
    log.warning("model_cap_wait outcome=%s purpose=%s waited_ms=%d cap=%d in_flight=%d queued=%d",
                outcome, purpose or "-", int(waited_s * 1000), cap, in_flight(), queued())


@contextlib.asynccontextmanager
async def call(wait_s: float, *, purpose: str) -> AsyncIterator[None]:
    if not applies():
        yield
        return
    cap = lane_config.resolve_live(ENV, DEFAULT)
    if cap != _pool.n:
        _pool.resize(cap)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    try:
        await asyncio.wait_for(_pool.acquire(), min(wait_s, WAIT_S))
    except TimeoutError:
        waited = loop.time() - t0
        _log("timeout", purpose, waited, cap)
        raise ModelCapTimeout(waited, cap) from None
    waited = loop.time() - t0
    if waited >= LONG_WAIT_S:
        _log("got", purpose, waited, cap)
    try:
        yield
    finally:
        _pool.release()
