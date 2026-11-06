"""The vault mirror as the background collector leaves it (service/vault_collect.py: vault_items upserted from
OF's media dicts, one `auto:done` vault_cache_runs row), by SQL, from lib/vault_wire.py's vaults, so a scenario
can start from a collected vault without waiting for the walk. Rows in vault_mirror.row_values' shape.

`set_urls` rewrites stored urls the way the product does when it sees a media again (raw_json + the columns
derived from it, together): `exp` in the past = OF's signature expired; a bumped `gen` = OF re-signed; `egress`
= signed for that egress (an earlier proxy's listing; wire `ip_bound`).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from . import World, ts


def _row(aid: str, m: dict, now: str) -> tuple:
    folders = [ls["id"] for ls in m.get("listStates") or []  # vault_mirror.row_values' rule
               if ls.get("type") == "custom" and ls.get("hasMedia") and ls.get("id")]
    created = datetime.strptime(m["createdAt"], "%Y-%m-%dT%H:%M:%S+00:00")
    return (aid, m["id"], m["type"], m.get("duration"), None, None, m["files"]["thumb"]["url"],
            m["files"]["full"]["url"], json.dumps(m), ts(created), now, json.dumps(folders), m["type"], "[]", 0)


def mirror(w: World, wire, uids: list[str], *, phase: str = "auto:done") -> dict[str, int]:
    now = ts(w.now)
    out = {}
    con = w.sql()
    with con:
        for aid in uids:
            ms = [wire.of_media(aid, m) for m in wire.vault(aid)["media"]]
            con.executemany(
                "INSERT INTO vault_items(account_id, media_id, kind, duration_seconds, width, height, thumb_url, "
                "full_url, raw_json, created_at, updated_at, of_folder_ids, search_text, tags, send_count) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [_row(aid, m, now) for m in ms])
            con.execute("INSERT INTO vault_cache_runs(account_id, status, phase, total_seen, upserted, pages_done, "
                        "started_at, finished_at) VALUES (?,?,?,?,?,?,?,?)",
                        (aid, "done", phase, len(ms), len(ms), -(-len(ms) // 100), now, now))
            out[aid] = len(ms)
    con.close()
    return out


def set_urls(w: World, wire, aid: str, mids: list[int], *, exp: int | None = None, gen: int | None = None,
             egress: str | None = None) -> int:
    by_id = wire.vault(aid)["by_id"]
    rows = []
    for mid in mids:
        m = wire.of_media(aid, by_id[mid], exp=exp, gen=gen, egress=egress)
        rows.append((m["files"]["thumb"]["url"], m["files"]["full"]["url"], json.dumps(m), aid, mid))
    con = w.sql()
    with con:
        con.executemany("UPDATE vault_items SET thumb_url=?, full_url=?, raw_json=? WHERE account_id=? AND media_id=?",
                        rows)
    con.close()
    return len(rows)


def expired_exp() -> int:
    return int(time.time()) - 7200


def utc_epoch(s: str | None) -> float | None:
    """A vault_cache_runs timestamp (naive UTC, seed ts or SQLAlchemy's) as epoch seconds."""
    if not s:
        return None
    return datetime.fromisoformat(str(s)).replace(tzinfo=timezone.utc).timestamp()
