from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from . import World, ts
from .vault_cache import LISTS_KEY, PICKER_PAGE, cache_row, media_key


def _row(aid: str, m: dict, now: str, run_id: int) -> tuple:
    folders = [ls["id"] for ls in m.get("listStates") or []
               if ls.get("type") == "custom" and ls.get("hasMedia") and ls.get("id")]
    created = datetime.strptime(m["createdAt"], "%Y-%m-%dT%H:%M:%S+00:00")
    dur = m.get("duration")
    files = m.get("files") or {}
    return (aid, int(m["id"]), str(m.get("type") or "photo"),
            int(dur) if isinstance(dur, (int, float)) and dur else None,
            m.get("width") if isinstance(m.get("width"), int) else None,
            m.get("height") if isinstance(m.get("height"), int) else None,
            (files.get("thumb") or {}).get("url"), (files.get("full") or {}).get("url"),
            json.dumps(m, ensure_ascii=False), ts(created), m.get("updatedAt"), now,
            json.dumps(folders), str(m.get("type") or "photo").lower(), "[]", run_id, 0)


def mirror(w: World, wire, uids: list[str], *, phase: str = "auto:done") -> dict[str, int]:
    now = ts(w.now)
    out = {}
    con = w.sql()
    with con:
        for aid in uids:
            ms = [wire.of_media(aid, m) for m in wire.vault(aid)["media"]]
            run_id = con.execute("INSERT INTO vault_cache_runs(account_id, status, phase, total_seen, upserted, pages_done, "
                                 "started_at, finished_at) VALUES (?,?,?,?,?,?,?,?)",
                                 (aid, "done", phase, len(ms), len(ms), -(-len(ms) // 100), now, now)).lastrowid
            con.executemany(
                "INSERT INTO vault_items(account_id, media_id, kind, duration_seconds, width, height, thumb_url, "
                "full_url, raw_json, created_at, updated_at_of, updated_at, of_folder_ids, search_text, tags, "
                "last_seen_run_id, send_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [_row(aid, m, now, run_id) for m in ms])
            out[aid] = len(ms)
    con.close()
    return out


def hot_paused(w: World, wire, uids: list[str], *, at: datetime, exp: int) -> dict[str, int]:
    now = ts(at)
    out = {}
    con = w.sql()
    with con:
        for aid in uids:
            folders = wire.vault(aid)["folders"]
            cache_row(con, aid, LISTS_KEY, {"list": folders, "hasMore": False}, at)
            pages = [(f["id"], 0) for f in folders] + [(None, 0), (None, PICKER_PAGE)]
            rows, upserted = {}, 0
            for list_id, off in pages:
                ms = wire.listing(aid, list_id=list_id)
                body = {"list": [wire.of_media(aid, m, exp=exp) for m in ms[off:off + PICKER_PAGE]],
                        "hasMore": off + PICKER_PAGE < len(ms)}
                cache_row(con, aid, media_key(list_id, off), body, at)
                upserted += len(body["list"])
                for m in body["list"]:
                    rows.setdefault(m["id"], _row(aid, m, now, None))
            con.execute("INSERT INTO vault_cache_runs(account_id, status, phase, total_seen, upserted, pages_done, "
                        "started_at) VALUES (?,?,?,?,?,?,?)", (aid, "running", "auto:all:0", 0, upserted, 0, now))
            con.executemany(
                "INSERT INTO vault_items(account_id, media_id, kind, duration_seconds, width, height, thumb_url, "
                "full_url, raw_json, created_at, updated_at_of, updated_at, of_folder_ids, search_text, tags, "
                "last_seen_run_id, send_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", list(rows.values()))
            out[aid] = len(rows)
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


def import_stub(w: World, account_id: str, media_id: int) -> None:
    con = w.sql()
    with con:
        con.execute("INSERT INTO vault_items (account_id, media_id, kind, tags, send_count, created_at, updated_at)"
                    " VALUES (?, ?, 'photo', '[]', 0, ?, ?)",
                    (account_id, media_id, ts(w.now), ts(w.now)))
    con.close()


def utc_epoch(s: str | None) -> float | None:
    if not s:
        return None
    return datetime.fromisoformat(str(s)).replace(tzinfo=timezone.utc).timestamp()
