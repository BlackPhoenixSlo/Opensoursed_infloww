#!/usr/bin/env python3
"""The App-open warm (ADR-0031, phase-01 1b, service/app_open_warm.py): an opened document load warms every
Creator the Employee can access, once: per Creator one read set (the purchases poll, then the chats window, the rail's
two money lists and the notifications count) as one background walk, per proxy one Creator at a time
APP_OPEN_WARM_GAP_S apart, proxies in parallel, leased Creators first; `creator_warmed` per Creator as its reads land.

Fakes: the OF client (client_pool.get: only its bound endpoint, `proxy_url`, is read), the feed read
(purchase_poll.run_fast_tick, behind the real poll_now and its single-flight), the server's read helper for
steps 2-4 (`app_open_warm._server`, except in case_read_set_on_the_real_routes), the registries (read through the real
transaction_ingest.live_account_ids), the reuse clock (`app_open_warm._clock`), a last ok poll (a seeded
`purchase_poll._poll_state`), events.publish (recorded).

  • case_every_creator_once: each live Creator read exactly once (feed, then steps 2-4), Caller kind
    walk:app_open_warm; dead, deactivated, watcher and no-session Creators skipped (not in the answer, no read); per
    proxy serial, starts >= GAP_S apart, leased first; the three groups start together; `creator_warmed` per Creator,
    after its reads.
  • case_reuse: a second start inside APP_OPEN_WARM_REUSE_S answers `reused` and reads nothing, also while the
    first is still running; a reused Creator whose warm ended publishes `creator_warmed` at once (one still queued
    publishes when its reads land); past the window it reads again.
  • case_reuse_decision_table: `reuse_decision` (pure): queued/reading → reused (concurrent opens: one warm); fresh
    + WS kept → reused; fresh + WS down or reconnected since → start; stale → start; failed just now → skip.
  • case_ws_kept_reuse: past REUSE_S, a Creator whose WebSocket stayed connected since its warm landed is `reused`
    (no read, `creator_warmed` at once) until FRESH_S; one whose socket is down, or reconnected after the warm,
    warms; FRESH_S is held to the roster count's TTL and the Idle tier.
  • case_recently_polled_no_read: a Creator whose last purchases poll started under PURCHASES_POLL_FAST_S ago
    gets no feed read, still steps 2-4 and its event.
  • case_refreshed_first: a Creator the route Select-refreshes is `started`, gets no feed read here, its steps 2-4
    first on its proxy one GAP_S late (the route's `note_read`: the Select refresh reads there now); the others'
    groups at once.
  • case_pace_lease_gains: a lease renewal's gains (`pace`): feed reads only, per proxy GAP_S apart, a proxy the
    selection reads on (`note_read`) waits one GAP_S, a current Creator skipped; no steps 2-4, event or memo.
  • case_one_gate_per_exit: pace and start calls on one exit share ONE queue: every read on it GAP_S apart across
    callers, a Creator already queued not queued again, a paced Creator no longer leased at its turn skipped.
  • case_overlapping_refreshed_coalesce: overlapping opens naming the same Select-refreshed Creator run one warm.
  • case_failed_warm_not_reused: a warm whose reads failed is never `reused` nor announced; a second open inside
    REUSE_S skips it (no read, absent from the answer); past the window it is tried again.
  • case_failed_poll_counts_as_attempt: a feed poll with no ok answer (error, no outcome) still counts for the
    selection floor and the warm's feed skip: a failing exit is not read again at once.
  • case_dead_after_feed_read: a Creator its feed read flags a Dead session reads nothing more and publishes nothing.
  • case_refresh_job_on_exit_gate: a Shared refresher job (`refresh`) runs on its Creator's exit GAP_S after the
    last read there, exits in parallel; no warm read, event or `pending`.
  • case_warm_absorbs_refresh: a warm takes a queued refresh's place; a refresh for a queued warm is not queued.
  • case_refresh_recheck_at_turn: the job's re-check runs at its turn; unwanted, it is dropped unread, no GAP.
  • case_refresh_deadline_frees_exit: a job hung past the 30 s deadline frees the exit for the next Creator; its walk
    is not cancelled and its late result lands; `shared_refresher_job_timeout` logged.
  • case_refresh_429_holds_the_exit: a refresh job's `hold` (a terminal 429) holds its whole exit for OF's wait: the
    next refresh or warm there starts no earlier, another exit at once; a hold under GAP keeps GAP.
  • case_refresh_dropped_at_turn_when_no_longer_wanted: the Shared refresher's own queued jobs are dropped unread at
    their turn when the Creator left `tracked`, went dead or got a Last refresh meanwhile; a still-wanted one reads.
  • case_read_set_on_the_real_routes: the real server helper and roster-counts recompute over a fake OF client:
    the four steps in order, at most 5 reads, the money lists at the rail's page size, `creator_warmed` in the house
    envelope carrying the roster count and the notifications count (an expired entry is left out); the entries are the pass-through's (`of_notifications`, `of_notifications_count`, roster-counts,
    the Fan List's page 0): read 25 s after the warm, no OF call; at 31 s the money list reads OF again.

Run:  ./venv/bin/python service/tests/test_app_open_warm.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402

import account_health  # noqa: E402
import accounts  # noqa: E402
import app_open_warm as aow  # noqa: E402
import client_pool  # noqa: E402
import events  # noqa: E402
import of_call_counter  # noqa: E402
import purchase_poll_decide as decide  # noqa: E402
import purchase_poll as pp  # noqa: E402
import transaction_ingest as ti  # noqa: E402
import view_lease  # noqa: E402
from fastapi import HTTPException  # noqa: E402

P1A, P1B, P1C, P2A, P2B, D1, DEAD, OFF, WATCH, NOSESS = (f"77{i:02d}" for i in range(10))
PROXY = {P1A: "socks5://u:pw@10.0.0.1:1080", P1B: "socks5://10.0.0.1:1080", P1C: "socks5://10.0.0.1:1080",
         P2A: "http://10.0.0.2:3128", P2B: "http://10.0.0.2:3128", D1: None}
LIVE = [P1A, P1B, P1C, P2A, P2B, D1]
ALL = LIVE + [DEAD, OFF, WATCH, NOSESS]
GAP = 0.15
READ_S = 0.03
STEP_S = 0.02
READS: list[tuple[str, float, str]] = []   # (Creator, start, Caller kind) per feed read
STEPS: list[tuple[str, float, str]] = []   # (Creator, start, Caller kind) per steps 2-4 call
PUBLISHED: list[dict] = []
CLOCK = [1000.0]
FLAG_DEAD: set[str] = set()                # Creators whose feed read flags them dead
WS_SINCE: dict[str, float] = {}            # Creator -> when its OF WebSocket connected (absent: down)


REFUSED: set[str] = set()                  # Creators whose reads the Relay refuses (bad session, 503)


async def _steps(aid):
    STEPS.append((aid, time.monotonic(), of_call_counter.caller_kind()))
    if aid in REFUSED:
        raise HTTPException(503, {"error": "bad_session"})
    await asyncio.sleep(STEP_S)


SERVER = types.SimpleNamespace(app_open_warm_reads=_steps, app_open_warm_values=lambda _aid: {})


DEAD_NOW: set[str] = set()


def _warmed_ids() -> list[str]:
    out = []
    for e in PUBLISHED:
        assert list(e) == ["creator_warmed", "__account_id"], e
        assert e["creator_warmed"]["account_id"] == e["__account_id"] and e["creator_warmed"]["at"], e
        out.append(e["__account_id"])
    return out


@contextlib.contextmanager
def _patched():
    async def _tick(aid):
        READS.append((aid, time.monotonic(), of_call_counter.caller_kind()))
        await asyncio.sleep(READ_S)
        if aid in FLAG_DEAD:
            DEAD_NOW.add(aid)
        return {"rows_inserted": 0, "rows_patched": 0, "error": None}

    async def _off():
        return {OFF}

    async def _dead():
        return {a: object() for a in {DEAD} | DEAD_NOW}

    async def _false(_aid):
        return False

    saved = [(pp, "run_fast_tick", _tick), (ti, "_is_paused", _false),
             (accounts, "list_accounts",
              lambda include_watchers=False: [{"id": a, "has_session": a != NOSESS} for a in ALL
                                              if include_watchers or a != WATCH]),
             (account_health, "deactivated_ids", _off), (account_health, "dead_session_map", _dead),
             (client_pool, "get", lambda a: types.SimpleNamespace(proxy_url=PROXY.get(a), proxy_label=None)),
             (events, "publish", PUBLISHED.append),
             (aow, "GAP_S", GAP), (aow, "_clock", lambda: CLOCK[0]), (aow, "_server", lambda: SERVER),
             (aow, "_ws_since", WS_SINCE.get)]
    old = [(m, k, getattr(m, k)) for m, k, _ in saved]
    for m, k, v in saved:
        setattr(m, k, v)
    READS.clear()
    STEPS.clear()
    PUBLISHED.clear()
    FLAG_DEAD.clear()
    DEAD_NOW.clear()
    WS_SINCE.clear()
    aow._warmed_at.clear()
    aow._failed_at.clear()
    aow._pending.clear()
    aow._exits.clear()
    view_lease._holders.clear()
    pp._poll_state.clear()
    pp._poll_inflight.clear()
    try:
        yield
    finally:
        for m, k, v in old:
            setattr(m, k, v)


async def _drain():
    while aow._tasks:
        await asyncio.gather(*list(aow._tasks))


def _starts(aid_list):
    return [t for a, t, _ in READS if a in aid_list]


async def case_every_creator_once():
    with _patched():
        got = await aow.start(("user", "u1"), ALL, leased_first={P1C, P2B})
        assert got == {a: "started" for a in LIVE}, got
        await _drain()
    read = [a for a, _, _ in READS]
    assert sorted(read) == sorted(LIVE), f"each live Creator once, none of dead/off/watcher/no-session: {read}"
    assert {k for _, _, k in READS} == {"walk:app_open_warm"}, READS
    p1 = [a for a in read if a in (P1A, P1B, P1C)]
    p2 = [a for a in read if a in (P2A, P2B)]
    assert p1 == [P1C, P1A, P1B] and p2 == [P2B, P2A], f"leased first, then the caller's order: {p1} {p2}"
    for grp in ((P1A, P1B, P1C), (P2A, P2B)):
        ts = _starts(grp)
        gaps = [b - a for a, b in zip(ts, ts[1:])]
        assert all(g >= GAP for g in gaps), f"same proxy: starts >= {GAP} s apart: {gaps}"
    firsts = [_starts(g)[0] for g in ((P1A, P1B, P1C), (P2A, P2B), (D1,))]
    assert max(firsts) - min(firsts) < GAP / 2, f"proxies in parallel: first starts {firsts}"
    assert sorted(a for a, _, _ in STEPS) == sorted(LIVE), f"steps 2-4 once per live Creator: {STEPS}"
    assert {k for _, _, k in STEPS} == {"walk:app_open_warm"}, STEPS
    feed_at = {a: t for a, t, _ in READS}
    assert all(t >= feed_at[a] + READ_S for a, t, _ in STEPS), "steps 2-4 after the Creator's feed read"
    assert sorted(_warmed_ids()) == sorted(LIVE), f"creator_warmed once per Creator: {PUBLISHED}"


async def case_refused_read_is_one_line():
    """A refused read (bad session) is a skip line, not `app_open_warm_failed` + Traceback; the rest still warm."""
    records: list[logging.LogRecord] = []
    h = logging.Handler(); h.emit = records.append
    lg = logging.getLogger("of-relay.app_open_warm"); lg.addHandler(h); old = lg.level; lg.setLevel(logging.INFO)
    REFUSED.add(P1A)
    try:
        with _patched():
            await aow.start(("user", "u1"), ALL, leased_first=set())
            await _drain()
    finally:
        REFUSED.discard(P1A); lg.removeHandler(h); lg.setLevel(old)
    msgs = [r.getMessage() for r in records]
    assert any(m.startswith("app_open_warm_skipped account=%s" % P1A) for m in msgs), msgs
    assert not any("app_open_warm_failed" in m for m in msgs) and not any(r.exc_info for r in records), msgs
    assert sorted(_warmed_ids()) == sorted(a for a in LIVE if a != P1A), PUBLISHED


async def case_reuse():
    with _patched():
        CLOCK[0] = 2000.0
        got = await aow.start(("user", "u1"), LIVE, leased_first=())
        assert set(got.values()) == {"started"}, got
        again = await aow.start(("chatter", "c1"), LIVE, leased_first=())   # the first still running
        assert again == {a: "reused" for a in LIVE}, again
        assert PUBLISHED == [], "a Creator still queued publishes when its reads land, not at the reuse"
        await _drain()
        n = len(READS)
        assert n == len(LIVE) and len(STEPS) == n, (READS, STEPS)
        assert sorted(_warmed_ids()) == sorted(LIVE), PUBLISHED
        PUBLISHED.clear()
        CLOCK[0] = 2000.0 + aow.REUSE_S - 1
        assert await aow.start(("user", "u2"), LIVE, leased_first=()) == {a: "reused" for a in LIVE}
        await _drain()
        assert len(READS) == n and len(STEPS) == n, "inside the reuse window: no read"
        assert sorted(_warmed_ids()) == sorted(LIVE), f"a reuse publishes at once: {PUBLISHED}"
        CLOCK[0] = 2000.0 + aow.REUSE_S + 1
        pp._poll_state.clear()   # forget any last ok poll, so the window alone decides
        assert await aow.start(("user", "u2"), LIVE, leased_first=()) == {a: "started" for a in LIVE}
        await _drain()
        assert len(READS) == 2 * n, READS


def case_reuse_decision_table():
    R, F = 30.0, 300.0
    rows = [  # pending, warmed_age, failed_age, ws_kept -> call
        ("queued or reading (concurrent opens)", True, None, None, False, "reused"),
        ("queued, an old failure too", True, None, 5.0, False, "reused"),
        ("inside REUSE_S, WS down", False, 10.0, None, False, "reused"),
        ("fresh + WS kept", False, 120.0, None, True, "reused"),
        ("fresh + WS down / reconnected", False, 120.0, None, False, "start"),
        ("stale, WS kept", False, F + 1, None, True, "start"),
        ("stale", False, F + 1, None, False, "start"),
        ("never warmed, WS up", False, None, None, True, "start"),
        ("failed just now, WS up", False, None, 5.0, True, "skip"),
        ("failed past REUSE_S", False, None, R + 1, True, "start"),
    ]
    for name, pending, wa, fa, kept, want in rows:
        got = aow.reuse_decision(pending=pending, warmed_age=wa, failed_age=fa, ws_kept=kept, reuse_s=R, fresh_s=F)
        assert got == want, (name, got, want)


async def case_ws_kept_reuse():
    import server  # noqa: F401 — first: accounts_admin_api is imported by server.py, never first
    import accounts_admin_api
    assert aow.FRESH_MAX_S == accounts_admin_api.ROSTER_COUNT_TTL_S, "FRESH_S never outlives the roster count's TTL"
    assert aow.REUSE_S <= aow.FRESH_S <= min(aow.FRESH_MAX_S, decide.SLOW_S), aow.FRESH_S
    with _patched():
        CLOCK[0] = 5000.0
        WS_SINCE.update({P1A: 4000.0, P1B: 4000.0})          # P1A, P1B: connected before the warm; the rest down
        assert set((await aow.start(("user", "u1"), LIVE, leased_first=())).values()) == {"started"}
        await _drain()
        n = len(READS)
        PUBLISHED.clear()
        WS_SINCE[P1B] = 5000.0 + 1                           # P1B's socket reconnected after its warm landed
        CLOCK[0] = 5000.0 + aow.REUSE_S + 1
        pp._poll_state.clear()
        got = await aow.start(("chatter", "c1"), LIVE, leased_first=())
        assert got == {a: ("reused" if a == P1A else "started") for a in LIVE}, got
        await _drain()
        assert sorted(a for a, _, _ in READS[n:]) == sorted(a for a in LIVE if a != P1A), READS[n:]
        assert P1A in _warmed_ids(), f"a reused Creator publishes at once: {PUBLISHED}"
        CLOCK[0] = 5000.0 + aow.FRESH_S + 1                  # P1A's warm now older than FRESH_S
        pp._poll_state.clear()
        assert (await aow.start(("user", "u2"), [P1A], leased_first=())) == {P1A: "started"}
        await _drain()


async def case_recently_polled_no_read():
    with _patched():
        now = time.monotonic()
        pp._poll_state[P1A] = decide.PollState(last_started_s=now - (decide.FAST_S - 5))   # inside the fast interval
        pp._poll_state[P1B] = decide.PollState(last_ok_s=now - (decide.FAST_S - 5),      # an ok answer, but
                                               last_started_s=now - (decide.FAST_S + 5))  # started older: read
        t0 = time.monotonic()
        got = await aow.start(("user", "u1"), [P1A, P1B, P1C], leased_first=())
        assert got == {P1A: "started", P1B: "started", P1C: "started"}, got
        await _drain()
    assert [a for a, _, _ in READS] == [P1B, P1C], READS
    assert [a for a, _, _ in STEPS] == [P1A, P1B, P1C], f"steps 2-4 still run for the current Creator: {STEPS}"
    assert STEPS[0][1] - t0 < GAP / 2, f"P1A first, at once (no feed read before it): {STEPS}"
    assert sorted(_warmed_ids()) == [P1A, P1B, P1C], PUBLISHED
    assert P1A in aow._warmed_at, "a current Creator counts as warmed: a second open reuses it"


async def case_refreshed_first():
    with _patched():
        t0 = time.monotonic()
        aow.note_read(P1A)                   # the route, as it spawns P1A's Select refresh
        got = await aow.start(("user", "u1"), [P1A, P1B, P2A], leased_first=(), refreshed=[P1A])
        assert got == {P1A: "started", P1B: "started", P2A: "started"}, got
        assert aow.current(P1A), "the Select-refreshed Creator counts as warmed (no second Select refresh)"
        await _drain()
        again = await aow.start(("user", "u2"), [P1A], leased_first=())
    assert again == {P1A: "reused"}, again
    assert sorted(a for a, _, _ in READS) == [P1B, P2A], f"the Select-refreshed Creator's feed is not read here: {READS}"
    steps = {a: t - t0 for a, t, _ in STEPS}
    at = {a: t - t0 for a, t, _ in READS}
    assert set(steps) == {P1A, P1B, P2A}, STEPS
    assert GAP <= steps[P1A] < at[P1B], f"its steps 2-4 first on its proxy, one GAP after the Select refresh: {steps}"
    assert at[P1B] >= steps[P1A] + STEP_S + GAP, f"then one GAP to the next Creator: {at} {steps}"
    assert at[P2A] < GAP / 2, f"another proxy's group starts at once: {at}"


async def case_pace_lease_gains():
    """A lease renewal's gains (app_open_warm.pace): feed reads only, per proxy one Creator at a time GAP_S apart,
    proxies in parallel, a proxy the selection reads on now waits one GAP_S first; a Creator polled inside
    PURCHASES_POLL_FAST_S by its turn is skipped; no steps 2-4, no event, no warm memo."""
    polled: list[tuple[str, float]] = []

    async def poll(aid):
        polled.append((aid, time.monotonic()))
        await asyncio.sleep(READ_S)

    with _patched():
        view_lease.renew(("user", "u1", "t1"), [P1A, P1B, P1C, P2A, D1], P2B)
        pp._poll_state[P1C] = decide.PollState(last_ok_s=time.monotonic(), last_started_s=time.monotonic())
        t0 = time.monotonic()
        aow.note_read(P2B)                   # the selection reads on P2's exit now
        aow.pace([P1A, P1B, P1C, P2A, D1], poll)
        await _drain()
    at = {a: t - t0 for a, t in polled}
    assert set(at) == {P1A, P1B, D1, P2A} and len(polled) == 4, f"each once, the current one skipped: {polled}"
    assert at[P1A] < GAP / 2 and at[D1] < GAP / 2, f"groups in parallel, at once: {at}"
    assert at[P1B] - at[P1A] >= GAP, f"same proxy: GAP_S apart: {at}"
    assert at[P2A] >= GAP, f"the selection reads on P2's proxy now: one GAP_S first: {at}"
    assert STEPS == [] and PUBLISHED == [] and aow._warmed_at == {} and aow._pending == set(), (STEPS, PUBLISHED)


async def case_one_gate_per_exit():
    polled: list[tuple[str, float]] = []

    async def poll(aid):
        polled.append((aid, time.monotonic()))
        await asyncio.sleep(READ_S)

    with _patched():
        view_lease.renew(("user", "u1", "t1"), [P1A, P1B, P1C, P2A, P2B], None)
        aow.pace([P1A], poll)                # two renewals' gains on one exit, a moment apart
        aow.pace([P1B], poll)
        aow.pace([P1A], poll)                # already queued: not again
        await aow.start(("user", "u1"), [P1C], leased_first=())   # an open's warm on the same exit
        aow.pace([P2B, P2A], poll)
        view_lease.renew(("user", "u1", "t1"), [P1A, P1B, P1C, P2B], None)   # P2A's lease lapses before its turn
        await _drain()
    p1 = sorted([(t, a) for a, t in polled if a in (P1A, P1B)] + [(t, a) for a, t, _ in READS if a == P1C])
    assert [a for _, a in p1] == [P1A, P1B, P1C], f"each once, in arrival order: {p1} {polled}"
    gaps = [b[0] - a[0] for a, b in zip(p1, p1[1:])]
    assert all(g >= GAP for g in gaps), f"one exit: every read GAP_S apart across callers: {gaps}"
    assert [a for a, _ in polled if a in (P2A, P2B)] == [P2B], f"no longer leased at its turn: skipped: {polled}"


async def case_overlapping_refreshed_coalesce():
    with _patched():
        got = [await aow.start(("user", f"u{i}"), [P1A], leased_first=(), refreshed=[P1A]) for i in range(3)]
        await _drain()
    assert got == [{P1A: "started"}, {P1A: "reused"}, {P1A: "reused"}], got
    assert [a for a, _, _ in STEPS] == [P1A], f"three tabs opening on one selection: one warm job: {STEPS}"
    assert READS == [], "the Select refresh reads its feed, not the warm"
    assert _warmed_ids() == [P1A], PUBLISHED


async def case_failed_warm_not_reused():
    REFUSED.add(P1A)
    try:
        with _patched():
            CLOCK[0] = 3000.0
            await aow.start(("user", "u1"), [P1A, P1B], leased_first=())
            await _drain()
            assert _warmed_ids() == [P1B], PUBLISHED
            PUBLISHED.clear()
            n = len(STEPS)
            CLOCK[0] = 3000.0 + aow.REUSE_S - 1
            again = await aow.start(("user", "u2"), [P1A, P1B], leased_first=())
            await _drain()
            assert again == {P1B: "reused"}, f"a failed warm is never reused: {again}"
            assert _warmed_ids() == [P1B], f"nothing announced for the failed one: {PUBLISHED}"
            assert len(STEPS) == n, "inside the window the failed one is not read again"
            pp._poll_state.clear()           # its feed poll counts for `current` on its own (F3): the memo alone
            assert not aow.current(P1A) and aow.current(P1B)
            CLOCK[0] = 3000.0 + aow.REUSE_S + 1
            pp._poll_state.clear()
            assert await aow.start(("user", "u3"), [P1A], leased_first=()) == {P1A: "started"}
            await _drain()
            assert [a for a, _, _ in STEPS[n:]] == [P1A], STEPS
    finally:
        REFUSED.discard(P1A)


async def case_failed_poll_counts_as_attempt():
    with _patched():
        assert not aow.just_polled(P1A)
        await pp.poll_now(P1A)               # the fake feed read answers no outcome (an error / no-session path)
        n = len(READS)
        assert n == 1, READS
        assert aow.just_polled(P1A), "a poll that started now counts for the selection floor, ok or not"
        await aow.start(("user", "u1"), [P1A], leased_first=())
        await _drain()
        assert len(READS) == n, f"the warm reads no feed a poll just tried: {READS}"


async def case_dead_after_feed_read():
    with _patched():
        FLAG_DEAD.add(P1A)
        got = await aow.start(("user", "u1"), [P1A, P1B], leased_first=())
        assert got == {P1A: "started", P1B: "started"}, got
        await _drain()
    assert [a for a, _, _ in READS] == [P1A, P1B], READS
    assert [a for a, _, _ in STEPS] == [P1B], f"a Creator flagged dead by its feed read reads nothing more: {STEPS}"
    assert _warmed_ids() == [P1B], PUBLISHED


def _refresher(log: list, hold_s: float = READ_S, landed: list | None = None):
    """A Shared refresher job's walk: records (Creator, start), reads for `hold_s`, then applies its result."""
    async def run(aid):
        log.append((aid, time.monotonic()))
        await asyncio.sleep(hold_s)
        if landed is not None:
            landed.append(aid)
    return run


async def _yes(_aid):
    return True


async def case_refresh_job_on_exit_gate():
    """A refresh job runs on its Creator's exit, APP_OPEN_WARM_GAP_S after the last read there, exits in parallel; it
    reads none of the warm's set, publishes nothing, and is not warm-pending."""
    ran: list[tuple[str, float]] = []
    with _patched():
        t0 = time.monotonic()
        await aow.start(("user", "u1"), [P1A], leased_first=())
        assert aow.refresh(P1B, _refresher(ran), wanted=_yes) is True
        assert aow.refresh(P2A, _refresher(ran), wanted=_yes) is True
        assert aow.pending(P1A) and not aow.pending(P1B) and not aow.pending(P2A), aow._pending
        await _drain()
        assert not aow.pending(P1A), "pending ends with the warm"
    at = {a: t - t0 for a, t in ran}
    assert set(at) == {P1B, P2A} and len(ran) == 2, ran
    steps_end = STEPS[0][1] - t0 + STEP_S
    assert at[P1B] >= steps_end + GAP, f"same exit: one GAP after the warm's reads ended: {at} {steps_end}"
    assert at[P2A] < GAP / 2, f"another exit: at once: {at}"
    assert [a for a, _, _ in READS] == [P1A] and [a for a, _, _ in STEPS] == [P1A], (READS, STEPS)
    assert _warmed_ids() == [P1A], PUBLISHED


async def case_warm_absorbs_refresh():
    """One entry per Creator: a warm arriving for a queued refresh takes its place (the refresh never runs); a refresh
    arriving for a queued warm is not queued; either way one warm, read once."""
    ran: list[tuple[str, float]] = []
    with _patched():
        await aow.start(("user", "u1"), [P1A], leased_first=())    # holds the exit: the rest stay queued
        assert aow.refresh(P1B, _refresher(ran), wanted=_yes) is True
        got = await aow.start(("user", "u2"), [P1B, P1C], leased_first=())
        assert got == {P1B: "started", P1C: "started"}, got
        assert aow.refresh(P1C, _refresher(ran), wanted=_yes) is False, "a queued warm absorbs the refresh"
        await _drain()
    assert ran == [], f"no refresh ran: the warms read more: {ran}"
    assert [a for a, _, _ in STEPS] == [P1A, P1B, P1C], f"each Creator one warm, in order: {STEPS}"
    assert sorted(_warmed_ids()) == [P1A, P1B, P1C], PUBLISHED


async def case_refresh_recheck_at_turn():
    """At its turn a refresh job re-checks (`wanted`, asked then, not at enqueue): unwanted, it is dropped unread and
    the exit does not wait a GAP for it."""
    ran: list[tuple[str, float]] = []
    asked: list[tuple[str, float]] = []
    gone: set[str] = set()

    async def wanted(aid):
        asked.append((aid, time.monotonic()))
        return aid not in gone

    with _patched():
        t0 = time.monotonic()
        assert aow.refresh(P1A, _refresher(ran), wanted=wanted)
        assert aow.refresh(P1B, _refresher(ran), wanted=wanted)
        assert aow.refresh(P1C, _refresher(ran), wanted=wanted)
        assert asked == [], "not asked at enqueue"
        gone.add(P1B)                        # e.g. its last tab closed after it was planned
        await _drain()
    at = {a: t - t0 for a, t in ran}
    assert set(at) == {P1A, P1C} and len(ran) == 2, f"P1B dropped unread: {ran}"
    assert [a for a, _ in asked] == [P1A, P1B, P1C], asked
    assert dict(asked)[P1B] - t0 >= READ_S + GAP, f"P1B asked at its turn: {asked}"
    assert GAP <= at[P1C] - (at[P1A] + READ_S) < 2 * GAP, f"no GAP for the dropped job: {at}"


async def case_refresh_deadline_frees_exit():
    """A refresh job hung past the job deadline (30 s) frees its exit: the next Creator there reads (one GAP later)
    while the hung walk runs on, never cancelled; its late result lands; logged `shared_refresher_job_timeout`."""
    assert aow.JOB_DEADLINE_S == 30.0, aow.JOB_DEADLINE_S
    deadline, hang = 0.2, 0.8
    ran: list[tuple[str, float]] = []
    landed: list[str] = []
    records: list[logging.LogRecord] = []
    h = logging.Handler(); h.emit = records.append
    lg = logging.getLogger("of-relay.app_open_warm"); lg.addHandler(h)
    old = aow.JOB_DEADLINE_S
    aow.JOB_DEADLINE_S = deadline
    try:
        with _patched():
            t0 = time.monotonic()
            aow.refresh(P1A, _refresher(ran, hang, landed), wanted=_yes)
            aow.refresh(P1B, _refresher(ran, READ_S, landed), wanted=_yes)
            await _drain()
    finally:
        aow.JOB_DEADLINE_S = old
        lg.removeHandler(h)
    at = {a: t - t0 for a, t in ran}
    assert deadline + GAP <= at[P1B] < hang, f"the exit serves P1B after the deadline, before P1A's walk ends: {at}"
    assert landed == [P1B, P1A], f"the hung walk was not cancelled: its late result landed: {landed}"
    msgs = [r.getMessage() for r in records]
    assert any(m.startswith("shared_refresher_job_timeout account=%s" % P1A) for m in msgs), msgs
    assert not any(P1B in m for m in msgs if "timeout" in m), msgs


async def case_refresh_429_holds_the_exit():
    """A refresh job whose read met a terminal 429 holds its whole exit for OF's asked wait (`hold`, 429s follow the
    proxy IP): the next Creator there, a refresh or a warm, starts no earlier; another exit at once. A hold shorter
    than GAP keeps GAP."""
    wait = 0.5
    ran: list[tuple[str, float]] = []

    def hot(hold_s):
        async def run(aid):
            ran.append((aid, time.monotonic()))
            await asyncio.sleep(READ_S)
            aow.hold(aid, hold_s)             # the shell's terminal-429 branch
        return run

    with _patched():
        t0 = time.monotonic()
        aow.refresh(P1A, hot(wait), wanted=_yes)
        aow.refresh(P1B, _refresher(ran), wanted=_yes)
        aow.refresh(P2A, _refresher(ran), wanted=_yes)
        await _drain()
        at = {a: t - t0 for a, t in ran}
        assert at[P2A] < GAP / 2, f"another exit: at once: {at}"
        assert wait + READ_S <= at[P1B] < wait + READ_S + GAP, f"same exit: held OF's wait, not GAP: {at}"
        aow.refresh(P1B, hot(wait), wanted=_yes)
        await _drain()
        t1 = time.monotonic()
        await aow.start(("user", "u1"), [P1C], leased_first=())  # a warm on the held, now idle, exit waits too
        await _drain()
        assert wait - 0.05 <= STEPS[-1][1] - t1, f"the warm waits out the hold: {STEPS[-1][1] - t1}"
        ran.clear()
        t2 = time.monotonic()
        aow.refresh(P2A, hot(GAP / 3), wanted=_yes)
        aow.refresh(P2B, _refresher(ran), wanted=_yes)
        await _drain()
    at = {a: t - t2 for a, t in ran}
    assert READ_S + GAP <= at[P2B] < READ_S + 2 * GAP, f"a hold under GAP keeps GAP: {at}"


async def case_refresh_dropped_at_turn_when_no_longer_wanted():
    """The Shared refresher's own jobs (its `tick`, the real `wanted`): queued behind a held exit, each re-checks at
    its turn and is dropped unread when its Creator left `tracked` (its last tab closed), went dead, or got a Last
    refresh meanwhile; a still-wanted one reads. A dropped job marks nothing in flight."""
    import shared_refresher as sr
    import shared_refresher_decide as srd
    clock = [1000.0]
    read: list[str] = []

    async def _reads(aid, window=None):
        read.append(aid)
        return True

    saved = (sr._state, sr._clock, sr._server, dict(sr._at_ms), dict(sr._seq), dict(sr._live_since_ms),
             accounts.is_watcher, accounts.get_platform)
    sr._state, sr._clock = srd.State(), (lambda: clock[0])
    sr._server = lambda: types.SimpleNamespace(shared_refresher_reads=_reads)
    accounts.is_watcher, accounts.get_platform = (lambda _a: False), (lambda _a: "onlyfans")
    tab_a = await events.subscribe("all", accounts=frozenset({P1A}), tab=True)
    tab_rest = await events.subscribe("all", accounts=frozenset({P1B, P1C, P2A}), tab=True)
    try:
        with _patched():
            await sr.tick()                          # first seen: published, nothing due yet
            aow.hold(P1A, 0.3)                       # both exits busy: the jobs queue
            aow.hold(P2A, 0.3)
            clock[0] += 61.0                         # past every first slot
            await sr.tick()
            queued = sorted(a for ex in aow._exits.values() for a in ex.jobs)
            assert queued == [P1A, P1B, P1C, P2A], queued
            await events.unsubscribe("all", tab_a)   # P1A's last tab closed
            DEAD_NOW.add(P1B)                        # P1B went dead
            sr._state = srd.after_read(sr._state, P1C, True, clock[0])   # P1C got a Last refresh meanwhile
            await _drain()
            assert read == [P2A], f"only the still-wanted job read: {read}"
            assert sr._in_flight == set(), sr._in_flight
    finally:
        await events.unsubscribe("all", tab_a)
        await events.unsubscribe("all", tab_rest)
        (sr._state, sr._clock, sr._server, at_ms, seq, live_since, accounts.is_watcher, accounts.get_platform) = saved
        for d, v in ((sr._at_ms, at_ms), (sr._seq, seq), (sr._live_since_ms, live_since)):
            d.clear()
            d.update(v)


class _OF:
    """A Creator's OF reads, counted: the chats window, the notifications lists and the count."""

    def __init__(self):
        self.user_id = 4242
        self.calls: list[tuple] = []

    def list_chats(self, *, limit=10, offset=0, order="recent", **_kw):
        self.calls.append(("chats", limit, offset))
        return {"list": [{"withUser": {"id": 5}, "unreadMessagesCount": 1, "lastMessage": {"fromUser": {"id": 5}}}],
                "hasMore": False}

    def notifications(self, *, limit=10, offset=0, type=None, **_kw):
        self.calls.append(("notifications", limit, offset, type))
        return {"list": [{"id": f"{type}-1", "type": type}], "hasMore": False}

    def notifications_count(self):
        self.calls.append(("count",))
        return {"all": 3, "tip": 1, "purchases": 1}


async def case_read_set_on_the_real_routes():
    import server   # first: accounts_admin_api is imported by server.py, never first
    import accounts_admin_api
    import relay_cache
    import relay_coalesce

    of = _OF()
    now = [5000.0]
    saved = [(server, "_load_client", lambda _aid: of), (server, "_resolve_account_id", lambda _req=None: P1A),
             (relay_cache, "time", types.SimpleNamespace(monotonic=lambda: now[0])),
             (aow, "_server", aow._server)]   # the real lookup, under _patched's stand-in
    with _patched():
        old = [(m, k, getattr(m, k)) for m, k, _ in saved]
        for m, k, v in saved:
            setattr(m, k, v)
        try:
            for ns in ("notifications", "notifications_count", "roster_count", "list_chats"):
                relay_cache.invalidate(ns, P1A)
            relay_coalesce.reset_for_tests()
            got = await aow.start(("user", "u1"), [P1A], leased_first=())
            assert got == {P1A: "started"}, got
            await _drain()
            assert [a for a, _, _ in READS] == [P1A], f"step 1: the purchases poll: {READS}"
            kinds = [c[0] for c in of.calls]
            assert kinds == ["chats", "notifications", "notifications", "count"], f"steps 2-4 in order: {of.calls}"
            assert len(READS) + len(of.calls) <= 5, "at most 5 reads per Creator"
            assert sorted(c[3] for c in of.calls if c[0] == "notifications") == ["purchases", "tip"], of.calls
            assert all(c[1:3] == (20, 0) for c in of.calls if c[0] == "notifications"), \
                f"the rail's page (app/lib/notifText.ts NOTIF_PAGE_SIZE 20, offset 0): {of.calls}"
            assert _warmed_ids() == [P1A], PUBLISHED
            warmed = PUBLISHED[0]["creator_warmed"]
            # The event carries what the warmed entries serve: the tab writes those, no re-read.
            assert {k: warmed["roster"][k] for k in ("unread", "owe_reply")} == {"unread": 1, "owe_reply": 0}, warmed
            assert warmed["roster"]["as_of"] > 0 and warmed["notif_count"] == 3 and warmed["now"] > 0, warmed
            n = len(of.calls)
            # 25 s later the tab's own reads, through the real routes, are served from the warm's entries.
            now[0] += 25.0
            for typ in ("tip", "purchases"):
                body = await server.of_notifications(limit=20, offset=0, type=typ, related_user=None, refresh=False)
                assert body["list"][0]["id"] == f"{typ}-1", body
            assert (await server.of_notifications_count(refresh=False))["all"] == 3
            fake_user = types.SimpleNamespace(id="u1", account_ids=[P1A])
            real_user, real_chatter = accounts_admin_api._get_request_user, accounts_admin_api._get_request_chatter
            accounts_admin_api._get_request_user = lambda: fake_user
            accounts_admin_api._get_request_chatter = lambda: None
            try:
                counts = await accounts_admin_api.admin_accounts_roster_counts(types.SimpleNamespace(headers={}))
            finally:
                accounts_admin_api._get_request_user, accounts_admin_api._get_request_chatter = real_user, real_chatter
            got = counts["counts"][P1A]
            assert {k: got[k] for k in ("unread", "owe_reply")} == {"unread": 1, "owe_reply": 0}, counts
            assert got["as_of"] > 0, counts   # the warm's window time (useRosterCounts keeps a newer patch)
            page0 = relay_cache._cache.get(("list_chats", P1A, (server._ROSTER_SCAN_MAX, 0, "recent", None, None, None)))
            assert page0 is not None, "the Fan List's page-0 window is warm"
            assert len(of.calls) == n, f"a pass-through read 25 s after the warm makes no OF call: {of.calls[n:]}"
            now[0] += 6.0   # 31 s: past the pass-through's 30 s TTL
            await server.of_notifications(limit=20, offset=0, type="tip", related_user=None, refresh=False)
            assert len(of.calls) == n + 1, of.calls
            # An expired entry is not carried (a reused warm's event then makes the tab re-read the count).
            assert "notif_count" not in server.app_open_warm_values(P1A), server.app_open_warm_values(P1A)
            assert server.app_open_warm_values(P1A)["roster"] == got, "the roster entry (300 s) still carried"
        finally:
            for m, k, v in old:
                setattr(m, k, v)
            for ns in ("notifications", "notifications_count", "roster_count", "list_chats"):
                relay_cache.invalidate(ns, P1A)


def case_hold_is_capped():
    """A 429's asked wait never holds an exit past HOLD_MAX_S (`Retry-After: inf`, a day, nan)."""
    for asked, lo, hi in ((float("inf"), 899.0, 900.0), (86400.0, 899.0, 900.0), (float("nan"), 899.0, 900.0),
                          (-5.0, 899.0, 900.0), (30.0, 29.0, 30.0)):
        aow.hold("hold-cap", asked)
        ex = aow._gate("hold-cap")[1]
        left = ex.free_at - time.monotonic()
        assert lo < left <= hi, (asked, left)
        ex.free_at = 0.0


_harness.run()
