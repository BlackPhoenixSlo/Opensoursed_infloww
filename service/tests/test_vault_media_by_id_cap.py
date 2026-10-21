#!/usr/bin/env python3
"""
`GET /api/of/v2/vault/media/{id}` — the by-id vault read's admission gate.
Plain-assert, no pytest (repo convention).

Why this suite exists. This is the route the UI asks for a WHOLE LIBRARY at a
time: `useVaultMediaByIds` fans out one request per stored media id, and
PPVLibraryTab hands it every id in the library. `_proxy` already caps UPSTREAM
calls per account, but it does so with a `threading.BoundedSemaphore` acquired
INSIDE `asyncio.to_thread` — so every queued call first takes one of the 64
asyncio executor threads and then blocks on it. The upstream was protected; the
executor was not, and the automation lane shares that executor.

Descriptors are a PROCESS resource, so when that queue got long the shortage
surfaced everywhere but here: sqlite answering "unable to open database file",
`scandir` answering EMFILE in the isolation gate (2026-07-28, 2026-08-08). The
route now parks waiters on the event loop instead of on threads, and coalesces
concurrent requests for the same id onto one upstream call.

Cases:
  case_a_library_pane_is_capped   — 40 DIFFERENT ids never put more than
                                    `admission.VAULT_MEDIA_READ.cap` calls in flight,
                                    and every one of them still resolves.
  case_the_cap_is_not_a_queue     — …but more than one runs at a time. A cap
                                    that serialised would make a real library
                                    unusable, which is how a fix gets reverted.
  case_same_id_collapses          — 25 requests for ONE id cost ONE OF call.
  case_a_waiter_holds_no_slot     — the collapse must happen OUTSIDE the slot,
                                    or 25 waiters for one id would occupy every
                                    slot and starve the other ids.

Exit 0 = all cases passed. Temp DB bound by _harness (never prod).
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import relay_coalesce  # noqa: E402
import admission  # noqa: E402
import server  # noqa: E402
import vault_cache  # noqa: E402

_AID = "8000149"


class _MeteredClient:
    """Stands in for the pooled OFClient, recording overlap.

    The upstream call runs under `asyncio.to_thread`, so the counter is guarded
    by a real lock — this measures actual thread overlap, not scheduling intent.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.live = 0
        self.peak = 0
        self.calls: list[int] = []

    def vault_media_by_id(self, media_id: int) -> dict:
        with self._lock:
            self.live += 1
            self.peak = max(self.peak, self.live)
            self.calls.append(media_id)
        try:
            # Long enough that anything allowed to overlap actually does. A cap
            # that "passes" because the work finished too fast to collide
            # proves nothing.
            time.sleep(0.03)
            return {"id": media_id, "type": "photo", "files": {}}
        finally:
            with self._lock:
                self.live -= 1


async def _drive(ids: list[int]) -> tuple[list[dict], _MeteredClient]:
    """Fire `ids` concurrently at the real route and return (results, meter)."""
    relay_coalesce.reset_for_tests()
    meter = _MeteredClient()

    # The seams. The route resolves + owner-gates the account off the request
    # context, which there is none of here. `vault_cache` is pinned to a
    # permanent MISS on purpose: it is not what these cases are about, and a
    # cache that answered would hide whether the gate below it works at all —
    # every assertion here has to come from the slot and the coalescer.
    #
    # `_proxy` stays REAL. It holds the OTHER (threading) semaphore, and the
    # whole point of this suite is where the waiting happens — a test that
    # stubbed it out would not be measuring the path production takes.
    real_resolve = server._resolve_account_id
    real_owned = server.assert_account_owned
    real_client = server._get_client
    real_get, real_put = vault_cache.get, vault_cache.put

    async def _always_miss(*_a, **_kw):
        return None

    async def _swallow(*_a, **_kw):
        return None

    server._resolve_account_id = lambda _req: _AID
    server.assert_account_owned = lambda _aid: None
    server._get_client = lambda *a, **kw: meter
    vault_cache.get, vault_cache.put = _always_miss, _swallow
    try:
        results = await asyncio.gather(*[
            server.of_vault_media_by_id(mid) for mid in ids
        ])
    finally:
        server._resolve_account_id = real_resolve
        server.assert_account_owned = real_owned
        server._get_client = real_client
        vault_cache.get, vault_cache.put = real_get, real_put
    return results, meter


async def case_a_library_pane_is_capped():
    ids = list(range(9000, 9040))
    results, meter = await _drive(ids)

    assert [r["id"] for r in results] == ids, "a capped read must still resolve"
    assert meter.peak <= admission.VAULT_MEDIA_READ.cap, (
        f"{len(ids)} ids put {meter.peak} calls in flight; cap is "
        f"{admission.VAULT_MEDIA_READ.cap} — the fd guard is not holding"
    )


async def case_the_cap_is_not_a_queue():
    _, meter = await _drive(list(range(9100, 9140)))
    assert meter.peak > 1, (
        "the cap collapsed to a serial queue — a library of 200 ids would "
        "resolve one round-trip at a time"
    )


async def case_same_id_collapses():
    results, meter = await _drive([9200] * 25)
    assert all(r["id"] == 9200 for r in results), "every caller must get the media"
    assert len(meter.calls) == 1, (
        f"25 requests for ONE id made {len(meter.calls)} OF calls — the "
        "coalescer is not collapsing them"
    )


async def case_a_waiter_holds_no_slot():
    """25 requests for one id plus enough distinct ids to fill the cap twice
    over. If waiters held slots, the single-id pile would occupy the gate and
    the distinct ids would be starved behind it — so assert the distinct ones
    all still resolve AND the peak still respects the cap."""
    ids = [9300] * 25 + list(range(9400, 9420))
    results, meter = await _drive(ids)

    assert len(results) == len(ids), "a starved request never returned"
    assert {r["id"] for r in results} == {9300} | set(range(9400, 9420)), \
        "an id resolved to the wrong media"
    assert meter.peak <= admission.VAULT_MEDIA_READ.cap, (
        f"peak {meter.peak} exceeded the cap of "
        f"{admission.VAULT_MEDIA_READ.cap} once waiters joined"
    )
    # 20 distinct ids + one collapsed call for the 25 duplicates.
    assert len(meter.calls) == 21, (
        f"expected 21 upstream calls (20 distinct + 1 collapsed), got "
        f"{len(meter.calls)}"
    )


_harness.run(
    case_a_library_pane_is_capped,
    case_the_cap_is_not_a_queue,
    case_same_id_collapses,
    case_a_waiter_holds_no_slot,
)
