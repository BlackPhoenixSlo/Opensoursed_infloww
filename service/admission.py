"""Admission lanes — the relay's bounded-concurrency primitive, stated once.

A "lane" is a named ceiling on how many of one KIND of expensive thing may be
in flight in this process at a time, plus the counters that make the ceiling
observable. Three of them existed as three hand-rolled copies of the same five
parts (a cap constant, a wait constant, a semaphore, a rejection counter, and an
acquire-log-reject block); this module is those five parts written once.

WHY THIS EXISTS AT ALL. Descriptors, threads and cores are PROCESS resources.
When the relay ran out of descriptors on 2026-08-08 the errors did not surface
in the vault pane that caused it — sqlite started answering "unable to open
database file", and seven OTHER accounts' chat reads and admin pages failed.
Anything that can be started N-at-a-time by a person scrolling therefore needs a
ceiling, and a ceiling nobody can read the current value of is a ceiling nobody
maintains — hence `stats()`.

TWO TYPES. `Lane` is process-wide THREADING slots: `exit` works from any thread
(a streaming body's `finally` runs in a worker), the wait gives up after
`wait_s` (a retryable rejection), and a waiter parks either on a thread
(`enter`: `vault_frames.warm_one_sync` inside `asyncio.to_thread`) or on its
event loop (`enter_async`: `/img`, an `async def` streaming endpoint).
`LoopLane` is per-loop asyncio slots for async-only call sites; its waiters
park on the loop and it never rejects. Two classes because an asyncio
semaphore binds to one running loop and a threading one does not.

`vault_stills._MAX_INFLIGHT_FETCHES` and `vault_ai_api._VISION_GLOBAL_CONCURRENCY`
are still hand-rolled copies of `LoopLane` in their own modules; they belong
here, and moving them is the obvious follow-up.

This module imports nothing from the relay. It is a leaf on purpose, so
`vault_frames` can take a lane at module scope instead of reaching through
`server` at call time — `vault_frames` only imports `server` lazily to dodge an
import cycle, and every name it pulls through that hole is a reason the hole
stays open.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import threading
import weakref
from typing import Any

# The only import, and it is another leaf (it pulls in nothing from the relay
# either). Lanes are built at MODULE IMPORT, before the loop or the DB exist,
# so whatever feeds them has to be importable and readable synchronously here.
import lane_config

log = logging.getLogger("of-relay.admission")


class Lane:
    """A named ceiling on concurrent work, with the counters to see it working.

    `enter()` / `await enter_async()` return True if a slot was taken and
    False if the wait (`wait_s`) expired. False means "not now", never "not
    possible" — callers must map it to something retryable. A caller that took
    a slot MUST pair it with `exit()` (from any thread) in a `finally`, and must
    not call `exit()` otherwise.
    """

    def __init__(self, name: str, env_var: str, default_cap: int,
                 wait_s: float) -> None:
        self.name = name
        # Env-overridable so a cap can be retuned on the VPS without a deploy —
        # these numbers are sized against a 2-core box and the right value is an
        # operational question, not a source-code one.
        # Kept so `describe()` can name the tuning surface without a second
        # table that could drift from the constructor call.
        self.env_var = env_var
        # env var > value saved from the Concurrency panel > this default.
        # See lane_config's docstring for why the env var wins.
        self.cap = lane_config.resolve(env_var, default_cap)
        self.wait_s = wait_s
        # BOUNDED, so that releasing a slot nobody holds raises instead of
        # silently inflating the ceiling. See `exit`.
        self._sem = threading.BoundedSemaphore(self.cap)
        self._lock = threading.Lock()
        self.busy = 0
        self.rejected = 0
        # `enter_async` waiters, FIFO. `exit` hands its slot to the head one.
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

    async def enter_async(self, label: str = "", *, forever: bool = False) -> bool:
        """`enter` for an `async def` caller: the same slots, cap, `wait_s` and
        `rejected`, but the waiter parks on its event loop, not on a thread.

        Why (#172): `/img` waited in `enter` inside a sync route, so each waiter
        held an anyio threadpool token for up to `wait_s` — and the slot
        holders' StreamingResponse generators need tokens of that same pool to
        finish. A cold herd bigger than the pool (200) parked every token on a
        waiter, no slot could finish, and the relay wedged until the waiters
        timed out (/img 5xx, /admin/streams 30 s). A loop waiter holds nothing.

        FIFO by hand-off: `exit` gives its slot straight to the head waiter
        (the semaphore is never released in between, so a newcomer cannot take
        it first), and a newcomer queues whenever anyone is queued. Mixing: a
        sync `enter` on the same lane gets a slot only via the semaphore, i.e.
        when no `enter_async` waiter is queued; the cap covers both. `forever`:
        no `wait_s` limit (a caller that holds nothing while it waits)."""
        loop = asyncio.get_running_loop()
        with self._lock:
            if not self._waiters and self._sem.acquire(blocking=False):
                self.busy += 1
                return True
            fut = loop.create_future()
            self._waiters.append(fut)
        try:
            await asyncio.wait_for(fut, None if forever else self.wait_s)
            return True               # handed a slot; `busy` already counts it
        except BaseException as e:
            # One fact decides: did `exit` pop us? Popped = handed a slot, ours
            # however the wait ended (its `_deliver` may still be on the way).
            with self._lock:
                try:
                    self._waiters.remove(fut)
                    popped = False
                except ValueError:
                    popped = True
            if popped:
                if isinstance(e, TimeoutError):
                    return True
                self.exit()           # cancelled holding a slot: pass it on
                raise
            if isinstance(e, TimeoutError):
                self._reject(label)
                return False
            raise

    @staticmethod
    def _deliver(fut: asyncio.Future) -> None:
        """On the waiter's loop: wake it. A waiter already gone (cancelled,
        timed out) was popped all the same, so its except path owns the slot."""
        if not fut.done():
            fut.set_result(None)

    def exit(self) -> None:
        """Hand back a slot taken by `enter` / `enter_async`: to the head
        `enter_async` waiter if one is queued, else to the semaphore.

        An over-release raises `ValueError` from the bounded semaphore and is
        NOT swallowed: it is the one signal that an enter/exit pair has come
        apart, and a lane that quietly grows past its cap is worse than the
        crash that tells you about it. `busy` is decremented only on a release
        that actually happened, so the gauge cannot drift below the truth. (A
        hand-off keeps the slot taken, so `busy` stays; with `busy` 0 there is
        no slot to hand, and the release below raises.)

        One lock over check + release: else an `enter_async` could queue
        between them and the released permit would sit beside a parked waiter.
        """
        with self._lock:
            while self.busy > 0 and self._waiters:
                fut = self._waiters.popleft()
                try:
                    fut.get_loop().call_soon_threadsafe(self._deliver, fut)
                    return
                except RuntimeError:  # its loop is closed: that waiter is gone
                    continue
            self._sem.release()
            self.busy = max(0, self.busy - 1)

    def free(self) -> int:
        """Slots currently available. For tests and diagnostics — never for
        deciding whether to `enter()` (that would be a race)."""
        return max(0, self.cap - self.busy)

    def stats(self) -> dict[str, int]:
        """This lane's numbers, keyed for the /admin/streams payload. Derived
        rather than restated, so a new lane cannot be added and then forgotten
        in the diagnostics that would have shown it saturating."""
        return {f"{self.name}_cap": self.cap,
                f"{self.name}_busy": self.busy,
                f"{self.name}_rejected": self.rejected}


class LoopLane:
    """`Lane`'s asyncio peer: a named ceiling whose waiters park on the event
    loop instead of on a thread.

    A separate class rather than a flag on `Lane`, for the reason the module
    docstring gives: its semaphore is bound to a loop. It lives here rather than at a call site
    because the same ten lines had already been hand-rolled three times (the
    by-id vault read, `vault_stills._SLOTS`, `vault_ai_api._vision_sema`) —
    which is exactly the situation that produced `Lane` in the first place.

    Two things follow from parking a coroutine rather than a thread:

    • It never rejects. `Lane` gives up after `wait_s` (a `Lane.enter` waiter
      holds a thread; an `/img` waiter is a browser tile better answered with a
      retryable 503 than left hanging). A queued caller here holds nothing, so
      queueing is simply the right answer and a timeout would only invent a
      failure mode the callers would have to handle. The exception is a slot
      held for minutes (a download stream): `enter_within` bounds that wait.
    • The semaphore is PER RUNNING LOOP. An `asyncio.Semaphore` that has parked
      a waiter belongs to the loop it parked it on, and the test harness gives
      every case its own `asyncio.run()`. Weak keys, so a finished loop takes
      its semaphore with it.

    A slot is held for the whole `async with` body — including a blocking call
    dispatched to a thread inside it. That is the point: the ceiling has to
    outlive any cancellation of the awaiting task, because cancelling a task
    does not stop the thread it is waiting on.
    """

    def __init__(self, name: str, env_var: str, default_cap: int) -> None:
        self.name = name
        # Kept so `describe()` can name the tuning surface without a second
        # table that could drift from the constructor call.
        self.env_var = env_var
        self.cap = lane_config.resolve(env_var, default_cap)
        self._sems: "weakref.WeakKeyDictionary[Any, asyncio.Semaphore]" = weakref.WeakKeyDictionary()
        # `busy` may be touched from more than one loop thread, and the module
        # docstring's rule is that a ceiling nobody can read is a ceiling nobody
        # maintains — so it is counted, and counted safely.
        self._lock = threading.Lock()
        self.busy = 0
        self.peak = 0

    def _semaphore(self) -> asyncio.Semaphore:
        # `cap` is read the first time a given loop needs a semaphore, so
        # changing it afterwards only reaches loops that have not started yet.
        # That is what makes it settable from a test (one loop per case) and
        # what makes it useless as a runtime knob (one loop for the process).
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
        """`__aexit__` without the coroutine, for a slot given back from a loop
        callback (a download's, once its upstream close finished). On the loop's
        thread only. Resolved by RUNNING loop, so this releases the same
        semaphore `__aenter__` took — there is no per-entry state to carry."""
        self._semaphore().release()
        with self._lock:
            self.busy = max(0, self.busy - 1)

    async def enter_within(self, wait_s: float) -> bool:
        """`__aenter__` with a bounded wait, for the one caller whose slot is held for minutes (a download stream):
        True with a slot taken (pair it with `__aexit__`), False with nothing taken when none came within `wait_s`.
        A timeout cancels the semaphore wait, which takes no permit (asyncio's acquire hands a permit it had already
        been given to the next waiter when cancelled), and `busy` is counted only after the acquire returned."""
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


# ── The lanes themselves ────────────────────────────────────────────
#
# Instances live HERE, not in the module that happens to have the busiest call
# site, because they describe resources of the PROCESS and more than one module
# needs them. `vault_frames` in particular imports `server` lazily inside a
# function purely to dodge an import cycle; every name it pulls through that
# hole is a reason the hole stays open, and a lane is a name it can now get from
# a leaf instead.

# /img requests carrying a Range header — a browser <video> seeking. Sized for
# "watching one clip + one preloaded sibling + headroom for the overlap when
# switching tiles". A rejection is cheap here: the <video> element reissues
# Range requests natively, so a transient 503 costs a few hundred ms.
VIDEO_STREAM = Lane("video_stream", "VIDEO_STREAM_CONCURRENCY", 6, 2.0)

# /img cache MISSES. Hits never reach this lane — a hit is a FileResponse off
# disk, and queueing it would be a latency regression for a warm pane with no
# safety benefit. A miss is a different animal: a descriptor, a thread and an OF
# round-trip, and on a cold store EVERY tile is one. That is what emptied the
# process's descriptor table on 2026-08-08 — 48 errors in two one-second bursts,
# after which seven OTHER accounts' chat reads and admin pages failed too.
#
# ⚠️ This lane REVERSES a deliberate earlier exemption. Thumbnails used to
# bypass the Range cap entirely, on the stated grounds that "the grid stays
# snappy even when the cap is saturated". That reasoning was right about LATENCY
# and wrong about SURVIVAL: an unbounded grid is what killed the process. The
# cost of reversing it is real and worth naming — a request with NO Range header
# may still be a whole-file mp4, and `server._MAX_STREAM_SEC` lets one hold its
# slot for 60s, so slow whole-file fetches and fast thumbnails now share a lane
# and can head-of-line block each other.
#
# The 8/15s pair is sized against that worst case rather than picked. 8 sits
# above the two neighbouring vault caps (6) because this lane also carries chat
# bubbles and avatars a person is WATCHING, not just grid tiles. 15s is far
# longer than a thumbnail could need but short enough to fail before a browser
# gives up on its own — a late thumbnail still paints, whereas a 503 is a broken
# image the browser will not retry. If `img_fetch_rejected` ever climbs while
# the cache is warm, the whole-file streams are the thing to look at, not the
# cap.
IMG_FETCH = Lane("img_fetch", "IMG_FETCH_CONCURRENCY", 8, 15.0)

# mp4 download + ffmpeg, for both build paths: a `/img/scrub` hover and
# `vault_frames.warm_one_sync` (the collect warm phase, and a DESCRIBE meeting a
# clip nobody warmed). The second is why this is not a scrub-only concern — a
# describe sweep runs `vault_ai_api._VISION_GLOBAL_CONCURRENCY` items at once and
# an un-warmed clip does its download and its ffmpeg INSIDE that vision slot, so
# eight cold clips meant eight ffmpegs.
#
# `server._storyboard_locks` is not a substitute: it stops the SAME video being
# built twice and says nothing about N different ones. Alone among these lanes
# the scarce resource is CPU rather than descriptors, and every ffmpeg runs
# inside the relay's own cgroup, so the Python process it serves shares that
# ceiling with them — this is deliberately the tightest number here. 3 fits
# both box profiles in docker-compose.yml: on a 4 vCPU box (relay `cpus: 3.0`)
# it was already the Concurrency panel's (unmeasured) suggestion, and on the
# 8 vCPU / 50-account box (`cpus: 6.0`) three builds still leave the event loop
# ~3 cores (inferred, not measured). It does not grow with accounts: a build is
# a hover or a describe, not a Creator.
# Serving an already-built frame never touches it.
#
# A rejection here must be mapped to something RETRYABLE by the caller. It says
# the lane was full; it says nothing about the clip. `vault_frames._WARM_REASON`
# maps it to `fetch_failed` for exactly that reason — treating it as terminal is
# what once gave 1,777 merely-unsigned items a 7-day cooldown.
STORYBOARD_BUILD = Lane("storyboard_build", "STORYBOARD_BUILD_CONCURRENCY", 3, 20.0)

# A vault video's Jev frames (`vault_frames.collect_jev_video`, D54): a whole 720p download (capped, 50 MB default) and
# one ffmpeg pass over it, ~4x the bytes and pixels of a 240p storyboard build. Its own lane, LOWER than
# STORYBOARD_BUILD's, so a describe / flags sweep walking a vault of clips never holds the slots a hover scrub
# needs. A sweep's clip takes its slot BEFORE its vision slot and waits as long as it takes (`vault_jev_pass.clip_lane`),
# so a waiting clip idles nothing; the 5 s here is for a lone visit (no sweep) only, whose full lane is `fetch_failed`
# (retry next sweep), like STORYBOARD_BUILD's.
JEV_VIDEO = Lane("jev_video", "JEV_VIDEO_CONCURRENCY", 2, 5.0)


# ── The loop lanes ──────────────────────────────────────────────────
#
# Same law as above — the instances live here, not at their busiest call site.

# `/api/of/v2/vault/media/{id}` — the by-id read. `_proxy` already caps UPSTREAM
# calls per account, so OF never sees a storm; the problem is WHERE the waiting
# happens, because that cap is a threading semaphore acquired INSIDE
# `asyncio.to_thread`. The upstream is protected, the executor is not. And this
# is the route the UI asks for a whole library at a time: `useVaultMediaByIds`
# issues one request per stored id and PPVLibraryTab hands it every id there is,
# so 200 ids wanted 200 threads for 5 usable slots — which starves the
# automation lane sharing that executor (the 2026-07-04 "socket hang up") and
# holds 200 inbound sockets and their DB connections open while they wait.
# Gating on the ASYNC side, before the dispatch, makes a queued request cost a
# parked coroutine instead. Its own budget, separate from VAULT_STILL_CONCURRENCY:
# a vault pane storm must not spend the stills allowance or vice versa. 10, not
# the stills' 6: a queued request is a parked coroutine, and at 50 Creators the
# panes open at once are one per chatter working a vault. 10 was the
# Concurrency panel's "4 core / up to 50 accounts" suggestion, which the panel
# itself called an untested hypothesis; it is still a guess, now the default.
VAULT_MEDIA_READ = LoopLane("vault_media_read", "VAULT_MEDIA_CONCURRENCY", 10)

# `/health?all_accounts=1` — the /setup table's per-account OF probe. It calls
# `_load_client()` + `c.me()` DIRECTLY rather than through `_proxy`, so no
# priority lane stands between a fan-out and the shared proxy/executor/descriptor
# ceilings, and a per-account cap would be the wrong shape anyway: this spends
# one call on each of N accounts rather than N on one.
#
# SIZED FOR THE SLOW ACCOUNTS, not the fast ones. A healthy probe takes ~0.6 s,
# but a probe behind a dead proxy holds its slot until the client gives up
# (`OFClient.timeout_s`, 30 s), past the route's 20 s budget — and one proxy
# carries 5-10 accounts. At 4, the first four stuck probes took every slot and
# every healthy Creator queued behind them into a `timeout` row: the table
# reported the whole agency down for one proxy. 24 holds two dead proxies'
# worth (20 stuck) with 4 slots still walking the healthy rest, and at 50
# Creators with one dead proxy the other 40 finish in ~2 s. It is a ceiling, not
# a pool: a relay with 5 accounts never uses more than 5.
HEALTH_PROBE = LoopLane("health_probe", "HEALTH_ALL_CONCURRENCY", 24)

# `/admin/stats/referrals` — the Dashboard's Referrals tile and Creator reports'
# Referrals channel: one OF `referrals_chart` read per Creator, the same
# one-call-on-each-of-N shape as HEALTH_PROBE, so the same kind of ceiling. Its
# own budget so a /setup probe storm cannot hold the Dashboard's tile back.
# 16: the route answers within `_REFERRALS_BUDGET_S` (10 s). At 50 Creators and
# ~1 s a read (a guess: no referrals read is measured; a /health probe is 0.6 s),
# 4 slots get through ~40 in the budget and a cold tile lists the rest
# `unavailable` every 5 minutes; 16 finishes them in ~4 s and still in time with
# one dead proxy (10 stuck slots, 6 walking the other 40 in ~7 s).
REFERRALS_READ = LoopLane("referrals_read", "REFERRALS_CONCURRENCY", 16)

# Vault Pro's download through the relay (`vault_download_api`): a slot per file for its WHOLE stream, which for a
# source video can be minutes. Queued for at most `vault_download_api.SLOT_WAIT_S` (`enter_within`), then a 503 the
# browser lists as a failed item (Retry failed): the browser runs 3 at a time per tab, so a waiter is another tab's
# file. 4 keeps a whole-vault pull from holding more than a few proxy sockets and curl handles at once.
VAULT_DOWNLOAD = LoopLane("vault_download", "VAULT_DOWNLOAD_CONCURRENCY", 4)

# Redirect-link stats (`tracking_stats`: /summary, /{id}/analytics): a read counts a link's raw clicks, ~105k rows
# in 30 days on a hot link, ~25 ms of SQLite CPU on a pooled connection. Uncapped, 5-11 owner reads at once in a
# 250 clicks/s storm took the 8-connection pool and the cores and pushed /t/ p95 to 379 ms server-side (slop
# tracking-links-clicks medium/200, 20261111T095148Z-...-b902). Queued, never rejected: 2 leave the rest to clicks.
TRACKING_STATS_READ = LoopLane("tracking_stats_read", "TRACKING_STATS_CONCURRENCY", 2)


# Every lane, so diagnostics can be DERIVED rather than restated. `admin_streams`
# merges `all_stats()`; adding a lane above and forgetting it here is the only
# way it can go unreported, which is one place to look instead of two files.
LANES = (VIDEO_STREAM, IMG_FETCH, STORYBOARD_BUILD, JEV_VIDEO)
LOOP_LANES = (VAULT_MEDIA_READ, HEALTH_PROBE, REFERRALS_READ, VAULT_DOWNLOAD, TRACKING_STATS_READ)


def describe() -> list[dict[str, Any]]:
    """Every lane as a ROW, for the operator panel.

    `all_stats()` below flattens to prefixed keys because `/admin/streams`
    merges it into one counter bag; a reader that wants "the lanes" then has to
    reassemble them by string-splitting. This returns them already assembled,
    and it is derived from the same LANES/LOOP_LANES tuples, so a lane added
    there cannot be missing here.

    ⚠️ THE CAPS ARE NOW WRITABLE, reversing a deliberate earlier decision.
    The previous text here said `cap` was "deliberately NOT settable over HTTP.
    These ceilings are what stopped the 2026-08-08 descriptor exhaustion from
    recurring, and a control that can widen them is a control that can reproduce
    it." That reasoning is still TRUE and is the cost being accepted: the
    Concurrency panel can now widen any of these, and the panel's own door is
    unauthenticated by explicit choice (see `lane_config_api`, which serves it
    ungated at `/lanes-panel/config`). What
    changed is the judgement, not the risk — the ceilings had never been retuned
    once because retuning meant editing an env file the deploy rsync excludes,
    which is the failure this module's own docstring names.

    Two things keep the reversal honest. A saved value applies at RESTART, so a
    bad number still costs a restart rather than an outage — the property the
    old text was protecting. And `lane_config.describe()` reports whether an env
    var is pinning a lane, so the panel cannot pretend to have changed something
    it did not.

    These rows deliberately stay OBSERVATIONAL — cap, busy, peak, rejected. Where
    a value came from and what it will be after a restart is `lane_config`'s
    view, served at `/lanes-panel/config`; restating it here would be two answers
    to one question, and the second one is the one that goes stale.
    """
    rows: list[dict[str, Any]] = []
    for lane in LANES:
        rows.append({
            "name": lane.name,
            "kind": "thread",
            "cap": lane.cap,
            "busy": lane.busy,
            "rejected": lane.rejected,
            "peak": None,
            # "thread": threading slots (waiters park on a thread or, via
            # `enter_async`, on a loop); the wait gives up after `wait_s` and
            # the caller answers something retryable.
            "wait_s": lane.wait_s,
            "env_var": lane.env_var,
        })
    for lane in LOOP_LANES:
        rows.append({
            "name": lane.name,
            "kind": "loop",
            "cap": lane.cap,
            "busy": lane.busy,
            # Nothing is ever turned away here — a coroutine waiter holds
            # nothing, so it queues. `peak` is the only question worth asking:
            # has the ceiling been reached at all?
            "rejected": None,
            "peak": lane.peak,
            "wait_s": None,
            "env_var": lane.env_var,
        })
    return rows


def all_stats() -> dict[str, int]:
    """Every lane's numbers, merged. Keys are prefixed by lane name, so they
    cannot collide."""
    out: dict[str, int] = {}
    for lane in (*LANES, *LOOP_LANES):
        out.update(lane.stats())
    return out
