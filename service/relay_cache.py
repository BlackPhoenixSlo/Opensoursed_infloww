"""
relay_cache.py — in-process TTL cache with explicit WS-driven invalidation.

Sister of `vault_cache.py`, but tuned for hot-path OF endpoint responses
(/api/of/v2/init, list_chats, notifications_count, ...). Differences from
vault_cache:

  * vault_cache persists to SQLite (cross-restart, cross-employee). This
    module is RAM-only — fastest possible hit (no row decode, no I/O) at
    the cost of losing state on process restart.
  * vault_cache is content-driven (TTL only). This module supports
    explicit invalidation on WS events: when the OF realtime channel
    tells us a chat got a new message, the transcoder calls
    `invalidate("list_chats", account_id)` and the next caller goes
    upstream.
  * Single-flight on misses via a per-key `asyncio.Lock`, so N concurrent
    callers on a cold key produce ONE upstream fetch (not N).

Namespacing
-----------
Cache keys are tuples: `(namespace, account_id, key_extras)`. The
`namespace` is the logical endpoint label (e.g. "list_chats"). The
`account_id` is always included so an invalidation for one OF account
can never touch another. `key_extras` is a tuple of the per-call
parameters that affect the response (limit, offset, filter, ...).

If a Stage C call-site caches a response that varies by employee
(anything that the upstream serves differently per X-Employee-Id), the
employee_id MUST be included in `key_extras` — this module is
account-scoped, not employee-scoped.

Single-flight vs multi-worker
-----------------------------
Coalescing is process-local. Running uvicorn with `--workers > 1` gives
each worker its own cache + lock dict; invalidation in one worker does
not propagate to the others. The relay runs single-worker by design
(see Dockerfile: SQLite write-lock + WS pump singleton), so this is not
a problem today. If multi-worker is ever introduced, swap this module
for a Redis-backed implementation — the public API stays the same.
"""
from __future__ import annotations

import asyncio
import heapq
import logging
import time
from typing import Any, Awaitable, Callable

log = logging.getLogger("of-relay.relay_cache")

# Cache key shape: (namespace, account_id, key_extras_tuple).
# Cache value shape: (value, expires_at_monotonic).
_cache: dict[tuple[str, str, tuple], tuple[Any, float]] = {}

# Invalidation generation per (namespace, account_id). A fetch snapshots the
# generation BEFORE going upstream and only writes its result back if no
# invalidation bumped it meanwhile — otherwise an in-flight fetch that read
# upstream BEFORE a state change (e.g. mark-as-read, a WS-signalled message)
# resolves after the invalidation and silently re-caches the pre-change
# snapshot for a full TTL ("zombie" entries the invalidation was meant to
# kill). Pair-level (not per-key) so a fetch on a key with no cached entry
# yet is covered too. Bounded by namespace x account count.
_pair_gen: dict[tuple[str, str], int] = {}


def _bump_gen(namespace: str, account_id: str) -> None:
    pair = (namespace, account_id)
    _pair_gen[pair] = _pair_gen.get(pair, 0) + 1

# Per-key locks, only used on the miss path. Guarded by `_registry_lock`
# so two coroutines can't both create + register a fresh lock for the
# same key.
_locks: dict[tuple[str, str, tuple], asyncio.Lock] = {}
_registry_lock = asyncio.Lock()

# Per-namespace hit/miss counters for /admin/_debug/relay-cache-stats.
_hits: dict[str, int] = {}
_misses: dict[str, int] = {}


def _record_hit(namespace: str) -> None:
    _hits[namespace] = _hits.get(namespace, 0) + 1


def _record_miss(namespace: str) -> None:
    _misses[namespace] = _misses.get(namespace, 0) + 1


# ── Bounding ──────────────────────────────────────────────────────────
# Entries are never read past expiry (plus a namespace's stale-while-revalidate
# window), but nothing removed them either, and some keys carry free-form
# request values (date ranges, markers, search text): left alone the dict grew
# for the life of the process, and a caller could grow it on purpose.
#
# So a miss runs `_maintain`, which is O(1) almost always: ONE full sweep of the
# dead entries (and their idle locks) at most every `_SWEEP_INTERVAL_S`, or
# sooner when a write takes the cache past `_MAX_ENTRIES`. That crossing also
# evicts the soonest-to-expire down to the low-water mark (80% of the cap), so
# the next crossing is ~a thousand new keys away, not one. A dead entry thus
# lives at most one interval past its expiry, and no miss leaves the cache over
# the cap.
_MAX_ENTRIES = 5000
_LOW_WATER_RATIO = 0.8
_SWEEP_INTERVAL_S = 60.0
_next_sweep_at = 0.0
_sweeps = 0   # full sweeps run (stats(), tests)
# Per namespace, the longest stale-while-revalidate window a caller asked for:
# an entry that old past expiry can still be served stale, so it is not dead.
_ns_grace: dict[str, float] = {}


def _dead(key: tuple[str, str, tuple], expires_at: float, now: float) -> bool:
    return expires_at + _ns_grace.get(key[0], 0.0) <= now


def _idle_lock(key: tuple[str, str, tuple]) -> bool:
    """Nobody holds or waits on this key's lock, so dropping it cannot split
    single-flight. (A woken waiter sits in `_waiters` until it takes the lock;
    taking a free lock never yields, so there is no gap between the two.)"""
    lock = _locks.get(key)
    return lock is not None and not lock.locked() and not getattr(lock, "_waiters", None)


def _maintain(keep: tuple[str, str, tuple]) -> None:
    """Called on every miss, after its write; `keep` is the key just filled.
    Sync: no other coroutine runs mid-way (snapshots guard the worker threads
    that call `invalidate`)."""
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
    low_water = int(_MAX_ENTRIES * _LOW_WATER_RATIO)
    # Only a cap crossing evicts, and always down to low water even when the
    # sweep alone got under the cap: else the next crossing is a few misses away.
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
    """Return a cached value or fetch + cache.

    `fetcher` may be sync OR async. Sync fetchers are dispatched via
    `asyncio.to_thread` so they don't block the event loop — this lets
    call-sites pass `lambda: _proxy(...)` directly without wrapping.

    `bypass=True` (used by `?refresh=1` callers) skips the cache read
    but still writes the fresh result back, so the next non-bypass
    caller sees it.

    `stale_while_revalidate=N`: an entry that expired less than N seconds
    ago is returned as-is and ONE background refresh is started (single-
    flight through the same per-key lock). Only TTL expiry is softened —
    an `invalidate()` drops the entry, so the next read still misses.

    Exceptions from `fetcher` propagate; nothing is cached on failure.
    """
    key = (namespace, account_id, tuple(key_extras))
    if stale_while_revalidate > _ns_grace.get(namespace, 0.0):
        _ns_grace[namespace] = float(stale_while_revalidate)

    # Fast path: cache hit without acquiring any lock.
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


# Keys with a stale-while-revalidate refresh in flight, so a burst of stale
# reads starts one background fetch, not one per reader.
_revalidating: set[tuple[str, str, tuple]] = set()


async def _revalidate(key: tuple[str, str, tuple], ttl_seconds: float, fetcher) -> None:
    try:
        await _fetch_locked(key, ttl_seconds, fetcher, bypass=False)
    except Exception:
        # The stale entry stays; the next stale read retries.
        log.warning("relay_cache swr refresh failed ns=%s account=%s", key[0], key[1], exc_info=True)
    finally:
        _revalidating.discard(key)


async def _fetch_locked(
    key: tuple[str, str, tuple], ttl_seconds: float, fetcher, *, bypass: bool,
) -> Any:
    namespace, account_id, _extras = key
    # Miss path: acquire per-key lock so N concurrent callers on the
    # same cold key produce ONE upstream fetch.
    lock = await _get_or_make_lock(key)
    async with lock:
        # Re-check the cache after acquiring the lock. A peer coroutine
        # may have already populated it while we were queued.
        if not bypass:
            entry = _cache.get(key)
            if entry is not None:
                value, expires_at = entry
                if expires_at > time.monotonic():
                    _record_hit(namespace)
                    return value

        _record_miss(namespace)
        gen0 = _pair_gen.get((namespace, account_id), 0)
        if asyncio.iscoroutinefunction(fetcher):
            value = await fetcher()
        else:
            value = await asyncio.to_thread(fetcher)

        # Latest-wins: skip the write-back if an invalidation landed while we
        # were upstream — our snapshot predates it. The caller still gets the
        # value it fetched; the NEXT reader misses and re-fetches post-change
        # state. (See _pair_gen.)
        if _pair_gen.get((namespace, account_id), 0) == gen0:
            _cache[key] = (value, time.monotonic() + float(ttl_seconds))
        _maintain(keep=key)
        return value


def invalidate(
    namespace: str,
    account_id: str,
    *,
    match: Callable[[tuple], bool] | None = None,
) -> int:
    """Drop cached entries for (namespace, account_id).

    With `match=None`, drops every entry for that pair. Otherwise drops
    only entries whose `key_extras` tuple satisfies `match(extras)`.

    Sync (no I/O) so the transcoder can call it right after
    `await s.commit()` without an extra await. Returns the count removed.

    Note on ordering — the transcoder MUST call this AFTER committing
    its DB writes. If it runs before the commit, a concurrent reader
    can miss-the-cache, re-fetch the pre-commit upstream state, and
    cache it.
    """
    # Bump the pair generation FIRST — even when nothing is currently cached —
    # so any in-flight fetch under this pair skips its write-back instead of
    # re-caching pre-invalidation state (see _pair_gen). Locks are deliberately
    # NOT popped: dropping a live lock would let a second coroutine mint a
    # fresh one and defeat single-flight; the dict is bounded by keyspace.
    _bump_gen(namespace, account_id)
    removed = 0
    # Two passes to avoid mutating during iteration.
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


def patch(
    namespace: str,
    account_id: str,
    fn: Callable[[tuple, Any], Any],
) -> None:
    """Rewrite cached entries for (namespace, account_id) in place.

    `fn(key_extras, value)` returns the new value (keeps the entry and its
    expiry) or `None` (drops it, as `invalidate` would). `fn` must not mutate
    `value` — readers may still hold it — so build a copy.

    Bumps the pair generation like `invalidate`: a fetch in flight read
    upstream before the change being patched in, so its write-back must not
    overwrite the patched entry. Sync, call after the DB commit (same ordering
    rule as `invalidate`).
    """
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
        else:
            _cache[key] = (new_value, expires_at)


# The namespaces whose bodies show MONEY — see `invalidate_money_feeds`.
_MONEY_FEED_NAMESPACES = ("notifications", "notifications_count")


def invalidate_money_feeds(account_id: str) -> int:
    """Drop every cached view of an account's money.

    OF serves two facts off one upstream state — the notifications feed and
    its per-category badge counts — so a tip, a subscribe or a PPV unlock
    changes both at once. (The cached `/init` bootstrap, whose embedded counts
    were the third, went with its route in the 2026-10 cleanup.) Callers are the money-event paths: an inbound tip and a `toasts`
    frame (`event_transcoder`), and a PPV purchase
    (`purchase_notifications._broadcast_purchase`). Each is the server-side
    twin of a client-side `["notif-list", aid]` invalidation in
    `NotificationToaster` — the browser refetches the moment it hears the
    event, so if the relay does not drop its own entry on the SAME event,
    that refetch just re-reads our cached body and the feed lags the toast
    by a whole TTL.

    One named set rather than an `invalidate()` call per namespace per site,
    because they are one fact. Re-deriving the set at each event path is how
    the purchase lane — the only one that fires in production — ended up
    busting the feed but not the badge. A named set has one place to be
    wrong.

    Sync (RAM-only), like `invalidate`. Returns the total count removed.
    """
    removed = 0
    for namespace in _MONEY_FEED_NAMESPACES:
        removed += invalidate(namespace, account_id)
    return removed


def invalidate_account(account_id: str) -> int:
    """Drop EVERY cached entry for an account across ALL namespaces.

    `invalidate()` is namespace-scoped; this is the account-wide variant
    used when an account is removed (or re-added) so no hot-path cache
    (list_chats, my_settings, init, notifications, ...) can serve a
    dropped account's data to a later caller — or leak a prior session's
    data if the same account_id is re-captured. Strictly scoped to the
    one account_id, so it never touches another account's entries.

    Sync (RAM-only), like `invalidate`. Returns the count removed.
    """
    to_drop = [key for key in list(_cache) if key[1] == account_id]
    # Bump every namespace seen for this account (cached OR in flight via the
    # lock registry) so no in-flight fetch writes back after the wipe.
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
