#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import contextvars  # noqa: E402

from starlette.requests import Request  # noqa: E402
from starlette.responses import Response  # noqa: E402

import auth  # noqa: E402
import chatters  # noqa: E402


def _anonymous() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/admin/reports/files/x",
                    "query_string": b"", "headers": []})


async def _seen(hook) -> tuple:
    seen = []

    async def route(_request):
        seen.append((auth.get_request_user(), auth._impersonation.get(), auth._request_token.get(),
                     chatters.get_request_chatter()))
        return Response("ok")

    await hook(_anonymous(), route)
    return seen[0]


def _stale_context() -> contextvars.Context:
    ctx = contextvars.Context()
    ctx.run(auth._request_user.set, auth.AuthedUser("u1", "prev", {"1"}, False))
    ctx.run(auth._impersonation.set, auth.Impersonation("u0", "founder", "u1", "prev"))
    ctx.run(auth._request_token.set, (1, "tok"))
    ctx.run(chatters._request_chatter.set, object())
    return ctx


# A keep-alive reader re-arm copies the previous request's ContextVars; hooks must clear identity first (signed-out read leaked a file).
def case_session_hook_clears_the_owner_identities():
    user, imp, tok, _ = _stale_context().run(asyncio.run, _seen(auth.session_middleware))
    assert (user, imp, tok) == (None, None, None), (user, imp, tok)


def case_chatter_hook_clears_the_chatter():
    *_, chatter = _stale_context().run(asyncio.run, _seen(chatters.chatter_session_middleware))
    assert chatter is None, chatter


if __name__ == "__main__":
    _harness.run()
