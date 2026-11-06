"""Named phone networks for a browser page, and a meter of what a screen costs on one.

PROFILES (round trip, down / up; measured 2026-11-05: the AE client's iPhone in Tokyo saw 250 ms to the
Düsseldorf host, Slovenia 25 ms):
  si          25 ms, no bandwidth cap (the owner's own line, "feels instant")
  jp          250 ms, no cap
  jp-mobile   250 ms, 1.6 Mbit/s down / 750 kbit/s up (Lighthouse's slow 4G, as dashboard-load's slow4g)
  jp-bad      400 ms, 1 Mbit/s down / 1 Mbit/s up (a guess at a congested cell; up = down, no measurement)

Wire profiles (`"wire": True`, never in DEFAULT_PROFILES until their budgets are set from a green run):
  jp-lossy      250 ms, 1.6 Mbit/s down / 750 kbit/s up, 2 % loss per packet each way (a guess at the Tokyo
                phone's line: its browser saw calls at p50 5 s, p95 67 s, worst 118 s, which no CDP profile shows)
  jp-lossy-bad  400 ms, 1 / 1 Mbit/s, 5 % loss each way (a guess at a congested cell)

`await emulate(cdp, profile)`: `Network.enable` + `Network.emulateNetworkConditions` on a page's CDP
session (latency = rtt_ms; throughput in bytes/s; `cellular4g` when capped, else `wifi`). Keep the session
open for the page's life: the conditions belong to it. CDP's latency is per request (each response's headers
held `latency` ms): no TCP / TLS handshake RTTs and no TCP slow start, unlike lib/wan.py's DelayProxy (a fresh
connection pays 3 RTTs there), which dashboard-load keeps. CDP's `packetLoss` applies only to WebRTC. A wire
profile gets `Network.enable` only (the Meter's events): its delay, bandwidth and loss are all the kernel's.

Wire mode: `with wired(profile, ports) as status:` shapes loopback TCP to / from `ports` with macOS dummynet through
the root helper (slop/lib/netloss_helper.sh, installed once by `sudo slop/install-netloss` as HELPER, NOPASSWD for
that path only): real TCP, so handshakes, slow start, retransmits and head-of-line blocking on one h2 connection,
and the open /events stream is delayed too. A stale state is switched off first; off again on exit (finally and
atexit; a SIGKILLed run's state is switched off by the next run's `wire_off_stale`, lib/cli.py, inside the machine
lock). `wire_lock(profile)` (lib/cli.py, around a wire run): one wire run per machine. `wire_problem()`: why wire mode cannot run here (one line naming the install command), or None.
`await calibrate(port)`: TCP connect times through the shaped port (one RTT each).

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
import atexit
import contextlib
import fcntl
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

PROFILES: dict[str, dict] = {
    "si": {"rtt_ms": 25, "down_kbps": None, "up_kbps": None},
    "jp": {"rtt_ms": 250, "down_kbps": None, "up_kbps": None},
    "jp-mobile": {"rtt_ms": 250, "down_kbps": 1_600, "up_kbps": 750},
    "jp-bad": {"rtt_ms": 400, "down_kbps": 1_000, "up_kbps": 1_000},
    "jp-lossy": {"rtt_ms": 250, "down_kbps": 1_600, "up_kbps": 750, "plr": 0.02, "wire": True},
    "jp-lossy-bad": {"rtt_ms": 400, "down_kbps": 1_000, "up_kbps": 1_000, "plr": 0.05, "wire": True},
}
DEFAULT_PROFILES = tuple(p for p, v in PROFILES.items() if not v.get("wire"))
HELPER = Path("/usr/local/libexec/slop-netloss")       # root:wheel 0755, a copy of HELPER_SRC
HELPER_SRC = Path(__file__).with_name("netloss_helper.sh")
WIRE_STATE = Path("/var/run/slop-netloss.state")       # the helper's: exists while shaping may be on
INSTALL = "sudo slop/install-netloss"
# The dummynet pipes and anchor are machine-wide while the machine gate lets several runs go at once: a wire run holds
# this flock from before its stack until after teardown (`wire_lock`), so two never overlap, and `wire_off_stale`
# touches the state only when it can take the lock (no live wire run owns it). A killed holder's flock dies with it.
WIRE_LOCK = Path("/tmp/slop-netloss.lock")
WIRE_LOCK_POLL_S = 5
SSE_PATHS = (re.compile(r"/events"),)
BEACON_PATHS = (re.compile(r"/admin/perflog/"),)


def is_wire(profile: str | None) -> bool:
    return bool(profile and PROFILES[profile].get("wire"))


def _helper(*args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["sudo", "-n", str(HELPER), *args], capture_output=True, text=True, timeout=timeout)


def wire_problem() -> str | None:
    """None when wire mode can run; else one line naming what to do."""
    if not HELPER.exists():
        return f"wire profiles need the packet-loss helper (not installed); run once: {INSTALL}"
    if HELPER.read_bytes() != HELPER_SRC.read_bytes():
        return f"{HELPER} differs from {HELPER_SRC.name} (changed since installed); re-run: {INSTALL}"
    st = HELPER.stat()
    if st.st_uid != 0 or st.st_mode & 0o022:
        return f"{HELPER} is not root-owned 0755; re-run: {INSTALL}"
    r = _helper("status")
    if r.returncode:
        return f"sudo -n {HELPER} status failed ({(r.stderr or r.stdout).strip()[:160]}); re-run: {INSTALL}"
    return None


def wire_off() -> str:
    r = _helper("off")
    if r.returncode:
        raise RuntimeError(f"slop-netloss off failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def _off_quiet() -> None:
    with contextlib.suppress(Exception):
        if WIRE_STATE.exists():
            wire_off()


class WireBusy(RuntimeError):
    """The wire lock stayed held past the wait budget: the run is INFRA."""


def _try_lock(fd: int) -> bool:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


@contextlib.contextmanager
def wire_lock(profile: str | None):
    """Held for a wire profile's whole run (a no-op for any other): one wire run per machine. Waits (polling, one line
    printed) up to SLOP_LOCK_WAIT_S (default 3600 s), then raises WireBusy. Yields the seconds waited."""
    if not is_wire(profile):
        yield 0.0
        return
    fd = os.open(WIRE_LOCK, os.O_RDWR | os.O_CREAT, 0o666)
    t0, budget, said = time.monotonic(), float(os.environ.get("SLOP_LOCK_WAIT_S") or 3600), False
    try:
        while not _try_lock(fd):
            if time.monotonic() - t0 > budget:
                raise WireBusy(f"{WIRE_LOCK} still held after {budget:.0f}s (another wire run): SLOP_LOCK_WAIT_S")
            if not said:
                holder = os.pread(fd, 512, 0).decode(errors="replace").strip()
                print(f"slop: waiting for the wire lock {WIRE_LOCK} (another wire run: {holder or '?'})", flush=True)
                said = True
            time.sleep(WIRE_LOCK_POLL_S)
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"pid {os.getpid()} --net={profile} since {time.strftime('%Y-%m-%dT%H:%M:%S')}\n".encode(), 0)
        yield round(time.monotonic() - t0, 1)
    finally:
        os.close(fd)  # releases the flock


def wire_off_stale() -> str | None:
    """A killed run's shaping left on (the helper's state file): off. None when there was none, or when a live wire
    run holds the wire lock (its shaping, not stale). Call it outside `wire_lock` (it takes the lock itself)."""
    if not WIRE_STATE.exists():
        return None
    if not HELPER.exists():
        return f"{WIRE_STATE} exists but {HELPER} is gone: shaping may be on; sudo {HELPER_SRC} off"
    fd = os.open(WIRE_LOCK, os.O_RDWR | os.O_CREAT, 0o666)
    try:
        if not _try_lock(fd):
            return None
        return f"stale packet-loss shaping switched off: {wire_off()}"
    finally:
        os.close(fd)


@contextlib.contextmanager
def wired(profile: str, ports: list[int]):
    """Dummynet on `ports` (the edge the browser talks to) for `profile`; yields the helper's status text."""
    p = PROFILES[profile]
    _off_quiet()
    atexit.register(_off_quiet)
    try:
        r = _helper("on", ",".join(map(str, ports)), str(p["rtt_ms"]), str(p.get("plr", 0)),
                    str(p["down_kbps"] or 0), str(p["up_kbps"] or 0))
        if r.returncode:
            raise RuntimeError(f"slop-netloss on failed: {(r.stderr or r.stdout).strip()[:300]}")
        yield r.stdout
    finally:
        try:
            wire_off()
        finally:
            atexit.unregister(_off_quiet)


async def calibrate(port: int, n: int = 10, timeout_s: float = 10) -> dict:
    """TCP connects to 127.0.0.1:`port` (SYN up, SYN-ACK down: one shaped RTT each, loss included): ms each, the
    median, and how many timed out."""
    def one() -> float | None:
        t0 = time.perf_counter()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout_s):
                return (time.perf_counter() - t0) * 1000
        except OSError:
            return None
    got = [await asyncio.to_thread(one) for _ in range(n)]
    ok = sorted(x for x in got if x is not None)
    return {"connect_ms": [None if x is None else round(x, 1) for x in got],
            "median_ms": round(ok[len(ok) // 2], 1) if ok else None, "failed": n - len(ok)}


async def emulate(cdp, profile: str) -> dict:
    """Throttle the page behind `cdp` to `profile`; returns the conditions sent. A wire profile: Network.enable
    only (dummynet shapes the edge's port, `wired`)."""
    p = PROFILES[profile]
    if p.get("wire"):
        await cdp.send("Network.enable")
        return {"wire": True, **p}
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
        return ts + (self._off if self._off is not None else time.time() - ts)

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
                          "start": self._wall(e["timestamp"]), "end": None, "status": None, "bytes": 0,
                          "cached": False, "failed": None}

    def _resp(self, e: dict) -> None:
        r = self.reqs.get(e["requestId"])
        if r is not None:
            r["status"] = e["response"]["status"]
            r["cached"] = bool(e["response"].get("fromDiskCache") or e["response"].get("fromMemoryCache"))

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
                        "end": None if r["end"] is None else round((r["end"] - self.t0) * 1000)})
        return out

    @staticmethod
    def _counted(r: dict) -> bool:
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
            win = [r for r in self.window() if self._counted(r)]
            pending = [r["path"] for r in win if r["end"] is None]
            last = max((r["end"] for r in win if r["end"] is not None), default=0)
            last = max(last, max((r["start"] for r in win), default=0))
            quiet = (now - self.t0) * 1000 - last
            if key_ms is not None and not pending and quiet >= idle_ms:
                break
            if now > end:
                break
            await asyncio.sleep(0.1)
        win = [r for r in self.window() if self._counted(r)]
        done = key_ms is not None and not pending and quiet >= idle_ms
        return {"settled_ms": max(key_ms, last) if done else None, "key_ms": key_ms, "requests": len(win),
                "bytes": sum(r["bytes"] for r in win), "by_kind": self.table(win), "pending": pending[:20]}
