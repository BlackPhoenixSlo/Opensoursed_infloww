#!/usr/bin/env python3
"""
Deleting a proxy a Creator uses (DELETE /admin/proxies/{label}): Infloww's
"Proxy already in use". The proxy and account registries are repointed at
temp files; no network.

  case_unbound_proxy_deletes:
      a proxy no account is bound to is removed, as before.
  case_bound_proxy_is_409_naming_creators:
      a proxy bound to a live account is refused 409, its detail a message
      naming the Creators that use it, and stays in the registry.
  case_deleted_account_binding_does_not_count:
      a binding left by an account that no longer exists does not block.
  case_signed_in_user_counts_only_own_creators:
      a signed-in owner's 409 names only their own Creators; a binding to one
      they cannot see does not block, and is removed with the proxy.

Run: ./venv/bin/python service/tests/test_proxy_in_use.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import contextvars  # noqa: E402
import json  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import accounts as account_registry  # noqa: E402
import auth  # noqa: E402
import proxies as proxy_registry  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="proxy_in_use_test_"))
proxy_registry.REGISTRY_PATH = _TMP / "proxies.json"
account_registry.ACCOUNTS_DIR = _TMP / "accounts"

import server as _srv  # noqa: E402
import proxies_admin_api  # noqa: E402

_srv._invalidate_client = lambda aid=None: None
_srv._kick_db_sync = lambda reason: None


class _U:
    def __init__(self, uid, account_ids):
        self.id = uid
        self.account_ids = account_ids


def as_user(user, fn, *a):
    def run():
        tok = auth._request_user.set(user)
        try:
            return fn(*a)
        finally:
            auth._request_user.reset(tok)
    return contextvars.copy_context().run(run)


def _reset(owner=None) -> None:
    proxy_registry.REGISTRY_PATH.write_text(json.dumps({"proxies": []}))
    proxy_registry.upsert({"label": "hu-1", "host": "p.invalid", "port": 8080, "user_id": owner})


def _refused(user, label) -> HTTPException:
    try:
        as_user(user, proxies_admin_api.admin_proxies_remove, label)
    except HTTPException as e:
        return e
    raise AssertionError("delete of an in-use proxy must be refused")


def case_unbound_proxy_deletes() -> None:
    _reset()
    assert as_user(None, proxies_admin_api.admin_proxies_remove, "hu-1") == {"ok": True}
    assert proxy_registry.get_by_label("hu-1") is None


def case_bound_proxy_is_409_naming_creators() -> None:
    _reset()
    account_registry.upsert_account("acct1", nickname="Jade")
    proxy_registry.assign_account("hu-1", "acct1")
    e = _refused(None, "hu-1")
    assert e.status_code == 409, e.status_code
    assert e.detail == "Proxy already in use by Jade. Unbind it first.", e.detail
    assert proxy_registry.get_by_label("hu-1") is not None, "a refused delete must keep the proxy"


def case_deleted_account_binding_does_not_count() -> None:
    _reset()
    account_registry.upsert_account("gone", nickname="Gone")
    proxy_registry.assign_account("hu-1", "gone")
    account_registry.delete_account("gone")
    assert as_user(None, proxies_admin_api.admin_proxies_remove, "hu-1") == {"ok": True}


def case_signed_in_user_counts_only_own_creators() -> None:
    _reset(owner="u1")
    account_registry.upsert_account("mine", nickname="Mine")
    account_registry.upsert_account("theirs", nickname="Theirs")
    proxy_registry.assign_account("hu-1", "mine")
    proxy_registry.assign_account("hu-1", "theirs")
    e = _refused(_U("u1", ["mine"]), "hu-1")
    assert e.status_code == 409
    assert e.detail == "Proxy already in use by Mine. Unbind it first.", e.detail
    # A binding the caller cannot see (GET /admin/proxies hides it) does not block, and goes with the proxy.
    proxy_registry.unbind_account("hu-1", "mine")
    assert as_user(_U("u1", ["mine"]), proxies_admin_api.admin_proxies_remove, "hu-1") == {"ok": True}
    assert proxy_registry.get_by_label("hu-1") is None


_harness.run()
