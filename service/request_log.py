from __future__ import annotations

import logging
import os
import re
import secrets
import time

from auth import get_request_user
from chatters import get_request_chatter

log = logging.getLogger("of-relay")
_SKIP = frozenset({"/livez", "/health"})
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _clean(raw: bytes | None, cap: int = 64) -> str:
    return _UNSAFE.sub("", (raw or b"").decode("latin-1"))[:cap]


def _slow_ms() -> float:
    try:
        return float(os.environ.get("CHATTERLY_SLOW_REQ_MS", "1000"))
    except ValueError:
        return 1000.0


class RequestLog:
    def __init__(self, app, redact=lambda path: path):
        self.app, self.redact = app, redact

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in _SKIP:
            return await self.app(scope, receive, send)
        hdrs = dict(scope["headers"])
        rid = _clean(hdrs.get(b"x-request-id")) or secrets.token_hex(5)
        scope.setdefault("state", {})["request_id"] = rid
        t0, done, status, stream = time.perf_counter(), None, 500, False

        async def send_wrap(msg):
            nonlocal done, status, stream
            if msg["type"] == "http.response.start":
                status = msg["status"]
                stream = any(k.lower() == b"content-type" and v.startswith(b"text/event-stream")
                             for k, v in msg.get("headers", ()))
                msg = {**msg, "headers": [*msg.get("headers", ()), (b"x-request-id", rid.encode())]}
            elif msg["type"] == "http.response.body" and not msg.get("more_body", False):
                done = time.perf_counter()
            await send(msg)

        try:
            await self.app(scope, receive, send_wrap)
        finally:
            ms = ((done or time.perf_counter()) - t0) * 1000
            route = scope.get("route")
            path = getattr(route, "path_format", None) or getattr(route, "path", None) \
                or self.redact(scope["path"])
            params = scope.get("path_params") or {}
            user, chatter = get_request_user(), get_request_chatter()
            extra = {"user": user and user.id, "chatter": chatter and chatter.id,
                     "acct": _clean(str(params.get("account_id") or params.get("aid") or "").encode())
                     or _clean(hdrs.get(b"x-account-id")),
                     "stream": stream and "1"}
            tail = "".join(f" {k}={v}" for k, v in extra.items() if v)
            level = logging.WARNING if not stream and ms > _slow_ms() else logging.INFO
            log.log(level, "req id=%s method=%s path=%s status=%s ms=%.1f%s",
                    rid, scope["method"], path, status, ms, tail)
