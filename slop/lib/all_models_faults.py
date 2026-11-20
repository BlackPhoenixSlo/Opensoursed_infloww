"""scenarios/2026-11-20-all-models-shared-inbox.py's checks and faults: lib/faults.py merges `register(Fault)`.

  warm-ignores-reuse        the App-open warm forgets every Creator it warmed before each `start` (app_open_warm's
                            REUSE_S window never holds) and ignores the shared Last refresh (`shared_refresher.
                            last_refresh` None: no netting, ADR-0044): a second chatter's open inside the window, and a
                            later open within the refresher's Cycle, re-warm every Creator (its roster rewarm re-reads
                            each chats window with bypass).
  refresher-per-subscriber  the Shared refresher reads per tab subscriber, not per Creator: each due Creator's job
                            (`app_open_warm.refresh`) gains one copy per further app-tab subscriber whose clamp holds
                            it, each its own entry on the exit's queue (keyed `<id>#sub<i>`, so the gate's one entry
                            per Creator cannot absorb it), always wanted at its turn, reading the server's
                            `shared_refresher_reads` (cache bypass) in a `walk:shared_refresher` walk. Patched here,
                            never in service/.
  unread-total-frozen       the Unread total keeps OF's first number: `unread_total.observe` takes a Creator's first
                            `/users/me` `chatMessagesCount` and drops every later one (our own DMs, flips and replies
                            still move it, so no drift ever shows): a read on OF web never lowers the badge nor
                            clears a row (READ_ON_OF_CLEARS), a fresh session's first badge misses every read made
                            elsewhere (FRESH_BADGE_TRUE). Patched here, never in service/.
  fresh-ping-off            the stream ping carries no `fresh` (`events._fresh` answers None, so `events_wire.ping`
                            sends `{ts}` only): an unchanged Cycle publishes nothing (`shared_refresher_decide.changed`
                            ignores `at`), so a quiet Creator's confirmations never reach a tab and the Unread chip
                            ages past its Cycle + slack into "as of" (QUIET_NOT_STALE). Patched here, never in service/.
"""
from __future__ import annotations

SECOND_OPEN_SHARED = ("a second chatter's All Models open within the warm's reuse window reads no chats list from "
                      "OF and at most SECOND_OPEN_MAX_PER_CREATOR other OF calls per Creator")
IDLE_BUDGET = "three idle All Models tabs cost each Creator at most IDLE_MAX_PER_CREATOR_MIN OF calls a minute"
DM_NO_LIST_REREAD = "fan DMs to chats already listed read no chats list from OF"
DM_ROW_LAG = "a fan DM shows in every All Models tab's row within DM_ROW_LAG_P95_MS (p95)"
REFRESHER_FLAT_IN_N = ("the Shared refresher reads each Creator once a Cycle whatever the tab count: per Creator per "
                       "minute in [0.8, 1.2] with three tabs and with one, three at most 0.25 above one")
REFRESH_WITHIN_CYCLE = "every Creator's Last refresh is at most its Cycle + 10 s old in every idle freshness sample"
REFRESHER_STOPS_WITHOUT_TABS = "no Shared refresher read after the first tick once every tab is closed"
READ_ON_OF_CLEARS = ("a chat read on OF's own site clears its row and drops the Unread chip in every All Models tab "
                     "within one Cycle (CLEAR_MAX_MS)")
FRESH_BADGE_TRUE = "a fresh All Models session's first Unread badge equals OF's whole-inbox unread chats"
OPEN_AFTER_CYCLE_REUSED = ("an open long past every warm reads no Creator the Shared refresher read within its Cycle "
                           "and costs at most OPEN_TOTAL_MAX OF calls of its own")
QUIET_NOT_STALE = ("a quiet Creator the Shared refresher reads within its Cycle shows no 'as of' on tab A's Unread "
                   "chip in either idle phase")


def _warm_ignores_reuse() -> None:
    import app_open_warm
    import shared_refresher
    orig = app_open_warm.start

    async def start(*a, **kw):
        app_open_warm._warmed_at.clear()
        return await orig(*a, **kw)

    app_open_warm.start = start
    shared_refresher.last_refresh = lambda _aid: None   # the warm's only reader of it (app_open_warm._decide)


def _subscribers(subs, account_id: str) -> int:
    """App-tab subscribers whose clamp holds `account_id` (events._subs' values)."""
    return sum(1 for s in list(subs) if s.tab and s.accounts is not None and account_id in s.accounts)


def _refresher_per_subscriber() -> None:
    import app_open_warm
    import events
    import of_pacing
    import shared_refresher
    orig = app_open_warm.refresh

    async def always(_key: str) -> bool:
        return True

    def copy(aid: str):
        async def run(_key: str) -> None:
            await of_pacing.walk(aid, "shared_refresher", lambda: shared_refresher._server().shared_refresher_reads(aid))
        return run

    def refresh(account_id, run, *, wanted):
        took = orig(account_id, run, wanted=wanted)
        _, ex = app_open_warm._gate(account_id)   # orig's _enqueue left its worker running: it sees these too
        for i in range(1, _subscribers(events._subs.values(), account_id)):
            ex.jobs[f"{account_id}#sub{i}"] = app_open_warm._Job(False, None, copy(account_id), always)
        return took

    app_open_warm.refresh = refresh


def _unread_total_frozen() -> None:
    import threading

    import unread_total
    import unread_total_decide as decide
    orig = unread_total.observe          # observe_response calls it through the module: the patch is seen
    seen: set[str] = set()
    lock = threading.Lock()

    def observe(account_id, me_body, asked_at):
        if decide.count(me_body) is None:
            return orig(account_id, me_body, asked_at)
        with lock:
            first = account_id not in seen
            seen.add(account_id)
        if first:
            orig(account_id, me_body, asked_at)

    unread_total.observe = observe


def _fresh_ping_off() -> None:
    import events
    events._fresh = lambda _sub, _shared_refresher: None   # events.stream looks it up per ping: seen


def register(Fault) -> dict:
    return {"warm-ignores-reuse": Fault(_warm_ignores_reuse, (SECOND_OPEN_SHARED, OPEN_AFTER_CYCLE_REUSED)),
            "refresher-per-subscriber": Fault(_refresher_per_subscriber, (REFRESHER_FLAT_IN_N,)),
            "unread-total-frozen": Fault(_unread_total_frozen, (READ_ON_OF_CLEARS, FRESH_BADGE_TRUE)),
            "fresh-ping-off": Fault(_fresh_ping_off, (QUIET_NOT_STALE,))}
