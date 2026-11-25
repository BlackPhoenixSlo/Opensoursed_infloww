#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / f"chatterly_vcdeg_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["CHATTERLY_DB_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["SHARE_TOKEN"] = ""
os.environ["CHATTERLY_TEST_MODE"] = "1"

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "service"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from sqlalchemy.exc import OperationalError  # noqa: E402

import vault_cache  # noqa: E402
from db.engine import get_session, init_db  # noqa: E402
from db.models import Account, VaultResponseCache  # noqa: E402

_AID = "accVaultDegrade"
_KEY = "lists:view=main|limit=50|offset=50"
_PAYLOAD = {"list": [{"id": 7, "name": "Reels"}], "hasMore": False}

_failures: list[str] = []


def _pending() -> dict | None:
    return getattr(vault_cache, "_invalidated_at", None)


def _expect(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


class _LockedSession:

    def __init__(self, calls: list[str]):
        self._calls = calls

    async def __aenter__(self):
        self._calls.append("open")
        raise OperationalError(
            "INSERT INTO vault_response_cache ...", {},
            Exception("database is locked"),
        )

    async def __aexit__(self, *exc):  # pragma: no cover - never reached
        return False


def _lock_the_db(calls: list[str]):
    real = vault_cache.get_session
    vault_cache.get_session = lambda: _LockedSession(calls)
    return real


async def _seed_account() -> None:
    async with get_session() as s:
        s.add(Account(id=_AID, nickname="degrade", color="#aaaaaa"))
        await s.commit()


async def _row_count(query_key: str | None = None) -> int:
    from sqlalchemy import func, select
    async with get_session() as s:
        stmt = (select(func.count()).select_from(VaultResponseCache)
                .where(VaultResponseCache.account_id == _AID))
        if query_key is not None:
            stmt = stmt.where(VaultResponseCache.query_key == query_key)
        return (await s.execute(stmt)).scalar_one()



async def case_happy_path_still_caches() -> None:
    await vault_cache.put(_AID, _KEY, _PAYLOAD, started_at=datetime.utcnow())
    got = await vault_cache.get(_AID, _KEY)
    _expect("happy path: put -> get round-trips the payload",
            got == _PAYLOAD, detail=f"got {got!r}")


async def case_empty_listings_are_never_cached() -> None:
    empty = {"list": [], "hasMore": False}
    await vault_cache.put(_AID, "empty-listing", empty, started_at=datetime.utcnow())
    _expect("empty listing: not served from cache",
            await vault_cache.get(_AID, "empty-listing") is None)
    _expect("empty listing: no row was written at all",
            await _row_count("empty-listing") == 0,
            detail=f"{await _row_count('empty-listing')} row(s) present")

    await vault_cache.put(_AID, _KEY, _PAYLOAD, started_at=datetime.utcnow())
    await vault_cache.put(_AID, _KEY, empty, started_at=datetime.utcnow())
    _expect("empty listing: does not overwrite a healthy cached row",
            await vault_cache.get(_AID, _KEY) == _PAYLOAD)


async def case_empty_detection_is_conservative() -> None:
    is_empty = getattr(vault_cache, "_is_empty_listing", None)
    _expect("vault_cache exposes _is_empty_listing", is_empty is not None)
    if is_empty is None:
        return
    for payload, want, label in (
        ({"list": [], "hasMore": False}, True, "{'list': []}"),
        ({"items": []}, True, "{'items': []}"),
        ({"data": []}, True, "{'data': []}"),
        ([], True, "a bare empty list"),
        (None, True, "None"),
        ({"list": [{"id": 1}]}, False, "a listing WITH a row"),
        ({"types": ["photo"]}, False, "a non-listing payload"),
        ({"count": 0}, False, "an unrecognised shape (must NOT be called empty)"),
        ({"list": None}, False, "list=None is a shape we don't understand"),
    ):
        _expect(f"empty-detection: {label} -> {want}",
                is_empty(payload) is want, detail=f"got {is_empty(payload)!r}")


async def case_put_never_raises_on_locked_db() -> None:
    calls: list[str] = []
    real = _lock_the_db(calls)
    try:
        raised = None
        try:
            await vault_cache.put(_AID, "key-while-locked", _PAYLOAD, started_at=datetime.utcnow())
        except Exception as e:  # noqa: BLE001 - that is the bug under test
            raised = e
    finally:
        vault_cache.get_session = real
    _expect("put: a locked DB does not raise",
            raised is None, detail=f"raised {raised!r}")
    _expect("put: it really did attempt the write (guard is not vacuous)",
            calls == ["open"], detail=f"session calls {calls!r}")


async def case_get_reports_a_miss_on_locked_db() -> None:
    calls: list[str] = []
    real = _lock_the_db(calls)
    try:
        raised, got = None, "sentinel"
        try:
            got = await vault_cache.get(_AID, _KEY)
        except Exception as e:  # noqa: BLE001
            raised = e
    finally:
        vault_cache.get_session = real
    _expect("get: a locked DB does not raise", raised is None, detail=f"raised {raised!r}")
    _expect("get: a locked DB reads as a miss", got is None, detail=f"got {got!r}")


async def case_invalidate_never_raises_on_locked_db() -> None:
    calls: list[str] = []
    real = _lock_the_db(calls)
    try:
        raised, deleted = None, -1
        try:
            deleted = await vault_cache.invalidate(_AID)
        except Exception as e:  # noqa: BLE001
            raised = e
    finally:
        vault_cache.get_session = real
    _expect("invalidate: a locked DB does not raise", raised is None, detail=f"raised {raised!r}")
    _expect("invalidate: reports 0 rows deleted", deleted == 0, detail=f"got {deleted!r}")


async def case_failed_invalidate_stops_serving_stale_rows() -> None:
    await vault_cache.put(_AID, _KEY, _PAYLOAD, started_at=datetime.utcnow())
    _expect("stale guard: row is served before the failed invalidate",
            await vault_cache.get(_AID, _KEY) == _PAYLOAD)

    real = _lock_the_db([])
    try:
        await vault_cache.invalidate(_AID)
    finally:
        vault_cache.get_session = real

    _expect("stale guard: the row survived the failed DELETE",
            await _row_count() >= 1)
    _expect("stale guard: but it is NO LONGER served",
            await vault_cache.get(_AID, _KEY) is None)

    fresh = {"list": [{"id": 7}, {"id": 8, "name": "just uploaded"}], "hasMore": False}
    await vault_cache.put(_AID, _KEY, fresh, started_at=datetime.utcnow())
    _expect("stale guard: a fresh put re-warms the account",
            await vault_cache.get(_AID, _KEY) == fresh,
            detail=f"got {await vault_cache.get(_AID, _KEY)!r}")


async def case_successful_invalidate_resets_the_mark() -> None:
    store = _pending()
    _expect("vault_cache exposes an invalidation store", store is not None)
    if store is None:
        return
    store[_AID] = datetime.utcnow() + timedelta(hours=1)
    await vault_cache.invalidate(_AID)
    _expect("mark reset to the invalidate's moment by a successful invalidate",
            store.get(_AID, datetime.min) <= datetime.utcnow(), detail=f"still {store!r}")
    await vault_cache.put(_AID, _KEY, _PAYLOAD, started_at=datetime.utcnow())
    _expect("cache usable again after a successful invalidate",
            await vault_cache.get(_AID, _KEY) == _PAYLOAD)


async def main() -> None:
    await init_db()
    await _seed_account()
    for case in (
        case_happy_path_still_caches,
        case_empty_listings_are_never_cached,
        case_empty_detection_is_conservative,
        case_put_never_raises_on_locked_db,
        case_get_reports_a_miss_on_locked_db,
        case_invalidate_never_raises_on_locked_db,
        case_failed_invalidate_stops_serving_stale_rows,
        case_successful_invalidate_resets_the_mark,
    ):
        store = _pending()
        if store is not None:
            store.clear()
        try:
            await case()
        except Exception as e:  # noqa: BLE001
            _expect(f"{case.__name__} completed without raising", False,
                    detail=f"{type(e).__name__}: {e}")
    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        sys.exit(1)
    print("all cases passed")


asyncio.run(main())
