from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

import run_slot

from .rhythm import INLINE_MAX_S

log = logging.getLogger("of-relay.automation.run_pool")

T = TypeVar("T")

_sleep = asyncio.sleep


@dataclass(slots=True)
class PoolResult:
    deferred: int = 0
    errors: list[BaseException] = field(default_factory=list)


async def run_paced(
    items: list[T], worker: Callable[[T], Awaitable[None]], *,
    concurrency: int, wall_budget_s: float, started_at: float,
    jitter_for: Callable[[T], float],
    clock: Callable[[], float] = time.monotonic,
) -> PoolResult:
    sem = asyncio.Semaphore(concurrency)
    tasks: list[asyncio.Task] = []
    result = PoolResult()

    async def _holding_the_slot(item: T) -> None:
        try:
            await _sleep(jitter_for(item))
            async with run_slot.borrowed(budget_s=INLINE_MAX_S):
                await worker(item)
        finally:
            sem.release()

    async with run_slot.lend(budget_s=INLINE_MAX_S):
        await _admit_and_gather(items, sem, tasks, result, _holding_the_slot,
                                wall_budget_s=wall_budget_s, started_at=started_at, clock=clock)
    return result


async def _admit_and_gather(items, sem, tasks, result, spawn_one, *,
                            wall_budget_s, started_at, clock) -> None:
    try:
        for i, item in enumerate(items):
            await sem.acquire()
            if clock() - started_at > wall_budget_s:
                sem.release()
                result.deferred = len(items) - i
                break
            tasks.append(asyncio.create_task(spawn_one(item)))
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                pass
        raise
    if tasks:
        for res in await asyncio.gather(*tasks, return_exceptions=True):
            # CancelledError is not an Exception: re-raise so a half-run batch is retried, not recorded as success.
            if isinstance(res, asyncio.CancelledError):
                raise res
            if isinstance(res, BaseException):
                result.errors.append(res)
