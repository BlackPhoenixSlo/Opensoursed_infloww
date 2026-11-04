"""service/automations/funnel_run_decide.py — reply_mass_funnel.run()'s tick tally
and the stats dict it returns (automation_runs.stats_json). The fan's status machine
is funnel_decide.decide; every effect it asks run() to perform is counted in `fx`.

No I/O, so it loads and tests without a DB (tests/test_funnel_decide.py).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import funnel_decide as fd


@dataclass
class Tally:
    discovered: int = 0
    discovery_skipped: int = 0   # anchors past the window — walking only, not scanning
    advanced: int = 0            # states that sent a step this tick
    skipped_locked: int = 0
    skipped_cooldown: int = 0
    audience_skipped: int = 0
    errors: int = 0
    cap_hit: bool = False
    key_error: dict | None = None  # missing/rejected key: generated steps stop, static ones send
    # every funnel_decide effect performed, by value (waiting / completed / ...)
    fx: Counter = field(default_factory=Counter)


def summary(t: Tally, runs: int, audience_mode: str, dry_run: bool, model: str) -> dict:
    return {
        "runs": runs,
        "discovered": t.discovered,
        "discovery_skipped": t.discovery_skipped,
        "advanced": t.advanced,
        "waiting": t.fx[fd.Wait()],
        "completed": t.fx[fd.Complete()],
        "converted": t.fx[fd.Convert()],
        "branched": t.fx[fd.Branch()],
        "blocked": t.fx[fd.Block()],
        "skipped_locked": t.skipped_locked,
        "skipped_cooldown": t.skipped_cooldown,
        "audience_mode": audience_mode,
        "audience_skipped": t.audience_skipped,
        "errors": t.errors,
        "cap_hit": t.cap_hit,
        "dry_run": dry_run,
        "model": model,
        **({"key_error": t.key_error} if t.key_error else {}),
    }
