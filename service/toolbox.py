"""service/toolbox.py — runs a Toolbox tool (`toolbox_decide.TOOLS`) as the caller:
`await call(tool, args, creds)` → the tool result dict (docs/plans/ultra-mode/issues/04-toolbox.md).

In-process HTTP through the whole middleware stack (session/bearer, isolation, role gates,
audit) via `httpx.ASGITransport(app=server.app)`, carrying only the caller's own credential.
Measured by the step-2 spike (.scratch/ultra-s2/spike/RESULT.md):

- Each request runs in `asyncio.create_task(…, context=contextvars.Context())`. Awaited in the
  caller's task it leaks the inner identity into the caller; in a copied context a request
  with no credential inherits the caller's user. In an empty context it is an honest 401.
- The caller must hold no DB session across `call()`: an open write transaction stalls the
  inner request ~64 s and loses its write; an open read costs +2 s when the pool is busy.
  `call()` itself opens none.
- `open_url` is built on the public app base (X-Forwarded-Host/Proto or APP_PUBLIC_URL),
  never on Host: behind Next, Host is the RELAY_URL host. The inner request carries the
  caller's Host and X-Forwarded-* unchanged, so a route that reads them (bio public URLs)
  answers as it would to the caller.
- The inner request's client address is the caller's real one (`client_addr`), not
  ASGITransport's 127.0.0.1 — loopback is a trusted proxy, and every caller would share one
  throttle bucket.

Results never raise: a refused tool, bad args or a non-2xx answer come back as
`{"error": {"status", "detail"}, "open_url"}`. `effect="send"` is refused until the plan
executor runs approved plan steps (ticket 13).

A 2xx write whose answer fails the tool's `check` (args silently dropped) is a 502 error result,
never success.
"""
from __future__ import annotations

import asyncio
import contextvars
import os
from dataclasses import dataclass
from typing import Any, Mapping

import httpx
from fastapi import Request

import client_addr
import toolbox_decide as td

SEND_REFUSED = "send tools run only from an owner-approved plan"


@dataclass(frozen=True)
class Creds:
    """The caller's credential, copied onto every inner request: an `Authorization: Bearer
    ifw_…` owner token (MCP) or the browser's Cookie (in-app). Never X-Employee-Id.
    `host` + `forwarded_*`: the caller's own (bio public URLs; `open_url` uses forwarded_*
    only); `client_host`: the caller's real address."""
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


async def _send(req: td.Request, creds: Creds) -> tuple[int, Any]:
    import server  # the app this process serves; imported late (server imports the API modules)
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=False,
                                    client=(creds.client_host or "127.0.0.1", 0))
    async with httpx.AsyncClient(transport=transport, base_url="http://relay.internal", timeout=None) as c:
        r = await c.request(req.method, req.path, params=req.query or None, json=req.json,
                            headers={**creds.headers(), **req.headers})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


async def call(t: td.Tool, args: Mapping[str, Any], creds: Creds) -> dict[str, Any]:
    """Run tool `t` with `args` as `creds`' owner; the shaped result, never a raise."""
    base = creds.public_base()
    raw_args = dict(args)
    if t.effect == "send":
        return {**td.error(403, SEND_REFUSED), "open_url": td.open_url(base, t.open, raw_args, None)}
    try:
        parsed = td.validate_args(t, args)
        req = td.build_request(t, parsed)
    except td.ArgsError as e:
        return {**td.error(422, {"detail": "invalid arguments", "errors": e.errors}),
                "open_url": td.open_url(base, t.open, raw_args, None)}
    status, body = await _isolated(req, creds)
    url = td.open_url(base, t.open, parsed, body)
    if t.check is not None and 200 <= status < 300 and (why := t.check(parsed, body)):
        return {**td.error(502, {"detail": why}), "open_url": url}
    return {**td.shape_result(t, status, body, base=base), "open_url": url}


async def _isolated(req: td.Request, creds: Creds) -> tuple[int, Any]:
    # An empty Context: the inner request neither sees nor sets the caller's identity.
    return await asyncio.create_task(_send(req, creds), context=contextvars.Context())
