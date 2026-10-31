"""The relay's SSE replay rule (service/events_decide.py, `replay`) break-it-once fault:
lib/faults.py merges `register(Fault)` into FAULTS. It patches the pure decide inside the relay
(events.py calls it through the module, so the shell performs what the patched one says). The check
it targets is the EventBus run's on scenarios/2026-10-24-big-model-dm-flood.py (lib/events_faults.py
owns the name): the bus reopens Agency 0's real /events with Last-Event-ID after each outage, so a
replay that loses an event shows up there and nowhere else (the direct listeners never reconnect).
"""
from __future__ import annotations

try:
    from .events_faults import BUS_NOTHING_DROPPED
except ImportError:  # inside the relay lib/ is on sys.path, not a package
    from events_faults import BUS_NOTHING_DROPPED


def _replay_skips_oldest_missed() -> None:
    """A reconnect's replay starts one event late: the oldest event the stream missed after its
    Last-Event-ID is dropped (an off-by-one at the id boundary, `seq > since + 1`). No resync, the
    rest in order, and the live stream and the DB untouched: only "nothing dropped across a
    reconnect" can see it."""
    import events_decide as ed

    real = ed.replay

    def skipping(*a, **kw):
        out, skipped = [], False
        for e in real(*a, **kw):
            if isinstance(e, ed.Emit) and not skipped:
                skipped = True
                if len(e.frames) > 1:
                    out.append(ed.Emit(e.frames[1:]))
                continue
            out.append(e)
        return tuple(out)

    ed.replay = skipping


def register(Fault) -> dict:
    return {
        # slop/run big-model --no-ui --break --fault=sse-replay-skips-oldest-missed
        "sse-replay-skips-oldest-missed": Fault(_replay_skips_oldest_missed, (BUS_NOTHING_DROPPED,)),
    }
