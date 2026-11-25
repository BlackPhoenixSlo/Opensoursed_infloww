from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from urllib.parse import urlsplit


class Hold:

    def __init__(self, match, method: str):
        self.match, self.method, self.on = match, method, True
        self.seen, self.release, self.bodies = asyncio.Event(), asyncio.Event(), []

    async def __call__(self, route):
        if route.request.method == self.method:
            self.bodies.append(route.request.post_data_json)
            if self.on:
                self.on = False
                self.seen.set()
                await self.release.wait()
        await route.fallback()


@asynccontextmanager
async def held(page, match, method: str):
    h = Hold(match, method)
    await page.route(match, h)
    try:
        yield h
    finally:
        h.release.set()
        await page.unroute(match, h)


async def release_settled(page, hold: Hold, refetch: str | None = None, save=None,
                          timeout_ms: float = 120_000) -> int:
    is_held = lambda x: x.request.method == hold.method and hold.match(x.url)  # noqa: E731
    is_refetch = lambda x: x.request.method == "GET" and urlsplit(x.url).path == refetch  # noqa: E731
    async with page.expect_response(is_held, timeout=timeout_ms) as resp:
        if refetch is None:
            hold.release.set()
        else:
            async with page.expect_response(is_refetch, timeout=timeout_ms) as again:
                hold.release.set()
            await again.value
    status = (await resp.value).status
    if save is not None:
        await page.wait_for_function("(b) => b && !b.disabled", arg=await save.element_handle(), timeout=timeout_ms)
    await page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    return status


@contextmanager
def recorded(page, method: str, path: str):
    sent: list[dict] = []
    reqs: list = []

    def on_request(r) -> None:
        if r.method == method and urlsplit(r.url).path == path:
            reqs.append(r)
            sent.append({"url": r.url, "body": r.post_data_json, "status": None})

    def settle(r, status, *, unanswered_only: bool = False) -> None:
        for q, x in zip(reqs, sent):
            if q is r and not (unanswered_only and x["status"] is not None):
                x["status"] = status

    on_response = lambda r: settle(r.request, r.status)  # noqa: E731
    on_failed = lambda r: settle(r, f"failed: {r.failure}", unanswered_only=True)  # noqa: E731
    page.on("request", on_request)
    page.on("response", on_response)
    page.on("requestfailed", on_failed)
    try:
        yield sent
    finally:
        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)
        page.remove_listener("requestfailed", on_failed)
