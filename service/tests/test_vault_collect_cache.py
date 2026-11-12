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
- the picker's `revalidate=1` on /vault/lists and /vault/media: an entry
  younger than VAULT_PICKER_REVALIDATE_S (default 300) is served, an older one
  is refetched, put and returned (concurrent ones share one OF read);
  `refresh=1` always fetches; the folder gate runs first; `vault_cache.get`
  without a max age keeps its meaning. A revalidated page 1 whose ids changed
  drops its view's other offsets (`vault_cache.drop_view_pages`), not other
  views' and not page 1's fresh put; unchanged ids keep them.

Run: ./venv/bin/python service/tests/test_vault_collect_cache.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
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
        for a in ("accTTL", "accEnv", "accMoved", "accStays", "accPersist", "accRace", "accRv", "accRvL",
                  "accRvGate", "accRvView"):
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


# ── the picker's revalidate on /vault/lists and /vault/media ──────────────

RV_MEDIA = vault_cache.vault_media_cache_key()               # the picker's All page 1
RV_LISTS = vault_cache.vault_lists_cache_key(limit=50)
OLD = {"list": [{"id": 1}], "hasMore": False}


class _FakeOF:
    """The OF client the routes reach: counts reads, each answers a new id."""

    def __init__(self, hold_s: float = 0.0):
        self.media = self.lists = 0
        self.hold_s = hold_s

    def vault_media(self, **_kw):
        self.media += 1
        time.sleep(self.hold_s)
        return {"list": [{"id": 100 + self.media}], "hasMore": False}

    def vault_lists(self, **_kw):
        self.lists += 1
        return {"list": [{"id": 200 + self.lists, "type": "custom"}], "hasMore": False}


@contextlib.contextmanager
def _routes(aid: str, fake: _FakeOF, allowed=None):
    async def _gate(_aid):
        return allowed

    saved = (server._get_client, server._resolve_account_id, server._allowed_folder_ids_for_chatter)
    server._get_client = lambda *a, **k: fake  # type: ignore[assignment]
    server._resolve_account_id = lambda *a, **k: aid  # type: ignore[assignment]
    server._allowed_folder_ids_for_chatter = _gate  # type: ignore[assignment]
    try:
        yield
    finally:
        server._get_client, server._resolve_account_id, server._allowed_folder_ids_for_chatter = saved


async def _media(**kw):
    return await server.of_vault_media(limit=24, offset=0, type="all", list_id=kw.pop("list_id", None),
                                       sort="desc", field="recent", query=None, before_publish_date=None, **kw)


async def _lists(**kw):
    return await server.of_vault_lists(view="main", limit=50, offset=0, query=None, **kw)


async def case_get_without_max_age_keeps_its_meaning():
    await vault_cache.put("accRv", RV_MEDIA, OLD, started_at=datetime.utcnow())
    await _age("accRv", RV_MEDIA, 3600)
    assert await vault_cache.get("accRv", RV_MEDIA) == OLD, "an hour-old row inside the TTL must serve"
    assert await vault_cache.get("accRv", RV_MEDIA, max_age_s=7200) == OLD
    assert await vault_cache.get("accRv", RV_MEDIA, max_age_s=1800) is None, "older than the max age"


async def case_revalidate_young_entry_served():
    os.environ.pop("VAULT_PICKER_REVALIDATE_S", None)
    fake = _FakeOF()
    for key in (RV_MEDIA, RV_LISTS):
        await vault_cache.put("accRv", key, OLD, started_at=datetime.utcnow())
        await _age("accRv", key, 200)                         # < 300 s
    with _routes("accRv", fake):
        assert await _media(revalidate=True, refresh=False) == OLD
        assert await _lists(revalidate=True, refresh=False) == OLD
    assert (fake.media, fake.lists) == (0, 0), "a young entry went to OF"


async def case_revalidate_old_entry_refetched_put_returned():
    os.environ.pop("VAULT_PICKER_REVALIDATE_S", None)
    fake = _FakeOF()
    for key in (RV_MEDIA, RV_LISTS):
        await vault_cache.put("accRv", key, OLD, started_at=datetime.utcnow())
        await _age("accRv", key, 400)                         # > 300 s, well inside the 20 h TTL
    with _routes("accRv", fake):
        assert await _media(refresh=False) == OLD, "no revalidate: the plain read still serves the cache"
        got = await _media(revalidate=True, refresh=False)
        assert got == {"list": [{"id": 101}], "hasMore": False}, got
        lists = await _lists(revalidate=True, refresh=False)
        assert lists["list"][0]["id"] == 201, lists
        assert await _media(revalidate=True, refresh=False) == got, "the refetched page is now the young entry"
    assert (fake.media, fake.lists) == (1, 1), (fake.media, fake.lists)
    assert await vault_cache.get("accRv", RV_MEDIA, max_age_s=5) == got, "the fresh page was not put"
    assert (await vault_cache.get("accRv", RV_LISTS, max_age_s=5))["list"][0]["id"] == 201


async def case_revalidate_knob_read_at_call_time():
    fake = _FakeOF()
    await vault_cache.put("accRvL", RV_MEDIA, OLD, started_at=datetime.utcnow())
    await _age("accRvL", RV_MEDIA, 120)
    try:
        os.environ["VAULT_PICKER_REVALIDATE_S"] = "60"
        assert server._vault_picker_revalidate_s() == 60
        with _routes("accRvL", fake):
            assert (await _media(revalidate=True, refresh=False))["list"][0]["id"] == 101
        os.environ["VAULT_PICKER_REVALIDATE_S"] = "junk"
        assert server._vault_picker_revalidate_s() == 300
    finally:
        os.environ.pop("VAULT_PICKER_REVALIDATE_S", None)
    assert server._vault_picker_revalidate_s() == 300
    assert fake.media == 1


async def case_refresh_always_fetches():
    fake = _FakeOF()
    for key in (RV_MEDIA, RV_LISTS):
        await vault_cache.put("accRvL", key, OLD, started_at=datetime.utcnow())   # young
    with _routes("accRvL", fake):
        await _media(refresh=True)
        await _media(refresh=True, revalidate=True)
        await _lists(refresh=True)
        await _lists(refresh=True, revalidate=True)
    assert (fake.media, fake.lists) == (2, 2), (fake.media, fake.lists)


async def case_concurrent_revalidates_share_one_of_read():
    """Many chatters opening one Creator's picker at once: one OF read."""
    fake = _FakeOF(hold_s=0.2)
    await vault_cache.put("accRvL", RV_MEDIA, OLD, started_at=datetime.utcnow())
    await _age("accRvL", RV_MEDIA, 900)
    with _routes("accRvL", fake):
        got = await asyncio.gather(*(_media(revalidate=True, refresh=False) for _ in range(5)))
    assert fake.media == 1, f"{fake.media} OF reads for 5 concurrent opens"
    assert all(g == got[0] for g in got) and got[0] != OLD


async def case_revalidate_folder_gate_runs_first():
    fake = _FakeOF()
    await vault_cache.put("accRvGate", RV_MEDIA, OLD, started_at=datetime.utcnow())
    await _age("accRvGate", RV_MEDIA, 900)
    await vault_cache.put("accRvGate", RV_LISTS, {"list": [{"id": 7}, {"id": 8}], "hasMore": False},
                          started_at=datetime.utcnow())
    with _routes("accRvGate", fake, allowed={7}):
        assert await _media(revalidate=True, refresh=False) == {"list": [], "hasMore": False}, "All to a chatter"
        lists = await _lists(revalidate=True, refresh=False)
    assert [f["id"] for f in lists["list"]] == [7], lists
    assert fake.media == 0, "a denied folder read reached OF"


async def case_revalidate_new_ids_drop_the_views_other_offsets():
    os.environ.pop("VAULT_PICKER_REVALIDATE_S", None)
    aid = "accRvView"
    page2 = vault_cache.vault_media_cache_key(offset=24)
    page3 = vault_cache.vault_media_cache_key(offset=48)
    photos2 = vault_cache.vault_media_cache_key(type="photo", offset=24)       # another view
    for key in (RV_MEDIA, page2, page3, photos2, RV_LISTS):
        await vault_cache.put(aid, key, OLD, started_at=datetime.utcnow())
        await _age(aid, key, 400)
    fake = _FakeOF()                                  # answers id 101: page 1 changed
    with _routes(aid, fake):
        got = await _media(revalidate=True, refresh=False)
    assert got["list"][0]["id"] == 101, got
    assert await vault_cache.get(aid, page2) is None and await vault_cache.get(aid, page3) is None, \
        "the view's later offsets were cut from the old listing"
    assert await vault_cache.get(aid, RV_MEDIA, max_age_s=5) == got, "page 1's fresh put must land"
    assert await vault_cache.get(aid, photos2) == OLD, "another view's page was dropped"
    assert await vault_cache.get(aid, RV_LISTS) == OLD, "the folder list was dropped"

    # Same ids again (page 1 now [101], OF answers [101]): the later pages stay.
    await vault_cache.put(aid, page2, OLD, started_at=datetime.utcnow())
    await _age(aid, RV_MEDIA, 400)
    same = _FakeOF()
    same.media = 0
    with _routes(aid, same):
        assert (await _media(revalidate=True, refresh=False))["list"][0]["id"] == 101
    assert await vault_cache.get(aid, page2) == OLD, "unchanged ids dropped a later page"

    # A plain miss and refresh=1 never drop (only the picker's revalidate compares).
    await vault_cache.put(aid, page2, OLD, started_at=datetime.utcnow())
    with _routes(aid, _FakeOF()):
        await _media(refresh=True)
    assert await vault_cache.get(aid, page2) == OLD, "refresh=1 dropped a later page"


_harness.run()
