from __future__ import annotations

import asyncio
import collections
import logging
import threading
import weakref
from typing import Any

# Leaf import: lanes are built at module import, before the loop or DB exist.
import lane_config

log = logging.getLogger("of-relay.admission")


class Lane:

    def __init__(self, name: str, env_var: str, default_cap: int,
                 wait_s: float) -> None:
        self.name = name
        self.env_var = env_var
        # Env var > saved Concurrency-panel value > default; env-overridable so a cap retunes on the VPS without a deploy.
        self.cap = lane_config.resolve(env_var, default_cap)
        self.wait_s = wait_s
        # Bounded so releasing a slot nobody holds raises instead of inflating the ceiling.
        self._sem = threading.BoundedSemaphore(self.cap)
        self._lock = threading.Lock()
        self.busy = 0
        self.rejected = 0
        self._waiters: collections.deque[asyncio.Future] = collections.deque()

    def enter(self, label: str = "") -> bool:
        if not self._sem.acquire(timeout=self.wait_s):
            self._reject(label)
            return False
        with self._lock:
            self.busy += 1
        return True

    def _reject(self, label: str) -> None:
        with self._lock:
            self.rejected += 1
        log.warning("%s lane full: waited %ss, %s already running (%s)",
                    self.name, self.wait_s, self.cap, label or "-")

    # Loop waiter, not `enter` in a sync route: parked waiters held anyio threadpool tokens the slot holders' streams needed, wedging the relay (/img herd > pool).
    # FIFO by hand-off: `exit` gives its slot straight to the head waiter, the semaphore is never released between, so a newcomer can't jump the queue.
    async def enter_async(self, label: str = "", *, forever: bool = False) -> bool:
        loop = asyncio.get_running_loop()
        with self._lock:
            if not self._waiters and self._sem.acquire(blocking=False):
                self.busy += 1
                return True
            fut = loop.create_future()
            self._waiters.append(fut)
        try:
            await asyncio.wait_for(fut, None if forever else self.wait_s)
            return True
        except BaseException as e:
            # One fact decides: did `exit` pop us? Popped = handed a slot, ours however the wait ended.
            with self._lock:
                try:
                    self._waiters.remove(fut)
                    popped = False
                except ValueError:
                    popped = True
            if popped:
                if isinstance(e, TimeoutError):
                    return True
                self.exit()
                raise
            if isinstance(e, TimeoutError):
                self._reject(label)
                return False
            raise

    @staticmethod
    def _deliver(fut: asyncio.Future) -> None:
        if not fut.done():
            fut.set_result(None)

    # Over-release raises ValueError from the bounded semaphore and is deliberately not swallowed: it signals a broken enter/exit pair.
    # One lock over check + release, else an `enter_async` could queue between them and strand the permit beside a parked waiter.
    def exit(self) -> None:
        with self._lock:
            while self.busy > 0 and self._waiters:
                fut = self._waiters.popleft()
                try:
                    fut.get_loop().call_soon_threadsafe(self._deliver, fut)
                    return
                except RuntimeError:
                    continue
            self._sem.release()
            self.busy = max(0, self.busy - 1)

    def free(self) -> int:
        return max(0, self.cap - self.busy)

    def stats(self) -> dict[str, int]:
        """This lane's numbers, keyed for the /admin/streams payload. Derived
        rather than restated, so a new lane cannot be added and then forgotten
        in the diagnostics that would have shown it saturating."""
        return {f"{self.name}_cap": self.cap,
                f"{self.name}_busy": self.busy,
                f"{self.name}_rejected": self.rejected}


class LoopLane:

    def __init__(self, name: str, env_var: str, default_cap: int) -> None:
        self.name = name
        self.env_var = env_var
        self.cap = lane_config.resolve(env_var, default_cap)
        # Per running loop: an asyncio semaphore binds to the loop it parked a waiter on; weak keys so a finished loop takes it along.
        self._sems: "weakref.WeakKeyDictionary[Any, asyncio.Semaphore]" = weakref.WeakKeyDictionary()
        self._lock = threading.Lock()
        self.busy = 0
        self.peak = 0

    # `cap` is read when a loop first needs its semaphore: settable from a test (one loop per case), useless as a runtime knob.
    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        sem = self._sems.get(loop)
        if sem is None:
            sem = self._sems[loop] = asyncio.Semaphore(self.cap)
        return sem

    async def __aenter__(self) -> "LoopLane":
        await self._semaphore().acquire()
        with self._lock:
            self.busy += 1
            self.peak = max(self.peak, self.busy)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.leave()

    def leave(self) -> None:
        self._semaphore().release()
        with self._lock:
            self.busy = max(0, self.busy - 1)

    async def enter_within(self, wait_s: float) -> bool:
        try:
            await asyncio.wait_for(self.__aenter__(), wait_s)
        except TimeoutError:
            log.warning("%s lane full: waited %ss, %s already running", self.name, wait_s, self.cap)
            return False
        return True

    def stats(self) -> dict[str, int]:
        """This lane's numbers for /admin/streams. `peak` rather than
        `rejected`: nothing is ever turned away here, so the only question a
        reader can have is whether the ceiling is being reached at all."""
        return {f"{self.name}_cap": self.cap,
                f"{self.name}_busy": self.busy,
                f"{self.name}_peak": self.peak}



# Range requests (browser <video> seeking); a rejection is cheap since the element reissues Range natively.
VIDEO_STREAM = Lane("video_stream", "VIDEO_STREAM_CONCURRENCY", 6, 2.0)

# Cache MISSES only; hits are a FileResponse and never queue. A cold store made every tile a miss and exhausted the process's descriptors, failing other accounts' reads too.
# Whole-file mp4 fetches (up to 60s) share this lane and can head-of-line block thumbnails; if rejects climb while warm, look at those streams, not the cap.
IMG_FETCH = Lane("img_fetch", "IMG_FETCH_CONCURRENCY", 8, 15.0)

# Tightest lane: the scarce resource is CPU (ffmpeg in the relay's own cgroup), not descriptors. 3 is inferred, not measured.
# A rejection means the lane was full, not that the clip is bad: callers must map it to retryable (terminal once gave 1,777 unsigned items a 7-day cooldown).
STORYBOARD_BUILD = Lane("storyboard_build", "STORYBOARD_BUILD_CONCURRENCY", 3, 20.0)

# Lower than STORYBOARD_BUILD so a describe/flags sweep never holds the slots a hover scrub needs; a lone visit's full lane is fetch_failed (retry next sweep).
JEV_VIDEO = Lane("jev_video", "JEV_VIDEO_CONCURRENCY", 2, 5.0)



# Gated on the async side before dispatch: the upstream cap is a threading semaphore inside to_thread, so 200 ids parked 200 threads and starved the automation executor. 10 is a guess.
VAULT_MEDIA_READ = LoopLane("vault_media_read", "VAULT_MEDIA_CONCURRENCY", 10)

# Sized for the slow accounts: a probe behind a dead proxy holds its slot ~30s and one proxy carries 5-10 accounts; 24 holds two dead proxies and still walks the healthy rest.
HEALTH_PROBE = LoopLane("health_probe", "HEALTH_ALL_CONCURRENCY", 24)

REFERRALS_READ = LoopLane("referrals_read", "REFERRALS_CONCURRENCY", 16)

OF_ME_READ = LoopLane("of_me_read", "OF_ME_CONCURRENCY", 4)

# Slot held for the whole stream (minutes); waiters are bounded by `enter_within`.
VAULT_DOWNLOAD = LoopLane("vault_download", "VAULT_DOWNLOAD_CONCURRENCY", 4)

# Queued, never rejected: uncapped owner reads in a click storm took the SQLite pool and pushed /t/ p95 to 379 ms.
TRACKING_STATS_READ = LoopLane("tracking_stats_read", "TRACKING_STATS_CONCURRENCY", 2)


# A lane missing from here goes unreported in diagnostics.
LANES = (VIDEO_STREAM, IMG_FETCH, STORYBOARD_BUILD, JEV_VIDEO)
LOOP_LANES = (VAULT_MEDIA_READ, HEALTH_PROBE, REFERRALS_READ, OF_ME_READ, VAULT_DOWNLOAD, TRACKING_STATS_READ)


def describe() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lane in LANES:
        rows.append({
            "name": lane.name,
            "kind": "thread",
            "cap": lane.cap,
            "busy": lane.busy,
            "rejected": lane.rejected,
            "peak": None,
            "wait_s": lane.wait_s,
            "env_var": lane.env_var,
        })
    for lane in LOOP_LANES:
        rows.append({
            "name": lane.name,
            "kind": "loop",
            "cap": lane.cap,
            "busy": lane.busy,
            "rejected": None,
            "peak": lane.peak,
            "wait_s": None,
            "env_var": lane.env_var,
        })
    return rows


def all_stats() -> dict[str, int]:
    out: dict[str, int] = {}
    for lane in (*LANES, *LOOP_LANES):
        out.update(lane.stats())
    return out
