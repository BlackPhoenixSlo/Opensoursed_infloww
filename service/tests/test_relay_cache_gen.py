#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402

import relay_cache  # noqa: E402


async def case_invalidate_mid_flight_skips_write_back():
    ns, aid = "genguard", "acct-g1"
    relay_cache.invalidate(ns, aid)

    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_v1():
        started.set()
        await release.wait()
        return "v1-pre-change"

    task = asyncio.create_task(relay_cache.get_or_fetch(
        ns, aid, ("k",), ttl_seconds=60.0, fetcher=_slow_v1,
    ))
    await started.wait()
    relay_cache.invalidate(ns, aid)
    release.set()
    got = await task
    assert got == "v1-pre-change", got

    async def _v2():
        return "v2-post-change"
    fresh = await relay_cache.get_or_fetch(
        ns, aid, ("k",), ttl_seconds=60.0, fetcher=_v2,
    )
    assert fresh == "v2-post-change", f"zombie write-back served: {fresh}"
    relay_cache.invalidate(ns, aid)


async def case_no_invalidation_still_caches():
    ns, aid = "genguard", "acct-g2"
    relay_cache.invalidate(ns, aid)
    calls = []

    async def _fetch():
        calls.append(1)
        return "value"

    a = await relay_cache.get_or_fetch(ns, aid, ("k",), ttl_seconds=60.0, fetcher=_fetch)
    b = await relay_cache.get_or_fetch(ns, aid, ("k",), ttl_seconds=60.0, fetcher=_fetch)
    assert a == b == "value"
    assert len(calls) == 1, f"warm hit refetched: {calls}"
    relay_cache.invalidate(ns, aid)


async def case_guard_covers_uncached_keys():
    ns, aid = "genguard", "acct-g3"
    relay_cache.invalidate(ns, aid)

    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow():
        started.set()
        await release.wait()
        return "stale"

    task = asyncio.create_task(relay_cache.get_or_fetch(
        ns, aid, ("fresh-key",), ttl_seconds=60.0, fetcher=_slow,
    ))
    await started.wait()
    removed = relay_cache.invalidate(ns, aid)
    assert removed == 0, f"key unexpectedly cached already: {removed}"
    release.set()
    await task

    async def _fresh():
        return "fresh"
    got = await relay_cache.get_or_fetch(
        ns, aid, ("fresh-key",), ttl_seconds=60.0, fetcher=_fresh,
    )
    assert got == "fresh", f"pair-level guard failed, zombie cached: {got}"
    relay_cache.invalidate(ns, aid)


async def case_single_flight_survives_invalidation():
    ns, aid = "genguard", "acct-g4"
    relay_cache.invalidate(ns, aid)
    calls = []
    release = asyncio.Event()

    async def _fetch():
        calls.append(1)
        await release.wait()
        return "coalesced"

    t1 = asyncio.create_task(relay_cache.get_or_fetch(
        ns, aid, ("k",), ttl_seconds=60.0, fetcher=_fetch,
    ))
    await asyncio.sleep(0)
    relay_cache.invalidate(ns, aid)  # must NOT pop the live lock
    t2 = asyncio.create_task(relay_cache.get_or_fetch(
        ns, aid, ("k",), ttl_seconds=60.0, fetcher=_fetch,
    ))
    await asyncio.sleep(0)
    release.set()
    r1, r2 = await asyncio.gather(t1, t2)
    assert r1 == r2 == "coalesced"
    assert len(calls) <= 2, f"single-flight broken: {len(calls)} fetches"
    relay_cache.invalidate(ns, aid)


_harness.run(
    case_invalidate_mid_flight_skips_write_back,
    case_no_invalidation_still_caches,
    case_guard_covers_uncached_keys,
    case_single_flight_survives_invalidation,
)
