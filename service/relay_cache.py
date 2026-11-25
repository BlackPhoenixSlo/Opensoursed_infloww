from __future__ import annotations

import asyncio
import heapq
import itertools
import logging
import time
from typing import Any, Awaitable, Callable, NamedTuple

import relay_coalesce

log = logging.getLogger("of-relay.relay_cache")

_cache: dict[tuple[str, str, tuple], tuple[Any, float]] = {}

# A fetch snapshots this before going upstream and skips write-back if bumped, else an in-flight fetch re-caches pre-change state.
_pair_gen: dict[tuple[str, str], int] = {}


def _bump_gen(namespace: str, account_id: str) -> None:
    pair = (namespace, account_id)
    _pair_gen[pair] = _pair_gen.get(pair, 0) + 1

# Guarded by _registry_lock so two coroutines can't both mint a lock for one key.
_locks: dict[tuple[str, str, tuple], asyncio.Lock] = {}
_registry_lock = asyncio.Lock()

# A caller queued on the key's lock while the fetch failed gets that failure instead of going upstream again (single-flight on errors).
_failed: dict[tuple[str, str, tuple], tuple[BaseException, float]] = {}


# Write fence: of two classes fetching one key, the one that STARTED later wins, whichever finishes last.
_fetch_seq = itertools.count()
_written: dict[tuple[str, str, tuple], int] = {}


def _lock_key(key: tuple[str, str, tuple]) -> tuple[str, str, tuple]:
    cls = relay_coalesce.priority_class()
    return key if cls == "user" else (key[0], key[1], (*key[2], ("priority", cls)))


def _fresh(e: BaseException) -> BaseException:
    try:
        c = type(e).__new__(type(e))
        c.args = e.args
        c.__dict__.update(e.__dict__)
        return c
    except Exception:
        return e

_hits: dict[str, int] = {}
_misses: dict[str, int] = {}


def _record_hit(namespace: str) -> None:
    _hits[namespace] = _hits.get(namespace, 0) + 1


def _record_miss(namespace: str) -> None:
    _misses[namespace] = _misses.get(namespace, 0) + 1


# Keys carry free-form request values, so the cache is swept and capped or it grows for the life of the process.
_MAX_ENTRIES = 5000
_LOW_WATER_RATIO = 0.8
_SWEEP_INTERVAL_S = 60.0
_next_sweep_at = 0.0
_sweeps = 0
_ns_grace: dict[str, float] = {}


def _dead(key: tuple[str, str, tuple], expires_at: float, now: float) -> bool:
    return expires_at + _ns_grace.get(key[0], 0.0) <= now


def _idle_lock(key: tuple[str, str, tuple]) -> bool:
    lock = _locks.get(key)
    return lock is not None and not lock.locked() and not getattr(lock, "_waiters", None)


def _maintain(keep: tuple[str, str, tuple]) -> None:
    global _next_sweep_at, _sweeps
    now = time.monotonic()
    over_cap = len(_cache) > _MAX_ENTRIES
    if not over_cap and now < _next_sweep_at:
        return
    _next_sweep_at = now + _SWEEP_INTERVAL_S
    _sweeps += 1
    for k, entry in list(_cache.items()):
        if k != keep and _dead(k, entry[1], now):
            _cache.pop(k, None)
    for k in list(_locks):
        if k != keep and k not in _cache and _idle_lock(k):
            _locks.pop(k, None)
    for k in list(_failed):
        if k not in _locks:
            _failed.pop(k, None)
    for k in list(_written):
        if k not in _cache:
            _written.pop(k, None)
    low_water = int(_MAX_ENTRIES * _LOW_WATER_RATIO)
    if not over_cap or len(_cache) <= low_water:
        return
    victims = heapq.nsmallest(len(_cache) - low_water,
                              (e for e in list(_cache.items()) if e[0] != keep),
                              key=lambda e: e[1][1])
    for k, _entry in victims:
        _cache.pop(k, None)
        if _idle_lock(k):
            _locks.pop(k, None)
    log.info("relay_cache.evicted count=%d cap=%d low_water=%d",
             len(victims), _MAX_ENTRIES, low_water)


async def _get_or_make_lock(key: tuple[str, str, tuple]) -> asyncio.Lock:
    async with _registry_lock:
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        return lock


# Account-scoped: a response that varies by X-Employee-Id must carry the employee id in key_extras.
async def get_or_fetch(
    namespace: str,
    account_id: str,
    key_extras: tuple,
    ttl_seconds: float,
    fetcher: Callable[[], Awaitable[Any]] | Callable[[], Any],
    *,
    bypass: bool = False,
    stale_while_revalidate: float = 0.0,
) -> Any:
    key = (namespace, account_id, tuple(key_extras))
    if stale_while_revalidate > _ns_grace.get(namespace, 0.0):
        _ns_grace[namespace] = float(stale_while_revalidate)

    if not bypass:
        entry = _cache.get(key)
        if entry is not None:
            value, expires_at = entry
            now = time.monotonic()
            if expires_at > now:
                _record_hit(namespace)
                return value
            if expires_at + stale_while_revalidate > now:
                _record_hit(namespace)
                if key not in _revalidating:
                    _revalidating.add(key)
                    asyncio.create_task(
                        _revalidate(key, ttl_seconds, fetcher),
                        name=f"relay-cache-swr-{namespace}-{account_id}",
                    )
                return value

    return await _fetch_locked(key, ttl_seconds, fetcher, bypass=bypass)


_revalidating: set[tuple[str, str, tuple]] = set()


async def _revalidate(key: tuple[str, str, tuple], ttl_seconds: float, fetcher) -> None:
    try:
        # Own slot BEFORE the key lock: waiting for a slot while holding it deadlocks the slot holders queued on it.
        async with relay_coalesce.admission(own=True):
            await _fetch_locked(key, ttl_seconds, fetcher, bypass=False)
    except Exception:
        log.warning("relay_cache swr refresh failed ns=%s account=%s", key[0], key[1], exc_info=True)
    finally:
        _revalidating.discard(key)


async def _fetch_locked(
    key: tuple[str, str, tuple], ttl_seconds: float, fetcher, *, bypass: bool,
) -> Any:
    namespace, account_id, _extras = key
    lkey = _lock_key(key)
    lock = await _get_or_make_lock(lkey)
    arrived = time.monotonic()
    async with lock:
        failed = _failed.get(lkey)
        if failed is not None and failed[1] >= arrived:
            log.info("relay_cache %s account=%s: a queued caller gets the failure of the fetch it waited on "
                     "(%s; that first caller's retry policy decided it)",
                     namespace, account_id, type(failed[0]).__name__)
            raise _fresh(failed[0])
        if not bypass:
            entry = _cache.get(key)
            if entry is not None:
                value, expires_at = entry
                if expires_at > time.monotonic():
                    _record_hit(namespace)
                    return value

        _record_miss(namespace)
        gen0 = _pair_gen.get((namespace, account_id), 0)
        seq0 = next(_fetch_seq)
        try:
            if asyncio.iscoroutinefunction(fetcher):
                value = await fetcher()
            else:
                # A sync fetcher takes a worker thread: a background read waits for its Creator's background lane first.
                async with relay_coalesce.admission():
                    value = await asyncio.to_thread(fetcher)
        except Exception as e:
            _failed[lkey] = (e, time.monotonic())
            raise
        _failed.pop(lkey, None)

        # Latest-wins: skip write-back if an invalidation landed or the other class's later-started fetch already wrote.
        if _pair_gen.get((namespace, account_id), 0) == gen0 and seq0 > _written.get(key, -1):
            _cache[key] = (value, time.monotonic() + float(ttl_seconds))
            _written[key] = seq0
        _maintain(keep=key)
        return value


def peek(namespace: str, account_id: str, key_extras: tuple) -> Any | None:
    entry = _cache.get((namespace, account_id, tuple(key_extras)))
    return entry[0] if entry is not None else None


def peek_fresh(namespace: str, account_id: str, key_extras: tuple) -> Any | None:
    entry = _cache.get((namespace, account_id, tuple(key_extras)))
    return entry[0] if entry is not None and entry[1] > time.monotonic() else None


# Call only after the DB commit (same for patch): before it, a concurrent miss can re-cache pre-commit state.
def invalidate(
    namespace: str,
    account_id: str,
    *,
    match: Callable[[tuple], bool] | None = None,
) -> int:
    # Bump FIRST so in-flight fetches skip write-back; locks are NOT popped (a fresh lock would defeat single-flight).
    _bump_gen(namespace, account_id)
    removed = 0
    to_drop: list[tuple[str, str, tuple]] = []
    for key in list(_cache):
        ns, aid, extras = key
        if ns != namespace or aid != account_id:
            continue
        if match is not None and not match(extras):
            continue
        to_drop.append(key)
    for key in to_drop:
        _cache.pop(key, None)
        removed += 1
    if removed:
        log.debug(
            "relay_cache.invalidate ns=%s account=%s removed=%d",
            namespace, account_id, removed,
        )
    return removed


class Expired(NamedTuple):
    value: Any


def patch(
    namespace: str,
    account_id: str,
    fn: Callable[[tuple, Any], Any],
) -> None:
    _bump_gen(namespace, account_id)
    for key in [k for k in list(_cache) if k[0] == namespace and k[1] == account_id]:
        entry = _cache.get(key)
        if entry is None:
            continue
        value, expires_at = entry
        try:
            new_value = fn(key[2], value)
        except Exception:
            log.warning("relay_cache.patch fn failed ns=%s account=%s", namespace, account_id, exc_info=True)
            new_value = None
        if new_value is None:
            _cache.pop(key, None)
        elif isinstance(new_value, Expired):
            _cache[key] = (new_value.value, min(expires_at, time.monotonic()))
        else:
            _cache[key] = (new_value, expires_at)


_MONEY_FEED_NAMESPACES = ("notifications", "notifications_count", "chat_pinned", "payouts")


def invalidate_money_feeds(account_id: str) -> int:
    removed = 0
    for namespace in _MONEY_FEED_NAMESPACES:
        removed += invalidate(namespace, account_id)
    return removed


def invalidate_account(account_id: str) -> int:
    to_drop = [key for key in list(_cache) if key[1] == account_id]
    for ns in {key[0] for key in to_drop} | {key[0] for key in list(_locks) if key[1] == account_id}:
        _bump_gen(ns, account_id)
    for key in to_drop:
        _cache.pop(key, None)
    if to_drop:
        log.debug(
            "relay_cache.invalidate_account account=%s removed=%d",
            account_id, len(to_drop),
        )
    return len(to_drop)


def stats() -> dict[str, Any]:
    """Snapshot of hit/miss counters + current entry counts.

    Exposed via /admin/_debug/relay-cache-stats. Useful for tuning TTLs
    once Stage C wires real namespaces in — a namespace with 0 hits
    after a warm-up window is either keyed wrong (per-employee data
    cached account-wide?) or has TTL=0 / always-bypass callers.
    """
    namespaces = set(_hits) | set(_misses)
    per_ns: dict[str, dict[str, int]] = {}
    for ns in namespaces:
        per_ns[ns] = {
            "hits": _hits.get(ns, 0),
            "misses": _misses.get(ns, 0),
        }
    entries_per_ns: dict[str, int] = {}
    for (ns, _aid, _extras) in list(_cache):
        entries_per_ns[ns] = entries_per_ns.get(ns, 0) + 1
    return {
        "namespaces": per_ns,
        "entries": entries_per_ns,
        "total_entries": len(_cache),
        "total_locks": len(_locks),
        "sweeps": _sweeps,
    }
