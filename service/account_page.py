from __future__ import annotations

import asyncio
import logging
import time

from of_coerce import cents_or_none

log = logging.getLogger("of-relay.account-page")

PAID_PAGE_SKIP = "paid_page"

_TTL_KNOWN_S = 6 * 3600
_TTL_UNKNOWN_S = 300

_cache: dict[str, tuple[float, int | None]] = {}
_locks: dict[str, asyncio.Lock] = {}


def _store(account_id: str, cents: int | None) -> int | None:
    ttl = _TTL_KNOWN_S if cents is not None else _TTL_UNKNOWN_S
    _cache[str(account_id)] = (time.monotonic() + ttl, cents)
    return cents


def _price_cents(profile: object) -> int | None:
    if not isinstance(profile, dict):
        return None
    raw = profile.get("subscribePrice")
    if isinstance(raw, bool):
        return None
    return cents_or_none(raw)


def prime(account_id: str, profile: object) -> None:
    cents = _price_cents(profile)
    if cents is not None:
        _store(account_id, cents)


def invalidate(account_id: str) -> None:
    _cache.pop(str(account_id), None)


# `subscribePrice` on /users/me is the only paid-page flag; `paidFeed` disagrees across paid pages.
async def subscribe_price_cents(account_id: str) -> int | None:
    key = str(account_id)
    hit = _cache.get(key)
    now = time.monotonic()
    if hit is not None and hit[0] > now:
        return hit[1]

    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] > time.monotonic():
            return hit[1]
        try:
            import automation_executor as ax

            client = await asyncio.to_thread(ax._make_client, key)
            profile = await asyncio.to_thread(client.me)
        except Exception:
            log.debug("account_page: /users/me probe failed account=%s", key,
                      exc_info=True)
            return _store(key, None)
        cents = _price_cents(profile)
        if cents is None:
            log.warning("account_page: /users/me for account=%s carried no "
                        "subscribePrice — page tier unknown", key)
        return _store(key, cents)


# Unknown reads False: failing closed would silently stop a free page selling on its wall.
async def is_paid_page(account_id: str) -> bool:
    cents = await subscribe_price_cents(account_id)
    return bool(cents and cents > 0)
