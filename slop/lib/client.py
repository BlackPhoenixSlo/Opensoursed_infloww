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
        # Every call as (end epoch s, route, status, ms), for checks over a time window.
        self.timeline: list[tuple[float, str, int, float]] = []

    def add(self, route: str, status: int, ms: float) -> None:
        self.calls[route].append((status, ms))
        self.timeline.append((time.time(), route, status, ms))
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


# An idle keep-alive connection is reused only below this age. httpx's default (5 s)
# equals uvicorn's timeout_keep_alive (5 s, the Dockerfile's too), so a request can be
# written into a connection the relay is about to time out: after any relay stall the
# relay resets it (httpx ReadError(BrokenResourceError)): a failure httpx never retries,
# while Chromium resends a request whose reused socket fails before any response. Kept
# below 5 s minus the longest stall a scenario injects (2 s), no reset was seen
# (.scratch/fleet-sharding/03-write-storm.md).
KEEPALIVE_EXPIRY_S = 2.0


class Http:
    """One signed-in session (cookie jar) against the relay. `host` sends that Host
    header (a fleet edge routes on it); `prefix` goes in front of every route label
    (e.g. "edge s03 ") so edge calls get their own p95 rows."""

    def __init__(self, base: str, rec: Recorder, *, limits: int = 100, host: str | None = None,
                 prefix: str = "", headers: dict | None = None):
        self.rec, self.host, self.prefix, self.headers = rec, host, prefix, dict(headers or {})
        hdrs = {**self.headers, **({"Host": host} if host else {})}
        self.c = httpx.AsyncClient(base_url=base, timeout=30, headers=hdrs,
                                   limits=httpx.Limits(max_connections=limits, max_keepalive_connections=limits,
                                                       keepalive_expiry=KEEPALIVE_EXPIRY_S))

    async def request(self, method: str, path: str, **kw) -> httpx.Response:
        t0 = time.perf_counter()
        try:
            r = await self.c.request(method, path, **kw)
        except httpx.HTTPError as e:
            self.rec.add(self.prefix + label(method, path), 599, (time.perf_counter() - t0) * 1000)
            self.rec.errors.append(f"{method} {path}: {type(e).__name__} {e} "
                                   f"(cause {e.__cause__ or e.__context__!r}; stage {self.rec.stage})")
            raise
        self.rec.add(self.prefix + label(method, path), r.status_code, (time.perf_counter() - t0) * 1000)
        if r.status_code >= 400 and len(self.rec.errors) < 50:
            self.rec.errors.append(f"{self.prefix}{method} {path} -> {r.status_code} {r.text[:200]}")
        return r

    async def get(self, path: str, **kw) -> httpx.Response:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, **kw) -> httpx.Response:
        return await self.request("POST", path, **kw)

    async def put(self, path: str, **kw) -> httpx.Response:
        return await self.request("PUT", path, **kw)

    def share(self, rec: Recorder | None = None, limits: int = 100) -> "Http":
        """A second client on the same session (e.g. one per actor pool)."""
        h = Http(str(self.c.base_url), rec or self.rec, limits=limits, host=self.host, prefix=self.prefix,
                 headers=self.headers)
        h.c.cookies = self.c.cookies
        return h

    async def aclose(self) -> None:
        await self.c.aclose()
