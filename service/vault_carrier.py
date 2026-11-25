# The one gap the hash may leave is closed by ELIMINATION (no order assumed): post lists exactly n distinct ids and the hash placed n - 1 of them, so the leftover id is the leftover claim; anything less certain is None.
from __future__ import annotations

import logging
import time
from typing import NamedTuple

log = logging.getLogger("of-relay.vault_carrier")

# The hash index lags the post (measured: 9 of 13 fresh files missed on the first lookup, all hit a minute later), so misses are re-read until placed. Position in the carrier's listing is never used. The carrier is already deleted by then, so this costs import time, never a live post.
HASH_WAIT_S = 600
HASH_RETRY_S = 3.0


class Carried(NamedTuple):
    vault_id: int | None
    transcoding: bool


def attribute(client, media: list[dict], keys: list[tuple]) -> list[Carried]:
    listed = [m["id"] for m in media]
    busy = {m["id"] for m in media if m.get("isReady") is False}
    if len(keys) == 1 and len(listed) == 1:
        return [Carried(listed[0], listed[0] in busy)]
    hashed: list = [None] * len(keys)
    ready: dict = {}
    deadline = time.time() + HASH_WAIT_S
    while True:
        for i, (key, size) in enumerate(keys):
            if hashed[i] is None and key and size:
                hit = _lookup(client, key, size)
                hashed[i] = hit.get("id")
                if hashed[i] is not None and "isReady" in hit:
                    ready[hashed[i]] = hit["isReady"]
        ids = _eliminate(hashed, listed)
        if (None not in ids or not set(listed).difference(hashed)
                or time.time() >= deadline):
            break
        time.sleep(HASH_RETRY_S)
    if None in ids:
        log.warning("vault carrier: %d of %d claims could not be attributed "
                    "(listed %s, hash %s)", ids.count(None), len(keys), listed, hashed)
    # The hash hit is read later than the listing, so its isReady is the fresher word; the listing speaks for an id placed without one.
    return [Carried(v, v is not None and (ready[v] is False if v in ready
                                          else v in busy)) for v in ids]


def _lookup(client, key: str, size: int) -> dict:
    try:
        return client.vault_media_lookup_hash(key, size) or {}
    except Exception as e:  # noqa: BLE001 — a miss, not a failure
        log.warning("vault: hash lookup failed: %s", e)
        return {}


def _eliminate(hashed: list, listed: list) -> list:
    pool, placed = set(listed), [h for h in hashed if h is not None]
    if (hashed.count(None) == 1 and len(listed) == len(hashed) == len(pool)
            and len(set(placed)) == len(placed) and pool.issuperset(placed)):
        (left,) = pool.difference(placed)
        return [left if h is None else h for h in hashed]
    return list(hashed)
