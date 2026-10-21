#!/usr/bin/env python3
"""The relay's HTTP hooks run in ONE middleware layer (`http_hooks.HookChain`)
instead of one `BaseHTTPMiddleware` each (roadmap W2 2.3).

Pins two things. The chain itself: hooks run in Starlette's order (last added
is outermost), an answering hook stops the request, an error still reaches
every outer hook, and a body a hook read still reaches the route. And the
relay's own stack, end to end over HTTP with real session cookies: the hook
order, a chatter refused by role before the audit writer, a repeated
`?account_id=` naming a denied Creator, the share gate's cookie on an inner
reply, GZip still applied, an unhandled error persisted, and the access log
written by its background writer without the share token.

No network: the OnlyFans client is a recording fake.

Run: ./venv/bin/python service/tests/test_http_hooks.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from contextvars import ContextVar  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.background import BackgroundTask  # noqa: E402
from starlette.responses import JSONResponse, PlainTextResponse, StreamingResponse  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import employees  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Action, AppError  # noqa: E402
from http_hooks import HookChain  # noqa: E402

IDS = fx.seed_two_agencies()


def _mirror(chatter: str, owner: str) -> int:
    emp = asyncio.run(employees.get_or_create_mirror_employee(
        IDS[chatter], IDS[owner], display_name=chatter, color="#bbbbbb"))
    assert emp is not None
    return emp


EMP_A = _mirror("chatter_a", "agency_a_owner")
EMP_AB_A = _mirror("chatter_ab", "agency_a_owner")
EMP_AB_B = _mirror("chatter_ab", "agency_b_owner")
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
CHATTER_A = fx.login_chatter("chatter_a")
CHATTER_AB = fx.login_chatter("chatter_ab")

# Test-only routes on the real app, so a request crosses the whole chain.
_BIG = {"rows": ["x" * 40] * 100}                     # ~4.5 KB of JSON
server.app.get("/admin/__hooks_big")(lambda: _BIG)


@server.app.get("/__hooks_boom")
def _boom():
    raise RuntimeError("hooks-boom-7c1")


# The SSE route's generator waits on this after its first frame: the frame must
# reach the client while the route is still running (see the SSE case).
_SSE_GATE: dict[str, asyncio.Event] = {}


@server.app.get("/__hooks_sse")
async def _sse():
    async def frames():
        yield b"data: one\n\n"
        await _SSE_GATE["first_seen"].wait()
        yield b"data: two\n\n"
    return StreamingResponse(frames(), media_type="text/event-stream")


_BG_RAN: list[str] = []


@server.app.get("/__hooks_bg")
def _bg():
    return JSONResponse({"ok": True}, background=BackgroundTask(_BG_RAN.append, "ran"))


def _roles(client, enforce: bool, assignments: dict[int, str], *roles: dict) -> None:
    r = client.put("/admin/settings/roles", json={
        "enforce": enforce, "roles": list(roles),
        "assignments": {str(e): rid for e, rid in assignments.items()}})
    assert r.status_code == 200, f"PUT roles: {r.status_code} {r.text}"


def _role(role_id: str, *hrefs: str) -> dict:
    return {"id": role_id, "name": f"Fixture {role_id}", "description": "",
            "permissions": {h: True for h in hrefs}, "scope": "self"}


def _reset_roles() -> None:
    _roles(OWNER_A, False, {})
    _roles(OWNER_B, False, {})


def _count(query) -> int:
    async def _run():
        async with get_session() as s:
            return (await s.execute(query)).scalar_one()
    return asyncio.run(_run())


class _FakeOF:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name):
        def _call(*_a, **_k):
            self.calls.append(name)
            return {"ok": True}
        return _call


# ── The chain on its own ────────────────────────────────────────────────────

def _mini(*hooks) -> tuple[FastAPI, list[str]]:
    """A bare app whose hooks run through one HookChain; `trail` records the path."""
    trail: list[str] = []
    chain = HookChain()
    for hook in hooks:
        chain.add(hook(trail))
    app = FastAPI()
    app.add_middleware(BaseHTTPMiddleware, dispatch=chain.dispatch)
    return app, trail


def _recording(name: str):
    def make(trail):
        async def hook(request, call_next):
            trail.append(f"{name}>")
            response = await call_next(request)
            trail.append(f"<{name}")
            return response
        hook.__name__ = name
        return hook
    return make


def case_hooks_run_last_added_outermost_and_unwind_in_reverse():
    app, trail = _mini(_recording("first"), _recording("second"), _recording("third"))

    @app.get("/x")
    def _x():
        trail.append("route")
        return {"ok": True}

    r = TestClient(app).get("/x")
    assert r.status_code == 200 and r.json() == {"ok": True}, r.text
    assert trail == ["third>", "second>", "first>", "route", "<first", "<second", "<third"], trail


def case_a_hook_that_answers_skips_the_inner_hooks_and_the_route():
    def gate(trail):
        async def hook(request, call_next):
            trail.append("gate")
            return PlainTextResponse("no", status_code=403)
        return hook

    app, trail = _mini(_recording("inner"), gate, _recording("outer"))
    app.get("/x")(lambda: trail.append("route"))
    r = TestClient(app).get("/x")
    assert r.status_code == 403 and r.text == "no", r.text
    assert trail == ["outer>", "gate", "<outer"], trail


def case_a_route_error_propagates_through_every_outer_hook():
    def catcher(trail):
        async def hook(request, call_next):
            try:
                return await call_next(request)
            except RuntimeError as exc:
                trail.append(f"saw {exc}")
                raise
        return hook

    app, trail = _mini(_recording("inner"), catcher)

    @app.get("/x")
    def _x():
        raise RuntimeError("route-broke")

    r = TestClient(app, raise_server_exceptions=False).get("/x")
    assert r.status_code == 500, r.status_code
    assert trail == ["inner>", "saw route-broke"], trail


def case_a_body_a_hook_read_still_reaches_the_route_and_a_contextvar_it_set_too():
    """The audit hook's pattern: read the body before `call_next`, then the
    route parses it again; and `_account_context`'s: a ContextVar set by a hook
    is what the route reads."""
    seen: ContextVar[str | None] = ContextVar("seen", default=None)

    def reader(trail):
        async def hook(request, call_next):
            trail.append((await request.body()).decode())
            token = seen.set("from-hook")
            try:
                return await call_next(request)
            finally:
                seen.reset(token)
        return hook

    app, trail = _mini(reader)

    @app.post("/x")
    async def _x(request: Request):
        return {"body": await request.json(), "ctx": seen.get()}

    r = TestClient(app).post("/x", json={"a": 1})
    assert r.json() == {"body": {"a": 1}, "ctx": "from-hook"}, r.text
    assert trail == ['{"a":1}'], trail


# ── The relay's own stack ───────────────────────────────────────────────────

def case_the_relay_registers_every_hook_in_one_layer_in_the_documented_order():
    names = [h.__name__ for h in server._http_hooks.hooks]
    assert names == [
        "_cap_vault_batch_body",
        "_persist_unhandled_errors",
        "_api_access_log",
        "_share_token_gate",
        "_account_context",
        "session_middleware",            # auth (owner) session
        "chatter_session_middleware",    # chatter session
        "_account_isolation_middleware",
        "role_enforcement_middleware",
        "_deactivated_write_guard",
        "audit_middleware",
    ], names
    layers = server.app.user_middleware
    assert [m.cls.__name__ for m in layers] == ["BaseHTTPMiddleware", "GZipMiddleware"], layers
    assert layers[0].kwargs["dispatch"] == server._http_hooks.dispatch


def case_a_chatter_denied_by_role_is_refused_before_the_route_and_the_audit_writer():
    fake = _FakeOF()
    original = server._get_client
    server._get_client = lambda *_a, **_k: fake
    # Only this PUT's rows: the role PUTs around it are audited too.
    actions = (select(func.count()).select_from(Action)
               .where(Action.action == "PUT /api/of/v2/subscriptions/42/note"))
    try:
        _roles(OWNER_A, True, {EMP_A: "role-none"}, _role("role-none"))
        before = _count(actions)
        r = CHATTER_A.put("/api/of/v2/subscriptions/42/note", json={"note": "after"})
        assert r.status_code == 403 and r.json() == {
            "detail": "Your role does not allow Messages Basic"}, r.text
        assert fake.calls == [] and _count(actions) == before, (fake.calls, _count(actions), before)
        _reset_roles()
        r = CHATTER_A.put("/api/of/v2/subscriptions/42/note", json={"note": "after"})
        assert r.status_code == 200 and fake.calls == ["set_fan_note"], r.text
        assert _count(actions) == before + 1, "the allowed PUT wrote no audit row"
    finally:
        server._get_client = original
        _reset_roles()


def case_a_repeated_account_id_naming_a_denied_creator_is_refused():
    a, b = IDS["creator_a"], IDS["creator_b"]
    path = "/admin/stats/sales-records?from=2026-06-10&to=2026-06-11"
    try:
        _roles(OWNER_A, True, {EMP_AB_A: "role-sr"}, _role("role-sr", "/analytics/sales-records"))
        _roles(OWNER_B, True, {EMP_AB_B: "role-none"}, _role("role-none"))
        assert CHATTER_AB.get(f"{path}&account_id={a}").status_code == 200
        for query in (f"account_id={b}&account_id={a}", f"account_id={a}&account_id={b}"):
            r = CHATTER_AB.get(f"{path}&{query}")
            assert r.status_code == 403 and r.json() == {
                "detail": "Your role does not allow Sales records"}, f"{query}: {r.text}"
    finally:
        _reset_roles()


def case_an_owner_naming_another_agencys_creator_is_refused_by_the_tenant_gate():
    r = OWNER_A.get(f"/admin/stats/sales-records?account_id={IDS['creator_b']}")
    assert r.status_code == 403 and r.text == "not your account", f"{r.status_code} {r.text}"


def case_gzip_still_compresses_a_large_reply_and_leaves_a_small_one_whole():
    r = OWNER_A.get("/admin/__hooks_big", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.json() == _BIG, r.status_code
    assert r.headers.get("content-encoding") == "gzip", dict(r.headers)
    small = OWNER_A.get("/livez", headers={"Accept-Encoding": "gzip"})
    assert small.json() == {"ok": True}
    assert "content-encoding" not in small.headers, dict(small.headers)


def case_the_share_gate_sets_its_cookie_on_the_reply_an_inner_hook_built():
    original = server.SHARE_TOKEN
    server.SHARE_TOKEN = "tok-hooks-1"
    try:
        anon = TestClient(server.app)
        r = anon.get("/admin/accounts")
        assert r.status_code == 401 and r.text.startswith("unauthorized"), r.text
        assert r.headers.get("cache-control") == "no-store", dict(r.headers)
        # Past the gate the tenant gate refuses the cookieless caller — and the
        # share gate still stamps its cookie on THAT reply on the way out.
        r = anon.get("/admin/accounts?t=tok-hooks-1")
        assert r.status_code == 401 and r.text == "sign in required", r.text
        assert "share_token=tok-hooks-1" in r.headers.get("set-cookie", ""), dict(r.headers)
    finally:
        server.SHARE_TOKEN = original


def case_sse_streams_frame_by_frame_through_the_chain_and_gzip():
    """The first frame must reach the client while the route is still running:
    the generator will not yield the second until the test has RECEIVED the
    first, so a chain (or GZip) that buffered the body would deadlock here."""
    async def run():
        _SSE_GATE["first_seen"] = asyncio.Event()
        got: list[bytes] = []
        status: list[int] = []
        sent_request = False

        async def receive():
            nonlocal sent_request
            if not sent_request:
                sent_request = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Event().wait()       # the client never disconnects

        async def send(message):
            if message["type"] == "http.response.start":
                status.append(message["status"])
            elif message["type"] == "http.response.body" and message.get("body"):
                got.append(message["body"])
                _SSE_GATE["first_seen"].set()

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "GET", "scheme": "http", "path": "/__hooks_sse",
                 "raw_path": b"/__hooks_sse", "query_string": b"", "root_path": "",
                 "headers": [(b"host", b"testserver"), (b"accept-encoding", b"gzip"),
                             (b"accept", b"text/event-stream")],
                 "client": ("127.0.0.1", 1), "server": ("testserver", 80)}
        await asyncio.wait_for(server.app(scope, receive, send), timeout=10)
        return status, got

    status, got = asyncio.run(run())
    assert status == [200], status
    assert b"".join(got) == b"data: one\n\ndata: two\n\n", got
    assert got[0] == b"data: one\n\n", f"the first frame arrived merged or late: {got}"


def case_a_background_task_runs_after_the_reply_crosses_the_chain():
    _BG_RAN.clear()
    log_path = Path(tempfile.mkdtemp()) / "of-api.log"
    original = server._API_LOG_PATH
    server._API_LOG_PATH = str(log_path)
    try:
        r = TestClient(server.app).get("/__hooks_bg")
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert _BG_RAN == ["ran"], _BG_RAN
        assert len(_log_lines(log_path, "/__hooks_bg")) == 1   # the outer hooks saw it
    finally:
        server._API_LOG_PATH = original


def _log_lines(path: Path, needle: str, timeout_s: float = 3.0) -> list[str]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            hits = [ln for ln in path.read_text().splitlines() if needle in ln]
            if hits:
                return hits
        time.sleep(0.02)
    return []


def case_an_unhandled_error_is_persisted_and_the_access_log_records_the_500():
    log_path = Path(tempfile.mkdtemp()) / "of-api.log"
    original = server._API_LOG_PATH
    server._API_LOG_PATH = str(log_path)
    try:
        r = TestClient(server.app, raise_server_exceptions=False).get("/__hooks_boom")
        assert r.status_code == 500, r.status_code
        rows = _count(select(func.count()).select_from(AppError)
                      .where(AppError.message == "hooks-boom-7c1"))
        assert rows == 1, f"app_errors rows: {rows}"
        lines = _log_lines(log_path, "/__hooks_boom")
        assert len(lines) == 1 and " 500 " in lines[0], lines
    finally:
        server._API_LOG_PATH = original


def case_the_access_log_is_written_by_its_writer_without_the_share_token():
    log_path = Path(tempfile.mkdtemp()) / "of-api.log"
    original = server._API_LOG_PATH
    server._API_LOG_PATH = str(log_path)
    try:
        r = TestClient(server.app).get("/livez?t=sekret-hooks&x=1")
        assert r.status_code == 200
        lines = _log_lines(log_path, "/livez")
        assert len(lines) == 1, lines
        assert "GET" in lines[0] and " 200 " in lines[0] and "/livez?x=1" in lines[0], lines
        assert "sekret-hooks" not in log_path.read_text()
    finally:
        server._API_LOG_PATH = original


_harness.run()
