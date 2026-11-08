"""Vault Refresh's world (scenarios/2026-11-05-vault-refresh.py): what the relay already holds of each Creator's
OnlyFans vault (lib/vault_wire.py serves the vault itself), by SQL, as the product leaves it:

  mirror Creators   the mirror as a finished collector walk leaves it (seed/vault_week.mirror: vault_items for every
                    OF media + one `auto:done` run) and the relay's cached folder list (`vault_response_cache`,
                    LISTS_KEY, fetched 2 h ago: inside the day-long TTL, so without a Refresh the rail stays stale).
  live Creators     no mirror; the relay's cached page 1 of the picker's listing (PICKER_KEY, fetched 2 h ago) whose
                    thumb urls expired 1 h ago, as OF signed them when that page was fetched.

PICKER_KEY / LISTS_KEY are vault_cache.vault_media_cache_key / vault_lists_cache_key's output for those reads, copied: the
scenario asserts both (THUMBS_RELOAD: the relay re-cached PICKER_KEY; REFRESH_WIRE: LISTS_KEY), so a format change
there turns its check red instead of stranding a stale row.

`seed(w, wire, mirror, live)` writes those rows and gives every vault call LATENCY_S (of_wire's `extra_s`).
"""
from __future__ import annotations

import json
import time
from datetime import timedelta

from . import World, ts, vault_week

LATENCY_S = 0.15     # each OF vault call (a guess at OF through a proxy): of_wire's own wait + `extra_s`
PICKER_PAGE = 24     # app/hooks/useVaultMedia.ts PAGE
PICKER_KEY = "media:type=all|list=None|offset=0|limit=24|sort=desc|field=recent|query="   # vault_cache.vault_media_cache_key
LISTS_KEY = "lists:view=main|limit=50|offset=0"                                           # vault_cache.vault_lists_cache_key


def seed(w: World, wire, mirror: list[str], live: list[str]) -> None:
    fake = wire.fake
    with fake.lock:
        for aid in (*mirror, *live):
            fake.extra_s[aid] = max(0.0, LATENCY_S - fake.latency_s)
    vault_week.mirror(w, wire, mirror)
    fetched = w.now - timedelta(hours=2)
    expired = int(time.time()) - 3600
    con = w.sql()
    with con:
        for aid in mirror:
            fs = wire.vault(aid)["folders"]
            _cache_row(con, aid, LISTS_KEY, {"list": fs, "hasMore": False}, fetched)
        for aid in live:
            ms = wire.listing(aid)
            body = {"list": [wire.of_media(aid, m, exp=expired) for m in ms[:PICKER_PAGE]],
                    "hasMore": len(ms) > PICKER_PAGE}
            _cache_row(con, aid, PICKER_KEY, body, fetched)
    con.close()


def _cache_row(con, aid, key, body, at) -> None:
    con.execute("INSERT INTO vault_response_cache(account_id, query_key, response_json, fetched_at) VALUES (?,?,?,?)",
                (aid, key, json.dumps(body), ts(at)))
