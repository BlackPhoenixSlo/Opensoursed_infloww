"""The full chat sweep cadence's break-it-once faults (service/sweep_cadence.py, whose `tick`
looks `plan` up in its module): lib/faults.py merges `register(Fault)` into FAULTS. The check names
live here and scenarios/2026-11-07-chat-sweep-cadence.py imports them.
"""
from __future__ import annotations

ONE_OPEN = "at most one open full sweep per live Creator after every relay restart and cadence pass"
COLLAPSE = ("a seeded backlog of duplicate full sweeps collapses to its oldest job (the rest cancelled "
            "'duplicate full sweep'); fan_ids jobs untouched")
ANCHOR = ("a new full sweep only once the last one finished >= SWEEP_EVERY_S ago (none while one is recent, "
          "one once it is older); a deactivated or session-dead Creator gets none")
FAILFAST = ("a full sweep that meets a 429 burst after good chats stops at SCRAPE_SWEEP_FAIL_FAST failed reads; "
            "its run is not ok and carries no full_sweep")
DEFER = ("a full sweep's first scrape of a Silent mass-only chat costs one page and no asc page, leaving it "
         "deferred with a NULL cursor; deep chats with a fan message on OF or in the DB get both ends")
BACKFILL_ON_DEMAND = ("a deferred chat's fan reply frame or head read (user or background priority) buys its "
                      "both-ends pages once: one deferred_history job however many triggers, today's rows; every "
                      "head read still reaches OF; no backfill for an untriggered or not-deferred chat")
DEFER_NET = ("the Silent mass-only chats' history pages, sweep plus triggered backfills, stay below the same "
             "workload under SCRAPE_EAGER_HISTORY=1 (each chat at a fan-message deep chat's sweep cost)")


def _sweep_every_pass() -> None:
    """The pre-fix shape in the new loop: every pass enqueues a sweep for every live Creator,
    open job or recent sweep or not (the boot seed ran once per restart, with no dedupe).
    The collapse is unchanged, so only the open-count and cadence checks can see it."""
    import sweep_cadence as sc

    real = sc.plan

    def every_pass(live, open_jobs, swept_recently):
        live = list(live)
        p = real(live, {}, set())
        return sc.Plan(enqueue=p.enqueue, cancel=real(live, open_jobs, swept_recently).cancel)

    sc.plan = every_pass


def _failfast_only_before_first_scan() -> None:
    """The pre-fix stop (service/automations/scrape_chats.py, whose sweep looks
    `_systemic_failure` up in its module): no failure counts as systemic, so the sweep stops
    only on its non-404 failures before the first scraped chat; after one good chat it reads
    every remaining chat into the limit and finishes as a full sweep."""
    from automations import scrape_chats

    scrape_chats._systemic_failure = lambda _e: False


def _history_eager() -> None:
    """Knob SCRAPE_EAGER_HISTORY on (service/automations/scrape_chats.py reads it at call time): every
    first scrape gets today's both-ends backfill, so a Silent mass-only chat costs the deep pages again."""
    import os

    os.environ["SCRAPE_EAGER_HISTORY"] = "1"


def _no_deferred_trigger() -> None:
    """The open / reply / gen_info triggers enqueue nothing: service/webhook_dispatch.py's
    `enqueue_fan_scrape`, which the DM dispatch, the thread_head hook's backfill and gen_info look
    up in its module at call time, claims nothing for source "deferred_history" and returns False;
    the blast-reply scrape is untouched."""
    import webhook_dispatch

    orig = webhook_dispatch.enqueue_fan_scrape

    async def deferred_never(account_id, fan_id, source) -> bool:
        if source == webhook_dispatch.DEFERRED_HISTORY_SOURCE:
            return False
        return await orig(account_id, fan_id, source)

    webhook_dispatch.enqueue_fan_scrape = deferred_never


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-07-chat-sweep-cadence --break (the scenario's FAULT)
        "sweep-enqueued-every-pass": Fault(_sweep_every_pass, (ONE_OPEN, ANCHOR)),
        # slop/run 2026-11-07-chat-sweep-cadence --break --fault=failfast-only-before-first-scan
        "failfast-only-before-first-scan": Fault(_failfast_only_before_first_scan, (FAILFAST,)),
        # slop/run 2026-11-07-chat-sweep-cadence --break --fault=history-eager
        "history-eager": Fault(_history_eager, (DEFER, DEFER_NET)),
        # slop/run 2026-11-07-chat-sweep-cadence --break --fault=no-deferred-trigger
        "no-deferred-trigger": Fault(_no_deferred_trigger, (BACKFILL_ON_DEMAND,)),
    }
