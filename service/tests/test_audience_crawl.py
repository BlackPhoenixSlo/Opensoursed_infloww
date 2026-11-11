#!/usr/bin/env python3
"""
audience_crawl — the paced, resumable Audience crawl after a mass send
(docs/spec/phase-02-audience-crawl.md), through `record_after_send` + `drain`, with
a fake OF client (its pages go through `of_pacing.paced`, as OFClient.get_json's do)
and an injected clock and sleep (audience_crawl._now / _sleep). Asserts the stamped
`mass_runs.recipients_json`, the departure log and the `audience_crawl_end` line.

  case_429_resumes_one_page_back:   a 429 at page k resumes at k - 1 and records the full
                                    set exactly (minus excluded ids and an exclude list);
                                    pages = roster pages + 1 overlap.
  case_two_429s_ask_then_ladder:    one page 429 twice: OF's body ask (45 s) then the
                                    ladder's second rung (60 s).
  case_retry_after_header:          `Retry-After: 120` (generic body) waits 120 s and no
                                    GET leaves in between (no in-place retry in of_pacing).
  case_overlap_does_not_reset_ladder: 429, overlap re-read ok, 429 again: 30 s then 60 s.
  case_overlap_end_before_failed_page_truncated: 429 at k, OF ends the roster on the resumed
                                    overlap page (k - 1): the page at k never read, NULL `truncated`
                                    (the gate alone would record it: inside its slack); a list there
                                    is complete iff its usersCount matches the ids read.
  case_deadline_inside_wait:        a wait that would end past the deadline is not waited
                                    and no further GET leaves: NULL, `deadline`.
  case_deadline_reached:            pages that take long reach the deadline: NULL,
                                    `deadline`, no page sent after it.
  case_401_one_call:                one call, NULL, `dead_session`.
  case_proxy_error_retries:         PAGE_TRIES tries 1 s then 2 s apart, then NULL `error`;
                                    one bad try then a good one records.
  case_big_roster_recorded:         250 pages (past of_paging.MAX_PAGES 200) recorded exactly;
                                    1001 pages past AUDIENCE_CRAWL_MAX_PAGES 1000: `truncated`, NULL.
  case_online_filtered_unknown_no_reads: no read; `online` / `unknown_list`; NULL.
  case_queued_sends_share_one_read: two sends queued behind a running crawl are served by the
                                    next round with one roster read (coalesced=1); a send queued
                                    after that round started waits for the one after; another
                                    Creator's crawl runs beside them.
  case_verified_lists_never_fetched: a verified Auto_Exclude and AUTOFENCE (verified_lists) are
                                    never fetched and their verified members are subtracted
                                    (reused=2); per request: another send of the round, without
                                    them verified, reads the list once.
  case_mirror_path_crawled_from_of: an Auto_Exclude past the backstop (the mirror path) whose
                                    mirror differs from OF: ensure_exclude_list verifies nothing,
                                    the crawl reads the list from OF and subtracts OF's members.
  case_mixed_round:                 A needs a truncated list, B only a healthy list: A NULL
                                    `truncated`, B recorded with its list read; C's roster (read
                                    after the lists), needed only by the failed C, is never read.
  case_dead_session_ends_round:     a 401 ends the round: no further GET, every request still
                                    needing a read NULL `dead_session`; one whose reads (a list,
                                    read before the rosters) had all completed is recorded.
  case_request_done_before_round_ends: A needs only a list, B also `fans` that 429s: A is
                                    stamped and logged once the list is read, inside B's waits.
  case_round_deadline_per_request: in one round, a wait past the older send's deadline fails
                                    only that send (`deadline`); the newer one waits and records.
  case_deadline_line_at_its_deadline: a request that reaches its deadline mid-read is logged
                                    then (clock at its deadline), not at the round's end; the
                                    rest of the shared read is charged to the live needer, so
                                    the round's lines still sum to its calls.
  case_deadline_of_request_not_reading: B needs only `following`, A a list that 429s first: a
                                    wait that would end past B's earlier deadline finishes B
                                    (`deadline`) before it starts, not when `following` starts;
                                    `following` is never read; A records.
  case_bad_request_fails_alone:     one bad request in a round with two good ones fails alone:
                                    a named exclude list (the Composer allows names) is
                                    `unknown_list`, never read; a non-numeric excluded id is
                                    `error`; the two good ones share one roster read and record.
  case_list_echo_complete_by_count: a list OF echoes past its end is complete iff its ids number
                                    its usersCount (one get_list after the repeat), else NULL
                                    `truncated`; the count GET is in `pages`.
  case_roster_repeat_retried_once:  a repeated fans page is re-read once at its offset (then
                                    recorded exactly); repeated twice in a row: NULL `truncated`,
                                    mid-roster and past the end alike, no feed read.
  case_page_bound_counts_calls:     a 3-page list with two 429s on page 2: 8 calls = the spec's
                                    bound exactly (pages + 1 + resumes + failed); the line's
                                    pages + failed == the calls; the 3-page roster: 7 calls <= 8.
  case_pages_paced_in_walk:         each page inside `of_pacing.walk("audience_crawl",
                                    retry_429=False)`, departures >= PAGE_GAP_S apart.
  case_legacy_mode_identical:       AUDIENCE_CRAWL_MODE=legacy: send_mass_message records inline
                                    with today's calls, no audience_crawl_end line.
  case_drain_timeout_names_dropped_runs: drain past its timeout cancels the crawl: the in-flight
                                    and queued runs stay NULL, one audience_crawl_cancelled
                                    warning names them all, the queue is empty, no end line; a run
                                    already finished in that round is stamped and not named.
  case_crawler_in_fresh_context:    a context var the first sender set is not visible in the
                                    crawl; its pages count as walk:audience_crawl (innermost).
  case_recover_at_boot_picks_cut_off_sends: seeded mass_runs: an immediate ok send, NULL, inside
                                    its deadline, a list audience, `online`/`filters` false, is
                                    crawled from offset 0 and stamped; one past its deadline, one
                                    `online`, one `filters`, one without the two keys, one already
                                    stamped, one scheduled (no queue_id), one still running and
                                    one with unparsable JSON get no reads; a Creator whose client
                                    does not load is skipped, the rest recover.
  case_recover_stops_at_run_deadline: a recovered crawl's deadline is the run's own (wall clock from
                                    its started_at), not a fresh AUDIENCE_CRAWL_DEADLINE_S: NULL
                                    `deadline`, no page sent past it.
  case_recover_legacy_mode_nothing: AUDIENCE_CRAWL_MODE=legacy: no reads, no crawler, NULL.
  case_recover_unreadable_db_no_raise: the DB read raising: recover_at_boot returns, nothing raised.

  P2b (fetch diet): test_audience_crawl_p2b.py.

Run: ./venv/bin/python service/tests/test_audience_crawl.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402

import audience_crawl  # noqa: E402
import of_call_counter  # noqa: E402
import of_pacing  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, MassRun  # noqa: E402

_REAL_GAP, _REAL_JITTER = of_pacing.PAGE_GAP_S, of_pacing.JITTER_S
_KNOB_ENV = [k for k in os.environ if k.startswith("AUDIENCE_CRAWL_")]
for _k in _KNOB_ENV:
    os.environ.pop(_k)


from _audience_crawl_fixtures import (  # noqa: E402 — the shared fakes and seeding
    AUD, PROBE, TOO_MANY, FakeOF, OFErr, _boot_row, _line, _loader, _outcome, _recorded, _run_row, _send,
    _send_many, _setup,
)


async def case_429_resumes_one_page_back():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 201), lists={77: [3, 150]})   # 4 pages of 50
    of.script[("fans", 100)] = [TOO_MANY(429)]
    run = await _send(of, clock, excluded_users=[2], excluded_user_lists=[77])
    await audience_crawl.drain()
    assert of.offsets() == [0, 50, 100, 50, 100, 150], of.offsets()
    assert await _recorded(run) == [x for x in range(1, 201) if x not in (2, 3, 150)]
    assert clock.waits == [30.0], clock.waits
    ln = _line(lines, run)
    # pages: 5 roster pages (4 + the overlap) + the exclude list's 2 (a bare page, then OF's empty one)
    # + the mass feed's 1; OF counts the same 197, read 30 s (the 429's wait) after the accept
    assert ln == {"account": "ac1", "run": str(run), "outcome": "recorded", "pages": "8", "failed": "1",
                  "resumes": "1", "waited_s": "30.0", "reused": "0", "coalesced": "0", "recipients": "197",
                  "sent_count": "197", "ratio": "1.000", "count_delay_s": "30.0"}, ln
    assert await _outcome(run) == "recorded"


async def case_two_429s_ask_then_ladder():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 151))
    of.script[("fans", 50)] = [TOO_MANY(429, '{"error":{"message":"Too many requests. Please allow 45 seconds"}}'),
                               TOO_MANY(429)]
    run = await _send(of, clock)
    await audience_crawl.drain()
    assert clock.waits == [45.0, 60.0], clock.waits
    assert of.offsets() == [0, 50, 0, 50, 0, 50, 100], of.offsets()
    assert await _recorded(run) == list(range(1, 151))
    assert _line(lines, run)["resumes"] == "2"


async def case_retry_after_header():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 101))
    of.script[("fans", 50)] = [TOO_MANY(429, "Too many requests", headers={"Retry-After": "120"})]
    run = await _send(of, clock)
    await audience_crawl.drain()
    assert clock.waits == [120.0], clock.waits
    i = next(n for n, c in enumerate(of.calls) if c[4] == 429)
    after = of.calls[i + 1:]
    assert after and min(c[0] for c in after) >= of.calls[i][0] + 120.0, of.calls
    assert [c[3] for c in of.calls].count(50) == 2, "one 429, one resumed read: no in-place retry"
    assert await _recorded(run) == list(range(1, 101))


async def case_overlap_does_not_reset_ladder():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 201))
    of.script[("fans", 100)] = [TOO_MANY(429), TOO_MANY(429)]
    run = await _send(of, clock)
    await audience_crawl.drain()
    assert clock.waits == [30.0, 60.0], clock.waits
    assert of.offsets() == [0, 50, 100, 50, 100, 50, 100, 150], of.offsets()
    assert await _recorded(run) == list(range(1, 201))
    # …and a later 429 past the page that failed starts the ladder again.
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 251))
    of.script[("fans", 50)] = [TOO_MANY(429), TOO_MANY(429)]
    of.script[("fans", 150)] = [TOO_MANY(429)]
    run = await _send(of, clock)
    await audience_crawl.drain()
    assert clock.waits == [30.0, 60.0, 30.0], clock.waits


async def case_deadline_inside_wait():
    clock, lines = _setup(AUDIENCE_CRAWL_DEADLINE_S=100)
    of = FakeOF(clock, fans=range(1, 201))
    of.script[("fans", 50)] = [TOO_MANY(429, "x", headers={"Retry-After": "300"})]
    run = await _send(of, clock)
    await audience_crawl.drain()
    assert of.offsets() == [0, 50], of.offsets()
    assert clock.waits == [], clock.waits
    assert await _recorded(run) is None
    ln = _line(lines, run)
    assert (ln["outcome"], ln["recipients"], ln["pages"], ln["failed"]) == ("deadline", "-", "1", "1"), ln


async def case_deadline_reached():
    clock, lines = _setup(AUDIENCE_CRAWL_DEADLINE_S=50)
    of = FakeOF(clock, fans=range(1, 501), cost_s=20.0)
    t0 = clock.now()
    run = await _send(of, clock)
    await audience_crawl.drain()
    assert of.calls and all(c[0] < t0 + 50 for c in of.calls), [c[0] - t0 for c in of.calls]
    assert len(of.calls) == 3, of.offsets()
    assert await _recorded(run) is None
    assert _line(lines, run)["outcome"] == "deadline"
    assert await _outcome(run) == "deadline", "a live send's deadline is a verdict: stamped"


async def case_401_one_call():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 101), following=range(500, 510))
    of.script[("fans", 0)] = [OFErr(401, "Unauthorized")]
    run = await _send(of, clock, user_lists=["fans", "following"])
    await audience_crawl.drain()
    assert len(of.calls) == 1, of.calls
    assert await _recorded(run) is None
    assert _line(lines, run)["outcome"] == "dead_session"
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 101))
    of.script[("fans", 50)] = [OFErr(403, "Forbidden")]
    run = await _send(of, clock)
    await audience_crawl.drain()
    assert of.offsets() == [0, 50] and _line(lines, run)["outcome"] == "dead_session"


async def case_proxy_error_retries():
    clock, lines = _setup()

    class ProxyError(Exception):
        pass
    of = FakeOF(clock, fans=range(1, 101))
    of.script[("fans", 50)] = [ProxyError("CONNECT 403") for _ in range(5)]
    run = await _send(of, clock)
    await audience_crawl.drain()
    assert of.offsets() == [0, 50, 50, 50], of.offsets()
    assert clock.waits == [1.0, 2.0], clock.waits
    assert await _recorded(run) is None
    ln = _line(lines, run)
    assert (ln["outcome"], ln["failed"]) == ("error", "3"), ln
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 101))
    of.script[("fans", 50)] = [ProxyError("timeout")]
    run = await _send(of, clock)
    await audience_crawl.drain()
    assert await _recorded(run) == list(range(1, 101)) and clock.waits == [1.0]


async def case_big_roster_recorded():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 12_501))   # 250 pages of 50
    run = await _send(of, clock)
    await audience_crawl.drain()
    assert len(of.calls) == 250, len(of.calls)
    assert await _recorded(run) == list(range(1, 12_501))
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 50_051))   # 1001 pages
    run = await _send(of, clock)
    await audience_crawl.drain()
    assert len(of.calls) == 1000, len(of.calls)
    assert await _recorded(run) is None
    ln = _line(lines, run)
    assert (ln["outcome"], ln["pages"]) == ("truncated", "1000"), ln


async def case_online_filtered_unknown_no_reads():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 51))
    runs = [await _send(of, clock, online_only=True),
            await _send(of, clock, filters={"online": 1}),
            await _send(of, clock, user_lists=["fans", "recent"])]
    await audience_crawl.drain()
    assert of.calls == [], of.calls
    assert [await _recorded(r) for r in runs] == [None, None, None]
    assert [_line(lines, r)["outcome"] for r in runs] == ["online", "online", "unknown_list"]


async def case_queued_sends_share_one_read():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 151))          # 3 pages: 0, 50, 100
    of.script[("fans", 50)] = [TOO_MANY(429), None, TOO_MANY(429)]   # once in round 1, once in round 2
    other = FakeOF(clock, fans=range(1000, 1101), account_id="ac2")
    runs: dict[str, int] = {}
    real_sleep = clock.sleep

    async def sleep(s):                              # sends arriving while a round waits out a 429
        if len(clock.waits) == 0:                    # round 1 (r0) running: r1, r2 queue behind it
            runs["r1"] = await _send(of, clock)
            runs["r2"] = await _send(of, clock, excluded_users=[7])
        elif len(clock.waits) == 1:                  # round 2 (r1 + r2) running: r3 waits for round 3
            runs["r3"] = await _send(of, clock)
        await real_sleep(s)
    clock.sleep = sleep
    audience_crawl._sleep = sleep
    runs["r0"] = await _send(of, clock)
    runs["x"] = await _send(other, clock, aid="ac2")
    await audience_crawl.drain()
    one = [0, 50, 0, 50, 100]
    assert of.offsets() == one + one + [0, 50, 100], of.offsets()     # 3 roster reads for 4 sends
    full = list(range(1, 151))
    got = {k: await _recorded(r) for k, r in runs.items()}
    assert got == {"r0": full, "r1": full, "r2": [x for x in full if x != 7], "r3": full,
                   "x": list(range(1000, 1101))}, got
    ln = {k: _line(lines, r) for k, r in runs.items()}
    assert [ln[k]["coalesced"] for k in ("r0", "r1", "r2", "r3")] == ["0", "1", "1", "0"], ln
    # the shared read (+ the mass feed's GET) is charged once, to the first request of the round
    assert [(ln[k]["pages"], ln[k]["failed"], ln[k]["resumes"]) for k in ("r1", "r2")] == \
        [("5", "1", "1"), ("0", "0", "0")], ln
    assert other.offsets() == [0, 50, 100], other.offsets()
    assert not audience_crawl._crawlers, audience_crawl._crawlers


async def case_verified_lists_never_fetched():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 21), lists={50: [3, 4, 99], 60: [5, 98]})   # OF's own lists differ
    v = {50: frozenset({3, 4}), 60: frozenset({5})}
    r1 = await _send(of, clock, excluded_users=[2], excluded_user_lists=[50, 60], verified_lists=v)
    await audience_crawl.drain()
    assert of.offsets(("list", 50)) == [] and of.offsets(("list", 60)) == [], of.calls
    assert await _recorded(r1) == [x for x in range(1, 21) if x not in (2, 3, 4, 5)]
    ln = _line(lines, r1)
    assert (ln["reused"], ln["outcome"]) == ("2", "recorded"), ln
    # per request: a send of the same round without list 50 verified reads it (once), the first does not use it
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 21), lists={50: [3, 4, 99]})
    r1, r2 = await _send_many(of, clock, {"excluded_user_lists": [50], "verified_lists": {50: frozenset({3})}},
                              {"excluded_user_lists": [50]})
    await audience_crawl.drain()
    assert of.offsets(("list", 50)) == [0, 3], of.offsets(("list", 50))   # a bare page, then OF's empty one
    assert await _recorded(r1) == [x for x in range(1, 21) if x != 3]
    assert await _recorded(r2) == [x for x in range(1, 21) if x not in (3, 4)]
    assert (_line(lines, r1)["reused"], _line(lines, r2)["reused"]) == ("1", "0")


class _ListOF(FakeOF):
    """FakeOF + the list writes ensure_exclude_list makes (one Auto_Exclude, id 50)."""

    def get_lists(self, **kw):
        return {"list": [{"id": 50, "name": "Auto_Exclude"}], "hasMore": False}

    def add_user_to_list(self, lid, uid):
        self.rows[("list", int(lid))].append(int(uid))

    def remove_user_from_list(self, lid, uid):
        self.rows[("list", int(lid))].remove(int(uid))


async def case_mirror_path_crawled_from_of():
    import audiences
    import of_paging
    clock, lines = _setup()
    # 351 members, 4 list pages: the mirror's capped crawl (MAX_PAGES 3) never sees fan 42 on page 4.
    of = _ListOF(clock, fans=range(1, 101), lists={50: [*range(5000, 5350), 42]})
    saved = of_paging.MAX_PAGES, audiences._schedule_auto_exclude_refresh
    of_paging.MAX_PAGES = 3
    audiences._ae_mirrors.clear()
    audiences._schedule_auto_exclude_refresh = lambda *a, **kw: None   # no refresh racing the crawl
    try:
        verified: dict = {}
        assert await audiences.ensure_exclude_list("ac1", {7}, client=of, verified=verified) == 50
        assert verified == {} and "ac1" in audiences._ae_mirrors, verified
        assert 42 not in audiences._ae_mirrors["ac1"].members        # the mirror differs from OF
        before = len(of.offsets(("list", 50)))
        run = await _send(of, clock, excluded_users=[7], excluded_user_lists=[50], verified_lists=verified)
        await audience_crawl.drain()
    finally:
        of_paging.MAX_PAGES, audiences._schedule_auto_exclude_refresh = saved
        audiences._ae_mirrors.clear()
    assert of.offsets(("list", 50))[before:] == [0, 100, 200, 300, 352], of.offsets(("list", 50))[before:]
    assert await _recorded(run) == [x for x in range(1, 101) if x not in (7, 42)]
    assert _line(lines, run)["reused"] == "0"


async def case_mixed_round():
    clock, lines = _setup(AUDIENCE_CRAWL_MAX_PAGES=2)
    of = FakeOF(clock, fans=range(1, 51), lists={66: list(range(1000, 1250)), 77: [500, 501]})   # 66: 3 pages > 2
    a, b, c = await _send_many(of, clock, {"user_lists": ["66"]}, {"user_lists": ["77"]},
                               {"excluded_user_lists": [66]})
    await audience_crawl.drain()
    assert of.offsets(("list", 66)) == [0, 100], of.offsets(("list", 66))
    assert of.offsets(("list", 77)) == [0, 2], of.calls
    assert of.offsets() == [], "needed only by the failed C: skipped"
    assert [await _recorded(r) for r in (a, b, c)] == [None, [500, 501], None]
    assert [_line(lines, r)["outcome"] for r in (a, b, c)] == ["truncated", "recorded", "truncated"]


async def case_dead_session_ends_round():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 101), following=range(500, 510), lists={77: [700]})
    of.script[("fans", 0)] = [OFErr(401, "Unauthorized")]
    b, a = await _send_many(of, clock, {"user_lists": ["77"]},        # b: read before the 401, complete
                            {"user_lists": ["fans", "following", "77"]})
    await audience_crawl.drain()
    assert [c[2] for c in of.calls] == [("list", 77), ("list", 77), "fans"], of.calls   # nothing after the 401
    assert await _recorded(a) is None and _line(lines, a)["outcome"] == "dead_session"
    assert await _recorded(b) == [700] and _line(lines, b)["outcome"] == "recorded"


async def case_request_done_before_round_ends():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 101), lists={77: [5, 6, 500]})
    of.script[("fans", 0)] = [TOO_MANY(429), TOO_MANY(429)]          # B's roster waits out the ladder
    seen: list = []
    real_sleep = clock.sleep

    async def sleep(s):                                              # inside list 77's 429 waits
        seen.append((await _recorded(a), [p["run"] for p in lines.parsed()]))
        await real_sleep(s)
    audience_crawl._sleep = sleep
    a, b = await _send_many(of, clock, {"user_lists": ["77"]}, {"user_lists": ["fans", "77"]})
    await audience_crawl.drain()
    full = [5, 6, 500]
    assert seen == [(full, [str(a)]), (full, [str(a)])], seen        # A stamped + logged once 77 was read
    assert await _recorded(b) == [*range(1, 101), 500]
    assert [_line(lines, r)["outcome"] for r in (a, b)] == ["recorded", "recorded"]


async def case_round_deadline_per_request():
    clock, lines = _setup(AUDIENCE_CRAWL_DEADLINE_S=100)
    of = FakeOF(clock, fans=range(1, 101))
    of.script[("fans", 50)] = [TOO_MANY(429, "x", headers={"Retry-After": "120"})]
    old, new = await _run_row("ac1"), await _run_row("ac1")
    await audience_crawl.record_after_send("ac1", of, old, user_lists=["fans"], sent_at=clock.now())        # until 1100
    await audience_crawl.record_after_send("ac1", of, new, user_lists=["fans"], sent_at=clock.now() + 60)   # until 1160
    await audience_crawl.drain()
    assert clock.waits == [120.0] and of.offsets() == [0, 50, 0, 50], (clock.waits, of.offsets())
    assert (await _recorded(old), _line(lines, old)["outcome"]) == (None, "deadline")
    assert (await _recorded(new), _line(lines, new)["outcome"]) == (list(range(1, 101)), "recorded")


async def case_deadline_line_at_its_deadline():
    clock, lines = _setup(AUDIENCE_CRAWL_DEADLINE_S=100)
    of = FakeOF(clock, fans=range(1, 501), cost_s=20.0)            # 10 pages, 20 s each: 200 s
    at: dict[str, float] = {}

    class When(logging.Handler):
        def emit(self, rec):
            m = re.search(r"audience_crawl_end .*run=(\d+)", rec.getMessage())
            if m:
                at[m.group(1)] = clock.t
    lg = logging.getLogger("of-relay.audience_crawl")
    lg.addHandler(when := When())
    try:
        old, new = await _run_row("ac1"), await _run_row("ac1")
        t0 = clock.now()
        await audience_crawl.record_after_send("ac1", of, old, user_lists=["fans"], sent_at=t0)        # until t0+100
        await audience_crawl.record_after_send("ac1", of, new, user_lists=["fans"], sent_at=t0 + 300)  # until t0+400
        await audience_crawl.drain()
    finally:
        lg.removeHandler(when)
    assert len(of.calls) == 10 and clock.t == t0 + 200, (len(of.calls), clock.t - t0)
    assert at == {str(old): t0 + 100, str(new): t0 + 200}, {k: v - t0 for k, v in at.items()}
    assert (await _recorded(old), _line(lines, old)["outcome"]) == (None, "deadline")
    assert await _recorded(new) == list(range(1, 501))
    lo, ln = _line(lines, old), _line(lines, new)
    assert (lo["pages"], ln["pages"]) == ("5", "6"), (lo, ln)     # the round's 10 roster calls + the mass feed


async def case_deadline_of_request_not_reading():
    clock, lines = _setup(AUDIENCE_CRAWL_DEADLINE_S=100)
    of = FakeOF(clock, following=range(500, 510), lists={77: [5, 6]})
    of.script[(("list", 77), 0)] = [TOO_MANY(429)] * 3              # A's list: waits 30, 60, 120 s
    at: dict[str, float] = {}

    class When(logging.Handler):
        def emit(self, rec):
            m = re.search(r"audience_crawl_end .*run=(\d+)", rec.getMessage())
            if m:
                at[m.group(1)] = clock.t
    lg = logging.getLogger("of-relay.audience_crawl")
    lg.addHandler(when := When())
    try:
        a, b = await _run_row("ac1"), await _run_row("ac1")
        t0 = clock.now()
        await audience_crawl.record_after_send("ac1", of, a, user_lists=["77"], sent_at=t0 + 200)       # until t0+300
        await audience_crawl.record_after_send("ac1", of, b, user_lists=["following"], sent_at=t0)      # until t0+100
        await audience_crawl.drain()
    finally:
        lg.removeHandler(when)
    assert clock.waits == [30.0, 60.0, 120.0], clock.waits
    assert (await _recorded(b), _line(lines, b)["outcome"]) == (None, "deadline")
    assert at[str(b)] <= t0 + 100, at[str(b)] - t0                  # logged by its deadline, not at t0+210
    assert of.offsets("following") == [], of.calls                  # no read for B after its deadline
    assert (await _recorded(a), _line(lines, a)["outcome"]) == ([5, 6], "recorded")


async def case_bad_request_fails_alone():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 101), lists={77: [5]})
    a, b, c = await _send_many(of, clock, {}, {"excluded_user_lists": ["VIP fans"]},
                               {"excluded_user_lists": [77]})
    await audience_crawl.drain()
    assert of.offsets() == [0, 50], of.offsets()                    # one roster read for A and C
    assert [await _recorded(r) for r in (a, b, c)] == [list(range(1, 101)), None, [x for x in range(1, 101) if x != 5]]
    assert [_line(lines, r)["outcome"] for r in (a, b, c)] == ["recorded", "unknown_list", "recorded"]
    assert _line(lines, a)["coalesced"] == "1", _line(lines, a)
    # …and a value only the set algebra trips on fails its own request only.
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 101))
    a, b, c = await _send_many(of, clock, {}, {"excluded_users": ["not-an-id"]}, {"excluded_users": [9]})
    await audience_crawl.drain()
    assert of.offsets() == [0, 50], of.offsets()
    assert [await _recorded(r) for r in (a, b, c)] == [list(range(1, 101)), None, [x for x in range(1, 101) if x != 9]]
    assert [_line(lines, r)["outcome"] for r in (a, b, c)] == ["recorded", "error", "recorded"]


async def case_page_bound_counts_calls():
    clock, lines = _setup()
    of = FakeOF(clock, lists={77: range(1, 301)})                    # 3 bare pages of 100, then OF's empty one
    of.script[(("list", 77), 100)] = [TOO_MANY(429), TOO_MANY(429)]
    run = await _send(of, clock, user_lists=["77"])
    await audience_crawl.drain()
    calls = len(of.calls)
    ln = _line(lines, run)
    resumes, failed = int(ln["resumes"]), int(ln["failed"])
    bound = (math.ceil(300 / 100) + 1) + resumes + failed            # the spec's per-round call bound
    assert (calls, resumes, failed, bound) == (8, 2, 2, 8), (of.offsets(("list", 77)), ln)
    assert int(ln["pages"]) + failed == calls, ln
    assert await _recorded(run) == list(range(1, 301))
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 151))                           # the 3-page roster (hasMore: no end page)
    of.script[("fans", 50)] = [TOO_MANY(429), TOO_MANY(429)]
    run = await _send(of, clock)
    await audience_crawl.drain()
    ln = _line(lines, run)
    assert len(of.calls) == 7 <= (3 + 1) + int(ln["resumes"]) + int(ln["failed"]), (of.offsets(), ln)


async def case_repeated_pages_fail_closed():
    # Nonempty repeats are incomplete, even if the repeated envelope claims EOF.
    for shape in ("more", "terminal", "bare"):
        clock, lines = _setup()

        class Repeated(FakeOF):
            def _get(self, src, offset, limit, bare=False):
                response = super()._get(src, 0, limit, bare=bare)
                if src == ("list", 77) and shape != "bare":
                    return {"list": response, "hasMore": shape == "more" or offset == 0}
                return response

        of = Repeated(clock, fans=[1, 2, 3], lists={77: [1, 2]})
        inc, exc = await _send_many(of, clock, {"user_lists": ["77"]}, {"excluded_user_lists": [77]})
        await audience_crawl.drain()
        assert [await _recorded(r) for r in (inc, exc)] == [None, None], shape
        assert [_line(lines, r)["outcome"] for r in (inc, exc)] == ["truncated", "truncated"], shape
        assert len(of.offsets(("list", 77))) == 2, of.calls


async def case_list_echo_complete_by_count():
    # OF echoes a list's page past its end (AE 2026-11-11): complete iff the ids number its usersCount.
    for count, want in ((2, "recorded"), (3, "truncated"), (None, "truncated")):
        clock, lines = _setup()

        class Echo(FakeOF):
            def _get(self, src, offset, limit, bare=False):
                return super()._get(src, 0 if src == ("list", 77) else offset, limit, bare=bare)

        of = Echo(clock, fans=[1, 2, 3], lists={77: [1, 2]})
        if count is not None:
            of.list_counts[77] = count
        run = await _send(of, clock, excluded_user_lists=[77])
        await audience_crawl.drain()
        ln = _line(lines, run)
        assert ln["outcome"] == want, (count, ln)
        assert lines.repeats == ["ok" if want == "recorded" else "truncated"], lines.repeats
        assert await _recorded(run) == ([3] if want == "recorded" else None), count
        # the journal holds the offset OF answered (0, echoed), not the asked one (2)
        assert of.offsets(("list", 77)) == [0, 0] and of.offsets(("count", 77)) == [0], of.calls
        assert int(ln["pages"]) + int(ln["failed"]) == len(of.calls) + len(of.feeds), (ln, of.calls)   # sum to calls


async def case_list_count_at_deadline():
    # The count GET's pacer turn comes past the only needer's deadline: `deadline`, no crash, no
    # `error` for another request of the round; a count GET that departs in time but answers past
    # the deadline: `deadline` too (never recorded late); a count GET that fails: `truncated`, in `failed`.
    for mode in ("turn", "late", "fail"):
        fail = mode == "fail"
        clock, lines = _setup(AUDIENCE_CRAWL_DEADLINE_S=10)

        class Echo(FakeOF):
            def _get(self, src, offset, limit, bare=False):
                return super()._get(src, 0 if src == ("list", 77) else offset, limit, bare=bare)

            def get_list(self, list_id):
                if fail:
                    raise RuntimeError("502")
                if mode == "turn":
                    clock.t += 20                    # its pacer turn: past the deadline
                    return super().get_list(list_id)
                r = super().get_list(list_id)
                clock.t += 20                        # departed in time, answered past the deadline
                return r

        of = Echo(clock, fans=[1, 2, 3], lists={77: [1, 2]})
        of.list_counts[77] = 2
        a, b = await _send_many(of, clock, {"user_lists": ["77"]}, {"user_lists": ["fans"]})
        await audience_crawl.drain()
        la, lb = _line(lines, a), _line(lines, b)
        if mode == "late":
            assert of.offsets(("count", 77)) == [0], of.calls   # the count did depart
        if fail:
            assert (la["outcome"], la["failed"]) == ("truncated", "1"), la
            assert lb["outcome"] == "recorded", lb
        else:
            assert (la["outcome"], lb["outcome"]) == ("deadline", "deadline"), (la, lb)


async def case_roster_repeat_retried_once():
    # A fans page that repeats (every id seen) is re-read once at the same offset (then recorded exactly);
    # repeated twice in a row: NULL `truncated`, mid-roster and past the end alike (never recorded off a repeat).
    for repeats, want in ((1, "recorded"), (2, "truncated")):
        clock, lines = _setup()

        class Flaky(FakeOF):
            left = repeats

            def _get(self, src, offset, limit, bare=False):
                if src == "fans" and offset == 50 and self.left:
                    self.left -= 1
                    return super()._get(src, 0, limit, bare=bare)
                return super()._get(src, offset, limit, bare=bare)

        of = Flaky(clock, fans=range(1, 151))
        run = await _send(of, clock)
        await audience_crawl.drain()
        ln = _line(lines, run)
        assert ln["outcome"] == want, ln
        assert lines.repeats == ["retry", "truncated"][:repeats], lines.repeats   # the repeat line's verdict
        if want == "recorded":
            assert await _recorded(run) == list(range(1, 151)) and ln["ratio"] == "1.000"
            assert of.offsets() == [0, 0, 50, 100], of.offsets()   # journal: offset 50 answered as 0, then re-read
        else:
            assert await _recorded(run) is None and of.offsets() == [0, 0, 0], of.offsets()
            assert (ln["sent_count"], ln["ratio"], of.feeds) == ("-", "-", []), ln   # no gate, no feed read

    clock, lines = _setup()

    class EchoEnd(FakeOF):   # past the end OF serves the last page again, hasMore true
        def _get(self, src, offset, limit, bare=False):
            r = super()._get(src, min(offset, 50) if src == "fans" else offset, limit, bare=bare)
            return {**r, "hasMore": True} if src == "fans" else r

    of = EchoEnd(clock, fans=range(1, 101))
    run = await _send(of, clock)
    await audience_crawl.drain()
    ln = _line(lines, run)
    assert (ln["outcome"], await _recorded(run)) == ("truncated", None), ln
    assert of.offsets() == [0, 50, 50, 50] and lines.repeats == ["retry", "truncated"], (of.offsets(), lines.repeats)


async def case_overlap_end_before_failed_page_truncated():
    # A 429 at 150 resumes at 100; OF then ends the roster there (hasMore false, no new id): the page at
    # 150 it had promised was never read. OF's count (140) would pass the gate at 150/140 = 1.07, so
    # only this rule keeps the cut set off: NULL `truncated`, no feed read.
    clock, lines = _setup()

    class EndsAfter429(FakeOF):
        def _get(self, src, offset, limit, bare=False):
            r = super()._get(src, offset, limit, bare=bare)
            return {**r, "hasMore": False} if src == "fans" and offset == 100 and 150 in self.offsets() else r

        def _feed(self, limit):
            return [{**x, "sentCount": 140} for x in super()._feed(limit)]

    of = EndsAfter429(clock, fans=range(1, 201))
    of.script[("fans", 150)] = [TOO_MANY(429)]
    run = await _send(of, clock)
    await audience_crawl.drain()
    ln = _line(lines, run)
    assert of.offsets() == [0, 50, 100, 150, 100], of.offsets()
    assert (ln["outcome"], await _recorded(run), ln["sent_count"], of.feeds) == ("truncated", None, "-", []), ln
    assert await _outcome(run) == "truncated"

    # A list proves itself by its count: 150 ids read, a 429 at the end offset 150, OF answers the
    # overlap page (50) empty: complete iff usersCount is 150 (one count GET), else `truncated`.
    for count, want in ((150, "recorded"), (149, "truncated"), (None, "truncated")):
        clock, lines = _setup()

        class EmptyOverlap(FakeOF):
            def _get(self, src, offset, limit, bare=False):
                r = super()._get(src, offset, limit, bare=bare)
                return [] if src == ("list", 77) and offset == 50 and 150 in self.offsets(src) else r

        of = EmptyOverlap(clock, fans=range(1, 201), lists={77: range(1, 151)})
        of.script[(("list", 77), 150)] = [TOO_MANY(429)]
        if count is not None:
            of.list_counts[77] = count
        run = await _send(of, clock, excluded_user_lists=[77])
        await audience_crawl.drain()
        ln = _line(lines, run)
        assert of.offsets(("list", 77)) == [0, 100, 150, 50] and of.offsets(("count", 77)) == [0], of.calls
        assert ln["outcome"] == want, (count, ln)
        assert await _recorded(run) == (list(range(151, 201)) if want == "recorded" else None), count
        assert of.offsets() == ([0, 50, 100, 150] if want == "recorded" else []), (count, of.offsets())   # rosters after lists


async def case_terminal_response_after_deadline():
    for later in (False, True):
        clock, lines = _setup(AUDIENCE_CRAWL_DEADLINE_S=10)
        of = FakeOF(clock, fans=[1, 2], cost_s=11)
        old, new = await _run_row("ac1"), await _run_row("ac1")
        await audience_crawl.record_after_send("ac1", of, old, user_lists=["fans"], sent_at=clock.now())
        if later:
            await audience_crawl.record_after_send("ac1", of, new, user_lists=["fans"], sent_at=clock.now() + 20)
        await audience_crawl.drain()
        assert (await _recorded(old), _line(lines, old)["outcome"]) == (None, "deadline")
        assert _line(lines, old)["pages"] == "1", lines.lines
        if later:
            assert (await _recorded(new), _line(lines, new)["outcome"]) == ([1, 2], "recorded")
            assert _line(lines, new)["pages"] == "1", lines.lines          # the mass feed's
        assert len(of.calls) == 1, of.calls


async def case_dead_session_after_deadline():
    clock, lines = _setup(AUDIENCE_CRAWL_DEADLINE_S=10)
    of = FakeOF(clock, fans=[1, 2], following=[3], cost_s=11)
    of.script[("fans", 0)] = [OFErr(401)]
    old, new = await _run_row("ac1"), await _run_row("ac1")
    await audience_crawl.record_after_send("ac1", of, old, user_lists=["fans"], sent_at=clock.now())
    await audience_crawl.record_after_send("ac1", of, new, user_lists=["following"], sent_at=clock.now() + 20)
    await audience_crawl.drain()
    assert [await _recorded(r) for r in (old, new)] == [None, None]
    assert [_line(lines, r)["outcome"] for r in (old, new)] == ["deadline", "dead_session"]
    assert len(of.calls) == 1 and of.offsets("following") == [], of.calls


async def case_pacer_wait_crosses_deadline():
    # Advance at the real worker-thread pacing boundary; admission must happen after it.
    from unittest.mock import patch
    for later, error in ((False, False), (True, False), (True, True)):
        clock, lines = _setup(AUDIENCE_CRAWL_DEADLINE_S=10)
        of = FakeOF(clock, fans=[1, 2])
        if error:
            of.script[("fans", 0)] = [OFErr(500)]
        old, new = await _run_row("ac1"), await _run_row("ac1")
        t0 = clock.now()

        def release(*keys):
            clock.t = max(clock.t, t0 + 11)

        with patch.object(of_pacing, "_wait_turn", release):
            await audience_crawl.record_after_send("ac1", of, old, user_lists=["fans"], sent_at=t0)
            if later:
                await audience_crawl.record_after_send("ac1", of, new, user_lists=["fans"], sent_at=t0 + 20)
            await audience_crawl.drain()
        assert (await _recorded(old), _line(lines, old)["outcome"]) == (None, "deadline")
        assert (_line(lines, old)["pages"], _line(lines, old)["failed"]) == ("0", "0"), lines.lines
        if later:
            assert (await _recorded(new), _line(lines, new)["outcome"]) == ([1, 2], "recorded")
            assert (_line(lines, new)["pages"], _line(lines, new)["failed"]) == ("2", str(int(error))), lines.lines
        assert len(of.calls) == (1 + int(error) if later else 0), of.calls


async def case_pages_paced_in_walk():
    clock, lines = _setup()
    of_pacing.PAGE_GAP_S = 0.05
    of = FakeOF(clock, fans=range(1, 201), following=range(300, 351))
    run = await _send(of, clock, user_lists=["fans", "following"])
    await audience_crawl.drain()
    of_pacing.PAGE_GAP_S = _REAL_GAP
    assert {c[5] for c in of.calls} == {("audience_crawl", False)}, {c[5] for c in of.calls}
    ts = [c[1] for c in of.calls]
    gaps = [y - x for x, y in zip(ts, ts[1:])]
    assert len(ts) == 6 and min(gaps) >= 0.04, gaps
    assert await _recorded(run) == list(range(1, 201)) + list(range(300, 351))


async def case_legacy_mode_identical():
    import automation_executor as ax
    import automations.send_mass_message  # noqa: F401 — registers
    from audiences import resolve_recipients_blocking
    from automation_executor import enqueue_job, run_once
    clock, lines = _setup(AUDIENCE_CRAWL_MODE="legacy")

    class Legacy(FakeOF):
        def send_mass_message(self, text, **kw):
            return {"id": 880001, "createdAt": "2026-06-04T10:00:00+00:00"}

    def fake():
        f = Legacy(clock, fans=range(1, 121), following=range(500, 530))
        f.script[("fans", 50)] = [TOO_MANY(429)]   # today: of_pacing is not around it, so the crawl fails
        return f
    today = fake()
    assert resolve_recipients_blocking(today, user_lists=["fans", "following"]) is None
    sent = fake()
    ax._make_client = lambda account_id: sent  # type: ignore[attr-defined]
    aid = "ac_legacy"
    async with get_session() as s:
        s.add(Account(id=aid))
    await enqueue_job(aid, "send_mass_message", payload={
        "text": "legacy", "user_lists": ["fans", "following"],
        "exclude_replied_hours": 0, "exclude_inbound_hours": 0})
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res
    assert not audience_crawl._crawlers, "legacy never hands off"
    assert [c[2:5] for c in sent.calls] == [c[2:5] for c in today.calls], (sent.calls, today.calls)
    assert {c[5] for c in sent.calls} == {None}, "legacy: unpaced, outside any walk"
    assert lines.lines == [], lines.lines
    async with get_session() as s:
        from sqlalchemy import select
        mr = (await s.execute(select(MassRun).where(MassRun.account_id == aid))).scalars().one()
    assert (mr.recipients_json, mr.crawl_outcome) == (None, None)
    # …and a readable roster records inline, before run_once returns.
    ok = Legacy(clock, fans=range(1, 121))
    ax._make_client = lambda account_id: ok  # type: ignore[attr-defined]
    aid = "ac_legacy_ok"   # another Creator: no 11 s write gap behind the first send
    async with get_session() as s:
        s.add(Account(id=aid))
    await enqueue_job(aid, "send_mass_message", payload={
        "text": "legacy ok", "user_lists": ["fans"], "exclude_replied_hours": 0, "exclude_inbound_hours": 0})
    await run_once(aid, "send_mass_message")
    async with get_session() as s:
        mr = (await s.execute(select(MassRun).where(MassRun.account_id == aid))).scalars().one()
    assert json.loads(mr.recipients_json) == list(range(1, 121))
    assert mr.crawl_outcome is None, "legacy: no crawl verdict, no gate"


async def case_drain_timeout_names_dropped_runs():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 101))
    of.script[("fans", 50)] = [TOO_MANY(429)]

    async def stuck(s):           # a 429 wait that outlives drain's bound
        await asyncio.sleep(3600)
    audience_crawl._sleep = stuck
    r1 = await _send(of, clock)
    r2 = await _send(FakeOF(clock, fans=range(1, 51)), clock)
    await audience_crawl.drain(timeout_s=0.05)
    assert [await _recorded(r) for r in (r1, r2)] == [None, None]
    assert lines.lines == [], lines.lines
    assert lines.cancelled == [f"audience_crawl_cancelled account=ac1 runs={r1},{r2} — those sends stay unrecorded"], \
        lines.cancelled
    assert not audience_crawl._queues["ac1"] and not audience_crawl._crawlers
    # …and a crawler cancelled before its first step (drain bound already spent) names its runs too.
    clock, lines = _setup()
    r3 = await _send(FakeOF(clock, fans=range(1, 51)), clock)
    await audience_crawl.drain(timeout_s=0)
    assert await _recorded(r3) is None and lines.lines == [], lines.lines
    assert lines.cancelled == [f"audience_crawl_cancelled account=ac1 runs={r3} — those sends stay unrecorded"], \
        lines.cancelled
    assert not audience_crawl._queues["ac1"]
    # …and a run finished earlier in the cancelled round (stamped) is not named.
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 51), lists={77: [5]})
    of.script[("fans", 0)] = [TOO_MANY(429)]
    audience_crawl._sleep = stuck
    r4, r5 = await _send_many(of, clock, {"user_lists": ["77"]}, {"user_lists": ["fans", "77"]})
    await audience_crawl.drain(timeout_s=0.05)
    assert [await _recorded(r) for r in (r4, r5)] == [[5], None]
    assert lines.cancelled == [f"audience_crawl_cancelled account=ac1 runs={r5} — those sends stay unrecorded"], \
        lines.cancelled


async def case_crawler_in_fresh_context():
    clock, lines = _setup()
    a = FakeOF(clock, fans=range(1, 101), following=range(200, 251))
    PROBE.set("first sender")
    with of_call_counter.caller("auto:send_mass_message"):
        r1 = await _send(a, clock)
        r2 = await _send(a, clock, user_lists=["following"])   # served by the crawler the first send started
    await audience_crawl.drain()
    assert a.ctx and {c[2] for c in a.calls} == {"fans", "following"}, a.calls
    assert set(a.ctx) == {(None, "walk:audience_crawl")}, a.ctx
    assert [await _recorded(r) for r in (r1, r2)] == [list(range(1, 101)), list(range(200, 251))]


# ── recover_at_boot: the sends a Relay restart cut off ──────────────────────────────────
async def case_recover_at_boot_picks_cut_off_sends():
    clock, lines = _setup()
    fans = range(1, 121)                      # 3 pages of 50
    cases = {
        "rb_cut": dict(age_s=60),
        "rb_past": dict(age_s=901),
        "rb_online": dict(age_s=60, audience={**AUD, "online": True}),
        "rb_filters": dict(age_s=60, audience={**AUD, "filters": True}),
        "rb_old_shape": dict(age_s=60, audience={k: v for k, v in AUD.items() if k not in ("online", "filters")}),
        "rb_stamped": dict(age_s=60, recipients=[7]),
        "rb_scheduled": dict(age_s=60, queue_id=None),
        "rb_running": dict(age_s=60, status="running"),
        "rb_bad_json": dict(age_s=60, raw="{nope"),
        "rb_no_lists": dict(age_s=60, audience={**AUD, "user_lists": []}),
    }
    of = {aid: FakeOF(clock, fans=fans, account_id=aid) for aid in cases}
    runs = {aid: await _boot_row(aid, **kw) for aid, kw in cases.items()}
    cut2 = await _boot_row("rb_cut", age_s=30, audience={**AUD, "excluded_users": [], "user_lists": ["fans"]})
    gone = await _boot_row("rb_no_client", age_s=60)
    await audience_crawl.recover_at_boot(_loader(of))
    await audience_crawl.drain()
    assert of["rb_cut"].offsets() == [0, 50, 100], of["rb_cut"].offsets()   # one round, from offset 0
    assert await _recorded(runs["rb_cut"]) == [x for x in fans if x != 2]
    assert await _recorded(cut2) == list(fans)
    assert _line(lines, runs["rb_cut"])["outcome"] == "recorded"
    for aid in cases:
        if aid != "rb_cut":
            assert of[aid].calls == [], (aid, of[aid].calls)
            assert not [p for p in lines.parsed() if p.get("run") == str(runs[aid])], (aid, lines.lines)
    assert await _recorded(runs["rb_stamped"]) == [7]
    assert await _recorded(gone) is None


async def case_recover_stops_at_run_deadline():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 1001), account_id="rd_one", cost_s=5.0)   # 20 pages, 5 s each
    run = await _boot_row("rd_one", age_s=880)    # 900 s deadline: 20 s left
    t0 = clock.now()
    await audience_crawl.recover_at_boot(_loader({"rd_one": of}))
    await audience_crawl.drain()
    assert await _recorded(run) is None
    assert _line(lines, run)["outcome"] == "deadline"
    assert await _outcome(run) is None, "a recovered deadline is the restart's, no verdict: not stamped"
    assert of.calls and len(of.calls) <= 5, of.calls
    assert max(c[0] for c in of.calls) < t0 + 21, "no page sent past the run's own deadline"


async def case_recover_legacy_mode_nothing():
    clock, lines = _setup(AUDIENCE_CRAWL_MODE="legacy")
    of = FakeOF(clock, fans=range(1, 51), account_id="rl_one")
    run = await _boot_row("rl_one", age_s=30)
    await audience_crawl.recover_at_boot(_loader({"rl_one": of}))
    await audience_crawl.drain()
    assert of.calls == [] and not audience_crawl._crawlers and lines.lines == [], (of.calls, lines.lines)
    assert await _recorded(run) is None


async def case_recover_unreadable_db_no_raise():
    clock, lines = _setup()
    import sys
    eng = sys.modules["db.engine"]   # `db.engine` the attribute is the AsyncEngine; the module is here

    def broken():
        raise RuntimeError("database is locked")
    real = eng.get_session
    eng.get_session = broken
    try:
        await audience_crawl.recover_at_boot(_loader({}))
    finally:
        eng.get_session = real
    assert not audience_crawl._crawlers


try:
    _harness.run()
finally:
    of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = _REAL_GAP, _REAL_JITTER
