"""Timed HTTP client for actors. Every call is recorded (route label, status,
latency), so the stock invariants (no 5xx, p95 per route) need no extra code."""
from __future__ import annotations

import re
import time
from collections import defaultdict

import httpx

_NUM = re.compile(r"/\d+(?=/|$)")


def label(method: str, path: str) -> str:
    return f"{method} {_NUM.sub('/:id', path.split('?')[0])}"


class Recorder:
    def __init__(self) -> None:
        self.calls: dict[str, list[tuple[int, float]]] = defaultdict(list)
        self.errors: list[str] = []
        # Optional phase tag (e.g. a load stage): calls are also kept per tag.
        self.stage: str | None = None
        self.by_stage: dict[str, dict[str, list[tuple[int, float]]]] = defaultdict(lambda: defaultdict(list))

    def add(self, route: str, status: int, ms: float) -> None:
        self.calls[route].append((status, ms))
        if self.stage is not None:
            self.by_stage[self.stage][route].append((status, ms))

    def summary(self, stage: str | None = None) -> dict:
        out = {}
        calls = self.by_stage.get(stage, {}) if stage is not None else self.calls
        for k, v in sorted(calls.items()):
            lat = sorted(ms for _, ms in v)
            out[k] = {"n": len(v), "5xx": sum(1 for s, _ in v if s >= 500), "4xx": sum(1 for s, _ in v if 400 <= s < 500),
                      "p50_ms": round(lat[len(lat) // 2], 1), "p95_ms": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 1)}
        return out

    def count(self, pred) -> int:
        return sum(1 for v in self.calls.values() for s, _ in v if pred(s))


class Http:
    """One signed-in session (cookie jar) against the relay."""

    def __init__(self, base: str, rec: Recorder, *, limits: int = 100):
        self.rec = rec
        self.c = httpx.AsyncClient(base_url=base, timeout=30,
                                   limits=httpx.Limits(max_connections=limits, max_keepalive_connections=limits))

    async def request(self, method: str, path: str, **kw) -> httpx.Response:
        t0 = time.perf_counter()
        try:
            r = await self.c.request(method, path, **kw)
        except httpx.HTTPError as e:
            self.rec.add(label(method, path), 599, (time.perf_counter() - t0) * 1000)
            self.rec.errors.append(f"{method} {path}: {type(e).__name__} {e} "
                                   f"(cause {e.__cause__ or e.__context__!r}; stage {self.rec.stage})")
            raise
        self.rec.add(label(method, path), r.status_code, (time.perf_counter() - t0) * 1000)
        if r.status_code >= 400 and len(self.rec.errors) < 50:
            self.rec.errors.append(f"{method} {path} -> {r.status_code} {r.text[:200]}")
        return r

    async def get(self, path: str, **kw) -> httpx.Response:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, **kw) -> httpx.Response:
        return await self.request("POST", path, **kw)

    def share(self, rec: Recorder | None = None, limits: int = 100) -> "Http":
        """A second client on the same session (e.g. one per actor pool)."""
        h = Http(str(self.c.base_url), rec or self.rec, limits=limits)
        h.c.cookies = self.c.cookies
        return h

    async def aclose(self) -> None:
        await self.c.aclose()
