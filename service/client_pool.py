"""
The relay's one OFClient pool.

Why this module exists: a client per call was an fd per call. Under a proxy
swap every IP-signed vault url died at once, every tile took the re-sign path,
and the relay hit EMFILE.

So clients are pinned per account. A client's ManagedSession leases a handle
per in-flight request (signed calls at most OFClient.SIGNED_SLOTS) and the
registry sweeps idle ones, so handles follow concurrency, not request count.
An evicted client refuses new signed calls (`close_signed_sessions`).

It lives in its own module rather than in `server.py` or
`automation_executor.py` because both of those need it and importing either
from the other is a cycle. It previously lived in both — `server._clients` for
HTTP routes and nothing at all for the automation lane — which meant an
invalidation had to remember two homes. There is one home now.

Eviction is the price of pinning: a pinned client holds the session cookies,
`x_of_rev` and `x_hash` it was built with, so anything that changes what's on
disk (re-bootstrap, proxy edit, re-capture) must evict. See `evict()`.
"""

from __future__ import annotations

import logging
import threading

import relay_coalesce
from of_client import OFClient

log = logging.getLogger("of-relay.client_pool")

_POOL: dict[str, OFClient] = {}
# Guards the miss branch and `evict()`. 50-odd call sites reach `get()` through
# `asyncio.to_thread`, and `from_account()` does disk I/O — so without this,
# a cold pool under a stampede (exactly the post-proxy-swap case) lets N
# threads each build a client and orphan N-1 of them, unclosed.
_LOCK = threading.Lock()


def get(account_id: str) -> OFClient:
    """The pinned OFClient for `account_id`, built on first use.

    Raises whatever `OFClient.from_account` raises (FileNotFoundError for a
    missing session, ValueError for incomplete signing rules) — callers that
    face a user translate those; the pool has no opinion. A failed build is
    not cached.
    """
    c = _POOL.get(account_id)
    if c is not None:
        return c
    with _LOCK:
        # Re-check: another thread may have built it while we waited.
        c = _POOL.get(account_id)
        if c is None:
            c = _POOL[account_id] = OFClient.from_account(account_id)
            log.info("OFClient ready (account=%s user_id=%s rev=%s)",
                     account_id, c.user_id, c.x_of_rev)
    return c


def evict(account_id: str | None = None, *, only: OFClient | None = None) -> None:
    """Drop pooled client(s) so the next `get()` re-reads session + proxy from
    disk. `None` evicts every account — a proxy edit can affect any of them.

    `only` (with an `account_id`): evict only while the pool still holds that
    exact client. A call that failed on a client someone already replaced must
    not drop, and retire, the fresh one other calls are on.

    Explicitly `is None` and not a truthiness test: the failure mode of a
    falsy-but-not-None argument slipping through is silently dumping every
    account's client, which is the worst possible reading of a typo.
    """
    # Under _LOCK: a build that read the OLD proxy before a registry write
    # would otherwise land in the pool after this pop and pin the old route.
    with _LOCK:
        if account_id is None:
            retired = list(_POOL.values())
            _POOL.clear()
        elif only is not None and _POOL.get(account_id) is not only:
            return
        else:
            old = _POOL.pop(account_id, None)
            retired = [old] if old is not None else []
    relay_coalesce.forget(account_id)   # no caller joins a flight on the evicted client
    for client in retired:
        client.close_signed_sessions()
    # Fansly accounts are pooled in fansly_backend, not here (their client is
    # the shim, not an OFClient). Invalidation still has ONE home — this
    # function — so a re-capture or proxy edit can't leave a stale shim behind
    # for the lane that happens to call the other module. Imported lazily and
    # guarded: a deployment without the sibling `fansly/` package has no Fansly
    # pool to drop, and eviction must not fail because of it.
    try:
        import fansly_backend
    except Exception:
        return
    fansly_backend.drop(account_id)
