"""Request and idle traffic summaries for the slow-connections scenario."""
from __future__ import annotations

import re

from slop.lib.net import Meter
from slop.lib.procmon import pct as _p

def route(path: str) -> str:
    """A request's route for the idle table: the query dropped, ids (digit runs) as {n}."""
    return re.sub(r"\d+", "{n}", path.split("?", 1)[0])


def idle(win: list[dict], seconds: float) -> dict:
    """The idle window's requests (SSE and beacon aside) per minute, in total, /img, and by route."""
    reqs = [q for q in win if Meter.counted(q)]
    img = [q for q in reqs if q["path"].startswith("/img")]
    per = 60 / seconds
    by: dict[str, int] = {}
    for q in reqs:
        by[route(q["path"])] = by.get(route(q["path"]), 0) + 1
    return {"seconds": seconds, "requests": len(reqs), "per_min": round(len(reqs) * per, 1), "img": len(img),
            "img_per_min": round(len(img) * per, 1),
            "by_route": dict(sorted(by.items(), key=lambda kv: -kv[1])[:30])}


def thread_reads(reqs: list[dict], wave_gap_ms: float, thread_local) -> dict:
    """The thread open's reads: routes GET more than once (/img aside), the bundle calls, local reads per route, and
    waves (start clusters)."""
    gets = [q for q in reqs if q.get("method", "GET") == "GET" and not q["path"].startswith("/img")]
    by: dict[str, int] = {}
    for q in gets:
        by[q["path"].split("?", 1)[0]] = by.get(q["path"].split("?", 1)[0], 0) + 1
    starts = sorted(q["start"] for q in reqs if q.get("start") is not None)
    waves = sum(1 for i, t in enumerate(starts) if i == 0 or t - starts[i - 1] > wave_gap_ms)
    return {"dupes": {k: v for k, v in by.items() if v > 1},
            "bundle": sum(1 for q in gets if q["path"].startswith("/admin/screens/chat")),
            "local": [q["path"][:160] for q in gets if any(rx.match(q["path"]) for rx in thread_local)],
            "waves": waves}


def req_ms(r: dict) -> dict:
    """One flow's request durations (the SSE stream and the beacon aside): n, p50 / p95 / max ms, the slowest's path,
    how many over 10 s and 60 s, unfinished, and failed (not the page's own ERR_ABORTED)."""
    qs = [q for q in r.get("reqs", []) if q["kind"] not in ("sse", "beacon")]
    done = sorted((q["ms"], q["path"]) for q in qs if q["ms"] is not None)
    ms = [m for m, _ in done]
    return {"n": len(qs), "p50": _p(ms, 0.5), "p95": _p(ms, 0.95), "max": ms[-1] if ms else None,
            "max_path": done[-1][1][:120] if done else None, "over_10s": sum(m > 10_000 for m in ms),
            "over_60s": sum(m > 60_000 for m in ms), "unfinished": len(qs) - len(done),
            "failed": sum(1 for q in qs if q.get("failed") and q["failed"] != "net::ERR_ABORTED")}


def reqs(meter: Meter) -> list[dict]:
    return [{"path": q["path"][:300], "method": q["method"], "kind": q["kind"], "status": q["status"],
             "bytes": q["bytes"], "start": q["start"],
             "ms": None if q["end"] is None else q["end"] - q["start"],
             "ttfb": None if q["resp"] is None else q["resp"] - q["start"],
             "cached": q["cached"], "failed": q["failed"]} for q in meter.window()]
