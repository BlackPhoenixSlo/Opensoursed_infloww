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
  tx-cadence-300       the ledger supervisor back on the old 300 s cadence
                       (transaction_ingest._TICK_INTERVAL_S = 300 in the relay, as
                       INGEST_TICK_INTERVAL_S=300 would set it): the same pages a pass at 3x the
                       passes an hour, so tx_calls_budget goes red. Every page and row unchanged.
  tx-recent-window-ignored  harness side (the scenario sets lib/sweep_pacing_wire.py's
                       `window = False`): OF ignores the ledger's startDate, so a recent walk
                       pages the whole ledger like a full one: tx_calls_budget red, and the relay's
                       guard logs ingest_tx_recent_window_ignored (tx_recent_window_kept
                       red). Every row still lands (walk_counts_match stays green).
  tx-recent-startdate-iso  harness side (the scenario sets lib/sweep_pacing_wire.py's
                       `startdate_iso = True`): the recent walk's startDate reaches OF as an ISO
                       datetime, which OF answers with an empty list (measured): the row added
                       10 h before the recent pass never lands and the relay logs
                       ingest_tx_recent_walk_empty (tx_recent_catches_new_row red).
  tx-backfill-offset-walk  the backfill back on offset paging, complete on an empty page: OF's
                       offset cap reads as the end. DEEP and REACT record complete past 600 rows.
  tx-backfill-complete-on-empty  an empty page ends the walk as complete, marker walk kept:
                       REACT's blank page reads as the end, the rows below it never land.
  tx-backfill-marker-exclusive  markers one second low (ties and the next page's first row skipped).
  tx-backfill-lifetime-on-reread  a re-read row adds its amount to the fan's lifetime again.
  tx-backfill-flips-uncapped  a backfill's old status flips announce as a recent walk's do.
  tx-backfill-uncapped  no per-tick page cap.
  tx-backfill-poll-only-complete  disputes polled only once a backfill is complete: the disputed row
                       REACT's walk puts back stays revenue through the partial tick.
  tx-backfill-poll-every-tick  disputes polled on every tick, whatever moved: the calls bound goes red.
  tx-backfill-gap-unread  a resumed read short of newest_seen reads as if it got there: the walk goes
                       on from its cursor, GAP's rows between the read and newest_seen never land.
  tx-backfill-blank-first-page  a blank first page reads as an empty window: BLANK records complete.
  tx-backfill-failure-counted  a tick that held pages counts its failure: DEEP, its streak at 2, pauses.
  tx-backfill-short-gap-unwalked  a reactivation inside 7 days gets no walk: BLANK, 6 days off, keeps its top 600.
  tx-backfill-crowded  4 backfills at once, the pace measured over CROWD's bucket: a retry's 429 ends a tick.
  tx-backfill-dispute-repolled  the disputes poll ignores a row's status (lib/ledger_faults.py's bug
                       class): every backfill tick deducts the disputed sale again.
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
TX_BUDGET = "tx_calls_budget"
TX_WINDOW = "tx_recent_window_kept"
TX_NEW_ROW = "tx_recent_catches_new_row"
WINDOW_IGNORED = "tx-recent-window-ignored"
STARTDATE_ISO = "tx-recent-startdate-iso"
BF_DROPPED = "tx_backfill_nothing_dropped"
BF_ONCE = "tx_backfill_exactly_once"
BF_LIFETIME = "tx_backfill_lifetime_once"
BF_PARTIAL = "tx_backfill_partial_not_complete"
BF_CALLS = "tx_backfill_calls_bounded"
BF_FRESH = "tx_backfill_fresh_rows_land"
BF_BURST = "tx_backfill_no_flip_burst"
BF_DISPUTE = "tx_backfill_dispute_stands"
BF_GAP = "tx_backfill_gap_rewalked"
BF_SHARED = "tx_backfill_shared_bucket"


def _unpaced() -> None:
    import of_pacing
    of_pacing.PAGE_GAP_S = 0.0
    of_pacing.JITTER_S = 0.0


def _no_retry() -> None:
    import of_pacing
    of_pacing.retry_after = lambda _e: None


def _tx_cadence_300() -> None:
    import transaction_ingest
    transaction_ingest._TICK_INTERVAL_S = 300.0


def _bf_offset_walk() -> None:
    import transaction_ingest as ti
    offsets: dict[int, int] = {}

    def fetch(client, start_date, marker):
        off = offsets.get(id(client), 0)
        offsets[id(client)] = off + 100
        return client.transactions(limit=100, offset=off, start_date=start_date)

    def step(*, rows, has_more, sent_marker, **_kw):
        if rows == 0 or not has_more:
            return ti.BackfillStep("complete", "fault")
        return ti.BackfillStep("next", "fault", sent_marker)

    ti._backfill_fetch, ti.backfill_step = fetch, step


def _bf_complete_on_empty() -> None:
    import transaction_ingest as ti
    real = ti.backfill_step

    def step(*, rows, **kw):
        return ti.BackfillStep("complete", "fault") if rows == 0 else real(rows=rows, **kw)

    ti.backfill_step = step


def _bf_marker_exclusive() -> None:
    import transaction_ingest as ti
    real_step, real_of = ti.backfill_step, ti.marker_of

    def step(**kw):
        got = real_step(**kw)
        return got._replace(marker=got.marker - 1) if got.marker is not None else got

    ti.backfill_step, ti.marker_of = step, lambda at: real_of(at) - 1


def _bf_lifetime_on_reread() -> None:
    import transaction_ingest as ti
    real = ti.plan_page

    def plan(parsed, *a, **kw):
        ops = real(parsed, *a, **kw)
        return [ti.RowOp("patch", op.parsed, op.kind, lifetime_delta=op.parsed["amount_cents"])
                if op.action == "noop" else op for op in ops]

    ti.plan_page = plan


def _bf_flips_uncapped() -> None:
    import transaction_ingest as ti

    class Off:
        def set(self, _v):
            return None

        def reset(self, _t):
            return None

        def get(self):
            return False

    ti._BACKFILL_NEWS_CAPPED = Off()


def _bf_uncapped() -> None:
    import transaction_ingest as ti
    ti._BACKFILL_TICK_PAGES = 1_000_000


def _bf_poll_only_complete() -> None:
    import transaction_chargebacks as cb
    import transaction_ingest as ti
    real = cb.poll_after_walk

    async def poll(account_id, client):
        async with ti.get_session() as s:
            done = (await ti._scan_state(s, account_id)).fully_backfilled
        return await real(account_id, client) if done else None

    cb.poll_after_walk = poll


def _bf_short_gap_unwalked() -> None:
    from datetime import datetime, timedelta

    import transaction_ingest as ti
    real = ti.backfill_after_reactivation

    async def after(account_id, deactivated_at):
        if datetime.utcnow() - deactivated_at <= timedelta(days=ti._ROLLING_WINDOW_DAYS):
            return False
        return await real(account_id, deactivated_at)

    ti.backfill_after_reactivation = after


def _bf_crowded() -> None:
    import transaction_ingest as ti
    ti._BACKFILL_CONCURRENCY = 4


def _bf_dispute_repolled() -> None:
    import dataclasses

    import transaction_chargebacks as cb
    real = cb.plan_chargebacks
    cb.plan_chargebacks = lambda disputes, held: real(disputes, [dataclasses.replace(h, status="cleared") for h in held])


def _bf_poll_every_tick() -> None:
    import transaction_ingest as ti

    class Always(set):
        def __contains__(self, _a):
            return True

    ti._reinstated = Always()


def _bf_gap_unread() -> None:
    import transaction_ingest as ti
    real = ti._backfill_recent_rows

    async def read(*a, **kw):
        got = await real(*a, **kw)
        return "reached" if got == "gap" else got

    ti._backfill_recent_rows = read


def _bf_blank_first_page() -> None:
    import transaction_ingest as ti

    async def real_empty(*_a, **_kw):
        return False

    ti._window_answered_blank = real_empty


def _bf_failure_counted() -> None:
    import transaction_ingest as ti
    real = ti._record_failure

    async def record(account_id, exc, *, progressed=False):
        await real(account_id, exc, progressed=False)

    ti._record_failure = record


def register(Fault) -> dict:
    return {
        # slop/run sweep-pacing --break
        "sweep-unpaced": Fault(_unpaced, (PAGES_SPACED, COUNTS)),
        # slop/run sweep-pacing --break --fault=sweep-no-429-retry --baseline=<green run>
        "sweep-no-429-retry": Fault(_no_retry, (RETRY_ONCE, TERMINAL, COUNTS)),
        # slop/run sweep-pacing --break --fault=tx-cadence-300 --baseline=<green run>
        "tx-cadence-300": Fault(_tx_cadence_300, (TX_BUDGET,)),
        # slop/run sweep-pacing --break --fault=tx-recent-window-ignored --baseline=<green run>
        WINDOW_IGNORED: Fault(None, (TX_BUDGET, TX_WINDOW)),
        # slop/run sweep-pacing --break --fault=tx-recent-startdate-iso --baseline=<green run>
        STARTDATE_ISO: Fault(None, (TX_NEW_ROW,)),
        # slop/run sweep-pacing --break --fault=<name> --baseline=<green run>
        "tx-backfill-offset-walk": Fault(_bf_offset_walk, (BF_DROPPED, BF_PARTIAL)),
        "tx-backfill-complete-on-empty": Fault(_bf_complete_on_empty, (BF_DROPPED, BF_PARTIAL)),
        "tx-backfill-marker-exclusive": Fault(_bf_marker_exclusive, (BF_DROPPED, BF_ONCE)),
        "tx-backfill-lifetime-on-reread": Fault(_bf_lifetime_on_reread, (BF_LIFETIME,)),
        "tx-backfill-flips-uncapped": Fault(_bf_flips_uncapped, (BF_BURST,)),
        "tx-backfill-uncapped": Fault(_bf_uncapped, (BF_CALLS, BF_PARTIAL)),
        "tx-backfill-poll-only-complete": Fault(_bf_poll_only_complete, (BF_DISPUTE,)),
        "tx-backfill-poll-every-tick": Fault(_bf_poll_every_tick, (BF_CALLS,)),
        "tx-backfill-gap-unread": Fault(_bf_gap_unread, (BF_DROPPED, BF_ONCE, BF_LIFETIME, BF_GAP)),
        "tx-backfill-blank-first-page": Fault(_bf_blank_first_page, (BF_DROPPED, BF_ONCE, BF_LIFETIME, BF_PARTIAL)),
        "tx-backfill-failure-counted": Fault(_bf_failure_counted, (BF_DROPPED, BF_ONCE, BF_LIFETIME, BF_PARTIAL)),
        "tx-backfill-short-gap-unwalked": Fault(_bf_short_gap_unwalked, (BF_DROPPED, BF_ONCE, BF_LIFETIME, BF_PARTIAL)),
        "tx-backfill-crowded": Fault(_bf_crowded, (BF_SHARED,)),
        "tx-backfill-dispute-repolled": Fault(_bf_dispute_repolled, (BF_DISPUTE, BF_LIFETIME)),
    }
