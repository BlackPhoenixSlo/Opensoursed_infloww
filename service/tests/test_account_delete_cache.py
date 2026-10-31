#!/usr/bin/env python3
"""
DELETE /admin/accounts/{id} — server-side cache eviction.

Dropping a model used to only stop its WS pump + drop its pooled OFClient;
the relay_cache (RAM, hot-path OF responses) and vault_cache (SQLite, vault
listings) both kept serving the dropped account's data until TTL — so a
re-added account (same account_id) could read the prior session's chats /
vault, and a manual logout was needed to clear it.

`admin_accounts_remove` now also calls `relay_cache.invalidate_account` +
`vault_cache.invalidate`, both strictly scoped to that one account_id. These
cases assert the endpoint fires BOTH on a real delete, fires neither on a
404 (unknown account), and that a cache failure can't fail the delete.

Plain-assert standalone script (no pytest), run via:

    ./venv/bin/python service/tests/test_account_delete_cache.py

Exit 0 = all pass.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

# ── Hard-bind a throwaway DB BEFORE importing any service module (same
# PROD-fallback guard as the other service tests).
_TMP_DB = Path(tempfile.gettempdir()) / f"chatterly_acctdel_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["CHATTERLY_DB_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["SHARE_TOKEN"] = ""
os.environ.setdefault("SESSION_SECRET", "test-session-secret-do-not-use-in-prod")
os.environ.setdefault("CHATTER_SESSION_SECRET", "test-chatter-secret-do-not-use-in-prod")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

HERE = Path(__file__).resolve().parent
SERVICE_ROOT = HERE.parent
sys.path.insert(0, str(SERVICE_ROOT))

from db.engine import init_db  # noqa: E402

asyncio.run(init_db())

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
import accounts_admin_api  # noqa: E402
import relay_cache  # noqa: E402
import vault_cache  # noqa: E402
import accounts as account_registry  # noqa: E402

_TEST_AID = "acctDelTest"


def _install_recorders(deleted: dict):
    """Patch the endpoint's collaborators so the delete runs in isolation
    (no real filesystem / pump / db-sync) and we can observe the two cache
    invalidations. Returns lists that capture the account_ids passed."""
    relay_calls: list[str] = []
    vault_calls: list[str] = []

    server._stop_account_pump = lambda aid: None
    server._invalidate_client = lambda aid: None
    server._kick_db_sync = lambda reason: None

    # get_account: known only for our test id (so the 404 case has a real
    # "unknown" id to reject).
    def _get_account(aid):
        return {"id": aid, "nickname": aid} if aid == _TEST_AID else None
    account_registry.get_account = _get_account
    # delete_account: pretend the dir existed and was removed.
    account_registry.delete_account = lambda aid: deleted.setdefault(aid, True)

    def _relay_inv(aid):
        relay_calls.append(aid)
        return 0
    relay_cache.invalidate_account = _relay_inv

    async def _vault_inv(aid):
        vault_calls.append(aid)
        return 0
    vault_cache.invalidate = _vault_inv

    return relay_calls, vault_calls


async def main() -> None:
    # ── Case 1: a real delete fires BOTH invalidations, scoped to the id,
    #            and returns ok.
    deleted: dict = {}
    relay_calls, vault_calls = _install_recorders(deleted)

    res = await accounts_admin_api.admin_accounts_remove(_TEST_AID)
    assert res.get("ok") is True, f"case1: endpoint did not report ok: {res}"
    assert relay_calls == [_TEST_AID], f"case1: relay_cache.invalidate_account not called with id: {relay_calls}"
    assert vault_calls == [_TEST_AID], f"case1: vault_cache.invalidate not called with id: {vault_calls}"
    assert deleted.get(_TEST_AID) is True, "case1: account_registry.delete_account not called"

    # ── Case 2: unknown account → 404 and NEITHER cache is touched.
    relay_calls.clear()
    vault_calls.clear()
    raised = False
    try:
        await accounts_admin_api.admin_accounts_remove("not-a-real-account")
    except HTTPException as e:
        raised = True
        assert e.status_code == 404, f"case2: wrong status {e.status_code}"
    assert raised, "case2: expected HTTPException(404) for unknown account"
    assert relay_calls == [], f"case2: relay invalidate fired for unknown account: {relay_calls}"
    assert vault_calls == [], f"case2: vault invalidate fired for unknown account: {vault_calls}"

    # ── Case 3: a cache-invalidation failure must NOT fail the delete
    #            (best-effort cleanup — the account still gets removed).
    deleted.clear()

    def _boom(aid):
        raise RuntimeError("relay cache exploded")
    relay_cache.invalidate_account = _boom

    res = await accounts_admin_api.admin_accounts_remove(_TEST_AID)
    assert res.get("ok") is True, f"case3: a cache failure broke the delete: {res}"
    assert deleted.get(_TEST_AID) is True, "case3: delete_account skipped after cache failure"

    print("[account_delete_cache] all cases passed")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
