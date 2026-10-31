"""
Automation executor — the background worker that runs the 12 automations
(MASTER_PLAN §5, db_data/08_build_order Phase B, one_section_of_automations).

This is the P3 *harness*: a single async supervisor task per process that
consumes `scheduled_jobs`, evaluates `automation_rules`, and runs one bounded
task per (account, automation_kind) on a tick. Every run writes an
`automation_runs` row (kind, started/finished, status, stats_json, error_text)
which `GET /admin/stats/automation-runs` already reads. Automation 01
`scrape_chats` (automations/scrape_chats.py) is the reference; P4 copies this
pattern for the rest.

It MIRRORS the two existing supervisors — it does not invent a new pattern:
  • server.py `_pump_supervisor` (15s reconcile ticks, per-account tasks,
    crash-restart) spawned in `_start_event_pumps`.
  • transaction_ingest.py `start_supervisor` (per-account asyncio.Lock guards a
    slow tick from stacking; `await asyncio.to_thread(client.<sync OF call>)` so
    the network never blocks the event loop; sleep-at-end so the cadence holds).

Two concurrency invariants the DA caught (MASTER_PLAN §5.6), both real bugs:
  1. **Atomic per-account spend cap** — the daily soft-cap check+spend must be
     atomic, else parallel LLM workers each read "under cap" and overspend. This
     now lives in `llm_client._reserve` (a single INSERT … ON CONFLICT DO UPDATE
     that bumps the rollup only while it stays under the cap) — no Python lock is
     needed. scrape_chats does not spend, so it skips it.
  2. **Per-(account, fan) lease** — A05/A06/A07/A11 can all message the SAME fan
     in overlapping ticks. `acquire_fan_lease()` writes a short-TTL row in
     `fan_lease` (PK (account_id, fan_id)); a live lease blocks every other
     automation from sending to that fan until it expires or is released. One
     bot message per fan per cycle. scrape_chats does not send, so it does not
     lease — but the harness provides + tests the primitive for P4.

The testable seam is `run_once(account_id, kind)`: it executes exactly one
automation run and returns. Tests call it directly — no infinite loop, no
timing, no network (inject a fake client via `_make_client`).

Guardrail (MASTER_PLAN §5): a route handler may only INSERT a `scheduled_jobs`
row (see `enqueue_job`) to trigger work — it must NEVER run an automation
inline. The worker loop is the only thing that calls `run_once`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Awaitable, Callable, assert_never

from sqlalchemy import case, func, select, update

from db.engine import get_session
from db.models import (
    Account,
    AccountAiConfig,
    AccountHealth,
    AutomationRule,
    AutomationRun,
    ScheduledJob,
)

from of_client import OUTBOUND_TEXT_GUARD, OFClient
import client_pool  # the relay's one OFClient pool (fd discipline lives there)
import accounts as account_registry  # platform lookup (OF vs Fansly) for _make_client
from automation_registry import (get_automation, canonical_kind,
                                 kind_family, load_automation_plugins,
                                 failed_plugins)
# The ONE creator-clock resolver (quiet hours). `automations/__init__` is a
# docstring and rhythm imports nothing of ours, so this cannot cycle back through
# the plugins that import THIS module.
from automations import rhythm
import account_health
import account_page  # free-vs-paid page (prime the cache off the recovery probe)

import lane_config
import run_slot
import dispatch_plan
import run_decide
# The fan lease + post-send cooldown (fan_lease.py) and the paced OF write
# (of_write.py) are re-exported as the SAME objects (`ax._write_gates is
# of_write._write_gates`, one `_RUN_WRITE` ContextVar). Rebinding one on ax
# (a test patch) only bites callers that look up `ax.<name>` at call time.
from fan_lease import (  # noqa: F401 — re-exports
    _FAN_COOLDOWN_S,
    _LEASE_TTL_S,
    _sweep_expired_leases,
    acquire_fan_lease,
    fan_on_cooldown,
    release_fan_lease,
    start_fan_cooldown,
)
from of_write import (  # noqa: F401 — re-exports
    _OF_WRITE_GAP_S,
    _RATE_LIMIT_MARK,
    _RUN_WRITE,
    _may_have_sent,
    _tracked,
    _write_gate,
    _write_gates,
    is_rate_limited,
    of_write_paced,
    of_write_with_retry,
)
# The scheduled_jobs queue + automation_runs rows live in job_queue; the names
# used here or read as `ax.<name>` are re-exported as the SAME objects
# (`ax.enqueue_job is job_queue.enqueue_job`, one `_current_rule_id` ContextVar).
# Patch queue internals on job_queue: a patch on ax misses job_queue's own calls.
from job_queue import (  # noqa: F401 — re-exports
    FOLLOWUP_MARK,
    JOB_CANCELLED,
    MISSED_WHILE_OFF_REASON,
    RULE_OFF_REASON,
    _FOLLOW_UP_JOB,
    _automation_employee,
    _by_operator,
    _claim_due_job,
    _current_rule_id,
    _finalize_run,
    _mark_job,
    _mark_job_failure,
    _open_run,
    _park_failed_job,
    _rule_is_live,
    cancel_jobs_missed_while_off,
    current_rule_id,
    enabled_rule_id,
    enqueue_followup,
    enqueue_job,
    rule_last_fired_at,
)

log = logging.getLogger("of-relay.automation")

# ── Knobs ────────────────────────────────────────────────────────────
_TICK_INTERVAL_S = 30          # supervisor cadence (sleep-at-end like tx-ingest)
# Measured 2026-08-26: at 7 accounts this lane runs 23.5% utilized
# (115,879 runs/7d, mean 4.9s), so it saturates near 30 accounts — it is the
# ceiling that binds FIRST as the fleet grows, ahead of the executor and every
# admission lane. Settable from the Concurrency panel for that reason.
# Since 2026-10-24 a run hands its slot back during typing holds
# (run_slot.py), and the soak timing model puts 50 models at a ~1.3 s
# p95 slot wait on these 4 (ADR 0025).
# Applies at restart: the semaphore below is built once when the supervisor starts.
_MAX_CONCURRENT_RUNS = lane_config.resolve("AUTOMATION_MAX_CONCURRENT_RUNS", 4)
# …and with neither the env nor the panel setting it, the supervisor sizes the
# pool from the active Creators every pass (run_slot.auto_runs, ADR 0025):
# adding or deactivating one re-sizes it on the next pass, live.
# Separate lane for long account-wide BULK sweeps (scrape_chats etc.). Proven
# live: the W7 startup seed fired 4 scrape_chats at once, they filled all the run
# slots for ~2 min, and a real-time welcome_chatter_for_info reply was starved ~40s. Bulk kinds
# now use their OWN small semaphore so they can NEVER consume a sender's slot —
# real-time replies stay fast even mid-scrape. Senders keep _run_sem; bulk gets
# _bulk_sem. Independent → at most RUNS+BULK concurrent (fine: per-account OF
# pacing + different accounts/sessions).
_MAX_CONCURRENT_BULK = lane_config.resolve("AUTOMATION_MAX_CONCURRENT_BULK", 2)
# Run slots only an OPERATOR's run may take (a job of an operator kind started
# from the app: a premade mass, a scheduled send, an unsend, a priority mass;
# its scheduled_jobs row carries `created_by_employee_id`, `_OPERATOR_KINDS`). Operator runs also go ahead of every
# queued automation run for the shared slots (run_slot.SlotPool), so the
# operator never waits behind automation; automation never uses these.
# Applies at restart, like the two above.
_OPERATOR_RESERVED_RUNS = lane_config.resolve("AUTOMATION_OPERATOR_RESERVED_RUNS", 2)
# The kinds whose run is a person's own content, sent when they said: only
# these take the operator tier (the slot queue, the write gate, the DM rate
# limiter's pass) when an operator enqueued them. Who clicked does not make a
# run an operator's: Run now on autoreply (or any automation kind) is the
# automation's own work and queues, spaces and rate-limits as automation.
_OPERATOR_KINDS: frozenset[str] = frozenset({
    "scheduled_send", "mass_premade", "unsend_messages", "priority_mass",
})
_BULK_KINDS: frozenset[str] = frozenset({
    "scrape_chats", "process_old_fans",
    "smart_list_sync",
    "priority_mass",   # ~2-min legs of paced per-fan DMs (automations/priority_mass)
})
# Job retries: job_queue._MAX_JOB_ATTEMPTS, run_decide.JOB_RETRY_BACKOFF_S.
# A dead-session account (OF "Wrong user." — the creator got unlinked) pauses
# ALL its automations; a fresh-from-disk client.me() probe runs this often per
# flagged account and the first success resumes them. See account_health.py.
_SESSION_PROBE_INTERVAL_S = 600

# Send priority (W3): lower rank = higher priority. Used by the supervisor to
# DISPATCH higher-priority kinds first within a tick, so on the rare fan overlap
# the more important automation acquires the fan-lease before a lower one does
# (e.g. a brand-new sub gets `send_welcome`, not `send_followup`). NOTE: a LIVE
# lease still blocks EVERY other kind regardless of priority — priority never
# steals a live lease (that would risk a double-message); it only orders who
# tries first. Unknown kinds sort last (after the ranked senders).
_KIND_PRIORITY: dict[str, int] = {
    "send_welcome": 1,
    "welcome_chatter_for_info": 3,
    "send_followup": 4,
    "reply_mass_funnel": 5,
    "send_mass_message": 6,
}
_DEFAULT_PRIORITY = 50

# Rule ids already warned about for carrying an unregistered kind — the skip in
# _materialize_due_rules() fires every tick, the warning only once per process.
# Keyed (rule_id, kind) — not bare id — so a rule EDITED to a different
# unknown kind (or a reused SQLite rowid) warns again instead of staying mute.
_UNKNOWN_RULE_WARNED: set[tuple[int, str]] = set()


def kind_priority(kind: str) -> int:
    """Dispatch rank for an automation kind — lower runs first. See _KIND_PRIORITY.
    Legacy names rank as their live kind (a pre-rename rule row keeps its slot)."""
    return _KIND_PRIORITY.get(canonical_kind(kind), _DEFAULT_PRIORITY)


# ── W7 supervisor wake ───────────────────────────────────────────────
# The supervisor normally drains on a fixed _TICK_INTERVAL_S cadence. W7 makes
# dispatch event-driven: an inbound WS event (webhook_dispatch.on_inbound_message)
# calls wake_supervisor() to drain NOW instead of waiting for the next tick. The
# 30s tick stays as a fallback. The Event is created lazily inside
# automation_supervisor() on the running loop; wake_supervisor() is a no-op until
# then (and during tests, which call run_once directly without a supervisor).
_wake_event: asyncio.Event | None = None


def wake_supervisor() -> None:
    """Signal the supervisor to drain immediately (W7 real-time dispatch).
    No-op when no supervisor is running (e.g. tests). Loop-safe: callers run on
    the same event loop as the supervisor, so a plain .set() suffices."""
    ev = _wake_event
    if ev is not None:
        ev.set()


# Event-driven rule fire (W2 2.10). A rule whose work an event just made due (a
# purchase for `purchase_followup`, a new subscriber for `send_welcome`) is
# POKED: the next materializer pass treats its interval as elapsed, and nothing
# else. Every other gate still holds: the rule must be enabled, there must be no
# due pending/running job for (account, kind) (the materializer's dedupe, so a
# poke never stacks a second job), max_runs, quiet hours. The job is the rule's
# own (rule_id, steps payload), so the sweep's own claims (purchase_followup_claims,
# welcome_sent) stay the per-fan no-double-send guard. A poke landing while the
# sweep RUNS is kept for the pass after it, because that run may have read
# before the event; one landing on a job not yet started is dropped, as that job
# will see it. The interval sweep stays as the backstop.
#
# FLOOR: a poke fires the rule only once its last job is at least
# min(every_seconds, dispatch_plan.POKE_FLOOR_S) old, so a stream of events cannot turn a
# long cadence into a sweep per event. A poke under the floor is spent; the
# cadence covers it. (purchase_followup's cadence IS 60 s, so there a poke only
# saves the wait for the supervisor's next tick.)
_poked: set[tuple[str, str]] = set()


def poke_rule(account_id: Any, kind: str) -> None:
    """An event made (account, kind)'s interval rule due now: materialize it on
    the next pass and wake the supervisor to run that pass. Sync and cheap; a
    no-op beyond the set when no supervisor runs (tests, scripts)."""
    _poked.add((str(account_id), canonical_kind(kind)))
    wake_supervisor()


# ── Non-blocking drain (W7) ──────────────────────────────────────────
# The supervisor must NOT await all runs per tick. A single slow run (observed
# live: a 5.7-min scrape_chats sweep on one account) would block the whole drain
# and stall every real-time webhook dispatch for minutes. Instead each run is
# spawned as a tracked background task bounded by a SHARED semaphore + an
# in-flight (account,kind) guard, and the loop keeps ticking/waking. A slow run
# on one account can no longer freeze a real-time welcome_chatter_for_info reply on another.
_run_sem: run_slot.SlotPool | None = None
_bulk_sem: run_slot.SlotPool | None = None
_inflight_pairs: set[tuple[str, str]] = set()
# When each account last WON a run slot (loop time). Dispatch within a priority
# rank goes least-recently-served first, so with 20 creators sharing the slots
# the one that ran a moment ago queues behind the one that has been waiting —
# instead of account-id order, which put the same high-id creators last on
# every busy tick.
_last_served: dict[str, float] = {}
_inflight_tasks: set = set()


# ── Shutdown drain ───────────────────────────────────────────────────
# A restart is safe at any moment. On SIGTERM the
# relay's SIGTERM handler calls `stop_claiming()` (no new run or send from
# then on) and its shutdown hook calls `drain()` first: every run
# that has already claimed a send is waited for, up to `DRAIN_S`, until the
# send is settled. A pass calls `begin_send()` right before its claim and
# `end_send()` once the send is recorded and the next one planned (what comes
# after, the follow-up script, is not waited for); once draining `begin_send`
# answers False and the pass leaves its planned send as it is, to fire after
# the restart. A run the bound cuts off, or a SIGKILL, is the crash case the
# automation's next pass heals. DRAIN_S sits
# inside the compose `stop_grace_period`, with uvicorn's graceful timeout
# (Dockerfile) before it.
DRAIN_S = float(os.environ.get("RELAY_DRAIN_S", "45"))
_draining = False
_sends_open: dict = {}   # the task that claimed a send -> a future set when it is settled


def begin_send() -> bool:
    """Called by a pass right before it claims a send, with no await between
    this and the claim's own first await. False while the relay drains (do not
    claim); otherwise the current task's send is one `drain()` waits for, until
    `end_send()` or the task's end."""
    if _draining:
        return False
    task = asyncio.current_task()
    if task is not None and task not in _sends_open:
        _sends_open[task] = asyncio.get_running_loop().create_future()
        task.add_done_callback(end_send)
    return True


def stop_claiming() -> None:
    """SIGTERM (server._close_streams_on_term): no new run and no new send from
    here on, so none starts during uvicorn's graceful wait; `drain()` later waits
    for the sends already claimed."""
    global _draining
    _draining = True


def end_send(task=None) -> None:
    """The current task's send is settled: `drain()` stops waiting for it."""
    fut = _sends_open.pop(task or asyncio.current_task(), None)
    if fut is not None and not fut.done():
        fut.set_result(None)


async def drain(timeout_s: float | None = None) -> dict:
    """Shutdown: start no new run, then wait up to `timeout_s` (default
    `DRAIN_S`) for every send that passed `begin_send()` to settle. Returns
    `{"waited", "left", "s"}`: how many there were, how many were still
    running at the bound, and how long it took."""
    stop_claiming()
    pending = {f for f in _sends_open.values() if not f.done()}
    t0 = time.monotonic()
    left: set = set()
    if pending:
        log.info("relay_drain waiting for %d send(s) claimed and not yet settled", len(pending))
        _done, left = await asyncio.wait(pending, timeout=DRAIN_S if timeout_s is None else timeout_s)
    out = {"waited": len(pending), "left": len(left), "s": round(time.monotonic() - t0, 2)}
    (log.warning if left else log.info)("relay_drain done %s", out)
    return out


async def _join_inflight_runs() -> None:
    """Await every in-flight drain task. The SUPERVISOR never calls this (it must
    not block on slow runs); tests use it to wait for spawned runs to finish."""
    if _inflight_tasks:
        await asyncio.gather(*list(_inflight_tasks), return_exceptions=True)

# (The per-account *spend* lock that used to live here is gone: llm_client._reserve
# now does the soft-cap check+spend atomically in one INSERT … ON CONFLICT, so no
# Python-side lock is needed. The per-(account, kind) run lock below stays; it is
# keyed by a stable, small (account, kind) set — accounts don't churn — so it
# doesn't grow unbounded. The write-gate dict lives in of_write.py.)

# Per-(account, kind) lock: stops a slow run from stacking with the next tick.
# Same idea as tx-ingest's per-account tick lock, scoped to the automation kind
# (scrape and welcome_chatter_for_info for one account can run concurrently; two scrapes can't).
_run_locks: dict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)


# ── Tiny parsing helpers (local copies — same house pattern as ───────
#    transaction_ingest.py / event_transcoder.py each keeping their own) ─

def _to_cents(price: Any) -> int:
    """OF prices arrive as floats like 9.99 → 999 cents. 0/None/'' → 0."""
    try:
        if price is None or price == "":
            return 0
        return int(round(float(price) * 100))
    except Exception:
        return 0


from isotime import parse_iso as _parse_iso  # noqa: E402 — OF ISO 8601 → naive UTC (callers use ax._parse_iso)


def _media_ids(media: list | None) -> list[int]:
    """Pluck integer media ids; skip anything non-int."""
    if not isinstance(media, list):
        return []
    out: list[int] = []
    for m in media:
        mid = (m or {}).get("id") if isinstance(m, dict) else None
        if isinstance(mid, int):
            out.append(mid)
        elif isinstance(mid, str) and mid.isdigit():
            out.append(int(mid))
    return out


_HTML_OPEN = "<"


def _strip_html(s: str | None) -> str:
    """Cheap tag-stripper for inbox previews (OF wraps bodies in <p>…</p>)."""
    if not s:
        return ""
    if _HTML_OPEN not in s:
        return s.strip()
    import re
    return re.sub(r"<[^>]+>", "", s).strip()


# ── scheduled_jobs queue (the queue itself: job_queue.py) ─────────────

async def _due_job_pairs() -> list[dispatch_plan.Pair]:
    """Distinct (account_id, kind) over all pending, due jobs — the supervisor
    spawns one bounded run per pair per tick — and whether an operator started
    one of them (`_by_operator`) of an operator kind (`_OPERATOR_KINDS`),
    which puts the run in the operator tier. A deactivated Creator's jobs stay
    pending, unspawned; activating it cancels the ones that fell due meanwhile
    (`cancel_jobs_missed_while_off`) and runs the rest."""
    now = datetime.utcnow()
    off = await account_health.deactivated_ids()
    auto_emp = await _automation_employee()
    async with get_session() as s:
        rows = (
            await s.execute(
                select(ScheduledJob.account_id, ScheduledJob.kind,
                       func.max(case((_by_operator(auto_emp), 1), else_=0)))
                .where(
                    ScheduledJob.status == "pending",
                    ScheduledJob.run_at <= now,
                )
                .group_by(ScheduledJob.account_id, ScheduledJob.kind)
            )
        ).all()
    return [dispatch_plan.Pair(r[0], r[1], bool(r[2]) and canonical_kind(r[1]) in _OPERATOR_KINDS)
            for r in rows if r[0] not in off]


# Accounts already warned about "quiet hours set, but no clock to evaluate them in".
# The materializer runs every 30s, so this is the difference between one honest
# warning and a log nobody can read. Process-local by design: a restart re-warns,
# which is when someone is looking anyway.
_QUIET_HOURS_NO_CLOCK_WARNED: set[str] = set()


async def _account_clock(s, account_id, offsets: dict, now: datetime) -> int | None:
    """The account's creator-local offset in minutes (None = no clock), cached in `offsets`
    for the pass. Through the ONE resolver, not the raw column — see
    dispatch_plan.in_quiet_hours. Both clock columns are read so a zone-only account still
    has a band. Named, because the SELECT order and the resolver's argument order are
    deliberately crossed."""
    if account_id not in offsets:
        row = (await s.execute(
            select(AccountAiConfig.utc_offset, AccountAiConfig.timezone)
            .where(AccountAiConfig.account_id == account_id)
        )).first()
        acct_off, acct_tz = (row[0], row[1]) if row else (None, None)
        offsets[account_id] = rhythm.tz_offset_for(acct_tz, acct_off, now)
    return offsets[account_id]


async def _pair_busy(s, rule: AutomationRule, now: datetime) -> dispatch_plan.Busy | None:
    """The status of a DUE pending/running job of the rule's (account, kind), or None:
    the materializer's one-job-per-(account, kind) gate. Read in the session the pass adds
    its jobs to, so a second rule of the pair sees the first one's job (autoflush). We only
    count jobs that are due now (run_at <= now): a future-dated one-shot (e.g.
    auto_stories' delete-later cleanup, which shares the `unsend_messages` kind) must NOT
    block a recurring rule from materializing its own hourly job — otherwise the rule is
    starved for as long as any future cleanup sits pending."""
    return (
        await s.execute(
            select(ScheduledJob.status)
            .where(
                ScheduledJob.account_id == rule.account_id,
                # kind_family, matching what this loop MINTS (canonical)
                # and what a pre-0062 row may still carry (legacy) — a
                # legacy rule must see the canonical job it created
                # last tick, or a backlog stacks a duplicate per tick.
                ScheduledJob.kind.in_(kind_family(rule.kind)),
                ScheduledJob.status.in_(("pending", "running")),
                ScheduledJob.run_at <= now,
                ~_FOLLOW_UP_JOB,
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def _materialize_due_rules() -> int:
    """Turn due `automation_rules` into `scheduled_jobs` rows (the uniform path
    — rules never execute inline, they only enqueue). Conservative: handles a
    `trigger_json` of `{"every_seconds": N}`, enqueues only when the rule's last
    run is older than N (or an event poked it, see `poke_rule`) AND no pending
    job for (account, kind) already exists.
    A malformed rule is logged + skipped, never fatal. Returns jobs enqueued."""
    load_automation_plugins()  # runners self-register on import; idempotent
    now = datetime.utcnow()
    enqueued = 0
    # This pass consumes the pokes made so far (see poke_rule); a poke made
    # while it runs waits for the next pass. No await between copy and clear.
    poked = set(_poked)
    _poked.clear()
    offsets: dict[str, int | None] = {}   # account_id → creator-local MINUTES (quiet hours)
    async with get_session() as s:
        rules = (
            await s.execute(
                select(AutomationRule).where(AutomationRule.is_enabled.is_(True))
            )
        ).scalars().all()

        for rule in rules:
            # A rule whose kind has no registered runner can only manufacture an
            # unknown-kind ERROR run every tick (run_once refuses it) — a retired
            # engine's leftover rule must go inert, not noisy. Checked against
            # the runner REGISTRY (the same source run_once dispatches from),
            # never a hand-kept kind list, so it stays true by construction.
            #
            # UNLESS the kind's module FAILED TO IMPORT this process: that is a
            # sending engine that vanished, not a retirement, and it must stay
            # LOUD — fall through, let the job materialize, and run_once writes
            # a status=error run row every tick where the ops surfaces show it.
            # (Kinds are module basenames by convention; a failed module's
            # secondary kinds still go quiet here — acceptable, the primary
            # kind raises the alarm for the whole module.)
            if get_automation(rule.kind) is None:
                failed = rule.kind in failed_plugins()
                if (rule.id, rule.kind) not in _UNKNOWN_RULE_WARNED:
                    _UNKNOWN_RULE_WARNED.add((rule.id, rule.kind))
                    if failed:
                        log.error(
                            "automation_rule_kind_import_failed rule_id=%s account=%s"
                            " kind=%s — plugin crashed on import; materializing so"
                            " the error runs stay visible",
                            rule.id, rule.account_id, rule.kind,
                        )
                    else:
                        log.warning(
                            "automation_rule_unknown_kind rule_id=%s account=%s kind=%s"
                            " — rule skipped (no registered runner)",
                            rule.id, rule.account_id, rule.kind,
                        )
                if not failed:
                    continue
            try:
                trigger = json.loads(rule.trigger_json or "{}")
            except Exception:
                log.warning("automation_rule_bad_trigger rule_id=%s", rule.id)
                continue
            trig = dispatch_plan.parse_trigger(trigger)
            if trig is None:
                continue  # neither an interval nor clock trigger — nothing to do

            # The facts dispatch_plan.plan_rule decides on, read in the pass's session.
            # Already a DUE job for this (account, kind)? Don't pile on (see _pair_busy).
            pair = (str(rule.account_id), canonical_kind(rule.kind))
            pending = await _pair_busy(s, rule, now)

            # Cadence anchor for BOTH the interval and clock triggers: the last
            # time THIS rule enqueued a job (rule_id == rule.id), NOT the last run
            # of the kind. `unsend_messages` (and other kinds) double as one-shot
            # actions — auto_stories' delete-later cleanup, the "Unsend this"
            # button, test drivers — all of which write AutomationRun rows for the
            # same (account, kind). Anchoring the "is it due?" check on the kind's
            # last *run* let those one-shots reset the rule's clock every few
            # minutes: an interval rule whose period (e.g. 1h) outlasts the
            # one-shot cadence NEVER became due, and a clock rule's daily slot got
            # marked "already ran" by an unrelated same-kind run. Anchoring on the
            # rule's own jobs decouples both. Its FOLLOW-ON jobs (drips /
            # resends, see enqueue_followup) also carry rule_id but are not the
            # rule firing — they must not push its next fire back.
            last_rule_job_at = await rule_last_fired_at(s, rule.id)

            # ── run-limit ("how many times to run") ──────────────────────
            # Count this (account, kind)'s prior runs (only for a rule with a
            # max_runs); the plan disables the rule once it has fired that often.
            run_count = None
            if trig.max_runs is not None:
                run_count = (
                    await s.execute(
                        select(func.count())
                        .select_from(AutomationRun)
                        .where(
                            AutomationRun.account_id == rule.account_id,
                            # run rows are written canonical (run_once), so a
                            # legacy-kind rule must count under the live name
                            AutomationRun.kind == canonical_kind(rule.kind),
                        )
                    )
                ).scalar_one()

            acct = rule.account_id
            plan = dispatch_plan.plan_rule(
                trig, busy=pending, poked=pair in poked, last_fired=last_rule_job_at,
                run_count=run_count, quiet_hours_json=rule.quiet_hours_json, now=now)
            # ── quiet hours (opt-in; default off) ────────────────────────
            # A due rule inside its creator-local quiet band does NOT enqueue this
            # tick — it'll materialize on the first tick after the band ends (it's
            # still "due" then — no job was enqueued). Unset/[] = fires 24/7. The
            # account's clock is read only here: busy / capped / not-due rules never
            # reach it.
            if isinstance(plan, dispatch_plan.CheckQuiet):
                plan = dispatch_plan.quiet_plan(
                    plan.band, await _account_clock(s, acct, offsets, now), now)
            match plan:
                case dispatch_plan.Repoke():
                    _poked.add(pair)   # that run may predate the event: fire once more after it
                    continue
                case dispatch_plan.Skip(reason="quiet_hours"):
                    log.info("automation_rule_quiet_hours rule_id=%s account=%s kind=%s",
                             rule.id, acct, rule.kind)
                    continue
                case dispatch_plan.Skip():
                    continue
                case dispatch_plan.Disable(runs=runs, limit=limit):
                    rule.is_enabled = False
                    log.info("automation_rule_run_limit_reached rule_id=%s runs=%s/%s",
                             rule.id, runs, limit)
                    continue
                case dispatch_plan.Enqueue(no_clock=True):
                    # Quiet hours are creator-LOCAL, so an account with no clock has
                    # no band — `dispatch_plan.quiet_plan` owns that call (the rule
                    # fires); this only narrates it, ONCE per account per process. The
                    # loop runs every 30s forever, and a warning repeated 2,880 times a
                    # day is one nobody reads.
                    if acct not in _QUIET_HOURS_NO_CLOCK_WARNED:
                        _QUIET_HOURS_NO_CLOCK_WARNED.add(acct)
                        log.warning("automation_rule_quiet_hours_no_clock rule_id=%s "
                                    "account=%s kind=%s — no clock on the account, so the "
                                    "band cannot apply and this rule fires 24/7. Set it in "
                                    "the Brain (Creator clock).", rule.id, acct, rule.kind)
                case dispatch_plan.Enqueue():
                    pass
                case _:
                    assert_never(plan)

            s.add(
                ScheduledJob(
                    account_id=rule.account_id,
                    # Canonical even for a legacy-kind rule row: new job rows
                    # never mint a retired token, so only the rule row itself
                    # is left for migration 0062 to rename.
                    kind=canonical_kind(rule.kind),
                    payload_json=rule.steps_json or "{}",
                    run_at=now,
                    status="pending",
                    rule_id=rule.id,
                )
            )
            enqueued += 1
    if enqueued:
        log.info("automation_rules_materialized count=%d", enqueued)
    return enqueued


# ── Client seam ──────────────────────────────────────────────────────
# Automation 01 scrape_chats lives in automations/scrape_chats.py; it reads
# this seam as `ax._make_client` at call time, so a patch here still bites.


def _make_client(account_id: str) -> OFClient:
    """Client construction seam for the automation lane. Tests override this to
    inject a fake (no network, no session files). Kept tiny so the override
    surface is one name.

    Clients are pinned per account — see service/client_pool.py for why (an
    OFClient per call was an fd per call, and it took the relay to EMFILE).

    Platform branch: mirrors server._load_client. A Fansly account gets the
    OF-shaped shim; without this the executor built an OFClient for an account
    that has no OF session, so every automation on a Fansly account — including
    the `scheduled_send` that fires a chatter's deferred DM — died on
    FileNotFoundError, retried, and left the ghost bubble reading "sending now…"
    forever. The two lanes must resolve a client the same way or the HTTP routes
    work while the executor silently does not."""
    if account_registry.get_platform(account_id) == "fansly":
        import fansly_backend
        return fansly_backend.get_client(account_id)
    return client_pool.get(account_id)


# Registry lives in automation_registry.py. Every automation — `scrape_chats`
# included (automations/scrape_chats.py) — is one file under service/automations/
# that self-registers via @register — NO edit to this file, so they can be built
# in parallel without colliding on a shared dict (load_automation_plugins finds
# scrape_chats by walking the package, like the rest).

# scrape_chats ties back here two ways:
# - the import at the bottom of this module: `import automation_executor` alone
#   registers it (test_p4_pre relies on that);
# - __getattr__ below (PEP 562): reads of the moved names still taken from here
#   (messages.py's `from automation_executor import _scrape_one_chat, …`, tests)
#   forward there. Its import stays lazy: when scrape_chats is imported first it
#   imports this module before the bottom line has run.
# Reads only: patch on automations.scrape_chats, not ax — its calls look names up there.
_SCRAPE_NAMES: frozenset[str] = frozenset({
    "_scrape_one_chat", "_upsert_fan_identity",
    "_SCRAPE_PAGE_SIZE", "_SCRAPE_MAX_PAGES",
})


def __getattr__(name: str) -> Any:
    if name in _SCRAPE_NAMES:
        from automations import scrape_chats  # lazy: it imports this module
        return getattr(scrape_chats, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ── Dead-session pause (see account_health.py) ──────────────────────

# account_id → time.monotonic() of the last "paused" log line. The gate in
# run_once fires every tick for every due (account, kind) pair, so without a
# throttle a paused account would log twice a minute per kind.
_session_skip_log_last: dict[str, float] = {}
_session_probe_task: asyncio.Task | None = None


def _log_session_dead_skip(account_id: str, kind: str) -> None:
    now = time.monotonic()
    last = _session_skip_log_last.get(account_id)
    if last is not None and now - last < _SESSION_PROBE_INTERVAL_S:
        return
    _session_skip_log_last[account_id] = now
    # Don't quote a probe period here: it WIDENS with how long the account has
    # been dead (account_health._PROBE_BACKOFF), so a fixed number would read as
    # a promise this line cannot keep for a month-dead account.
    log.info(
        "automation_paused_session_dead account=%s kind=%s — runs skipped "
        "until the recovery probe or a re-capture clears it",
        account_id, kind,
    )


async def _probe_dead_sessions() -> None:
    """Recovery sweep: for each flagged account due under the backoff ladder
    (account_health.probe_interval_s — _SESSION_PROBE_INTERVAL_S while the death
    is fresh, widening toward 6-hourly once it is a week old), try a
    fresh-from-disk `client.me()` — evict
    first, because a re-captured session on disk must be picked up. Evicting
    (rather than bypassing the pool) is load-bearing: a probe that proved the
    session healthy while automations kept the stale pooled client would clear
    the flag, fail, and re-flag forever. The first success clears the flag;
    its parked jobs run on the next tick."""
    try:
        aids = await account_health.due_probe_ids(_SESSION_PROBE_INTERVAL_S)
        for aid in aids:
            await account_health.stamp_probe(aid)
            try:
                client_pool.evict(aid)
                client = _make_client(aid)
                me = await asyncio.to_thread(client.me)
            except Exception as e:
                log.info("session_probe_still_dead account=%s err=%s", aid, repr(e)[:200])
                continue
            # Free-run: this probe already holds the profile the paid-post gate
            # needs, and a recovered account is exactly when it went stale.
            account_page.prime(aid, me)
            if await account_health.clear_session_dead(aid):
                log.info("account_session_recovered account=%s — automations resume", aid)
    except Exception:
        log.warning("session_probe_sweep_failed", exc_info=True)


async def _outbound_guard(account_id: str):
    """This run's outbound word guard (of_client.OUTBOUND_TEXT_GUARD): the
    Agency's sensitive words for this account, in block mode. Every automation send and post passes it, whichever
    helper it went through — the per-sender filter_banned calls stay as the
    whole-turn check, this is the floor under the senders that never had one
    (posts and S4S). None when nothing is listed."""
    from automations import _wordfilter  # lazy: _common's import graph reaches the plugins
    try:
        return _wordfilter.outbound_guard(*await _wordfilter.load_banned_words(account_id))
    except Exception:
        log.warning("outbound_guard_load_failed account=%s", account_id, exc_info=True)
        return None


# ── The testable seam: run exactly one automation run ────────────────

async def run_once(
    account_id: str,
    kind: str,
    *,
    payload: dict | None = None,
    job_id: int | None = None,
    job_only: bool = True,
) -> dict:
    """Execute exactly one automation run for (account_id, kind) and return a
    summary dict. No loop, no sleeping, no supervisor — tests call this
    directly.

    Job binding: when neither `payload` nor `job_id` is given, the earliest due
    `scheduled_jobs` row for (account, kind) is CLAIMED and its payload used (so
    "enqueue a scrape job → run_once → it executes" works). A test may also pass
    an explicit `payload` to bypass the queue. Every run writes an
    `automation_runs` row; a bound job is marked done/error/requeued.

    `job_only` (default): with no `payload`/`job_id` and NOTHING to claim, skip
    (`reason=no_job`) instead of running an unbound empty-payload sweep. That
    empty run used to fire whenever the job was gone by claim time — cancelled
    because its rule was switched off, or already claimed by the supervisor
    (fans.py kicks a run_once right after enqueueing). Pass `job_only=False`
    to get the old "run with {} anyway" behaviour.

    Rule binding: while a claimed job of a LIVE rule (`scheduled_jobs.rule_id`)
    runs, `current_rule_id()` returns that rule, so follow-on jobs the automation
    enqueues (`enqueue_followup`: a drip, a resend) carry it and die with it. A
    follow-on, or a job tagged by a payload `_rule_id` (a real-time job queued
    under a rule — webhook_dispatch), is dropped at claim time if that rule is
    now OFF or gone.
    """
    load_automation_plugins()  # ensure P4 plugin modules under service/automations/ self-registered
    # Canonical from here down: the run row, the (account, kind) locks and the
    # stats vocabulary all speak the live name even when the caller (a legacy
    # rule/job row migration 0062 hasn't rewritten) still says the old one.
    kind = canonical_kind(kind)
    fn = get_automation(kind)
    if fn is None:
        # Truthful per-tick artifact: a plugin that CRASHED on import is not a
        # retired kind, and the run row is what the ops surfaces show.
        err = (f"automation plugin failed to import: {kind}"
               if kind in failed_plugins()
               else f"unknown automation kind: {kind}")
        log.warning("automation_unknown_kind account=%s kind=%s", account_id, kind)
        # CONSUME the bound job (error, no retry): a leftover pending job for a
        # retired kind would otherwise re-dispatch this exact branch every 30s
        # tick, forever — error-run noise plus automation_runs bloat. Loudness
        # for a FAILED-IMPORT kind is unharmed: its rule keeps materializing a
        # fresh job each tick (see _materialize_due_rules), so each tick still
        # errors once, visibly, while a truly retired kind errors once and
        # goes quiet.
        if payload is None and job_id is None:
            claimed = await _claim_due_job(account_id, kind)
            job_id = claimed.id if claimed is not None else None
        run_id = await _open_run(account_id, kind)
        status, job_status, err = run_decide.outcome("unknown_kind", None, err)
        await _finalize_run(run_id, status, None, err, job_id=job_id, job_status=job_status)
        return {"status": "error", "reason": "unknown_kind", "run_id": run_id}

    # Don't stack a second run of the same (account, kind) over a slow one.
    lock = _run_locks[(account_id, kind)]
    if lock.locked():
        return {"status": "skipped", "reason": "in_flight"}

    # Dead-session account (OF "Wrong user." — creator got unlinked): paused
    # wholesale. Don't claim the job (it stays pending and simply runs on the
    # first tick after the session recovers) and don't write a run row (one
    # per 30s tick per kind would be pure noise). See account_health.py.
    # A deactivated Creator (Creators › ⋮ › Deactivate) parks the same way, for
    # the direct callers that don't come through _due_job_pairs.
    try:
        if await account_health.is_session_dead(account_id):
            _log_session_dead_skip(account_id, kind)
            return {"status": "skipped", "reason": "session_unlinked"}
    except Exception:
        log.warning("session_dead_check_failed account=%s", account_id, exc_info=True)
    try:
        if await account_health.is_deactivated(account_id):
            return {"status": "skipped", "reason": "account_deactivated"}
    except Exception:
        log.warning("deactivated_check_failed account=%s", account_id, exc_info=True)

    # Again, with no await before the acquire: the checks above awaited, and
    # two raw kinds with one canonical_kind (a legacy alias and its live name
    # are two `_inflight_pairs` entries) could both have passed the first
    # check. The loser must return here, not queue on the lock: queued, it
    # would pin a run slot while the winner may need a slot back to finish.
    if lock.locked():
        return {"status": "skipped", "reason": "in_flight"}
    async with lock:
        rule_id: int | None = None
        if payload is None and job_id is None:
            claimed = await _claim_due_job(account_id, kind)
            if claimed is not None:
                payload = run_decide.parse_payload(claimed.payload_json)
                job_id = claimed.id
                # Drop-or-bind rules: run_decide.bind_claim; the liveness read stays here.
                check = run_decide.tagged_rule(payload, claimed.rule_id) or claimed.rule_id
                live = None
                if check is not None:
                    async with get_session() as s:
                        live = await _rule_is_live(s, check)
                match claim := run_decide.bind_claim(claimed.payload_json, claimed.rule_id, live):
                    case run_decide.Drop(rule_id=tagged):
                        await _mark_job(job_id, JOB_CANCELLED, RULE_OFF_REASON)
                        log.info("automation_job_dropped_rule_off account=%s "
                                 "kind=%s job=%s rule=%s",
                                 account_id, kind, job_id, tagged)
                        return {"status": "skipped", "reason": "rule_disabled",
                                "job_id": job_id}
                    case run_decide.Bind(rule_id=bound):
                        # Only a LIVE rule's run hands its id to follow-ons: Run-now on a
                        # disabled rule behaves as a one-shot (its drip is not dropped).
                        rule_id = bound
                    case _:
                        assert_never(claim)
            elif job_only:
                return {"status": "skipped", "reason": "no_job"}
        payload = payload or {}

        run_id = await _open_run(account_id, kind)
        t0 = time.monotonic()
        rule_token = _current_rule_id.set(rule_id)
        write = run_decide.RunWrites()   # of_write_paced keeps it per attempt
        write_token = _RUN_WRITE.set(write)
        once = run_decide.sends_once(kind)
        from automations._wordfilter import OutboundWordsBlocked  # lazy: see _outbound_guard
        guard = await _outbound_guard(account_id)
        guard_token = OUTBOUND_TEXT_GUARD.set(guard)
        try:
            ran = "ok"
            try:
                stats = await fn(account_id, payload, run_id=run_id) or {}
            except OutboundWordsBlocked:
                # The sender let a word-guard block abort the run: its own stats
                # died with it, the guard's summary below is what is left. Never
                # an error to retry: the text won't get cleaner on a re-fire.
                stats = {}
                ran = "words_blocked"
            stats["duration_ms"] = int((time.monotonic() - t0) * 1000)
            # One rule whether the sender let the block propagate or caught it
            # per fan: the guard's summary in the stats, `skipped` iff it blocked
            # something and let nothing through.
            guard_status = None
            if guard is not None and guard.blocked:
                stats.update(guard.summary())
                guard_status = guard.run_status()
            status, job_status, _ = run_decide.outcome(ran, guard_status)
            await _finalize_run(run_id, status, stats, None, job_id=job_id, job_status=job_status)
            if status == "skipped":
                log.info("automation_run_skipped account=%s kind=%s run_id=%s job=%s "
                         "blocked word(s) %r", account_id, kind, run_id, job_id, guard.hits)
                return {"status": "skipped", "reason": "sensitive_words",
                        "run_id": run_id, "job_id": job_id, **stats}
            log.info(
                "automation_run_ok account=%s kind=%s run_id=%s job=%s stats=%s",
                account_id, kind, run_id, job_id, stats,
            )
            return {"status": "ok", "run_id": run_id, "job_id": job_id, **stats}
        except asyncio.CancelledError:
            # Shutdown / supervisor cancel: park the run, requeue the job (a
            # one-shot OF may have taken: 'error', never resent).
            status, job_status, err = run_decide.outcome(
                "cancelled", None, "cancelled", once=once, wrote=write.state)
            _log_parked(job_status, account_id, kind, run_id, job_id, write.state)
            await _finalize_run(run_id, status, None, err,
                                job_id=job_id, job_status=job_status)
            raise
        except Exception as e:
            err = repr(e)[:2000]
            log.warning(
                "automation_run_failed account=%s kind=%s run_id=%s",
                account_id, kind, run_id, exc_info=True,
            )
            dead_reason = account_health.is_session_dead_error(e)
            if dead_reason:
                try:
                    if await account_health.mark_session_dead(account_id, dead_reason):
                        log.warning(
                            "account_session_dead account=%s kind=%s reason=%s — "
                            "pausing this account's automations until the session probe recovers",
                            account_id, kind, dead_reason,
                        )
                except Exception:
                    log.warning("mark_session_dead_failed account=%s", account_id, exc_info=True)
            status, job_status, err = run_decide.outcome(
                "exception", None, err, once=once, wrote=write.state)
            _log_parked(job_status, account_id, kind, run_id, job_id, write.state)
            await _finalize_run(run_id, status, None, err, job_id=job_id, job_status=job_status)
            return {"status": "error", "run_id": run_id, "job_id": job_id, "error": err}
        finally:
            OUTBOUND_TEXT_GUARD.reset(guard_token)
            _RUN_WRITE.reset(write_token)
            _current_rule_id.reset(rule_token)


def _log_parked(job_status: str, account_id: str, kind: str, run_id: int,
                job_id: int | None, wrote: str) -> None:
    """A failed run's job parked 'error' (run_decide.outcome: a one-shot OF may have taken)."""
    if job_status == "error":
        log.warning("automation_job_parked_may_have_sent account=%s kind=%s run_id=%s "
                    "job=%s write=%s", account_id, kind, run_id, job_id, wrote)


# ── Supervisor ───────────────────────────────────────────────────────

async def _reconcile_orphans() -> None:
    """Boot-time self-heal. A fresh process owns ZERO in-flight work, so any row
    still marked 'running' was orphaned by the previous process's restart/crash:
      • a stuck `ScheduledJob.status='running'` makes _materialize_due_rules skip
        that (account, kind) forever — it looks like work is still in progress, so
        the rule silently stops materializing new jobs (a real clog);
      • a stuck `AutomationRun.status='running'` shows as forever-running in the UI
        and inflates the max_runs count (cosmetic).
    Park a one-shot send (run_decide.one_shot_family: OF may already have taken it,
    and nothing records whether its write started) 'error', ORPHAN_REASON, never sent
    twice; requeue every other job (the work never finished). Mark the runs
    interrupted. Idempotent; the supervisor awaits it before its first tick. A
    direct run_once (e.g. a slop hook) may claim a job before it ends: such a job is
    'running' too, so the heal treats it as orphaned (slop scenarios wait for the
    `reconciled_orphans` line before their first pass)."""
    now = datetime.utcnow()
    running = ScheduledJob.status == "running"
    async with get_session() as s:
        parked = await s.execute(
            update(ScheduledJob)
            .where(running, ScheduledJob.kind.in_(run_decide.one_shot_family()))
            .values(status="error", last_error=run_decide.ORPHAN_REASON)
        )
        jobs = await s.execute(update(ScheduledJob).where(running).values(status="pending"))
        runs = await s.execute(
            update(AutomationRun)
            .where(AutomationRun.status == "running")
            .values(status="error", completed_at=now,
                    error_text="interrupted (relay restart)")
        )
    # Always logged: a scenario waits for this line before its first pass.
    log.info("reconciled_orphans requeued_jobs=%s parked_jobs=%s interrupted_runs=%s",
             jobs.rowcount, parked.rowcount, runs.rowcount)


async def _active_models() -> int:
    """Creators on the relay that are not deactivated."""
    off = select(AccountHealth.account_id).where(AccountHealth.deactivated_at.is_not(None))
    async with get_session() as s:
        return int((await s.execute(
            select(func.count()).select_from(Account).where(Account.id.not_in(off))
        )).scalar_one())


async def _size_run_slots(pool: run_slot.SlotPool) -> None:
    """Size the run slots from the active Creators (run_slot.auto_runs) unless
    the env or the panel sets AUTOMATION_MAX_CONCURRENT_RUNS. The panel shows
    the auto size as the knob's default and live value, so nothing reads as a
    pending restart."""
    knob = "AUTOMATION_MAX_CONCURRENT_RUNS"
    if lane_config.overridden(knob):
        return
    models = await _active_models()
    n = run_slot.auto_runs(models)
    if n != pool.n:
        log.info("automation_run_slots_resized from=%d to=%d active_models=%d", pool.n, n, models)
        pool.resize(n)
    lane_config.resolve(knob, n)
    lane_config.record_live(knob, n)


async def _drain_due_jobs_once() -> None:
    """One supervisor pass: materialize due rules → jobs, sweep expired leases,
    then spawn ONE bounded `run_once` per due (account, kind) pair. Bounded by
    `_MAX_CONCURRENT_RUNS`; the per-(account, kind) lock inside run_once keeps a
    slow run from stacking with the next tick."""
    try:
        await _materialize_due_rules()
    except Exception:
        log.warning("automation_rule_materialize_failed", exc_info=True)
    try:
        await _sweep_expired_leases()
    except Exception:
        log.warning("automation_lease_sweep_failed", exc_info=True)

    # Dead-session recovery probe — detached so a slow OF round-trip can't
    # stall dispatch; internally rate-limited per account, so spawning it
    # every tick is a no-op between probe windows.
    global _session_probe_task
    if _session_probe_task is None or _session_probe_task.done():
        _session_probe_task = asyncio.create_task(_probe_dead_sessions())

    pairs = await _due_job_pairs()
    if not pairs:
        return

    # Priority dispatch (W3, dispatch_plan.plan_dispatch): higher-priority kinds
    # are spawned first so on the rare same-fan overlap they win the lease race (a
    # new sub gets welcome, not followup). Operator-started work first, then the
    # kind priority. Within a rank, the account served longest ago goes first (see
    # `_last_served`, read here, before the sizing await below: runs that start
    # during it must not reorder this pass); account_id only breaks an exact tie,
    # for determinism.
    served = dict(_last_served)

    global _run_sem, _bulk_sem
    if _run_sem is None:
        _run_sem = run_slot.SlotPool(_MAX_CONCURRENT_RUNS, reserve=_OPERATOR_RESERVED_RUNS)
    if _bulk_sem is None:
        _bulk_sem = run_slot.SlotPool(_MAX_CONCURRENT_BULK)
    try:
        await _size_run_slots(_run_sem)
    except Exception:
        log.warning("automation_run_slots_size_failed", exc_info=True)

    async def _one(aid: str, kind: str, operator: bool, bulk: bool) -> None:
        # Long bulk sweeps run in their own lane so they can't starve real-time
        # senders of a slot (see _BULK_KINDS).
        sem = _bulk_sem if bulk else _run_sem
        try:
            # run_slot.hold == `async with sem`, except the run gives the slot
            # back during its typing holds (_common.hold_with_typing) and takes
            # it back ahead of fresh runs (run_slot.SlotPool). An operator's
            # run takes the operator tier: the reserve, else ahead of everyone.
            async with run_slot.hold(sem, operator=operator):
                if _draining:   # shutting down: the job stays pending for the next process
                    return
                _last_served[aid] = asyncio.get_running_loop().time()
                await run_once(aid, kind)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning(
                "automation_run_dispatch_failed account=%s kind=%s",
                aid, kind, exc_info=True,
            )
        finally:
            _inflight_pairs.discard((aid, kind))

    # Spawn DETACHED, tracked tasks — do NOT await. The supervisor loop returns
    # immediately and keeps ticking/waking, so a slow run can't stall real-time
    # dispatch. The plan skips a pair already in flight (no stacking); the
    # shared semaphore bounds total concurrency across overlapping drains. No
    # await between the plan and the last spawn: the in-flight set it read holds.
    for sp in dispatch_plan.plan_dispatch(pairs, _inflight_pairs, served, kind_priority, _BULK_KINDS):
        _inflight_pairs.add((sp.account_id, sp.kind))
        t = asyncio.create_task(_one(sp.account_id, sp.kind, sp.operator, sp.bulk))
        _inflight_tasks.add(t)
        t.add_done_callback(_inflight_tasks.discard)


async def automation_supervisor() -> None:
    """Async supervisor loop — mirror of transaction_ingest.start_supervisor /
    server._pump_supervisor: drain a tick, sleep AT END so cadence holds
    regardless of tick duration, return on CancelledError, log+continue on
    anything else. Spawned from server._start_event_pumps and cancelled in
    _stop_event_pumps alongside the other supervisors."""
    global _wake_event
    _wake_event = asyncio.Event()  # created on the running loop (W7 wake)
    log.info(
        "automation_supervisor_started tick=%ds max_concurrent=%d",
        _TICK_INTERVAL_S, _MAX_CONCURRENT_RUNS,
    )
    # Self-heal orphaned 'running' rows from the previous process before the
    # first tick, so a crash/restart mid-run can't permanently starve a rule.
    try:
        await _reconcile_orphans()
    except Exception:
        log.warning("reconcile_orphans_failed", exc_info=True)
    while True:
        try:
            cycle_started = time.monotonic()
            await _drain_due_jobs_once()
            elapsed = time.monotonic() - cycle_started
            # W7: wake early on an inbound event, else hold the 30s cadence.
            # Wait FIRST, clear AFTER: a wake that landed during the drain above
            # leaves the event set, so wait_for returns immediately and we
            # re-drain it on the next cycle instead of losing it.
            try:
                await asyncio.wait_for(
                    _wake_event.wait(), timeout=max(0.0, _TICK_INTERVAL_S - elapsed)
                )
            except asyncio.TimeoutError:
                pass  # normal fallback tick
            _wake_event.clear()
        except asyncio.CancelledError:
            return
        except Exception:
            log.warning("automation supervisor cycle failed", exc_info=True)
            await asyncio.sleep(_TICK_INTERVAL_S)


# Last, once every name above exists: scrape_chats imports this module (its
# `from automation_executor import _to_cents, …` needs them defined), and its
# @register("scrape_chats") must run on importing the executor.
from automations import scrape_chats as _scrape_chats  # noqa: E402,F401
