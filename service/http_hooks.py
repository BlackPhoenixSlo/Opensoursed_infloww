from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

CallNext = Callable[[Request], Awaitable[Response]]
Hook = Callable[[Request, CallNext], Awaitable[Response]]


class HookChain:

    def __init__(self) -> None:
        self._hooks: list[Hook] = []

    def add(self, hook: Hook) -> Hook:
        self._hooks.insert(0, hook)
        return hook

    @property
    def hooks(self) -> tuple[Hook, ...]:
        return tuple(self._hooks)

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        hooks = self._hooks

        async def step(i: int, req: Request) -> Response:
            if i == len(hooks):
                return await call_next(req)
            return await hooks[i](req, lambda r: step(i + 1, r))

        return await step(0, request)
