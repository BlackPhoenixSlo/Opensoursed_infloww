#!/usr/bin/env python3
"""
A write must name its Creator once the caller can reach more than one.

`_resolve_account_id` falls back to the active account when a request carries
no `X-Account-Id` / `?account_id=`. For a read that is a harmless default; for
a write (send_message → `_get_client()`) on a 2-Creator Agency it sends AS
WHICHEVER CREATOR HAPPENS TO BE ACTIVE. `resolve_account` now refuses that
write with a 400 `account_required`; reads keep the fallback, background
callers (`request is None`) are never refused, and an explicit id is never
refused.

Cases:
  case_helper_table          — the pure rule: explicit wins, write × >1 refused,
                               background never; thunks read only when needed.
  case_resolver_table        — `_resolve_account_id` with a real Request per
                               principal (user / chatter / none): the reach
                               count comes from that principal's set (registry
                               when nobody is signed in).
  case_existing_order_kept   — 404 / 403 still fire; 400 precedes 503.
  case_background_never_refused — `request is None` keeps the fallback.
  case_send_without_header_400  — POST send on a 2-Creator Agency with no header
                               → 400, the fake OF client sees 0 sends.
  case_send_with_header_200  — same with X-Account-Id → 200, 1 send.
  case_get_fan_concurrent_stub — the other drawer open inserts the stub row
                               between our miss and our insert → 200, one row.

No network: the registry and the OF client are stubbed.

Run: ./venv/bin/python service/tests/test_account_scope_writes.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import uuid  # noqa: E402

import httpx  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from starlette.requests import Request  # noqa: E402

import accounts as account_registry  # noqa: E402
import auth  # noqa: E402
import chatters  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, User, UserAccount  # noqa: E402

_harness.make_client()  # neutralises the startup spawns before `server` serves
import server  # noqa: E402

A, B = "510001", "510002"
_ACCOUNTS = (A, B)

account_registry.get_account = lambda aid: {"id": aid} if aid in _ACCOUNTS else None
account_registry.list_accounts = lambda: [{"id": a, "has_session": True} for a in _ACCOUNTS]
account_registry.is_account = lambda aid: aid in _ACCOUNTS
account_registry.account_ids = lambda: frozenset(_ACCOUNTS)
account_registry.get_active_account_id = lambda: A

METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")
READS = ("GET", "HEAD")


async def _setup() -> None:
    async with get_session() as s:
        boss = User(id=uuid.uuid4().hex, username="boss", password="pw")
        s.add(boss)
        s.add_all([Account(id=a, nickname=a) for a in _ACCOUNTS])
        await s.flush()
        s.add_all([UserAccount(user_id=boss.id, account_id=a) for a in _ACCOUNTS])


asyncio.run(_setup())


def _request(method: str, headers: dict[str, str] | None = None) -> Request:
    return Request({
        "type": "http", "method": method, "path": "/api/of/v2/x", "raw_path": b"/api/of/v2/x",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "scheme": "http", "server": ("test", 80), "client": ("test", 1),
    })


def _principal(kind: str, ids: frozenset[str]):
    """Set the contextvars the session middlewares would; return reset tokens."""
    user = auth.AuthedUser(id_="u1", username="u", account_ids=ids) if kind == "user" else None
    chatter = (chatters.ChatterIdentity(id_="c1", username="c", display_name=None, color=None,
                                        owner_user_ids=frozenset({"u1"}), account_ids=ids)
               if kind == "chatter" else None)
    return auth._request_user.set(user), chatters._request_chatter.set(chatter)


def _reset(tokens) -> None:
    auth._request_user.reset(tokens[0])
    chatters._request_chatter.reset(tokens[1])


def case_helper_table() -> None:
    """Principal dims live in case_resolver_table; here only the rule + laziness."""
    def must_not(name):
        def boom():
            raise AssertionError(f"{name} read when the answer did not need it")
        return boom
    R = server.resolve_account
    assert R(B, must_not("active"), must_not("method"), 2) == B
    assert R(None, lambda: A, None, 2) == A, "background refused"
    assert R(None, lambda: A, must_not("method"), 1) == A, "≤1 Creator reads no method"
    assert R(None, lambda: None, lambda: "GET", 2) is None, "no active → None (503 upstream)"
    for method in METHODS:
        got = R(None, lambda: A, lambda m=method: m, 2)
        if method in READS:
            assert got == A, (method, got)
        else:
            assert isinstance(got, server.Refuse) and got.status == 400 \
                and got.detail["error"] == "account_required" and got.detail["message"], (method, got)


def case_resolver_table() -> None:
    bad = []
    for kind in ("user", "chatter", "none"):
        for n in (1, 2):
            ids = frozenset(_ACCOUNTS[:n])
            # No principal → the registry is the reach; size it per n.
            account_registry.account_ids = lambda ids=ids: ids
            for method in METHODS:
                for explicit in (B if n == 2 else A, None):
                    tokens = _principal(kind, ids)
                    try:
                        hdr = {"X-Account-Id": explicit} if explicit else None
                        try:
                            have = server._resolve_account_id(_request(method, hdr))
                        except HTTPException as e:
                            have = e.status_code
                    finally:
                        _reset(tokens)
                    want = 400 if (explicit is None and n > 1 and method not in READS) \
                        else (explicit or A)
                    if have != want:
                        bad.append((kind, n, method, explicit, have, want))
    account_registry.account_ids = lambda: frozenset(_ACCOUNTS)
    assert not bad, f"resolver table mismatches: {bad}"


def case_existing_order_kept() -> None:
    """404 (unknown explicit) and 403 (not yours) still fire; 400 precedes 503."""
    tokens = _principal("user", frozenset({A}))
    try:
        for method in ("GET", "POST"):
            try:
                server._resolve_account_id(_request(method, {"X-Account-Id": "999999"}))
                raise AssertionError("unknown explicit id resolved")
            except HTTPException as e:
                assert e.status_code == 404, f"{method} unknown explicit: {e.status_code}"
            try:
                server._resolve_account_id(_request(method, {"X-Account-Id": B}))
                raise AssertionError("foreign explicit id resolved")
            except HTTPException as e:
                assert e.status_code == 403, f"{method} foreign explicit: {e.status_code}"
    finally:
        _reset(tokens)
    tokens = _principal("user", frozenset(_ACCOUNTS))
    saved = account_registry.get_active_account_id
    account_registry.get_active_account_id = lambda: None
    try:
        for method, want in (("GET", 503), ("POST", 400)):
            try:
                server._resolve_account_id(_request(method))
                raise AssertionError(f"{method} with no active resolved")
            except HTTPException as e:
                assert e.status_code == want, f"{method} no active: {e.status_code} != {want}"
    finally:
        account_registry.get_active_account_id = saved
        _reset(tokens)


def case_background_never_refused() -> None:
    tokens = _principal("user", frozenset(_ACCOUNTS))
    try:
        assert server._resolve_account_id(None) == A, "background caller lost the fallback"
    finally:
        _reset(tokens)
    assert server._resolve_account_id(None) == A, "no-principal background caller refused"


class _FakeOF:
    """The OF client `_load_client` hands the send route: counts sends."""
    sends: list[tuple[str, int]] = []

    def __init__(self, aid: str) -> None:
        self.aid = aid

    def send_message(self, chat_id, **_kw):
        _FakeOF.sends.append((self.aid, int(chat_id)))
        return {"id": 900000 + len(_FakeOF.sends), "text": _kw.get("text") or "",
                "createdAt": "2026-10-31T00:00:00Z"}


@contextlib.asynccontextmanager
async def _client():
    """The owner of both Creators, signed in over the real login route."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                 base_url="http://test") as c:
        r = await c.post("/auth/login", json={"username": "boss", "password": "pw"})
        assert r.status_code == 200, f"login: {r.status_code} {r.text}"
        yield c


async def _send(headers: dict[str, str]) -> httpx.Response:
    saved = server._load_client
    server._load_client = _FakeOF
    _FakeOF.sends.clear()
    try:
        async with _client() as c:
            return await c.post("/api/of/v2/chats/4242/messages", json={"text": "hi"},
                                headers=headers)
    finally:
        server._load_client = saved


async def case_send_without_header_400() -> None:
    r = await _send({})
    assert r.status_code == 400, f"no-header send: {r.status_code} {r.text}"
    assert r.json()["detail"]["error"] == "account_required", r.text
    assert _FakeOF.sends == [], f"OF saw sends: {_FakeOF.sends}"


async def case_send_with_header_200() -> None:
    r = await _send({"X-Account-Id": B})
    assert r.status_code == 200, f"scoped send: {r.status_code} {r.text}"
    assert _FakeOF.sends == [(B, 4242)], f"OF sends: {_FakeOF.sends}"


async def case_get_fan_concurrent_stub() -> None:
    """Forced race: `_ensure_account_row` runs after our miss, so the other open's
    insert lands there (own session, committed) before ours. The old add+commit
    raised IntegrityError here (a 500); ON CONFLICT no-ops and reads the one row."""
    import fans

    fid = 777001
    real = fans._ensure_account_row

    async def other_open_wins(s, account_id):
        fans._ensure_account_row = real  # once
        async with get_session() as other:
            other.add(Fan(account_id=account_id, fan_id=fid, source="onlyfans"))
            await other.commit()
        await real(s, account_id)

    fans._ensure_account_row = other_open_wins
    try:
        async with _client() as c:
            r = await c.get(f"/admin/fans/{A}/{fid}")
    finally:
        fans._ensure_account_row = real
    async with get_session() as s:
        n = (await s.execute(select(func.count()).select_from(Fan)
                             .where(Fan.account_id == A, Fan.fan_id == fid))).scalar_one()
    assert r.status_code == 200, f"drawer open after the race: {r.status_code} {r.text[:200]}"
    assert r.json()["fan_id"] == fid, r.text[:120]
    assert n == 1, f"fans rows: {n}"

if __name__ == "__main__":
    _harness.run()
