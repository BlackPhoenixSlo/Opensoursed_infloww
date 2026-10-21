#!/usr/bin/env python3
"""
`_priority_lane` — the per-account OF concurrency lane in server.py.

Until now it had no tests at all, and its two counters
(`_priority_total_waits` / `_priority_background_waits`) incremented before
EVERY acquire rather than only blocked ones — and nothing read them. So the
question "is this lane actually a queue, and for how long?" had no answer,
which is exactly the question you must answer before bounding the acquire.

These cases pin the accounting (blocked-only counting, real wait times, a
strictly paired in-flight gauge) and the two release paths that a timeout
would later have to get right:

  * case 6 — the body raises: both semaphores come back.
  * case 7 — the SECOND acquire raises while the background slot is already
    held: the background cap must not decay 2 → 1 → 0.

Nothing here is bounded or rejected — this is the observe-first half of P5.

Plain-assert standalone script (no pytest), run via:

    ./venv/bin/python service/tests/test_priority_lane_accounting.py

Exit 0 = all pass.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

# ── Hard-bind a throwaway DB BEFORE importing any service module (same
# PROD-fallback guard as the other service tests).
_TMP_DB = Path(tempfile.gettempdir()) / f"chatterly_lane_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["CHATTERLY_DB_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["SHARE_TOKEN"] = ""
os.environ.setdefault("SESSION_SECRET", "test-session-secret-do-not-use-in-prod")
os.environ.setdefault("CHATTER_SESSION_SECRET", "test-chatter-secret-do-not-use-in-prod")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

HERE = Path(__file__).resolve().parent
SERVICE_ROOT = HERE.parent
sys.path.insert(0, str(SERVICE_ROOT))

import server  # noqa: E402

CAP = server._ACCOUNT_LANE_TOTAL
CAP_BG = server._ACCOUNT_LANE_BACKGROUND


def _aid(tag: str) -> str:
    """A fresh account id per case, so each case reads its own counters."""
    return f"lane-{tag}-{uuid.uuid4().hex[:8]}"


def _stat(account_id: str) -> dict:
    with server._lane_stats_lock:
        return dict(server._lane_stats.get(account_id) or server._new_lane_stat())


def _drain(sem: threading.BoundedSemaphore) -> int:
    """How many slots are free right now (leaves the semaphore as found)."""
    got = 0
    while sem.acquire(blocking=False):
        got += 1
    for _ in range(got):
        sem.release()
    return got


def _assert_lane_whole(account_id: str, label: str) -> None:
    """Both semaphores back at full and the gauge back at zero."""
    total, background = server._lanes_for(account_id)
    assert _drain(total) == CAP, f"{label}: total not fully released ({_drain(total)}/{CAP})"
    assert _drain(background) == CAP_BG, f"{label}: background not fully released"
    st = _stat(account_id)
    assert st["in_flight"] == 0, f"{label}: in_flight={st['in_flight']}"
    assert st["bg_in_flight"] == 0, f"{label}: bg_in_flight={st['bg_in_flight']}"


def _child(stats_path: str | None, body: str) -> dict:
    """Run `body` in a FRESH interpreter that imports server.py — the only
    honest way to test "survives a restart", since a restart is a new process
    with empty module state. Returns whatever the child prints as JSON."""
    env = dict(os.environ)
    env["DATABASE_URL"] = os.environ["DATABASE_URL"]
    env["CHATTERLY_DB_URL"] = os.environ["CHATTERLY_DB_URL"]
    if stats_path is None:
        env["PRIORITY_LANE_STATS_PATH"] = ""      # explicit: persistence off
    else:
        env["PRIORITY_LANE_STATS_PATH"] = stats_path
    code = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(SERVICE_ROOT)!r})\n"
        "import server\n" + body
    )
    r = subprocess.run([sys.executable, "-c", code], env=env,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, f"child failed: {r.stderr[-1500:]}"
    return json.loads(r.stdout.strip().splitlines()[-1])


def main() -> None:
    # ── Case 1: a free slot is NOT a wait.
    # The old counters incremented here, which is why they could never
    # prove queueing. `calls` moves, `blocked_*` must not.
    a = free_aid = _aid("free")
    with server._priority_lane(a):
        st = _stat(a)
        assert st["in_flight"] == 1, f"case1 in_flight={st['in_flight']}"
    st = _stat(a)
    assert st["calls"] == 1 and st["calls_user"] == 1, f"case1 calls: {st}"
    assert st["blocked_total"] == 0 and st["blocked_background"] == 0, f"case1 blocked: {st}"
    assert st["wait_s_total"] == 0.0 and st["wait_s_max"] == 0.0, f"case1 wait: {st}"
    assert st["in_flight_peak"] == 1, f"case1 peak: {st}"
    _assert_lane_whole(a, "case1")

    # ── Case 2: user saturation — the (CAP+1)th caller queues, is counted
    # as blocked exactly once, and the wait it records is real. It also
    # eventually gets in: the acquire is still unbounded, not a timeout.
    a = sat_aid = _aid("sat")
    total, _bg = server._lanes_for(a)
    for _ in range(CAP):
        assert total.acquire(blocking=False), "case2: could not fill the lane"
    entered = threading.Event()
    done = threading.Event()

    def _late():
        with server._priority_lane(a):
            entered.set()
        done.set()

    t = threading.Thread(target=_late, daemon=True)
    t.start()
    assert not entered.wait(0.2), "case2: entered a full lane"
    held = 0.25
    time.sleep(held)
    total.release()                       # free one slot
    assert entered.wait(2.0), "case2: never acquired after a slot freed"
    assert done.wait(2.0), "case2: never exited"
    t.join(2.0)
    assert not t.is_alive(), "case2: thread stuck"
    st = _stat(a)
    assert st["calls"] == 1, f"case2 calls: {st}"
    assert st["blocked_total"] == 1, f"case2 blocked_total: {st}"
    assert st["blocked_background"] == 0, f"case2 blocked_background: {st}"
    assert st["wait_s_total"] >= held * 0.8, f"case2 wait too small: {st}"
    assert st["wait_s_max"] >= held * 0.8, f"case2 wait_s_max: {st}"
    for _ in range(CAP - 1):
        total.release()
    _assert_lane_whole(a, "case2")

    # ── Case 3: background sub-cap — a 3rd background caller queues on the
    # BACKGROUND semaphore while `total` still has free slots. The two
    # waits must not be conflated: blocked_background moves, blocked_total
    # does not. That distinction is the whole point of the sub-cap.
    a = _aid("bgsat")
    total, background = server._lanes_for(a)
    for _ in range(CAP_BG):
        assert background.acquire(blocking=False), "case3: could not fill the bg sub-cap"
    assert _drain(total) == CAP, "case3: total should still be wide open"
    entered = threading.Event()

    def _late_bg():
        with server._priority_lane_background(a):
            entered.set()

    t = threading.Thread(target=_late_bg, daemon=True)
    t.start()
    assert not entered.wait(0.2), "case3: background caller ignored the sub-cap"
    background.release()
    assert entered.wait(2.0), "case3: never acquired after a bg slot freed"
    t.join(2.0)
    assert not t.is_alive(), "case3: thread stuck"
    st = _stat(a)
    assert st["blocked_background"] == 1, f"case3 blocked_background: {st}"
    assert st["blocked_total"] == 0, f"case3 blocked_total should stay 0: {st}"
    assert st["calls_background"] == 1 and st["calls_user"] == 0, f"case3 priority: {st}"
    assert st["bg_in_flight_peak"] == 1, f"case3 bg peak: {st}"
    for _ in range(CAP_BG - 1):
        background.release()
    _assert_lane_whole(a, "case3")

    # ── Case 4: no account id → no lane, no accounting, no acquire.
    before = dict(server._lane_stats_all)
    lanes_before = len(server._account_lanes)
    with server._priority_lane(None):
        pass
    with server._priority_lane(""):
        pass
    assert len(server._account_lanes) == lanes_before, "case4: created a lane for a falsy id"
    assert server._lane_stats_all["calls"] == before["calls"], "case4: counted a non-entry"

    # ── Case 5: concurrent users never exceed the cap, and the peak gauge
    # sees the saturation. CAP+3 threads, each holding briefly.
    a = _aid("conc")
    n = CAP + 3
    start = threading.Barrier(n)
    errors: list[str] = []

    def _worker():
        try:
            start.wait(5.0)
            with server._priority_lane(a):
                st = _stat(a)
                if st["in_flight"] > CAP:
                    errors.append(f"in_flight={st['in_flight']} > cap {CAP}")
                time.sleep(0.05)
        except Exception as exc:            # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=_worker, daemon=True) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10.0)
        assert not t.is_alive(), "case5: thread stuck"
    assert not errors, f"case5: {errors}"
    st = _stat(a)
    assert st["calls"] == n, f"case5 calls: {st}"
    assert st["in_flight_peak"] == CAP, f"case5 peak should hit the cap exactly: {st}"
    assert st["blocked_total"] >= 1, f"case5 expected queueing: {st}"
    _assert_lane_whole(a, "case5")

    # ── Case 6: the body raises → both semaphores come back and the gauge
    # unwinds. A lane that leaks on the error path decays to zero capacity.
    a = _aid("boom")
    try:
        with server._priority_lane(a, priority="background"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    else:
        raise AssertionError("case6: exception swallowed")
    _assert_lane_whole(a, "case6")

    # ── Case 7: THE LEAK. A background caller holds `background`, then the
    # `total` acquire raises. Without an unwind the background cap decays
    # 2 → 1 → 0 permanently for that account and bulk work silently dies.
    a = _aid("leak")
    real_acquire = server._lane_acquire

    def _explode(sem, account_id, which):
        if account_id == a and which == "total":
            raise RuntimeError("acquire failed")
        return real_acquire(sem, account_id, which)

    def _attempt(box: list):
        try:
            with server._priority_lane(a, priority="background"):
                box.append("body ran")
        except RuntimeError:
            box.append("raised")

    server._lane_acquire = _explode
    try:
        # Run each attempt in a thread with a bounded join: a leak drains the
        # sub-cap to zero and the (CAP_BG+1)th attempt then blocks FOREVER on
        # `background.acquire()`. Assert the decay, don't hang on it.
        for i in range(CAP_BG + 1):
            box: list = []
            t = threading.Thread(target=_attempt, args=(box,), daemon=True)
            t.start()
            t.join(3.0)
            assert not t.is_alive(), (
                f"case7: attempt {i + 1} never returned — the background slot from a "
                f"failed second acquire was never released, so the sub-cap decayed to 0"
            )
            assert box == ["raised"], f"case7: attempt {i + 1} -> {box}"
    finally:
        server._lane_acquire = real_acquire
    _assert_lane_whole(a, "case7")
    st = _stat(a)
    assert st["calls"] == 0, f"case7: a failed entry must not count as a call: {st}"

    # ── Case 8: the stats endpoint reports blocked-only counts in a shape
    # you can read without a decoder ring, and survives a zero-call lane.
    out = server.admin_priority_lane_stats()
    assert out["cap_total"] == CAP and out["cap_background"] == CAP_BG, f"case8 caps: {out}"
    assert out["rejections"] == 0, "case8: observe-first rejects nothing"
    assert "saturated" not in out["overall"], "case8: fleet row has no per-account cap"
    row = out["accounts"][sat_aid]          # the case-2 lane: 1 call, 1 block
    assert row["blocked"] == 1 and row["blocked_rate"] == 1.0, f"case8 row: {row}"
    assert row["wait_s_avg_blocked"] >= 0.2, f"case8 avg wait: {row}"
    assert row["in_flight"] == 0 and row["saturated"] is False, f"case8 gauge: {row}"
    free = out["accounts"][free_aid]        # the case-1 lane: 1 call, no block
    assert free["blocked"] == 0 and free["blocked_rate"] == 0.0, f"case8 free row: {free}"
    assert free["wait_s_avg_blocked"] == 0.0, f"case8 free avg: {free}"
    assert out["overall"]["calls"] >= 1 and out["lanes"] >= 5, f"case8 overall: {out}"

    # ── Case 9: THE RESTART. Cumulative counters must cross process death —
    # an observe-first window that resets on every relay recreate reads as
    # "no queueing", which is the one wrong answer that looks like a result.
    # Gauges must NOT cross it: nothing is in flight in a process that just
    # booted, and a restored gauge would be wrong forever.
    stats_file = str(Path(tempfile.gettempdir()) / f"lane_stats_{uuid.uuid4().hex}.json")
    drive = (
        "aid = 'acct-restart'\n"
        "for _ in range(3):\n"
        "    with server._priority_lane(aid):\n"
        "        pass\n"
        "total, bg = server._lanes_for(aid)\n"
        "total.acquire()\n"                     # leave a slot held at exit
        "server._lane_stats_flush(force=True)\n"
        "print(json.dumps(server.admin_priority_lane_stats()))\n"
    )
    first = _child(stats_file, drive)
    assert first["overall"]["calls"] == 3, f"case9 first run: {first['overall']}"
    assert first["boots"] == 1, f"case9 boots: {first['boots']}"
    assert Path(stats_file).exists(), "case9: nothing was persisted"

    second = _child(stats_file, "print(json.dumps(server.admin_priority_lane_stats()))\n")
    assert second["overall"]["calls"] == 3, (
        f"case9: totals did not survive the restart: {second['overall']}")
    assert second["boots"] == 2, f"case9: boots did not increment: {second['boots']}"
    assert second["overall"]["in_flight"] == 0, (
        f"case9: a live gauge was restored: {second['overall']['in_flight']}")
    assert second["uptime_s"] <= second["window_s"], (
        f"case9: window must span boots, not just this process: {second}")
    assert second["persist_error"] is None, f"case9: {second['persist_error']}"

    third = _child(stats_file, drive)
    assert third["overall"]["calls"] == 6, f"case9: totals must ADD, not replace: {third['overall']}"
    assert third["boots"] == 3, f"case9 boots: {third['boots']}"

    # ── Case 10: a corrupt stats file must not take the relay down with it.
    # Start a fresh window, say so in `persist_error`, keep serving.
    bad = Path(tempfile.gettempdir()) / f"lane_bad_{uuid.uuid4().hex}.json"
    bad.write_text("{not json at all", encoding="utf-8")
    out = _child(str(bad), drive)
    assert out["overall"]["calls"] == 3, f"case10: lane stopped counting: {out['overall']}"
    assert out["persist_error"], "case10: a corrupt file must be reported, not hidden"
    assert out["boots"] == 1, f"case10: a fresh window starts at boot 1: {out['boots']}"

    # ── Case 11: persistence off is a supported state, not a crash.
    out = _child(None, drive)
    assert out["persisted_to"] is None, f"case11: {out['persisted_to']}"
    assert out["overall"]["calls"] == 3, f"case11: {out['overall']}"

    print("OK  11/11 priority-lane accounting cases passed")


if __name__ == "__main__":
    main()
