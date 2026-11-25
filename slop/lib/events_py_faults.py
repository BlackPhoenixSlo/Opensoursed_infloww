from __future__ import annotations

try:
    from .events_faults import BUS_NOTHING_DROPPED
except ImportError:
    from events_faults import BUS_NOTHING_DROPPED


def _replay_skips_oldest_missed() -> None:
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
        "sse-replay-skips-oldest-missed": Fault(_replay_skips_oldest_missed, (BUS_NOTHING_DROPPED,)),
    }
