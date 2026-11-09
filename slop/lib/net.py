"""Named phone networks for a browser page, and a meter of what a screen costs on one.

PROFILES (round trip, down / up; measured 2026-11-05: the AE client's iPhone in Tokyo saw 250 ms to the
Düsseldorf host, Slovenia 25 ms):
  si          25 ms, no bandwidth cap (the owner's own line, "feels instant")
  jp          250 ms, no cap
  jp-mobile   250 ms, 1.6 Mbit/s down / 750 kbit/s up (Lighthouse's slow 4G, as dashboard-load's slow4g)
  jp-bad      400 ms, 1 Mbit/s down / 1 Mbit/s up (a guess at a congested cell; up = down, no measurement)

Wire profiles (`"wire": True`, excluded from DEFAULT_PROFILES; their budgets live in slow-connections):
  jp-lossy      250 ms, 1.6 Mbit/s down / 750 kbit/s up, 2 % loss per packet each way (a guess at the Tokyo
                phone's line: its browser saw calls at p50 5 s, p95 67 s, worst 118 s, which no CDP profile shows)
  jp-lossy-bad  400 ms, 1 / 1 Mbit/s, 5 % loss each way (a guess at a congested cell)

`await emulate(cdp, profile)`: `Network.enable` + `Network.emulateNetworkConditions` on a page's CDP
session (latency = rtt_ms; throughput in bytes/s; `cellular4g` when capped, else `wifi`). Keep the session
open for the page's life: the conditions belong to it. CDP's latency is per request (each response's headers
held `latency` ms): no TCP / TLS handshake RTTs and no TCP slow start, unlike lib/wan.py's DelayProxy (a fresh
connection pays 3 RTTs there), which dashboard-load keeps. CDP's `packetLoss` applies only to WebRTC. A wire
profile is handled by the scenario, which enables CDP events while lib/netloss.py shapes TCP.

`Meter(cdp)`: every request the page sends, from CDP's Network events (`requestWillBeSent`, `responseReceived`,
`loadingFinished` / `loadingFailed`; one clock: CDP's monotonic stamps moved onto the epoch by the first
`wallTime`). `mark()` opens a window; `window()` lists the requests since it (path, method, status, bytes =
`encodedDataLength` (0 from the HTTP cache), start / end ms from the mark, kind: html js css img api (/api/of/)
relay sse beacon other); `await settled(page, key, ...)`: time-to-settled from the mark = the later of the key
showing (a CSS selector, or a JS predicate `() => ...`) and the last network activity followed by `idle_ms` of none;
not counted (listed in the window, not in requests / bytes / settled): the open SSE stream (`/events`) and the perf
log's beacon (`/admin/perflog/ingest`: app/lib/perfLog.ts's 10 s flush timer, whatever the user does; measured
landing 1.2 s after si's creators rows, 20261105T165728Z-...-7e07). A request sent before the mark is not the
window's: settle (network quiet) before marking.
"""
from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import urlsplit

PROFILES: dict[str, dict] = {
    "si": {"rtt_ms": 25, "down_kbps": None, "up_kbps": None},
    "jp": {"rtt_ms": 250, "down_kbps": None, "up_kbps": None},
    "jp-mobile": {"rtt_ms": 250, "down_kbps": 1_600, "up_kbps": 750},
    "jp-bad": {"rtt_ms": 400, "down_kbps": 1_000, "up_kbps": 1_000},
    "jp-lossy": {"rtt_ms": 250, "down_kbps": 1_600, "up_kbps": 750, "plr": 0.02, "wire": True},
    "jp-lossy-bad": {"rtt_ms": 400, "down_kbps": 1_000, "up_kbps": 1_000, "plr": 0.05, "wire": True},
}
SSE_PATHS = (re.compile(r"/events"),)
BEACON_PATHS = (re.compile(r"/admin/perflog/"),)


def is_wire(profile: str | None) -> bool:
    return bool(profile and PROFILES[profile].get("wire"))


DEFAULT_PROFILES = tuple(p for p in PROFILES if not is_wire(p))


async def emulate(cdp, profile: str) -> dict:
    """Throttle the page behind `cdp` to `profile`; returns the conditions sent."""
    p = PROFILES[profile]
    if is_wire(profile):
        raise ValueError(f"wire profile {profile} needs a shaped edge port")
    capped = p["down_kbps"] is not None
    cond = {"offline": False, "latency": p["rtt_ms"],
            "downloadThroughput": p["down_kbps"] * 1000 / 8 if capped else -1,
            "uploadThroughput": p["up_kbps"] * 1000 / 8 if capped else -1,
            "connectionType": "cellular4g" if capped else "wifi"}
    await cdp.send("Network.enable")
    await cdp.send("Network.emulateNetworkConditions", cond)
    return cond


def _kind(path: str, rtype: str) -> str:
    if rtype == "EventSource" or any(rx.match(path) for rx in SSE_PATHS):
        return "sse"
    if any(rx.match(path) for rx in BEACON_PATHS):
        return "beacon"
    if rtype == "Document":
        return "html"
    if rtype == "Script" or path.endswith(".js"):
        return "js"
    if rtype == "Stylesheet" or path.endswith(".css"):
        return "css"
    if rtype == "Image" or path.startswith("/img"):
        return "img"
    if path.startswith("/api/of/"):
        return "api"
    if rtype in ("Fetch", "XHR"):
        return "relay"
    return "other"


class Meter:
    """Every request the page behind `cdp` sends (Network must be enabled on it: `emulate` does)."""

    def __init__(self, cdp):
        self.reqs: dict[str, dict] = {}
        self.order: list[str] = []
        self._off: float | None = None  # epoch s - CDP monotonic s
        self.t0 = time.time()
        cdp.on("Network.requestWillBeSent", self._sent)
        cdp.on("Network.responseReceived", self._resp)
        cdp.on("Network.loadingFinished", self._done)
        cdp.on("Network.loadingFailed", self._failed)

    def _wall(self, ts: float) -> float:
        return ts + self._off

    def _sent(self, e: dict) -> None:
        if self._off is None:
            self._off = e["wallTime"] - e["timestamp"]
        u = urlsplit(e["request"]["url"])
        if u.scheme not in ("http", "https"):
            return
        path = u.path + (f"?{u.query}" if u.query else "")
        rid = e["requestId"]
        if rid not in self.reqs:
            self.order.append(rid)
        self.reqs[rid] = {"path": path, "method": e["request"]["method"], "kind": _kind(u.path, e.get("type", "")),
                          "start": self._wall(e["timestamp"]), "end": None, "resp": None, "status": None, "bytes": 0,
                          "cached": False, "failed": None}

    def _resp(self, e: dict) -> None:
        r = self.reqs.get(e["requestId"])
        if r is not None:
            r["status"] = e["response"]["status"]
            r["resp"] = self._wall(e["timestamp"])  # its headers: the first byte (end: the last)
            r["cached"] = bool(e["response"].get("fromDiskCache") or e["response"].get("fromMemoryCache"))
            if r["kind"] == "html":  # a document's caching (a signed-in page's HTML carries that user's answers)
                r["cache_control"] = {k.lower(): v for k, v in e["response"].get("headers", {}).items()}.get("cache-control")

    def _done(self, e: dict) -> None:
        r = self.reqs.get(e["requestId"])
        if r is not None:
            r["end"], r["bytes"] = self._wall(e["timestamp"]), int(e.get("encodedDataLength") or 0)

    def _failed(self, e: dict) -> None:
        r = self.reqs.get(e["requestId"])
        if r is not None:
            r["end"], r["failed"] = self._wall(e["timestamp"]), e.get("errorText") or "failed"

    def mark(self) -> None:
        self.t0 = time.time()

    def window(self) -> list[dict]:
        """The requests since the mark, in send order; ms relative to it."""
        out = []
        for rid in self.order:
            r = self.reqs[rid]
            if r["start"] < self.t0:
                continue
            out.append({**r, "start": round((r["start"] - self.t0) * 1000),
                        "end": None if r["end"] is None else round((r["end"] - self.t0) * 1000),
                        "resp": None if r["resp"] is None else round((r["resp"] - self.t0) * 1000)})
        return out

    @staticmethod
    def counted(r: dict) -> bool:
        return r["kind"] not in ("sse", "beacon")

    @staticmethod
    def table(reqs: list[dict]) -> dict:
        by: dict[str, list[int]] = {}
        for r in reqs:
            n_b = by.setdefault(r["kind"], [0, 0])
            n_b[0] += 1
            n_b[1] += r["bytes"]
        return {k: {"n": v[0], "kb": round(v[1] / 1024, 1)} for k, v in sorted(by.items())}

    async def settled(self, page, key: str, idle_ms: int = 1500, timeout_ms: int = 120_000) -> dict:
        """Wait until `key` shows and the network went `idle_ms` quiet (SSE and the beacon aside). Returns
        settled_ms (None: timed out), key_ms, requests, bytes, by_kind, pending (paths still open at the end)."""
        js = key.lstrip().startswith(("(", "function", "async"))
        key_ms = None
        end = time.time() + timeout_ms / 1000
        while True:
            now = time.time()
            if key_ms is None:
                try:
                    ok = await (page.evaluate(key) if js else page.locator(key).first.is_visible())
                except Exception:  # noqa: BLE001  mid-navigation: not yet
                    ok = False
                if ok:
                    key_ms = round((time.time() - self.t0) * 1000)
            win = [r for r in self.window() if self.counted(r)]
            pending = [r["path"] for r in win if r["end"] is None]
            last = max((r["end"] for r in win if r["end"] is not None), default=0)
            last = max(last, max((r["start"] for r in win), default=0))
            quiet = (now - self.t0) * 1000 - last
            if key_ms is not None and not pending and quiet >= idle_ms:
                break
            if now > end:
                break
            await asyncio.sleep(0.1)
        win = [r for r in self.window() if self.counted(r)]
        done = key_ms is not None and not pending and quiet >= idle_ms
        return {"settled_ms": max(key_ms, last) if done else None, "key_ms": key_ms, "requests": len(win),
                "bytes": sum(r["bytes"] for r in win), "by_kind": self.table(win), "pending": pending[:20]}
