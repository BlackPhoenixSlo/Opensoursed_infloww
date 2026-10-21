"""One middleware layer for all of the relay's `(request, call_next)` hooks.

`@app.middleware("http")` wraps EACH hook in its own Starlette
`BaseHTTPMiddleware`: a task group, a memory stream between it and the next
layer, and a re-stream of every body chunk through that stream. The relay had
ten, so a trivial request paid ten of those and every chunk of a streamed body
(/img, SSE) crossed ten streams. Measured in process: /livez p50 1.71 ms against 0.21 ms bare, and a
512-chunk stream 65.8 ms against 0.56 ms.

The hooks themselves are cheap; the layers were the cost. `HookChain` keeps
every hook exactly as written and calls them as plain functions inside ONE
`BaseHTTPMiddleware`: each hook's `call_next` is the next hook, and only the
last one crosses into the app. So a request pays one task group and a chunk
one stream, whatever the hook count.

ORDER is Starlette's, so the registration sites and their load-bearing
comments in server.py read the same: the hook added LAST is the OUTERMOST,
the one added first runs closest to the routes.

What changes for a hook, and why none of the relay's hooks mind:
  • They share one `Request` object instead of one each. The audit hook's
    `request.body()` caches the body on it and the app is fed from that cache,
    exactly as its own layer fed it before.
  • A ContextVar an inner hook sets is now visible to an outer hook's code
    after `call_next` (before, the inner layer ran in a child task). No outer
    hook reads one there; `_account_context` resets only its own.
  • A hook sees the inner hook's own Response object rather than a re-streamed
    copy of it. Status, headers and `set_cookie` behave the same on both.
An exception still propagates out of `call_next` to every outer hook, as
`BaseHTTPMiddleware.call_next` re-raised it.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

CallNext = Callable[[Request], Awaitable[Response]]
Hook = Callable[[Request, CallNext], Awaitable[Response]]


class HookChain:
    """Ordered `(request, call_next)` hooks, run inside one middleware layer.

    `add` doubles as a decorator. Register the chain once, with
    `app.add_middleware(BaseHTTPMiddleware, dispatch=chain.dispatch)`; hooks
    added after that still run, because Starlette builds the stack on the
    first request and the chain reads its list per request."""

    def __init__(self) -> None:
        self._hooks: list[Hook] = []   # outermost first

    def add(self, hook: Hook) -> Hook:
        self._hooks.insert(0, hook)    # last added = outermost, as Starlette
        return hook

    @property
    def hooks(self) -> tuple[Hook, ...]:
        """Outermost first: the order a request meets them."""
        return tuple(self._hooks)

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        hooks = self._hooks

        async def step(i: int, req: Request) -> Response:
            if i == len(hooks):
                return await call_next(req)
            return await hooks[i](req, lambda r: step(i + 1, r))

        return await step(0, request)
