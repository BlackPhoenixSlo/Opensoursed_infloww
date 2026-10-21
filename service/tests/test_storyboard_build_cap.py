#!/usr/bin/env python3
"""
The storyboard BUILD lane — `admission.STORYBOARD_BUILD`. Plain-assert, no
pytest (repo convention).

Why this suite exists. A storyboard build is an mp4 download AND an ffmpeg
process, so alone among the relay's admission lanes the scarce resource is CPU
rather than descriptors, and the box has two cores. `server._storyboard_locks`
stops the SAME video being built twice and says nothing at all about N DIFFERENT
videos, which is the case that actually happens: a describe sweep runs
`vault_ai_api._VISION_GLOBAL_CONCURRENCY` items at once and every un-warmed clip
among them starts a build inside its vision slot.

The lane therefore has to hold for BOTH entry points, and they are in different
modules — `server._ensure_storyboard_frame` (a /img/scrub hover) and
`vault_frames.warm_one_sync` (the collect warm phase, and describe). A cap that
only covered the hover would have left the expensive path exactly as it was, so
these cases drive both and assert their SUM is bounded.

Cases:
  case_distinct_videos_are_capped  — N different videos through the scrub path
                                     never exceed the cap, and all still build.
  case_the_describe_path_shares_the_build_lane
                                   — the same holds through warm_one_sync.
  case_a_busy_lane_is_retryable_not_a_cooldown
                                   — a rejection is `busy`, and `busy` maps to
                                     the RETRY side of the reason vocabulary.

Exit 0 = all cases passed. Temp DB bound by _harness (never prod); the
storyboard store is bound to a throwaway temp dir BEFORE server is imported.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import os  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

_TMP = Path(tempfile.gettempdir()) / f"storyboard_cap_test_{uuid.uuid4().hex}"
os.environ["STORYBOARD_DIR"] = str(_TMP / "storyboard")
# Bind the cap to a small, known number. Reading it off the module under test
# would make every assertion below tautological — it would pass at any value,
# including one that never bounds anything.
os.environ["STORYBOARD_BUILD_CONCURRENCY"] = "2"

import admission  # noqa: E402
import server  # noqa: E402 — after _harness (DB) + the store dir are bound
import vault_frames  # noqa: E402

_BUILD_CAP = 2


class _Meter:
    """Counts real overlap. Builds run on worker threads, so this is guarded by
    a lock — it measures what actually collided, not scheduling intent."""

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


class _FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}


def case_distinct_videos_are_capped():
    """`_storyboard_locks` stops the SAME video building twice. Nothing stopped
    N different videos putting N ffmpeg processes on a 2-core box — that is what
    `_STORYBOARD_BUILD_CAP` is for, and it is the only CPU-bound lane here."""
    meter = _Meter()
    real_dl = server._storyboard_download
    real_extract = server._storyboard_extract_batch

    def _fake_download(request, u, src_path, session_id=None):
        meter.enter(u)
        src_path.parent.mkdir(parents=True, exist_ok=True)
        src_path.write_bytes(b"fake-mp4")
        time.sleep(0.05)
        return True

    def _fake_extract(src_path, dest, indices, dur):
        try:
            for i in indices:
                (dest / f"{i}.jpg").write_bytes(b"jpg")
            return True
        finally:
            meter.leave()

    server._storyboard_download = _fake_download
    server._storyboard_extract_batch = _fake_extract
    try:
        vids = [f"https://cdn2.onlyfans.com/files/v/vv/clip{n}/source.mp4" for n in range(12)]

        def _one(u: str) -> bool:
            return server._ensure_storyboard_frame(
                _FakeRequest(), u, server._video_path_hash(u), 0, hint_duration=10.0)

        with ThreadPoolExecutor(max_workers=len(vids)) as pool:
            oks = list(pool.map(_one, vids))
    finally:
        server._storyboard_download = real_dl
        server._storyboard_extract_batch = real_extract

    assert all(oks), f"a capped build must still produce its frame: {oks}"
    assert len(meter.calls) == len(vids), \
        f"only {len(meter.calls)}/{len(vids)} videos were built"
    assert meter.peak <= _BUILD_CAP, (
        f"{len(vids)} distinct videos ran {meter.peak} concurrent builds; cap "
        f"is {_BUILD_CAP} — N ffmpeg processes on a 2-core box is the thing "
        "this gate exists to prevent"
    )
    assert meter.peak > 1, \
        "builds serialised completely — a vault of clips would warm one at a time"


def case_the_describe_path_shares_the_build_lane():
    """The gate has to hold for `vault_frames.warm_one_sync`, not just for a
    hover — that is the path a DESCRIBE takes when it meets an un-warmed clip,
    and it runs up to `_VISION_GLOBAL_CONCURRENCY` wide. A cap that only covered
    /img/scrub would have left the expensive lane exactly as it was.

    Both entry points are driven together here, because they take the SAME
    semaphore and the thing worth proving is that their SUM is bounded."""
    meter = _Meter()
    real_extract = server._storyboard_extract_batch

    def _fake_extract(src_path, dest, indices, dur):
        meter.enter(str(dest))
        try:
            time.sleep(0.05)
            for i in indices:
                (dest / f"{i}.jpg").write_bytes(b"jpg")
            return True
        finally:
            meter.leave()

    class _WarmClient:
        timeout_s = 30

        class http:
            @staticmethod
            def get(u, timeout=None, stream=False):
                class _R:
                    status_code = 200

                    @staticmethod
                    def iter_content(chunk_size=0):
                        yield b"fake-mp4"

                    @staticmethod
                    def close():
                        pass
                return _R()

    server._storyboard_extract_batch = _fake_extract
    try:
        vids = [f"https://cdn2.onlyfans.com/files/v/vv/warm{n}/source.mp4"
                for n in range(10)]

        def _one(u: str) -> str:
            return vault_frames.warm_one_sync(_WarmClient(), u, 10.0)

        with ThreadPoolExecutor(max_workers=len(vids)) as pool:
            outcomes = list(pool.map(_one, vids))
    finally:
        server._storyboard_extract_batch = real_extract

    assert all(o == "warmed" for o in outcomes), \
        f"a capped warm must still produce frames: {outcomes}"
    assert meter.peak <= _BUILD_CAP, (
        f"{len(vids)} describe-path warms ran {meter.peak} concurrent ffmpegs; "
        f"cap is {_BUILD_CAP} — warm_one_sync is not taking the build slot, so "
        "the lane the 120s describe tail came from is still open"
    )


def case_a_busy_lane_is_retryable_not_a_cooldown():
    """`busy` must land on the retry side of the reason vocabulary. Anything
    unmapped falls to `no_variant`, which is the 7-day DRM cool-off — so a clip
    that merely arrived while ffmpeg was saturated would be frozen out of
    describe for a week. That exact confusion froze 1,777 items once already."""
    assert vault_frames._WARM_REASON.get("busy") == "fetch_failed", (
        "a full build lane resolved to "
        f"{vault_frames._WARM_REASON.get('busy', 'no_variant (UNMAPPED)')!r} — "
        "being busy says nothing about the clip and must never cool it off"
    )

    # And the outcome really is `busy` when there is no slot to be had.
    held = [admission.STORYBOARD_BUILD.enter(f"hold{i}") for i in range(_BUILD_CAP)]
    assert all(held), "could not saturate the build lane"
    real_wait = admission.STORYBOARD_BUILD.wait_s
    admission.STORYBOARD_BUILD.wait_s = 0.05   # don't sit through the real wait
    try:
        out = vault_frames.warm_one_sync(
            object(), "https://cdn2.onlyfans.com/files/v/vv/blocked/source.mp4", 10.0)
        assert out == "busy", f"a saturated lane returned {out!r}, not 'busy'"
    finally:
        admission.STORYBOARD_BUILD.wait_s = real_wait
        for _ in range(_BUILD_CAP):
            admission.STORYBOARD_BUILD.exit()


_harness.run(
    case_distinct_videos_are_capped,
    case_the_describe_path_shares_the_build_lane,
    case_a_busy_lane_is_retryable_not_a_cooldown,
)
