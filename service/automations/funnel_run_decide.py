from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import funnel_decide as fd


@dataclass
class Tally:
    discovered: int = 0
    discovery_skipped: int = 0
    advanced: int = 0
    skipped_locked: int = 0
    skipped_cooldown: int = 0
    audience_skipped: int = 0
    errors: int = 0
    cap_hit: bool = False
    key_error: dict | None = None
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
