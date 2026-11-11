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
# fetch diet P2b
INCOMPLETE_NULL = ("incomplete_null: the partial Creator's first send (re-probed; crawled set far under OF's own "
                   "count of it) NULL `incomplete`, sent_count and a ratio under 1.0 on its line, crawl_outcome stamped")
SKIP_NEXT = ("skip_next: the partial Creator's next send NULL `skipped_incomplete` with 0 pages; its roster calls "
             "<= the first crawl's pages + failed less its feed reads")
EXCLUDE_FIRST = ("exclude_first: the broken-exclude-list Creator's sends NULL `truncated`, its list read, each "
                 "repeat proven short by one 200 `GET /lists/{id}` (users_count=150 -> truncated), zero roster calls")
REPEAT_TWICE_NULL = ("repeat_twice_null: the Creator whose fans roster repeats a page twice in a row (re-read once, "
                     "repeated again): every send NULL `truncated`, zero recorded, crawl_outcome stamped")
NO_COUNT_NULL = ("no_count_null: the bare Creator (rosters end normally, its sends missing from OF's mass feed): every "
                 "send NULL `no_count`, sent_count and ratio `-`, stamped, the feed read")


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


def _p2b_off() -> None:
    """Fetch diet P2b reverted inside the crawl (audience_crawl reads audience_crawl_decide's rules at call time):
    no completeness gate (`complete` always records), no skip after a failed verdict, sources read as first seen
    (the pre-P2b order: rosters before a send's exclude lists, so a broken one fails its send after the rosters
    were read). A repeated page is #440's either way (not P2b's): REPEAT_TWICE_NULL is no target."""
    import audience_crawl_decide as acd

    acd.complete = lambda n, sent, k: ("recorded", n / sent if sent else None)
    acd.skips = lambda last, age_s, k: False
    acd.lists_first = lambda by_src: by_src


def register(Fault) -> dict:
    return {
        # slop/run mass-audience-crawl --break (the scenario's FAULT). SEND_UNSLOWED and EXACT_OR_NULL must
        # stay green (read on the noise line). RESTART_RECOVERED: legacy stamps inline (nothing in flight at the
        # stop, nothing cut off) and recovers nothing.
        "audience-crawl-legacy": Fault(_legacy, (RECORDED_95, PAGE_BOUND, PACED, DETACHED, BIG_ROSTER,
                                                 RESTART_RECOVERED)),
        # slop/run mass-audience-crawl --break --fault=no-boot-recovery --baseline=<its green folder>
        "no-boot-recovery": Fault(_no_boot_recovery, (RESTART_RECOVERED,)),
        # slop/run mass-audience-crawl --break --fault=crawl-p2b-off --baseline=<its green folder>: only the P2b
        # checks (their Creators are outside RECORDED_95 / EXACT_OR_NULL / PACED's live set).
        # NO_COUNT_NULL: with no gate its sends record. REPEAT_TWICE_NULL stays green (#440's repeat rule).
        "crawl-p2b-off": Fault(_p2b_off, (INCOMPLETE_NULL, SKIP_NEXT, EXCLUDE_FIRST, NO_COUNT_NULL)),
    }
