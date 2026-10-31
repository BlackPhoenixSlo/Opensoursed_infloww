"""Mass placeholders whose OF echo never came: per Creator one closed `mass_runs` row (status
`ok`, its body and send stamp, as `server._close_mass_run` leaves it, audience_filter as
`server._open_mass_run` stores an explicit-fan composer send) and one optimistic `messages` row
per recipient in the shape `attribution.write_mass_optimistic_rows` writes (message_id
`_MASS_PLACEHOLDER_BASE + run`, `temp_id mass:<run>:<fan>`, the run, the body as stored with
plain `\\n`, sender_name "", no employee). Prod's common case: 90.6% of stubs never get a real
twin. Not written: the forward-only chat-preview bump (a 2-day-old send never beats the thread's
newer history anyway).

`seed(w, fans_by_aid, body_of, at)`: per Creator its recipient fan ids, `body_of(aid)` its run's
caption, one send stamp `at` for all. Returns `{account_id: mass_run_id}` (also
`w.data["mass_placeholders"]`).

`PLACEHOLDER_BASE` / `PLACEHOLDER_CEIL`: the service's band, read off `service/attribution.py`
(by ast: importing attribution would bind its DB engine to the checkout's DB)."""
from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import World, ts


def _attribution_const(name: str) -> int:
    tree = ast.parse((Path(__file__).resolve().parents[2] / "service" / "attribution.py").read_text())
    return next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == name for t in n.targets))


PLACEHOLDER_BASE = _attribution_const("_MASS_PLACEHOLDER_BASE")
PLACEHOLDER_CEIL = _attribution_const("_MASS_PLACEHOLDER_CEIL")


def _audience(fan_ids: list[int]) -> str:
    """mass_runs.audience_filter as `server._open_mass_run` stores a composer send to explicit
    fans (`user_ids` only; same keys, same order). Not `send_mass_decide.audience_filter`: that
    is the automation sender's wider shape, and this run is a composer send."""
    return json.dumps({"user_lists": [], "included_users": list(fan_ids), "excluded_users": [],
                       "excluded_user_lists": []})


def seed(w: World, fans_by_aid: dict[str, list[int]], body_of: Callable[[str], str],
         at: datetime) -> dict[str, int]:
    runs: dict[str, int] = {}
    con = w.sql()
    with con:
        for aid, fan_ids in fans_by_aid.items():
            aid, body = str(aid), body_of(str(aid))
            fans = sorted({int(f) for f in fan_ids})
            run = con.execute(
                "INSERT INTO mass_runs(account_id, audience_filter, recipient_count, started_at, completed_at, "
                "status, body, sent_at, recipients_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (aid, _audience(fans), len(fans), ts(at), ts(at), "ok", body, ts(at),
                 json.dumps(fans))).lastrowid
            con.executemany(
                "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
                "media_count, price_cents, is_paid, is_tip, is_unsent, is_promise, sent_by_employee_id, temp_id, "
                "mass_run_id, automation_kind, raw_json, created_at, ingested_at) "
                "VALUES (?,?,?,'out','',?,'[]',0,0,NULL,0,0,0,NULL,?,?,NULL,NULL,?,?)",
                [(aid, f, PLACEHOLDER_BASE + run, body, f"mass:{run}:{f}", run, ts(at), ts(at)) for f in fans])
            runs[aid] = run
    con.close()
    w.data["mass_placeholders"] = runs
    return runs
