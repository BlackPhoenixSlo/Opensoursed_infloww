from __future__ import annotations

import contextlib
import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import client_addr
import llm_client
from automations._common import DEFAULT_MODEL
from llm_client import LLMCapExceeded, LLMConfigError, LLMHTTPError, LLMKeyError, key_error_payload
from support_photos import Photo, capped_form, form_text, photo_response, read_photos, reencode

log = logging.getLogger("of-relay.support_hub")

router = APIRouter(include_in_schema=False)

PREFIX = "/support"
API = f"{PREFIX}/api"
COOKIE = "support_hub_session"
SESSION_S = 14 * 24 * 3600
MAX_TEXT = 4000
MAX_FIELD = 200
FAIL_LIMIT = 5
GLOBAL_FAIL_LIMIT = 30
FAIL_WINDOW_S = 600.0
SEND_LIMIT = 20
SEND_WINDOW_S = 600
PURPOSE = "support_summary"
DIGEST_MAX_CHARS = 60_000
DIGEST_MSG_CHARS = 1_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
  id INTEGER PRIMARY KEY,
  instance TEXT NOT NULL,
  user_key TEXT NOT NULL,
  agency_id TEXT NOT NULL DEFAULT '',
  agency_name TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT '',
  last_at TEXT NOT NULL,
  owner_read_id INTEGER NOT NULL DEFAULT 0,
  user_read_id INTEGER NOT NULL DEFAULT 0,
  UNIQUE (instance, user_key));
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  thread_id INTEGER NOT NULL REFERENCES threads(id),
  sender TEXT NOT NULL CHECK (sender IN ('user', 'support')),
  text TEXT NOT NULL,
  at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS messages_thread ON messages(thread_id, id);
CREATE TABLE IF NOT EXISTS photos (
  id INTEGER PRIMARY KEY,
  message_id INTEGER NOT NULL REFERENCES messages(id),
  w INTEGER NOT NULL,
  h INTEGER NOT NULL,
  data BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS photos_message ON photos(message_id);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, exp INTEGER NOT NULL);
"""

_NEWEST = "(SELECT MAX(id) FROM messages WHERE thread_id = t.id) DESC, t.id DESC"

_ready: set[str] = set()
_secrets: dict[str, bytes] = {}
_fails: dict[str, deque[float]] = {}
_all_fails: deque[float] = deque()
_fail_lock = threading.Lock()
_clock = time.time


def _password() -> str:
    return os.environ.get("SUPPORT_HUB_PASSWORD", "").strip()


def enabled() -> bool:
    return bool(_password())


def owns(path: str) -> bool:
    return enabled() and (path == PREFIX or path.startswith(PREFIX + "/"))


def _db_path() -> str:
    return os.environ.get("SUPPORT_HUB_DB") or str(Path(__file__).with_name("data") / "support_hub.db")


def _connect() -> sqlite3.Connection:
    path = _db_path()
    if path not in _ready:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    if path not in _ready:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(_SCHEMA)
        _ready.add(path)
    return db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require_enabled() -> None:
    if not enabled():
        raise HTTPException(status_code=404, detail="Not Found")


def _secret() -> bytes:
    path = _db_path()
    if path not in _secrets:
        with contextlib.closing(_connect()) as db:
            db.execute("INSERT OR IGNORE INTO meta (k, v) VALUES ('session_secret', ?)", (secrets.token_bytes(32),))
            _secrets[path] = bytes(db.execute("SELECT v FROM meta WHERE k = 'session_secret'").fetchone()["v"])
    return _secrets[path]


def _session_key() -> bytes:
    # Password hash mixed in: changing the password signs every owner session out.
    pw = hashlib.sha256(_password().encode()).digest()
    return hmac.new(_secret(), b"support-hub-session\0" + pw, hashlib.sha256).digest()


def _sign(sid: str, exp: int) -> str:
    return hmac.new(_session_key(), f"{sid}.{exp}".encode(), hashlib.sha256).hexdigest()


def _new_session() -> str:
    sid = secrets.token_hex(16)
    exp = int(_clock()) + SESSION_S
    with contextlib.closing(_connect()) as db:
        db.execute("DELETE FROM sessions WHERE exp <= ?", (int(_clock()),))
        db.execute("INSERT INTO sessions (id, exp) VALUES (?, ?)", (sid, exp))
    return f"{sid}.{exp}.{_sign(sid, exp)}"


def _parse(value: str | None) -> tuple[str, int] | None:
    parts = (value or "").split(".")
    if len(parts) != 3:
        return None
    sid, exp_s, sig = parts
    if len(sid) != 32 or not all(c in "0123456789abcdef" for c in sid):
        return None
    if not (exp_s.isascii() and exp_s.isdigit()) or len(exp_s) > 12:
        return None
    exp = int(exp_s)
    if not hmac.compare_digest(sig.encode(), _sign(sid, exp).encode()) or exp <= _clock():
        return None
    return sid, exp


def _session_ok(value: str | None) -> bool:
    parsed = _parse(value)
    if parsed is None:
        return False
    with contextlib.closing(_connect()) as db:
        return db.execute("SELECT 1 FROM sessions WHERE id = ? AND exp = ?", parsed).fetchone() is not None


def _revoke(value: str | None) -> None:
    parsed = _parse(value)
    if parsed is not None:
        with contextlib.closing(_connect()) as db:
            db.execute("DELETE FROM sessions WHERE id = ?", (parsed[0],))


def _too_many() -> JSONResponse:
    return JSONResponse({"detail": "Too many tries. Wait 10 minutes."}, status_code=429,
                        headers={"Retry-After": str(int(FAIL_WINDOW_S))})


def _owner(request: Request) -> None:
    _require_enabled()
    value = request.cookies.get(COOKIE)
    if not value:
        raise HTTPException(status_code=401, detail="sign in required")
    if _session_ok(value):
        return
    ip = str(client_addr.client_address(request))
    if not _reserve(ip, _clock()):
        log.warning("support hub: cookie checks throttled addr=%s", ip)
        raise HTTPException(status_code=429, detail="Too many tries. Wait 10 minutes.",
                            headers={"Retry-After": str(int(FAIL_WINDOW_S))})
    log.warning("support hub: bad session cookie addr=%s", ip)
    raise HTTPException(status_code=401, detail="sign in required")


def _instance(request: Request) -> None:
    _require_enabled()
    token = os.environ.get("SUPPORT_HUB_TOKEN", "").strip()
    auth = request.headers.get("authorization", "")
    given = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    if not token or not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(status_code=401, detail="bad token")


def _prune(q: deque[float], now: float) -> None:
    while q and q[0] <= now - FAIL_WINDOW_S:
        q.popleft()


def _reserve(ip: str, now: float) -> bool:
    with _fail_lock:
        q = _fails.setdefault(ip, deque())
        _prune(q, now)
        _prune(_all_fails, now)
        if len(q) >= FAIL_LIMIT or len(_all_fails) >= GLOBAL_FAIL_LIMIT:
            return False
        q.append(now)
        _all_fails.append(now)
        return True


def _release(ip: str, now: float) -> None:
    with _fail_lock:
        q = _fails.get(ip)
        if q is not None:
            with contextlib.suppress(ValueError):
                q.remove(now)
            if not q:
                _fails.pop(ip, None)
        with contextlib.suppress(ValueError):
            _all_fails.remove(now)


def _record_fail(ip: str, now: float) -> None:
    with _fail_lock:
        _fails.setdefault(ip, deque()).append(now)
        _all_fails.append(now)


def reset_throttle() -> None:
    with _fail_lock:
        _fails.clear()
        _all_fails.clear()


def _clip(text: str, limit: int = MAX_FIELD) -> str:
    return (text or "").strip()[:limit]


def _message_rows(db: sqlite3.Connection, thread_id: int) -> list[dict[str, Any]]:
    own = not db.in_transaction
    if own:
        db.execute("BEGIN")
    try:
        rows = [{**dict(r), "photos": []} for r in db.execute(
            "SELECT id, sender, text, at FROM (SELECT id, sender, text, at FROM messages WHERE thread_id = ? "
            "ORDER BY id DESC LIMIT 500) ORDER BY id", (thread_id,)).fetchall()]
        pics = db.execute("SELECT p.id, p.message_id, p.w, p.h FROM photos p JOIN messages m "
                          "ON m.id = p.message_id WHERE m.thread_id = ? AND m.id BETWEEN ? AND ? ORDER BY p.id",
                          (thread_id, rows[0]["id"], rows[-1]["id"])).fetchall() if rows else []
    finally:
        if own:
            db.execute("COMMIT")
    by_id = {r["id"]: r for r in rows}
    for p in pics:
        if p["message_id"] in by_id:
            by_id[p["message_id"]]["photos"].append({"id": p["id"], "w": p["w"], "h": p["h"]})
    return rows


def _thread_id(db: sqlite3.Connection, instance: str, user_key: str) -> int | None:
    row = db.execute("SELECT id FROM threads WHERE instance = ? AND user_key = ?",
                     (instance, user_key)).fetchone()
    return row["id"] if row else None


def _add_message(db: sqlite3.Connection, thread_id: int, sender: str, text: str,
                 photos: Sequence[Photo] = ()) -> None:
    at = _now()
    mid = db.execute("INSERT INTO messages (thread_id, sender, text, at) VALUES (?, ?, ?, ?)",
                     (thread_id, sender, text, at)).lastrowid
    for data, w, h in photos:
        db.execute("INSERT INTO photos (message_id, w, h, data) VALUES (?, ?, ?, ?)", (mid, w, h, data))
    db.execute("UPDATE threads SET last_at = ? WHERE id = ?", (at, thread_id))


def _db_full() -> bool:
    try:
        cap = float(os.environ.get("SUPPORT_HUB_MAX_DB_GB", "") or 2) * 1024 ** 3
    except ValueError:
        cap = 2 * 1024 ** 3
    path = _db_path()
    used = sum(os.path.getsize(p) for p in (path, path + "-wal") if os.path.exists(p))
    return used > cap


async def _form_message(request: Request, who_fields: Sequence[str] = ()) -> tuple[dict[str, str], str, list[bytes]]:
    form = await capped_form(request, max_fields=1 + len(who_fields))
    try:
        who = {k: form_text(form, k, MAX_FIELD) for k in who_fields}
        text = form_text(form, "text", MAX_TEXT).strip()
        raw = await read_photos(form)
    finally:
        await form.close()
    if not text and not raw:
        raise HTTPException(status_code=400, detail="empty message")
    return who, text, raw


async def _photos(raw: Sequence[bytes]) -> list[Photo]:
    if raw and await run_in_threadpool(_db_full):
        raise HTTPException(status_code=507, detail="Photo storage is full — send text for now.")
    return [await reencode(r) for r in raw]


class Who(BaseModel):
    instance: str = Field(..., min_length=1, max_length=MAX_FIELD)
    user_key: str = Field(..., min_length=1, max_length=MAX_FIELD)


class Ingest(Who):
    agency_id: str = Field("", max_length=MAX_FIELD)
    agency_name: str = Field("", max_length=MAX_FIELD)
    name: str = Field("", max_length=MAX_FIELD)
    role: str = Field("", max_length=MAX_FIELD)
    text: str = Field(..., min_length=1, max_length=MAX_TEXT)


class Text(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT)


class Login(BaseModel):
    password: str = Field(..., max_length=500)


def _require_text(text: str) -> str:
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty message")
    return text


def _over_send_limit(db: sqlite3.Connection, tid: int | None) -> bool:
    if tid is None:
        return False
    since = (datetime.now(timezone.utc) - timedelta(seconds=SEND_WINDOW_S)).isoformat(timespec="seconds")
    return db.execute("SELECT COUNT(*) FROM messages WHERE thread_id = ? AND sender = 'user' AND at > ?",
                      (tid, since)).fetchone()[0] >= SEND_LIMIT


def _check_send_limit(who: dict[str, str]) -> None:
    with contextlib.closing(_connect()) as db:
        if _over_send_limit(db, _thread_id(db, _clip(who["instance"]), _clip(who["user_key"]))):
            raise HTTPException(status_code=429, detail="send limit")


def _ingest(who: dict[str, str], text: str, photos: Sequence[Photo] = ()) -> dict[str, Any]:
    with contextlib.closing(_connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                "INSERT INTO threads (instance, user_key, agency_id, agency_name, name, role, last_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (instance, user_key) DO UPDATE SET "
                "agency_id = excluded.agency_id, agency_name = excluded.agency_name, "
                "name = excluded.name, role = excluded.role",
                (_clip(who["instance"]), _clip(who["user_key"]), _clip(who["agency_id"]),
                 _clip(who["agency_name"]), _clip(who["name"]), _clip(who["role"]), _now()))
            tid = _thread_id(db, _clip(who["instance"]), _clip(who["user_key"]))
            assert tid is not None
            if _over_send_limit(db, tid):
                raise HTTPException(status_code=429, detail="send limit")
            _add_message(db, tid, "user", text, photos)
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        return {"messages": _message_rows(db, tid)}


WHO_FIELDS = ("instance", "user_key", "agency_id", "agency_name", "name", "role")


@router.post(f"{API}/instance/messages")
def instance_ingest(request: Request, body: Ingest = Body(...)) -> dict[str, Any]:
    _instance(request)
    text = _require_text(body.text)
    return _ingest(body.model_dump(include=set(WHO_FIELDS)), text)


@router.post(f"{API}/instance/messages/upload")
async def instance_ingest_upload(request: Request) -> dict[str, Any]:
    _instance(request)
    who, text, raw = await _form_message(request, WHO_FIELDS)
    if not who["instance"].strip() or not who["user_key"].strip():
        raise HTTPException(status_code=400, detail="instance and user_key required")
    await run_in_threadpool(_check_send_limit, who)
    return await run_in_threadpool(_ingest, who, text, await _photos(raw))


@router.get(API + "/instance/photos/{photo_id}")
def instance_photo(request: Request, photo_id: int, instance: str = Query(..., max_length=MAX_FIELD),
                   user_key: str = Query(..., max_length=MAX_FIELD)) -> Response:
    _instance(request)
    with contextlib.closing(_connect()) as db:
        row = db.execute("SELECT p.data FROM photos p JOIN messages m ON m.id = p.message_id "
                         "JOIN threads t ON t.id = m.thread_id WHERE p.id = ? AND t.instance = ? "
                         "AND t.user_key = ?", (photo_id, _clip(instance), _clip(user_key))).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no such photo")
    return photo_response(row["data"])


@router.get(f"{API}/instance/thread")
def instance_thread(request: Request, instance: str = Query(..., max_length=MAX_FIELD),
                    user_key: str = Query(..., max_length=MAX_FIELD)) -> dict[str, Any]:
    _instance(request)
    with contextlib.closing(_connect()) as db:
        tid = _thread_id(db, _clip(instance), _clip(user_key))
        return {"messages": _message_rows(db, tid) if tid is not None else []}


@router.get(f"{API}/instance/unread")
def instance_unread(request: Request, instance: str = Query(..., max_length=MAX_FIELD),
                    user_key: str = Query(..., max_length=MAX_FIELD)) -> dict[str, Any]:
    _instance(request)
    with contextlib.closing(_connect()) as db:
        row = db.execute(
            "SELECT COUNT(m.id) AS n FROM threads t JOIN messages m ON m.thread_id = t.id "
            "WHERE t.instance = ? AND t.user_key = ? AND m.sender = 'support' AND m.id > t.user_read_id",
            (_clip(instance), _clip(user_key))).fetchone()
        return {"unread": int(row["n"]) if row else 0}


@router.post(f"{API}/instance/read")
def instance_read(request: Request, body: Who = Body(...)) -> dict[str, Any]:
    _instance(request)
    with contextlib.closing(_connect()) as db:
        db.execute(
            "UPDATE threads SET user_read_id = COALESCE((SELECT MAX(id) FROM messages "
            "WHERE thread_id = threads.id), 0) WHERE instance = ? AND user_key = ?",
            (_clip(body.instance), _clip(body.user_key)))
    return {"ok": True}


@router.post(f"{API}/login")
def login(request: Request, body: Login = Body(...)) -> JSONResponse:
    _require_enabled()
    ip = str(client_addr.client_address(request))
    now = _clock()
    if not _reserve(ip, now):
        log.warning("support hub: login throttled addr=%s", ip)
        return _too_many()
    if not hmac.compare_digest(body.password.encode(), _password().encode()):
        log.warning("support hub: wrong password addr=%s", ip)
        return JSONResponse({"detail": "Wrong password."}, status_code=401)
    _release(ip, now)
    with _fail_lock:
        _fails.pop(ip, None)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, _new_session(), max_age=SESSION_S, path=PREFIX,
                    httponly=True, secure=True, samesite="strict")
    return resp


@router.post(f"{API}/logout")
def logout(request: Request) -> JSONResponse:
    _require_enabled()
    _revoke(request.cookies.get(COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path=PREFIX, httponly=True, secure=True, samesite="strict")
    return resp


@router.get(f"{API}/threads")
def owner_threads(request: Request) -> dict[str, Any]:
    _owner(request)
    with contextlib.closing(_connect()) as db:
        rows = db.execute(
            "SELECT t.id, t.instance, t.agency_id, t.agency_name, t.name, t.role, t.last_at, "
            "(SELECT text FROM messages WHERE thread_id = t.id ORDER BY id DESC LIMIT 1) AS last_text, "
            "(SELECT sender FROM messages WHERE thread_id = t.id ORDER BY id DESC LIMIT 1) AS last_sender, "
            "EXISTS (SELECT 1 FROM messages WHERE thread_id = t.id AND sender = 'user' "
            "AND id > t.owner_read_id) AS unread "
            "FROM threads t ORDER BY " + _NEWEST).fetchall()
    return {"threads": [{**dict(r), "unread": bool(r["unread"])} for r in rows]}


def _thread_row(db: sqlite3.Connection, thread_id: int) -> dict[str, Any]:
    row = db.execute("SELECT id, instance, agency_id, agency_name, name, role, last_at FROM threads "
                     "WHERE id = ?", (thread_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no such thread")
    return dict(row)


def _owner_thread(db: sqlite3.Connection, thread_id: int) -> dict[str, Any]:
    return {"thread": _thread_row(db, thread_id), "messages": _message_rows(db, thread_id)}


@router.get(API + "/threads/{thread_id}")
def owner_thread(request: Request, thread_id: int) -> dict[str, Any]:
    _owner(request)
    with contextlib.closing(_connect()) as db:
        out = _owner_thread(db, thread_id)
        if out["messages"]:
            db.execute("UPDATE threads SET owner_read_id = MAX(owner_read_id, ?) WHERE id = ?",
                       (out["messages"][-1]["id"], thread_id))
    return out


def _reply(thread_id: int, text: str, photos: Sequence[Photo] = ()) -> dict[str, Any]:
    with contextlib.closing(_connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            _thread_row(db, thread_id)
            _add_message(db, thread_id, "support", text, photos)
            db.execute("UPDATE threads SET owner_read_id = (SELECT MAX(id) FROM messages "
                       "WHERE thread_id = ?) WHERE id = ?", (thread_id, thread_id))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        return _owner_thread(db, thread_id)


def _require_thread(thread_id: int) -> None:
    with contextlib.closing(_connect()) as db:
        _thread_row(db, thread_id)


@router.post(API + "/threads/{thread_id}/reply")
def owner_reply(request: Request, thread_id: int, body: Text = Body(...)) -> dict[str, Any]:
    _owner(request)
    text = _require_text(body.text)
    return _reply(thread_id, text)


@router.post(API + "/threads/{thread_id}/reply/upload")
async def owner_reply_upload(request: Request, thread_id: int) -> dict[str, Any]:
    _owner(request)
    _, text, raw = await _form_message(request)
    await run_in_threadpool(_require_thread, thread_id)
    return await run_in_threadpool(_reply, thread_id, text, await _photos(raw))


@router.get(API + "/photos/{photo_id}")
def owner_photo(request: Request, photo_id: int) -> Response:
    _owner(request)
    with contextlib.closing(_connect()) as db:
        row = db.execute("SELECT data FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no such photo")
    return photo_response(row["data"])


SUMMARY_SYSTEM = """\
You read messages that users of a CRM for OnlyFans agencies sent to the product team \
through its in-app Support chat. The users are agency owners, admins and chatters, \
across several agencies and installs. Find what they say is missing, what blocks or \
annoys them, and what they want added or changed.

Group the points into themes. For each theme write:
- a short title
- how many distinct users raised it (count users, not messages)
- one short quote, copied word for word from one user message

Order themes by that count, highest first; on a tie, put whatever blocks work first. \
Ignore greetings, thanks and the team's own replies, except to understand what a user \
answered. Never invent a theme or a quote. If the messages say nothing about missing, \
blocking or wanted things, say that in one line. Plain text, no tables."""

SUMMARY_HEAD = """\
Support threads, newest first. Each opens with a header line naming the user, their \
role, agency and install. "User:" lines are theirs; "Team:" lines are our replies."""


def _digest_input() -> tuple[str, int, int]:
    with contextlib.closing(_connect()) as db:
        threads = db.execute("SELECT id, instance, agency_name, name, role, user_key FROM threads t "
                             "ORDER BY " + _NEWEST).fetchall()
        blocks: list[str] = []
        used = 0
        for t in threads:
            msgs = db.execute("SELECT sender, text, (SELECT COUNT(*) FROM photos WHERE message_id = m.id) AS n "
                              "FROM messages m WHERE thread_id = ? ORDER BY id DESC LIMIT 40",
                              (t["id"],)).fetchall()[::-1]
            if not any(m["sender"] == "user" for m in msgs):
                continue
            head = (f"### {t['name'] or t['user_key']} ({t['role'] or 'user'}) · agency "
                    f"{t['agency_name'] or '?'} · install {t['instance']}")
            lines = [head] + [f"{'User' if m['sender'] == 'user' else 'Team'}: "
                              f"{' '.join([m['text'], *['[photo]'] * m['n']]).strip()[:DIGEST_MSG_CHARS]}"
                              for m in msgs]
            block = "\n".join(lines)
            if used + len(block) > DIGEST_MAX_CHARS:
                break
            blocks.append(block)
            used += len(block)
        total = db.execute("SELECT COUNT(DISTINCT thread_id) FROM messages WHERE sender = 'user'").fetchone()[0]
    return "\n\n".join(blocks), len(blocks), total


@router.post(f"{API}/summarise")
async def summarise(request: Request) -> dict[str, Any]:
    _owner(request)
    body, included, total = await run_in_threadpool(_digest_input)
    if not included:
        return {"summary": "No user messages yet.", "threads": 0, "total": total}
    content = f"{SUMMARY_HEAD}\n\n{body}"
    if included < total:
        content += f"\n\n(Older threads left out to fit: {total - included}.)"
    try:
        result = await llm_client.chat(
            model=DEFAULT_MODEL, purpose=PURPOSE, account_id=None,
            messages=[{"role": "system", "content": SUMMARY_SYSTEM},
                      {"role": "user", "content": content}],
            temperature=0.2, max_tokens=2000, timeout_s=120,
            api_key=os.environ.get("SUPPORT_HUB_DEEPSEEK_KEY", "").strip() or None)
    except LLMKeyError as e:
        p = key_error_payload(e)
        return {"error": f"{p['message']} {p['fix']}"}
    except LLMConfigError:
        log.warning("support hub: summarise config error", exc_info=True)
        return {"error": "No AI key is set on this install, so nothing can be summarised."}
    except LLMCapExceeded:
        return {"error": "Today's AI budget on this install is used up — try tomorrow."}
    except LLMHTTPError:
        log.warning("support hub: summarise provider error", exc_info=True)
        return {"error": "The AI provider is having trouble — try again in a minute."}
    text = (result.content or "").strip()
    if not text:
        return {"error": "The AI came back empty — try again."}
    return {"summary": text, "threads": included, "total": total}


def _page(nonce: str) -> str:
    return _PAGE.replace("__NONCE__", nonce)


@router.get(PREFIX)
def page() -> HTMLResponse:
    _require_enabled()
    nonce = secrets.token_urlsafe(16)
    csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
           "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; "
           "frame-ancestors 'none'")
    return HTMLResponse(_page(nonce), headers={
        "Content-Security-Policy": csp, "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<title>Support</title>
<style nonce="__NONCE__">
:root { color-scheme: dark; --bg:#141414; --panel:#1d1d1d; --line:#2c2c2c; --fg:#ededed; --dim:#9a9a9a; --me:#2f2f2f; --acc:#e5372f; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 -apple-system, system-ui, sans-serif; }
header { position:sticky; top:0; display:flex; gap:8px; align-items:center; padding:12px 14px; background:var(--panel); border-bottom:1px solid var(--line); z-index:1; }
header h1 { font-size:17px; margin:0; flex:1; }
button { font:inherit; color:var(--fg); background:#2a2a2a; border:1px solid var(--line); border-radius:10px; padding:8px 12px; cursor:pointer; }
button:disabled { opacity:.5; }
button.primary { background:var(--fg); color:#111; border-color:var(--fg); }
main { max-width:760px; margin:0 auto; padding:12px; }
.hidden { display:none !important; }
.row { display:block; width:100%; text-align:left; padding:12px; margin:0 0 8px; background:var(--panel); border-radius:12px; }
.meta { font-size:12px; color:var(--dim); }
.who { font-weight:600; display:flex; align-items:center; gap:6px; }
.dot { width:9px; height:9px; border-radius:50%; background:var(--acc); display:inline-block; }
.last { color:var(--dim); margin-top:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.msgs { display:flex; flex-direction:column; gap:8px; padding-bottom:12px; }
.msg { max-width:85%; padding:8px 12px; border-radius:14px; white-space:pre-wrap; word-wrap:break-word; }
.msg.user { align-self:flex-start; background:var(--panel); border:1px solid var(--line); }
.msg.support { align-self:flex-end; background:var(--me); }
.msg .meta { margin-top:4px; }
textarea, input { width:100%; font-family:inherit; font-size:16px; line-height:1.4; color:var(--fg); background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:10px; }
textarea { min-height:80px; resize:vertical; }
.compose { display:flex; flex-direction:column; gap:8px; position:sticky; bottom:0; background:var(--bg); padding:8px 0 max(12px, env(safe-area-inset-bottom)); }
.pics { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
.pics img { display:block; width:120px; height:120px; object-fit:cover; border-radius:10px; background:var(--line); }
.pending { display:flex; gap:8px; flex-wrap:wrap; }
.pend { position:relative; }
.pend img { display:block; width:64px; height:64px; object-fit:cover; border-radius:8px; }
.pend button { position:absolute; top:-6px; right:-6px; padding:0 6px; line-height:20px; border-radius:50%; }
.actions { display:flex; gap:8px; }
.actions #send { flex:1; }
.err { color:#ff8a80; min-height:1.2em; margin:6px 0; }
#summary { white-space:pre-wrap; background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:12px; margin-bottom:12px; }
form { display:flex; flex-direction:column; gap:10px; max-width:360px; margin:40px auto; }
</style>
</head>
<body>
<header>
  <button id="back" class="hidden" type="button">&larr;</button>
  <h1 id="title">Support</h1>
  <button id="sum" class="hidden" type="button">Summarise all</button>
  <button id="out" class="hidden" type="button">Log out</button>
</header>
<main>
  <form id="login" class="hidden">
    <input id="pw" type="password" autocomplete="current-password" placeholder="Password" required>
    <button class="primary" type="submit">Sign in</button>
    <div id="loginErr" class="err"></div>
  </form>
  <section id="list" class="hidden">
    <div id="summary" class="hidden"></div>
    <div id="listErr" class="err"></div>
    <div id="threads"></div>
  </section>
  <section id="thread" class="hidden">
    <div id="threadMeta" class="meta"></div>
    <div id="msgs" class="msgs"></div>
    <div class="compose">
      <div id="pending" class="pending hidden"></div>
      <textarea id="reply" placeholder="Reply… (Ctrl/Cmd+Enter sends)"></textarea>
      <div class="actions">
        <button id="pick" type="button" title="Add up to 4 photos">Photo</button>
        <input id="file" class="hidden" type="file" accept="image/*" multiple>
        <button id="send" class="primary" type="button">Send</button>
      </div>
      <div id="threadErr" class="err"></div>
    </div>
  </section>
</main>
<script nonce="__NONCE__">
(function () {
  var API = "/support/api";
  var MAX_PHOTOS = 4, MAX_SIDE = 2048;
  var $ = function (id) { return document.getElementById(id); };
  var openId = null;
  var shown = { thread: null, ids: {} };
  var pending = [];
  var busy = { list: false, thread: false, send: false };
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function show(view) {
    ["login", "list", "thread"].forEach(function (v) { $(v).classList.toggle("hidden", v !== view); });
    var signed = view !== "login";
    $("out").classList.toggle("hidden", !signed);
    $("sum").classList.toggle("hidden", view !== "list");
    $("back").classList.toggle("hidden", view !== "thread");
    if (view !== "thread") { openId = null; $("title").textContent = "Support"; }
  }
  function when(iso) {
    var d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  function call(method, path, body) {
    var opt = { method: method, credentials: "same-origin", headers: {} };
    if (body instanceof FormData) opt.body = body;
    else if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    return fetch(API + path, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.status === 401 && path !== "/login") { show("login"); throw new Error("Signed out"); }
        if (!r.ok) throw new Error((j && typeof j.detail === "string") ? j.detail : "Error " + r.status);
        return j;
      });
    });
  }
  function loadThreads(poll) {
    if (busy.list) return Promise.resolve();
    busy.list = true;
    return call("GET", "/threads").then(function (j) {
      if (poll && $("list").classList.contains("hidden")) return;
      var box = $("threads");
      box.replaceChildren();
      if (!j.threads.length) box.appendChild(el("p", "meta", "No messages yet."));
      j.threads.forEach(function (t) {
        var b = el("button", "row");
        b.type = "button";
        var who = el("div", "who");
        if (t.unread) { var d = el("span", "dot"); d.title = "Unread"; who.appendChild(d); }
        who.appendChild(el("span", null, (t.name || "?") + " · " + (t.role || "user")));
        b.appendChild(who);
        b.appendChild(el("div", "meta", t.instance + " · " + (t.agency_name || t.agency_id || "no agency") + " · " + when(t.last_at)));
        b.appendChild(el("div", "last", (t.last_sender === "support" ? "You: " : "") + (t.last_text || "[photo]")));
        b.addEventListener("click", function () { openThread(t.id); });
        box.appendChild(b);
      });
      $("listErr").textContent = "";
      if (!poll) show("list");
    }).catch(function (e) { $("listErr").textContent = e.message; })
      .finally(function () { busy.list = false; });
  }
  function atBottom() {
    return window.innerHeight + window.scrollY >= document.body.scrollHeight - 60;
  }
  function photoRow(photos) {
    var row = el("div", "pics");
    photos.forEach(function (p) {
      var a = el("a");
      a.href = API + "/photos/" + p.id;
      a.target = "_blank";
      a.rel = "noopener";
      var img = el("img");
      img.src = a.href;
      img.alt = "Photo";
      img.loading = "lazy";
      a.appendChild(img);
      row.appendChild(a);
    });
    return row;
  }
  function renderThread(j) {
    var t = j.thread;
    if (t.id !== openId) return;
    $("title").textContent = t.name || "Thread";
    $("threadMeta").textContent = (t.role || "user") + " · " + (t.agency_name || t.agency_id || "no agency") + " · " + t.instance;
    var box = $("msgs");
    var fresh = shown.thread !== t.id;
    if (fresh) { box.replaceChildren(); shown = { thread: t.id, ids: {} }; }
    var stick = fresh || atBottom();
    var added = false;
    j.messages.forEach(function (m) {
      if (shown.ids[m.id]) return;
      shown.ids[m.id] = true;
      added = true;
      var b = el("div", "msg " + m.sender);
      if (m.text) b.appendChild(el("div", null, m.text));
      if (m.photos && m.photos.length) b.appendChild(photoRow(m.photos));
      b.appendChild(el("div", "meta", (m.sender === "support" ? "You" : (t.name || "User")) + " · " + when(m.at)));
      box.appendChild(b);
    });
    if (added && stick) window.scrollTo(0, document.body.scrollHeight);
  }
  function refreshThread() {
    if (openId == null || busy.thread || $("thread").classList.contains("hidden")) return;
    busy.thread = true;
    call("GET", "/threads/" + openId).then(renderThread).catch(function () {})
      .finally(function () { busy.thread = false; });
  }
  function openThread(id) {
    $("threadErr").textContent = "";
    show("thread");
    openId = id;
    shown = { thread: null, ids: {} };
    clearPending();
    call("GET", "/threads/" + id).then(renderThread).catch(function (e) { $("threadErr").textContent = e.message; });
  }
  function drawPending() {
    var box = $("pending");
    box.replaceChildren();
    pending.forEach(function (p, i) {
      var cell = el("div", "pend");
      var img = el("img");
      img.src = p.url;
      img.alt = "Photo to send";
      var x = el("button", null, "×");
      x.type = "button";
      x.title = "Remove photo";
      x.addEventListener("click", function () { pending.splice(i, 1); drawPending(); });
      cell.appendChild(img);
      cell.appendChild(x);
      box.appendChild(cell);
    });
    box.classList.toggle("hidden", !pending.length);
    $("pick").disabled = pending.length >= MAX_PHOTOS;
  }
  function clearPending() { pending = []; drawPending(); }
  function toJpeg(file) {
    return new Promise(function (resolve, reject) {
      var fr = new FileReader();
      fr.onerror = function () { reject(new Error("Couldn't read that photo.")); };
      fr.onload = function () {
        var img = new Image();
        img.onerror = function () { reject(new Error("That file isn't a photo.")); };
        img.onload = function () {
          var k = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
          var c = document.createElement("canvas");
          c.width = Math.max(1, Math.round(img.naturalWidth * k));
          c.height = Math.max(1, Math.round(img.naturalHeight * k));
          var g = c.getContext("2d");
          g.fillStyle = "#fff";
          g.fillRect(0, 0, c.width, c.height);
          g.drawImage(img, 0, 0, c.width, c.height);
          c.toBlob(function (blob) {
            if (!blob) { reject(new Error("Couldn't read that photo.")); return; }
            resolve({ blob: blob, url: c.toDataURL("image/jpeg", 0.85) });
          }, "image/jpeg", 0.85);
        };
        img.src = fr.result;
      };
      fr.readAsDataURL(file);
    });
  }
  function addFiles(files) {
    var id = openId;
    var list = Array.prototype.filter.call(files, function (f) { return f.type.indexOf("image/") === 0; });
    var room = MAX_PHOTOS - pending.length;
    if (list.length > room) $("threadErr").textContent = "Up to " + MAX_PHOTOS + " photos per message.";
    list.slice(0, Math.max(0, room)).forEach(function (f) {
      toJpeg(f).then(function (p) {
        if (openId === id && pending.length < MAX_PHOTOS) { pending.push(p); drawPending(); }
      }).catch(function (e) { if (openId === id) $("threadErr").textContent = e.message; });
    });
  }
  function send() {
    var text = $("reply").value.trim();
    if ((!text && !pending.length) || openId == null || busy.send) return;
    busy.send = true;
    var id = openId;
    var sent = pending.slice();
    var req;
    if (sent.length) {
      var fd = new FormData();
      fd.append("text", text);
      sent.forEach(function (p, i) { fd.append("photos", p.blob, "photo" + i + ".jpg"); });
      req = call("POST", "/threads/" + id + "/reply/upload", fd);
    } else {
      req = call("POST", "/threads/" + id + "/reply", { text: text });
    }
    $("send").disabled = true;
    req.then(function (j) {
      if (openId !== id) return;
      if ($("reply").value.trim() === text) $("reply").value = "";
      pending = pending.filter(function (p) { return sent.indexOf(p) < 0; });
      drawPending();
      $("threadErr").textContent = "";
      renderThread(j);
      window.scrollTo(0, document.body.scrollHeight);
    }).catch(function (e) { if (openId === id) $("threadErr").textContent = e.message; })
      .finally(function () { busy.send = false; $("send").disabled = false; });
  }
  $("login").addEventListener("submit", function (ev) {
    ev.preventDefault();
    call("POST", "/login", { password: $("pw").value }).then(function () {
      $("pw").value = "";
      $("loginErr").textContent = "";
      loadThreads();
    }).catch(function (e) { $("loginErr").textContent = e.message; });
  });
  $("send").addEventListener("click", send);
  $("pick").addEventListener("click", function () { $("file").click(); });
  $("file").addEventListener("change", function () { addFiles($("file").files); $("file").value = ""; });
  $("reply").addEventListener("paste", function (ev) {
    var items = ev.clipboardData ? ev.clipboardData.files : null;
    if (items && items.length) { ev.preventDefault(); addFiles(items); }
  });
  $("reply").addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); send(); }
  });
  $("back").addEventListener("click", function () {
    show("list");
    shown = { thread: null, ids: {} };
    clearPending();
    loadThreads();
  });
  $("out").addEventListener("click", function () {
    call("POST", "/logout").finally(function () { show("login"); });
  });
  $("sum").addEventListener("click", function () {
    var box = $("summary");
    box.classList.remove("hidden");
    box.textContent = "Summarising every thread…";
    $("sum").disabled = true;
    call("POST", "/summarise").then(function (j) {
      box.textContent = j.error ? j.error : j.summary + (j.total > j.threads ? "\\n\\n(" + j.threads + " of " + j.total + " threads read.)" : "");
    }).catch(function (e) { box.textContent = e.message; })
      .finally(function () { $("sum").disabled = false; });
  });
  setInterval(function () {
    if (document.visibilityState === "visible" && openId != null) refreshThread();
  }, 4000);
  setInterval(function () {
    if (document.visibilityState === "visible" && !$("list").classList.contains("hidden")) loadThreads(true);
  }, 10000);
  loadThreads();
})();
</script>
</body>
</html>
"""
