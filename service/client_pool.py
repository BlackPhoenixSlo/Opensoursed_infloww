from __future__ import annotations

import logging
import threading

import platforms
import relay_coalesce
from of_client import OFClient

log = logging.getLogger("of-relay.client_pool")

_POOL: dict[str, OFClient] = {}
# Guards the miss branch and evict(): from_account() does disk I/O and get() is reached via to_thread, so a cold-pool stampede would build N clients and orphan N-1 unclosed.
_LOCK = threading.Lock()


def get(account_id: str) -> OFClient:
    platforms.require_account(account_id)
    c = _POOL.get(account_id)
    if c is not None:
        return c
    with _LOCK:
        # Re-check: another thread may have built it while we waited. A failed build is not cached.
        c = _POOL.get(account_id)
        if c is None:
            platforms.require_account(account_id)
            c = _POOL[account_id] = OFClient.from_account(account_id)
            log.info("OFClient ready (account=%s user_id=%s rev=%s)",
                     account_id, c.user_id, c.x_of_rev)
    return c


def peek(account_id: str) -> OFClient | None:
    return _POOL.get(account_id)


# `only`: evict only while the pool still holds that exact client, so a failure on an already-replaced client can't retire the fresh one. `is None`, not truthiness: a falsy typo must not dump every account's client.
# Under _LOCK: a build that read the old proxy before a registry write would otherwise land after the pop and pin the old route.
def evict(account_id: str | None = None, *, only: OFClient | None = None) -> bool:
    with _LOCK:
        if account_id is None:
            retired = list(_POOL.values())
            _POOL.clear()
        elif only is not None and _POOL.get(account_id) is not only:
            return _POOL.get(account_id) is None
        else:
            old = _POOL.pop(account_id, None)
            retired = [old] if old is not None else []
    relay_coalesce.forget(account_id)
    for client in retired:
        client.close_signed_sessions()
    for backend in platforms.backends():
        backend.drop(account_id)
    return True
