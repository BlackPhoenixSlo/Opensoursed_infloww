"""The Model-call cap: one Relay-wide bound on automation `llm_client.chat` calls in flight
while their run has handed its Run slot back (spec docs/spec/ingest-llm-caps/phase-0B).

WHY. A run gives its slot back while a model answers (`run_slot.freed`: Full AI Turns, the
model-reply senders, free masses), so the run slots bound only slot work. Model waits were
bounded only by per-Creator caps x Creators: at 50 Creators, ~200 Full AI calls plus the
senders' at once on a 4-core box and one SQLite writer. This pool bounds them.

WHO WAITS (`applies`): only a call from an automation run whose slot is given back right now.
- No run (app requests, the Test chat, help assistant drafts, manual tools: Employee model
  calls): bypass. Loops outside every run (vault describe, customs_watch) bypass the same way.
- An operator-kind run: bypass (operator work never waits behind automation).
- A run that still holds its slot (photo describe in a Turn, gen_info, mass drafts, the release
  kill switch off): bypass; the slot pools bound it, and it must never wait while pinning a slot.

THE WAIT has a deadline: `WAIT_S`, cut to the call's own model timeout. Past it
`ModelCapTimeout` (llm_client re-raises it as `LLMModelCapTimeout`, read by callers as a model
timeout). llm_client enters `call()` before any spend reservation, audit row or request, and
holds the permit through the request and its retries (one permit per `chat`).

The bound is the Concurrency panel knob `AUTOMATION_MAX_MODEL_CALLS` (env > stored > default),
read at each capped call, so a saved value applies at the next call. A wait of `LONG_WAIT_S` or
more, and every timeout, logs one `model_cap_wait` line (proxy-health watch `model_cap_wait`).

Jev requests (`automations/_jev`, FM relevance) never enter it: Jev's 10 s timeout would fail
first under saturation, a silent selling change.

A leaf: imports lane_config, run_slot, stdlib.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import AsyncIterator

import lane_config
import run_slot

log = logging.getLogger("of-relay.model_cap")

ENV = "AUTOMATION_MAX_MODEL_CALLS"
DEFAULT = 50          # ~one call in flight per Creator at the <=50-Creator target (spec: reasoned, not measured)
WAIT_S = 20.0         # the longest a capped call waits for a permit (cut to its own model timeout)
LONG_WAIT_S = 5.0     # a wait this long or longer is logged

# Fresh tier only: FIFO, live resize, a cancelled waiter passes its permit on.
_pool = run_slot.SlotPool(lane_config.resolve_live(ENV, DEFAULT))   # registers the panel row at import


class ModelCapTimeout(Exception):
    """No permit within the call's deadline: nothing was reserved, recorded or sent."""

    def __init__(self, waited_s: float, cap: int):
        self.waited_s, self.cap = waited_s, cap
        super().__init__(f"model-call cap: waited {waited_s:.1f}s (cap {cap})")


def applies() -> bool:
    """Does this task's model call take a permit? Only an automation run's, slot given back."""
    r = run_slot.run_of_task()
    return r is not None and not r.operator and not r.held


def in_flight() -> int:
    """Permits held now (the log line's `in_flight`, and tests)."""
    return _pool.n - _pool.free


def queued() -> int:
    """Calls waiting for a permit now (a cancelled one counts until its task runs its handler)."""
    return sum(_pool.queued())


def _log(outcome: str, purpose: str, waited_s: float, cap: int) -> None:
    log.warning("model_cap_wait outcome=%s purpose=%s waited_ms=%d cap=%d in_flight=%d queued=%d",
                outcome, purpose or "-", int(waited_s * 1000), cap, in_flight(), queued())


@contextlib.asynccontextmanager
async def call(wait_s: float, *, purpose: str) -> AsyncIterator[None]:
    """Hold one permit for the body when `applies()`; else a pass-through. Waits at most
    `min(wait_s, WAIT_S)`, then raises `ModelCapTimeout`. The permit goes back on any exit."""
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
