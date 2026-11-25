#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

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
            time.sleep(0.03)
            return {"id": media_id, "type": "photo", "files": {}}
        finally:
            with self._lock:
                self.live -= 1


async def _drive(ids: list[int]) -> tuple[list[dict], _MeteredClient]:
    relay_coalesce.reset_for_tests()
    meter = _MeteredClient()

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
    ids = [9300] * 25 + list(range(9400, 9420))
    results, meter = await _drive(ids)

    assert len(results) == len(ids), "a starved request never returned"
    assert {r["id"] for r in results} == {9300} | set(range(9400, 9420)), \
        "an id resolved to the wrong media"
    assert meter.peak <= admission.VAULT_MEDIA_READ.cap, (
        f"peak {meter.peak} exceeded the cap of "
        f"{admission.VAULT_MEDIA_READ.cap} once waiters joined"
    )
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
