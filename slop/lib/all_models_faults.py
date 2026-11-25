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
    shared_refresher.last_refresh = lambda _aid: None


def _subscribers(subs, account_id: str) -> int:
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
        _, ex = app_open_warm._gate(account_id)
        for i in range(1, _subscribers(events._subs.values(), account_id)):
            ex.jobs[f"{account_id}#sub{i}"] = app_open_warm._Job(False, None, copy(account_id), always)
        return took

    app_open_warm.refresh = refresh


def _unread_total_frozen() -> None:
    import threading

    import unread_total
    import unread_total_decide as decide
    orig = unread_total.observe
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
    events._fresh = lambda _sub, _shared_refresher: None


def register(Fault) -> dict:
    return {"warm-ignores-reuse": Fault(_warm_ignores_reuse, (SECOND_OPEN_SHARED, OPEN_AFTER_CYCLE_REUSED)),
            "refresher-per-subscriber": Fault(_refresher_per_subscriber, (REFRESHER_FLAT_IN_N,)),
            "unread-total-frozen": Fault(_unread_total_frozen, (READ_ON_OF_CLEARS, FRESH_BADGE_TRUE)),
            "fresh-ping-off": Fault(_fresh_ping_off, (QUIET_NOT_STALE,))}
