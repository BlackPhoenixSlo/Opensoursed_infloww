#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

import os  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

_TMP = Path(tempfile.gettempdir()) / f"storyboard_cap_test_{uuid.uuid4().hex}"
os.environ["STORYBOARD_DIR"] = str(_TMP / "storyboard")
os.environ["STORYBOARD_BUILD_CONCURRENCY"] = "2"

import admission  # noqa: E402
import server  # noqa: E402 — after _harness (DB) + the store dir are bound
import storyboard  # noqa: E402
import vault_frames  # noqa: E402

_BUILD_CAP = 2


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


class _FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}


def case_distinct_videos_are_capped():
    meter = _Meter()
    real_dl = storyboard._storyboard_download
    real_extract = storyboard._storyboard_extract_batch

    def _fake_download(request, u, src_path, session_id=None, media_id=None):
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

    storyboard._storyboard_download = _fake_download
    storyboard._storyboard_extract_batch = _fake_extract
    try:
        vids = [f"https://cdn2.onlyfans.com/files/v/vv/clip{n}/source.mp4" for n in range(12)]

        def _one(u: str) -> bool:
            return storyboard._ensure_storyboard_frame(
                _FakeRequest(), u, storyboard._video_path_hash(u), 0, hint_duration=10.0)

        with ThreadPoolExecutor(max_workers=len(vids)) as pool:
            oks = list(pool.map(_one, vids))
    finally:
        storyboard._storyboard_download = real_dl
        storyboard._storyboard_extract_batch = real_extract

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
    meter = _Meter()
    real_extract = storyboard._storyboard_extract_batch

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

    storyboard._storyboard_extract_batch = _fake_extract
    try:
        vids = [f"https://cdn2.onlyfans.com/files/v/vv/warm{n}/source.mp4"
                for n in range(10)]

        def _one(u: str) -> str:
            return vault_frames.warm_one_sync(_WarmClient(), u, 10.0)

        with ThreadPoolExecutor(max_workers=len(vids)) as pool:
            outcomes = list(pool.map(_one, vids))
    finally:
        storyboard._storyboard_extract_batch = real_extract

    assert all(o == "warmed" for o in outcomes), \
        f"a capped warm must still produce frames: {outcomes}"
    assert meter.peak <= _BUILD_CAP, (
        f"{len(vids)} describe-path warms ran {meter.peak} concurrent ffmpegs; "
        f"cap is {_BUILD_CAP} — warm_one_sync is not taking the build slot, so "
        "the lane the 120s describe tail came from is still open"
    )


def case_a_busy_lane_is_retryable_not_a_cooldown():
    assert vault_frames._WARM_REASON.get("busy") == "fetch_failed", (
        "a full build lane resolved to "
        f"{vault_frames._WARM_REASON.get('busy', 'no_variant (UNMAPPED)')!r} — "
        "being busy says nothing about the clip and must never cool it off"
    )

    held = [admission.STORYBOARD_BUILD.enter(f"hold{i}") for i in range(_BUILD_CAP)]
    assert all(held), "could not saturate the build lane"
    real_wait = admission.STORYBOARD_BUILD.wait_s
    admission.STORYBOARD_BUILD.wait_s = 0.05
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
