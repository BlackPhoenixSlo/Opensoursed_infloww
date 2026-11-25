import time

import pytest

from slop.lib.badge_metrics import (Read, amber_gate, both_circles, counter_moves, dots, gap_ok, group_reads,
                                    over_pages, p95, queue_reads, raw_attempts, raw_leak, relay_marks,
                                    single_flight_ok, lag, stale_answers, window_reads)


@pytest.mark.parametrize("truth, observed, end, want", [
    ([(0, 3)], [(0.5, 3)], 10, [0.5]),
    ([(0, 3)], [], 10, [10]),
    ([(0, 3)], [(-1, 3)], 10, [0]),
    ([(0, 3), (1, 4)], [(2, 4)], 10, [2, 1]),
    ([(0, 3), (1, 4), (2, 5)], [(1.5, 4), (3, 5)], 10, [1.5, 0.5, 1]),
    ([(0, 3), (1, 4)], [(0.2, 9)], 10, [10, 9]),
    ([(0, 3), (4, 5)], [(1, 3), (2, 7)], 10, [1, 6]),
    ([(0, 3), (1, 4), (2, 3)], [(-1, 3)], 10, [0, 1, 0]),
])
def test_lag(truth, observed, end, want):
    assert lag(truth, observed, end) == pytest.approx(want)


@pytest.mark.parametrize("xs, want", [
    ([], None),
    ([7.0], 7.0),
    ([3.0, 1.0], 3.0),
    ([float(i) for i in range(20, 0, -1)], 19.0),
    ([float(i) for i in range(1, 101)], 95.0),
])
def test_p95(xs, want):
    assert p95(xs) == want


def _c(t, offset, account="1", status=200, dur=0.25, query=None):
    return {"t0": t, "t": t + dur, "account": account, "route": "GET /api2/v2/chats", "status": status,
            "query": query if query is not None else f"limit=10&offset={offset}&filter=unread&order=recent"}


def test_two_page_read_counts_once():
    assert group_reads([_c(0, 0), _c(0.125, 10)]) == [Read("1", 0, 0.375, 2)]


def test_page_two_close_behind_never_fails_gap():
    reads = group_reads([_c(0, 0), _c(0.1, 10), _c(5, 0), _c(5.1, 10)])
    assert len(reads) == 2
    assert gap_ok([r.start for r in reads], 5) == (True, 5)


def test_three_page_read_is_flagged():
    reads = group_reads([_c(0, 0), _c(0.1, 10), _c(0.2, 20), _c(6, 0)])
    assert [r.pages for r in reads] == [3, 1]
    assert over_pages(reads) == [reads[0]]


def test_group_reads_per_creator_and_ignores_other_calls():
    calls = [_c(0, 0, "1"), _c(0.05, 0, "2"), _c(0.125, 10, "1"), _c(0.25, 10, "2"),
             _c(1, 0, query="limit=10&offset=0&order=recent"),
             {**_c(2, 0), "route": "GET /api2/v2/chats/{id}/messages"}]
    assert group_reads(calls) == [Read("1", 0, 0.375, 2), Read("2", 0.05, 0.5, 2)]


def test_orphan_cursor_page_starts_its_own_read():
    assert group_reads([_c(3, 10)]) == [Read("1", 3, 3.25, 1)]


def test_t0_missing_falls_back_to_t():
    assert group_reads([{**_c(1, 0), "t0": None}]) == [Read("1", 1.25, 1.25, 1)]


def test_raw_attempts_count_every_unread_call_429s_included():
    calls = [_c(0, 0, status=429), _c(6, 0), _c(6.1, 10), _c(7, 0, query="offset=0")]
    assert raw_attempts(calls) == 3
    assert len(group_reads(calls)) == 2


@pytest.mark.parametrize("starts, want", [
    ([], (True, None)),
    ([4.0], (True, None)),
    ([0.0, 5.0], (True, 5.0)),
    ([0.0, 4.999], (False, 4.999)),
    ([10.0, 0.0, 5.0], (True, 5.0)),
    ([0.0, 6.0, 9.0], (False, 3.0)),
])
def test_gap_ok(starts, want):
    ok, worst = gap_ok(starts, 5)
    assert ok == want[0] and worst == pytest.approx(want[1])


@pytest.mark.parametrize("spans, ok, overlaps", [
    ([], True, []),
    ([(0, 1), (1, 2)], True, []),
    ([(0, 1), (0.999, 2)], False, [((0, 1), (0.999, 2))]),
    ([(1, 2), (0, 5)], False, [((0, 5), (1, 2))]),
    ([(0, 5), (1, 2), (3, 4)], False, [((0, 5), (1, 2)), ((0, 5), (3, 4))]),
])
def test_single_flight_ok(spans, ok, overlaps):
    assert single_flight_ok(spans) == (ok, overlaps)


@pytest.mark.parametrize("red, amber, want", [
    (set(), set(), set()),
    ({1, 2}, {3}, set()),
    ({1, 2}, {2, 3}, {2}),
    ([1, 2, 3], [3, 2], {2, 3}),
])
def test_both_circles(red, amber, want):
    assert both_circles(red, amber) == want


@pytest.mark.parametrize("served, raw, red, want", [
    ([(5, "1", 4)], [(0, "1", 4)], [(0, "1", 4)], []),
    ([(5, "1", 5)], [(0, "1", 5)], [(0, "1", 4)], [(5, "1", 5)]),
    ([(5, "1", 4)], [(0, "1", 5)], [(0, "1", 4)], []),
    ([(5, "1", 5)], [(0, "1", 5), (4, "1", 4)], [(0, "1", 4)], []),
    ([(5, "1", 5)], [(0, "1", 5)], [(0, "1", 4), (6, "1", 5)], [(5, "1", 5)]),
    ([(5, "1", 5)], [(0, "2", 5)], [(0, "2", 4)], []),
    ([(1, "1", 5)], [(2, "1", 5)], [(0, "1", 4)], []),
])
def test_raw_leak(served, raw, red, want):
    assert raw_leak(served, raw, red) == want


def test_lag_and_raw_leak_scale_to_thousands_of_points():
    truth = [(float(i), i) for i in range(3000)]
    observed = [(i + 0.5, i) for i in range(0, 3000, 2)]
    t0 = time.perf_counter()
    got = lag(truth, observed, 4000.0)
    leaks = raw_leak([(i + 0.5, "1", i) for i in range(3000)], [(float(i), "1", i) for i in range(3000)],
                     [(float(i), "1", -1) for i in range(3000)])
    assert time.perf_counter() - t0 < 1
    assert got == [0.5 if i % 2 == 0 else 1.5 for i in range(2999)] + [1001.0]
    assert len(leaks) == 3000


@pytest.mark.parametrize("reads, want", [
    ([], []),
    ([{"via": "relay"}, {"via": "of_web"}, {"via": "relay_send"}, {"via": "relay_mute"}], []),
    ([{"via": "relay_get", "fan": 1}, {"via": "relay", "fan": 2}], [{"via": "relay_get", "fan": 1}]),
])
def test_relay_marks(reads, want):
    assert relay_marks(reads) == want


@pytest.mark.parametrize("frames, before, want", [
    ([], {"a": 3}, []),
    ([{"kind": "counter", "account": "a", "value": 3}, {"kind": "dm", "account": "a", "value": 9}], {"a": 3}, []),
    ([{"kind": "counter", "account": "a", "value": 2}], {"a": 3}, [{"kind": "counter", "account": "a", "value": 2}]),
    ([{"kind": "counter", "account": "b", "value": 0}], {"a": 3}, [{"kind": "counter", "account": "b", "value": 0}]),
])
def test_counter_moves(frames, before, want):
    assert counter_moves(frames, before) == want


def _w(t, offset, account="1", dur=0.5, filt=None):
    q = f"limit=25&offset={offset}&order=recent&skip_users=all" + (f"&filter={filt}" if filt else "")
    return {"t0": t, "t": t + dur, "account": account, "route": "GET /api2/v2/chats", "status": 200, "query": q}


def test_window_reads_are_page_zero_unfiltered_calls():
    calls = [_w(0, 0), _w(0.5, 10), _w(1.0, 20), _w(2, 0, filt="unread"), _w(3, 0, account="2"),
             {**_w(4, 0), "route": "GET /api2/v2/chats/{id}/messages"}]
    assert window_reads(calls) == [(0, 0.5, "1"), (3, 3.5, "2")]


R1, R2 = (100.0, 101.5, "1"), (140.0, 141.5, "1")


@pytest.mark.parametrize("answers, judged, stale", [
    ([(99.0, 101.6, "1", 101.5)], 0, []),
    ([(100.4, 101.6, "1", 101.5)], 1, []),
    ([(100.4, 100.45, "1", 60.0)], 1, [(100.4, 100.45, "1", 60.0)]),
    ([(120.0, 120.01, "1", 101.5)], 1, []),
    ([(139.0, 141.6, "1", 141.5)], 1, []),
    ([(141.0, 141.6, "1", 101.5)], 1, [(141.0, 141.6, "1", 101.5)]),
    ([(120.0, 120.01, "2", 1.0)], 0, []),
])
def test_stale_answers(answers, judged, stale):
    assert stale_answers(answers, [R1, R2]) == (judged, stale)


ROWS = {1: (True, False), 2: (False, False), 3: (True, True), 4: (True, False)}


@pytest.mark.parametrize("events, want", [
    ([], {1: True, 2: False, 3: False, 4: True}),
    ([(5.0, 1, False), (5.1, 2, True)], {1: False, 2: True, 3: False, 4: True}),
    ([(6.0, 1, True), (5.0, 1, False)], {1: True, 2: False, 3: False, 4: True}),
    ([(5.0, 3, True)], {1: True, 2: False, 3: False, 4: True}),
    ([(5.0, None, False), (6.0, 4, True)], {1: False, 2: False, 3: False, 4: True}),
    ([(5.0, 9, True)], {1: True, 2: False, 3: False, 4: True, 9: True}),
])
def test_dots(events, want):
    assert dots(ROWS, events) == want


@pytest.mark.parametrize("present, require, ok, want", [
    (True, False, True, True),
    (True, False, False, False),
    (True, True, True, True),
    (True, True, False, False),
    (True, False, None, None),
    (True, True, None, False),
    (False, False, True, None),
    (False, False, None, None),
    (False, True, True, False),
    (False, True, None, False),
])
def test_amber_gate(present, require, ok, want):
    got, why = amber_gate(present, require, ok)
    assert got is want
    assert (why is None) == (present and not (require and ok is None))
    if not present:
        assert "amber field is absent" in why and ("require_amber=1" in why) == require


def test_queue_reads_parse_only_kind_queue_lines():
    text = "\n".join((
        "2026-11-23 10:00:01,250 INFO badge_reads: badge_read account=11 kind=queue calls=3 rows=24 counter=- "
        "complete=- mismatch=- flips=- restricted=-",
        "2026-11-23 10:00:02,000 INFO badge_reads: badge_read account=11 kind=frame calls=1 rows=4 counter=7",
        "2026-11-23 10:00:03,000 INFO badge_reads: badge_read_failed account=11 kind=queue error=OFError",
        "2026-11-23 10:00:04,500 INFO badge_reads: badge_read account=12 kind=queue calls=3 rows=20",
    ))
    base = time.mktime(time.strptime("2026-11-23 10:00:00", "%Y-%m-%d %H:%M:%S"))
    assert [(round(t - base, 3), a) for t, a in queue_reads(text)] == [(1.25, "11"), (4.5, "12")]
