"""The mass-audience-crawl flow's break-it-once faults (service/audience_crawl.py, its mode read at call time by
audience_crawl_decide.knobs): lib/faults.py merges `register(Fault)` into FAULTS. The check names live here and
scenarios/2026-11-08-mass-audience-crawl.py imports them.
"""
from __future__ import annotations

RECORDED_95 = "recorded_95: >= 95 % of recordable mass sends stamped within the compressed deadline"
EXACT_OR_NULL = ("exact_or_null: every stamped audience (churn off) equals OF's recipients at accept; "
                 "Dead-session sends NULL")
PACED = "paced: per Creator, roster pages leave >= the compressed PAGE_GAP_S apart"
SEND_UNSLOWED = "send_unslowed: enqueue / composer POST -> OF accept p95 within budget"
DETACHED = "detached: every automation run returns before its mass run is stamped"
BIG_ROSTER = "big_roster: every recordable send of the > 10k-roster Creator recorded"
PAGE_BOUND = ("page_bound: per Creator, roster calls <= the per-round call bound; the crawl never fetches a "
              "verified Auto_Exclude; the big Creator's sends queued behind its crawl share one round")
RESTART_RECOVERED = ("restart_recovered: the relay stopped with crawls in flight and restarted on the same temp dir; "
                     "every recordable send still inside its deadline stamped after the boot")


def _legacy() -> None:
    """Today's inline, unpaced crawl (`AUDIENCE_CRAWL_MODE=legacy`): stamped inside the run, outside any walk,
    a 429 fails the read, of_paging's 200-page backstop, every exclude list read again, no shared round."""
    import os
    os.environ["AUDIENCE_CRAWL_MODE"] = "legacy"


def _no_boot_recovery() -> None:
    """`audience_crawl.recover_at_boot` does nothing: the sends a restart cut off stay NULL. Applied before
    startup (lib/relay.py `_wire`), on the restarted relay too (same env); server reads the attribute at boot."""
    import audience_crawl

    async def nothing(load_client) -> None:
        return None
    audience_crawl.recover_at_boot = nothing


def register(Fault) -> dict:
    return {
        # slop/run mass-audience-crawl --break (the scenario's FAULT). SEND_UNSLOWED and EXACT_OR_NULL must
        # stay green (read on the noise line). RESTART_RECOVERED: legacy stamps inline (nothing in flight at the
        # stop, nothing cut off) and recovers nothing.
        "audience-crawl-legacy": Fault(_legacy, (RECORDED_95, PAGE_BOUND, PACED, DETACHED, BIG_ROSTER,
                                                 RESTART_RECOVERED)),
        # slop/run mass-audience-crawl --break --fault=no-boot-recovery --baseline=<its green folder>
        "no-boot-recovery": Fault(_no_boot_recovery, (RESTART_RECOVERED,)),
    }
