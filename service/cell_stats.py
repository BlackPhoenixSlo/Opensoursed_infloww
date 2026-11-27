from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import threading
import time
from pathlib import Path

log = logging.getLogger("of-relay.cell_stats")

ENABLED = bool(os.environ.get("OI_CELL_MAP"))
WINDOW_S = 300
_MIN_S = 60
_CAP = 2000
FILE = "cell-stats.json"

_lock = threading.Lock()
_rng = random.Random(0)
_buckets: dict[int, dict] = {}
_spills = 0
_task: asyncio.Task | None = None


class _Res:
    __slots__ = ("n", "xs")

    def __init__(self) -> None:
        self.n, self.xs = 0, []

    def add(self, x: float) -> None:
        self.n += 1
        if len(self.xs) < _CAP:
            self.xs.append(x)
        else:
            j = _rng.randrange(self.n)
            if j < _CAP:
                self.xs[j] = x


def _bucket(now: float) -> dict:
    m = int(now // _MIN_S)
    b = _buckets.get(m)
    if b is None:
        b = _buckets[m] = {"routes": {}, "pool": _Res(), "spills": _spills}
        for k in [k for k in _buckets if k <= m - WINDOW_S // _MIN_S]:
            del _buckets[k]
    return b


def route(key: str, ms: float) -> None:
    with _lock:
        routes = _bucket(time.time())["routes"]
        r = routes.get(key)
        if r is None:
            r = routes[key] = _Res()
        r.add(ms)


def timed(get):
    def _do_get(pool):
        global _spills
        t0 = time.perf_counter()
        try:
            return get(pool)
        finally:
            ms = (time.perf_counter() - t0) * 1000
            with _lock:
                _spills = pool.spills
                _bucket(time.time())["pool"].add(ms)
    _do_get.cell_stats = True
    return _do_get


def instrument(pool_cls) -> None:
    if not getattr(pool_cls._do_get, "cell_stats", False):
        pool_cls._do_get = timed(pool_cls._do_get)


def _p95(xs: list[float]) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * 0.95))], 1)


def snapshot(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    m = int(now // _MIN_S)
    with _lock:
        live = [b for k, b in _buckets.items() if k > m - WINDOW_S // _MIN_S]
        routes: dict[str, tuple[int, list[float]]] = {}
        for b in live:
            for key, r in b["routes"].items():
                n, xs = routes.get(key, (0, []))
                routes[key] = (n + r.n, xs + r.xs)
        pool = [x for b in live for x in b["pool"].xs]
        waits = sum(b["pool"].n for b in live)
        base = min((b["spills"] for b in live), default=_spills)
        spills = _spills - base
    return {"ts": int(now), "window_s": WINDOW_S, "spills": spills, "pool_waits": waits,
            "pool_wait_p95_ms": _p95(pool),
            "routes": {k: {"n": n, "p95_ms": _p95(xs)} for k, (n, xs) in sorted(routes.items())}}


def write(path: Path) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(snapshot(), sort_keys=True))
    os.replace(tmp, path)


async def _loop(path: Path) -> None:
    while True:
        try:
            await asyncio.to_thread(write, path)
        except Exception:  # noqa: BLE001 — stats must never take the relay with them
            log.exception("cell_stats write failed")
        await asyncio.sleep(_MIN_S)


def start(path: Path) -> None:
    global _task
    if ENABLED and (_task is None or _task.done()):
        _task = asyncio.create_task(_loop(path), name="cell-stats")
