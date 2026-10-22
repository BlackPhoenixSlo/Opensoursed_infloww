"""Which vault id is whose, after a carrier post shared by many files.

A carrier (`OFClient.materialize_to_vault`) lists the media it minted in
whatever order OnlyFans chose. `attribute` turns that listing back into one
record per claim, from each file's own bytes — never from where it sits.

The HASH decides: `GET /vault/media/hash` on a claim's S3 ETag + size, the read
`upload_media` dedupes with, names the vault id for those exact bytes. It runs
after the carrier is gone (the vault item outlives it), unpaced.

THE INDEX LAGS THE POST. MEASURED LIVE 2026-10-22 (16 files, carriers of 10
and 3, read the moment every claim was listed): 9 of 13 fresh files missed on
the first lookup; every one hit a minute later under exactly the id its carrier
had listed, and lookups a few seconds later in the same pass already hit. So
misses are re-read every few seconds until they are all placed, until every id
the post listed is placed (anything still missing was never on it — a .webp
OnlyFans dropped — and no wait will find it), or `HASH_WAIT_S`. A re-run with
the re-read: 16 of 16, one 3 s pass per carrier.

Position is NEVER used. It held live — every carrier so far listed its media in
`mediaFiles` order, including one that dropped a claim — but nothing OnlyFans
documents promises it, and the failure it invites is the worst one available:
two files that miss the hash and are listed swapped would each get the other's
id, both marked done, the wrong id pinned to a Drive file's memo and one file's
price and tags written onto the other.

The one gap the hash may leave is closed by ELIMINATION, which assumes no
order: when the post lists exactly n distinct ids and the hash placed n - 1 of
them, all among those listed, the id left over is the claim left over. That is
what lets a long video still transcoding (and so not indexed yet) ride with
images without a wait, and why a one-claim carrier listing one media needs no
lookup at all. Anything less certain is None, and that file fails on its own.
"""
from __future__ import annotations

import logging
import time
from typing import NamedTuple

log = logging.getLogger("of-relay.vault_carrier")

# How long hash misses are re-read while an id the post listed is still
# unplaced. The carrier is already deleted by then, so this costs the import
# time, never a live post. The same bound the carrier poll has.
HASH_WAIT_S = 600
HASH_RETRY_S = 3.0


class Carried(NamedTuple):
    """One claim's share of a carrier. `vault_id` None: nothing could say."""
    vault_id: int | None
    transcoding: bool


def attribute(client, media: list[dict], keys: list[tuple]) -> list[Carried]:
    """One `Carried` per claim, aligned to `keys` — `(dedupe_key, size)` for
    each claim, in the order they were put on the carrier. `media` is the
    carrier's listing, `materialize_to_vault()["media"]`."""
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
    # The hash hit is read later than the listing, so its isReady is the
    # fresher word; the listing's speaks for an id placed without one.
    return [Carried(v, v is not None and (ready[v] is False if v in ready
                                          else v in busy)) for v in ids]


def _lookup(client, key: str, size: int) -> dict:
    try:
        return client.vault_media_lookup_hash(key, size) or {}
    except Exception as e:  # noqa: BLE001 — a miss, not a failure
        log.warning("vault: hash lookup failed: %s", e)
        return {}


def _eliminate(hashed: list, listed: list) -> list:
    """`hashed`, with its single gap filled when the listing leaves exactly
    one id unplaced — see the module docstring. Otherwise unchanged."""
    pool, placed = set(listed), [h for h in hashed if h is not None]
    if (hashed.count(None) == 1 and len(listed) == len(hashed) == len(pool)
            and len(set(placed)) == len(placed) and pool.issuperset(placed)):
        (left,) = pool.difference(placed)
        return [left if h is None else h for h in hashed]
    return list(hashed)
