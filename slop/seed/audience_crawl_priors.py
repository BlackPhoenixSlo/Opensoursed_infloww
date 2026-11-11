"""Earlier sends the Audience crawl's skip reads (fetch diet P2b, scenarios/2026-11-08-mass-audience-crawl.py): per
Creator one immediate ok send of `user_lists` excluding its `excluded_user_lists` (the Creator's Auto_Exclude list id)
and `excluded_users` (the guard that list held), `age` ago, as send_mass_message leaves it (automation_kind
send_mass_message, queue_id, audience_filter with `online` / `filters` false, NULL recipients) with its crawl verdict
(`crawl_outcome`): comparable to the Creator's next sends (the same kind, user_lists and excluded_user_lists, no
explicit ids), so `_priors` reads it. Older than AUDIENCE_CRAWL_REPROBE_S, an `incomplete` verdict is the re-probe
case: the next send crawls for real.

Queue ids ID_BASE + the Creator's index in `verdicts` (above seed/mass_broadcast_cache.py's 7.7e9 block, below
lib/of_wire.py's 9e9 ids; not in OF's feed). Deterministic: no randomness, only `now` and the inputs.
"""
from __future__ import annotations

import json
from datetime import timedelta

from . import World, ts

ID_BASE = 7_800_000_000


def seed(w: World, verdicts: dict[str, tuple[str, timedelta]], user_lists: list[str],
         excluded_user_lists: dict[str, list] | None = None,
         excluded_users: dict[str, list] | None = None) -> dict[str, int]:
    """`verdicts`: Creator -> (its earlier send's crawl_outcome, its age, past the crawl deadline so
    recover_at_boot never picks it); `excluded_user_lists` / `excluded_users`: Creator -> its exclude list ids /
    excluded fan ids. Returns Creator -> that send's mass_runs id."""
    out: dict[str, int] = {}
    con = w.sql()
    with con:
        for i, (aid, (outcome, age)) in enumerate(verdicts.items()):
            at = w.now - age
            af = json.dumps({"user_lists": list(user_lists), "included_users": [],
                             "excluded_users": sorted((excluded_users or {}).get(aid) or ()),
                             "excluded_user_lists": list((excluded_user_lists or {}).get(aid) or ()),
                             "online": False, "filters": False})
            out[aid] = con.execute(
                "INSERT INTO mass_runs(account_id, audience_filter, recipient_count, queue_id, automation_kind, "
                "started_at, completed_at, status, body, sent_at, crawl_outcome) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (aid, af, 0, ID_BASE + i, "send_mass_message", ts(at), ts(at + timedelta(seconds=2)), "ok",
                 f"slop prior send {i}", ts(at + timedelta(seconds=2)), outcome)).lastrowid
    con.close()
    return out
