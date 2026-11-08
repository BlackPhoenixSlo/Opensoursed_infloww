#!/usr/bin/env python3
"""vault_cache TTL + proxy-switch staling + invalidate/put race + per-account user activity.

- every key (lists carry signed cover urls too) at most 20 h; the env sets the
  TTL, capped at 20 h; 0 disables.
- a proxy change for an account (proxies.save → server._on_proxy_switched)
  makes its cached vault pages misses; other accounts keep theirs. With the
  relay's loop running, the rows are also deleted, so a restart (RAM marks
  gone) cannot serve them.
- a put whose fetch started before the account's last invalidate is dropped.
- a user-priority lane entry records the account's last activity; a
  background one does not (of_pacing.last_user_at).

Run: ./venv/bin/python service/tests/test_vault_collect_cache.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import server  # noqa: E402  — registers the proxy-switch hook
import of_pacing  # noqa: E402
import proxies as proxy_registry  # noqa: E402
import vault_cache  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultResponseCache  # noqa: E402

LISTS = vault_cache.vault_lists_cache_key(limit=50)
MEDIA = vault_cache.vault_media_cache_key(list_id=7)
PAYLOAD = {"list": [{"id": 1}], "hasMore": False}


async def case_seed_accounts():
    async with get_session() as s:
        for a in ("accTTL", "accEnv", "accMoved", "accStays", "accPersist", "accRace"):
            s.add(Account(id=a))


async def _rows(aid: str) -> int:
    async with get_session() as s:
        return len((await s.execute(select(VaultResponseCache.query_key).where(
            VaultResponseCache.account_id == aid))).all())


async def _age(aid: str, key: str, seconds: float) -> None:
    async with get_session() as s:
        await s.execute(update(VaultResponseCache).where(
            VaultResponseCache.account_id == aid, VaultResponseCache.query_key == key,
        ).values(fetched_at=datetime.utcnow() - timedelta(seconds=seconds)))


async def _hit(aid: str, key: str) -> bool:
    return await vault_cache.get(aid, key) is not None


async def case_ttl_defaults():
    os.environ.pop("CHATTERLY_VAULT_CACHE_TTL_SECONDS", None)
    for k in (LISTS, MEDIA, "media-by-id:5"):
        await vault_cache.put("accTTL", k, PAYLOAD, started_at=datetime.utcnow())
        await _age("accTTL", k, 19 * 3600)
        assert await _hit("accTTL", k), f"{k} missed at 19 h"
        await _age("accTTL", k, 21 * 3600)
        assert not await _hit("accTTL", k), f"{k} served at 21 h (signed urls > 20 h)"


async def case_ttl_env_override():
    try:
        os.environ["CHATTERLY_VAULT_CACHE_TTL_SECONDS"] = "3600"
        assert vault_cache._ttl_seconds() == 3600
        os.environ["CHATTERLY_VAULT_CACHE_TTL_SECONDS"] = "200000"
        assert vault_cache._ttl_seconds() == 72000, "env above the signed-url cap"
        os.environ["CHATTERLY_VAULT_CACHE_TTL_SECONDS"] = "0"
        await vault_cache.put("accEnv", LISTS, PAYLOAD, started_at=datetime.utcnow())
        assert not await _hit("accEnv", LISTS), "TTL 0 must disable the cache"
    finally:
        os.environ.pop("CHATTERLY_VAULT_CACHE_TTL_SECONDS", None)


async def case_proxy_switch_stales_that_account_only():
    proxy_registry.REGISTRY_PATH = Path(tempfile.mkdtemp(prefix="vc_proxies_")) / "proxies.json"
    proxy_registry.REGISTRY_PATH.write_text(json.dumps({"proxies": []}))
    for aid in ("accMoved", "accStays"):
        for k in (LISTS, MEDIA):
            await vault_cache.put(aid, k, PAYLOAD, started_at=datetime.utcnow())
    assert await _hit("accMoved", MEDIA) and await _hit("accStays", MEDIA)
    proxy_registry.upsert({"label": "px1", "scheme": "http", "host": "10.0.0.1", "port": 8080})
    proxy_registry.assign_account("px1", "accMoved")       # egress changes → hook fires
    assert not await _hit("accMoved", MEDIA), "cached signed urls survived a proxy change"
    assert not await _hit("accMoved", LISTS)
    assert await _hit("accStays", MEDIA), "an unrelated account lost its cache"
    await vault_cache.put("accMoved", MEDIA, PAYLOAD, started_at=datetime.utcnow())      # re-warmed through the new IP
    assert await _hit("accMoved", MEDIA), "a fresh put after the switch must serve"


async def case_proxy_switch_survives_restart():
    """On the relay's loop the hook also deletes the rows: with the RAM marks
    gone (a restart), the old-IP pages are still not served."""
    for k in (LISTS, MEDIA):
        await vault_cache.put("accPersist", k, PAYLOAD, started_at=datetime.utcnow())
    server._on_proxy_switched(["accPersist"])
    for _ in range(100):
        await asyncio.sleep(0.01)
        if await _rows("accPersist") == 0:
            break
    vault_cache._invalidated_at.clear()                    # "restart": RAM is gone
    assert await _rows("accPersist") == 0, "proxy switch left the old-IP rows on disk"
    assert not await _hit("accPersist", MEDIA) and not await _hit("accPersist", LISTS)


async def case_put_started_before_invalidate_is_dropped():
    """A fetch that began before an invalidate (an upload, a folder edit, a
    proxy change) must not write its pre-mutation payload back after it."""
    t0 = datetime.utcnow()
    await vault_cache.invalidate("accRace")
    await vault_cache.put("accRace", MEDIA, PAYLOAD, started_at=t0)
    assert not await _hit("accRace", MEDIA), "pre-invalidate fetch was cached after it"
    vault_cache.mark_stale("accRace")
    t1 = datetime.utcnow()
    await vault_cache.put("accRace", MEDIA, PAYLOAD, started_at=t1)
    assert await _hit("accRace", MEDIA), "a fetch started after the invalidate must cache"


def case_user_lane_records_activity_background_does_not():
    of_pacing._last_user.pop("accLane", None)
    with server._priority_lane_background("accLane"):
        pass
    assert of_pacing.last_user_at("accLane") is None, "background lane counted as a user"
    with server._priority_lane("accLane", priority="user"):   # server job, no request
        pass
    assert of_pacing.last_user_at("accLane") is None, "requestless job counted as a user"
    token = server._request_ctx.set(object())                  # a real request in flight
    try:
        with server._priority_lane("accLane", priority="user"):
            pass
    finally:
        server._request_ctx.reset(token)
    assert of_pacing.last_user_at("accLane") is not None


_harness.run()
