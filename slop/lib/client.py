from __future__ import annotations

import re
import time
from collections import defaultdict

import httpx

_NUM = re.compile(r"/\d+(?=/|$)")


def label(method: str, path: str) -> str:
    return f"{method} {_NUM.sub('/:id', path.split('?')[0])}"


async def actor_call(http, kind: str, aid: str, path: str, method: str = "GET", body=None, text=None) -> dict:
    t0 = time.perf_counter()
    try:
        r = await (http.get(path, headers={"X-Account-Id": aid}) if method == "GET"
                   else http.post(path, headers={"X-Account-Id": aid}, json=body))
        status = r.status_code
        detail = r.json().get("detail") if status >= 400 and r.headers.get("content-type", "").startswith(
            "application/json") else None
    except Exception:  # noqa: BLE001  transport error: 599 as the recorder does
        status, detail = 599, None
    t1 = time.perf_counter()
    return {"kind": kind, "aid": aid, "status": status, "ms": (t1 - t0) * 1000, "t0": t0, "t1": t1,
            "text": text, "detail": detail, "unreachable": status == 502 and isinstance(detail, dict)
            and detail.get("upstream_status") == "proxy_unreachable"}


class Recorder:
    def __init__(self) -> None:
        self.calls: dict[str, list[tuple[int, float]]] = defaultdict(list)
        self.errors: list[str] = []
        self.stage: str | None = None
        self.by_stage: dict[str, dict[str, list[tuple[int, float]]]] = defaultdict(lambda: defaultdict(list))
        self.timeline: list[tuple[float, str, int, float]] = []
        self.urls: set[tuple[str, str]] = set()

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


# Reuse idle connections only below uvicorn's 5 s keep-alive minus the longest injected stall (2 s): else the relay resets a reused socket (httpx ReadError, never retried).
KEEPALIVE_EXPIRY_S = 2.0


class Http:

    def __init__(self, base: str, rec: Recorder, *, limits: int = 100, host: str | None = None,
                 prefix: str = "", headers: dict | None = None):
        self.rec, self.host, self.prefix, self.headers = rec, host, prefix, dict(headers or {})
        hdrs = {**self.headers, **({"Host": host} if host else {})}
        self.c = httpx.AsyncClient(base_url=base, timeout=30, headers=hdrs,
                                   limits=httpx.Limits(max_connections=limits, max_keepalive_connections=limits,
                                                       keepalive_expiry=KEEPALIVE_EXPIRY_S))

    async def request(self, method: str, path: str, *, route: str | None = None,
                      expect: tuple[int, ...] = (), **kw) -> httpx.Response:
        route = self.prefix + (route or label(method, path))
        t0 = time.perf_counter()
        try:
            r = await self.c.request(method, path, **kw)
        except httpx.HTTPError as e:
            self.rec.add(route, 599, (time.perf_counter() - t0) * 1000)
            self.rec.errors.append(f"{method} {path}: {type(e).__name__} {e} "
                                   f"(cause {e.__cause__ or e.__context__!r}; stage {self.rec.stage})")
            raise
        self.rec.add(route, r.status_code, (time.perf_counter() - t0) * 1000)
        self.rec.urls.add((f"{r.request.url.host}:{r.request.url.port}", r.request.url.path))
        if r.status_code >= 400 and r.status_code not in expect and len(self.rec.errors) < 50:
            self.rec.errors.append(f"{self.prefix}{method} {path} -> {r.status_code} {r.text[:200]}")
        return r

    async def get(self, path: str, **kw) -> httpx.Response:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, **kw) -> httpx.Response:
        return await self.request("POST", path, **kw)

    async def put(self, path: str, **kw) -> httpx.Response:
        return await self.request("PUT", path, **kw)

    def share(self, rec: Recorder | None = None, limits: int = 100) -> "Http":
        h = Http(str(self.c.base_url), rec or self.rec, limits=limits, host=self.host, prefix=self.prefix,
                 headers=self.headers)
        h.c.cookies = self.c.cookies
        return h

    async def aclose(self) -> None:
        await self.c.aclose()
