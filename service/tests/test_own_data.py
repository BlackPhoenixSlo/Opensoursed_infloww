#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import own_data  # noqa: E402

_MOD = Path(own_data.__file__).resolve()
_SCOPE = json.loads((_MOD.parent / "cell_scope.json").read_text())["tables"]
A, B, BIG = "acct_a", "acct_b", "9007199254740993"


def _fresh() -> Path:
    path = Path(tempfile.mkdtemp(prefix="own_data_t_")) / "db.sqlite"
    src = sqlite3.connect(str(_harness.DB_PATH))
    dst = sqlite3.connect(str(path))
    src.backup(dst)
    src.close()
    dst.execute("PRAGMA journal_mode=WAL")
    dst.close()
    return path


def _ins(con, table, **vals):
    for name, typ, notnull, dflt, pk in [(r[1], r[2].upper(), r[3], r[4], r[5])
                                          for r in con.execute(f"PRAGMA table_info({table})")]:
        if name in vals or not notnull or dflt is not None or (pk and "INT" in typ):
            continue
        vals[name] = 0 if any(t in typ for t in ("INT", "BOOL", "NUM", "REAL")) else "x"
    con.execute(f"INSERT INTO {table} ({','.join(vals)}) VALUES ({','.join('?' * len(vals))})", list(vals.values()))


def _seeded() -> Path:
    path = _fresh()
    con = sqlite3.connect(str(path))
    for acct in (A, B, BIG):
        _ins(con, "accounts", id=acct)
        _ins(con, "fans", account_id=acct, fan_id="f1", notes=f"note {acct}", of_username="u")
        _ins(con, "messages", account_id=acct, fan_id="f1", message_id="m1", direction="out", body="hi",
             automation_kind="followup")
        _ins(con, "skip_list", account_id=acct, fan_id="f1", reason="r")
        _ins(con, "lists", account_id=acct, name=f"l {acct}", kind="local")
    lists = dict(con.execute("SELECT account_id, id FROM lists"))
    for acct in (A, B):
        _ins(con, "list_members", list_id=lists[acct], fan_id="f1", added_by_employee_id=1)
    _ins(con, "s4s_requests", from_account_id=A, to_account_id=B, status="pending", slot_at="2026-11-01")
    con.commit()
    con.close()
    return path


def _sums(path, *accts):
    return own_data.checksums(path, list(accts) or None)


def _edit(path, sql, *args):
    con = sqlite3.connect(str(path))
    con.execute(sql, args)
    con.commit()
    con.close()


def _cli(*args):
    p = subprocess.run([sys.executable, "-I", str(_MOD), *map(str, args)], capture_output=True, text=True,
                       cwd=tempfile.gettempdir(), timeout=120)
    return p.returncode, p.stdout, p.stderr


def case_real_schema_is_fully_classified_and_matches_cell_scope_tables():
    con = sqlite3.connect(str(_harness.DB_PATH))
    assert own_data.unclassified(con) == [], own_data.unclassified(con)
    live = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite%'")}
    con.close()
    runtime = {"cell_meta", "agency_copy_gate", "agency_copy_sections", "agency_copy_missing_owners",
               "agency_copy_version", "creator_reservations", "creator_handoff_ops", "send_ops", "cell_holds",
               "employee_floor", "employee_floor_reports"}
    assert set(own_data.TABLES) == live | runtime and live == set(_SCOPE), set(own_data.TABLES) ^ live ^ set(_SCOPE)
    for t, (_, own, other) in own_data.TABLES.items():
        assert not set(own.split()) & set(other.split()), t


def case_cells_runtime_tables_are_classified():
    import agency_copy
    import cell_hold
    import cell_mode
    import creator_reservations
    import send_ops
    for role in ("control", "data"):
        path = _fresh()
        cell_mode.install_meta(f"sqlite:///{path}")
        send_ops.install(f"sqlite:///{path}")
        cell_hold.install(f"sqlite:///{path}")
        agency_copy.install(f"sqlite:///{path}", role)
        if role == "control":
            creator_reservations.install(f"sqlite:///{path}")
        con = sqlite3.connect(str(path))
        assert own_data.unclassified(con) == [], (role, own_data.unclassified(con))
        con.close()


def case_new_table_or_column_goes_red_by_name():
    path = _fresh()
    _edit(path, "CREATE TABLE zz_new (id INTEGER PRIMARY KEY)")
    _edit(path, "ALTER TABLE fans ADD COLUMN zz TEXT")
    con = sqlite3.connect(str(path))
    assert own_data.unclassified(con) == ["fans.zz", "zz_new"], own_data.unclassified(con)
    con.close()
    rc, out, _ = _cli("unclassified", path)
    assert rc == 1 and out.split() == ["fans.zz", "zz_new"], (rc, out)
    rc, out, err = _cli("unclassified", _fresh())
    assert rc == 0 and out == "", (rc, out, err)


def case_checksum_equal_on_byte_copy():
    path = _seeded()
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    copy = path.with_name("copy.sqlite")
    shutil.copyfile(path, copy)
    a = _sums(path)
    assert set(a) == {f"?:{a}" for a in (A, B, BIG)}, a
    assert a == _sums(copy) and len(set(a.values())) == 3, a


def case_own_change_moves_only_that_account():
    path = _seeded()
    base = _sums(path)
    for sql, args in [("UPDATE fans SET notes = 'changed' WHERE account_id = ?", (A,)),
                      ("UPDATE skip_list SET reason = 'changed' WHERE account_id = ?", (A,)),
                      ("UPDATE list_members SET added_by_employee_id = 7 WHERE list_id = "
                       "(SELECT id FROM lists WHERE account_id = ?)", (A,)),
                      ("UPDATE messages SET automation_kind = 'mass' WHERE account_id = ?", (A,))]:
        _edit(path, sql, *args)
        now = _sums(path)
        assert now[f"?:{A}"] != base[f"?:{A}"], sql
        assert now[f"?:{B}"] == base[f"?:{B}"] and now[f"?:{BIG}"] == base[f"?:{BIG}"], sql
        base = now


def case_other_accounts_and_not_own_columns_leave_a_unchanged():
    path = _seeded()
    base = _sums(path)
    _edit(path, "UPDATE fans SET notes = 'b changed' WHERE account_id = ?", B)
    _edit(path, "UPDATE skip_list SET reason = 'b changed' WHERE account_id = ?", B)
    mid = _sums(path)
    assert mid[f"?:{A}"] == base[f"?:{A}"] and mid[f"?:{B}"] != base[f"?:{B}"]
    _edit(path, "UPDATE fans SET of_username = 'new', lifetime_spend_cents = 99 WHERE account_id = ?", A)
    _edit(path, "UPDATE messages SET body = 'edited', is_paid = 1 WHERE account_id = ?", A)
    _edit(path, "UPDATE chats SET unread_count = 5 WHERE account_id = ?", A)
    assert _sums(path)[f"?:{A}"] == base[f"?:{A}"]


def case_pair_row_counts_for_both_sides():
    path = _seeded()
    base = _sums(path)
    _edit(path, "UPDATE s4s_requests SET status = 'accepted'")
    now = _sums(path)
    assert now[f"?:{A}"] != base[f"?:{A}"] and now[f"?:{B}"] != base[f"?:{B}"] and now[f"?:{BIG}"] == base[f"?:{BIG}"]


def case_one_read_snapshot_ignores_a_concurrent_writer():
    path = _seeded()
    before = _sums(path)
    stmts: list[str] = []
    real = sqlite3.connect

    def hooked(*a, **k):
        con = real(*a, **k)

        def trace(sql):
            stmts.append(sql)
            if 'FROM "fans"' in sql and len([s for s in stmts if 'FROM "fans"' in s]) == 1:
                w = real(str(path))
                w.execute("UPDATE skip_list SET reason = 'raced' WHERE account_id = ?", (A,))
                w.commit()
                w.close()
        con.set_trace_callback(trace)
        return con

    own_data.sqlite3.connect = hooked
    try:
        during = _sums(path)
    finally:
        own_data.sqlite3.connect = real
    assert during == before, "a write between table reads leaked into the result"
    assert _sums(path)[f"?:{A}"] != before[f"?:{A}"], "the racing write did land"
    assert stmts[0] == "BEGIN" and stmts[-1] == "ROLLBACK", (stmts[0], stmts[-1])
    assert stmts.count("BEGIN") == 1 and not any(s.startswith(("INSERT", "UPDATE", "DELETE")) for s in stmts)


def case_big_id_round_trips_as_string_through_cli():
    path = _seeded()
    rc, out, err = _cli("checksum", path)
    assert rc == 0, err
    full = json.loads(out)
    assert f"?:{BIG}" in full and full == _sums(path), out
    assert out == json.dumps(full, sort_keys=True) + "\n"
    rc, out, err = _cli("checksum", path, f"of:{BIG}", A)
    assert rc == 0, err
    assert json.loads(out) == {f"of:{BIG}": full[f"?:{BIG}"], A: full[f"?:{A}"]}, out
    assert own_data.checksum(path, BIG) == full[f"?:{BIG}"]
    assert _cli("bogus")[0] == 2


def case_checksum_uses_platform_from_session_metadata():
    path = _seeded()
    sessions = path.parent / "accounts"
    (sessions / BIG).mkdir(parents=True)
    (sessions / BIG / "meta.json").write_text(json.dumps({"platform": "fansly"}))
    (sessions / A).mkdir()
    (sessions / A / "meta.json").write_text("{invalid")
    sums = own_data.checksums(path, session_accounts=sessions)
    rc, out, err = _cli("checksum", path, "--sessions", sessions)
    assert rc == 0, err
    assert json.loads(out) == sums
    assert set(sums) == {f"fansly:{BIG}", f"?:{A}", f"?:{B}"}
    assert sums[f"fansly:{BIG}"] == own_data.checksum(path, BIG)


def case_older_db_missing_tables_and_columns_is_skipped():
    path = _seeded()
    _edit(path, "DROP TABLE skip_list")
    _edit(path, "ALTER TABLE fans DROP COLUMN notes")
    _edit(path, "DROP TABLE lists")
    assert set(_sums(path)) == {f"?:{a}" for a in (A, B, BIG)}


def case_own_linkage_agrees_with_cell_scope():
    bad = []
    for t, (link, own, _) in own_data.TABLES.items():
        if not own:
            continue
        scope = _SCOPE[t]
        if not link:
            ok = scope["scope"] in ("agency", "mixed", "cell_local", "cache")
        elif ">" in link:
            fk, _, target = link.partition(">")
            ok = scope["scope"] == "model_via" and scope.get("via") == [f"{t}.{fk}->{target.partition('.')[0]}"]
        elif "+" in link:
            fks = {f.split("->")[0] for f in scope.get("hint", {}).get("fks", [])}
            ok = scope["scope"] == "pair" and set(link.split("+")) <= fks
        else:
            ok = scope["scope"] == "model" and link == "account_id"
        if not ok:
            bad.append(f"{t}: own_data links {link!r}, cell_scope says {scope['scope']} {scope.get('via')}")
    assert not bad, bad


if __name__ == "__main__":
    _harness.run()
