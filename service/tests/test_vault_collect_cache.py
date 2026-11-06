#!/usr/bin/env python3
"""vault_cache TTL split + proxy-switch staling + per-account user activity.

- lists keep 7 d, media pages (signed urls) at most 20 h; the env sets the
  lists TTL and media = min(env, 20 h).
- a proxy change for an account (proxies.save → server._on_proxy_switched)
  makes its cached vault pages misses; other accounts keep theirs.
- a user-priority lane entry records the account's last activity; a
  background one does not (relay_host.last_user_activity_at).

Run: ./venv/bin/python service/tests/test_vault_collect_cache.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import update  # noqa: E402

import server  # noqa: E402  — registers the proxy-switch hook
import of_pacing  # noqa: E402
import proxies as proxy_registry  # noqa: E402
import relay_host  # noqa: E402
import vault_cache  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultResponseCache  # noqa: E402

LISTS = vault_cache.vault_lists_cache_key(limit=50)
MEDIA = vault_cache.vault_media_cache_key(list_id=7)
PAYLOAD = {"list": [{"id": 1}], "hasMore": False}


async def case_seed_accounts():
    async with get_session() as s:
        for a in ("accTTL", "accEnv", "accMoved", "accStays"):
            s.add(Account(id=a))


async def _age(aid: str, key: str, seconds: float) -> None:
    async with get_session() as s:
        await s.execute(update(VaultResponseCache).where(
            VaultResponseCache.account_id == aid, VaultResponseCache.query_key == key,
        ).values(fetched_at=datetime.utcnow() - timedelta(seconds=seconds)))


async def _hit(aid: str, key: str) -> bool:
    return await vault_cache.get(aid, key) is not None


async def case_ttl_split_defaults():
    os.environ.pop("CHATTERLY_VAULT_CACHE_TTL_SECONDS", None)
    for k in (LISTS, MEDIA):
        await vault_cache.put("accTTL", k, PAYLOAD)
        await _age("accTTL", k, 21 * 3600)
    assert await _hit("accTTL", LISTS), "lists gone after 21 h (want 7 d)"
    assert not await _hit("accTTL", MEDIA), "media page served at 21 h (signed urls > 20 h)"
    await _age("accTTL", MEDIA, 19 * 3600)
    assert await _hit("accTTL", MEDIA), "media page missed at 19 h"
    await _age("accTTL", LISTS, 6.9 * 86400)
    assert await _hit("accTTL", LISTS)
    await _age("accTTL", LISTS, 7.1 * 86400)
    assert not await _hit("accTTL", LISTS), "lists served past 7 d"
    # Unknown prefixes (media-by-id) carry signed urls too → media cap.
    assert vault_cache._ttl_seconds("media-by-id:5") == 72000


async def case_ttl_env_override():
    try:
        os.environ["CHATTERLY_VAULT_CACHE_TTL_SECONDS"] = "3600"
        assert (vault_cache._ttl_seconds(LISTS), vault_cache._ttl_seconds(MEDIA)) == (3600, 3600)
        os.environ["CHATTERLY_VAULT_CACHE_TTL_SECONDS"] = "200000"
        assert (vault_cache._ttl_seconds(LISTS), vault_cache._ttl_seconds(MEDIA)) == (200000, 72000)
        os.environ["CHATTERLY_VAULT_CACHE_TTL_SECONDS"] = "0"
        await vault_cache.put("accEnv", LISTS, PAYLOAD)
        assert not await _hit("accEnv", LISTS), "TTL 0 must disable the cache"
    finally:
        os.environ.pop("CHATTERLY_VAULT_CACHE_TTL_SECONDS", None)


async def case_proxy_switch_stales_that_account_only():
    proxy_registry.REGISTRY_PATH = Path(tempfile.mkdtemp(prefix="vc_proxies_")) / "proxies.json"
    proxy_registry.REGISTRY_PATH.write_text(json.dumps({"proxies": []}))
    for aid in ("accMoved", "accStays"):
        for k in (LISTS, MEDIA):
            await vault_cache.put(aid, k, PAYLOAD)
    assert await _hit("accMoved", MEDIA) and await _hit("accStays", MEDIA)
    proxy_registry.upsert({"label": "px1", "scheme": "http", "host": "10.0.0.1", "port": 8080})
    proxy_registry.assign_account("px1", "accMoved")       # egress changes → hook fires
    assert not await _hit("accMoved", MEDIA), "cached signed urls survived a proxy change"
    assert not await _hit("accMoved", LISTS)
    assert await _hit("accStays", MEDIA), "an unrelated account lost its cache"
    await vault_cache.put("accMoved", MEDIA, PAYLOAD)      # re-warmed through the new IP
    assert await _hit("accMoved", MEDIA), "a fresh put after the switch must serve"


def case_user_lane_records_activity_background_does_not():
    of_pacing._last_user.pop("accLane", None)
    with server._priority_lane_background("accLane"):
        pass
    assert relay_host.last_user_activity_at("accLane") is None, "background lane counted as a user"
    with server._priority_lane("accLane", priority="user"):   # server job, no request
        pass
    assert relay_host.last_user_activity_at("accLane") is None, "requestless job counted as a user"
    token = server._request_ctx.set(object())                  # a real request in flight
    try:
        with server._priority_lane("accLane", priority="user"):
            pass
    finally:
        server._request_ctx.reset(token)
    assert relay_host.last_user_activity_at("accLane") is not None


_harness.run()
