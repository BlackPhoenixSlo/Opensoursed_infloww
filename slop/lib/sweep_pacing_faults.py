"""Background OF walks' faults (lib/faults.py merges `register(Fault)` into FAULTS), for
scenarios/2026-11-05-sweep-pacing.py. The check names live here and the scenario imports them,
so a target can never name a check that does not exist.

  sweep-unpaced        service/of_pacing.py's pacer off: no gap between a Creator's background
                       pages (PAGE_GAP_S = JITTER_S = 0). OF's 429 still retried once, but a
                       Creator's walks drain its bucket (lib/sweep_pacing_wire.py) within a second,
                       retries meet a second 429 and the roster crawls fail: spacing and the counts
                       go red (measured: 5 of 5, small at host load 25-40, medium at 6-99). Noise,
                       no targets (races, measured): no_429_on_user_reads / no_5xx (a person's
                       lookup meeting GROWTH's empty bucket: 2/2 small under load, 0/3 medium) and
                       growth_refresh_walked (which GROWTH walk meets the second 429 first: 2/5);
                       user_read_p95 is a budget.
                       growth_route_not_blocked stays green (no lock is held across a page).
  sweep-no-429-retry   OF's 429 never retried (`retry_after` finds none: the walks' pages and the
                       name fill's lookups). The pacer kept.
"""
from __future__ import annotations

PAGES_SPACED = "pages_spaced"
RETRY_ONCE = "retry_once_per_429"
NO_429_USER = "no_429_on_user_reads"
SKIPS = "prewarm_skips_busy_creators"
GROWTH = "growth_refresh_walked"
GROWTH_ROUTE = "growth_route_not_blocked"
TERMINAL = "terminal_429_keeps_mirror"
COUNTS = "walk_counts_match"
NO_5XX = "no_5xx"
USER_P95 = "user_read_p95"
BG_P95 = "background_lookup_p95"


def _unpaced() -> None:
    import of_pacing
    of_pacing.PAGE_GAP_S = 0.0
    of_pacing.JITTER_S = 0.0


def _no_retry() -> None:
    import of_pacing
    of_pacing.retry_after = lambda _e: None


def register(Fault) -> dict:
    return {
        # slop/run sweep-pacing --break
        "sweep-unpaced": Fault(_unpaced, (PAGES_SPACED, COUNTS)),
        # slop/run sweep-pacing --break --fault=sweep-no-429-retry --baseline=<green run>
        "sweep-no-429-retry": Fault(_no_retry, (RETRY_ONCE, TERMINAL, COUNTS)),
    }
