from __future__ import annotations

STALE_READ_NEVER_CLEARS = "STALE_READ_NEVER_CLEARS"


def _badge_ordering_fence_off() -> None:
    try:
        import badge_reads_decide
    except ImportError:
        badge_reads_decide = None
    if not callable(getattr(badge_reads_decide, "newer_than_ask", None)):
        raise SystemExit("slop: badge-ordering-fence-off needs badge_reads_decide.newer_than_ask (Phase C's "
                         "ordering fence), which is not built here yet")
    badge_reads_decide.newer_than_ask = lambda _at, _asked_at: False


def register(Fault) -> dict:
    return {
        "badge-ordering-fence-off": Fault(_badge_ordering_fence_off, (STALE_READ_NEVER_CLEARS,)),
    }
