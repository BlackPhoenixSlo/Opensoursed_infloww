from __future__ import annotations

from . import World, ts


def seed(w: World, fences: dict[str, dict[str, list[int]]], *, of_list_id_base: int) -> None:
    at = ts(w.now)
    con = w.sql()
    try:
        with con:
            for ci, (aid, f) in enumerate(fences.items()):
                row = con.execute("SELECT id FROM lists WHERE account_id = ? AND kind = 'exclude' AND name = 'MASSdmEXCLUDE'",
                                  (aid,)).fetchone()
                lid = row[0] if row else con.execute(
                    "INSERT INTO lists(account_id, of_list_id, name, kind, is_system, created_at) "
                    "VALUES (?,NULL,'MASSdmEXCLUDE','exclude',1,?)", (aid, at)).lastrowid
                con.executemany("INSERT OR IGNORE INTO list_members(list_id, fan_id, added_at) VALUES (?,?,?)",
                                [(lid, x, at) for x in f["massdm"]])
                out = set(f["autofence"])
                members = [x for (x,) in con.execute("SELECT fan_id FROM fans WHERE account_id = ?", (aid,))
                           if int(x) not in out]
                inc = con.execute("INSERT INTO lists(account_id, of_list_id, name, kind, is_system, synced_at, created_at) "
                                  "VALUES (?,?,'slop include','automation_include',1,?,?)",
                                  (aid, of_list_id_base + ci, at, at)).lastrowid
                con.executemany("INSERT INTO list_members(list_id, fan_id, added_at) VALUES (?,?,?)",
                                [(inc, x, at) for x in members])
                con.execute("INSERT OR IGNORE INTO account_ai_config (account_id, utc_offset, daily_cost_cap_cents)"
                            " VALUES (?, 0, 100)", (aid,))
                con.execute("UPDATE account_ai_config SET audience_mode = 'enforce', audience_list_id = ? "
                            "WHERE account_id = ?", (inc, aid))
    finally:
        con.close()
