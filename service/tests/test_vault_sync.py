"""POST /admin/vault-ai/sync — Vault Pro's Refresh reads OnlyFans, not a cache.

REGRESSION (report 2026-11-05): a folder made on OnlyFans and new media never showed after
Refresh. The button only re-ran React Query reads: `/api/of/v2/vault/lists` answered from the relay's day-long
`vault_cache`, and a collected account's grid reads the local mirror, which only a full Collect fills.

Cases:
  case_drops_the_listing_cache       — the relay's cached vault/lists + media rows are gone after a sync.
  case_no_mirror_reads_no_of         — an account the grid reads live: cache dropped, OF untouched.
  case_new_media_lands_newest_first  — the walk stops at the first page with nothing new.
  case_folder_is_read_whole          — a folder view reads every page (membership of OLD media updates).
  case_page_cap                      — never more than _SYNC_MAX_PAGES OF reads.
  case_concurrent_presses_share_one_walk — two Refreshes of one Creator at once: one OF walk, both answered.
  case_of_failure_is_502_and_clears  — OF raising: 502, and the coalescer holds no in-flight walk after it.
  case_operator_fields_survive       — tags / notes / prices / locks survive a sync; a soft-deleted media OF
                                       still lists comes back (`removed_at` lifted).

Run: ./venv/bin/python service/tests/test_vault_sync.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from datetime import datetime  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

import automation_executor as ax  # noqa: E402
import relay_coalesce  # noqa: E402
import vault_ai_api as api  # noqa: E402
import vault_cache  # noqa: E402
import vault_mirror  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultItem  # noqa: E402

AID = "acc_vault_sync"
FOLDER = 4242


def _media(mid: int, folders=()) -> dict:
    return {"id": mid, "type": "photo", "createdAt": "2026-11-05T10:00:00+00:00",
            "files": {"thumb": {"url": f"https://cdn2.onlyfans.com/t/{mid}.jpg"}},
            "listStates": [{"id": f, "type": "custom", "name": f"f{f}", "hasMedia": True} for f in folders]}


class _FakeOF:
    def __init__(self, items: list[dict]):
        self.items = items  # newest first, as OF answers sort=desc
        self.calls: list[tuple] = []
        self.delay_s = 0.0
        self.boom = False

    def vault_media(self, *, limit=24, offset=0, type="all", sort="desc", list_id=None, **_kw):  # noqa: A002
        self.calls.append((offset, list_id, sort))
        if self.delay_s:
            time.sleep(self.delay_s)  # a worker thread, as of_client's blocking read
        if self.boom:
            raise RuntimeError("OF unreachable")
        rows = [m for m in self.items if list_id is None
                or any(ls["id"] == list_id for ls in m.get("listStates", []))]
        return {"list": rows[offset:offset + limit], "hasMore": offset + limit < len(rows)}


async def _reset(mirror_ids=()) -> None:
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID))
        await s.execute(delete(VaultItem).where(VaultItem.account_id == AID))
        for mid in mirror_ids:
            await s.execute(vault_mirror.upsert_stmt(vault_mirror.row_values(AID, _media(mid))))
        await s.commit()
    await vault_cache.invalidate(AID)


async def _ids() -> list[int]:
    async with get_session() as s:
        return sorted((await s.execute(select(VaultItem.media_id).where(
            VaultItem.account_id == AID))).scalars().all())


def _use(of: _FakeOF) -> None:
    api.assert_account_owned = lambda _aid: None
    ax._make_client = lambda _aid, *a, **k: of  # type: ignore[assignment]


async def case_drops_the_listing_cache():
    await _reset(mirror_ids=[1])
    _use(_FakeOF([_media(1)]))
    await vault_cache.put(AID, "lists:view=main|limit=50|offset=0", {"list": [], "hasMore": False}, started_at=datetime.utcnow())
    await vault_cache.put(AID, "media:type=all", {"list": [], "hasMore": False}, started_at=datetime.utcnow())
    await api.sync_from_of(account_id=AID, of_folder_id=None)
    assert await vault_cache.get(AID, "lists:view=main|limit=50|offset=0") is None
    assert await vault_cache.get(AID, "media:type=all") is None


async def case_no_mirror_reads_no_of():
    await _reset()
    of = _FakeOF([_media(1)])
    _use(of)
    await vault_cache.put(AID, "lists:view=main|limit=50|offset=0", {"list": [], "hasMore": False}, started_at=datetime.utcnow())
    r = await api.sync_from_of(account_id=AID, of_folder_id=None)
    assert r["mirror"] is False and of.calls == [], (r, of.calls)
    assert await vault_cache.get(AID, "lists:view=main|limit=50|offset=0") is None
    assert await _ids() == []


async def case_new_media_lands_newest_first():
    old = list(range(1, 251))           # 250 mirrored
    await _reset(mirror_ids=old)
    newest = [_media(m) for m in range(400, 250, -1)]  # 150 new on OF, newest first
    of = _FakeOF(newest + [_media(m) for m in reversed(old)])
    _use(of)
    r = await api.sync_from_of(account_id=AID, of_folder_id=None)
    # page 1: 100 new, page 2: 50 new + 50 known, page 3: nothing new -> stop
    assert [c[0] for c in of.calls] == [0, 100, 200], of.calls
    assert all(c[2] == "desc" for c in of.calls), of.calls
    assert r["new"] == 150 and r["pages"] == 3, r
    assert await _ids() == sorted(old + list(range(251, 401)))


async def case_folder_is_read_whole():
    await _reset(mirror_ids=[1, 2, 3])
    # 1..3 are OLD media the creator just moved into a new OF folder.
    of = _FakeOF([_media(m, folders=[FOLDER]) for m in (3, 2, 1)])
    _use(of)
    r = await api.sync_from_of(account_id=AID, of_folder_id=FOLDER)
    assert of.calls == [(0, FOLDER, "desc")], of.calls
    assert r["new"] == 0 and r["seen"] == 3, r
    async with get_session() as s:
        rows = (await s.execute(select(VaultItem.of_folder_ids).where(VaultItem.account_id == AID))).scalars().all()
    assert all(json.loads(x) == [FOLDER] for x in rows), rows


async def case_page_cap():
    await _reset(mirror_ids=[1])
    of = _FakeOF([_media(m) for m in range(5000, 1, -1)])
    _use(of)
    r = await api.sync_from_of(account_id=AID, of_folder_id=None)
    assert len(of.calls) == api._SYNC_MAX_PAGES and r["pages"] == api._SYNC_MAX_PAGES, (of.calls, r)


async def case_concurrent_presses_share_one_walk():
    await _reset(mirror_ids=[1])
    of = _FakeOF([_media(m) for m in (3, 2, 1)])
    of.delay_s = 0.2
    _use(of)
    a, b = await asyncio.gather(api.sync_from_of(account_id=AID, of_folder_id=None),
                                api.sync_from_of(account_id=AID, of_folder_id=None))
    assert of.calls == [(0, None, "desc")], of.calls
    assert a["new"] == b["new"] == 2 and a["mirror"] is True, (a, b)


async def case_of_failure_is_502_and_clears():
    await _reset(mirror_ids=[1])
    of = _FakeOF([_media(1)])
    of.boom = True
    _use(of)
    try:
        await api.sync_from_of(account_id=AID, of_folder_id=None)
    except HTTPException as e:
        assert e.status_code == 502, e
    else:
        raise AssertionError("an OF failure answered 200")
    assert not [k for k in relay_coalesce._inflight if k[0] == "vault_sync"], relay_coalesce._inflight
    of.boom = False  # the next press walks again, nothing stuck
    r = await api.sync_from_of(account_id=AID, of_folder_id=None)
    assert r["pages"] == 1 and len(of.calls) == 2, (r, of.calls)


async def case_operator_fields_survive():
    await _reset(mirror_ids=[1, 2])
    async with get_session() as s:
        one = await s.get(VaultItem, (AID, 1))
        one.tags, one.notes, one.default_price_cents = '["beach"]', "keep me", 1500
        one.locked_fields_json, one.description = '["explicitness_tier"]', "operator text"
        (await s.get(VaultItem, (AID, 2))).removed_at = datetime(2026, 11, 1)
        await s.commit()
    _use(_FakeOF([_media(m, folders=[FOLDER]) for m in (3, 2, 1)]))
    await api.sync_from_of(account_id=AID, of_folder_id=FOLDER)
    async with get_session() as s:
        one, two = await s.get(VaultItem, (AID, 1)), await s.get(VaultItem, (AID, 2))
        got = (one.tags, one.notes, one.default_price_cents, one.locked_fields_json, one.description)
        assert got == ('["beach"]', "keep me", 1500, '["explicitness_tier"]', "operator text"), got
        assert json.loads(one.of_folder_ids) == [FOLDER], one.of_folder_ids
        assert two.removed_at is None, two.removed_at


_harness.run()
