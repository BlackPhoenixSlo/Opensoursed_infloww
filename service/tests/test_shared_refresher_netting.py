#!/usr/bin/env python3
"""Shared refresher netting with the App-open warm (phase-01 seam 3, ADR-0044), over the server's `app_open_warm_reads`
with a stubbed client and a recording roster rewarm, and over `app_open_warm.start` with its reads stubbed.

  case_warm_step_2_goes_through_window_read: with the refresher on, the warm's step 2 reads the chats window only
      through the window-read hook (`shared_refresher.window_read`: a registered reader, else the roster rewarm);
      off, it reads exactly as today (the roster rewarm, never the hook's reader).
  case_warm_reused_inside_the_cycle_started_past_it: on, the warm answers `reused` (no read) for a Creator whose shared
      Last refresh is within its Cycle (the lease tier's when leased) and `started` past it, its OF WebSocket up or
      down alike; off, the shared Last refresh is not consulted (today's rule).
  case_warm_reads_users_me_bypassing_only_when_on: on, the warm reads `/users/me` from OF (a held entry never serves
      it) into the route's entry; off, it reads no `/users/me`.
  case_refresher_not_due_after_a_warm: a warm's kept `/users/me` writes the Creator's Last refresh (its ask time, `at`
      in epoch ms): the refresher's plan reads it again only at its next slot, and a job planned before the warm is
      dropped at its turn.
  case_discarded_or_failed_warm_writes_no_last_refresh: a warm whose `/users/me` write-back was discarded (invalidated
      mid-fetch, latest-wins), or whose later reads failed, leaves the Last refresh and `at` as they were.

Run: ./venv/bin/python service/tests/test_shared_refresher_netting.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # noqa: E401,E702
import _harness  # noqa: E402  (first: temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import types  # noqa: E402

import server  # noqa: E402  (before accounts_admin_api: server loads it)
import accounts_admin_api  # noqa: E402
import app_open_warm as aow  # noqa: E402
import events  # noqa: E402
import purchase_poll  # noqa: E402
import relay_cache  # noqa: E402
import relay_coalesce  # noqa: E402
import shared_refresher  # noqa: E402
import shared_refresher_decide as decide  # noqa: E402
import transaction_ingest  # noqa: E402
import view_lease  # noqa: E402

ME = {"id": 4242, "username": "creator", "notificationsCount": 3}
PRIOR = 100.0                 # a Last refresh held before the warm (monotonic)
PRIOR_MS = 1_700_000_000_000
ASK = 5000.0                  # the warm's ask time on the injected clock


class _Rail:
    """The warm's OF reads past the window: `/users/me` (counted; `during` runs inside it), the rail's money lists,
    the notifications count (`count_exc` raised)."""

    def __init__(self, during=None, count_exc=None):
        self.me_calls, self.during, self.count_exc = 0, during, count_exc

    def me(self):
        self.me_calls += 1
        if self.during is not None:
            self.during()
        return dict(ME)

    def notifications(self, **_k):
        return {"list": []}

    def notifications_count(self):
        if self.count_exc is not None:
            raise self.count_exc
        return {"all": 0}


async def _warm_reads(aid: str, *, enabled: bool, reader: bool, client: _Rail | None = None, prime=None) -> dict:
    """One `server.app_open_warm_reads(aid)`; the Creator held a Last refresh (PRIOR); `prime`: a fresh `users_me`
    entry held before. Returns the window reads, the client, what it raised, the Last refresh after and the entry."""
    relay_cache._cache.clear()
    relay_coalesce.reset_for_tests()
    if prime is not None:
        relay_cache._cache[("users_me", aid, ("users_me",))] = (prime, relay_cache.time.monotonic() + 60.0)
    got = {"rewarm": [], "reader": []}
    client = client or _Rail()

    async def rewarm(a):
        got["rewarm"].append(a)
        return {"unread": 0, "owe_reply": 0, "as_of": 0}

    async def recorder(a):
        got["reader"].append(a)

    saved = (shared_refresher.ENABLED, shared_refresher._window_reader, accounts_admin_api.rewarm_roster_count,
             server._load_client, shared_refresher._state, dict(shared_refresher._at_ms), shared_refresher._clock)
    shared_refresher.ENABLED = enabled
    shared_refresher._window_reader = recorder if reader else None
    accounts_admin_api.rewarm_roster_count = rewarm
    server._load_client = lambda *_a, **_k: client
    shared_refresher._state = decide.State(last={aid: PRIOR})
    shared_refresher._at_ms.clear()
    shared_refresher._at_ms[aid] = PRIOR_MS
    shared_refresher._clock = lambda: ASK
    try:
        try:
            await server.app_open_warm_reads(aid)
            got["raised"] = None
        except Exception as e:  # noqa: BLE001 — the case reads it
            got["raised"] = e
        got.update(client=client, state=shared_refresher._state, at=shared_refresher._at_ms.get(aid),
                   entry=relay_cache.peek_fresh("users_me", aid, ("users_me",)))
    finally:
        (shared_refresher.ENABLED, shared_refresher._window_reader, accounts_admin_api.rewarm_roster_count,
         server._load_client, shared_refresher._state, at_ms, shared_refresher._clock) = saved
        shared_refresher._at_ms.clear()
        shared_refresher._at_ms.update(at_ms)
        relay_cache._cache.clear()
    return got


async def case_warm_step_2_goes_through_window_read():
    aid = "acct-n1"
    win = lambda g: {k: g[k] for k in ("rewarm", "reader")}  # noqa: E731
    assert win(await _warm_reads(aid, enabled=True, reader=True)) == {"rewarm": [], "reader": [aid]}, \
        "on: the hook's reader"
    assert win(await _warm_reads(aid, enabled=True, reader=False)) == {"rewarm": [aid], "reader": []}, \
        "on, no reader: the hook's default, the roster rewarm"
    assert win(await _warm_reads(aid, enabled=False, reader=True)) == {"rewarm": [aid], "reader": []}, \
        "off: as today, the hook never consulted"


async def case_warm_reads_users_me_bypassing_only_when_on():
    aid = "acct-n2"
    on = await _warm_reads(aid, enabled=True, reader=False, prime={"stale": True})
    assert on["raised"] is None and on["client"].me_calls == 1, ("on: one /users/me from OF, never the held entry", on)
    assert on["entry"] == ME, ("the route's entry rewritten with what OF answered", on["entry"])
    off = await _warm_reads(aid, enabled=False, reader=False, prime={"stale": True})
    assert off["raised"] is None and off["client"].me_calls == 0, ("off: no /users/me read", off)
    assert off["entry"] == {"stale": True}, off["entry"]
    assert off["state"].last == {aid: PRIOR} and off["at"] == PRIOR_MS, ("off: no Last refresh written", off)


async def case_refresher_not_due_after_a_warm():
    aid = "acct-n3"
    r = await _warm_reads(aid, enabled=True, reader=False)
    assert r["raised"] is None, r
    st = r["state"]
    assert st.last == {aid: ASK} and r["at"] > PRIOR_MS, ("the warm's kept /users/me is the Last refresh", st, r["at"])
    cycle = decide.cycle_s(False, aid, shared_refresher.KNOBS)
    ins = lambda now: decide.Inputs(now=now, tracked=frozenset({aid}), readable=frozenset({aid}))  # noqa: E731
    reads = lambda now: [e for e in decide.plan(st, ins(now), shared_refresher.KNOBS)[1]  # noqa: E731
                         if isinstance(e, decide.Read)]
    assert reads(ASK + 1) == [] and reads(ASK + cycle - 1) == [], "just warmed: not due before its next slot"
    assert reads(ASK + cycle) == [decide.Read(aid)], "due at its next slot"
    # A refresher job planned before the warm landed (Last refresh PRIOR) is dropped at its turn.
    saved = (shared_refresher._state, events.open_tab_accounts, transaction_ingest.live_account_ids)

    async def live():
        return [aid]
    shared_refresher._state = st
    events.open_tab_accounts = lambda: frozenset({aid})
    transaction_ingest.live_account_ids = live
    try:
        assert await shared_refresher._wanted(PRIOR)(aid) is False, "refreshed meanwhile: dropped unread"
        assert aid not in shared_refresher._in_flight
    finally:
        shared_refresher._state, events.open_tab_accounts, transaction_ingest.live_account_ids = saved


async def case_discarded_or_failed_warm_writes_no_last_refresh():
    aid = "acct-n4"
    r = await _warm_reads(aid, enabled=True, reader=False,
                          client=_Rail(during=lambda: relay_cache.invalidate("users_me", aid)))
    assert r["raised"] is None and r["client"].me_calls == 1 and r["entry"] is None, ("discarded write-back", r)
    assert r["state"].last == {aid: PRIOR} and r["at"] == PRIOR_MS, ("a discarded /users/me confirms nothing", r)
    r = await _warm_reads(aid, enabled=True, reader=False, client=_Rail(count_exc=RuntimeError("count down")))
    assert isinstance(r["raised"], RuntimeError) and r["client"].me_calls == 1, r
    assert r["state"].last == {aid: PRIOR} and r["at"] == PRIOR_MS, ("a failed warm writes no Last refresh", r)


# ── app_open_warm.start's reuse decision under Netting ──────────────────────────────────────────────────────────
NOW = 10_000.0


@contextlib.contextmanager
def _start_world(aids, *, enabled: bool, last: dict, ws: dict):
    """`app_open_warm.start` over stubbed reads: `aids` live, no feed read (polled just now), steps 2-4 recorded;
    the shared Last refresh `last`, the OF WebSocket `ws` (Creator -> connected-at; absent: down), one clock."""
    steps: list[str] = []

    async def reads(aid):
        steps.append(aid)

    async def live():
        return list(aids)
    srv = types.SimpleNamespace(app_open_warm_reads=reads, app_open_warm_values=lambda _a: {})
    patches = [(transaction_ingest, "live_account_ids", live), (purchase_poll, "last_poll_age_s", lambda _a: 0.0),
               (events, "publish", lambda _e: None), (aow, "_server", lambda: srv), (aow, "_clock", lambda: NOW),
               (aow, "_ws_since", ws.get), (shared_refresher, "_clock", lambda: NOW),
               (shared_refresher, "ENABLED", enabled), (shared_refresher, "_state", decide.State(last=dict(last)))]
    old = [(m, k, getattr(m, k)) for m, k, _ in patches]
    for m, k, v in patches:
        setattr(m, k, v)
    for d in (aow._warmed_at, aow._failed_at, aow._pending, aow._exits, view_lease._holders):
        d.clear()
    try:
        yield steps
    finally:
        for m, k, v in old:
            setattr(m, k, v)
        view_lease._holders.clear()


async def _drain():
    while aow._tasks:
        await asyncio.gather(*list(aow._tasks))


async def case_warm_reused_inside_the_cycle_started_past_it():
    a, b = "acct-n5", "acct-n6"
    ca, cb = (decide.cycle_s(False, x, shared_refresher.KNOBS) for x in (a, b))
    assert ca > aow.REUSE_S + 2 and cb > aow.REUSE_S + 2, (ca, cb)
    for name, ws in (("socket up since long before", {a: 1.0, b: 1.0}), ("socket down", {}),
                     ("reconnected after the Last refresh", {a: NOW - 1, b: NOW - 1})):
        last = {a: NOW - (ca - 1), b: NOW - (cb + 1)}       # a inside its Cycle, b past it
        with _start_world((a, b), enabled=True, last=last, ws=ws) as steps:
            got = await aow.start(("chatter", "c1"), [a, b])
            await _drain()
        assert got == {a: "reused", b: "started"}, (name, got)
        assert steps == [b], (name, "only the Creator past its Cycle is read", steps)
    # The lease tier: a leased Creator's Cycle is the lease cycle.
    lc = decide.cycle_s(True, a, shared_refresher.KNOBS)
    assert lc < ca, (lc, ca)
    with _start_world((a,), enabled=True, last={a: NOW - (lc + 1)}, ws={}) as steps:
        view_lease.renew(("user", "u9", "tab1"), [a], None)
        assert view_lease.is_leased(a), "the lease row needs a held lease"
        got = await aow.start(("chatter", "c1"), [a])
        await _drain()
    assert got == {a: "started"}, ("leased: past its lease Cycle", got)
    # Off: today's rule, the shared Last refresh not consulted (never warmed here: started; socket alike).
    with _start_world((a,), enabled=False, last={a: NOW - 1}, ws={a: 1.0}) as steps:
        got = await aow.start(("chatter", "c1"), [a])
        await _drain()
    assert got == {a: "started"} and steps == [a], ("off: unchanged", got, steps)


_harness.run()
