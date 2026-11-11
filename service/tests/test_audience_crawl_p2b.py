#!/usr/bin/env python3
"""
audience_crawl, fetch diet P2b (docs/spec/phase-02-audience-crawl.md): lists read before rosters,
the completeness gate on OF's own count of the send, the skip after a failed verdict, a roster
repeated twice (NULL, no gate), and what makes an earlier send comparable. Same harness as test_audience_crawl.py
(_audience_crawl_fixtures): a fake OF client (rosters, lists and the mass feed, whose sentCount is
each send's audience over the full rows unless a case says otherwise), an injected clock, the
stamped run, its crawl_outcome and its `audience_crawl_end` line. An earlier send (`_prior`) is a
mass_runs row as a real send leaves it, with its crawl verdict.

  case_lists_read_first:            a send's exclude list is read before its roster; one that
                                    truncates (OF ignores its offset) or fails ends the send with
                                    that outcome and zero roster pages; in a round it fails only its
                                    sender.
  case_gate_below_threshold:        crawled set / this send's sentCount in the mass feed under 1.0:
                                    NULL `incomplete`, sent_count and ratio on the line, stamped;
                                    nothing written to mass_broadcast_cache.
  case_gate_at_threshold:           complete by OF's count (ratio 1.0) records, 95/100 does not; over
                                    COMPLETE_MAX (1.15) is `no_count`; OF's count is of the set it
                                    sent, so a large excluded set (the guard) neither inflates nor
                                    deflates it.
  case_no_count:                    the send missing from the feed, its sentCount 0: NULL `no_count`,
                                    never recorded; a 429 on the feed waits like any page, then counts.
  case_feed_failure_no_count:       the feed read failing after the roster was read (401, 403,
                                    PAGE_TRIES errors, transport errors, bad JSON, a 429 wait past the
                                    deadline): NULL `no_count`, never `dead_session` / `deadline`, and
                                    the next send crawls (no skip).
  case_one_feed_per_round:          two roster sends of one round: one feed GET, charged to the
                                    first; each judged on its own count; a failed GET is not retried.
  case_feed_inside_deadline:        a roster read that ends past the request's deadline: `deadline`,
                                    no feed GET leaves.
  case_ungated_audiences:           explicit ids only, or a list-only audience: no feed GET, no
                                    gate (`sent_count=-`), recorded; no skip on a list-only audience.
  case_skip_after_failed_verdict:   the newest verdict `incomplete` / `deadline` < REPROBE_S ago:
                                    NULL `skipped_incomplete`, zero reads, stamped; a skipped send is
                                    no verdict (the next skips too); another audience crawls.
  case_failed_crawl_masks_no_verdict: a newer `truncated` / `error` / `dead_session` / `no_count`
                                    crawl does not hide the `incomplete` before it.
  case_incomparable_priors:         an `online` send is passed over to an older comparable verdict;
                                    other exclude lists, explicit ids, another automation_kind:
                                    none skips.
  case_reprobe_after_knob:          the verdict older than REPROBE_S (default 24 h, or the knob):
                                    one real crawl; a newer `recorded` verdict: crawl.
  case_incomplete_then_next_skipped: end to end: a send gated `incomplete`, the next send of the
                                    Creator skipped with zero roster pages.
  case_roster_repeat_twice_null:    a roster repeating twice in a row (its tail again past the end,
                                    hasMore true): NULL `truncated` (#440), no feed read, no gate;
                                    no verdict, so the next send crawls again.
  case_malformed_prior_skipped:     a prior row that does not parse right is no prior: the older
                                    comparable verdict behind it still skips, and it never fails a
                                    later request either.
  case_recover_error_recrawled:     boot recovery re-crawls a cut-off run stamped `error`
                                    (retryable), never one stamped with any other outcome.
  case_legacy_schema_gains_crawl_outcome: a box at 0111 without mass_runs.crawl_outcome: boot's
                                    catch-up adds it (NULL: no verdict); the 0112 revision is 0111's
                                    one child, guarded and idempotent up and down.

Run: ./venv/bin/python service/tests/test_audience_crawl_p2b.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import os  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import audience_crawl  # noqa: E402
import of_pacing  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, MassBroadcastCache, MassRun  # noqa: E402

from _audience_crawl_fixtures import (  # noqa: E402 — the shared fakes and seeding
    AUD, TOO_MANY, FakeOF, OFErr, _boot_row, _line, _loader, _outcome, _recorded, _send, _send_many, _setup,
    audience_filter,
)

_REAL_GAP, _REAL_JITTER = of_pacing.PAGE_GAP_S, of_pacing.JITTER_S
for _k in [k for k in os.environ if k.startswith("AUDIENCE_CRAWL_")]:
    os.environ.pop(_k)

DAY = 86_400.0


async def _prior(aid: str, user_lists=("fans",), *, outcome=None, age_s=3600.0, kind=None,
                 raw: str | None = None, **aud) -> int:
    """An earlier immediate send of `aid`, `age_s` ago, as a real send leaves its row (`aud`:
    record_after_send's other audience keys; `raw`: the audience_filter as given) with its crawl
    verdict (no queue id: not in the mass feed)."""
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        mr = MassRun(account_id=aid, recipient_count=0, status="ok", crawl_outcome=outcome, automation_kind=kind,
                     audience_filter=raw if raw is not None else audience_filter({"user_lists": user_lists, **aud}),
                     started_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=age_s))
        s.add(mr)
        await s.flush()
        return int(mr.id)


async def _cached(aid: str) -> int:
    """mass_broadcast_cache rows of `aid` (the crawl's feed read writes none)."""
    from sqlalchemy import func, select
    async with get_session() as s:
        return (await s.execute(select(func.count()).select_from(MassBroadcastCache).where(
            MassBroadcastCache.account_id == aid))).scalar()


class TailRepeat(FakeOF):
    """A roster past its end: the last page's rows again with hasMore true where the empty page belongs. A
    shape for the repeat rule only, not one measured on AE (41182778's one repeat, ~offset 2450, was mid-roster)."""

    def _get(self, src, offset, limit, bare=False):
        if src in ("fans", "following"):
            n = len(self.rows[src])
            r = super()._get(src, max(0, n - limit) if offset >= n else offset, limit, bare)
            return {**r, "hasMore": True}
        return super()._get(src, offset, limit, bare)


class OffsetIgnored(FakeOF):
    """A custom list whose GET ignores the offset (the list repeat that stays `truncated`)."""

    def _get(self, src, offset, limit, bare=False):
        return super()._get(src, 0 if src == ("list", 77) else offset, limit, bare)


async def case_lists_read_first():
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 101), lists={77: [3, 4]})
    run = await _send(of, clock, excluded_user_lists=[77])
    await audience_crawl.drain()
    assert [c[2] for c in of.calls] == [("list", 77)] * 2 + ["fans"] * 2, of.calls   # list, then roster
    assert await _recorded(run) == [x for x in range(1, 101) if x not in (3, 4)]
    # …an exclude list that truncates (OF ignores its offset): `truncated`, zero roster pages.
    clock, lines = _setup()
    of = OffsetIgnored(clock, fans=range(1, 101), lists={77: [3, 4]})
    run = await _send(of, clock, excluded_user_lists=[77])
    await audience_crawl.drain()
    assert of.offsets() == [] and len(of.offsets(("list", 77))) == 2 and of.feeds == [], of.calls
    assert of.offsets(("count", 77)) == [0], of.calls        # #440: one usersCount GET; no count: unproven
    ln = _line(lines, run)
    assert (await _recorded(run), ln["outcome"], ln["pages"], ln["ratio"]) == (None, "truncated", "3", "-"), ln
    assert await _outcome(run) == "truncated"
    # …one that fails (PAGE_TRIES errors): `error`, zero roster pages.
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 101), lists={77: [3, 4]})
    of.script[(("list", 77), 0)] = [OFErr(500)] * 3
    run = await _send(of, clock, excluded_user_lists=[77])
    await audience_crawl.drain()
    assert of.offsets() == [] and len(of.offsets(("list", 77))) == 3, of.calls
    assert (await _recorded(run), _line(lines, run)["outcome"]) == (None, "error")
    # …and in a round, the broken list fails only its sender; the other still reads the roster once.
    clock, lines = _setup()
    of = OffsetIgnored(clock, fans=range(1, 101), lists={77: [3, 4]})
    bad, good = await _send_many(of, clock, {"excluded_user_lists": [77]}, {})
    await audience_crawl.drain()
    srcs = [c[2] for c in of.calls]
    assert srcs == [("list", 77)] * 2 + [("count", 77)] + ["fans"] * 2, srcs
    assert [_line(lines, r)["outcome"] for r in (bad, good)] == ["truncated", "recorded"]
    assert _line(lines, bad)["pages"] == "3" and _line(lines, good)["pages"] == "3", lines.lines   # + count / feed


async def case_gate_below_threshold():
    clock, lines = _setup()
    aid = "ac_gate_low"
    of = FakeOF(clock, fans=range(1, 95), account_id=aid)     # 94 read / OF's 100
    run = await _send(of, clock, aid=aid, count=100)
    await audience_crawl.drain()
    ln = _line(lines, run)
    assert (await _recorded(run), ln["outcome"], ln["recipients"], ln["sent_count"], ln["ratio"]) == \
        (None, "incomplete", "-", "100", "0.940"), ln
    assert await _outcome(run) == "incomplete"
    assert ln["pages"] == "3" and len(of.feeds) == 1, (ln, of.feeds)   # 2 roster pages + the feed: a verdict
    assert ln["count_delay_s"] == "0.0", ln
    assert await _cached(aid) == 0, "the feed's items are not written through (N2)"


async def case_gate_at_threshold():
    clock, lines = _setup()
    aid = "ac_gate_at"
    of = FakeOF(clock, fans=range(1, 101), account_id=aid)    # 100 / 100: complete by OF's count
    run = await _send(of, clock, aid=aid, count=100)
    await audience_crawl.drain()
    ln = _line(lines, run)
    assert (ln["outcome"], ln["recipients"], ln["sent_count"], ln["ratio"]) == ("recorded", "100", "100", "1.000"), ln
    assert len(await _recorded(run)) == 100 and await _outcome(run) == "recorded"
    # …95 / 100 is 5 % short: `incomplete` (B1); 116 / 100 is past COMPLETE_MAX: `no_count`, its ratio logged.
    for n, want in ((95, ("incomplete", "100", "0.950")), (116, ("no_count", "100", "1.160"))):
        clock, lines = _setup()
        aid = f"ac_gate_{n}"
        of = FakeOF(clock, fans=range(1, n + 1), account_id=aid)
        run = await _send(of, clock, aid=aid, count=100)
        await audience_crawl.drain()
        ln = _line(lines, run)
        assert (ln["outcome"], ln["sent_count"], ln["ratio"], await _recorded(run)) == (*want, None), ln
        assert await _outcome(run) == want[0]
    # …OF's count is of the set it sent: 30 excluded of a 200-fan roster (and 5 no fan) read 170 / 170.
    clock, lines = _setup()
    aid = "ac_gate_guard"
    of = FakeOF(clock, fans=range(1, 201), account_id=aid)
    run = await _send(of, clock, aid=aid, excluded_users=[*range(171, 201), *range(9001, 9006)])
    await audience_crawl.drain()
    ln = _line(lines, run)
    assert (ln["outcome"], ln["sent_count"], ln["ratio"], len(await _recorded(run))) == ("recorded", "170", "1.000", 170), ln


async def case_no_count():
    for name, kw, sent in (("unlisted", {"listed": False}, "-"), ("zero", {"count": 0}, "0")):
        clock, lines = _setup()
        aid = f"ac_nocount_{name}"
        of = FakeOF(clock, fans=range(1, 51), account_id=aid)
        run = await _send(of, clock, aid=aid, **kw)
        await audience_crawl.drain()
        ln = _line(lines, run)
        assert (await _recorded(run), ln["outcome"], ln["recipients"], ln["sent_count"], ln["ratio"]) == \
            (None, "no_count", "-", sent, "-"), (name, ln)
        assert await _outcome(run) == "no_count" and of.offsets() == [0] and len(of.feeds) == 1, (name, of.calls)
    # …a 429 on the feed waits (30 s) like any page, then counts.
    clock, lines = _setup()
    of = FakeOF(clock, fans=range(1, 51), account_id="ac_nocount_429")
    of.script[("feed", 0)] = [TOO_MANY(429)]
    run = await _send(of, clock, aid="ac_nocount_429")
    await audience_crawl.drain()
    ln = _line(lines, run)
    assert (ln["outcome"], ln["sent_count"], ln["ratio"], ln["count_delay_s"], clock.waits) == \
        ("recorded", "50", "1.000", "30.0", [30.0]), ln


async def case_feed_failure_no_count():
    import json
    bad_json = json.JSONDecodeError("Expecting value", "<html>", 0)
    for name, script, env, feeds in (
            ("401", [OFErr(401)], {}, 1), ("403", [OFErr(403)], {}, 1),
            ("errors", [OFErr(500)] * 3, {}, 3), ("transport", [ConnectionError("reset")] * 3, {}, 3),
            ("bad json", [bad_json] * 3, {}, 3),
            ("429 past the deadline", [OFErr(429, headers={"Retry-After": "200"})], {"AUDIENCE_CRAWL_DEADLINE_S": 100}, 1)):
        clock, lines = _setup(**env)
        aid = f"ac_feedfail_{name.replace(' ', '_')}"
        of = FakeOF(clock, fans=range(1, 51), account_id=aid)
        of.script[("feed", 0)] = script
        run = await _send(of, clock, aid=aid)
        await audience_crawl.drain()
        ln = _line(lines, run)
        assert (await _recorded(run), ln["outcome"], ln["sent_count"], ln["ratio"]) == (None, "no_count", "-", "-"), \
            (name, ln)
        assert await _outcome(run) == "no_count" and len(of.feeds) == feeds and clock.waits == [1.0, 2.0][:feeds - 1], \
            (name, of.feeds, clock.waits)   # 429: no wait starts past the deadline
        nxt = await _send(of, clock, aid=aid)                    # no verdict: the next send crawls and counts
        await audience_crawl.drain()
        assert of.offsets() == [0, 0] and _line(lines, nxt)["outcome"] == "recorded", (name, of.calls, lines.lines)


async def case_one_feed_per_round():
    clock, lines = _setup()
    aid = "ac_feed_round"
    of = FakeOF(clock, fans=range(1, 97), account_id=aid)
    a, b = await _send_many(of, clock, {}, {}, aid=aid)
    of.counts.update({a: 96, b: 200})
    await audience_crawl.drain()
    assert of.offsets() == [0, 50] and len(of.feeds) == 1, (of.calls, of.feeds)
    got = [(_line(lines, r)["outcome"], _line(lines, r)["ratio"], _line(lines, r)["pages"]) for r in (a, b)]
    assert got == [("recorded", "1.000", "3"), ("incomplete", "0.480", "0")], got
    # …a failed feed GET is the round's one try: no retry for the next roster reader.
    clock, lines = _setup()
    aid = "ac_feed_round_err"
    of = FakeOF(clock, fans=range(1, 51), account_id=aid)
    of.script[("feed", 0)] = [OFErr(500)] * 3
    a, b = await _send_many(of, clock, {}, {}, aid=aid)
    await audience_crawl.drain()
    assert len(of.feeds) == 3, of.feeds
    assert [_line(lines, r)["outcome"] for r in (a, b)] == ["no_count", "no_count"], lines.lines


async def case_feed_inside_deadline():
    clock, lines = _setup(AUDIENCE_CRAWL_DEADLINE_S=100)
    of = FakeOF(clock, fans=range(1, 101), cost_s=60.0)          # the roster's 2nd page ends at t0 + 120
    run = await _send(of, clock)
    await audience_crawl.drain()
    assert of.offsets() == [0, 50] and of.feeds == [], (of.calls, of.feeds)
    assert (await _recorded(run), _line(lines, run)["outcome"]) == (None, "deadline"), lines.lines


async def case_ungated_audiences():
    clock, lines = _setup()
    aid = "ac_ungated"
    await _prior(aid, ["77"], outcome="incomplete")
    of = FakeOF(clock, lists={77: [5, 6]}, account_id=aid)
    run = await _send(of, clock, aid=aid, user_lists=["77"])
    ids = await _send(of, clock, aid=aid, user_lists=[], included_users=[7, 8])
    await audience_crawl.drain()
    for r, want in ((run, [5, 6]), (ids, [7, 8])):
        ln = _line(lines, r)
        assert (ln["outcome"], ln["sent_count"], ln["ratio"], await _recorded(r)) == ("recorded", "-", "-", want), ln
    assert of.offsets(("list", 77)) == [0, 2] and of.feeds == [], (of.calls, of.feeds)


async def case_skip_after_failed_verdict():
    for last in ("incomplete", "deadline"):
        clock, lines = _setup()
        aid = f"ac_skip_{last}"
        await _prior(aid, outcome=last, age_s=3600)
        await _prior(aid, outcome="skipped_incomplete", age_s=60)              # no verdict: looked past
        of = FakeOF(clock, fans=range(1, 51), following=range(100, 111), account_id=aid)
        run = await _send(of, clock, aid=aid)
        other = await _send(of, clock, aid=aid, user_lists=["following"])     # its own audience: crawls
        await audience_crawl.drain()
        assert of.offsets() == [] and of.offsets("following") == [0], (last, of.calls)
        ln = _line(lines, run)
        assert (await _recorded(run), ln["outcome"], ln["pages"], ln["ratio"]) == \
            (None, "skipped_incomplete", "0", "-"), (last, ln)
        assert await _outcome(run) == "skipped_incomplete"
        assert (await _recorded(other), _line(lines, other)["outcome"]) == (list(range(100, 111)), "recorded")
        run2 = await _send(of, clock, aid=aid)                                  # still the same verdict
        await audience_crawl.drain()
        assert of.offsets() == [] and _line(lines, run2)["outcome"] == "skipped_incomplete", last


async def case_failed_crawl_masks_no_verdict():
    clock, lines = _setup()
    aid = "ac_mask"
    await _prior(aid, outcome="incomplete", age_s=7200)
    for failed in ("truncated", "error", "dead_session", "no_count"):         # newer, but no verdict
        await _prior(aid, outcome=failed, age_s=3600)
    of = FakeOF(clock, fans=range(1, 51), account_id=aid)
    run = await _send(of, clock, aid=aid)
    await audience_crawl.drain()
    assert of.offsets() == [] and _line(lines, run)["outcome"] == "skipped_incomplete", (of.calls, lines.lines)


async def case_incomparable_priors():
    clock, lines = _setup()
    aid = "ac_incomparable"
    await _prior(aid, outcome="incomplete", age_s=7200)                    # comparable
    await _prior(aid, outcome="recorded", age_s=3600, online_only=True)   # online (mass_queue_api: ["fans"]): passed over
    of = FakeOF(clock, fans=range(1, 97), account_id=aid)
    run = await _send(of, clock, aid=aid)
    await audience_crawl.drain()
    assert of.offsets() == [] and _line(lines, run)["outcome"] == "skipped_incomplete", (of.calls, lines.lines)
    # …and alone, none of these skips.
    for name, prior in (("online", {"online_only": True}), ("filters", {"filters": {"x": 1}}),
                        ("other excludes", {"excluded_user_lists": [88]}), ("explicit ids", {"included_users": [7]}),
                        ("another kind", {"kind": "mass_premade"})):
        clock, lines = _setup()
        aid = f"ac_incomparable_{name.replace(' ', '_')}"
        await _prior(aid, outcome="incomplete", **{"excluded_user_lists": [77], **prior})
        of = FakeOF(clock, fans=range(1, 11), lists={77: [], 88: []}, account_id=aid)
        run = await _send(of, clock, aid=aid, excluded_user_lists=[77])
        await audience_crawl.drain()
        ln = _line(lines, run)
        assert (ln["outcome"], ln["sent_count"], ln["ratio"], await _recorded(run)) == \
            ("recorded", "10", "1.000", list(range(1, 11))), (name, ln)


async def case_reprobe_after_knob():
    for env, age_s in (({}, DAY + 60), ({"AUDIENCE_CRAWL_REPROBE_S": 600}, 3600)):
        clock, lines = _setup(**env)
        aid = f"ac_reprobe_{int(age_s)}"
        await _prior(aid, outcome="incomplete", age_s=age_s)
        of = FakeOF(clock, fans=range(1, 51), account_id=aid)
        run = await _send(of, clock, aid=aid)
        await audience_crawl.drain()
        assert of.offsets() == [0], (env, of.calls)
        assert (await _recorded(run), _line(lines, run)["outcome"]) == (list(range(1, 51)), "recorded"), env
        assert await _outcome(run) == "recorded"
    # …a newer `recorded` verdict after the `incomplete` one: crawl.
    clock, lines = _setup()
    aid = "ac_reprobe_newer"
    await _prior(aid, outcome="incomplete", age_s=7200)
    await _prior(aid, outcome="recorded", age_s=3600)
    of = FakeOF(clock, fans=range(1, 51), account_id=aid)
    run = await _send(of, clock, aid=aid)
    await audience_crawl.drain()
    assert of.offsets() == [0] and _line(lines, run)["outcome"] == "recorded", of.calls


async def case_incomplete_then_next_skipped():
    clock, lines = _setup()
    aid = "ac_e2e"
    of = FakeOF(clock, fans=range(1, 101), account_id=aid)        # 100 / 1000
    first = await _send(of, clock, aid=aid, count=1000)
    await audience_crawl.drain()
    assert of.offsets() == [0, 50], of.calls
    assert (_line(lines, first)["outcome"], await _recorded(first)) == ("incomplete", None)
    second = await _send(of, clock, aid=aid)
    await audience_crawl.drain()
    assert of.offsets() == [0, 50] and len(of.feeds) == 1, "the next send reads zero roster pages, no feed"
    ln = _line(lines, second)
    assert (ln["outcome"], ln["pages"], await _recorded(second)) == ("skipped_incomplete", "0", None), ln


async def case_roster_repeat_twice_null():
    # P2b gates nothing off a repeat: a roster that repeats twice in a row (past its end here) is NULL `truncated`
    # (#440), no feed read, no gate; never a verdict, so the next send crawls again.
    clock, lines = _setup()
    of = TailRepeat(clock, fans=range(1, 121), account_id="ac_tail")   # 3 pages, then the tail again
    run = await _send(of, clock, aid="ac_tail")
    await audience_crawl.drain()
    assert of.offsets() == [0, 50, 100, 70, 70] and of.feeds == [], of.offsets()   # re-read once, then cut
    ln = _line(lines, run)
    assert (ln["outcome"], ln["pages"], ln["sent_count"], ln["ratio"]) == ("truncated", "5", "-", "-"), ln
    assert await _recorded(run) is None and await _outcome(run) == "truncated"
    nxt = await _send(of, clock, aid="ac_tail")
    await audience_crawl.drain()
    assert _line(lines, nxt)["outcome"] == "truncated" and len(of.offsets()) == 10, of.offsets()


async def case_malformed_prior_skipped():
    clock, lines = _setup()
    aid = "ac_malformed"
    await _prior(aid, outcome="incomplete", age_s=7200)           # behind it: still skips
    await _prior(aid, outcome="incomplete",                      # parses, but not a list: no prior
                 raw='{"user_lists": 5, "online": false, "filters": false}')
    of = FakeOF(clock, fans=range(1, 97), account_id=aid)
    first = await _send(of, clock, aid=aid)
    await audience_crawl.drain()
    second = await _send(of, clock, aid=aid)                     # still in its lookback: poisons nothing
    await audience_crawl.drain()
    assert of.offsets() == [], of.calls
    assert [_line(lines, r)["outcome"] for r in (first, second)] == ["skipped_incomplete"] * 2, lines.lines


async def case_recover_error_recrawled():
    clock, lines = _setup()
    fans = range(1, 51)
    outcomes = {"rb2_error": "error", "rb2_incomplete": "incomplete", "rb2_skipped": "skipped_incomplete",
                "rb2_truncated": "truncated", "rb2_dead": "dead_session", "rb2_deadline": "deadline",
                "rb2_nocount": "no_count"}
    of = {aid: FakeOF(clock, fans=fans, account_id=aid) for aid in outcomes}
    runs = {aid: await _boot_row(aid, age_s=60, outcome=o) for aid, o in outcomes.items()}
    await audience_crawl.recover_at_boot(_loader(of))
    await audience_crawl.drain()
    assert of["rb2_error"].offsets() == [0], of["rb2_error"].calls
    assert await _recorded(runs["rb2_error"]) == [x for x in fans if x not in AUD["excluded_users"]]
    assert await _outcome(runs["rb2_error"]) == "recorded"
    for aid in outcomes:
        if aid != "rb2_error":
            assert of[aid].calls == [] and await _recorded(runs[aid]) is None, (aid, of[aid].calls)


def case_legacy_schema_gains_crawl_outcome():
    import asyncio
    import importlib
    import importlib.util
    import sqlite3
    import tempfile
    from pathlib import Path

    import sqlalchemy as sa
    import sqlalchemy.dialects.sqlite  # noqa: F401
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.schema import CreateTable

    db = Path(tempfile.gettempdir()) / f"mass_run_crawl_outcome_{os.getpid()}.db"
    db.unlink(missing_ok=True)
    acct_ddl, ddl = (str(CreateTable(m.__table__).compile(dialect=sa.dialects.sqlite.dialect()))
                     for m in (Account, MassRun))
    con = sqlite3.connect(db)
    con.executescript(f"""
        CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);
        INSERT INTO alembic_version VALUES ('0111_tx_scan_full_walk_failures');
        {acct_ddl};
        {ddl};
        ALTER TABLE mass_runs DROP COLUMN crawl_outcome;
        INSERT INTO mass_runs (account_id, audience_filter, recipient_count, status, started_at)
            VALUES ('legacy_mr', '{{}}', 0, 'ok', '2026-11-10 00:00:00');
    """)
    con.commit()
    con.close()
    eng = sa.create_engine(f"sqlite:///{db}")
    try:
        db_engine = importlib.import_module("db.engine")
        prev = db_engine.DATABASE_URL
        try:
            db_engine.DATABASE_URL = f"sqlite+aiosqlite:///{db}"
            asyncio.run(db_engine.init_db())
        finally:
            db_engine.DATABASE_URL = prev
        with eng.connect() as c:
            assert c.exec_driver_sql("SELECT crawl_outcome FROM mass_runs").fetchall() == [(None,)]

        versions = Path(__file__).resolve().parents[1] / "db" / "migrations" / "versions"
        spec = importlib.util.spec_from_file_location("mig_0112_crawl", versions / "20261111_1200_mass_run_crawl_outcome.py")
        mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mig)
        assert (mig.revision, mig.down_revision) == ("0112_mass_run_crawl_outcome", "0111_tx_scan_full_walk_failures")
        downs = [ln for f in versions.glob("*.py") for ln in f.read_text().splitlines()
                 if ln.startswith("down_revision") and "0111_tx_scan_full_walk_failures" in ln]
        assert len(downs) == 1, f"0111 must have exactly one child: {downs}"

        def step(fn):
            with eng.begin() as conn, Operations.context(MigrationContext.configure(conn)):
                fn()

        def has() -> bool:
            return "crawl_outcome" in {c["name"] for c in sa.inspect(eng).get_columns("mass_runs")}

        step(mig.upgrade)   # boot already added it: guarded
        assert has()
        step(mig.downgrade)
        step(mig.downgrade)
        assert not has()
        step(mig.upgrade)
        step(mig.upgrade)
        assert has()
    finally:
        eng.dispose()
        db.unlink(missing_ok=True)


try:
    _harness.run()
finally:
    of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = _REAL_GAP, _REAL_JITTER
