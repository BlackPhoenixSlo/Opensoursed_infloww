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

Cases:
  case_a_cold_pane_is_capped      — 40 distinct misses never put more than
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
Exit 0 = all cases passed. Temp DB bound by _harness (never prod); the image
cache is bound to a throwaway temp dir BEFORE server is imported, so nothing
here can touch a real store.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import asyncio  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

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


def _drain(resp) -> None:
    """Consume the response body. The fetch slot is held until the stream ends,
    so a case that never drains leaks slots — and it does not fail honestly, it
    poisons every LATER case with a gate that is already full.

    Starlette wraps our sync generator with `iterate_in_threadpool`, so what
    comes back is an ASYNC iterator even though `proxy_image` is a plain `def`.
    Each worker thread therefore needs its own loop to drain it."""
    it = getattr(resp, "body_iterator", None)
    if it is None:
        return
    if not hasattr(it, "__anext__"):
        for _ in it:
            pass
        return

    async def _run() -> None:
        async for _ in it:
            pass

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


def _fire(urls: list[str], *, hold_s: float = 0.05,
          headers: dict[str, str] | None = None) -> _Meter:
    """Drive `proxy_image` concurrently for each url and drain every response.

    `_get_client` is the seam; everything else — the semaphore, the cache
    lookups, the streaming generator's finally — stays REAL, because where the
    waiting happens is the entire subject of this suite.
    """
    meter = _Meter()
    real_get_client = server._get_client
    server._get_client = lambda *a, **kw: _FakeClient(meter, hold_s)
    try:
        def _one(u: str):
            resp = img_api.proxy_image(_FakeRequest(headers), u=u)
            _drain(resp)
            return resp

        with ThreadPoolExecutor(max_workers=len(urls)) as pool:
            list(pool.map(_one, urls))
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
        resp = img_api.proxy_image(_FakeRequest(), u=warm)
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
    meter = _Meter()
    real_get_client = server._get_client
    real_lane = admission.IMG_FETCH
    server._get_client = lambda *a, **kw: _FakeClient(meter, 0.30)
    admission.IMG_FETCH = admission.Lane('img_fetch', 'NO_SUCH_ENV', 1, 15.0)
    try:
        def _one(_i):
            resp = img_api.proxy_image(_FakeRequest(), u=u)
            _drain(resp)

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_one, 0)
            # Long enough that the second caller has passed its first (missing)
            # lookup and is parked on the semaphore, short enough that the first
            # is still streaming.
            time.sleep(0.05)
            f2 = pool.submit(_one, 1)
            f1.result(); f2.result()
    finally:
        server._get_client = real_get_client
        admission.IMG_FETCH = real_lane

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



_harness.run(
    case_a_cold_pane_is_capped,
    case_the_cap_is_not_a_queue,
    case_a_cache_hit_takes_no_slot,
    case_the_herd_collapses,
    case_a_range_request_uses_the_other_lane,
)
