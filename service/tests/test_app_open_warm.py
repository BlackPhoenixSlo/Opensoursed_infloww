#!/usr/bin/env python3
"""The App-open warm (ADR-0031, phase-01 1a, service/app_open_warm.py): an opened document load warms every
Creator the Employee can access, once: one purchases poll per Creator (1a: the feed only), per proxy one at a
time APP_OPEN_WARM_GAP_S apart, proxies in parallel, leased Creators first.

Fakes: the OF client (client_pool.get: only its bound endpoint, `proxy_url`, is read), the feed read
(transaction_ingest.run_fast_tick, behind the real poll_now and its single-flight), the registries (read through
the real transaction_ingest.live_account_ids), the reuse clock (`app_open_warm._clock`) and a last ok poll (a
seeded `transaction_ingest._poll_state`).

  • case_every_creator_once: each live Creator read exactly once, Caller kind walk:app_open_warm; dead,
    deactivated, watcher and no-session Creators skipped (not in the answer, no read); per proxy serial, starts
    >= GAP_S apart, leased first; the three groups start together; no `creator_warmed` published (1a).
  • case_reuse: a second start inside APP_OPEN_WARM_REUSE_S answers `reused` and reads nothing, also while the
    first is still running; past the window it reads again.
  • case_recently_polled_no_read: a Creator whose last ok purchases poll is younger than PURCHASES_POLL_FAST_S
    gets no feed read (it is still `started`, and takes no gap).
  • case_refreshed_first: a Creator the route Select-refreshes is `started`, warmed and never read here; the
    group on its proxy reads one GAP_S late, the others at once.

Run:  ./venv/bin/python service/tests/test_app_open_warm.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402

import account_health  # noqa: E402
import accounts  # noqa: E402
import app_open_warm as aow  # noqa: E402
import client_pool  # noqa: E402
import events  # noqa: E402
import of_call_counter  # noqa: E402
import purchase_poll_decide as decide  # noqa: E402
import transaction_ingest as ti  # noqa: E402

P1A, P1B, P1C, P2A, P2B, D1, DEAD, OFF, WATCH, NOSESS = (f"77{i:02d}" for i in range(10))
PROXY = {P1A: "socks5://u:pw@10.0.0.1:1080", P1B: "socks5://10.0.0.1:1080", P1C: "socks5://10.0.0.1:1080",
         P2A: "http://10.0.0.2:3128", P2B: "http://10.0.0.2:3128", D1: None}
LIVE = [P1A, P1B, P1C, P2A, P2B, D1]
ALL = LIVE + [DEAD, OFF, WATCH, NOSESS]
GAP = 0.15
READ_S = 0.03
READS: list[tuple[str, float, str]] = []   # (Creator, start, Caller kind) per feed read
PUBLISHED: list[dict] = []
CLOCK = [1000.0]


@contextlib.contextmanager
def _patched():
    async def _tick(aid):
        READS.append((aid, time.monotonic(), of_call_counter.caller_kind()))
        await asyncio.sleep(READ_S)
        return {"rows_inserted": 0, "rows_patched": 0, "error": None}

    async def _off():
        return {OFF}

    async def _dead():
        return {DEAD: object()}

    async def _false(_aid):
        return False

    saved = [(ti, "run_fast_tick", _tick), (ti, "_is_paused", _false),
             (accounts, "list_accounts",
              lambda include_watchers=False: [{"id": a, "has_session": a != NOSESS} for a in ALL
                                              if include_watchers or a != WATCH]),
             (account_health, "deactivated_ids", _off), (account_health, "dead_session_map", _dead),
             (client_pool, "get", lambda a: types.SimpleNamespace(proxy_url=PROXY.get(a), proxy_label=None)),
             (events, "publish", PUBLISHED.append),
             (aow, "GAP_S", GAP), (aow, "_clock", lambda: CLOCK[0])]
    old = [(m, k, getattr(m, k)) for m, k, _ in saved]
    for m, k, v in saved:
        setattr(m, k, v)
    READS.clear()
    PUBLISHED.clear()
    aow._warmed_at.clear()
    aow._pending.clear()
    ti._poll_state.clear()
    ti._poll_inflight.clear()
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
    assert PUBLISHED == [], f"1a publishes nothing: {PUBLISHED}"


async def case_reuse():
    with _patched():
        CLOCK[0] = 2000.0
        got = await aow.start(("user", "u1"), LIVE, leased_first=())
        assert set(got.values()) == {"started"}, got
        again = await aow.start(("chatter", "c1"), LIVE, leased_first=())   # the first still running
        assert again == {a: "reused" for a in LIVE}, again
        await _drain()
        n = len(READS)
        assert n == len(LIVE), READS
        CLOCK[0] = 2000.0 + aow.REUSE_S - 1
        assert await aow.start(("user", "u2"), LIVE, leased_first=()) == {a: "reused" for a in LIVE}
        await _drain()
        assert len(READS) == n, "inside the reuse window: no read"
        CLOCK[0] = 2000.0 + aow.REUSE_S + 1
        ti._poll_state.clear()   # forget any last ok poll, so the window alone decides
        assert await aow.start(("user", "u2"), LIVE, leased_first=()) == {a: "started" for a in LIVE}
        await _drain()
        assert len(READS) == 2 * n, READS


async def case_recently_polled_no_read():
    with _patched():
        now = time.monotonic()
        ti._poll_state[P1A] = decide.PollState(last_ok_s=now - (decide.FAST_S - 5))   # inside the fast interval
        ti._poll_state[P1B] = decide.PollState(last_ok_s=now - (decide.FAST_S + 5))   # older: read
        t0 = time.monotonic()
        got = await aow.start(("user", "u1"), [P1A, P1B, P1C], leased_first=())
        assert got == {P1A: "started", P1B: "started", P1C: "started"}, got
        await _drain()
    assert [a for a, _, _ in READS] == [P1B, P1C], READS
    assert P1A in aow._warmed_at, "a current Creator counts as warmed: a second open reuses it"
    # P1A took no gap: P1B started at once.
    assert READS[0][1] - t0 < GAP / 2, READS


async def case_refreshed_first():
    with _patched():
        t0 = time.monotonic()
        got = await aow.start(("user", "u1"), [P1A, P1B, P2A], leased_first=(), refreshed=[P1A])
        assert got == {P1A: "started", P1B: "started", P2A: "started"}, got
        assert P1A in aow._warmed_at and P1A not in aow._pending, "the Select-refreshed Creator counts as warmed"
        await _drain()
        again = await aow.start(("user", "u2"), [P1A], leased_first=())
    assert again == {P1A: "reused"}, again
    assert sorted(a for a, _, _ in READS) == [P1B, P2A], f"the Select-refreshed Creator is not read here: {READS}"
    at = {a: t - t0 for a, t, _ in READS}
    assert at[P1B] >= GAP, f"its proxy's group waits one GAP after the Select refresh: {at}"
    assert at[P2A] < GAP / 2, f"another proxy's group starts at once: {at}"


_harness.run()
