#!/usr/bin/env python3
import importlib
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _harness  # noqa: E402


def _fresh(tmp: Path):
    os.environ["LANE_CONFIG_PATH"] = str(tmp)
    sys.modules.pop("lane_config", None)
    sys.modules.pop("restart_budget", None)
    return importlib.import_module("restart_budget")


def _ledger(tmp: Path) -> Path:
    return tmp.with_name("lane_restarts.json")


def case_budget_starts_full_and_spends_down():
    with tempfile.TemporaryDirectory() as d:
        rb = _fresh(Path(d) / "lc.json")
        assert rb.budget()["remaining"] == rb.LIMIT
        assert rb.budget()["used"] == 0

        after = rb.spend()
        assert after is not None, "the first restart must be allowed"
        assert (after["used"], after["remaining"]) == (1, rb.LIMIT - 1), after


def case_retry_after_counts_from_the_oldest_stamp():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        rb = _fresh(p)
        now = time.time()
        _ledger(p).write_text(json.dumps([now - 3000, now]), "utf-8")

        budget = rb.budget()
        assert budget["remaining"] == 0, budget
        assert 598 <= budget["retry_after_s"] <= 604, (
            f"the window frees when the OLDEST stamp leaves it: 3600-3000=600, "
            f"got {budget['retry_after_s']}"
        )


def case_budget_survives_a_reimport():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        rb = _fresh(p)
        for _ in range(rb.LIMIT):
            rb.spend()

        reborn = _fresh(p)
        assert reborn.budget()["remaining"] == 0, (
            "the ledger must outlive the process it limits — an in-memory "
            "counter would reset on the very event it counts"
        )
        assert reborn.spend() is None


def case_concurrent_spends_never_exceed_the_limit():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        rb = _fresh(p)
        threads_n = 8
        barrier = threading.Barrier(threads_n)
        granted: list[dict] = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            result = rb.spend()
            if result is not None:
                with lock:
                    granted.append(result)

        threads = [threading.Thread(target=worker) for _ in range(threads_n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(granted) == rb.LIMIT, (
            f"{len(granted)} restarts granted against a limit of {rb.LIMIT}"
        )
        on_disk = json.loads(_ledger(p).read_text("utf-8"))
        assert len(on_disk) == rb.LIMIT, (
            f"every granted restart must be RECORDED, else the next boot's "
            f"budget is wrong: granted {len(granted)}, ledger has {len(on_disk)}"
        )
        assert rb.budget()["remaining"] == 0


def case_the_clock_is_read_inside_the_lock():
    with tempfile.TemporaryDirectory() as d:
        rb = _fresh(Path(d) / "lc.json")
        held: list[bool] = []
        real_time = time.time

        def probe():
            held.append(rb._lock.locked())
            return real_time()

        rb.time.time = probe
        try:
            assert rb.spend() is not None
        finally:
            rb.time.time = real_time

        assert held, "spend() must read the clock at all"
        assert all(held), (
            "spend() read the clock while NOT holding _lock — a spender "
            "preempted in that window prunes a stamp another just committed"
        )


def case_stamps_outside_the_window_do_not_count():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        rb = _fresh(p)
        old = time.time() - rb.WINDOW_S - 60
        _ledger(p).write_text(json.dumps([old] * rb.LIMIT), "utf-8")

        assert rb.budget()["remaining"] == rb.LIMIT, (
            "it is a rolling window, not a lifetime quota"
        )
        assert rb.spend() is not None


def case_future_stamps_do_not_wedge_the_button():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        rb = _fresh(p)
        ahead = time.time() + 86400
        _ledger(p).write_text(json.dumps([ahead] * rb.LIMIT), "utf-8")

        assert rb.budget()["remaining"] == rb.LIMIT
        assert rb.spend() is not None


def case_a_backward_clock_does_not_erase_the_ledger():
    # future stamps are not counted but must be kept, or a backward clock correction erases the budget
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        rb = _fresh(p)
        ahead = time.time() + 1800
        _ledger(p).write_text(json.dumps([ahead, ahead]), "utf-8")

        rb.spend()
        survivors = json.loads(_ledger(p).read_text("utf-8"))
        assert sum(1 for t in survivors if t >= ahead) == 2, (
            f"both future stamps must survive the write so a clock correction "
            f"restores the budget rather than erasing it: {survivors}"
        )


def case_future_stamps_cannot_evict_the_ones_that_count():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        rb = _fresh(p)
        now = time.time()
        seeded = [now - 5] + [now + 3600 + i for i in range(rb._MAX_STAMPS * 2)]
        _ledger(p).write_text(json.dumps(seeded), "utf-8")
        assert rb.budget()["used"] == 1, rb.budget()

        assert rb.spend() is not None, "one in-window stamp leaves budget to spend"
        after = rb.budget()
        assert after["used"] == 2, (
            f"the pre-existing stamp AND the new one must both still count; "
            f"got used={after['used']} — the backstop ate the real stamps"
        )
        assert rb.spend() is None, "and the limit must now actually refuse"


def case_a_corrupt_ledger_keeps_the_good_stamps():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        rb = _fresh(p)
        for junk in ("{not json", '{"used": 2}', '"just a string"', "17"):
            _ledger(p).write_text(junk, "utf-8")
            assert rb.budget()["remaining"] == rb.LIMIT, junk

        _ledger(p).write_text(json.dumps([time.time(), "x", None]), "utf-8")
        assert rb.budget()["remaining"] == rb.LIMIT - 1, rb.budget()


def case_unwritable_ledger_fails_closed():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        rb = _fresh(p)
        _ledger(p).mkdir()

        assert rb.spend() is None, (
            "a restart that cannot be recorded must be refused, not granted"
        )
        assert not list(_ledger(p).parent.glob("." + _ledger(p).name + ".*")), (
            "the failed write must not leave its temp behind"
        )


def case_the_write_is_atomic_and_leaves_no_temp():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        rb = _fresh(p)
        rb.spend()

        on_disk = json.loads(_ledger(p).read_text("utf-8"))
        assert isinstance(on_disk, list) and len(on_disk) == 1, on_disk
        assert all(isinstance(t, (int, float)) for t in on_disk), on_disk
        assert not list(_ledger(p).parent.glob("." + _ledger(p).name + ".*")), (
            "temp file must not survive the write"
        )


_harness.run(
    case_budget_starts_full_and_spends_down,
    case_retry_after_counts_from_the_oldest_stamp,
    case_budget_survives_a_reimport,
    case_concurrent_spends_never_exceed_the_limit,
    case_the_clock_is_read_inside_the_lock,
    case_stamps_outside_the_window_do_not_count,
    case_future_stamps_do_not_wedge_the_button,
    case_a_backward_clock_does_not_erase_the_ledger,
    case_future_stamps_cannot_evict_the_ones_that_count,
    case_a_corrupt_ledger_keeps_the_good_stamps,
    case_unwritable_ledger_fails_closed,
    case_the_write_is_atomic_and_leaves_no_temp,
)
