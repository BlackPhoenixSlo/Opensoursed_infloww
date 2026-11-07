"""scenarios/2026-11-07-ingest-health-banner.py's fault: lib/faults.py merges `register(Fault)`.

  ingest-banner-raw-status  the banner shows the raw status again (`backfill_stalled`), not its words.
"""
from __future__ import annotations

WORDS = "banner_words_a_stopped_and_a_working_walk"


def register(Fault) -> dict:
    return {"ingest-banner-raw-status": Fault(None, (WORDS,), browser=((r"backfill stalled", "backfill_stalled"),))}
