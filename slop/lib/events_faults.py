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
        "event-bus-resume-without-last-id": Fault(None, (BUS_NOTHING_DROPPED,), browser=(
            (r"lastEventId: ev\.resume \? state\.lastEventId : \"\"", 'lastEventId: ""'),
        )),
        "event-bus-flush-reverses-order": Fault(None, (BUS_ORDER,), browser=(
            (r'type: "Apply",\s*events: s\.pending\b', 'type: "Apply", events: [...s.pending].reverse()'),
        )),
        "event-bus-backoff-uncapped": Fault(None, (BUS_BACKOFF,), browser=(
            (r"retryMs: Math\.min\(state\.retryMs \* 2, RETRY_MAX_MS\)", "retryMs: state.retryMs * 2"),
        )),
    }
