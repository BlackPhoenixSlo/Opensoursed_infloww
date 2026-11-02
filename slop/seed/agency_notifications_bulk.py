"""Agency notifications in bulk: `n` `agency_notifications` rows for the owner, each shaped as
`notifications_api` files it (text, account / employee ids, data, dedupe key), read and
unread, aged 1 min to MAX_AGE (some past RETENTION), in one SQL insert.

Rows come in "filings", one per `notify` call, all of its notices with ONE `created_at`, so ties
on created_at happen and only `id` orders them; ids grow with created_at, as the product inserts.
Only a roles save files several at once (`_roles_step`): one `role_changed` per changed Employee
(distinct Employees), then at most one "Role settings changed"; every other kind is one row per
filing. Plus three boundary rows at `w.now - retention` -1 s / 0 / +1 s (a prune at `w.now`
must drop only the first).

Only what the product could have written:
  role_changed          "<name>'s role changed from <old> to <new>" (a former Employee: employee_id
                        NULL, as its FK leaves it after a delete) or "Role settings changed: <roles>"
  employee_deactivated  "<name> was deactivated" (a former Employee, employee_id NULL)
  message_unsent        "<actor> unsent a message to <fan> on <creator>", account_id, data
                        {fan_id, message_id} (message_id unique, growing with time); actor a former
                        Employee (employee_id NULL)
  session_dead          notify_session_dead's sentences and data, dedupe
                        "session_dead:<account>:<since iso>"; never older than its Creator
No `clock_in_missed`: each names a Shift occurrence (data.shift_id); the scenario files those
for real through the sweep. `w.data["agency_notifications_bulk"]`: {ids, boundary: {before,
at, after}: id}.
"""
from __future__ import annotations

import json
from datetime import timedelta

from . import World, ts

FIRST = ["Nina", "Omar", "Pia", "Quinn", "Rosa", "Theo", "Uma", "Vik", "Wes", "Yara", "Zed", "Bea"]
ROLES = ("Chatter", "Team Leader", "Creator", "Admin", "no role")
MAX_AGE = timedelta(days=120)
MESSAGE_ID_BASE = 9_100_000_000


def _session_dead(rng, c: dict, at) -> tuple:
    """notify_session_dead's row for Creator `c`'s dead episode (began just before `at`)."""
    name = c["nickname"] or c["id"]
    reason = rng.choice(("logged_out", "logged_out", "no_session", "otp_required"))
    data: dict = {"reason": reason}
    if reason == "otp_required":
        text = (f"{name} needs a 2FA code on OnlyFans: sign in to {name}'s OnlyFans account again "
                f"with Browserbase login to resume")
        data["href"] = "/creators?relink=browserbase"
    else:
        why = "has no captured session" if reason == "no_session" else "was logged out of OnlyFans"
        text = f"{name} {why}: relink the creator to resume"
    since = at - timedelta(seconds=rng.randint(1, 600), microseconds=rng.randint(0, 999_999))
    return ("session_dead", text, c["id"], json.dumps(data), f"session_dead:{c['id']}:{since.isoformat()}")


def seed(w: World, creators: list[dict], fans: dict[str, list[dict]], *, n: int,
         retention: timedelta) -> dict:
    rng = w.rng("agency_notifications_bulk")
    staff = [f"{rng.choice(FIRST)} {chr(65 + k % 26)}." for k in range(24)]  # former Employees

    def filing(at) -> list[tuple]:
        """The (kind, text, account_id, data_json, dedupe_key) notices one `notify` call files at `at`."""
        alive = [c for c in creators if c["created_at"] <= at]
        kind = rng.choices(("role_changed", "employee_deactivated", "message_unsent", "session_dead"),
                           (4, 2, 3, 2))[0]
        if kind in ("message_unsent", "session_dead") and not alive:
            kind = "role_changed"
        if kind == "role_changed":  # a roles save: changed assignments, then the definitions line
            settings = rng.random() < 0.15
            n_emp = rng.choice((0, 1, 1) if settings else (1, 1, 1, 1, 2, 3))
            out = []
            for name in rng.sample(staff, n_emp):
                old, new = rng.sample(ROLES, 2)
                out.append((kind, f"{name}'s role changed from {old} to {new}", None, None, None))
            if settings:
                out.append((kind, f"Role settings changed: {', '.join(rng.sample(ROLES[:4], rng.randint(1, 2)))}",
                            None, None, None))
            return out
        if kind == "employee_deactivated":
            return [(kind, f"{rng.choice(staff)} was deactivated", None, None, None)]
        c = rng.choice(alive)
        if kind == "session_dead":
            return [_session_dead(rng, c, at)]
        fan = rng.choice(fans[c["id"]])
        mid = MESSAGE_ID_BASE + int((at - (w.now - MAX_AGE)).total_seconds() * 1_000_000)  # one per microsecond
        return [(kind, f"{rng.choice(staff)} unsent a message to {fan['name']} on {c['nickname'] or c['id']}",
                 c["id"], json.dumps({"fan_id": fan["id"], "message_id": mid}), None)]

    filings: list[tuple] = []  # (created_at, [notice, ...], boundary key or None)
    left = n
    while left > 0:
        at = w.now - timedelta(seconds=rng.randint(60, int(MAX_AGE.total_seconds())),
                               microseconds=rng.randint(0, 999_999))
        notices = filing(at)[:left]
        filings.append((at, notices, None))
        left -= len(notices)
    edge = w.now - retention
    boundary = {"before": edge - timedelta(seconds=1), "at": edge, "after": edge + timedelta(seconds=1)}
    for key, at in boundary.items():
        filings.append((at, [("role_changed", f"{rng.choice(staff)}'s role changed from Chatter to Team Leader",
                              None, None, None)], key))
    filings.sort(key=lambda f: f[0])

    rows = []
    at_row: dict[str, int] = {}  # boundary key -> its index in rows
    for at, notices, key in filings:
        age = w.now - at
        read_p = 0.85 if age > timedelta(days=7) else 0.3
        if key:
            at_row[key] = len(rows)
        for kind, text, account_id, data, dedupe in notices:
            read_at = None
            if rng.random() < read_p:
                read_at = ts(min(w.now, at + timedelta(seconds=rng.randint(30, 3 * 86_400))))
            rows.append((w.user_id, kind, text, account_id, None, data, dedupe, ts(at), read_at))
    con = w.sql()
    with con:  # one transaction: nothing else inserts in between, so ids follow `rows`
        first = (con.execute("SELECT COALESCE(MAX(id), 0) FROM agency_notifications").fetchone()[0]) + 1
        con.executemany(
            "INSERT INTO agency_notifications (agency_user_id, kind, text, account_id, employee_id, data_json,"
            " dedupe_key, created_at, read_at) VALUES (?,?,?,?,?,?,?,?,?)", rows)
        ids = [r[0] for r in con.execute(
            "SELECT id FROM agency_notifications WHERE agency_user_id=? AND id>=? ORDER BY id", (w.user_id, first))]
    con.close()
    assert len(ids) == len(rows), (len(ids), len(rows))
    out = {"ids": ids, "boundary": {k: ids[i] for k, i in at_row.items()}}
    w.data["agency_notifications_bulk"] = out
    return out
