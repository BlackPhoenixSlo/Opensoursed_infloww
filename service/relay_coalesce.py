"""In-flight request coalescer for idempotent OF GETs.

Collapses concurrent identical in-flight relay GETs onto a single
upstream OF call. This is **dedup, not caching** — each unique request
still hits OF once. The win is when multiple chatters (or multiple
tabs/popouts of the same chatter) request the same data within a
100-500ms window.

The coalescer sits OUTSIDE the per-account priority lane in
`server._proxy`, so waiters joining an in-flight request do NOT hold
a semaphore slot each — only the original fetcher does.

────────────────────────────────────────────────────────────────────────
DO NOT coalesce a handler if any of these hold:
  • body (or any helper it calls) reads `X-Employee-Id`
  • body calls `attribution.resolve()` (service/attribution.py:51)
  • body calls `resolve_employee_id` / `_employee_for_request`
    (service/employees.py:559+)
  • any POST/PUT/PATCH/DELETE
  • response carries per-caller context (e.g. /admin/errors,
    /employees/whoami, /admin/stats/*, /admin/automations/*)
  • send/queue endpoints — must run per-chatter for attribution

Known X-Employee-Id read sites (grep `service/`):
  server.py:1477, 2738, 2745, 2841, 2888, 2899
  messages.py:131, 143, 146
  employees.py:530, 542, 559, 782, 833, 860, 886, 985
  attribution.py:51
────────────────────────────────────────────────────────────────────────

Allowlist lives in `service/server.py` next to each wrapped endpoint —
this is an explicit per-endpoint list, NOT a `@coalesce` decorator that
auto-applies to GETs. A blanket decorator is a footgun for attribution.

The one POST on it, by exception:
  • `vault_sync` (service/vault_ai_api.py, POST /admin/vault-ai/sync, keyed
    account + folder): Vault Pro's Refresh. It sends nothing to OF (GETs of
    vault/media only, upserted into the mirror idempotently), reads no
    employee attribution and answers no per-caller data (page / item counts
    of the shared walk), so a second press during a walk joins it instead
    of paying OF for the same pages.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import threading
from typing import Any, AsyncContextManager, Awaitable, Callable, TypeVar

T = TypeVar("T")

# Keyed by the full tuple supplied by the caller. The first element is
# the namespace ("list_chats", "list_users", ...) used for stats.
_inflight: dict[tuple, asyncio.Future] = {}

# Stats: number of waiters that joined an already-in-flight request,
# per namespace. The original (first) caller does NOT increment this —
# only joiners do. Read via `/admin/coalesce/stats`.
_coalesced_hits: dict[str, int] = {}
_first_calls: dict[str, int] = {}

# Two hooks server.py installs at import (defaults: one class, no admission), so
# this module stays importable alone and never imports server:
#   priority_class()  "user" | "background", the request's (X-Priority). A user
#                     read never joins a background-led flight: it would inherit
#                     the background lane wait, the 5-try retry and its failure.
#                     A background read may join a user-led one (same class first).
#   admission()       an async context manager the LEADER enters around its fetch:
#                     a background read waits for its Creator's background lane on
#                     the event loop, before any worker thread is taken (server.
#                     _bg_admission). Joiners never take a slot.
priority_class: Callable[[], str] = lambda: "user"
admission: Callable[[], AsyncContextManager] = contextlib.nullcontext

# Guards `_coalesced_hits` and `_first_calls`. The `_inflight` dict is
# only mutated from inside the event loop, so it doesn't need a lock.
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
    """If a fetcher is already in flight for `key`, await its result.
    Otherwise start one. Each waiter gets a `copy.deepcopy` of the
    result so post-return mutations by one waiter can't leak into
    another waiter's response.

    Exceptions from the fetcher propagate to ALL waiters via
    `future.set_exception(e)`; no waiter retries on its own.

    The flight key is `key` + the caller's `priority_class()` (above).

    The fetcher runs in a detached `asyncio.create_task` so that
    cancellation of the original awaiter does NOT abort the upstream
    call — other waiters still get a result.

    `key` must be a hashable tuple. By convention, key[0] is the
    namespace label (used for stats grouping) and the remaining slots
    fully identify the request, INCLUDING account_id — otherwise two
    chatters on different OF accounts would share a response."""
    assert isinstance(key, tuple) and len(key) >= 1, "key must be a non-empty tuple"
    namespace = str(key[0])
    cls = priority_class()
    existing = _inflight.get(key + (cls,))
    if existing is None and cls == "background":
        existing = _inflight.get(key + ("user",))
    key = key + (cls,)
    if existing is not None:
        _bump_hit(namespace)
        # `shield` so a cancelled waiter doesn't propagate `.cancel()` to
        # the shared future (which would knock out every other waiter).
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
            # Clear the in-flight entry only if it still points to us.
            # If a fast retry happened after set_result, _inflight may
            # already hold a fresh future — don't clobber it.
            if _inflight.get(key) is fut:
                _inflight.pop(key, None)

    asyncio.create_task(_run())
    # Leader uses shield too — if the request that kicked off the fetch
    # is cancelled, the detached fetcher task must keep running so the
    # joined waiters still get a result.
    result = await asyncio.shield(fut)
    return copy.deepcopy(result)


# `coalesce_fresh`: per key, the run callers arriving now join (not started yet) and the run in progress.
_next: dict[tuple, asyncio.Future] = {}
_running: dict[tuple, asyncio.Future] = {}


async def coalesce_fresh(key: tuple, fetcher: Callable[[], Awaitable[T]]) -> T:
    """`coalesce` for a read that must see every write committed before the call (a local-DB list read
    right after the caller's own PUT): a caller never joins a run that already started; it joins, or
    starts, the NEXT run, which begins once the current one ends. N concurrent callers cost at most two
    runs. Every waiter gets the SAME object (no deepcopy), so return an immutable value (encoded bytes).
    Detached and shielded like `coalesce`; an exception reaches every waiter of that run."""
    assert isinstance(key, tuple) and len(key) >= 1, "key must be a non-empty tuple"
    namespace = str(key[0])
    fut = _next.get(key)
    if fut is not None:
        _bump_hit(namespace)
        return await asyncio.shield(fut)
    fut = _next[key] = asyncio.get_running_loop().create_future()
    fut.add_done_callback(lambda f: f.cancelled() or f.exception())  # no "never retrieved" if all left
    _bump_first(namespace)

    async def _run() -> None:
        prev = _running.get(key)
        if prev is not None:
            await asyncio.wait([prev])
        if _next.get(key) is fut:
            _next.pop(key)  # started: later callers make the next run
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


def reset_for_tests() -> None:
    """Wipe state. Only call from test scripts."""
    _inflight.clear()
    _next.clear()
    _running.clear()
    with _stats_lock:
        _coalesced_hits.clear()
        _first_calls.clear()
