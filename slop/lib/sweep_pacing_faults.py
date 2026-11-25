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
TX_RESTART = "tx_restart_keeps_full_schedule"
TX_FAILED_FULL = "tx_failed_full_consumes_period"
TX_PROXY_SPACED = "tx_proxy_pages_spaced"
PROMO_CAP = "promo_cap_once"
PREWARM_SCOPE = "prewarm_scope"


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
    import transaction_backfill as tb
    import transaction_ingest as ti
    offsets: dict[int, int] = {}

    def fetch(client, start_date, marker):
        off = offsets.get(id(client), 0)
        offsets[id(client)] = off + ti._PAGE_LIMIT
        return client.transactions(limit=ti._PAGE_LIMIT, offset=off, start_date=start_date)

    def step(*, rows, has_more, sent_marker, **_kw):
        if rows == 0 or not has_more:
            return ti.BackfillStep("complete", "fault")
        return ti.BackfillStep("next", "fault", sent_marker)

    tb._backfill_fetch, tb.backfill_step = fetch, step


def _bf_complete_on_empty() -> None:
    import transaction_backfill as tb
    import transaction_ingest as ti
    real = tb.backfill_step

    def step(*, rows, **kw):
        return ti.BackfillStep("complete", "fault") if rows == 0 else real(rows=rows, **kw)

    tb.backfill_step = step


def _bf_marker_exclusive() -> None:
    import transaction_backfill as tb
    real_step, real_of = tb.backfill_step, tb.marker_of

    def step(**kw):
        got = real_step(**kw)
        return got._replace(marker=got.marker - 1) if got.marker is not None else got

    tb.backfill_step, tb.marker_of = step, lambda at: real_of(at) - 1


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
    real = ti.write_page

    async def write(account_id, rows, *, capped=False):
        return await real(account_id, rows)

    ti.write_page = write


def _bf_uncapped() -> None:
    import transaction_backfill as tb
    tb._BACKFILL_TICK_PAGES = 1_000_000


def _bf_poll_only_complete() -> None:
    import transaction_chargebacks as cb
    import transaction_ingest as ti
    real = cb.poll_after_walk

    async def poll(account_id, client):
        async with ti.get_session() as s:
            done = (await ti.scan_state(s, account_id)).fully_backfilled
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
    import transaction_backfill as tb
    real = tb._backfill_recent_rows

    async def read(*a, **kw):
        got = await real(*a, **kw)
        return "reached" if got == "gap" else got

    tb._backfill_recent_rows = read


def _bf_blank_first_page() -> None:
    import transaction_backfill as tb

    async def real_empty(*_a, **_kw):
        return False

    tb._window_answered_blank = real_empty


def _bf_failure_counted() -> None:
    import transaction_ingest as ti
    real = ti._record_failure

    async def record(account_id, exc, *, progressed=False, **kw):
        await real(account_id, exc, progressed=False, **kw)

    ti._record_failure = record


def _tx_full_watermark_forgotten() -> None:
    from dataclasses import replace
    from datetime import datetime

    import transaction_ingest as ti
    # Creators this process stamped (the old in-memory dict's keys)
    mine: set[str] = set()
    real_ok, real_fail, real_decide = ti._mark_success, ti._record_failure, ti._decide_mode

    async def ok(account_id, **kw):
        await real_ok(account_id, **kw)
        if kw.get("full_at") is not None:
            mine.add(account_id)

    async def fail(account_id, exc, **kw):
        await real_fail(account_id, exc, **kw)
        if kw.get("full_at") is not None:
            mine.add(account_id)

    async def decide(account_id):
        if account_id in mine:
            return await real_decide(account_id)
        async with ti.get_session() as s:
            row = await s.get(ti.TransactionScanHistory, account_id)
            facts = ti.scan_facts(row) if row is not None else None
        got = ti.decide_mode(facts if facts is None else replace(facts, last_full_at=None), now=datetime.utcnow()).mode
        return "refresh" if got == "recent" else got

    ti._mark_success, ti._record_failure, ti._decide_mode = ok, fail, decide


def _tx_failed_full_not_stamped() -> None:
    import transaction_ingest as ti
    real = ti._record_failure

    async def record(account_id, exc, *, full_at=None, **kw):
        async with ti.get_session() as s:
            row = await s.get(ti.TransactionScanHistory, account_id)
            done = row is not None and row.fully_backfilled
        await real(account_id, exc, full_at=None if done else full_at, **kw)

    ti._record_failure = record


def _tx_full_failure_hidden() -> None:
    import tx_ingest_admin_api as api
    tier = api._tx_ingest_tier
    api._health_status = lambda status, _fails: status
    api._tx_ingest_tier = lambda mins, status, _fails: tier(mins, status, 0)


def _tx_proxy_pacing_bypassed() -> None:
    import of_pacing
    of_pacing._PROXY_PACED_KINDS = frozenset()


def _promo_memo_cleared_on_need_ids() -> None:
    import of_promos
    real = of_promos.paged_of_fetch

    async def relabelled(*a, **kw):
        rows = await real(*a, **kw)
        if rows is not None and rows.stop == of_promos.STOP_NEED:
            # a need_ids stop reads as the real end: the memo clears
            rows.stop = of_promos.STOP_END
        return rows
    of_promos.paged_of_fetch = relabelled


def _prewarm_all_accounts() -> None:
    import link_prewarm
    link_prewarm.prewarm_scope = lambda: "all"


def register(Fault) -> dict:
    return {
        "sweep-unpaced": Fault(_unpaced, (PAGES_SPACED, COUNTS)),
        "sweep-no-429-retry": Fault(_no_retry, (RETRY_ONCE, TERMINAL, COUNTS)),
        "tx-cadence-300": Fault(_tx_cadence_300, (TX_BUDGET,)),
        WINDOW_IGNORED: Fault(None, (TX_BUDGET, TX_WINDOW)),
        STARTDATE_ISO: Fault(None, (TX_NEW_ROW,)),
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
        "tx-full-watermark-forgotten": Fault(_tx_full_watermark_forgotten, (TX_RESTART,)),
        "tx-failed-full-not-stamped": Fault(_tx_failed_full_not_stamped, (TX_FAILED_FULL,)),
        "tx-full-failure-hidden": Fault(_tx_full_failure_hidden, (TX_FAILED_FULL,)),
        "tx-proxy-pacing-bypassed": Fault(_tx_proxy_pacing_bypassed, (TX_PROXY_SPACED,)),
        "promo-memo-cleared-on-need-ids": Fault(_promo_memo_cleared_on_need_ids, (PROMO_CAP,)),
        "prewarm-all-accounts": Fault(_prewarm_all_accounts, (PREWARM_SCOPE,)),
    }
