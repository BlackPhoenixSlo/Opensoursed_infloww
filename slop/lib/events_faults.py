"""The app's EventBus (app/lib/events.ts, its rules in app/lib/eventBusReducer.ts) break-it-once
faults: lib/faults.py merges `register(Fault)` into FAULTS. Client side (`browser=`): they rewrite
eventBusReducer.ts as lib/app_ts.py loads it in node (slop/lib/events_ts.mjs drives the real bus on
an Agency's real /events). Run them with --no-ui: in a UI run the browser's tabs would load the
rewritten module too (another file count, and their own checks as noise). The check names live
here and scenarios/2026-10-24-big-model-dm-flood.py imports them, so a target always names a check.
"""
from __future__ import annotations

BUS_NOTHING_DROPPED = ("event bus (the app's EventBus on the Agency's /events): nothing dropped across a forced "
                       "reconnect and a pause/resume (every DM the relay sent in its window reached the listeners, "
                       "once, no resync)")
BUS_ORDER = ("event bus: listeners got the DMs in the relay's order (as the direct /events listener got them), "
             "across the reconnects, the pause/resume and the hot-rate flushes")
BUS_BACKOFF = ("event bus: reconnect backoff doubles from 5s, never exceeds the 60s cap, and starts at 5s "
               "again once a socket opened")


def register(Fault) -> dict:
    return {
        # slop/run big-model --no-ui --break --fault=event-bus-resume-without-last-id
        # Every reopen (the retry after the outage, resume after the pause) asks for the live stream
        # only, so what the relay sent meanwhile is never replayed. Order and backoff stay right.
        "event-bus-resume-without-last-id": Fault(None, (BUS_NOTHING_DROPPED,), browser=(
            (r"lastEventId: ev\.resume \? state\.lastEventId : \"\"", 'lastEventId: ""'),
        )),
        # slop/run big-model --no-ui --break --fault=event-bus-flush-reverses-order
        # A hot-rate flush applies its queue newest first. Nothing is lost; only the order check sees it.
        "event-bus-flush-reverses-order": Fault(None, (BUS_ORDER,), browser=(
            (r'type: "Apply",\s*events: s\.pending\b', 'type: "Apply", events: [...s.pending].reverse()'),
        )),
        # slop/run big-model --no-ui --break --fault=event-bus-backoff-uncapped
        # The retry delay keeps doubling past 60 s (80 s, 160 s, ...).
        "event-bus-backoff-uncapped": Fault(None, (BUS_BACKOFF,), browser=(
            (r"retryMs: Math\.min\(state\.retryMs \* 2, RETRY_MAX_MS\)", "retryMs: state.retryMs * 2"),
        )),
    }
