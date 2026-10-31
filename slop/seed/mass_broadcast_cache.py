"""The Mass messages tab's cached broadcasts (scenarios/2026-10-29-state-reducers.py, section 1c): per
Creator, `copies` x each of KINDS as `mass_broadcast_cache` rows, the way `mass_broadcast_cache.upsert_many`
writes OF's feed items, fetched now (newer than every `mass_runs` row, so the tab's read never calls OF).

  KINDS   (kind, hours ago, free, media count, giphy id, unsent, OF can still unsend): free text, GIF-only,
          image, paid text, paid image (5-9 h old); fresh free text (1 h, and 3 h: under the 4 h gate with an
          hour's margin for a slow run); an already unsent one; one OF says can no longer be unsent.

Queue ids are ID_BASE + Creator index * 100_000 + copy * 100 + kind index (below lib/of_wire.py's own
ids). Each copy is `copy` seconds older than the first. Deterministic: no randomness, only `now`.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import World, ts

KINDS = (
    ("free text", 5, True, 0, None, False, True),
    ("free gif", 6, True, 0, "slopgif", False, True),
    ("free image", 7, True, 2, None, False, True),
    ("paid text", 8, False, 0, None, False, True),
    ("paid image", 9, False, 1, None, False, True),
    ("free text fresh", 1, True, 0, None, False, True),
    ("free text 3h", 3, True, 0, None, False, True),
    ("free text unsent", 6, True, 0, None, True, False),
    ("free text OF no", 6, True, 0, None, False, False),
)
ID_BASE = 7_700_000_000


def seed(w: World, creators: list[str], copies: int) -> dict[tuple[str, int], dict]:
    """Writes the rows; returns them by (Creator, queue id): kind, hours, free, media, gif, canceled, can_unsend."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows: dict[tuple[str, int], dict] = {}
    con = w.sql()
    with con:
        for ci, aid in enumerate(creators):
            for k in range(copies):
                for ki, (kind, hours, free, media, gif, canceled, can) in enumerate(KINDS):
                    qid = ID_BASE + ci * 100_000 + k * 100 + ki
                    rows[(aid, qid)] = {"kind": kind, "hours": hours, "free": free, "media": media, "gif": gif,
                                        "canceled": canceled, "can_unsend": can}
                    con.execute(
                        "INSERT INTO mass_broadcast_cache (account_id, queue_id, sent_at, body_text, raw_text,"
                        " giphy_id, is_free, is_tip, media_count, media_json, previews_json, sent_count,"
                        " viewed_count, is_canceled, can_unsend, unsend_seconds, template, fetched_at)"
                        " VALUES (?,?,?,?,?,?,?,0,?,?,'[]',?,?,?,?,?,NULL,?)",
                        (aid, qid, ts(now - timedelta(hours=hours, seconds=k)), f"slop {kind} {ci}.{k}",
                         f"<p>slop {kind} {ci}.{k}</p>", gif, int(free), media,
                         json.dumps([{"id": qid * 10 + j, "type": "photo", "files": {}} for j in range(media)]),
                         40 + k, 10 + k, int(canceled), int(can), 0 if canceled else 1_000_000, ts(now)))
    con.close()
    return rows
