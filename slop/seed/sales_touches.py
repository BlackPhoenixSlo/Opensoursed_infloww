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
        if row is None:
            row = (con.execute("INSERT INTO employees (display_name, color, is_active, created_at) "
                               "VALUES ('Automation', '#808080', 0, ?)", (ts(w.now),)).lastrowid,)
            w.data["automation_seeded"] = True
        out["Automation"] = row[0]
    con.close()
    w.data["employee_ids"] = out
    return out
