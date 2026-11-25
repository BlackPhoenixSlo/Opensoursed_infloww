#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

from collections import Counter  # noqa: E402
from dataclasses import replace  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import transaction_ingest_decide as d  # noqa: E402
from transaction_ingest_decide import ScanState  # noqa: E402

NOW = datetime(2026, 10, 30, 12, 0, 0)


def _mode(st, **kw):
    return d.decide_mode(st, **kw).mode


def _seeded(st, now, **kw):
    return d.decide_mode(st, now=now, **kw).state


_rng = __import__("random").Random(7)
FLEET = [str(_rng.randrange(10**8, 10**9)) for _ in range(50)]


def _full_ticks(aid: str, tick_s: float, hours: float, t0: datetime,
                last: datetime | None = None) -> list[int]:
    st, out = ScanState(fully_backfilled=True, last_full_at=last), []
    ph = d.full_phase_s(aid)
    for n in range(int(hours * 3600 / tick_s)):
        now = t0 + timedelta(seconds=n * tick_s)
        mode, st = d.decide_mode(st, now=now, phase_s=ph)
        if mode == "refresh":
            out.append(n)
            st = replace(st, last_full_at=now)
    return out


def case_full_phase_deterministic_in_period():
    got = [d.full_phase_s(a) for a in FLEET]
    assert all(0 <= g < 7200 and isinstance(g, int) for g in got), got
    assert got == [d.full_phase_s(a) for a in FLEET], "phase must not change between calls"
    assert d.full_phase_s("80000112") == __import__("zlib").crc32(b"80000112") % 7200
    assert d.full_phase_s("80000112", 3600) == __import__("zlib").crc32(b"80000112") % 3600


def case_restart_herd_spreads_within_one_period_then_exact_period():
    t0 = NOW + timedelta(seconds=123)
    second = Counter()
    for aid in FLEET:
        fulls = _full_ticks(aid, 900, 26, t0)
        assert 1 <= fulls[0] <= 8, (aid, fulls[:3])
        assert {b - a for a, b in zip(fulls, fulls[1:])} == {8}, (aid, fulls)
        second[fulls[0]] += 1
    spread = [second[n] for n in range(1, 9)]
    print(f"    full-walk phase spread of 50 Creators over the 8 ticks of a period: {spread}")
    assert sum(spread) == 50 and max(spread) <= 16 and min(spread) >= 1, spread
    for aid in FLEET[:10]:
        fulls = _full_ticks(aid, 905, 26, t0)
        gaps = {(b - a) * 905 for a, b in zip(fulls, fulls[1:])}
        assert all(7200 - 905 <= g <= 7200 + 905 for g in gaps), (aid, gaps)


def case_full_watermark_seed_failure_and_rollback():
    full, ph = d._DEFAULT_FULL_EVERY_S, 437
    B = NOW - timedelta(seconds=ph)
    done = ScanState(fully_backfilled=True)
    assert _seeded(done, NOW).last_full_at == NOW
    for st in (ScanState(), ScanState(oldest_seen_occurred_at=NOW), replace(done, last_full_at=B)):
        assert _seeded(st, NOW) is st, st
    assert _mode(_seeded(done, NOW), now=NOW, phase_s=ph) == "recent"
    s = _seeded(done, B - timedelta(seconds=1))
    assert _mode(s, now=B, phase_s=ph) == "refresh"
    assert _mode(s, now=B - timedelta(milliseconds=500), phase_s=ph) == "recent"
    for every in (900.0, 3600.0, 86400.0):
        p = d.full_phase_s("80000112", every)
        start = datetime(1970, 1, 1) + timedelta(
            seconds=d.full_bucket(NOW, full_every_s=every, phase_s=p) * every - p)
        st = replace(done, last_full_at=start)
        assert _mode(st, now=start + timedelta(seconds=every - 1), full_every_s=every, phase_s=p) == "recent"
        assert _mode(st, now=start + timedelta(seconds=every), full_every_s=every, phase_s=p) == "refresh"
        assert _mode(st, now=start - timedelta(seconds=1), full_every_s=every, phase_s=p) == "refresh"
    at = NOW - timedelta(minutes=3)
    f = d.scan_after_failure(replace(done, last_full_at=B - timedelta(hours=2)), False, NOW,
                             error="OF 429", full_at=at)
    assert (f.last_full_at, f.current_status, f.consecutive_failures, f.last_error, f.full_walk_failures) == (
        at, "error", 1, "full_walk_failed: OF 429", 1)
    refused = d.scan_after_failure(done, True, NOW, error="refused", full_at=at)
    assert (refused.last_full_at, refused.full_walk_failures) == (None, 0), refused
    third = d.scan_after_failure(replace(done, consecutive_failures=2), False, NOW, error="x", full_at=at)
    assert third.current_status == "paused" and third.last_full_at == at, third
    kept = d.scan_after_failure(replace(done, last_full_at=B), False, NOW, error="x")
    assert kept.last_full_at == B
    ok = dict(inserted=0, patched=0, last_marker=None, rows_min=None, rows_max=None, now=NOW)
    assert d.scan_after_success(replace(done, last_full_at=B), mode="recent", floor_reached=True,
                                **ok).state.last_full_at == B
    assert d.scan_after_success(done, mode="refresh", floor_reached=False, full_at=at, **ok).state.last_full_at == at
    assert _mode(f, now=NOW, phase_s=ph) == "recent", "a failed full walk re-walks in its period"
    future = replace(done, last_full_at=NOW + timedelta(hours=3))
    assert _mode(future, now=NOW, phase_s=ph) == "refresh"
    assert _mode(replace(future, last_full_at=NOW), now=NOW + timedelta(seconds=1), phase_s=ph) == "recent"
    # A boot on a persisted DB: only the accounts whose period turned over walk full.
    fulls = _full_ticks("80000112", 900, 3, NOW, last=NOW - timedelta(seconds=1))
    p = d.full_phase_s("80000112")
    same = d.full_bucket(NOW, full_every_s=full, phase_s=p) == d.full_bucket(
        NOW - timedelta(seconds=1), full_every_s=full, phase_s=p)
    assert (fulls[0] != 0) if same else (fulls[0] == 0), (fulls, same)
    due, not_due = 0, 0
    for aid in FLEET:
        p = d.full_phase_s(aid)
        last = NOW - timedelta(minutes=20)
        crossed = d.full_bucket(NOW, full_every_s=full, phase_s=p) != d.full_bucket(last, full_every_s=full, phase_s=p)
        first = _full_ticks(aid, 900, 0.25, NOW, last=last)
        assert bool(first) == crossed, (aid, first, crossed)
        due, not_due = due + crossed, not_due + (not crossed)
    assert due and not_due and due < len(FLEET) // 2, (due, not_due)


def case_the_boot_after_an_outage_is_no_full_walk_herd():
    full, ph = d._DEFAULT_FULL_EVERY_S, 437
    done = ScanState(fully_backfilled=True)
    B = NOW - timedelta(seconds=ph)
    table = [
        (B - timedelta(seconds=1), False),
        (B - timedelta(seconds=full), False),
        (B - timedelta(seconds=full + 1), True),
        (NOW - timedelta(hours=26), True),
        (B, False),
        (NOW + timedelta(hours=3), False),
    ]
    for last, seeded in table:
        st = replace(done, last_full_at=last)
        got = _seeded(st, NOW, full_every_s=full, phase_s=ph)
        assert (got.last_full_at == NOW) == seeded and (got is st) == (not seeded), (last, got)
    stale = NOW - timedelta(hours=26)
    for st, seeded in [(ScanState(oldest_seen_occurred_at=NOW, last_full_at=stale), True),
                       (ScanState(backfill_stalls=1, last_full_at=stale), True),
                       (ScanState(oldest_seen_occurred_at=NOW, last_full_at=B - timedelta(seconds=1)), False),
                       (ScanState(oldest_seen_occurred_at=NOW), False),
                       (ScanState(last_full_at=stale), False)]:
        got = _seeded(st, NOW, full_every_s=full, phase_s=ph)
        assert (got.last_full_at == NOW) == seeded and (got is st) == (not seeded), (st, got)
        if seeded:
            assert _mode(got, now=NOW, full_every_s=full, phase_s=ph) == "backfill", got
    t0 = NOW + timedelta(seconds=123)
    first = Counter()
    for aid in FLEET:
        fulls = _full_ticks(aid, 900, 4, t0, last=t0 - timedelta(hours=26))
        assert fulls and 1 <= fulls[0] <= 8, (aid, fulls[:3])
        first[fulls[0]] += 1
    assert max(first.values()) <= 16, first


def case_window_and_mode():
    done = ScanState(fully_backfilled=True)
    full, phase = d._DEFAULT_FULL_EVERY_S, 437
    B = NOW - timedelta(seconds=phase)
    assert d.full_bucket(B, full_every_s=full, phase_s=phase) == d.full_bucket(NOW, full_every_s=full, phase_s=phase)
    assert d.full_bucket(B - timedelta(seconds=1), full_every_s=full, phase_s=phase) \
        == d.full_bucket(NOW, full_every_s=full, phase_s=phase) - 1
    table = [
        ("no scan row", None, None, 0, "backfill"),
        ("never backfilled", ScanState(), None, 0, "backfill"),
        ("backfilling, full walk recent", ScanState(), NOW, 0, "backfill"),
        ("walk started, full walk this period", ScanState(oldest_seen_occurred_at=NOW), B, phase, "backfill"),
        ("walk started, full walk due", ScanState(oldest_seen_occurred_at=NOW), B - timedelta(seconds=1), phase, "refresh"),
        ("walk started, never stamped", ScanState(oldest_seen_occurred_at=NOW), None, phase, "refresh"),
        ("walk not started, full walk due", ScanState(), B - timedelta(seconds=1), phase, "backfill"),
        ("walk stopped on its first page, full walk due",
         ScanState(backfill_stalls=1, last_error="backfill_stopped: blank_first_page"), None, phase, "refresh"),
        ("walk stopped on its first page, full walk done",
         ScanState(backfill_stalls=1, last_error="backfill_stopped: blank_first_page"), B, phase, "backfill"),
        ("walk stopped, then a tick failed: still started",
         ScanState(backfill_stalls=1, last_error="RuntimeError('OF 500')"), None, phase, "refresh"),
        ("stop words in last_error alone decide nothing",
         ScanState(last_error="backfill_stopped: blank_first_page"), None, phase, "backfill"),
        ("a tick failed before any page: not stopped", ScanState(last_error="OF 500"), None, phase, "backfill"),
        ("backfilled, never stamped: recent, no deploy herd", done, None, phase, "recent"),
        ("full walk at the start of this period", done, B, phase, "recent"),
        ("full walk 5 min ago, same period", done, NOW - timedelta(minutes=5), phase, "recent"),
        ("full walk 1 s before this period", done, B - timedelta(seconds=1), phase, "refresh"),
        ("10 min ago is the previous period at this phase", done, NOW - timedelta(minutes=10), phase, "refresh"),
        ("phase 0: NOW is the boundary, 1 s ago was the last period", done, NOW - timedelta(seconds=1), 0, "refresh"),
        ("phase 0: a walk at NOW", done, NOW, 0, "recent"),
        ("a walk stamped in a later period (clock stepped back)", done, NOW + timedelta(hours=3), phase, "refresh"),
        ("hours ago: two periods behind (an outage), re-seeded, no boot herd", done,
         NOW - timedelta(hours=5), phase, "recent"),
    ]
    for name, st, last, ph, want in table:
        got = _mode(st if st is None else replace(st, last_full_at=last), now=NOW, phase_s=ph)
        assert got == want, (name, got, want)
    assert _mode(replace(done, last_full_at=NOW - timedelta(seconds=899)), now=NOW,
                 full_every_s=900) == "refresh"
    assert _mode(replace(done, last_full_at=NOW - timedelta(seconds=950)), now=NOW,
                 full_every_s=900) == "recent", "two 900 s periods behind: re-seeded"
    assert d.window_for("recent", ScanState(), NOW) == (NOW - timedelta(hours=24), NOW)
    assert d.window_for("recent", ScanState(), NOW, recent_h=12) == (NOW - timedelta(hours=12), NOW)
    assert d.window_for("refresh", ScanState(), NOW) == (NOW - timedelta(days=7), NOW)
    assert d.window_for("backfill", ScanState(), NOW) == (NOW - timedelta(days=90), NOW)
    floor, oldest = NOW - timedelta(days=30), NOW - timedelta(days=4)
    assert d.window_for("backfill", ScanState(backfill_floor=floor, oldest_seen_occurred_at=oldest), NOW) \
        == (floor, oldest)


def case_a_failing_full_walk_never_reads_green():
    from tx_ingest_admin_api import FULL_WALK_FAILED, _health_status, _tx_ingest_tier
    full = d._DEFAULT_FULL_EVERY_S
    ok = dict(inserted=0, patched=0, last_marker=None, rows_min=None, rows_max=None)
    st, seen = ScanState(fully_backfilled=True, last_full_at=NOW - timedelta(seconds=full)), []
    for period in range(4):
        t = NOW + timedelta(seconds=period * full)
        mode, st = d.decide_mode(st, now=t)
        assert mode == "refresh", (period, st)
        st = d.scan_after_failure(st, False, t, error="OFAPIError('500')", full_at=t)
        for k in range(1, 8):
            tk = t + timedelta(seconds=900 * k)
            mode, st = d.decide_mode(st, now=tk)
            assert mode == "recent", (period, k, st)
            st = d.scan_after_success(st, mode="recent", floor_reached=True, now=tk, **ok).state
        seen.append((st.current_status, st.full_walk_failures, st.consecutive_failures, st.paused_until))
    assert seen == [("ok", n, 0, None) for n in (1, 2, 3, 4)], seen
    assert st.last_error == "full_walk_failed: OFAPIError('500')", st.last_error
    owed = {
        "between ticks (ok)": (st, FULL_WALK_FAILED),
        "in flight (refreshing): keeps its word": (d.scan_started(st, "refresh", NOW, NOW), "refreshing"),
        "in flight (backfilling): keeps its word": (d.scan_started(st, "backfill", NOW, NOW), "backfilling"),
        "idle after a queued backfill": (d.scan_backfill_queued(st, NOW - timedelta(days=30)), FULL_WALK_FAILED),
        "ok after /resume": (replace(st, current_status="ok", paused_until=None), FULL_WALK_FAILED),
        "idle after an interrupt": (d.scan_interrupted(st, "interrupted_mid_tick"), FULL_WALK_FAILED),
        "backfill_partial": (replace(st, current_status=d.BACKFILL_PARTIAL), FULL_WALK_FAILED),
    }
    for name, (s, word) in owed.items():
        assert s.full_walk_failures == 4, (name, s)
        reported = _health_status(s.current_status, 4)
        assert (reported, _tx_ingest_tier(5.0, reported, 4)) == (word, "yellow"), (name, reported)
        assert _tx_ingest_tier(5.0, _health_status(s.current_status, 0), 0) == "green", (name, "count 0: green")
    for status, tier in (("paused", "red"), ("error", "red"), (d.BACKFILL_STALLED, "yellow")):
        assert (_health_status(status, 4), _tx_ingest_tier(5.0, status, 4)) == (status, tier), status
    done = d.scan_after_success(st, mode="refresh", floor_reached=True, now=NOW, full_at=NOW, **ok).state
    assert (done.full_walk_failures, done.last_error, _tx_ingest_tier(5.0, done.current_status, 0)) == (
        0, None, "green"), done


def case_full_walk_failures_table():
    prev = NOW - timedelta(seconds=d._DEFAULT_FULL_EVERY_S)
    clean = ScanState(fully_backfilled=True, last_full_at=prev)
    owed = replace(clean, full_walk_failures=2, current_status="ok",
                   last_error="full_walk_failed: OFAPIError('500')")
    walk = ScanState(oldest_seen_occurred_at=NOW - timedelta(days=3), last_full_at=prev)
    ok = dict(inserted=0, patched=0, last_marker=None, rows_min=None, rows_max=None, now=NOW)

    def success(mode, floor, stop=None):
        return lambda s: d.scan_after_success(s, mode=mode, floor_reached=floor, stop_reason=stop,
                                              full_at=NOW if mode == "refresh" else None, **ok).state
    table = [
        ("completed full walk resets it", owed, success("refresh", True), ("ok", 0, None, NOW)),
        ("cut-short full walk counts, period spent", clean, success("refresh", False, "repeated_page"),
         ("ok", 1, "full_walk_failed: cut_short: repeated_page", NOW)),
        ("cut short at the page ceiling, owed already", owed, success("refresh", False, "page_ceiling"),
         ("ok", 3, "full_walk_failed: cut_short: page_ceiling", NOW)),
        ("failed full walk counts, period spent", clean,
         lambda s: d.scan_after_failure(s, False, NOW, error="OF 429", full_at=NOW),
         ("error", 1, "full_walk_failed: OF 429", NOW)),
        ("failed before page 1 (not a refusal): reached OF, counts", clean,
         lambda s: d.scan_after_failure(s, False, NOW, error="OF 429", full_at=NOW, reached=False),
         ("error", 1, "full_walk_failed: OF 429", NOW)),
        ("proxy refusal before page 1: no stamp, no count", clean,
         lambda s: d.scan_after_failure(s, True, NOW, error="CONNECT refused", full_at=NOW),
         ("idle", 0, "CONNECT refused", prev)),
        ("proxy refusal after page 1: stamped + counted, no streak", clean,
         lambda s: d.scan_after_failure(s, True, NOW, error="CONNECT refused", full_at=NOW, reached=True),
         ("idle", 1, "full_walk_failed: CONNECT refused", NOW)),
        ("proxy refusal while owed: count kept, its own error", owed,
         lambda s: d.scan_after_failure(s, True, NOW, error="CONNECT refused", full_at=NOW),
         ("idle", 2, "CONNECT refused", prev)),
        ("a recent walk leaves it, the line kept", owed, success("recent", True),
         ("ok", 2, "full_walk_failed: OFAPIError('500')", prev)),
        ("a recent failure between overwrote the line: the reason falls back to owed",
         replace(owed, last_error="OF 500"), success("recent", True), ("ok", 2, "full_walk_failed: owed", prev)),
        ("a refusal before page 1 overwrote it, then a recent success: owed", owed,
         lambda s: success("recent", True)(d.scan_after_failure(s, True, NOW, error="CONNECT refused", full_at=NOW)),
         ("ok", 2, "full_walk_failed: owed", prev)),
        ("a recent failure itself reads red, its own error", owed,
         lambda s: d.scan_after_failure(s, False, NOW, error="OF 500"), ("error", 2, "OF 500", prev)),
        ("interrupted while owed", owed, lambda s: d.scan_interrupted(s, "interrupted_mid_tick"),
         ("idle", 2, "interrupted_mid_tick", prev)),
        ("an unfinished walk's backfill_partial, the count kept", replace(walk, full_walk_failures=1),
         success("backfill", False, "tick_cap"), (d.BACKFILL_PARTIAL, 1, "full_walk_failed: owed", prev)),
        ("an unfinished walk's completed refresh: back to backfill_partial", replace(walk, full_walk_failures=1),
         success("refresh", True), (d.BACKFILL_PARTIAL, 0, None, NOW)),
    ]
    for name, st, tick, want in table:
        got = tick(st)
        assert (got.current_status, got.full_walk_failures, got.last_error, got.last_full_at) == want, (name, got)
        assert got.paused_until is None, (name, got)
    refused = d.scan_after_failure(clean, True, NOW, error="CONNECT refused", full_at=NOW)
    assert _mode(refused, now=NOW + timedelta(seconds=900)) == "refresh"
    late = d.scan_after_failure(replace(clean, consecutive_failures=2), True, NOW, error="CONNECT refused",
                                full_at=NOW, reached=True)
    assert (late.consecutive_failures, late.current_status) == (2, "idle"), late
    assert _mode(late, now=NOW + timedelta(seconds=900)) == "recent"


_harness.run()
