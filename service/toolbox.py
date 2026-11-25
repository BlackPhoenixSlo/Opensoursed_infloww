from __future__ import annotations

import asyncio
import contextvars
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import httpx
from fastapi import Request
from sqlalchemy import select

import client_addr
import toolbox_decide as td
import ultra_decide as ud
from db.engine import get_session
from db.models import UltraPlan

SEND_REFUSED = "send tools run only from an owner-approved plan"
UNSENDABLE = "not sendable: NaN/Infinity, a lone surrogate or a value too long"
NOT_LIVE = "the plan was cancelled before this call went out; nothing was sent"


@dataclass(frozen=True)
class Creds:
    authorization: str | None = None
    cookie: str | None = None
    forwarded_host: str | None = None
    forwarded_proto: str | None = None
    client_host: str | None = None
    host: str | None = None

    @classmethod
    def from_request(cls, request: Request) -> "Creds":
        h = request.headers
        bearer = h.get("authorization")
        return cls(authorization=bearer or None, cookie=None if bearer else (h.get("cookie") or None),
                   forwarded_host=h.get("x-forwarded-host") or None,
                   forwarded_proto=h.get("x-forwarded-proto") or request.url.scheme,
                   client_host=str(client_addr.client_address(request)), host=h.get("host") or None)

    def headers(self) -> dict[str, str]:
        out = {"Host": self.host} if self.host else {}
        if self.authorization:
            out["Authorization"] = self.authorization
        elif self.cookie:
            out["Cookie"] = self.cookie
        if self.forwarded_host:
            out["X-Forwarded-Host"] = self.forwarded_host
        if self.forwarded_proto:
            out["X-Forwarded-Proto"] = self.forwarded_proto
        return out

    def public_base(self) -> str | None:
        return td.public_base(self.forwarded_host, self.forwarded_proto, os.environ.get("APP_PUBLIC_URL"))


async def _raw(req: td.Request, creds: Creds) -> httpx.Response:
    import server
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=False,
                                    client=(creds.client_host or "127.0.0.1", 0))
    async with httpx.AsyncClient(transport=transport, base_url="http://relay.internal", timeout=None) as c:
        return await c.request(req.method, req.path, params=req.query or None, json=req.json,
                               headers={**creds.headers(), **req.headers})


async def raw(req: td.Request, creds: Creds) -> httpx.Response:
    # Empty Context: in the caller's task the inner identity leaks into the caller; in a copied one a credential-less request inherits the caller's user.
    return await asyncio.create_task(_raw(req, creds), context=contextvars.Context())


def body_of(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return r.text


async def _send(req: td.Request, creds: Creds) -> tuple[int, Any]:
    r = await raw(req, creds)
    return r.status_code, body_of(r)


async def call(t: td.Tool, args: Mapping[str, Any], creds: Creds, *,
               plan_step: str | None = None, plan_owner: str | None = None,
               live: Callable[[], bool] | None = None) -> dict[str, Any]:
    # The caller must hold no DB session across call(): an open write transaction stalls the inner request ~64 s and loses its write.
    base = creds.public_base()
    raw_args = dict(args)
    if t.effect == "send" and not await _plan_send(t, raw_args, plan_step, plan_owner):
        return {**td.error(403, SEND_REFUSED), "open_url": td.open_url(base, t.open, raw_args, None)}
    try:
        parsed = td.validate_args(t, args)
        req = td.build_request(t, parsed)
    except td.ArgsError as e:
        return {**td.error(422, {"detail": "invalid arguments", "errors": e.errors}),
                "open_url": td.open_url(base, t.open, raw_args, None)}
    if live is not None and not live():
        return {**td.error(409, NOT_LIVE), "open_url": td.open_url(base, t.open, raw_args, None)}
    try:
        status, body = await _send(req, creds)
    except (ValueError, httpx.InvalidURL):
        return {**td.error(422, {"detail": "invalid arguments", "errors": {"args": UNSENDABLE}}),
                "open_url": td.open_url(base, t.open, raw_args, None)}
    url = td.open_url(base, t.open, parsed, body)
    if t.check is not None and 200 <= status < 300 and (why := t.check(parsed, body)):
        return {**td.error(502, {"detail": why}), "open_url": url}
    return {**td.shape_result(t, status, body, base=base), "open_url": url}


async def _plan_send(t: td.Tool, args: dict[str, Any], plan_step: str | None, owner: str | None) -> bool:
    pid, _, sid = (plan_step or "").partition(":")
    if not pid or not sid or not owner:
        return False
    async with get_session() as s:
        row = (await s.execute(select(UltraPlan.status, UltraPlan.plan_json, UltraPlan.step_states)
                               .where(UltraPlan.id == pid, UltraPlan.owner_user_id == owner))).first()
    return row is not None and ud.may_send(json.loads(row.plan_json), row.status, json.loads(row.step_states),
                                           sid, t.name, args)

