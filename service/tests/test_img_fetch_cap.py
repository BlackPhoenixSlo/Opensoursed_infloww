#!/usr/bin/env python3
"""
`/img`'s cache-MISS fetch lane — `admission.IMG_FETCH`. Plain-assert, no pytest
(repo convention). The sibling storyboard build lane has its own suite in
test_storyboard_build_cap.py.

Why this suite exists. `/api/of/v2/vault/media/{id}` and `vault_stills` were
each capped after their own descriptor incident; these two lanes were not, and
they are the ones a cold vault pane actually leans on. On 2026-08-08 the process
ran out of file descriptors twice in thirteen minutes with every error on the
media path, and because descriptors are a PROCESS resource the shortage came out
somewhere else entirely: sqlite answering "unable to open database file", and
seven OTHER accounts' chat reads and admin pages failing while one account's
vault was being browsed.

Hits deliberately bypass the lane: a hit is a FileResponse off disk, and making
a warm pane queue behind cold tiles would be a latency regression with no safety
benefit. So every case here is about the MISS path, and one of them exists
purely to prove hits stay free.

Cases (the first three are pure `admission.Lane` tests; they would belong in an
admission suite, and live here because this change owns only this file):
  case_waiters_are_served_in_order
                                  — `exit` hands each freed slot to the head
                                    `enter_async` waiter, never to a newcomer.
  case_a_waiter_leaving_during_a_hand_off_loses_no_slot
                                  — a waiter `exit` popped owns the slot however
                                    its wait ends (cancel: passed on; timeout:
                                    kept); no slot leaks or doubles.
  case_sync_and_async_entrants_share_one_cap
                                  — `enter` threads and `enter_async` tasks on
                                    one lane never exceed `cap` together.
  case_a_cold_pane_is_capped     — 40 distinct misses never put more than
                                    `IMG_FETCH.cap` fetches in flight, and
                                    every one still resolves.
  case_the_cap_is_not_a_queue     — …but more than one runs at a time. A cap
                                    that serialised would make a cold pane
                                    unusable, which is how a fix gets reverted.
  case_a_cache_hit_takes_no_slot  — a HIT answers off disk while the gate is
                                    fully saturated. The cap must cost a WARM
                                    pane nothing, or it is a latency regression
                                    dressed up as a safety fix.
  case_the_herd_collapses         — a waiter re-reads the store when its turn
                                    comes and finds the bytes the holder just
                                    wrote, instead of paying a second
                                    round-trip for them.
  case_a_range_request_uses_the_other_lane
                                  — video streaming has its own cap; a Range
                                    request must not also consume a fetch slot.
  case_waiters_hold_no_thread     — a request queued for a slot parks on the
                                    event loop, not on a threadpool token (#172,
                                    see `admission.Lane.enter_async`).
  case_a_herd_bigger_than_the_pool_finishes
                                  — the same, end to end: 4 threadpool tokens,
                                    30 cold misses, a slot cap of 2; all 200.
  case_an_aborted_stream_releases_its_slot
                                  — a client that goes away mid-body hands the
                                    slot back (the generator's finally).
  case_a_full_lane_answers_503    — the wait still gives up after `wait_s`: 503,
                                    `rejected` counted, the slot never taken.
Exit 0 = all cases passed. Temp DB bound by _harness (never prod); the image
cache is bound to a throwaway temp dir BEFORE server is imported, so nothing
here can touch a real store.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import gc  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

import anyio.to_thread  # noqa: E402
from fastapi import HTTPException  # noqa: E402

_TMP = Path(tempfile.gettempdir()) / f"img_cap_test_{uuid.uuid4().hex}"
os.environ["IMG_CACHE_DIR"] = str(_TMP / "cache")
# Bind the cap to a small, known number. Reading it off the module under test
# would make every assertion below tautological — it would pass at any value,
# including one that never bounds anything.
os.environ["IMG_FETCH_CONCURRENCY"] = "4"

import admission  # noqa: E402
import server  # noqa: E402 — after _harness (DB) + the store dirs are bound
import img_api  # noqa: E402

_CAP = 4


class _Meter:
    """Counts real overlap. The work runs on worker threads, so this is guarded
    by a lock — it measures what actually collided, not scheduling intent."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.live = 0
        self.peak = 0
        self.calls: list[str] = []

    def enter(self, tag: str) -> None:
        with self._lock:
            self.live += 1
            self.peak = max(self.peak, self.live)
            self.calls.append(tag)

    def leave(self) -> None:
        with self._lock:
            self.live -= 1


class _FakeResp:
    """Just enough of a requests Response for `proxy_image` to stream."""

    def __init__(self, meter: _Meter, body: bytes, hold_s: float) -> None:
        self._meter = meter
        self._body = body
        self._hold = hold_s
        self.status_code = 200
        self.headers = {"Content-Type": "image/jpeg",
                        "Content-Length": str(len(body))}

    def iter_content(self, chunk_size: int = 65536):
        # The hold lives in the STREAM, not in the get(), because that is where
        # production spends its time and where the slot is actually held.
        time.sleep(self._hold)
        yield self._body
        # A second chunk, so a reader can stop half-way (the abort case).
        yield self._body

    def close(self) -> None:
        self._meter.leave()


class _FakeHttp:
    def __init__(self, meter: _Meter, hold_s: float) -> None:
        self._meter = meter
        self._hold = hold_s

    def get(self, u, timeout=None, stream=False, headers=None):
        self._meter.enter(u)
        return _FakeResp(self._meter, b"x" * 512, self._hold)


class _FakeClient:
    def __init__(self, meter: _Meter, hold_s: float) -> None:
        self.http = _FakeHttp(meter, hold_s)
        self.timeout_s = 30


class _FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}


def _url(n: int | str) -> str:
    return (f"https://cdn2.onlyfans.com/files/t/tt/cap{n}/source.jpg"
            f"?Policy=P&Signature=s{n}&Key-Pair-Id=K1")


async def _drain(resp) -> None:
    """Consume the response body. The fetch slot is held until the stream ends,
    so a case that never drains leaks slots — and it does not fail honestly, it
    poisons every LATER case with a gate that is already full.

    Starlette wraps our sync generator with `iterate_in_threadpool`, so what
    comes back is an ASYNC iterator, drained on the loop like the server does."""
    it = getattr(resp, "body_iterator", None)
    if it is None:
        return
    async for _ in it:
        pass


async def _get(u: str, headers: dict[str, str] | None = None):
    """One `/img` the way the server runs it: awaited on the loop, body drained."""
    resp = await img_api.proxy_image(_FakeRequest(headers), u=u)
    await _drain(resp)
    return resp


def _fire(urls: list[str], *, hold_s: float = 0.05,
          headers: dict[str, str] | None = None) -> _Meter:
    """Drive `proxy_image` concurrently for each url on one loop (the server's
    shape) and drain every response.

    `_get_client` is the seam; everything else — the semaphore, the cache
    lookups, the streaming generator's finally — stays REAL, because where the
    waiting happens is the entire subject of this suite.
    """
    meter = _Meter()
    real_get_client = server._get_client
    server._get_client = lambda *a, **kw: _FakeClient(meter, hold_s)
    try:
        async def _all():
            await asyncio.gather(*(_get(u, headers) for u in urls))
        asyncio.run(_all())
    finally:
        server._get_client = real_get_client
    return meter


def case_a_cold_pane_is_capped():
    urls = [_url(n) for n in range(100, 140)]
    meter = _fire(urls)

    assert len(meter.calls) == len(urls), \
        f"a capped fetch must still resolve: {len(meter.calls)}/{len(urls)}"
    assert meter.peak <= _CAP, (
        f"{len(urls)} cold tiles put {meter.peak} fetches in flight; cap is "
        f"{_CAP} — the descriptor guard is not holding"
    )


def case_the_cap_is_not_a_queue():
    meter = _fire([_url(n) for n in range(200, 240)])
    assert meter.peak > 1, (
        "the cap collapsed to a serial queue — a cold pane of 500 tiles would "
        "paint one round-trip at a time"
    )


def case_a_cache_hit_takes_no_slot():
    """A warm tile must not queue behind cold ones. Saturate the gate, then ask
    for something already on disk and require an immediate answer."""
    warm = _url("warm")
    img_api._img_cache_write(warm, "image/jpeg", b"already-here")

    held = [admission.IMG_FETCH.enter('saturate') for _ in range(_CAP)]
    assert all(held), "could not saturate the gate; the rest of this case is meaningless"
    try:
        started = time.monotonic()
        resp = asyncio.run(img_api.proxy_image(_FakeRequest(), u=warm))
        elapsed = time.monotonic() - started
        assert resp.headers.get("X-Img-Cache") == "HIT", \
            f"a warm tile did not serve from disk: {resp.headers.get('X-Img-Cache')!r}"
        # The gate's wait is 15s; anything that took a slot would have blocked
        # for all of it. A generous bound still separates the two outcomes.
        assert elapsed < 1.0, (
            f"a cache HIT waited {elapsed:.2f}s on a saturated gate — hits are "
            "taking fetch slots, which makes the cap a latency regression"
        )
    finally:
        for _ in range(_CAP):
            admission.IMG_FETCH.exit()


def case_the_herd_collapses():
    """Two callers, one url, a gate of ONE. The second misses the first lookup,
    queues, and must find the bytes on disk when its turn comes.

    This is what pins the release ORDER in `_safe_iter`'s finally: the slot is
    handed over only after the cache write, so the waiter it wakes cannot see an
    empty store. Release before the write and this case fails with 2 calls."""
    u = _url("herd")
    before = img_api._img_cache_collapsed
    with _rig(1, 15.0, 0.30) as (_, meter):
        async def _two():
            first = asyncio.create_task(_get(u))
            # Long enough that the second caller has passed its first (missing)
            # lookup and is parked on the semaphore, short enough that the first
            # is still streaming.
            await asyncio.sleep(0.05)
            await asyncio.gather(first, _get(u))
        asyncio.run(_two())

    assert len(meter.calls) == 1, (
        f"two callers for ONE url made {len(meter.calls)} upstream fetches — "
        "the waiter is not re-reading the store inside its slot"
    )
    assert img_api._img_cache_collapsed > before, \
        "the collapse happened but was never counted (nothing would show it in prod)"


def case_a_range_request_uses_the_other_lane():
    """Video streaming has had its own cap since long before this one. A Range
    request must take THAT slot and not also a fetch slot — double-charging
    would silently halve the video lane."""
    free_before = admission.IMG_FETCH.free()
    meter = _fire([_url("ranged")], headers={"range": "bytes=0-1023"})
    assert len(meter.calls) == 1, "the ranged request never reached upstream"
    assert admission.IMG_FETCH.free() == free_before, (
        "a Range request consumed a cache-miss fetch slot; it belongs to the "
        "video lane and would be counted twice"
    )


def _tokens(n: int):
    """Shrink this loop's anyio threadpool (the one sync routes and streaming
    bodies share; the relay sets 200), so a herd can outnumber it. Call inside
    the case's loop: the limiter is per loop."""
    lim = anyio.to_thread.current_default_thread_limiter()
    lim.total_tokens = n
    return lim


@contextlib.contextmanager
def _rig(cap: int, wait_s: float, hold_s: float):
    """`admission.IMG_FETCH` swapped for a fresh lane (`cap`, `wait_s`) and the
    client for a fake whose bodies take `hold_s`; both restored on the way out.
    Yields (lane, meter)."""
    real_lane, real_get_client = admission.IMG_FETCH, server._get_client
    meter = _Meter()
    server._get_client = lambda *a, **kw: _FakeClient(meter, hold_s)
    admission.IMG_FETCH = lane = admission.Lane("img_fetch", "NO_SUCH_ENV", cap, wait_s)
    try:
        yield lane, meter
    finally:
        admission.IMG_FETCH, server._get_client = real_lane, real_get_client


def case_waiters_hold_no_thread():
    """Saturate the lane, queue 20 misses, and look: every one is parked on the
    loop (the lane's waiter queue) and not one threadpool token is borrowed.
    Then free the slots and every one completes."""
    async def _go():
        lim = _tokens(40)
        held = [lane.enter("saturate") for _ in range(2)]
        assert all(held)
        tasks = [asyncio.create_task(_get(_url(f"park{i}"))) for i in range(20)]
        for _ in range(200):          # until every request reached the lane
            await asyncio.sleep(0.01)
            if len(lane._waiters) == 20:
                break
        parked, borrowed = len(lane._waiters), lim.borrowed_tokens
        for _ in held:
            lane.exit()
        await asyncio.gather(*tasks)
        return parked, borrowed

    with _rig(2, 15.0, 0.01) as (lane, meter):
        parked, borrowed = asyncio.run(_go())
    assert parked == 20, f"{parked}/20 requests queued on the lane"
    assert borrowed == 0, (
        f"{borrowed} threadpool tokens held while every request only waited for a "
        "slot — waiters are parking on threads again (#172)")
    assert len(meter.calls) == 20 and lane.busy == 0 and lane.rejected == 0, \
        (len(meter.calls), lane.busy, lane.rejected)


def case_a_herd_bigger_than_the_pool_finishes():
    """4 tokens, a cap of 2, 30 distinct cold misses at once. Parked on threads,
    the waiters would take all 4 tokens and the two holders' bodies could never
    get one: nothing finishes until the waits run out (503s). Parked on the
    loop, all 30 answer 200 and nothing is rejected."""
    statuses: list[int] = []

    async def _one(u):
        resp = await _get(u)
        statuses.append(resp.status_code)

    async def _all():
        _tokens(4)
        await asyncio.gather(*(_one(_url(f"pool{i}")) for i in range(30)))

    with _rig(2, 5.0, 0.02) as (lane, meter):
        started = time.monotonic()
        asyncio.run(_all())
        elapsed = time.monotonic() - started
    assert statuses == [200] * 30 and lane.rejected == 0, (statuses, lane.rejected)
    assert meter.peak <= 2 and lane.busy == 0, (meter.peak, lane.busy)
    assert elapsed < 5.0, f"the herd took {elapsed:.1f}s — something waited out the lane"


def case_an_aborted_stream_releases_its_slot():
    """Read one chunk, then the client goes away (Starlette stops iterating and
    drops the body): the slot comes back, and nothing is cached."""
    u = _url("abort")

    async def _go():
        resp = await img_api.proxy_image(_FakeRequest(), u=u)
        it = resp.body_iterator
        await it.__anext__()
        busy_mid = lane.busy
        await it.aclose()
        del resp, it
        gc.collect()
        return busy_mid

    with _rig(1, 15.0, 0.0) as (lane, meter):
        busy_mid = asyncio.run(_go())
        gc.collect()
    assert busy_mid == 1, f"the slot was not held while streaming: busy={busy_mid}"
    assert lane.busy == 0 and lane.free() == 1, f"an aborted stream leaked its slot: busy={lane.busy}"
    assert img_api._img_cache_lookup(u) is None, "a half-read body was cached"


def case_a_full_lane_answers_503():
    async def _go():
        lim = anyio.to_thread.current_default_thread_limiter()
        task = asyncio.create_task(img_api.proxy_image(_FakeRequest(), u=_url("full")))
        await asyncio.sleep(0.15)
        borrowed = lim.borrowed_tokens
        try:
            await task
        except HTTPException as e:
            return e.status_code, borrowed
        return None, borrowed

    with _rig(1, 0.3, 0.0) as (lane, meter):
        assert lane.enter("saturate")
        try:
            status, borrowed = asyncio.run(_go())
        finally:
            lane.exit()
    assert status == 503, f"a full lane answered {status}, not a retryable 503"
    assert lane.rejected == 1 and lane.busy == 0 and not lane._waiters, \
        (lane.rejected, lane.busy, len(lane._waiters))
    assert borrowed == 0, f"the 503-bound wait held {borrowed} threadpool tokens"
    assert not meter.calls, "a rejected request still reached upstream"


def _slots(lane: admission.Lane) -> int:
    """Count the lane's free slots by taking them all, then hand them back: a
    leaked or duplicated slot shows here even when `busy` looks right."""
    n = 0
    while lane._sem.acquire(blocking=False):
        n += 1
    for _ in range(n):
        lane._sem.release()
    return n


def case_waiters_are_served_in_order():
    """Cap 1, three queued waiters, and a newcomer arriving right after every
    `exit`: the head waiter gets each freed slot, not the newcomer that showed
    up between the release and the head's wake-up."""
    lane = admission.Lane("fifo", "NO_SUCH_ENV", 1, 5.0)
    order: list[str] = []
    late: list[asyncio.Task] = []

    async def worker(name: str) -> bool:
        ok = await lane.enter_async(name)
        if ok:
            order.append(name)
            await asyncio.sleep(0.005)
            lane.exit()
            if name.startswith("w"):   # a newcomer lands between the release and the head's wake-up
                late.append(asyncio.create_task(worker("n" + name)))
        return ok

    async def _go():
        assert await lane.enter_async("hold")
        heads = []
        for i in range(3):
            heads.append(asyncio.create_task(worker(f"w{i}")))
            while len(lane._waiters) < i + 1:
                await asyncio.sleep(0)
        lane.exit()
        late.append(asyncio.create_task(worker("nhold")))
        oks = list(await asyncio.gather(*heads))
        return oks + list(await asyncio.gather(*late))

    oks = asyncio.run(_go())
    assert all(oks), oks
    assert len(order) == 7 and order[:3] == ["w0", "w1", "w2"], f"newcomers jumped the queue: {order}"
    assert lane.rejected == 0 and lane.busy == 0 and not lane._waiters, \
        (lane.rejected, lane.busy, len(lane._waiters))
    assert _slots(lane) == 1, "a slot leaked or doubled"


def case_a_waiter_leaving_during_a_hand_off_loses_no_slot():
    """Once `exit` has popped a waiter the slot is that waiter's, however its
    wait ends: cancelled before the hand-off lands, it passes the slot to the
    next waiter; timed out as the hand-off lands (either callback first), it
    keeps it. Every slot is back afterwards, nothing rejected."""
    lane = admission.Lane("leave", "NO_SUCH_ENV", 1, 5.0)

    async def _cancelled_head():
        assert await lane.enter_async("hold")
        first = asyncio.create_task(lane.enter_async("first"))
        second = asyncio.create_task(lane.enter_async("second"))
        while len(lane._waiters) < 2:
            await asyncio.sleep(0)
        lane.exit()        # pops `first`; the hand-off is queued on the loop
        first.cancel()     # …and `first` leaves before it lands
        got = await asyncio.wait_for(second, 1.0)
        try:
            await first
        except asyncio.CancelledError:
            pass
        lane.exit()
        return got

    assert asyncio.run(_cancelled_head()) is True, "the slot did not reach the next waiter"
    assert lane.busy == 0 and not lane._waiters and _slots(lane) == 1, \
        (lane.busy, len(lane._waiters), _slots(lane))

    # Block the loop past the deadline so the timeout and `exit` are due in the
    # same loop turn, in either order; `exit` pops the waiter before its except
    # path runs both times.
    async def _timeout_race(exit_first: bool):
        lane = admission.Lane("race", "NO_SUCH_ENV", 1, 0.05)
        loop = asyncio.get_running_loop()
        assert await lane.enter_async("hold")
        waiter = asyncio.create_task(lane.enter_async("waiter"))
        while not lane._waiters:
            await asyncio.sleep(0)
        if exit_first:
            time.sleep(0.1)
            lane.exit()
        else:
            loop.call_at(loop.time() + 0.06, lane.exit)
            time.sleep(0.1)
        got = await waiter
        if got:
            lane.exit()
        return got, lane

    for exit_first in (True, False):
        got, lane = asyncio.run(_timeout_race(exit_first))
        assert got is True, f"exit_first={exit_first}: a popped waiter answered {got}"
        assert lane.busy == 0 and not lane._waiters and _slots(lane) == 1 and lane.rejected == 0, \
            (exit_first, lane.busy, len(lane._waiters), _slots(lane), lane.rejected)


def case_sync_and_async_entrants_share_one_cap():
    """Threads in `enter` and tasks in `enter_async` on one lane: never more
    than `cap` holders at once, and every slot back afterwards."""
    lane = admission.Lane("mixed", "NO_SUCH_ENV", 3, 10.0)
    meter = _Meter()

    def _hold() -> None:
        meter.enter("x")
        time.sleep(0.002)
        meter.leave()

    def _sync_worker() -> None:
        for _ in range(20):
            if lane.enter("sync"):
                try:
                    _hold()
                finally:
                    lane.exit()

    async def _async_one() -> None:
        if await lane.enter_async("async"):
            try:
                await asyncio.to_thread(_hold)
            finally:
                lane.exit()

    async def _go():
        threads = [threading.Thread(target=_sync_worker) for _ in range(4)]
        for t in threads:
            t.start()
        await asyncio.gather(*(_async_one() for _ in range(120)))
        await asyncio.to_thread(lambda: [t.join() for t in threads])

    asyncio.run(_go())
    assert len(meter.calls) > 3, len(meter.calls)
    assert meter.peak <= 3, f"{meter.peak} holders on a cap of 3"
    assert lane.busy == 0 and not lane._waiters and _slots(lane) == 3, \
        (lane.busy, len(lane._waiters), _slots(lane))


def case_exit_releases_under_the_lock():
    """`exit` checks the queue and releases the permit in one lock hold: let
    go between them and an `enter_async` can queue in the gap, leaving a free
    permit beside a parked waiter that nothing wakes (a stranded slot)."""
    lane = admission.Lane("gap", "NO_SUCH_ENV", 1, 5.0)
    sem, seen = lane._sem, []

    class _Watch:
        def acquire(self, *a, **kw):
            return sem.acquire(*a, **kw)

        def release(self):
            seen.append(lane._lock.locked())
            sem.release()

    lane._sem = _Watch()
    assert lane.enter("hold")
    lane.exit()
    assert seen == [True], f"release ran outside the lane lock: {seen}"
    assert lane.busy == 0 and _slots(lane) == 1, (lane.busy, _slots(lane))


_harness.run(
    case_waiters_are_served_in_order,
    case_a_waiter_leaving_during_a_hand_off_loses_no_slot,
    case_exit_releases_under_the_lock,
    case_sync_and_async_entrants_share_one_cap,
    case_a_cold_pane_is_capped,
    case_the_cap_is_not_a_queue,
    case_a_cache_hit_takes_no_slot,
    case_the_herd_collapses,
    case_a_range_request_uses_the_other_lane,
    case_waiters_hold_no_thread,
    case_a_herd_bigger_than_the_pool_finishes,
    case_an_aborted_stream_releases_its_slot,
    case_a_full_lane_answers_503,
)
