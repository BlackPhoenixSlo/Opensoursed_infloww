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
  • case_recently_polled_no_read: a Creator whose last ok purchases poll is younger than PURCHASES_POLL_FAST_S
    gets no feed read, still steps 2-4 and its event.
  • case_refreshed_first: a Creator the route Select-refreshes is `started`, gets no feed read here, its steps 2-4
    first on its proxy one GAP_S late (the Select refresh reads there now); the others' groups at once.
  • case_pace_lease_gains: a lease renewal's gains (`pace`): feed reads only, grouped per proxy GAP_S apart, a
    proxy the selection reads on waits one GAP_S, a current Creator skipped; no steps 2-4, event or memo.
  • case_dead_after_feed_read: a Creator its feed read flags a Dead session reads nothing more and publishes nothing.
  • case_read_set_on_the_real_routes: the real server helper and roster-counts recompute over a fake OF client:
    the four steps in order, at most 5 reads, the money lists at the rail's page size, `creator_warmed` in the house
    envelope; the entries are the pass-through's (`of_notifications`, `of_notifications_count`, roster-counts,
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


REFUSED: set[str] = set()                  # Creators whose reads the Relay refuses (bad session, 503)


async def _steps(aid):
    STEPS.append((aid, time.monotonic(), of_call_counter.caller_kind()))
    if aid in REFUSED:
        raise HTTPException(503, {"error": "bad_session"})
    await asyncio.sleep(STEP_S)


SERVER = types.SimpleNamespace(app_open_warm_reads=_steps)


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
             (aow, "GAP_S", GAP), (aow, "_clock", lambda: CLOCK[0]), (aow, "_server", lambda: SERVER)]
    old = [(m, k, getattr(m, k)) for m, k, _ in saved]
    for m, k, v in saved:
        setattr(m, k, v)
    READS.clear()
    STEPS.clear()
    PUBLISHED.clear()
    FLAG_DEAD.clear()
    DEAD_NOW.clear()
    aow._warmed_at.clear()
    aow._pending.clear()
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


async def case_recently_polled_no_read():
    with _patched():
        now = time.monotonic()
        pp._poll_state[P1A] = decide.PollState(last_ok_s=now - (decide.FAST_S - 5))   # inside the fast interval
        pp._poll_state[P1B] = decide.PollState(last_ok_s=now - (decide.FAST_S + 5))   # older: read
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
    proxies in parallel, a proxy the selection reads on now waits one GAP_S first; a Creator polled ok inside
    PURCHASES_POLL_FAST_S by its turn is skipped; no steps 2-4, no event, no warm memo."""
    polled: list[tuple[str, float]] = []

    async def poll(aid):
        polled.append((aid, time.monotonic()))
        await asyncio.sleep(READ_S)

    with _patched():
        pp._poll_state[P1C] = decide.PollState(last_ok_s=time.monotonic())    # current: skipped
        t0 = time.monotonic()
        aow.pace([P1A, P1B, P1C, P2A, D1], poll, busy=[P2B])
        await _drain()
    at = {a: t - t0 for a, t in polled}
    assert set(at) == {P1A, P1B, D1, P2A} and len(polled) == 4, f"each once, the current one skipped: {polled}"
    assert at[P1A] < GAP / 2 and at[D1] < GAP / 2, f"groups in parallel, at once: {at}"
    assert at[P1B] - at[P1A] >= GAP, f"same proxy: GAP_S apart: {at}"
    assert at[P2A] >= GAP, f"the selection reads on P2's proxy now: one GAP_S first: {at}"
    assert STEPS == [] and PUBLISHED == [] and aow._warmed_at == {} and aow._pending == set(), (STEPS, PUBLISHED)


async def case_dead_after_feed_read():
    with _patched():
        FLAG_DEAD.add(P1A)
        got = await aow.start(("user", "u1"), [P1A, P1B], leased_first=())
        assert got == {P1A: "started", P1B: "started"}, got
        await _drain()
    assert [a for a, _, _ in READS] == [P1A, P1B], READS
    assert [a for a, _, _ in STEPS] == [P1B], f"a Creator flagged dead by its feed read reads nothing more: {STEPS}"
    assert _warmed_ids() == [P1B], PUBLISHED


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
        finally:
            for m, k, v in old:
                setattr(m, k, v)
            for ns in ("notifications", "notifications_count", "roster_count", "list_chats"):
                relay_cache.invalidate(ns, P1A)


_harness.run()
