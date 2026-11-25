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

    def __init__(self, cdp):
        self.reqs: dict[str, dict] = {}
        self.order: list[str] = []
        self._off: float | None = None
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
        account = next((v for k, v in (e["request"].get("headers") or {}).items() if k.lower() == "x-account-id"), None)
        self.reqs[rid] = {"path": path, "method": e["request"]["method"], "kind": _kind(u.path, e.get("type", "")),
                          "start": self._wall(e["timestamp"]), "end": None, "resp": None, "status": None, "bytes": 0,
                          "cached": False, "failed": None, "account": account}

    def _resp(self, e: dict) -> None:
        r = self.reqs.get(e["requestId"])
        if r is not None:
            r["status"] = e["response"]["status"]
            r["resp"] = self._wall(e["timestamp"])
            r["cached"] = bool(e["response"].get("fromDiskCache") or e["response"].get("fromMemoryCache"))
            if r["kind"] == "html":
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
