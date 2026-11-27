from __future__ import annotations

import _harness

import contextlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

_harness.bootstrap()

import agency_copy as ac  # noqa: E402
from _cell_probe.cell_probe import COPIED as PROBE_COPIED  # noqa: E402
from db.models import Base  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="cell-copy-"))
BIG_ACC, BIG_ACC2 = "900539700124344320", "900539700124344321"
BIG_FAN = 9007199254740993


def _fresh(name: str, role: str) -> str:
    path = str(_TMP / f"{name}.db")
    with contextlib.closing(sqlite3.connect(_harness.DB_PATH)) as src, contextlib.closing(sqlite3.connect(path)) as dst:
        src.backup(dst)
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS cell_meta (data_gen INTEGER NOT NULL DEFAULT 1, copy_epoch INTEGER,"
                   " copy_version INTEGER, section_sha TEXT, applied_at TEXT, confirmed_at TEXT, grant_gen INTEGER)")
        db.execute("INSERT INTO cell_meta (data_gen) VALUES (1)")
    ac.install(f"sqlite:///{path}", role)
    return path


def _db(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None, timeout=30)
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _ver(path: str) -> tuple[int, int, int]:
    with contextlib.closing(_db(path)) as db:
        return ac._current(db)


def _seed(path: str) -> None:
    with contextlib.closing(_db(path)) as db:
        db.execute("INSERT INTO users (id, username, password, created_at, last_seen_at, is_admin, totp_secret,"
                   " totp_recovery) VALUES ('u1', 'owner', '$2b$hash', '2026-01-01', '2026-01-01', 1, 'TOTPSEED',"
                   " 'RECOVERY')")
        db.execute("INSERT INTO chatters (id, username, password, is_active, created_at, last_seen_at, totp_secret)"
                   " VALUES ('c1', 'chat', '$2b$hash2', 1, '2026-01-01', '2026-01-01', 'TOTP2')")
        db.execute("INSERT INTO chatter_users VALUES ('c1', 'u1', '2026-01-01')")
        db.execute("INSERT INTO accounts (id, is_active_default) VALUES (?, 1), (?, 1)", (BIG_ACC, BIG_ACC2))
        db.execute("INSERT INTO user_accounts VALUES ('u1', ?, '2026-01-01'), ('u1', ?, '2026-01-01')",
                   (BIG_ACC, BIG_ACC2))
        db.execute("INSERT INTO chatter_account_access VALUES ('c1', 'u1', ?, '2026-01-01')", (BIG_ACC2,))
        db.execute("INSERT INTO employees (id, display_name, is_active, created_at, user_id) VALUES"
                   " (7, 'Ann', 1, '2026-01-01', 'u1'), (8, 'Bob', 1, '2026-01-01', 'u1')")
        db.execute("INSERT INTO owner_tokens (id, user_id, name, token_sha256, hint, created_at, expires_at) VALUES"
                   " (1, 'u1', 'k', 'abc', 'h', '2026-01-01', '2099-01-01')")
        db.execute("INSERT INTO blacklist (fan_id, reason, added_at) VALUES (?, 'x', '2026-01-01')", (BIG_FAN,))


def _doc(path: str, have: dict | None = None) -> dict:
    return json.loads(ac.answer(ac.read_snapshot(path), have or {}))


def _copied_state(path: str) -> dict:
    with contextlib.closing(_db(path)) as db:
        return {t: db.execute(f'SELECT * FROM "{t}" ORDER BY 1').fetchall() for t in ac.COPIED}


def case_allowlist_covers_every_column_and_no_secret() -> None:
    assert set(ac.COPIED) == set(PROBE_COPIED), set(ac.COPIED) ^ set(PROBE_COPIED)
    for t in ac.COPIED:
        cols = {c.name for c in Base.metadata.tables[t].columns}
        listed = set(ac.FIELDS[t]) | set(ac.LOCAL.get(t, ())) | (ac.SECRET & cols)
        assert cols == listed, (t, cols ^ listed)
        assert not (set(ac.FIELDS[t]) & (ac.SECRET | {"last_seen_at", "last_used_at"})), t


def case_control_version_and_grant_gen() -> None:
    ctl = _fresh("ctl-ver", "control")
    e0, v0, g0 = _ver(ctl)
    _seed(ctl)
    e1, v1, g1 = _ver(ctl)
    assert e1 == e0 and v1 > v0 and g1 > g0, (v0, v1, g0, g1)
    with contextlib.closing(_db(ctl)) as db:
        db.execute("UPDATE users SET last_seen_at = '2026-02-02', password = 'new', totp_secret = 'x'")
        db.execute("UPDATE chatters SET last_seen_at = '2026-02-02'")
        db.execute("UPDATE owner_tokens SET last_used_at = '2026-02-02'")
        assert _ver(ctl) == (e1, v1, g1), "local-only or secret column moved the copy version"
        db.execute("UPDATE employees SET display_name = 'Anna' WHERE id = 7")
        _, v2, g2 = _ver(ctl)
        assert v2 == v1 + 1 and g2 == g1, "plain row change must not move grant_gen"
        db.execute("UPDATE chatters SET display_name = 'Chat'")
        assert _ver(ctl)[2] == g1
        db.execute("UPDATE chatters SET is_active = 0")
        assert _ver(ctl)[2] == g1 + 1, "deactivating a chatter is a revoke"
        db.execute("DELETE FROM chatter_account_access")
        assert _ver(ctl)[2] == g1 + 2


def case_answer_holds_no_secret_and_skips_matching_sections() -> None:
    ctl = _fresh("ctl-ans", "control")
    _seed(ctl)
    raw = ac.answer(ac.read_snapshot(ctl), {})
    for needle in (b"$2b$", b"TOTPSEED", b"RECOVERY", b"TOTP2", b"password", b"totp"):
        assert needle not in raw, needle
    doc = json.loads(raw)
    assert set(doc) >= {"format", "epoch", "version", "grant_gen", "sections"}, doc.keys()
    assert str(BIG_FAN).encode() in raw and doc["sections"]["blacklist"]["rows"][0]["fan_id"] == BIG_FAN
    have = {t: s["sha256"] for t, s in doc["sections"].items() if t != "users"}
    slim = json.loads(ac.answer(ac.read_snapshot(ctl), have))
    assert "rows" in slim["sections"]["users"] and "rows" not in slim["sections"]["employees"], slim["sections"]


def case_apply_copies_whole_and_stores_control_grant_gen() -> None:
    ctl, cell = _fresh("ctl-apply", "control"), _fresh("cell-apply", "data")
    _seed(ctl)
    doc = _doc(ctl)
    res = ac.apply(cell, doc)
    assert res["applied"] and "users" in res["changed"], res
    mine = ac.meta_at(cell)
    assert (mine["epoch"], mine["version"], mine["grant_gen"]) == (doc["epoch"], doc["version"], doc["grant_gen"])
    with contextlib.closing(_db(cell)) as db:
        assert db.execute("SELECT password, totp_secret, totp_recovery FROM users").fetchone() == ("!", None, None)
        assert db.execute("SELECT account_id FROM chatter_account_access").fetchone() == (BIG_ACC2,)
        assert db.execute("SELECT is_active_default FROM accounts WHERE id = ?", (BIG_ACC2,)).fetchone() == (0,)
        assert db.execute("SELECT fan_id FROM blacklist").fetchone() == (BIG_FAN,)
        assert db.execute("SELECT open FROM agency_copy_gate").fetchone() == (0,)
    assert not ac.apply(cell, doc)["applied"], "same version applied twice"
    with contextlib.closing(_db(ctl)) as db:
        db.execute("DELETE FROM employees WHERE id = 8")
        db.execute("DELETE FROM chatter_users")
    res = ac.apply(cell, _doc(ctl, ac.meta_at(cell)["section_sha"]))
    assert set(res["changed"]) == {"employees", "chatter_users"}, res
    with contextlib.closing(_db(cell)) as db:
        assert db.execute("SELECT id, is_active FROM employees ORDER BY id").fetchall() == [(7, 1), (8, 0)]
        assert db.execute("SELECT COUNT(*) FROM chatter_users").fetchone() == (0,)
    assert ac.meta_at(cell)["grant_gen"] == _ver(ctl)[2]


def case_recreated_mirror_and_deactivate_apply() -> None:
    ctl, cell = _seeded_control("ctl-mirror"), _fresh("cell-mirror", "data")
    with contextlib.closing(_db(ctl)) as db:
        db.execute("INSERT INTO employees (id, display_name, is_active, created_at, user_id, chatter_id) VALUES"
                   " (20, 'Mirror', 1, '2026-01-01', 'u1', 'c1')")
    ac.apply(cell, _doc(ctl))
    with contextlib.closing(_db(ctl)) as db:
        db.execute("DELETE FROM employees WHERE id = 20")
        db.execute("INSERT INTO employees (id, display_name, is_active, created_at, user_id, chatter_id) VALUES"
                   " (21, 'Mirror', 1, '2026-01-01', 'u1', 'c1')")
        db.execute("UPDATE chatters SET is_active = 0")
    res = ac.apply(cell, _doc(ctl, ac.meta_at(cell)["section_sha"]))
    assert res["applied"] and ("chatters", "c1") in res["revoked"], res
    with contextlib.closing(_db(cell)) as db:
        assert db.execute("SELECT id, is_active, chatter_id FROM employees WHERE id IN (20, 21) ORDER BY id"
                          ).fetchall() == [(20, 0, None), (21, 1, "c1")]
    with contextlib.closing(_db(ctl)) as db:
        db.execute("DELETE FROM chatters")
    res = ac.apply(cell, _doc(ctl, ac.meta_at(cell)["section_sha"]))
    assert ("chatters", "c1") in res["revoked"], res


def case_newer_epoch_beats_higher_version() -> None:
    ctl, cell = _fresh("ctl-epoch", "control"), _fresh("cell-epoch", "data")
    _seed(ctl)
    doc = _doc(ctl)
    ac.apply(cell, {**doc, "version": doc["version"] + 50})
    old_epoch = doc["epoch"]
    assert not ac.apply(cell, {**doc, "version": doc["version"] + 10})["applied"]
    new_epoch = ac.bump_epoch(ctl)
    assert new_epoch > old_epoch
    fresh = _doc(ctl)
    assert fresh["version"] < doc["version"] + 50
    assert ac.apply(cell, fresh)["applied"], "newer epoch with a lower version was refused"
    assert not ac.apply(cell, {**fresh, "epoch": old_epoch, "version": 10 ** 9})["applied"], "older epoch won"


def case_cell_triggers_block_copied_writes() -> None:
    cell = _fresh("cell-ro", "data")
    ac.apply(cell, _doc(_seeded_control("ctl-ro")))
    with contextlib.closing(_db(cell)) as db:
        for sql in ("INSERT INTO users (id, username, password, created_at, last_seen_at, is_admin) VALUES"
                    " ('u9', 'x', 'p', '2026', '2026', 0)",
                    "UPDATE users SET username = 'evil'", "UPDATE users SET password = 'p'",
                    "DELETE FROM employees", "UPDATE chatters SET is_active = 0",
                    "INSERT INTO runtime_switches (name, value_json) VALUES ('X', '1')"):
            _refused(db, sql)
        db.execute("UPDATE users SET last_seen_at = '2026-03-03'")
        db.execute("UPDATE chatters SET last_seen_at = '2026-03-03'")
        db.execute("UPDATE owner_tokens SET last_used_at = '2026-03-03'")
        db.execute("INSERT INTO agency_notifications (id, agency_user_id, kind, text) VALUES (1, 'u1', 'k', 't')")
        db.execute("DELETE FROM agency_copy_gate")
        _refused(db, "UPDATE users SET username = 'evil'")
        db.execute("INSERT INTO agency_copy_gate VALUES (2)")
        _refused(db, "DELETE FROM blacklist")
    from sqlalchemy import create_engine, exc, text
    engine = create_engine(f"sqlite:///{cell}")
    ac.log_read_only_hits(engine)
    hits = []
    handler = logging.Handler()
    handler.emit = hits.append
    ac.log.addHandler(handler)
    try:
        with engine.begin() as c:
            c.execute(text("UPDATE users SET username = 'evil'"))
    except exc.IntegrityError:
        pass
    finally:
        ac.log.removeHandler(handler)
        engine.dispose()
    assert any("agency copy is read-only on this Cell" in h.getMessage() for h in hits), "read-only hit not logged"


def _refused(db: sqlite3.Connection, sql: str) -> None:
    try:
        db.execute(sql)
    except sqlite3.IntegrityError as e:
        assert ac.READ_ONLY_MSG in str(e), (sql, e)
    else:
        raise AssertionError(f"local write allowed: {sql}")


def _seeded_control(name: str) -> str:
    ctl = _fresh(name, "control")
    _seed(ctl)
    return ctl


_TEXT = {"recent_events": "[]", "family_names": "[]", "pets": "[]", "tags": "[]", "custom_fields": "{}"}


def _fan_writer(db: sqlite3.Connection):
    cols = [r[1] for r in db.execute("PRAGMA table_info(fans)") if r[3] and r[4] is None]
    sql = f"INSERT INTO fans ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
    kinds = {r[1]: r[2].upper() for r in db.execute("PRAGMA table_info(fans)")}

    def row(fan_id: int) -> list:
        return [BIG_ACC if c == "account_id" else fan_id if c == "fan_id" else
                _TEXT.get(c, 0 if kinds[c] in ("INTEGER", "BIGINT", "BOOLEAN") else "") for c in cols]
    return sql, row


def case_failed_apply_during_fan_burst_keeps_old_version() -> None:
    ctl = _seeded_control("ctl-fail")
    cell = _fresh("cell-fail", "data")
    ac.apply(cell, _doc(ctl))
    with contextlib.closing(_db(cell)) as db:
        db.execute("INSERT INTO accounts (id, is_active_default) SELECT ?, 1"
                   " WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE id = ?)", (BIG_ACC, BIG_ACC))
    with contextlib.closing(_db(ctl)) as db:
        db.execute("UPDATE employees SET display_name = 'Changed'")
        db.execute("INSERT INTO users (id, username, password, created_at, last_seen_at, is_admin) VALUES"
                   " ('u2', 'second', 'p', '2026', '2026', 0)")
    good = _doc(ctl, ac.meta_at(cell)["section_sha"])
    late_fk = json.loads(json.dumps(good))
    late_fk["sections"]["chatter_users"] = {"sha256": "x", "rows": [
        {"chatter_id": "nobody", "user_id": "u1", "created_at": "2026"}]}
    early_null = json.loads(json.dumps(good))
    early_null["sections"]["users"]["rows"][0]["username"] = None
    for name, bad in (("FK at COMMIT", late_fk), ("NOT NULL in the first section", early_null)):
        before, meta_before = _copied_state(cell), ac.meta_at(cell)
        stop, errors, wrote = threading.Event(), [], [0]

        def burst(base: int) -> None:
            with contextlib.closing(_db(cell)) as w:
                sql, row = _fan_writer(w)
                i = 0
                while not stop.is_set() or i < 50:
                    i += 1
                    try:
                        w.execute(sql, row(base + i))
                        wrote[0] += 1
                    except Exception as e:
                        errors.append(repr(e))
                        return
        t = threading.Thread(target=burst, args=(BIG_FAN + 10 ** 6 * (len(name)),))
        t.start()
        time.sleep(0.05)
        try:
            ac.apply(cell, bad)
        except (sqlite3.IntegrityError, sqlite3.OperationalError):
            pass
        else:
            raise AssertionError(f"{name}: bad apply succeeded")
        stop.set()
        t.join(60)
        assert not errors, (name, errors[:3])
        assert wrote[0] >= 50, (name, wrote[0])
        assert _copied_state(cell) == before, f"{name}: copied tables changed after a failed apply"
        assert ac.meta_at(cell) == meta_before, name
        with contextlib.closing(_db(cell)) as db:
            assert db.execute("SELECT open FROM agency_copy_gate").fetchone() == (0,), name
            _refused(db, "UPDATE users SET username = 'evil'")
    assert ac.apply(cell, good)["applied"], "the good version did not apply after the failures"



async def case_changed_grant_section_clears_caches() -> None:
    import chatter_identity_cache
    import push_send
    ctl, cell = _seeded_control("ctl-cache"), _fresh("cell-cache", "data")
    with contextlib.closing(_db(ctl)) as db:
        db.execute("INSERT INTO push_subscriptions (id, endpoint, p256dh, auth, principal_kind, principal_id,"
                   " issued_ms, types, platforms, created_at, updated_at) VALUES ('p1',"
                   " 'https://fcm.googleapis.com/x', 'k', 'a', 'user', 'u1', 1, '[]', '{}', '2026', '2026')")
    gen = chatter_identity_cache.generation()
    res = ac.apply(cell, _doc(ctl))
    ac._notify_apply(cell, set(res["tables"]), set(res.get("revoked", ())))
    await ac._reload_runtime(cell, set(res["tables"]))
    assert chatter_identity_cache.generation() > gen, "grant change did not drop the identity cache"
    assert "p1" in push_send._subs, "copied push subscription not loaded"
    with contextlib.closing(_db(ctl)) as db:
        db.execute("DELETE FROM push_subscriptions")
        db.execute("UPDATE employees SET display_name = 'Z'")
    gen = chatter_identity_cache.generation()
    res = ac.apply(cell, _doc(ctl, ac.meta_at(cell)["section_sha"]))
    ac._notify_apply(cell, set(res["tables"]), set(res.get("revoked", ())))
    await ac._reload_runtime(cell, set(res["tables"]))
    assert "p1" not in push_send._subs
    assert chatter_identity_cache.generation() > gen



async def case_held_polls_share_one_version_read_and_one_snapshot() -> None:
    import asyncio
    ctl = _seeded_control("ctl-herd")
    reads, snaps = [0], [0]
    current, snapshot = ac._current, ac.read_snapshot

    def counted_current(db):
        reads[0] += 1
        time.sleep(0.02)
        return current(db)

    def counted_snapshot(path):
        snaps[0] += 1
        return snapshot(path)

    ac._current, ac.read_snapshot = counted_current, counted_snapshot
    ac._cur, saved = (0.0, None), dict(ac._snap)
    ac._snap.clear()
    try:
        got = await asyncio.gather(*(ac._snapshot(ctl) for _ in range(100)))
    finally:
        ac._current, ac.read_snapshot = current, snapshot
        ac._cur = (0.0, None)
        ac._snap.clear()
        ac._snap.update(saved)
    assert all(g is got[0] for g in got)
    assert (reads[0], snaps[0]) == (2, 1), (reads[0], snaps[0])

def _wire_rows(path: str) -> dict:
    with contextlib.closing(_db(path)) as db:
        out = {}
        for t in ac.COPIED:
            cols = ", ".join(f'"{c}"' for c in ac._wire(db, t))
            out[t] = db.execute(f'SELECT {cols} FROM "{t}" ORDER BY {", ".join(ac._pk(db, t))}').fetchall()
        return out


def _people_control(name: str) -> str:
    ctl = _seeded_control(name)
    with contextlib.closing(_db(ctl)) as db:
        db.execute("INSERT INTO chatters (id, username, password, is_active, created_at, last_seen_at) VALUES"
                   " ('c2', 'two', 'p', 1, '2026-01-01', '2026-01-01')")
        db.execute("INSERT INTO chatter_users VALUES ('c2', 'u1', '2026-01-01')")
        db.execute("INSERT INTO chatter_account_access VALUES ('c2', 'u1', ?, '2026-01-01')", (BIG_ACC,))
        db.execute("INSERT INTO employee_account_access VALUES (7, ?)", (BIG_ACC,))
    return ctl


def _doc2(snap: dict, prev: dict | None = None) -> dict:
    return json.loads(ac.answer2(snap, prev))


def _synced(ctl: str, cell: str) -> None:
    assert _wire_rows(cell) == _wire_rows(ctl), "cell rows differ from control"
    with contextlib.closing(_db(cell)) as db:
        assert ac.root_ok(db, ac.read_snapshot(ctl)["root"]), "cell root differs from control"


def case_format2_one_person_edit_sends_only_that_section() -> None:
    ctl, cell = _people_control("ctl-f2-edit"), _fresh("cell-f2-edit", "data")
    snap0 = ac.read_snapshot(ctl)
    assert {"grants/user:u1", "grants/chatter:c1", "grants/chatter:c2", "grants/employee:7", "grants/employee:8",
            "user_accounts", "blacklist"} <= set(snap0["sections2"]), sorted(snap0["sections2"])
    assert not set(snap0["sections2"]) & (set(ac.PEOPLE) - {"user_accounts"})
    res = ac.apply(cell, _doc2(snap0))
    assert res["applied"] and res["root_ok"], res
    _synced(ctl, cell)
    with contextlib.closing(_db(ctl)) as db:
        db.execute("INSERT INTO chatter_account_access VALUES ('c1', 'u1', ?, '2026-01-01')", (BIG_ACC,))
    snap1 = ac.read_snapshot(ctl)
    raw = ac.answer2(snap1, snap0["shas2"])
    doc = json.loads(raw)
    assert list(doc["sections"]) == ["grants/chatter:c1"] and doc["removed"] == [], doc
    assert doc["root_sha"] == snap1["root"] and doc["format"] == 2 and doc["grant_gen"] == snap1["grant_gen"]
    full1 = ac.answer(snap1, {t: s["sha256"] for t, s in snap0["sections"].items()})
    print(f"one person's edit: format 2 {len(raw)} B, format 1 {len(full1)} B")
    assert len(raw) < len(full1)
    res = ac.apply(cell, doc)
    assert res["root_ok"] and res["changed"] == ["grants/chatter:c1"], res
    assert "chatter_account_access" in res["tables"] and not res.get("revoked"), res
    _synced(ctl, cell)


def case_format2_removed_person_deleted_on_cell() -> None:
    ctl, cell = _people_control("ctl-f2-rm"), _fresh("cell-f2-rm", "data")
    snap0 = ac.read_snapshot(ctl)
    ac.apply(cell, _doc2(snap0))
    with contextlib.closing(_db(ctl)) as db:
        db.execute("DELETE FROM chatter_account_access WHERE chatter_id = 'c2'")
        db.execute("DELETE FROM chatter_users WHERE chatter_id = 'c2'")
        db.execute("DELETE FROM chatters WHERE id = 'c2'")
    doc = _doc2(ac.read_snapshot(ctl), snap0["shas2"])
    assert doc["sections"] == {} and doc["removed"] == ["grants/chatter:c2"], doc
    res = ac.apply(cell, doc)
    assert res["root_ok"] and ("chatters", "c2") in res["revoked"] and ("chatters", "c1") not in res["revoked"], res
    _synced(ctl, cell)
    assert "grants/chatter:c2" not in ac.meta_at(cell)["section_sha"]


def case_format2_tampered_section_repairs_from_full_copy() -> None:
    ctl, cell = _people_control("ctl-f2-tamper"), _fresh("cell-f2-tamper", "data")
    snap0 = ac.read_snapshot(ctl)
    ac.apply(cell, _doc2(snap0))
    with contextlib.closing(_db(cell)) as db:
        db.execute("UPDATE agency_copy_gate SET open = 1")
        db.execute("DELETE FROM chatter_account_access WHERE chatter_id = 'c2'")
        db.execute("UPDATE agency_copy_gate SET open = 0")
        db.execute("UPDATE agency_copy_sections SET sha256 = 'x' WHERE name = 'grants/chatter:c2'")
    same = _doc2(snap0, snap0["shas2"])
    assert not ac.confirm(cell, same), "root mismatch confirmed"
    with contextlib.closing(_db(ctl)) as db:
        db.execute("UPDATE employees SET display_name = 'Anna' WHERE id = 7")
    snap1 = ac.read_snapshot(ctl)
    res = ac.apply(cell, _doc2(snap1, snap0["shas2"]))
    assert res["applied"] and res["root_ok"] is False, res
    res = ac.apply(cell, _doc2(snap1), repair=True)
    assert res["root_ok"], res
    _synced(ctl, cell)
    assert ac.confirm(cell, _doc2(snap1, snap1["shas2"]))


def case_format2_from_format1_and_back() -> None:
    ctl, cell = _people_control("ctl-f2-mix"), _fresh("cell-f2-mix", "data")
    snap0 = ac.read_snapshot(ctl)
    ac.apply(cell, _doc(ctl))
    assert set(ac.meta_at(cell)["section_sha"]) == set(snap0["sections"])
    with contextlib.closing(_db(ctl)) as db:
        db.execute("DELETE FROM chatter_account_access WHERE chatter_id = 'c2'")
        db.execute("DELETE FROM chatter_users WHERE chatter_id = 'c2'")
        db.execute("DELETE FROM chatters WHERE id = 'c2'")
    snap1 = ac.read_snapshot(ctl)
    res = ac.apply(cell, _doc2(snap1, snap0["shas2"]))
    assert res["root_ok"] is False, "a format-1 holder matched the format-2 root"
    res = ac.apply(cell, _doc2(snap1), repair=True)
    assert res["root_ok"], res
    assert set(ac.meta_at(cell)["section_sha"]) == set(snap1["sections2"])
    _synced(ctl, cell)
    with contextlib.closing(_db(ctl)) as db:
        db.execute("UPDATE chatters SET display_name = 'One' WHERE id = 'c1'")
    res = ac.apply(cell, _doc(ctl, ac.meta_at(cell)["section_sha"]))
    assert res["applied"] and "chatters" in res["changed"], res
    assert set(ac.meta_at(cell)["section_sha"]) == set(ac.read_snapshot(ctl)["sections"])
    assert _wire_rows(cell) == _wire_rows(ctl)


def case_format2_unknown_table_kept_by_sha_only() -> None:
    ctl, cell = _people_control("ctl-f2-new-table"), _fresh("cell-f2-new-table", "data")
    doc = _doc2(ac.read_snapshot(ctl))
    doc["sections"]["future_table"] = {"sha256": "f" * 64, "rows": [{"id": 1}]}
    doc["root_sha"] = ac.root_of({n: x["sha256"] for n, x in doc["sections"].items()})
    res = ac.apply(cell, doc)
    assert res["root_ok"] and "future_table" not in res["tables"], res
    assert ac.meta_at(cell)["section_sha"]["future_table"] == "f" * 64
    with contextlib.closing(_db(cell)) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name = 'future_table'").fetchone()


def case_format1_answer_unchanged_and_format2_waits_for_every_cell() -> None:
    ctl = _people_control("ctl-f2-gate")
    snap = ac.read_snapshot(ctl)
    assert json.loads(ac.answer(snap, {}))["format"] == 1 and "root_sha" not in json.loads(ac.answer(snap, {}))
    pl = _TMP / "placement.json"
    pl.write_text(json.dumps({"cells": {"c0": {"role": "control"}, "a": {"role": "data"}, "b": {"role": "data"}}}))
    saved, os.environ["OI_CELL_MAP"] = os.environ.get("OI_CELL_MAP"), str(pl)
    ac._asked.clear()
    try:
        assert ac._format_for(2) == 1
        ac._asked.update(a=2)
        assert ac._format_for(2) == 1, "format 2 before every Cell asked"
        ac._asked.update(b=1)
        assert ac._format_for(2) == 1
        ac._asked.update(b=2, probe=1)
        assert ac._format_for(2) == 2 and ac._format_for(1) == 1, "old poller got format 2"
        time.sleep(0.01)
        pl.write_text(json.dumps({"cells": {"a": {"role": "data"}, "b": {"role": "data"}, "new": {"role": "data"}}}))
        assert ac._format_for(2) == 1, "a new Cell in Placement has not asked yet"
    finally:
        ac._asked.clear()
        if saved is None:
            os.environ.pop("OI_CELL_MAP", None)
        else:
            os.environ["OI_CELL_MAP"] = saved


def _restore(ctl: str, backup: str) -> None:
    with contextlib.closing(sqlite3.connect(backup)) as src, contextlib.closing(sqlite3.connect(ctl)) as dst:
        src.backup(dst)
    ac.bump_epoch(ctl)


def _missing(cell: str) -> list:
    with contextlib.closing(_db(cell)) as db:
        return db.execute(f"SELECT user_id FROM {ac.MISSING}").fetchall()


def case_older_control_keeps_missing_owner_and_its_cell_rows() -> None:
    for fmt in (1, 2):
        ctl, cell = _people_control(f"ctl-old-{fmt}"), _fresh(f"cell-old-{fmt}", "data")
        old = str(_TMP / f"ctl-old-{fmt}-backup.db")
        with contextlib.closing(sqlite3.connect(ctl)) as src, contextlib.closing(sqlite3.connect(old)) as dst:
            src.backup(dst)
        with contextlib.closing(_db(ctl)) as db:
            db.execute("INSERT INTO users (id, username, password, created_at, last_seen_at, is_admin) VALUES"
                       " ('u2', 'late', 'p', '2026-01-01', '2026-01-01', 0)")
            db.execute("INSERT INTO user_accounts VALUES ('u2', ?, '2026-01-01')", (BIG_ACC,))
        snap = lambda: _doc(ctl) if fmt == 1 else _doc2(ac.read_snapshot(ctl))  # noqa: E731
        ac.apply(cell, snap())
        with contextlib.closing(_db(cell)) as db:
            db.execute("INSERT INTO agency_notifications (agency_user_id, kind, text, created_at)"
                       " VALUES ('u2', 'creator', 'Nova expired', '2026-01-01')")
        _restore(ctl, old)
        doc = snap()
        res = ac.apply(cell, doc)
        assert res["applied"] and res["owners_missing"] == ["u2"] and ("users", "u2") in res["revoked"], res
        with contextlib.closing(_db(cell)) as db:
            assert db.execute("SELECT username FROM users WHERE id = 'u2'").fetchall() == [("late",)], fmt
            assert db.execute("SELECT text FROM agency_notifications WHERE agency_user_id = 'u2'"
                              ).fetchall() == [("Nova expired",)], "Cell-local CASCADE child deleted"
            assert db.execute("SELECT 1 FROM user_accounts WHERE user_id = 'u2'").fetchall() == []
        assert _missing(cell) == [("u2",)] and res.get("root_ok", True), res
        lines = []
        handler = logging.Handler()
        handler.emit = lambda r: lines.append(r.getMessage())
        ac.log.addHandler(handler)
        try:
            ac._log_missing(doc, res)
            with contextlib.closing(_db(ctl)) as db:
                db.execute("UPDATE employees SET display_name = 'Anna' WHERE id = 7")
            again = ac.apply(cell, snap())
            ac._log_missing(doc, again)
        finally:
            ac.log.removeHandler(handler)
        assert again["applied"] and again["owners_missing"] == [], again
        assert lines == [f"agency_copy_owner_missing owner=u2 copy={doc['epoch']}.{doc['version']}: Control no"
                         " longer lists this owner; kept its rows, access denied until a copy lists it again"], lines
        with contextlib.closing(_db(ctl)) as db:
            db.execute("INSERT INTO users (id, username, password, created_at, last_seen_at, is_admin) VALUES"
                       " ('u2', 'late', 'p', '2026-01-01', '2026-01-01', 0)")
        back = ac.apply(cell, snap())
        assert back["applied"] and back["owners_missing"] == [] and _missing(cell) == [], back
        with contextlib.closing(_db(cell)) as db:
            assert db.execute("SELECT COUNT(*) FROM agency_notifications WHERE agency_user_id = 'u2'"
                              ).fetchone() == (1,)
        if fmt == 2:
            _synced(ctl, cell)


def case_installer_moves_section_sha_into_its_table() -> None:
    ctl, cell = _seeded_control("ctl-mig"), _fresh("cell-mig", "data")
    ac.apply(cell, _doc(ctl))
    shas = ac.meta_at(cell)["section_sha"]
    with contextlib.closing(_db(cell)) as db:
        assert db.execute("SELECT section_sha FROM cell_meta").fetchone() == (None,)
        db.execute("UPDATE cell_meta SET section_sha = ?", (json.dumps({"users": "old"}),))
    ac.install(f"sqlite:///{cell}", "data")
    assert ac.meta_at(cell)["section_sha"] == {"users": "old"}, "rollback's section_sha not reloaded"
    ac.install(f"sqlite:///{cell}", "data")
    assert ac.meta_at(cell)["section_sha"] == {"users": "old"} and shas


def case_env_unset_installs_nothing() -> None:
    with contextlib.closing(_db(str(_harness.DB_PATH))) as db:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'cell_copy_%'"
                                          " OR name LIKE 'agency_copy_%'")}
    assert not names, names


def case_snapshot_waiters_reuse_newer_build() -> None:
    from unittest.mock import patch

    with contextlib.ExitStack() as patches:
        import asyncio

        started = threading.Event()
        release = threading.Event()
        all_sampled = None
        sampled = builds = 0

        async def version(_path):
            nonlocal sampled
            sampled += 1
            if sampled == 5:
                all_sampled.set()
            return 1, 1, 1

        def snapshot(_path):
            nonlocal builds
            builds += 1
            started.set()
            assert release.wait(5)
            return {"epoch": 1, "version": 2, "shas2": {}}

        patches.enter_context(patch.object(ac, "_version", version))
        patches.enter_context(patch.object(ac, "read_snapshot", snapshot))
        patches.enter_context(patch.object(ac, "_snap", {}))
        patches.enter_context(patch.object(ac, "_hist", {}))

        async def burst():
            nonlocal all_sampled
            all_sampled = asyncio.Event()
            patches.enter_context(patch.object(ac, "_one_snapshot_build", asyncio.Lock()))
            tasks = [asyncio.create_task(ac._snapshot("local")) for _ in range(5)]
            try:
                assert await asyncio.to_thread(started.wait, 5)
                await asyncio.wait_for(all_sampled.wait(), 5)
            finally:
                release.set()
            return await asyncio.gather(*tasks)

        assert all(s["version"] == 2 for s in asyncio.run(burst()))
        assert builds == 1


def case_poll_retries_runtime_reload_while_confirming_copy() -> None:
    from unittest.mock import patch

    with contextlib.ExitStack() as patches:
        import asyncio

        import httpx

        import runtime_switches
        from importlib import import_module
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        path = _fresh("runtime-reload", "data")
        patches.enter_context(patch.dict(os.environ, {"OI_CELL_CONTROL_URL": "http://127.0.0.1:1"}))
        patches.enter_context(patch.dict(os.environ, {"OI_ACCOUNTS": ""}))
        switch = "FULL_AI_CHAT_OFF"
        patches.enter_context(patch.dict(os.environ, {switch: "0"}))
        patches.enter_context(patch.object(ac, "_held", ac._held))
        patches.enter_context(patch.object(runtime_switches, "_overrides", {}))
        doc = {"format": 1, "epoch": 1, "version": 1, "grant_gen": 1, "sections": {
            "runtime_switches": {"sha256": "sha", "rows": [{"name": switch, "value_json": "true",
                                                            "updated_at": "2026-01-01", "updated_by": None}]},
        }}
        reads = 0
        confirmed_after_failure = False
        load_rows = runtime_switches._read_rows

        async def read_rows():
            nonlocal reads
            reads += 1
            if reads == 1:
                raise OSError("temporary load failure")
            result = await load_rows()
            loaded.set()
            return result

        async def get(_self, url, *, params):
            nonlocal confirmed_after_failure
            if reads == 1:
                confirmed_after_failure = ac.meta_at(path)["confirmed_at"] is not None
                assert not runtime_switches.value(switch)
            await asyncio.sleep(min(params["hold"], 0.05))
            return httpx.Response(200, json=doc, request=httpx.Request("GET", url))

        patches.enter_context(patch.object(runtime_switches, "_read_rows", read_rows))
        patches.enter_context(patch.object(httpx.AsyncClient, "get", get))

        async def exercise():
            nonlocal loaded
            loaded = asyncio.Event()
            engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
            try:
                with patch.object(import_module("db.engine"), "get_session", async_sessionmaker(engine)):
                    task = asyncio.create_task(ac.poll_forever(path))
                    try:
                        await asyncio.wait_for(loaded.wait(), 3)
                        assert runtime_switches.value(switch) is True
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            finally:
                await engine.dispose()

        loaded = None
        asyncio.run(exercise())
        assert reads == 2
        assert confirmed_after_failure


async def case_poll_revokes_cached_actor_during_reload_backoff() -> None:
    import asyncio
    from unittest.mock import patch

    import actor_token
    import chatters
    import httpx
    import runtime_switches
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    ctl, cell = _seeded_control("ctl-revoke-backoff"), _fresh("cell-revoke-backoff", "data")
    with contextlib.closing(_db(ctl)) as db:
        db.execute("INSERT INTO runtime_switches (name, value_json, updated_at) VALUES ('FULL_AI_CHAT_OFF', 'true', '2026')")
    first = _doc(ctl)
    with contextlib.closing(_db(ctl)) as db:
        db.execute("UPDATE chatters SET is_active = 0 WHERE id = 'c1'")
    second = _doc(ctl, {name: sec["sha256"] for name, sec in first["sections"].items()})
    assert second["grant_gen"] > first["grant_gen"]
    checked = asyncio.Event()
    claims = actor_token.Claims("u1", "chatter", "c1", "c1", False, 1, 2, second["grant_gen"])

    async def get(_self, url, *, params):
        held = ac.meta_at(cell)["grant_gen"]
        if held == first["grant_gen"]:
            assert await actor_token.chatter_identity(claims) is not None
        if held == second["grant_gen"]:
            checked.set()
            await asyncio.Future()
        return httpx.Response(200, json=first if held is None else second, request=httpx.Request("GET", url))

    engine = create_async_engine(f"sqlite+aiosqlite:///{cell}")
    try:
        with (patch.dict(os.environ, {"OI_CELL_CONTROL_URL": "http://127.0.0.1:1", "OI_ACCOUNTS": ""}),
              patch.object(chatters, "get_session", async_sessionmaker(engine)),
              patch.object(httpx.AsyncClient, "get", get),
              patch.object(runtime_switches, "load", side_effect=OSError("temporary load failure")) as load):
            task = asyncio.create_task(ac.poll_forever(cell))
            try:
                await asyncio.wait_for(checked.wait(), 3)
                assert load.await_count == 1
                assert await actor_token.chatter_identity(claims) is None, "revoked actor kept cached identity"
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    finally:
        await engine.dispose()


async def case_poll_revokes_cached_actor_when_owner_read_fails() -> None:
    import asyncio
    from unittest.mock import patch

    import actor_token
    import chatters
    import httpx
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    ctl, cell = _seeded_control("ctl-revoke-owners"), _fresh("cell-revoke-owners", "data")
    with contextlib.closing(_db(ctl)) as db:
        db.execute("INSERT INTO runtime_switches (name, value_json, updated_at) VALUES ('FULL_AI_CHAT_OFF', 'true', '2026')")
    first = _doc(ctl)
    with contextlib.closing(_db(ctl)) as db:
        db.execute("UPDATE chatters SET is_active = 0 WHERE id = 'c1'")
    second = _doc(ctl, {name: sec["sha256"] for name, sec in first["sections"].items()})
    assert second["grant_gen"] > first["grant_gen"]
    checked = asyncio.Event()
    claims = actor_token.Claims("u1", "chatter", "c1", "c1", False, 1, 2, second["grant_gen"])

    async def get(_self, url, *, params):
        held = ac.meta_at(cell)["grant_gen"]
        if held == first["grant_gen"]:
            assert await actor_token.chatter_identity(claims) is not None
        if held == second["grant_gen"]:
            checked.set()
            await asyncio.Future()
        return httpx.Response(200, json=first if held is None else second, request=httpx.Request("GET", url))

    engine = create_async_engine(f"sqlite+aiosqlite:///{cell}")
    try:
        with (patch.dict(os.environ, {"OI_CELL_CONTROL_URL": "http://127.0.0.1:1", "OI_ACCOUNTS": ""}),
              patch.object(chatters, "get_session", async_sessionmaker(engine)),
              patch.object(httpx.AsyncClient, "get", get),
              patch.object(ac, "_owners", side_effect=sqlite3.OperationalError("database is locked"))):
            task = asyncio.create_task(ac.poll_forever(cell))
            try:
                await asyncio.wait_for(checked.wait(), 3)
                assert await actor_token.chatter_identity(claims) is None, "revoked actor kept cached identity"
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    finally:
        await engine.dispose()


async def case_poll_new_control_epoch_reasserts_connected_reservations() -> None:
    import asyncio
    from unittest.mock import patch

    import accounts
    import creator_reservations as reservations
    import httpx

    ctl, cell = _fresh("ctl-activation-epoch", "control"), _fresh("cell-activation-epoch", "data")
    ac.apply(cell, _doc(ctl))
    ac.bump_epoch(ctl)
    fresh = _doc(ctl)
    directory = _TMP / "activation-epoch-sessions" / BIG_ACC
    directory.mkdir(parents=True)
    (directory / "session.json").write_text("{}")
    (directory / "latest.json").write_text('{"session":"session.json"}')
    initial_claim = threading.Event()
    reasserted = threading.Event()

    def send(_url, *, json, **_kwargs):
        assert json["creator_id"] == BIG_ACC and json["state"] == "active"
        if ac.meta_at(cell)["epoch"] == fresh["epoch"]:
            reasserted.set()
        else:
            initial_claim.set()
        return httpx.Response(200, json={"state": "active"})

    async def get(_self, url, *, params):
        if params["since"] == f'{fresh["epoch"]}.{fresh["version"]}':
            await asyncio.Future()
        return httpx.Response(200, json=fresh, request=httpx.Request("GET", url))

    with (patch.dict(os.environ, {"OI_CELL_CONTROL_URL": "http://127.0.0.1:1", "OI_ACCOUNTS": f"onlyfans:{BIG_ACC}"}),
          patch.object(accounts, "ACCOUNTS_DIR", directory.parent),
          patch.object(httpx, "post", send),
          patch.object(httpx.AsyncClient, "get", get)):
        retry = asyncio.create_task(reservations.retry_activations())
        try:
            assert await asyncio.to_thread(initial_claim.wait, 3)
            async with asyncio.timeout(3):
                while True:
                    with reservations._activation_lock:
                        if not reservations._pending_activation:
                            break
                    await asyncio.sleep(0.01)
            poll = asyncio.create_task(ac.poll_forever(cell))
            try:
                assert await asyncio.to_thread(reasserted.wait, 4), "Control epoch advanced without re-claiming"
            finally:
                poll.cancel()
                await asyncio.gather(poll, return_exceptions=True)
        finally:
            retry.cancel()
            await asyncio.gather(retry, return_exceptions=True)


_harness.run()
