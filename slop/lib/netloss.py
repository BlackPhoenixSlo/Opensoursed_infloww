"""Machine-wide macOS packet-loss shaping for slop wire profiles.

The caller holds wire_lock through stack teardown; the root helper serializes its own
on/off operations in case sudo outlives a timed-out Python caller.
Install the NOPASSWD root helper once with slop/install-netloss. It shapes real TCP on
the loopback edge port, including handshake, retransmission, and open streams.
"""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from slop.lib.net import PROFILES, is_wire

HELPER = Path("/usr/local/libexec/slop-netloss")       # root:wheel 0755, a copy of HELPER_SRC
HELPER_SRC = Path(__file__).with_name("netloss_helper.sh")
WIRE_STATE = Path("/var/run/slop-netloss.state")       # the helper's: exists while shaping may be on
INSTALL = "sudo slop/install-netloss"
# The dummynet pipes and anchor are machine-wide while the machine gate lets several runs go at once: a wire run holds
# this flock from before its stack until after teardown (`wire_lock`), so two never overlap, and `wire_off_stale`
# touches the state only when it can take the lock (no live wire run owns it). A killed holder's flock dies with it.
WIRE_LOCK = Path("/tmp/slop-netloss.lock")
WIRE_LOCK_POLL_S = 5
_lock_held = False


class WireError(RuntimeError):
    """The root helper could not complete a wire operation."""


def _checked(*args: str) -> str:
    try:
        # Allow more than the helper's 120 s operation-lock wait before timing out sudo.
        r = subprocess.run(["sudo", "-n", str(HELPER), *args], capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired as e:
        raise WireError(f"slop-netloss {args[0]} timed out; helper may still be running") from e
    if r.returncode:
        raise WireError(f"slop-netloss {args[0]} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def _open_lock() -> int:
    return os.open(WIRE_LOCK, os.O_RDWR | os.O_CREAT, 0o666)


def wire_problem() -> str | None:
    """None when wire mode can run; else one line naming what to do."""
    if not HELPER.exists():
        return f"wire profiles need the packet-loss helper (not installed); run once: {INSTALL}"
    if HELPER.read_bytes() != HELPER_SRC.read_bytes():
        return f"{HELPER} differs from {HELPER_SRC.name} (changed since installed); re-run: {INSTALL}"
    st = HELPER.stat()
    if st.st_uid != 0 or st.st_mode & 0o022:
        return f"{HELPER} is not root-owned 0755; re-run: {INSTALL}"
    try:
        _checked("status")
    except WireError as e:
        return f"{e}; re-run: {INSTALL}"
    return None


def _off_preserving_termination() -> None:
    exc = sys.exc_info()[1]  # unwinding a termination (KeyboardInterrupt, CancelledError, cli's RunTerminated):
    terminating = exc is not None and not isinstance(exc, Exception)  # log a failing off, never mask it
    try:
        _checked("off")
    except WireError as e:
        if terminating:
            print(f"slop: wire teardown during termination: {e}", flush=True)
        else:
            raise


class WireBusy(RuntimeError):
    """The wire lock stayed held past the wait budget: the run is INFRA."""


def _try_lock(fd: int) -> bool:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


@contextlib.contextmanager
def wire_lock(profile: str, *, wait: bool = True):
    """Hold the machine-wide wire lock through teardown. Poll up to SLOP_WIRE_LOCK_WAIT_S (default 900 s);
    --no-wait attempts once. slop/run takes its machine-gate slot first, so a waiting wire run holds one slot."""
    global _lock_held
    fd = _open_lock()
    t0, budget, said = time.monotonic(), float(os.environ.get("SLOP_WIRE_LOCK_WAIT_S") or 900) if wait else 0, False
    try:
        while not _try_lock(fd):
            if time.monotonic() - t0 >= budget:
                raise WireBusy(f"{WIRE_LOCK} still held after {budget:.0f}s (another wire run): SLOP_WIRE_LOCK_WAIT_S")
            if not said:
                holder = os.pread(fd, 512, 0).decode(errors="replace").strip()
                print(f"slop: waiting for the wire lock {WIRE_LOCK} (another wire run: {holder or '?'})", flush=True)
                said = True
            time.sleep(min(WIRE_LOCK_POLL_S, max(0, budget - (time.monotonic() - t0))))
        _lock_held = True
        try:
            os.ftruncate(fd, 0)
            os.pwrite(fd, f"pid {os.getpid()} --net={profile} since {time.strftime('%Y-%m-%dT%H:%M:%S')}\n".encode(), 0)
            yield round(time.monotonic() - t0, 1)
        finally:
            try:
                _off_preserving_termination()
            finally:
                _lock_held = False
    finally:
        os.close(fd)  # releases the flock only after teardown


def _stale_off() -> str:
    return f"stale packet-loss shaping switched off: {_checked('off')}"


def wire_off_stale() -> str | None:
    """A killed run's shaping left on: off while holding the wire lock."""
    if not WIRE_STATE.exists():
        return None
    if not HELPER.exists():
        raise WireError(f"{WIRE_STATE} exists but {HELPER} is gone: shaping may be on; reinstall: {INSTALL}")
    fd = _open_lock()
    try:
        if not _try_lock(fd):
            return None
        return _stale_off()
    finally:
        os.close(fd)


@contextlib.contextmanager
def guard(profile: str | None, *, wait: bool = True):
    """Own wire cleanup around the run's gate slot; report lock wait and stale cleanup."""
    if is_wire(profile):
        with wire_lock(profile, wait=wait) as waited:
            facts = {"wire_lock_wait_s": waited}
            if WIRE_STATE.exists():
                facts["net_wire_stale"] = _stale_off()
            yield facts
    else:
        stale = wire_off_stale()
        yield {"net_wire_stale": stale} if stale else {}


@contextlib.contextmanager
def wired(profile: str, ports: list[int]):
    """Dummynet on `ports` (the edge the browser talks to) for `profile`; yields the helper's status text."""
    p = PROFILES[profile]
    if not _lock_held:
        raise WireError("wired requires the wire lock")
    try:
        status = _checked("on", ",".join(map(str, ports)), str(p["rtt_ms"]), str(p.get("plr", 0)),
                          str(p["down_kbps"] or 0), str(p["up_kbps"] or 0))
        yield status
    finally:
        if _lock_held:
            _off_preserving_termination()


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
