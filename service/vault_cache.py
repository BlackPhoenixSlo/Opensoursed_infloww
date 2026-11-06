"""
vault_cache.py — shared TTL cache for OF vault listing responses.

Every employee on the same OF account sees the same vault, so caching
the OF response keyed on (account_id, query_key) lets the second
picker-open (from any browser) skip the OF round-trip entirely.

API:
    await get(account_id, query_key)           -> dict | None  (None = miss/stale)
    await put(account_id, query_key, payload)  -> None         (write-through)
    await invalidate(account_id)               -> int          (rows deleted)

TTL is per key prefix. Folder lists (`lists:`) keep for
`CHATTERLY_VAULT_CACHE_TTL_SECONDS` (default 604800 = 7 days); every other
key (media pages, media-by-id) for min(that, 72000 = 20 h), because those
payloads carry OF's signed urls and a cache older than ~20 h hands out links
that 403. A proxy change also stales the account's rows (`mark_stale`): the
signed urls are bound to the egress IP. Vault content changes are creator-driven and all mutation
paths (/api/of/v2/upload, vault list/folder edits) call
`invalidate(account_id)` so the cache cannot serve a stale row after a
write the relay performed. External edits (e.g. the creator deleting
media in OF's own UI) age out via the TTL — worst case the picker
shows a ghost row for up to 1 day until either an upload invalidates
or the user hits Refresh.

This cache is an OPTIMISATION, never a dependency
----------------------------------------------------
Every entry point here degrades instead of raising. That is not defensive
habit, it is a bug we shipped: on 2026-08-22 the box lost ~90% of its CPU
to hypervisor steal, SQLite writers could not finish inside `busy_timeout`,
and `put`'s unguarded INSERT turned `database is locked` into a **500 on a
request whose upstream OF fetch had already SUCCEEDED**. We threw away good
data because we could not memoise it. The docstring on `put` already said
"Don't break the upstream response just because we couldn't cache it" — the
guard just never covered the DB write, only the JSON encode.

So: a failed read is a MISS (go upstream), a failed write is a NO-OP, and a
failed invalidate falls back to `_pending_invalidations` below. The caller
gets slower, never broken.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from db.engine import get_session
from db.models import VaultResponseCache

log = logging.getLogger("of-relay.vault_cache")

# Account ids whose `invalidate` could not delete its rows, mapped to the
# moment the invalidation was requested.
#
# Swallowing a failed invalidate is only safe if the rows it meant to kill
# stop being served — otherwise a creator uploads media, the DELETE fails on
# a locked DB, and the picker keeps serving the pre-upload listing for a full
# TTL (a day, by default). That is a worse failure than the 500 we are
# removing, because it is silent.
#
# So when the DELETE fails we record the account here and `get` treats every
# row stamped at or before that moment as stale — the cache degrades to
# "always miss for this account" until a fresh `put` re-warms it, which is
# exactly what a successful invalidate would have produced.
#
# Deliberately RAM-only: it is a repair for a write we could not perform, so
# persisting it would need the very write that just failed. A restart drops
# it, and the row falls back to ordinary TTL expiry.
_pending_invalidations: dict[str, datetime] = {}


LISTS_TTL_DEFAULT_S = 604800   # 7 d — folder lists carry no row-level signed urls worth guarding
MEDIA_TTL_CAP_S = 72000        # 20 h — signed media urls are never served older than this


def vault_media_cache_key(*, type: str = "all", list_id: int | None = None,
                          offset: int = 0, limit: int = 24, sort: str = "desc",
                          field: str = "recent", q_norm: str = "",
                          before: str | None = None) -> str:
    """THE cache key for a /vault/media request — the single place its format
    lives. The route (server.py) and the background collector (vault_collect)
    both build keys here, so a page the collector warms is the page the picker
    reads."""
    # `before` (Go to date) only when set, so every existing key stays as it was.
    return (f"media:type={type}|list={list_id}|offset={offset}|limit={limit}"
            f"|sort={sort}|field={field}|query={q_norm}"
            + (f"|before={before}" if before else ""))


def vault_lists_cache_key(*, view: str = "main", limit: int = 10, offset: int = 0,
                          q_norm: str = "") -> str:
    """THE cache key for a /vault/lists request — same single-home rule.
    The folder search (`q_norm`) only when set, so the plain key is unchanged."""
    return f"lists:view={view}|limit={limit}|offset={offset}" + (f"|query={q_norm}" if q_norm else "")


def _ttl_seconds(query_key: str = "") -> int:
    """TTL for this key. The env sets the lists TTL; anything else (media pages,
    by-id reads: signed urls) is capped at MEDIA_TTL_CAP_S. 0 disables."""
    raw = os.environ.get("CHATTERLY_VAULT_CACHE_TTL_SECONDS", str(LISTS_TTL_DEFAULT_S))
    try:
        v = max(int(raw), 0)
    except ValueError:
        v = LISTS_TTL_DEFAULT_S
    return v if query_key.startswith("lists:") else min(v, MEDIA_TTL_CAP_S)


def mark_stale(account_id: str) -> None:
    """Make every row cached so far for `account_id` read as a miss. Sync and
    DB-free, for the sync proxy-switch hook (server._on_proxy_switched): a proxy
    change re-binds the egress IP, and OF's signed urls are IP-bound. RAM-only
    like `_pending_invalidations`; after a restart the 20 h media cap bounds it."""
    _pending_invalidations[account_id] = datetime.utcnow()


async def get(account_id: str, query_key: str) -> dict[str, Any] | None:
    """Return the cached response for (account_id, query_key) if it is
    within TTL. Returns None on miss or stale row. Stale rows are left in
    place — `put` overwrites them on the next upstream success.

    A DB failure is reported as a miss: the caller then fetches upstream
    and serves real data, which is the whole point of a cache being
    optional."""
    ttl = _ttl_seconds(query_key)
    if ttl == 0:
        return None
    cutoff = datetime.utcnow() - timedelta(seconds=ttl)
    # A failed invalidate (or a `mark_stale`) raises the bar past the TTL, so
    # rows the mutation should have deleted are not served.
    pending = _pending_invalidations.get(account_id)
    if pending is not None and pending > cutoff:
        cutoff = pending
    try:
        async with get_session() as s:
            row = (
                await s.execute(
                    select(VaultResponseCache)
                    .where(
                        VaultResponseCache.account_id == account_id,
                        VaultResponseCache.query_key == query_key,
                        VaultResponseCache.fetched_at >= cutoff,
                    )
                )
            ).scalar_one_or_none()
    except SQLAlchemyError as e:
        # `database is locked`, EMFILE ("unable to open database file"), a
        # closed pool during shutdown — all mean the same thing to a caller:
        # we have nothing for you, go upstream.
        log.warning("vault_cache: read failed for account=%s key=%s (%s) — treating as miss",
                    account_id, query_key, e.__class__.__name__)
        return None
    if row is None:
        return None
    try:
        return json.loads(row.response_json)
    except (ValueError, TypeError):
        # Corrupt blob — treat as miss and let put() overwrite it.
        log.warning("vault_cache: corrupt blob for account=%s key=%s", account_id, query_key)
        return None


def _is_empty_listing(payload: Any) -> bool:
    """True when `payload` carries no rows — the thing `put` refuses to cache.

    Conservative by construction: it returns True only for a payload whose
    row-bearing key is present and empty (or an empty container outright). A
    shape it doesn't recognise is NOT called empty, so an unfamiliar response
    keeps its cache entry rather than silently losing memoisation."""
    if payload is None:
        return True
    if isinstance(payload, (list, tuple)):
        return len(payload) == 0
    if isinstance(payload, dict):
        for key in ("list", "items", "data"):
            if key in payload:
                rows = payload[key]
                return isinstance(rows, (list, tuple, dict)) and len(rows) == 0
    return False


async def put(account_id: str, query_key: str, payload: Any) -> None:
    """Write-through cache. Upserts on the composite PK so re-fetching
    the same page just refreshes `fetched_at`.

    Never raises: the payload this memoises has already been fetched and is
    on its way to the caller.

    EMPTY LISTINGS ARE NOT CACHED. This is not a micro-optimisation, it is a
    bug we shipped: on 2026-08-31 the Fansly vault reads were still returning
    nothing, three `{"list": [], "hasMore": false}` rows landed here, and for
    the next 24h the picker served them to a browser whose vault was by then
    perfectly healthy — folders AND media both blank, with the shim, the
    endpoints and the session all provably fine. A day-long outage caused
    entirely by memoising a transient backend failure.

    Caching "nothing" buys nothing: an empty listing is the cheapest possible
    upstream fetch and the smallest possible payload, so the round-trip we
    skip is the one worth least. Meanwhile it converts ANY upstream hiccup —
    a half-migrated platform, an expired session, a rate-limit, a shim method
    that isn't wired yet — into a silent TTL-long lie that self-heals just
    slowly enough to be impossible to reproduce. A genuinely empty vault
    simply re-asks and gets an honest empty answer.

    Deliberately shape-agnostic: anything with a `list`/`items`/`data` key
    that is empty, or an empty container, counts. Non-listing payloads are
    unaffected."""
    if _is_empty_listing(payload):
        log.debug("vault_cache: refusing to memoise an EMPTY listing "
                  "account=%s key=%s (see put.__doc__)", account_id, query_key)
        return
    try:
        blob = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as e:
        # Don't break the upstream response just because we couldn't cache it.
        log.warning("vault_cache: payload not serializable (%s) — skipping write", e)
        return
    now = datetime.utcnow()
    stmt = sqlite_insert(VaultResponseCache).values(
        account_id=account_id,
        query_key=query_key,
        response_json=blob,
        fetched_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["account_id", "query_key"],
        set_={"response_json": blob, "fetched_at": now},
    )
    try:
        async with get_session() as s:
            await s.execute(stmt)
    except SQLAlchemyError as e:
        # The cache write is the LAST thing between a successful OF fetch and
        # the response. Losing it costs the next reader one round-trip;
        # raising here would cost this reader the data they already have.
        log.warning("vault_cache: write failed for account=%s key=%s (%s) — response unaffected",
                    account_id, query_key, e.__class__.__name__)


async def invalidate(account_id: str) -> int:
    """Drop every cached row for an account. Called after any mutation
    the relay mediates (upload, delete, folder edit) so the next read
    goes upstream and re-warms the cache with fresh data.

    Never raises — the mutation it follows has already happened upstream, so
    a 500 here would report failure for work that succeeded and invite the
    caller to repeat it (a re-run upload means duplicate vault media). If the
    DELETE cannot run, `_pending_invalidations` keeps the surviving rows from
    being served; the return value is the number of rows actually deleted,
    which is 0 in that case."""
    try:
        async with get_session() as s:
            result = await s.execute(
                delete(VaultResponseCache).where(VaultResponseCache.account_id == account_id)
            )
            # The rows are gone, so any earlier failed invalidate for this
            # account is now satisfied — stop holding fresh `put`s hostage.
            _pending_invalidations.pop(account_id, None)
            return result.rowcount or 0
    except SQLAlchemyError as e:
        _pending_invalidations[account_id] = datetime.utcnow()
        log.warning("vault_cache: invalidate failed for account=%s (%s) — "
                    "serving misses for this account until a fresh write lands",
                    account_id, e.__class__.__name__)
        return 0
