from __future__ import annotations

import asyncio
import contextlib
import copy
import threading
from typing import Any, AsyncContextManager, Awaitable, Callable, TypeVar

T = TypeVar("T")

_inflight: dict[tuple, asyncio.Future] = {}

_coalesced_hits: dict[str, int] = {}
_first_calls: dict[str, int] = {}

priority_class: Callable[[], str] = lambda: "user"
admission: Callable[..., AsyncContextManager] = lambda own=False: contextlib.nullcontext()

_stats_lock = threading.Lock()


def _bump_hit(namespace: str) -> None:
    with _stats_lock:
        _coalesced_hits[namespace] = _coalesced_hits.get(namespace, 0) + 1


def _bump_first(namespace: str) -> None:
    with _stats_lock:
        _first_calls[namespace] = _first_calls.get(namespace, 0) + 1


def stats() -> dict[str, Any]:
    """Snapshot of coalescer activity for `/admin/coalesce/stats`."""
    with _stats_lock:
        return {
            "coalesced_hits": dict(_coalesced_hits),
            "first_calls": dict(_first_calls),
            "inflight": len(_inflight) + len(_running),
            "inflight_keys": [k[0] for k in (*_inflight.keys(), *_running.keys())],
        }


async def coalesce(key: tuple, fetcher: Callable[[], Awaitable[T]]) -> T:
    assert isinstance(key, tuple) and len(key) >= 1, "key must be a non-empty tuple"
    namespace = str(key[0])
    cls = priority_class()
    # A user read never joins a background-led flight (it would inherit the lane wait and retries); a background read may join a user-led one.
    existing = _inflight.get(key + (cls,))
    if existing is None and cls == "background":
        existing = _inflight.get(key + ("user",))
    key = key + (cls,)
    if existing is not None:
        _bump_hit(namespace)
        # shield: a cancelled waiter must not cancel the shared future for the other waiters.
        result = await asyncio.shield(existing)
        return copy.deepcopy(result)

    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    _inflight[key] = fut
    _bump_first(namespace)

    async def _run() -> None:
        try:
            async with admission():
                value = await fetcher()
            if not fut.done():
                fut.set_result(value)
        except BaseException as e:  # noqa: BLE001 — propagate ALL to waiters
            if not fut.done():
                fut.set_exception(e)
        finally:
            # A fast retry after set_result may already hold a fresh future; don't clobber it.
            if _inflight.get(key) is fut:
                _inflight.pop(key, None)

    asyncio.create_task(_run())
    # Leader shields too: if the originating request is cancelled the detached fetch must still serve the joiners.
    result = await asyncio.shield(fut)
    return copy.deepcopy(result)


_next: dict[tuple, asyncio.Future] = {}
_running: dict[tuple, asyncio.Future] = {}


async def coalesce_fresh(key: tuple, fetcher: Callable[[], Awaitable[T]]) -> T:
    assert isinstance(key, tuple) and len(key) >= 1, "key must be a non-empty tuple"
    namespace = str(key[0])
    fut = _next.get(key)
    if fut is not None:
        _bump_hit(namespace)
        return await asyncio.shield(fut)
    fut = _next[key] = asyncio.get_running_loop().create_future()
    fut.add_done_callback(lambda f: f.cancelled() or f.exception())
    _bump_first(namespace)

    async def _run() -> None:
        prev = _running.get(key)
        if prev is not None:
            await asyncio.wait([prev])
        if _next.get(key) is fut:
            _next.pop(key)
        _running[key] = fut
        try:
            fut.set_result(await fetcher())
        except BaseException as e:  # noqa: BLE001 — propagate ALL to waiters
            fut.set_exception(e)
        finally:
            if _running.get(key) is fut:
                _running.pop(key)

    asyncio.create_task(_run())
    return await asyncio.shield(fut)


def forget(account_id: str | None = None) -> None:
    for k in list(_inflight):
        if account_id is None or k[1] == account_id:
            _inflight.pop(k, None)


def reset_for_tests() -> None:
    _inflight.clear()
    _next.clear()
    _running.clear()
    with _stats_lock:
        _coalesced_hits.clear()
        _first_calls.clear()
