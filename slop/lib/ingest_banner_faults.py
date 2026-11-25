from __future__ import annotations

WORDS = "banner_words_a_stopped_and_a_working_walk"


def register(Fault) -> dict:
    return {"ingest-banner-raw-status": Fault(None, (WORDS,), browser=((r"backfill stalled", "backfill_stalled"),))}
