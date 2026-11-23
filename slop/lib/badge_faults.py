"""Creator badges' break-it-once fault (Phase C's scenario badge-load-elsewhere, 2a): lib/faults.py merges
`register(Fault)` into FAULTS."""
from __future__ import annotations

STALE_READ_NEVER_CLEARS = "STALE_READ_NEVER_CLEARS"


def _badge_ordering_fence_off() -> None:
    """The DA #8 ordering fence is gone: `badge_reads_decide.newer_than_ask` (Phase C's one fence, called by `diff`
    and `replace_set`) always answers False, so a fan message is never newer than the ask and a read sent before it
    counts as clearing it. Nothing else is patched. Patched here, never in service/. Fails loudly while Phase C has
    not built that name: a silent no-op would read as NOT CAUGHT."""
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
        # slop/run badge-load-elsewhere --break --baseline=slop/evidence/<green folder>
        "badge-ordering-fence-off": Fault(_badge_ordering_fence_off, (STALE_READ_NEVER_CLEARS,)),
    }
