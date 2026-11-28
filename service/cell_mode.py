from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import HTTPConnection, Request
from starlette.routing import Match

CELL_PROTO = 2


def _refuse(msg: str) -> None:
    raise SystemExit(f"Cells: refusing to start: {msg}")


def read_placement() -> dict:
    with open(os.environ["OI_CELL_MAP"], "rb") as fh:
        return json.load(fh)


def boot_check() -> None:
    path = os.environ.get("OI_CELL_MAP", "")
    try:
        doc = read_placement()
    except (KeyError, OSError, ValueError) as e:
        _refuse(f"OI_CELL_MAP {path} is unreadable ({e})")
    proto = doc.get("min_cell_proto") if isinstance(doc, dict) else None
    if (not isinstance(doc, dict) or doc.get("schema") != 1 or not isinstance(doc.get("cells"), dict)
            or not isinstance(proto, int) or isinstance(proto, bool)):
        _refuse(f"OI_CELL_MAP {path} is not Placement v1")
    agency = doc.get("agency")
    if not isinstance(agency, str) or not agency.strip():
        _refuse(f"OI_CELL_MAP {path} has no agency")
    cell_id = os.environ.get("OI_CELL_ID", "")
    if not cell_id:
        _refuse("OI_CELL_ID is unset")
    cell = doc["cells"].get(cell_id)
    if not isinstance(cell, dict):
        _refuse(f"Cell {cell_id} is not in {path}")
    local_role = role() or ""
    if local_role != cell.get("role"):
        _refuse(f"OI_CELL_ROLE={local_role!r} but Placement gives Cell {cell_id} role {cell.get('role')!r}")
    if proto > CELL_PROTO:
        _refuse(f"Placement needs min_cell_proto {proto}; this Relay speaks {CELL_PROTO}")
    try:
        scope_rows()
    except (OSError, ValueError, KeyError) as e:
        _refuse(f"Cell scope {SCOPE_PATH} is unreadable ({e})")
    import actor_token
    actor_token.configure(agency)


SCOPE_PATH = Path(__file__).resolve().with_name("cell_scope.json")
_doc: dict | None = None


def _scope() -> dict:
    global _doc
    if _doc is None:
        doc = json.loads(SCOPE_PATH.read_bytes())
        _doc = {"routes": doc["routes"], "jobs": doc["jobs"]}
    return _doc


def scope_rows() -> dict:
    return _scope()["routes"]


def role() -> str | None:
    return os.environ.get("OI_CELL_ROLE") if os.environ.get("OI_CELL_MAP") else None


def is_control() -> bool:
    return role() == "control"


def runs_job(name: str) -> bool:
    row = _scope()["jobs"].get(name)
    return isinstance(row, dict) and (row.get("scope") != "agency" or is_control())


def owned(platform: str, account_id: str) -> bool:
    return f"{platform}:{account_id}" in {a.strip() for a in os.environ.get("OI_ACCOUNTS", "").split(",")}


_STATE_KEY = "oi_cell_gen"
_data_gen: int | None = None


def owned_ids() -> frozenset[str]:
    return frozenset(a.strip().partition(":")[2] for a in os.environ.get("OI_ACCOUNTS", "").split(",") if ":" in a)


def owned_only(account_ids):
    ids = owned_ids()
    return [a for a in account_ids if str(a) in ids]


def data_gen() -> int | None:
    return _data_gen


def owned_set() -> frozenset[str] | None:
    return owned_ids() if os.environ.get("OI_CELL_MAP") else None


def read_scope(ids):
    owned = owned_set()
    if owned is None:
        return ids
    return owned if ids is None else frozenset(ids) & owned


def clamp(ids):
    # Control keeps the full set: its /auth/* and /chatter/* routes list a person's Creators from it.
    return ids if ids is None or is_control() else read_scope(ids)


def install_meta(sync_url: str) -> int:
    global _data_gen
    path = sync_url.split("sqlite:///", 1)[1]
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS cell_meta (data_gen INTEGER NOT NULL DEFAULT 1, copy_epoch INTEGER,"
                   " copy_version INTEGER, section_sha TEXT, applied_at TEXT, confirmed_at TEXT, grant_gen INTEGER)")
        db.execute("INSERT INTO cell_meta (data_gen) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM cell_meta)")
        _data_gen = int(db.execute("SELECT data_gen FROM cell_meta").fetchone()[0])
    return _data_gen


def refusal(status_code: int, error: str, **extra) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, **extra})


async def _body_account(conn: HTTPConnection) -> str | None:
    if not isinstance(conn, Request) or conn.method in _SAFE:
        return None
    if not conn.headers.get("content-type", "").startswith("application/json"):
        return None
    try:
        body = json.loads(await conn.body() or b"null")
    except ValueError:
        return None
    v = body.get("account_id") if isinstance(body, dict) else None
    return str(v) if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v) else None


_SAFE = frozenset({"GET", "HEAD", "OPTIONS"})


def _route_key(conn: HTTPConnection) -> str | None:
    path = getattr(conn.scope.get("route"), "path", None)
    if path is None:
        return None
    return f"{'WS' if conn.scope['type'] == 'websocket' else conn.scope['method']} {path}"


async def route_creator(conn: HTTPConnection) -> str | None:
    query = conn.query_params
    path_account = conn.path_params.get("account_id") if _route_key(conn) else None
    return (conn.headers.get("x-account-id") or query.get("account_id") or query.get("account")
            or path_account or await _body_account(conn))


_FANIN_KEY = "oi_cell_fanin"


def _scope_check(conn: HTTPConnection) -> str:
    key = _route_key(conn)
    row = scope_rows().get(key) if key else None
    scope = row.get("scope") if isinstance(row, dict) else None
    if scope in (None, "closed") or (scope == "fanin" and key not in FANIN):
        raise refusal(403, "cell_scope_closed", route=key)
    if scope == "agency" and conn.scope.get("method", "GET") not in _SAFE and not is_control():
        raise refusal(403, "agency_write_on_data_cell", route=key)
    if scope == "fanin":
        conn.scope.setdefault("state", {})[_FANIN_KEY] = key
    return scope


def account_path_param(conn: HTTPConnection) -> str | None:
    for route in conn.app.router.routes:
        match, scope = route.matches(conn.scope)
        if match == Match.FULL:
            return scope.get("path_params", {}).get("account_id")
    return None


async def route_guard(conn: HTTPConnection) -> None:
    scope = _scope_check(conn)
    if conn.scope["type"] == "http" and conn.scope["method"] not in _SAFE:
        import cell_hold
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(cell_hold.refuse_writes)
    q = conn.query_params
    named = {v for v in (conn.headers.get("x-account-id"), q.get("account_id"), q.get("account"),
                         conn.path_params.get("account_id"), await _body_account(conn)) if v}
    if len(named) > 1:
        raise refusal(400, "account_conflict", accounts=sorted(named))
    expect = conn.headers.get("x-cell-expect")
    if expect is not None and expect != f"{os.environ.get('OI_CELL_ID', '')}.{os.environ.get('OI_EPOCH', '')}":
        raise refusal(409, "not_owner", expected=expect)
    named.update(a.strip() for a in q.get("accounts", "").split(",") if a.strip())
    if not named:
        return
    if scope != "agency" or not is_control():
        if stray := sorted(named - owned_ids()):
            raise refusal(409, "not_owner", accounts=stray)
    conn.scope.setdefault("state", {})[_STATE_KEY] = _data_gen
    gen = conn.headers.get("x-cell-gen")
    if gen is not None and getattr(conn, "method", "GET") not in _SAFE and (
            not gen.isdigit() or _data_gen is None or int(gen) < _data_gen):
        raise refusal(409, "stale_cell_gen", cell_gen=_data_gen)


async def no_proxy_refused(request, exc) -> JSONResponse:  # noqa: ANN001
    return JSONResponse({"detail": {"error": "no_proxy_refused", "account_id": exc.account_id}}, status_code=409)


class CellGenHeader:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        state = scope.setdefault("state", {})

        async def stamp(msg):
            if msg["type"] == "http.response.start" and state.get(_STATE_KEY) is not None:
                msg["headers"] = [*msg.get("headers", []), (b"x-cell-gen", str(state[_STATE_KEY]).encode())]
            await send(msg)
        if scope["method"] in _SAFE:
            return await self.app(scope, receive, stamp)
        from cell_hold import writing
        with writing():
            await self.app(scope, receive, stamp)


def _owned_platforms() -> dict[str, str]:
    out = {}
    for a in os.environ.get("OI_ACCOUNTS", "").split(","):
        platform, sep, aid = a.strip().partition(":")
        if sep:
            out[aid] = platform
    return out


class _Tagger:
    def __init__(self, query: dict[str, str]):
        self.plat = _owned_platforms()
        self.as_of = int(time.time() * 1000)
        self.bad: set[str] = set()
        named = query.get("accounts") or query.get("account_id") or ""
        self.asked = {a.strip() for a in named.split(",") if a.strip()} or set(self.plat)

    def rows(self, rows, aid_of, ok_of=lambda r: True) -> list:
        out = []
        for r in rows if isinstance(rows, list) else ():
            aid = aid_of(r) if isinstance(r, dict) else None
            platform = self.plat.get(str(aid)) if aid is not None else None
            if platform is None or r.get("platform", platform) != platform:
                continue
            ok = bool(ok_of(r))
            if not ok:
                self.bad.add(str(aid))
            out.append({**r, "platform": platform, "account_id": str(aid), "as_of": self.as_of, "ok": ok})
        return out

    def roster(self, body) -> None:
        if isinstance(body, dict) and "accounts" in body:
            body["accounts"] = self.rows(body["accounts"], lambda r: r.get("id"))

    def partial(self) -> list[str]:
        import accounts as account_registry
        from auth import require_actor_account_ids
        authorized = read_scope(require_actor_account_ids())
        here = {str(a.get("id")) for a in account_registry.list_accounts()}
        missing = ((self.asked - here) | self.bad) & self.plat.keys() & authorized
        return sorted(f"{self.plat[a]}:{a}" for a in missing)


def _tag_recent(t: _Tagger, body: dict) -> None:
    body["list"] = t.rows(body.get("list"), lambda r: r.get("__accountId"))


def _tag_inbox(t: _Tagger, body: dict) -> None:
    answers = body.get("answers")
    out = []
    for a in answers if isinstance(answers, list) else ():
        if isinstance(a, dict) and a.get("accountId") is None:
            if a.get("read") == "accounts":
                t.roster(a.get("body"))
            out.append(a)
        else:
            out += t.rows([a], lambda r: r.get("accountId"), lambda r: "status" not in r)
    body["answers"] = out


FANIN = {
    "GET /admin/accounts": lambda t, body: t.roster(body),
    "GET /admin/chats/recent": _tag_recent,
    "GET /admin/screens/inbox": _tag_inbox,
}


class FaninTags:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        state = scope.setdefault("state", {})
        held: dict = {}

        async def tag(msg):
            key = state.get(_FANIN_KEY)
            if msg["type"] == "http.response.start" and key and msg.get("status") == 200:
                held["start"], held["body"] = msg, []
                return
            if "start" not in held or msg["type"] != "http.response.body":
                return await send(msg)
            held["body"].append(msg.get("body", b""))
            if msg.get("more_body"):
                return
            raw = b"".join(held["body"])
            try:
                body = json.loads(raw)
            except ValueError:
                body = None
            if isinstance(body, dict):
                t = _Tagger(dict(parse_qsl(scope.get("query_string", b"").decode("latin-1"))))
                FANIN[key](t, body)
                body["partial"] = t.partial()
                raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            start = held.pop("start")
            start["headers"] = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"] + [
                (b"content-length", str(len(raw)).encode())]
            await send(start)
            await send({"type": "http.response.body", "body": raw})
        await self.app(scope, receive, tag)
