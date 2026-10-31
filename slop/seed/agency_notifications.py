"""Agency notifications: unread `agency_notifications` rows for the owner, as
`notifications_api.notify` files them (one per Creator, kind `session_dead`, the
sweep's sentence), without its SSE push: a page reads them on its next fetch."""
from __future__ import annotations

from datetime import timedelta

from . import World, ts


def seed(w: World, creators: list[dict]) -> list[int]:
    """One unread row per Creator; returns their ids."""
    con = w.sql()
    with con:
        for i, c in enumerate(creators):
            con.execute(
                "INSERT INTO agency_notifications (agency_user_id, kind, text, account_id, dedupe_key, created_at)"
                " VALUES (?, 'session_dead', ?, ?, ?, ?)",
                (w.user_id, f"{c['nickname']} was logged out of OnlyFans", c["id"], f"slop:session_dead:{c['id']}",
                 ts(w.now - timedelta(minutes=10 * (i + 1)))))
    ids = [r[0] for r in con.execute(
        "SELECT id FROM agency_notifications WHERE agency_user_id=? AND dedupe_key LIKE 'slop:%' ORDER BY id",
        (w.user_id,))]
    con.close()
    return ids
