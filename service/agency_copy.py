from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import sys
import time
import types
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse, Response

from tenant_keys import NON_LLM_PROVIDERS

log = logging.getLogger(__name__)

FORMAT = 1
FORMAT2 = 2
HOLD_S = 25.0
_TICK_S = 0.1

# Allowlist, not denylist: a new column stays on control until listed here. Password/TOTP/recovery never leave it.
FIELDS: dict[str, tuple[str, ...]] = {
    "users": ("id", "username", "created_at", "is_admin", "sessions_valid_after"),
    "chatters": ("id", "username", "display_name", "color", "is_active", "created_at", "sessions_valid_after"),
    "chatter_users": ("chatter_id", "user_id", "created_at"),
    "employee_groups": ("id", "agency_user_id", "parent_id", "name", "created_at"),
    "employees": ("id", "display_name", "color", "is_active", "created_at", "user_id", "chatter_id", "group_id"),
    "user_accounts": ("user_id", "account_id", "created_at"),
    "chatter_account_access": ("chatter_id", "user_id", "account_id", "created_at"),
    "chatter_folder_access": ("chatter_id", "account_id", "folder_id", "folder_name", "created_at"),
    "employee_account_access": ("employee_id", "account_id"),
    "shifts": ("id", "agency_user_id", "start_utc", "end_utc", "tz", "repeat_days", "repeat_until",
               "cancelled_dates", "status", "created_by", "created_at", "updated_at", "cancelled_at"),
    "shift_assignments": ("shift_id", "employee_id", "account_id"),
    "user_settings": ("user_id", "tab", "config_json", "updated_at"),
    "settings_versions": ("id", "user_id", "tab", "effective_from", "config_json", "created_at"),
    "sensitive_words": ("id", "agency_user_id", "word", "word_key", "created_at"),
    "owner_tokens": ("id", "user_id", "name", "token_sha256", "hint", "created_at", "expires_at", "revoked_at"),
    "user_llm_keys": ("user_id", "provider", "api_key", "updated_at"),
    "mass_message_funnels": ("id", "name", "description", "opening_message", "vault_folder", "media_indices",
                             "opening_vault_folder", "opening_media_indices", "steps_json", "created_at",
                             "updated_at"),
    "blacklist": ("fan_id", "reason", "added_at"),
    "push_subscriptions": ("id", "endpoint", "p256dh", "auth", "principal_kind", "principal_id", "issued_ms", "types",
                           "platforms", "created_at", "updated_at"),
    "runtime_switches": ("name", "value_json", "updated_by", "updated_at"),
}
COPIED = tuple(FIELDS)
CONTROL_ONLY_ROWS = {"user_llm_keys": ("provider", frozenset(NON_LLM_PROVIDERS))}
SECRET = frozenset({"password", "totp_secret", "totp_enabled_at", "totp_recovery", "totp_last_step"})
LOCAL = {"users": ("last_seen_at",), "chatters": ("last_seen_at",), "owner_tokens": ("last_used_at",)}
# NOT NULL columns a Cell never receives, filled only when a row is first inserted; '!' is never a valid hash.
_FILL = {"password": lambda r: "!", "last_seen_at": lambda r: r.get("created_at")}
GRANT_ANY = ("user_accounts", "chatter_account_access", "chatter_folder_access", "employee_account_access",
             "shift_assignments", "chatter_users")
# Revokes on the principal rows move grant_gen too, so a token minted before a deactivate or sign-out-everywhere is old.
GRANT_REVOKE = {"users": ("sessions_valid_after",), "chatters": ("is_active", "sessions_valid_after")}
PEOPLE = {"users": ("user", "id"), "chatters": ("chatter", "id"),
          "chatter_users": ("chatter", "chatter_id"), "chatter_account_access": ("chatter", "chatter_id"),
          "chatter_folder_access": ("chatter", "chatter_id"), "employees": ("employee", "id"),
          "employee_account_access": ("employee", "employee_id"), "shift_assignments": ("employee", "employee_id")}
GRANTS = "grants/"
_UNMATERIALIZED = "unmaterialized:"
_HIST_N = 64
_ACCOUNT_FK = ("user_accounts", "chatter_account_access", "chatter_folder_access", "employee_account_access",
               "shift_assignments")
_RO = "cell_copy_ro_"
_VER = "cell_copy_v_"
_FLOOR = "cell_floor_"
READ_ONLY_MSG = "agency_copy_read_only:"
FLOOR_MSG = "employee_floor_pending"
FLOOR_NAME = "(employee id floor)"
GRANT_AGE_MSG = "grant_age_exceeded"
MISSING = "agency_copy_missing_owners"
_held: tuple[float | None, int | None] = (None, None)


def db_path(sync_url: str) -> str:
    return sync_url.split("sqlite:///", 1)[1]


def _connect(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    return db


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]


def _pk(db: sqlite3.Connection, table: str) -> list[str]:
    rows = sorted((r[5], r[1]) for r in db.execute(f'PRAGMA table_info("{table}")') if r[5])
    return [name for _, name in rows]


def _wire(db: sqlite3.Connection, table: str) -> list[str]:
    have = set(_columns(db, table))
    return [c for c in FIELDS[table] if c in have]


def _sync(db: sqlite3.Connection, prefix: str, want: dict[str, str]) -> int:
    have = dict(db.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name LIKE ?",
                           (prefix + "%",)).fetchall())
    n = 0
    for name in sorted(have.keys() - want.keys()):
        db.execute(f'DROP TRIGGER "{name}"')
        n += 1
    for name, sql in sorted(want.items()):
        if have.get(name) != sql:
            if name in have:
                db.execute(f'DROP TRIGGER "{name}"')
            db.execute(sql)
            n += 1
    return n


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


class _Schema:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db, self.tables, self._shape = db, _tables(db), {}

    def shape(self, t: str) -> tuple[list[str], list[str], list[str], str]:
        if t not in self._shape:
            local_cols, pk = set(_columns(self.db, t)), _pk(self.db, t)
            cols = [c for c in FIELDS[t] if c in local_cols]
            fill = [c for c in _FILL if c in local_cols and c not in cols]
            ins_cols = ", ".join(f'"{c}"' for c in cols + fill)
            vals = ", ".join("?" * (len(cols) + len(fill)))
            set_cols = [c for c in cols if c not in pk]
            sets = ", ".join(f'"{c}" = excluded."{c}"' for c in set_cols)
            conflict = f"DO UPDATE SET {sets}" if set_cols else "DO NOTHING"
            sql = f'INSERT INTO "{t}" ({ins_cols}) VALUES ({vals}) ON CONFLICT ({", ".join(pk)}) {conflict}'
            self._shape[t] = (pk, cols, fill, sql)
        return self._shape[t]


def read_only_triggers(db: sqlite3.Connection) -> dict[str, str]:
    out = {}
    present = _tables(db)
    for t in COPIED:
        if t not in present:
            continue
        stop = f"WHEN (SELECT open FROM agency_copy_gate) IS NOT 1 BEGIN SELECT RAISE(ABORT, '{READ_ONLY_MSG}{t}'); END"
        cols = ", ".join(f'"{c}"' for c in _columns(db, t) if c not in LOCAL.get(t, ()))
        out[f"{_RO}{t}_insert"] = f'CREATE TRIGGER "{_RO}{t}_insert" BEFORE INSERT ON "{t}" {stop}'
        out[f"{_RO}{t}_delete"] = f'CREATE TRIGGER "{_RO}{t}_delete" BEFORE DELETE ON "{t}" {stop}'
        out[f"{_RO}{t}_update"] = f'CREATE TRIGGER "{_RO}{t}_update" BEFORE UPDATE OF {cols} ON "{t}" {stop}'
    return out


def version_triggers(db: sqlite3.Connection) -> dict[str, str]:
    out = {}
    present = _tables(db)
    for t in COPIED:
        if t not in present:
            continue
        wire = _wire(db, t)
        revoke = [c for c in GRANT_REVOKE.get(t, ()) if c in wire]
        for op in ("insert", "delete", "update"):
            grant = t in GRANT_ANY or (t in GRANT_REVOKE and op == "delete")
            on = f'UPDATE OF {", ".join(chr(34) + c + chr(34) for c in wire)}' if op == "update" else op.upper()
            bump = "version = version + 1" + (", grant_gen = grant_gen + 1" if grant else "")
            body = f"UPDATE agency_copy_version SET {bump};"
            if op == "update" and not grant and revoke:
                moved = " OR ".join(f'OLD."{c}" IS NOT NEW."{c}"' for c in revoke)
                body += f" UPDATE agency_copy_version SET grant_gen = grant_gen + 1 WHERE {moved};"
            out[f"{_VER}{t}_{op}"] = f'CREATE TRIGGER "{_VER}{t}_{op}" AFTER {on} ON "{t}" BEGIN {body} END'
    return out


def floor_triggers() -> dict[str, str]:
    name = f"{_FLOOR}employees_insert"
    return {name: f'CREATE TRIGGER "{name}" BEFORE INSERT ON "employees" WHEN (SELECT pending FROM employee_floor)'
                  f" IS 1 BEGIN SELECT RAISE(ABORT, '{FLOOR_MSG}'); END"}


def _floor_tables(db: sqlite3.Connection) -> None:
    db.execute("CREATE TABLE IF NOT EXISTS employee_floor (pending INTEGER NOT NULL)")
    db.execute("INSERT INTO employee_floor SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM employee_floor)")
    db.execute("CREATE TABLE IF NOT EXISTS employee_floor_reports (cell TEXT PRIMARY KEY, epoch INTEGER NOT NULL,"
                " max_emp INTEGER NOT NULL, reported_at TEXT NOT NULL)")


_placement: tuple[tuple[int, int] | None, list[str]] = (None, [])


def placement_data_cells() -> list[str]:
    from cell_mode import read_placement

    global _placement
    st = os.stat(os.environ["OI_CELL_MAP"])
    if _placement[0] != (st.st_mtime_ns, st.st_size):
        cells = read_placement()["cells"]
        _placement = ((st.st_mtime_ns, st.st_size), sorted(c for c, v in cells.items() if v.get("role") == "data"))
    return _placement[1]


def is_floor_error(exc: Exception) -> bool:
    return FLOOR_MSG in str(getattr(exc, "orig", exc))


def _floor_pending(db: sqlite3.Connection) -> bool:
    return db.execute("SELECT pending FROM employee_floor").fetchone()[0] == 1


def _maybe_floor(db: sqlite3.Connection) -> int | None:
    if not _floor_pending(db):
        return None
    got = dict(db.execute("SELECT cell, max_emp FROM employee_floor_reports WHERE epoch = ?", (_current(db)[0],)))
    waiting = [c for c in placement_data_cells() if c not in got]
    if waiting:
        log.warning("Cells: no Employee is created until %s report their highest Employee id", ",".join(waiting))
        return None
    top = max(got.values(), default=0)
    local = db.execute("SELECT COALESCE(MAX(id), 0) FROM employees").fetchone()[0]
    db.execute("UPDATE employee_floor SET pending = 0")
    if top >= local:
        db.execute("INSERT INTO employees (id, display_name, is_active, created_at, user_id) VALUES (?, ?, 0, ?, NULL)",
                   (top + 1, FLOOR_NAME, _now()))
    floor = max(top + 1, local)
    log.warning("Cells: Employee id floor %d (highest Cell id %d, control %d); Employees can be created again",
                floor, top, local)
    return floor


def report_max_emp(path: str, cell: str, max_emp: int) -> int | None:
    with contextlib.closing(_connect(path)) as db:
        if not _floor_pending(db):
            return None
        db.execute("BEGIN IMMEDIATE")
        try:
            if not _floor_pending(db):
                db.execute("ROLLBACK")
                return None
            db.execute("INSERT INTO employee_floor_reports (cell, epoch, max_emp, reported_at) VALUES (?, ?, ?, ?)"
                       " ON CONFLICT (cell) DO UPDATE SET max_emp = CASE WHEN epoch = excluded.epoch"
                       " THEN MAX(max_emp, excluded.max_emp) ELSE excluded.max_emp END, epoch = excluded.epoch,"
                       " reported_at = excluded.reported_at", (cell, _current(db)[0], max_emp, _now()))
            floor = _maybe_floor(db)
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return floor


def install(sync_url: str, role: str) -> dict[str, int]:
    with contextlib.closing(_connect(db_path(sync_url))) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            if role == "control":
                db.execute("CREATE TABLE IF NOT EXISTS agency_copy_version (epoch INTEGER NOT NULL,"
                           " version INTEGER NOT NULL, grant_gen INTEGER NOT NULL)")
                db.execute("INSERT INTO agency_copy_version SELECT ?, 1, 1"
                           " WHERE NOT EXISTS (SELECT 1 FROM agency_copy_version)", (int(time.time()),))
                _floor_tables(db)
                n = {"dropped_ro": _sync(db, _RO, {}), "version": _sync(db, _VER, version_triggers(db)),
                     "floor": _sync(db, _FLOOR, floor_triggers())}
                _maybe_floor(db)
            else:
                db.execute("CREATE TABLE IF NOT EXISTS agency_copy_gate (open INTEGER)")
                db.execute("INSERT INTO agency_copy_gate SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM agency_copy_gate)")
                _sections_table(db)
                db.execute("CREATE TABLE IF NOT EXISTS agency_copy_repair (pending INTEGER PRIMARY KEY)")
                db.execute(f"CREATE TABLE IF NOT EXISTS {MISSING} (user_id TEXT PRIMARY KEY, since TEXT NOT NULL)")
                n = {"dropped_version": _sync(db, _VER, {}), "dropped_floor": _sync(db, _FLOOR, {}),
                     "read_only": _sync(db, _RO, read_only_triggers(db))}
                if "users" in _tables(db):
                    db.execute("UPDATE agency_copy_gate SET open = 1")
                    db.execute(f"UPDATE users SET username = '#missing:' || id WHERE id IN (SELECT user_id FROM {MISSING})"
                               " AND username IS NOT '#missing:' || id")
                    db.execute("UPDATE agency_copy_gate SET open = 0")
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return n


def _sections_table(db: sqlite3.Connection) -> None:
    db.execute("CREATE TABLE IF NOT EXISTS agency_copy_sections (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)")
    if "cell_meta" not in _tables(db):
        return
    old = db.execute("SELECT section_sha FROM cell_meta").fetchone()
    if old and old[0]:
        db.execute("DELETE FROM agency_copy_sections")
        db.executemany("INSERT OR IGNORE INTO agency_copy_sections (name, sha256) VALUES (?, ?)",
                       sorted(json.loads(old[0]).items()))
        db.execute("UPDATE cell_meta SET section_sha = NULL")


def bump_epoch(path: str) -> int:
    with contextlib.closing(_connect(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT epoch FROM agency_copy_version").fetchone()[0]
        new = max(int(old) + 1, int(time.time()))
        db.execute("UPDATE agency_copy_version SET epoch = ?", (new,))
        _floor_tables(db)
        db.execute("UPDATE employee_floor SET pending = 1")
        db.execute("DELETE FROM employee_floor_reports")
        db.execute("COMMIT")
    return new


_snap: dict[str, Any] = {}
_hist: dict[tuple[int, int], dict[str, str]] = {}
_asked: dict[str, int] = {}
_cur: tuple[float, tuple[int, int, int] | None] = (0.0, None)
_one_version_read = asyncio.Lock()
_one_snapshot_build = asyncio.Lock()
router = APIRouter()


def _current(db: sqlite3.Connection) -> tuple[int, int, int]:
    e, v, g = db.execute("SELECT epoch, version, grant_gen FROM agency_copy_version").fetchone()
    return int(e), int(v), int(g)


def _dump(rows: list[dict]) -> bytes:
    return json.dumps(rows, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()


def read_snapshot(path: str) -> dict[str, Any]:
    with contextlib.closing(_connect(path)) as db:
        db.execute("BEGIN")
        try:
            epoch, version, grant_gen = _current(db)
            present = _tables(db)
            sections, people = {}, {}
            for t in COPIED:
                if t not in present:
                    continue
                cols = _wire(db, t)
                order = ", ".join(f'"{c}"' for c in _pk(db, t))
                rows = [dict(zip(cols, r)) for r in db.execute(
                    f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{t}" ORDER BY {order}')]
                if t in CONTROL_ONLY_ROWS:
                    col, kept = CONTROL_ONLY_ROWS[t]
                    rows = [r for r in rows if r[col] not in kept]
                for r in rows:
                    if any(isinstance(v, bytes) for v in r.values()):
                        raise ValueError(f"{t}: binary value, not copyable")
                raw = _dump(rows)
                sections[t] = {"sha256": hashlib.sha256(raw).hexdigest(), "raw": raw}
                if t in PEOPLE:
                    kind, col = PEOPLE[t]
                    for r in rows:
                        people.setdefault(f"{GRANTS}{kind}:{r[col]}", {}).setdefault(t, []).append(r)
        finally:
            db.execute("COMMIT")
    sections2 = {t: sec for t, sec in sections.items() if t not in PEOPLE}
    for name in sorted(people):
        raw = _dump(people[name])
        sections2[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "raw": raw}
    shas2 = {n: sec["sha256"] for n, sec in sections2.items()}
    return {"epoch": epoch, "version": version, "grant_gen": grant_gen, "sections": sections,
            "sections2": sections2, "shas2": shas2, "root": root_of(shas2)}


def root_of(shas: dict[str, str]) -> str:
    return hashlib.sha256("\n".join(f"{n}:{shas[n]}" for n in sorted(shas)).encode()).hexdigest()


async def _version(path: str) -> tuple[int, int, int]:
    global _cur
    if _cur[1] is None or time.monotonic() - _cur[0] >= _TICK_S:
        async with _one_version_read:
            if _cur[1] is None or time.monotonic() - _cur[0] >= _TICK_S:
                def read():
                    with contextlib.closing(_connect(path)) as db:
                        return _current(db)
                val = await asyncio.to_thread(read)
                _cur = (time.monotonic(), val)
    return _cur[1]


async def _snapshot(path: str) -> dict[str, Any]:
    cur = await _version(path)
    if _snap.get("key") != cur[:2]:
        async with _one_snapshot_build:
            key = _snap.get("key")
            if key is None or key[0] != cur[0] or key[1] < cur[1]:
                snap = await asyncio.to_thread(read_snapshot, path)
                _snap.clear()
                _snap.update(snap, key=(snap["epoch"], snap["version"]))
                _hist[_snap["key"]] = snap["shas2"]
                while len(_hist) > _HIST_N:
                    del _hist[next(iter(_hist))]
    return _snap


def _keys() -> dict[str, str]:
    out = {}
    for part in os.environ.get("OI_CELL_COPY_KEYS", "").split(","):
        cell, _, digest = part.strip().partition(":")
        if cell and len(digest) == 64:
            out[cell] = digest.lower()
    return out


def matching_digest(token: str, digests: Iterable[str]) -> str | None:
    if not token:
        return None
    got = hashlib.sha256(token.encode()).hexdigest().encode()
    hit = None
    for digest in digests:
        if hmac.compare_digest(got, digest.strip().lower().encode()):
            hit = digest
    return hit


def caller(authorization: str | None) -> str | None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    by_digest = {digest: cell for cell, digest in _keys().items()}
    return by_digest.get(matching_digest(token, by_digest))


def _parse_since(since: str) -> tuple[int, int] | None:
    e, dot, v = since.partition(".")
    return (int(e), int(v)) if dot and e.isdigit() and v.isdigit() else None


def _parse_have(have: str) -> dict[str, str]:
    out = {}
    for part in have.split(","):
        name, _, sha = part.partition(":")
        if name in FIELDS and sha:
            out[name] = sha
    return out


def answer(snap: dict[str, Any], have: dict[str, str]) -> bytes:
    parts = []
    for name, sec in snap["sections"].items():
        rows = b"" if have.get(name) == sec["sha256"] else b',"rows":' + sec["raw"]
        parts.append(json.dumps(name).encode() + b':{"sha256":"' + sec["sha256"].encode() + b'"' + rows + b"}")
    head = json.dumps({"format": FORMAT, "epoch": snap["epoch"], "version": snap["version"],
                       "grant_gen": snap["grant_gen"]}, separators=(",", ":")).encode()
    return head[:-1] + b',"sections":{' + b",".join(parts) + b"}}"


def answer2(snap: dict[str, Any], prev: dict[str, str] | None) -> bytes:
    parts = []
    for name, sec in snap["sections2"].items():
        if prev is None or prev.get(name) != sec["sha256"]:
            parts.append(json.dumps(name).encode() + b':{"sha256":"' + sec["sha256"].encode() + b'","rows":'
                         + sec["raw"] + b"}")
    removed = sorted(set(prev) - set(snap["sections2"])) if prev else []
    head = json.dumps({"format": FORMAT2, "epoch": snap["epoch"], "version": snap["version"],
                       "grant_gen": snap["grant_gen"], "root_sha": snap["root"]}, separators=(",", ":")).encode()
    return (head[:-1] + b',"sections":{' + b",".join(parts) + b'},"removed":'
            + json.dumps(removed, separators=(",", ":")).encode() + b"}")


def _format_for(accept: int) -> int:
    if accept < FORMAT2:
        return FORMAT
    return FORMAT2 if all(_asked.get(c, FORMAT) >= FORMAT2 for c in placement_data_cells()) else FORMAT


@router.get("/fleet/agency-copy")
async def agency_copy(since: str = "0.0", have: str = "", hold: Annotated[float, Query(ge=0, le=HOLD_S)] = HOLD_S,
                      max_emp: Annotated[int | None, Query(ge=0)] = None, accept: int = FORMAT, full: bool = False,
                      authorization: Annotated[str | None, Header()] = None):
    no_store = {"Cache-Control": "no-store"}
    cell = caller(authorization)
    if cell is None:
        return JSONResponse({"detail": "forbidden"}, status_code=403, headers=no_store)
    mine = _parse_since(since)
    if mine is None:
        return JSONResponse({"detail": "since must be <epoch>.<version>"}, status_code=422, headers=no_store)
    from db.engine import sync_database_url
    path = db_path(sync_database_url())
    if max_emp is not None:
        try:
            await asyncio.to_thread(report_max_emp, path, cell, max_emp)
        except Exception:
            log.exception("Cells: %s reported highest Employee id %d but it was not recorded", cell, max_emp)
    _asked[cell] = accept
    deadline = time.monotonic() + (0 if full and accept >= FORMAT2 else hold)
    while (await _version(path))[:2] == mine and time.monotonic() < deadline:
        await asyncio.sleep(_TICK_S)
    snap = await _snapshot(path)
    if _format_for(accept) == FORMAT2:
        prev = None if full else snap["shas2"] if (snap["epoch"], snap["version"]) == mine else _hist.get(mine)
        body = answer2(snap, prev)
    elif (snap["epoch"], snap["version"]) == mine:
        body = json.dumps({"format": FORMAT, "epoch": snap["epoch"], "version": snap["version"],
                           "grant_gen": snap["grant_gen"], "sections": {}}, separators=(",", ":")).encode()
    else:
        body = answer(snap, _parse_have(have))
    return Response(body, media_type="application/json", headers=no_store)


def _local_no_action_refs(db: sqlite3.Connection) -> dict[str, list[tuple[str, str, str]]]:
    refs: dict[str, list[tuple[str, str, str]]] = {}
    for t in _tables(db) - set(COPIED):
        for fk in db.execute(f'PRAGMA foreign_key_list("{t}")'):
            target, src, dst, on_delete = fk[2], fk[3], fk[4], fk[6]
            if target in FIELDS and on_delete.upper() in ("NO ACTION", "RESTRICT"):
                refs.setdefault(target, []).append((t, src, dst or _pk(db, target)[0]))
    return refs


def meta(db: sqlite3.Connection) -> dict[str, Any]:
    e, v, g, conf = db.execute("SELECT copy_epoch, copy_version, grant_gen, confirmed_at FROM cell_meta").fetchone()
    shas = dict(db.execute("SELECT name, sha256 FROM agency_copy_sections"))
    pending = {n for n, sha in shas.items() if n in FIELDS and sha.startswith(_UNMATERIALIZED)}
    repair = db.execute("SELECT 1 FROM agency_copy_repair").fetchone() is not None
    return {"epoch": e, "version": v, "repair_needed": repair, "section_sha": {n: sha.removeprefix(_UNMATERIALIZED) for n, sha in shas.items()},
            "pending": pending, "grant_gen": g, "confirmed_at": conf}


def root_ok(db: sqlite3.Connection, want: str) -> bool:
    mine = meta(db)
    return not mine["pending"] and root_of(mine["section_sha"]) == want


def newer(doc: dict, mine: dict) -> bool:
    if mine["epoch"] is None:
        return True
    if doc["epoch"] != mine["epoch"]:
        return doc["epoch"] > mine["epoch"]
    return doc["version"] > mine["version"]


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


def _mark_missing(db: sqlite3.Connection, doc: dict, changes: dict) -> None:
    at = f"{doc['epoch']}.{doc['version']}"
    changes["owners_missing"] = [uid for uid in sorted(set(changes.get("owners_missing", ()))) if db.execute(
        f"INSERT INTO {MISSING} (user_id, since) VALUES (?, ?) ON CONFLICT DO NOTHING", (uid, at)).rowcount]


def _log_missing(doc: dict, result: dict) -> None:
    for uid in result.get("owners_missing", ()):
        log.warning("agency_copy_owner_missing owner=%s copy=%s.%s: Control no longer lists this owner;"
                    " kept its rows, access denied until a copy lists it again", uid, doc["epoch"], doc["version"])


async def owner_missing(s, ids) -> bool:
    from sqlalchemy import bindparam, text
    q = text(f"SELECT 1 FROM {MISSING} WHERE user_id IN :ids LIMIT 1").bindparams(bindparam("ids", expanding=True))
    return (await s.execute(q, {"ids": sorted(ids)})).first() is not None


def _apply_section(db: sqlite3.Connection, schema: _Schema, t: str, rows: list[dict], refs, changes: dict,
                   scope=None) -> None:
    pk, cols, fill, sql = schema.shape(t)
    only, args = (f' WHERE "{scope[0]}" IS ?', (scope[1],)) if scope else ("", ())
    want = {tuple(r.get(k) for k in pk) for r in rows}
    have = db.execute(f'SELECT {", ".join(pk)} FROM "{t}"{only}', args).fetchall()
    gone = [k for k in have if tuple(k) not in want]
    if t in GRANT_REVOKE:
        cols_r = GRANT_REVOKE[t]
        sel = ", ".join(f'"{c}"' for c in cols_r)
        old = {r[0]: r[1:] for r in db.execute(f'SELECT id, {sel} FROM "{t}"{only}', args)}
        new = {r["id"]: tuple(r.get(c) for c in cols_r) for r in rows}
        changes.setdefault("revoked", []).extend(
            (t, pid) for pid, was in old.items() if pid not in new or new[pid] != was)
    if t == "users":
        # Owner decision keep-and-deny: an older Control's copy never deletes an owner (CASCADE takes Cell rows).
        db.executemany("UPDATE users SET username = '#missing:' || id WHERE id = ?", gone)
        db.executemany(f"DELETE FROM {MISSING} WHERE user_id = ?", [(r["id"],) for r in rows])
        changes.setdefault("owners_missing", []).extend(k[0] for k in gone)
        gone = []
    where = " AND ".join(f'"{k}" IS ?' for k in pk)
    for key in gone:
        pinned = any(db.execute(f'SELECT 1 FROM "{src_t}" WHERE "{src}" IN (SELECT "{dst}" FROM "{t}" WHERE {where})'
                                ' LIMIT 1', key).fetchone() for src_t, src, dst in refs.get(t, ()))
        if t == "employees":
            db.execute(f'UPDATE "{t}" SET is_active = 0, chatter_id = NULL WHERE {where}', key)
        elif not pinned:
            db.execute(f'DELETE FROM "{t}" WHERE {where}', key)
    if t in _ACCOUNT_FK:
        for aid in {r["account_id"] for r in rows if r.get("account_id") is not None}:
            db.execute("INSERT INTO accounts (id, is_active_default) SELECT ?, 0"
                       " WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE id = ?)", (aid, aid))
    db.executemany(sql, ([r.get(c) for c in cols] + [_FILL[c](r) for c in fill] for r in rows))


def _person(name: str) -> tuple[str, Any]:
    kind, _, pid = name[len(GRANTS):].partition(":")
    if kind not in {k for k, _c in PEOPLE.values()} or not pid:
        raise ValueError(f"unknown section {name!r}")
    return kind, int(pid) if kind == "employee" else pid


def _apply_person(db: sqlite3.Connection, schema: _Schema, name: str, rows: dict, refs, changes: dict,
                  touched: set) -> None:
    kind, pid = _person(name)
    present = schema.tables
    for t in rows:
        if t not in present and rows[t]:
            raise ValueError(f"{name}: missing Cell table {t}")
        if PEOPLE.get(t, ("",))[0] != kind or any(r.get(PEOPLE[t][1]) != pid for r in rows[t]):
            raise ValueError(f"{name}: rows of {t} are not this person's")
    for t, (k, col) in PEOPLE.items():
        if k == kind and t in present:
            _apply_section(db, schema, t, rows.get(t, []), refs, changes, scope=(col, pid))
            touched.add(t)


def _local_people(db: sqlite3.Connection) -> set[str]:
    present = _tables(db)
    return {f"{GRANTS}{kind}:{v}" for t, (kind, col) in PEOPLE.items() if t in present
            for (v,) in db.execute(f'SELECT DISTINCT "{col}" FROM "{t}"')}


class _RootMismatch(Exception):
    pass


def _apply_tx(db: sqlite3.Connection, doc: dict, repair: bool) -> dict[str, Any]:
    mine = meta(db)
    same = (doc["epoch"], doc["version"]) == (mine["epoch"], mine["version"])
    if (mine["repair_needed"] and not repair) or not (newer(doc, mine) or (repair and same)):
        return {"applied": False, "changed": [], "root_ok": None}
    sections = doc.get("sections") or {}
    previous = mine["section_sha"]
    if repair and doc.get("format") != FORMAT2 and not sections:
        raise ValueError("full format-1 answer lacks sections")
    if doc.get("format") == FORMAT2:
        expected_root = doc["root_sha"]
        if not isinstance(expected_root, str):
            raise _RootMismatch
        full = root_of({n: s["sha256"] for n, s in sections.items()}) == expected_root
        if repair and not full:
            raise _RootMismatch
        drop = set(doc.get("removed") or []) - set(sections)
        if full:
            drop |= (set(previous) | _local_people(db)) - set(sections)
        drop_people = sorted(n for n in drop if n.startswith(GRANTS))
        changed = sorted(n for n, sec in sections.items() if repair
                         or sec["sha256"] != previous.get(n) or n in mine["pending"])
        for n in changed:
            if n in PEOPLE:
                raise ValueError(f"section {n!r} must come per person")
    else:
        expected_root = None
        drop = set(previous) - set(sections)
        drop_people = []
        changed = [n for n in COPIED if n in sections
                   and (repair or sections[n]["sha256"] != previous.get(n) or n in mine["pending"])]
    for n in changed:
        if not isinstance(sections[n].get("rows"), dict if n.startswith(GRANTS) else list):
            raise ValueError(f"answer lacks rows for changed section {n}")
    changes: dict[str, Any] = {}
    touched: set[str] = set()
    shas = []
    db.execute("PRAGMA defer_foreign_keys=ON")
    db.execute("UPDATE agency_copy_gate SET open = 1")
    refs = _local_no_action_refs(db)
    schema = _Schema(db)
    for n in drop_people:
        _apply_person(db, schema, n, {}, refs, changes, touched)
    for n in changed:
        rows = sections[n]["rows"]
        sha = sections[n]["sha256"]
        if n.startswith(GRANTS):
            _apply_person(db, schema, n, rows, refs, changes, touched)
        elif n in COPIED:
            _apply_section(db, schema, n, rows, refs, changes)
            touched.add(n)
        else:
            sha = _UNMATERIALIZED + sha
        shas.append((n, sha))
    _mark_missing(db, doc, changes)
    db.executemany("DELETE FROM agency_copy_sections WHERE name = ?", [(n,) for n in sorted(drop)])
    db.executemany("INSERT INTO agency_copy_sections (name, sha256) VALUES (?, ?) ON CONFLICT (name)"
                   " DO UPDATE SET sha256 = excluded.sha256", shas)
    if expected_root is not None and not root_ok(db, expected_root):
        raise _RootMismatch
    if repair:
        db.execute("DELETE FROM agency_copy_repair")
    now = _now()
    db.execute("UPDATE cell_meta SET copy_epoch = ?, copy_version = ?, applied_at = ?, confirmed_at = ?, grant_gen = ?",
               (doc["epoch"], doc["version"], now, now, doc["grant_gen"]))
    db.execute("UPDATE agency_copy_gate SET open = 0")
    return {"applied": True, "changed": changed, "removed": sorted(drop), "tables": sorted(touched),
            "root_ok": True, "confirmed_at": now, **changes}


def apply(path: str, doc: dict, repair: bool = False) -> dict[str, Any]:
    with contextlib.closing(_connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("SAVEPOINT copy_rows")
        try:
            result = _apply_tx(db, doc, repair)
        except _RootMismatch:
            db.execute("ROLLBACK TO copy_rows")
            db.execute("INSERT OR IGNORE INTO agency_copy_repair VALUES (1)")
            return {"applied": False, "changed": [], "root_ok": False}
    if result["applied"]:
        _note(result.pop("confirmed_at"), doc["grant_gen"])
    return result


def confirm(path: str, doc: dict) -> bool:
    with contextlib.closing(_connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        mine = meta(db)
        if mine["repair_needed"] or (doc["epoch"], doc["version"]) != (mine["epoch"], mine["version"]):
            return False
        if mine["pending"] or (doc.get("format") == FORMAT2 and not root_ok(db, doc["root_sha"])):
            db.execute("INSERT OR IGNORE INTO agency_copy_repair VALUES (1)")
            return False
        now = _now()
        db.execute("UPDATE cell_meta SET confirmed_at = ?, grant_gen = ?", (now, doc["grant_gen"]))
    _note(now, doc["grant_gen"])
    return True


def _ts(stamp: str | None) -> float | None:
    return datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc).timestamp() if stamp else None


def _note(confirmed_at: str | None, gen: int | None) -> None:
    global _held
    _held = (_ts(confirmed_at), gen)


def load_confirmed(path: str) -> float | None:
    m = meta_at(path)
    _note(m["confirmed_at"], m["grant_gen"])
    return grant_age_s()


def max_grant_age_s() -> float:
    return float(os.environ.get("OI_CELL_MAX_GRANT_AGE_S") or 900)


def grant_age_s(now: float | None = None) -> float | None:
    at = _held[0]
    return None if at is None else (now if now is not None else time.time()) - at


def aged(now: float | None = None) -> bool:
    age = grant_age_s(now)
    return age is None or age > max_grant_age_s()


def held_grant_gen() -> int | None:
    return _held[1]


async def watch_grant_age(tick_s: float = 1.0) -> None:
    import events
    was = None
    while True:
        now_aged = aged()
        if now_aged:
            events.cut_streams()
        if now_aged != was:
            age = grant_age_s()
            if now_aged:
                log.error("Cells: GRANT AGE EXCEEDED (%s, max %.0f s): every human request answers 503 %s and"
                          " open streams end until control confirms the copy",
                          "no confirmed copy" if age is None else f"{age:.0f} s since control confirmed",
                          max_grant_age_s(), GRANT_AGE_MSG)
            elif was is not None:
                log.warning("Cells: control confirmed the Agency copy again; human requests served")
            was = now_aged
        await asyncio.sleep(tick_s)


def grant_gen(path: str) -> int | None:
    with contextlib.closing(_connect(path)) as db:
        return meta(db)["grant_gen"]


def _notify_apply(path: str, changed: set[str], revoked: set[tuple[str, str]]) -> None:
    import chatter_identity_cache
    import events
    grants = changed & (set(GRANT_ANY) | set(GRANT_REVOKE) | {"employees", "employee_groups", "shifts"})
    if grants or revoked:
        chatter_identity_cache.invalidate()
    for t, pid in revoked:
        events.publish_state("sessions_revoked", agency=events.sessions_audience(t[:-1], pid))
    if grants:
        try:
            owners = _owners(path)
        except Exception:
            log.exception("Agency copy committed; grant cache cleared but permissions_changed not published")
            return
        for owner in owners:
            events.publish_state("permissions_changed", agency=owner)
            events.publish_state("assignment_changed", agency=owner)


def _owners(path: str) -> list[str]:
    with contextlib.closing(_connect(path)) as db:
        return [r[0] for r in db.execute("SELECT id FROM users")]


async def _reload_runtime(path: str, changed: set[str]) -> None:
    if "user_settings" in changed:
        import split_inbox
        for owner in _owners(path):
            with contextlib.suppress(Exception):
                await split_inbox.default_changed(owner)
        changed.remove("user_settings")
    if "runtime_switches" in changed:
        import runtime_switches
        await runtime_switches.load()
        changed.remove("runtime_switches")
    if "push_subscriptions" in changed:
        await _reload_push(path)
        changed.remove("push_subscriptions")


async def _reload_push(path: str) -> None:
    import push_send
    with contextlib.closing(_connect(path)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM push_subscriptions").fetchall()
    keep = set()
    for r in rows:
        if push_send.pd.endpoint_allowed(r["endpoint"], push_send.HOSTS):
            push_send.upsert(push_send.sub_from_row(types.SimpleNamespace(**dict(r))))
            keep.add(r["id"])
    for sid in list(push_send._subs):
        if sid not in keep:
            push_send._subs.pop(sid, None)


def _said(names: list[str]) -> str:
    return ",".join(names) if len(names) <= 8 else f"{len(names)} sections ({','.join(names[:3])},...)"


@dataclass
class _RuntimeReload:
    tables: set[str] = field(default_factory=set)
    next_at: float = 0.0
    delay: float = 0.5

    def add(self, result: dict) -> None:
        self.tables.update({"user_settings", "runtime_switches", "push_subscriptions"}.intersection(result["tables"]))

    async def run_due(self, path: str) -> None:
        if not self.tables or time.monotonic() < self.next_at:
            return
        try:
            await _reload_runtime(path, self.tables)
        except Exception:
            log.exception("Agency copy committed; runtime reload failed and will retry in %.1fs", self.delay)
            self.next_at = time.monotonic() + self.delay
            self.delay = min(self.delay * 2, 5.0)
        else:
            self.next_at, self.delay = 0.0, 0.5

    def hold_cap(self) -> float:
        cap = min(HOLD_S, max_grant_age_s() / 4)
        if self.tables:
            return min(cap, max(0.0, self.next_at - time.monotonic()))
        return cap


def _applied(path: str, doc: dict, result: dict, pending: _RuntimeReload, previous_epoch: int | None) -> None:
    if not result["applied"]:
        return
    pending.add(result)
    _log_missing(doc, result)
    _notify_apply(path, set(result["tables"]), result.get("revoked", set()))
    log.info("agency copy %s.%s applied (grant_gen %s): %s", doc["epoch"], doc["version"], doc["grant_gen"],
             _said(result["changed"]) or "no section changed")
    if previous_epoch is not None and doc["epoch"] > previous_epoch:
        import creator_reservations
        creator_reservations.reseed_activations()


async def poll_forever(path: str) -> None:
    import httpx
    url = os.environ["OI_CELL_CONTROL_URL"].rstrip("/") + "/fleet/agency-copy"
    key = os.environ.get("OI_CELL_COPY_KEY", "")
    backoff = 0.5
    failed_full = None
    pending = _RuntimeReload()
    async with httpx.AsyncClient(timeout=HOLD_S + 15, headers={"Authorization": f"Bearer {key}"}) as client:
        while True:
            full = False
            await pending.run_due(path)
            try:
                mine, max_emp = await asyncio.to_thread(lambda: (meta_at(path), max_employee_id(path)))
                since = f"{mine['epoch'] or 0}.{mine['version'] or 0}"
                have = ",".join(f"{t}:{s}" for t, s in sorted(mine["section_sha"].items())
                                if t in FIELDS and t not in mine["pending"])
                params = {"since": since, "have": have, "max_emp": max_emp, "accept": FORMAT2,
                          "hold": pending.hold_cap()}
                full = mine["repair_needed"] and failed_full is None
                if full:
                    params |= {"since": "0.0", "have": "", "full": 1, "hold": 0}
                elif failed_full is not None:
                    params["since"] = f"{failed_full[0]}.{failed_full[1]}"
                r = await client.get(url, params=params)
                r.raise_for_status()
                doc = r.json()
                at = (doc["epoch"], doc["version"])
                same = at == (mine["epoch"], mine["version"])
                if failed_full is not None:
                    if at == failed_full:
                        await asyncio.sleep(5)
                    else:
                        failed_full = None
                    continue
                if full or not same:
                    result = await asyncio.to_thread(apply, path, doc, full)
                    ok = result["root_ok"]
                    if ok is None:
                        log.warning("agency copy: control answered older %s.%s than ours %s; kept ours",
                                    doc["epoch"], doc["version"], since)
                        await asyncio.sleep(5)
                        continue
                    _applied(path, doc, result, pending, mine["epoch"])
                else:
                    ok = await asyncio.to_thread(confirm, path, doc)
                if ok is False:
                    if full:
                        failed_full = at
                        log.error("AGENCY COPY ROOT MISMATCH after a full copy at %s.%s; not confirmed", *at)
                    else:
                        log.warning("agency copy root hash differs from control at %s.%s; fetching the full copy", *at)
                backoff = 0.5
            except asyncio.CancelledError:
                raise
            except Exception as e:
                delay = backoff
                backoff = min(backoff * 2, 300.0 if full else 5.0)
                log.error("AGENCY COPY NOT APPLIED: %s: %s; kept the old version, retrying in %.1fs",
                          type(e).__name__, e, delay)
                await asyncio.sleep(delay)


def meta_at(path: str) -> dict[str, Any]:
    with contextlib.closing(_connect(path)) as db:
        return meta(db)


def max_employee_id(path: str) -> int:
    with contextlib.closing(_connect(path)) as db:
        return int(db.execute("SELECT COALESCE(MAX(id), 0) FROM employees").fetchone()[0])


def log_read_only_hits(sync_engine) -> None:
    from sqlalchemy import event

    @event.listens_for(sync_engine, "handle_error")
    def _hit(ctx) -> None:
        if READ_ONLY_MSG in str(ctx.original_exception):
            log.error("agency copy is read-only on this Cell: %s", ctx.original_exception, stack_info=True)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--bump-epoch":
        sys.exit("usage: python service/agency_copy.py --bump-epoch <control relay.db>")
    print(f"AGENCY-COPY-EPOCH {bump_epoch(sys.argv[2])}")
