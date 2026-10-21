#!/usr/bin/env python3
"""
vault_cache is an optimisation, not a dependency.

On 2026-08-22 the VPS lost ~90% of its CPU to hypervisor steal. SQLite
writers stopped finishing inside `busy_timeout`, and `vault_cache.put`'s
unguarded INSERT turned `database is locked` into a **500 on a request whose
upstream OF fetch had already succeeded** — the picker died holding good
data it simply could not memoise:

    INSERT INTO vault_response_cache ... -> OperationalError: database is locked
    url: /api/of/v2/vault/lists?view=main&limit=50&offset=50

These cases pin the degradation contract: a failed read is a MISS, a failed
write is a NO-OP, a failed invalidate does not raise — and, because a
swallowed invalidate would otherwise let the picker serve pre-upload
listings for a full TTL, the rows it failed to delete stop being served.

Plain-assert standalone script (no pytest), run via:

    ./venv/bin/python service/tests/test_vault_cache_degrades.py

Exit 0 = all pass.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# ── Hard-bind a throwaway DB BEFORE importing any service module (same
# PROD-fallback guard as the other service tests).
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
    """The watermark store, or None on a build that predates it. Fetched
    defensively so this file fails on the BEHAVIOUR below rather than dying
    with an AttributeError before a single case runs — a RED proof that
    aborts at setup proves nothing."""
    return getattr(vault_cache, "_pending_invalidations", None)


def _expect(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


class _LockedSession:
    """Stands in for `get_session()` on a box whose SQLite writer cannot get
    the lock. Raises the exact exception SQLAlchemy surfaces for
    `sqlite3.OperationalError: database is locked`."""

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
    """Swap vault_cache's session factory for one that always fails."""
    real = vault_cache.get_session
    vault_cache.get_session = lambda: _LockedSession(calls)
    return real


async def _seed_account() -> None:
    async with get_session() as s:
        s.add(Account(id=_AID, nickname="degrade", color="#aaaaaa"))
        await s.commit()


async def _row_count(query_key: str | None = None) -> int:
    """Cached rows for the account, or for ONE key when given. Cases share a
    DB and do not clear it between runs, so a whole-account count would carry
    the previous case's rows — scope to the key when that matters."""
    from sqlalchemy import func, select
    async with get_session() as s:
        stmt = (select(func.count()).select_from(VaultResponseCache)
                .where(VaultResponseCache.account_id == _AID))
        if query_key is not None:
            stmt = stmt.where(VaultResponseCache.query_key == query_key)
        return (await s.execute(stmt)).scalar_one()


# ── Cases ───────────────────────────────────────────────────────────────

async def case_happy_path_still_caches() -> None:
    """The guard must not cost us the cache itself."""
    await vault_cache.put(_AID, _KEY, _PAYLOAD)
    got = await vault_cache.get(_AID, _KEY)
    _expect("happy path: put -> get round-trips the payload",
            got == _PAYLOAD, detail=f"got {got!r}")


async def case_empty_listings_are_never_cached() -> None:
    """An empty listing must NOT be memoised.

    Regression for a 24h outage: on 2026-08-31 the Fansly vault reads were
    still returning nothing, three `{"list": []}` rows landed in this cache,
    and the picker then served them for a full TTL to a browser whose vault
    was by that point completely healthy — folders and media both blank while
    the shim, the endpoints and the session were all provably fine. Caching
    "nothing" saves the cheapest possible fetch and buys a silent, TTL-long,
    self-healing lie in exchange."""
    empty = {"list": [], "hasMore": False}
    await vault_cache.put(_AID, "empty-listing", empty)
    _expect("empty listing: not served from cache",
            await vault_cache.get(_AID, "empty-listing") is None)
    _expect("empty listing: no row was written at all",
            await _row_count("empty-listing") == 0,
            detail=f"{await _row_count('empty-listing')} row(s) present")

    # ...and it must not shadow a GOOD row already cached under that key.
    await vault_cache.put(_AID, _KEY, _PAYLOAD)
    await vault_cache.put(_AID, _KEY, empty)
    _expect("empty listing: does not overwrite a healthy cached row",
            await vault_cache.get(_AID, _KEY) == _PAYLOAD)


async def case_empty_detection_is_conservative() -> None:
    """Only recognised, actually-empty listing shapes count as empty.

    If this over-matched it would quietly disable caching for payload shapes
    it merely failed to understand — trading a visible outage for an
    invisible performance cliff."""
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
    """The 500 we actually shipped. `put` is the LAST statement before the
    endpoint returns OF data that is already in hand."""
    calls: list[str] = []
    real = _lock_the_db(calls)
    try:
        raised = None
        try:
            await vault_cache.put(_AID, "key-while-locked", _PAYLOAD)
        except Exception as e:  # noqa: BLE001 - that is the bug under test
            raised = e
    finally:
        vault_cache.get_session = real
    _expect("put: a locked DB does not raise",
            raised is None, detail=f"raised {raised!r}")
    _expect("put: it really did attempt the write (guard is not vacuous)",
            calls == ["open"], detail=f"session calls {calls!r}")


async def case_get_reports_a_miss_on_locked_db() -> None:
    """A failed read must send the caller upstream, not 500 them."""
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
    """`invalidate` runs AFTER the mutation succeeded upstream — raising here
    reports failure for completed work and invites a re-upload (duplicate
    vault media)."""
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
    """The correctness hole that swallowing would otherwise open: the creator
    uploads, the DELETE fails, and the picker keeps serving the pre-upload
    listing for a full TTL. The surviving row must read as a miss."""
    await vault_cache.put(_AID, _KEY, _PAYLOAD)
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

    # A fresh upstream result must still re-warm the cache — the account is
    # not poisoned, only the rows the invalidate meant to kill.
    fresh = {"list": [{"id": 7}, {"id": 8, "name": "just uploaded"}], "hasMore": False}
    await vault_cache.put(_AID, _KEY, fresh)
    _expect("stale guard: a fresh put re-warms the account",
            await vault_cache.get(_AID, _KEY) == fresh,
            detail=f"got {await vault_cache.get(_AID, _KEY)!r}")


async def case_successful_invalidate_clears_the_pending_mark() -> None:
    """Once the rows are actually gone the watermark has nothing left to
    suppress — leaving it set would keep raising the bar forever."""
    store = _pending()
    _expect("vault_cache exposes a pending-invalidation store", store is not None)
    if store is None:
        return
    store[_AID] = datetime.utcnow() + timedelta(hours=1)
    await vault_cache.invalidate(_AID)
    _expect("pending mark cleared by a successful invalidate",
            _AID not in store, detail=f"still {store!r}")
    await vault_cache.put(_AID, _KEY, _PAYLOAD)
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
        case_successful_invalidate_clears_the_pending_mark,
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
