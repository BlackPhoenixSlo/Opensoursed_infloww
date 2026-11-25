#!/usr/bin/env python3
from __future__ import annotations

import _harness

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
os.environ["IMG_FETCH_CONCURRENCY"] = "4"

import admission  # noqa: E402
import server  # noqa: E402 — after _harness (DB) + the store dirs are bound
import img_api  # noqa: E402

_CAP = 4


class _Meter:

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

    def __init__(self, meter: _Meter, body: bytes, hold_s: float) -> None:
        self._meter = meter
        self._body = body
        self._hold = hold_s
        self.status_code = 200
        self.headers = {"Content-Type": "image/jpeg",
                        "Content-Length": str(2 * len(body))}

    def iter_content(self, chunk_size: int = 65536):
        time.sleep(self._hold)
        yield self._body
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
    it = getattr(resp, "body_iterator", None)
    if it is None:
        return
    async for _ in it:
        pass


async def _get(u: str, headers: dict[str, str] | None = None):
    resp = await img_api.proxy_image(_FakeRequest(headers), u=u)
    await _drain(resp)
    return resp


def _fire(urls: list[str], *, hold_s: float = 0.05,
          headers: dict[str, str] | None = None) -> _Meter:
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
        assert elapsed < 1.0, (
            f"a cache HIT waited {elapsed:.2f}s on a saturated gate — hits are "
            "taking fetch slots, which makes the cap a latency regression"
        )
    finally:
        for _ in range(_CAP):
            admission.IMG_FETCH.exit()


def case_the_herd_collapses():
    u = _url("herd")
    before = img_api._img_cache_collapsed
    with _rig(1, 15.0, 0.30) as (_, meter):
        async def _two():
            first = asyncio.create_task(_get(u))
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
    free_before = admission.IMG_FETCH.free()
    meter = _fire([_url("ranged")], headers={"range": "bytes=0-1023"})
    assert len(meter.calls) == 1, "the ranged request never reached upstream"
    assert admission.IMG_FETCH.free() == free_before, (
        "a Range request consumed a cache-miss fetch slot; it belongs to the "
        "video lane and would be counted twice"
    )


def _tokens(n: int):
    lim = anyio.to_thread.current_default_thread_limiter()
    lim.total_tokens = n
    return lim


@contextlib.contextmanager
def _rig(cap: int, wait_s: float, hold_s: float):
    real_lane, real_get_client = admission.IMG_FETCH, server._get_client
    meter = _Meter()
    server._get_client = lambda *a, **kw: _FakeClient(meter, hold_s)
    admission.IMG_FETCH = lane = admission.Lane("img_fetch", "NO_SUCH_ENV", cap, wait_s)
    try:
        yield lane, meter
    finally:
        admission.IMG_FETCH, server._get_client = real_lane, real_get_client


def case_waiters_hold_no_thread():
    async def _go():
        lim = _tokens(40)
        held = [lane.enter("saturate") for _ in range(2)]
        assert all(held)
        tasks = [asyncio.create_task(_get(_url(f"park{i}"))) for i in range(20)]
        for _ in range(200):
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
    n = 0
    while lane._sem.acquire(blocking=False):
        n += 1
    for _ in range(n):
        lane._sem.release()
    return n


def case_waiters_are_served_in_order():
    lane = admission.Lane("fifo", "NO_SUCH_ENV", 1, 5.0)
    order: list[str] = []
    late: list[asyncio.Task] = []

    async def worker(name: str) -> bool:
        ok = await lane.enter_async(name)
        if ok:
            order.append(name)
            await asyncio.sleep(0.005)
            lane.exit()
            if name.startswith("w"):
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
    lane = admission.Lane("leave", "NO_SUCH_ENV", 1, 5.0)

    async def _cancelled_head():
        assert await lane.enter_async("hold")
        first = asyncio.create_task(lane.enter_async("first"))
        second = asyncio.create_task(lane.enter_async("second"))
        while len(lane._waiters) < 2:
            await asyncio.sleep(0)
        lane.exit()
        first.cancel()
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
