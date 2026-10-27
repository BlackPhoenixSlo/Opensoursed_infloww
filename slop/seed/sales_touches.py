"""Sales touches: outbound messages to a fan written as the product writes them, for a
history no actor can produce on demand. Each touch is one `messages` row
(direction 'out', `sent_by_employee_id` set, created_at in the past) exactly as
`attribution.write_outbound_attribution` stores it:
  - an Automation 1:1 send: the Automation sentinel Employee, `automation_kind` set
    (what an automation's send writes; no actor runs an automation for a chosen fan);
  - a mass send: one `mass_runs` row (status `done`, started by that Employee) and the
    fan's row carrying its `mass_run_id` (OF's mass API is not faked in this run);
  - a human 1:1 send in the past (hours or days ago: the send route stamps `now`).
The credit triggers (tx_rollup) fire on these inserts as on any write.

`touches`: [{account_id, fan_id, employee_id, at, automation_kind?, mass?}]; returns them with
`message_id` (and `mass_run_id`) filled. Deterministic: ids in order, no randomness.
`w.data["sales_touches"]` keeps every touch written.

`employees(w, chatters)`: each chatter's mirror Employee for the Agency (the row
`employees.get_or_create_mirror_employee` keys by `chatter_id` and the owner's `user_id`;
accepting an invite with an Employee setup already writes it), read, or written in that
shape when missing, before any send, so a touch can name it whatever the send path does.
The Automation sentinel (`employees.get_automation_employee_id`) is migration 0011's row; a
fresh slop DB is built by `create_all`, which never writes it, so it is written here as 0011
does (`w.data["automation_seeded"]`). Returns {username: employee id, "Automation": the
sentinel's id} (`w.data["employee_ids"]`)."""
from __future__ import annotations

from . import World, ts

TOUCH_ID_BASE = 9_800_000_000_000


def seed(w: World, touches: list[dict]) -> list[dict]:
    done = w.data.setdefault("sales_touches", [])
    con = w.sql()
    with con:
        for k, t in enumerate(touches, start=len(done) + 1):
            mass_run_id = None
            if t.get("mass"):
                cur = con.execute(
                    "INSERT INTO mass_runs(account_id, started_by_employee_id, audience_filter, recipient_count, "
                    "automation_kind, started_at, completed_at, status) VALUES (?,?,?,?,?,?,?,?)",
                    (t["account_id"], t["employee_id"], "{}", 1, t.get("automation_kind"), ts(t["at"]),
                     ts(t["at"]), "done"))
                mass_run_id = cur.lastrowid
            mid = TOUCH_ID_BASE + k
            con.execute(
                "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
                "media_count, price_cents, is_paid, is_tip, is_unsent, is_promise, sent_by_employee_id, "
                "mass_run_id, automation_kind, created_at, ingested_at) "
                "VALUES (?,?,?,'out',?,?,'[]',0,0,NULL,0,0,0,?,?,?,?,?)",
                (t["account_id"], t["fan_id"], mid, "", "slop touch", t["employee_id"], mass_run_id,
                 t.get("automation_kind"), ts(t["at"]), ts(t["at"])))
            t.update(message_id=mid, mass_run_id=mass_run_id)
            done.append(t)
    con.close()
    return touches


def employees(w: World, chatters: list[dict]) -> dict[str, int]:
    con = w.sql()
    out: dict[str, int] = {}
    with con:
        for c in chatters:
            row = con.execute("SELECT id FROM employees WHERE chatter_id = ? AND user_id = ?",
                              (c["chatter_id"], c["owner"])).fetchone()
            if row is None:
                row = (con.execute(
                    "INSERT INTO employees(display_name, color, is_active, created_at, user_id, chatter_id) "
                    "VALUES (?,?,1,?,?,?)", (c["username"][:64], None, ts(w.now), c["owner"], c["chatter_id"])
                ).lastrowid,)
            out[c["username"]] = row[0]
        row = con.execute("SELECT id FROM employees WHERE display_name = 'Automation' AND is_active = 0").fetchone()
        if row is None:  # a fresh DB (create_all) lacks it: migration 0011's row, as 0011 writes it
            row = (con.execute("INSERT INTO employees (display_name, color, is_active, created_at) "
                               "VALUES ('Automation', '#808080', 0, ?)", (ts(w.now),)).lastrowid,)
            w.data["automation_seeded"] = True
        out["Automation"] = row[0]
    con.close()
    w.data["employee_ids"] = out
    return out
