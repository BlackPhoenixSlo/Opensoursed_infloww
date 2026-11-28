from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Awaitable, Callable, TYPE_CHECKING, assert_never

from sqlalchemy import case, func, literal, or_, select, text, update

from db.engine import get_session
from db.models import (
    Account,
    AccountAiConfig,
    AccountHealth,
    AutomationRule,
    AutomationRun,
    MASS_RUN_INTERRUPTED,
    MASS_RUN_RUNNING,
    MassRun,
    ScheduledJob,
)

from of_client import OUTBOUND_TEXT_GUARD, OFClient, proxy_refused
import client_pool
import of_call_counter
import accounts as account_registry  # noqa: F401
import platforms
from automation_registry import (get_automation, canonical_kind,
                                 kind_family, load_automation_plugins,
                                 failed_plugins)
from automations import rhythm
import account_health
import account_page

import lane_config
import run_slot
import dispatch_plan
import run_decide
import send_ops
from of_coerce import cents_or_zero as _to_cents, strip_tags as _strip_html  # noqa: F401 — ax._to_cents / ax._strip_html importers
from fan_lease import (  # noqa: F401 — re-exports
    _FAN_COOLDOWN_S,
    _LEASE_TTL_S,
    _sweep_expired_leases,
    acquire_fan_lease,
    fan_on_cooldown,
    fans_on_cooldown,
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
from job_queue import (  # noqa: F401 — re-exports
    ANY_FAN,
    FOLLOWUP_MARK,
    JOB_FAN,
    JOB_CANCELLED,
    MISSED_WHILE_OFF_REASON,
    RULE_OFF_REASON,
    _FOLLOW_UP_JOB,
    _automation_employee,
    _by_operator,
    _claim_due_job,
    _current_job_id,
    _current_rule_id,
    _finalize_run,
    _mark_job,
    _mark_job_failure,
    _open_run,
    _park_failed_job,
    _release_job,
    cancel_jobs_missed_while_off,
    current_rule_id,
    enabled_rule_id,
    enqueue_followup,
    enqueue_job,
    rule_is_live,
    rule_last_fired_at,
)

if TYPE_CHECKING:
    import cell_hold

import cell_mode
from send_tripwire import UnclaimedSend

_CELLS = bool(os.environ.get("OI_CELL_MAP"))

log = logging.getLogger("of-relay.automation")

_TICK_INTERVAL_S = 30
_MAX_CONCURRENT_RUNS = lane_config.resolve("AUTOMATION_MAX_CONCURRENT_RUNS", 4)
_MAX_CONCURRENT_BULK = lane_config.resolve("AUTOMATION_MAX_CONCURRENT_BULK", 2)
_OPERATOR_RESERVED_BULK = 1
_OPERATOR_RESERVED_RUNS = lane_config.resolve("AUTOMATION_OPERATOR_RESERVED_RUNS", 2)
# The kinds whose run is a person's own content, sent when they said: only
# these take the operator tier (the slot queue, the write gate, the DM rate
# limiter's pass) when an operator enqueued them. Who clicked does not make a
# run an operator's: Run now on autoreply (or any automation kind) is the
# automation's own work and queues, spaces and rate-limits as automation.
_OPERATOR_KINDS: frozenset[str] = frozenset({
    "scheduled_send", "mass_premade", "unsend_messages", "priority_mass",
})
_FULL_AI_PER_CREATOR = 4
_PER_FAN_KINDS: frozenset[str] = frozenset({"full_ai_chat"})


def _per_fan_caps() -> dict[str, int]:
    cap = lane_config.resolve_live("AUTOMATION_FULL_AI_PER_CREATOR", _FULL_AI_PER_CREATOR)
    return dict.fromkeys(_PER_FAN_KINDS, cap)


_per_fan_caps()
_BULK_KINDS: frozenset[str] = frozenset({
    "scrape_chats", "process_old_fans",
    "smart_list_sync",
    "priority_mass",   # ~2-min legs of paced per-fan DMs (automations/priority_mass)
})
_SESSION_PROBE_INTERVAL_S = 600

_KIND_PRIORITY: dict[str, int] = {
    "send_welcome": 1,
    "welcome_chatter_for_info": 3,
    "send_followup": 4,
    "reply_mass_funnel": 5,
    "send_mass_message": 6,
}
_DEFAULT_PRIORITY = 50

_UNKNOWN_RULE_WARNED: set[tuple[int, str]] = set()


def kind_priority(kind: str) -> int:
    return _KIND_PRIORITY.get(canonical_kind(kind), _DEFAULT_PRIORITY)


_wake_event: asyncio.Event | None = None


def wake_supervisor() -> None:
    ev = _wake_event
    if ev is not None:
        ev.set()


_poked: set[tuple[str, str]] = set()


def poke_rule(account_id: Any, kind: str) -> None:
    _poked.add((str(account_id), canonical_kind(kind)))
    wake_supervisor()


_run_sem: run_slot.SlotPool | None = None
_bulk_sem: run_slot.SlotPool | None = None
_inflight_pairs: set[tuple] = set()
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
_sends_open: dict = {}


def begin_send() -> bool:
    if _draining:
        return False
    task = asyncio.current_task()
    if task is not None and task not in _sends_open:
        _sends_open[task] = asyncio.get_running_loop().create_future()
        task.add_done_callback(end_send)
    return True


def stop_claiming() -> None:
    global _draining
    _draining = True


def draining() -> bool:
    return _draining


def end_send(task=None) -> None:
    fut = _sends_open.pop(task or asyncio.current_task(), None)
    if fut is not None and not fut.done():
        fut.set_result(None)


async def drain(timeout_s: float | None = None) -> dict:
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
    if _inflight_tasks:
        await asyncio.gather(*list(_inflight_tasks), return_exceptions=True)


_run_locks: dict[tuple, asyncio.Lock] = defaultdict(asyncio.Lock)


def runs_inflight() -> int:
    return sum(lock.locked() for lock in _run_locks.values())



from isotime import parse_iso as _parse_iso  # noqa: E402 — OF ISO 8601 → naive UTC (callers use ax._parse_iso)


def _media_ids(media: list | None) -> list[int]:
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



_CELL_HELD = "cell_held"
_HoldNotes = dict[str, tuple[str, "cell_hold.Hold"]]


def _json_field(stats_json, field):
    return case((func.json_valid(stats_json), func.json_extract(stats_json, f"$.{field}")))


def _is_hold_note(run):
    return (run.status == "skipped") & (_json_field(run.stats_json, "reason") == _CELL_HELD) & (
        _json_field(run.stats_json, "hold_id").is_not(None))


async def _record_hold_notes(notes: _HoldNotes) -> None:
    if not notes:
        return
    run = AutomationRun.__table__
    now = datetime.utcnow()
    async with get_session() as s:
        for account_id, (kind, hold) in notes.items():
            noted = select(run.c.id).where(run.c.account_id == account_id, _is_hold_note(run.c),
                                          _json_field(run.c.stats_json, "hold_id") == hold.id)
            stats = json.dumps({"reason": _CELL_HELD, "why": hold.why, "hold_id": hold.id})
            values = dict(account_id=account_id, kind=canonical_kind(kind), status="skipped",
                          started_at=now, completed_at=now, stats_json=stats)
            await s.execute(run.insert().from_select(list(values), select(*(
                literal(value, type_=run.c[key].type) for key, value in values.items()
            )).where(~noted.exists())))


def _held_accounts(pairs, notes: _HoldNotes | None) -> set[str]:
    import cell_hold

    rows = cell_hold.holds()
    if not rows:
        return set()
    owned = cell_mode._owned_platforms()
    held = set()
    for aid, kind in pairs:
        aid = str(aid)
        if aid not in held and aid in owned and (hold := cell_hold.blocking(rows, owned[aid], aid, True)):
            held.add(aid)
            if notes is not None:
                notes.setdefault(aid, (kind, hold))
    return held


async def _due_job_pairs(notes: _HoldNotes | None = None) -> list[dispatch_plan.Pair]:
    now = datetime.utcnow()
    off = await account_health.deactivated_ids()
    auto_emp = await _automation_employee()
    per_fan = [k for kind in _PER_FAN_KINDS for k in kind_family(kind)]
    fan = case((ScheduledJob.kind.in_(per_fan), JOB_FAN), else_=None)
    async with get_session() as s:
        rows = (
            await s.execute(
                select(ScheduledJob.account_id, ScheduledJob.kind,
                       func.max(case((_by_operator(auto_emp), 1), else_=0)),
                       func.min(ScheduledJob.run_at), fan)
                .where(
                    ScheduledJob.status == "pending",
                    ScheduledJob.run_at <= now,
                    *(_owned_only(ScheduledJob.account_id) if _CELLS else ()),
                )
                .group_by(ScheduledJob.account_id, ScheduledJob.kind, fan)
            )
        ).all()
        held = _held_accounts(((r[0], r[1]) for r in rows), notes) if _CELLS else frozenset()
    return [dispatch_plan.Pair(r[0], r[1], bool(r[2]) and canonical_kind(r[1]) in _OPERATOR_KINDS,
                               _epoch(r[3]), r[4])
            for r in rows if r[0] not in off and str(r[0]) not in held]


def _epoch(dt: datetime | str) -> float:
    if isinstance(dt, str):
        dt = _parse_iso(dt)
    return (dt - datetime(1970, 1, 1)).total_seconds()


_QUIET_HOURS_NO_CLOCK_WARNED: set[str] = set()


async def _account_clock(s, account_id, offsets: dict, now: datetime) -> int | None:
    if account_id not in offsets:
        row = (await s.execute(
            select(AccountAiConfig.utc_offset, AccountAiConfig.timezone)
            .where(AccountAiConfig.account_id == account_id)
        )).first()
        acct_off, acct_tz = (row[0], row[1]) if row else (None, None)
        offsets[account_id] = rhythm.tz_offset_for(acct_tz, acct_off, now)
    return offsets[account_id]


async def _pair_busy(s, rule: AutomationRule, now: datetime) -> dispatch_plan.Busy | None:
    return (
        await s.execute(
            select(ScheduledJob.status)
            .where(
                ScheduledJob.account_id == rule.account_id,
                ScheduledJob.kind.in_(kind_family(rule.kind)),
                ScheduledJob.status.in_(("pending", "running")),
                ScheduledJob.run_at <= now,
                ~_FOLLOW_UP_JOB,
            )
            .limit(1)
        )
    ).scalar_one_or_none()


def _rule_trigger(rule: AutomationRule) -> dispatch_plan.Trigger | None:
    try:
        trigger = json.loads(rule.trigger_json or "{}")
    except (TypeError, ValueError):
        log.warning("automation_rule_bad_trigger rule_id=%s", rule.id)
        return None
    return dispatch_plan.parse_trigger(trigger) if isinstance(trigger, dict) else None


async def _materialize_due_rules(notes: _HoldNotes | None = None) -> int:
    load_automation_plugins()
    now = datetime.utcnow()
    enqueued = 0
    poked = set(_poked)
    _poked.clear()
    offsets: dict[str, int | None] = {}
    async with get_session() as s:
        rules = (
            await s.execute(
                select(AutomationRule).where(
                    AutomationRule.is_enabled.is_(True),
                    *(_owned_only(AutomationRule.account_id) if _CELLS else ()),
                )
            )
        ).scalars().all()
        held = _held_accounts(((r.account_id, r.kind) for r in rules), notes) if _CELLS else frozenset()
        for rule in rules:
            if str(rule.account_id) in held:
                continue
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
            trig = _rule_trigger(rule)
            if trig is None:
                continue

            pair = (str(rule.account_id), canonical_kind(rule.kind))
            pending = await _pair_busy(s, rule, now)

            last_rule_job_at = await rule_last_fired_at(s, rule.id)

            run_count = None
            if trig.max_runs is not None:
                cadence_runs = (func.coalesce(_is_hold_note(AutomationRun), False).is_(False),) if _CELLS else ()
                run_count = (
                    await s.execute(
                        select(func.count())
                        .select_from(AutomationRun)
                        .where(
                            AutomationRun.account_id == rule.account_id,
                            AutomationRun.kind == canonical_kind(rule.kind),
                            *cadence_runs,
                        )
                    )
                ).scalar_one()

            acct = rule.account_id
            plan = dispatch_plan.plan_rule(
                trig, busy=pending, poked=pair in poked, last_fired=last_rule_job_at,
                run_count=run_count, quiet_hours_json=rule.quiet_hours_json, now=now, kind=pair[1])
            if isinstance(plan, dispatch_plan.CheckQuiet):
                plan = dispatch_plan.quiet_plan(
                    plan.band, await _account_clock(s, acct, offsets, now), now)
            match plan:
                case dispatch_plan.Repoke():
                    _poked.add(pair)
                    continue
                case dispatch_plan.Skip(reason="quiet_hours"):
                    if pair in poked and pair[1] in dispatch_plan.REPOKE_KINDS:
                        _poked.add(pair)
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




def _make_client(account_id: str) -> OFClient:
    backend = platforms.require_account(account_id).backend
    if backend is not None:
        return backend.get_client(account_id)
    return client_pool.get(account_id)



_SCRAPE_NAMES: frozenset[str] = frozenset({
    "_scrape_one_chat", "_upsert_fan_identity",
    "_SCRAPE_PAGE_SIZE", "_SCRAPE_MAX_PAGES",
})


def __getattr__(name: str) -> Any:
    if name in _SCRAPE_NAMES:
        from automations import scrape_chats
        return getattr(scrape_chats, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")



_session_skip_log_last: dict[str, float] = {}
_session_probe_task: asyncio.Task | None = None


def _log_session_dead_skip(account_id: str, kind: str) -> None:
    now = time.monotonic()
    last = _session_skip_log_last.get(account_id)
    if last is not None and now - last < _SESSION_PROBE_INTERVAL_S:
        return
    _session_skip_log_last[account_id] = now
    log.info(
        "automation_paused_session_dead account=%s kind=%s — runs skipped "
        "until the recovery probe or a re-capture clears it",
        account_id, kind,
    )


async def _probe_dead_sessions() -> None:
    try:
        aids = await account_health.due_probe_ids(_SESSION_PROBE_INTERVAL_S)
        if _CELLS:
            aids = cell_mode.owned_only(aids)
        for aid in aids:
            await account_health.stamp_probe(aid)
            try:
                # Evict, don't bypass the pool: a fresh-client probe would clear the flag while runs keep the stale pooled client, fail, and re-flag forever.
                client_pool.evict(aid)
                client = _make_client(aid)
                me = await asyncio.to_thread(client.me)
            except Exception as e:
                log.info("session_probe_still_dead account=%s err=%s", aid, repr(e)[:200])
                continue
            account_page.prime(aid, me)
            if await account_health.clear_session_dead(aid):
                log.info("account_session_recovered account=%s — automations resume", aid)
    except Exception:
        log.warning("session_probe_sweep_failed", exc_info=True)


async def _outbound_guard(account_id: str):
    from automations import _wordfilter
    try:
        return _wordfilter.outbound_guard(*await _wordfilter.load_banned_words(account_id))
    except Exception:
        log.warning("outbound_guard_load_failed account=%s", account_id, exc_info=True)
        return None



async def run_once(
    account_id: str,
    kind: str,
    *,
    payload: dict | None = None,
    job_id: int | None = None,
    job_only: bool = True,
    fan: Any = ANY_FAN,
) -> dict:
    load_automation_plugins()
    kind = canonical_kind(kind)
    fn = get_automation(kind)
    if fn is None:
        err = (f"automation plugin failed to import: {kind}"
               if kind in failed_plugins()
               else f"unknown automation kind: {kind}")
        log.warning("automation_unknown_kind account=%s kind=%s", account_id, kind)
        if payload is None and job_id is None:
            claimed = await _claim_due_job(account_id, kind)
            job_id = claimed.id if claimed is not None else None
        run_id = await _open_run(account_id, kind)
        status, job_status, err = run_decide.outcome("unknown_kind", None, err)
        await _finalize_run(run_id, status, None, err, job_id=job_id, job_status=job_status)
        return {"status": "error", "reason": "unknown_kind", "run_id": run_id}

    lock = _run_locks[dispatch_plan.run_key(account_id, kind, fan, () if fan is ANY_FAN else _PER_FAN_KINDS)]
    if lock.locked():
        return {"status": "skipped", "reason": "in_flight"}

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

    if _CELLS:
        import cell_hold
        if (hold := cell_hold.held(account_id)) is not None:
            if job_id is not None:
                await _release_job(job_id)
            await _record_hold_notes({str(account_id): (kind, hold)})
            return {"status": "skipped", "reason": _CELL_HELD, "why": hold.why}

    if lock.locked():
        return {"status": "skipped", "reason": "in_flight"}
    async with lock:
        if send_ops.paused():
            result = {"status": "skipped", "reason": "writes_paused"}
            if job_id is None:
                return result
            await _release_job(job_id)
            run_id = await _open_run(account_id, kind)
            await _finalize_run(run_id, "skipped", {"reason": "writes_paused"}, None)
            return {**result, "run_id": run_id}
        if send_ops.cells() and kind in send_ops.ANCHORLESS_EXECUTORS:
            if payload is None and job_id is None:
                claimed = await _claim_due_job(account_id, kind, fan=fan)
                job_id = claimed.id if claimed is not None else None
            result = {"status": "skipped", "reason": "no_anchor"}
            if job_id is None:
                return result
            run_id = await _open_run(account_id, kind)
            await _finalize_run(run_id, "skipped", {"reason": "no_anchor"}, None, job_id=job_id)
            return {**result, "run_id": run_id}
        rule_id: int | None = None
        if payload is None and job_id is None:
            claimed = await _claim_due_job(account_id, kind, fan=fan)
            if claimed is not None:
                payload = run_decide.parse_payload(claimed.payload_json)
                job_id = claimed.id
                check = run_decide.tagged_rule(payload, claimed.rule_id) or claimed.rule_id
                live = None
                if check is not None:
                    async with get_session() as s:
                        live = await rule_is_live(s, check)
                match claim := run_decide.bind_claim(claimed.payload_json, claimed.rule_id, live):
                    case run_decide.Drop(rule_id=tagged):
                        await _mark_job(job_id, JOB_CANCELLED, RULE_OFF_REASON)
                        log.info("automation_job_dropped_rule_off account=%s "
                                 "kind=%s job=%s rule=%s",
                                 account_id, kind, job_id, tagged)
                        return {"status": "skipped", "reason": "rule_disabled",
                                "job_id": job_id}
                    case run_decide.Bind(rule_id=bound):
                        rule_id = bound
                    case _:
                        assert_never(claim)
            elif job_only:
                return {"status": "skipped", "reason": "no_job"}
        payload = payload or {}

        run_id = await _open_run(account_id, kind)
        if unknown := platforms.unknown_refusal(account_id):
            status, job_status, reason = run_decide.outcome("ok", None, plugin_reason=unknown)
            stats = {"status": status, "reason": reason}
            await _finalize_run(run_id, status, stats, None, job_id=job_id, job_status=job_status)
            log.info("automation_run_skipped account=%s kind=%s run_id=%s job=%s reason=%s",
                     account_id, kind, run_id, job_id, reason)
            return {**stats, "run_id": run_id, "job_id": job_id}
        t0 = time.monotonic()
        rule_token = _current_rule_id.set(rule_id)
        job_token = _current_job_id.set(job_id)
        write = run_decide.RunWrites()
        write_token = _RUN_WRITE.set(write)
        once = run_decide.sends_once(kind)
        from automations._wordfilter import OutboundWordsBlocked
        guard = await _outbound_guard(account_id)
        guard_token = OUTBOUND_TEXT_GUARD.set(guard)
        try:
            ran = "ok"
            try:
                if _CELLS and kind in ("send_mass_message", "mass_premade"):
                    import restore_reconcile
                    dry_mass = kind in ("send_mass_message", "mass_premade") and payload.get("dry_run")
                    if restore_reconcile.active() and not dry_mass:
                        await asyncio.to_thread(restore_reconcile.refuse_queue,
                                                platforms.for_account(account_id).key, "mass_job")
                with of_call_counter.caller(f"auto:{kind}"):
                    stats = await fn(account_id, payload, run_id=run_id) or {}
            except OutboundWordsBlocked:
                stats = {}
                ran = "words_blocked"
            stats["duration_ms"] = int((time.monotonic() - t0) * 1000)
            guard_status = None
            if guard is not None and guard.blocked:
                stats.update(guard.summary())
                guard_status = guard.run_status()
            status, job_status, skip_reason = run_decide.outcome(
                ran, guard_status, plugin_reason=stats.get("reason"), plugin_status=stats.get("status"))
            plugin_skipped = status == "skipped" and guard_status != "skipped"
            if plugin_skipped:
                stats.update(status="skipped", reason=skip_reason)
            await _finalize_run(run_id, status, stats, None, job_id=job_id, job_status=job_status)
            if status == "skipped":
                if not plugin_skipped:
                    log.info("automation_run_skipped account=%s kind=%s run_id=%s job=%s "
                             "blocked word(s) %r", account_id, kind, run_id, job_id, guard.hits)
                    return {"status": "skipped", "reason": "sensitive_words",
                            **stats, "run_id": run_id, "job_id": job_id}
                log.info("automation_run_skipped account=%s kind=%s run_id=%s job=%s reason=%s",
                         account_id, kind, run_id, job_id, skip_reason)
                return {**stats, "run_id": run_id, "job_id": job_id}
            log.info(
                "automation_run_%s account=%s kind=%s run_id=%s job=%s stats=%s",
                status, account_id, kind, run_id, job_id, stats,
            )
            return {"status": "ok", **stats, "run_id": run_id, "job_id": job_id}
        except asyncio.CancelledError:
            status, job_status, err = run_decide.outcome(
                "cancelled", None, "cancelled", once=once, wrote=write.state)
            _log_parked(job_status, account_id, kind, run_id, job_id, write.state)
            await _finalize_run(run_id, status, None, err,
                                job_id=job_id, job_status=job_status)
            raise
        except Exception as e:
            if ((reason := send_ops.refusal_reason(e) if _CELLS or write.state == "none" else None)
                    and (write.state == "none" or reason == _CELL_HELD)):
                await _release_job(job_id, defer_s=run_decide.JOB_RETRY_BACKOFF_S
                                   if _CELLS and reason in send_ops._FAN_REFUSALS else 0)
                await _finalize_run(run_id, "skipped", {"reason": reason}, None)
                return {"status": "skipped", "reason": reason, "run_id": run_id, "job_id": job_id}
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
            if isinstance(e, UnclaimedSend) and write.state == "none":
                job_status = "error"
            else:
                _log_parked(job_status, account_id, kind, run_id, job_id, write.state)
            refused = run_decide.defers_refusal(kind, proxy_refused(e), write.state)
            await _finalize_run(run_id, status, None, err, job_id=job_id,
                                job_status=job_status, refused=refused)
            return {"status": "error", "run_id": run_id, "job_id": job_id, "error": err}
        finally:
            OUTBOUND_TEXT_GUARD.reset(guard_token)
            _RUN_WRITE.reset(write_token)
            _current_rule_id.reset(rule_token)
            _current_job_id.reset(job_token)


def _log_parked(job_status: str, account_id: str, kind: str, run_id: int,
                job_id: int | None, wrote: str) -> None:
    if job_status == "error":
        log.warning("automation_job_parked_may_have_sent account=%s kind=%s run_id=%s "
                    "job=%s write=%s", account_id, kind, run_id, job_id, wrote)




def _owned_only(col) -> tuple:
    owned = cell_mode.owned_set()
    return () if owned is None else (col.in_(sorted(owned)),)


async def park_restore(account_ids: list[str], cutoff: datetime, *, data_gen: int | None = None) -> int:
    async with get_session() as s:
        parked = (await s.execute(
            update(ScheduledJob)
            .where(ScheduledJob.account_id.in_(account_ids), ScheduledJob.status.in_(("pending", "running")),
                   ScheduledJob.run_at <= cutoff,
                   or_(ScheduledJob.kind.in_(run_decide.one_shot_family()), ScheduledJob.rule_id.is_not(None),
                       _json_field(ScheduledJob.payload_json, "_rule_id").is_not(None)))
            .values(status="error", last_error=run_decide.RESTORE_REASON)
        )).rowcount
        rules = (await s.execute(select(AutomationRule).where(
            AutomationRule.is_enabled.is_(True), AutomationRule.account_id.in_(account_ids),
        ))).scalars().all()
        for rule in rules:
            trigger = _rule_trigger(rule)
            if trigger is None:
                continue
            last_fired = await rule_last_fired_at(s, rule.id)
            due = dispatch_plan.next_due(trigger, last_fired, cutoff, run_count=0)
            if due is None or due > cutoff:
                continue
            s.add(ScheduledJob(account_id=rule.account_id, kind=canonical_kind(rule.kind),
                               payload_json=rule.steps_json or "{}", run_at=due, created_at=cutoff,
                               rule_id=rule.id, status="error", last_error=run_decide.RESTORE_REASON))
            parked += 1
        if data_gen is not None:
            await s.execute(text("UPDATE cell_meta SET last_data_gen=:gen"), {"gen": data_gen})
    return parked


async def _interrupt_orphan_mass_runs(s, now: datetime) -> list[int]:
    ids = list((await s.execute(
        select(MassRun.id).where(MassRun.status == MASS_RUN_RUNNING, *_owned_only(MassRun.account_id))
        .order_by(MassRun.id))).scalars())
    if ids:
        await s.execute(update(MassRun).where(MassRun.id.in_(ids), MassRun.status == MASS_RUN_RUNNING)
                        .values(status=MASS_RUN_INTERRUPTED, completed_at=now))
    return ids


async def _reconcile_orphans() -> None:
    now = datetime.utcnow()
    running = (ScheduledJob.status == "running", *_owned_only(ScheduledJob.account_id))
    async with get_session() as s:
        parked = await s.execute(
            update(ScheduledJob)
            .where(*running, ScheduledJob.kind.in_(run_decide.one_shot_family()))
            .values(status="error", last_error=run_decide.ORPHAN_REASON)
        )
        jobs = await s.execute(update(ScheduledJob).where(*running).values(status="pending"))
        runs = await s.execute(
            update(AutomationRun)
            .where(AutomationRun.status == "running", *_owned_only(AutomationRun.account_id))
            .values(status="error", completed_at=now,
                    error_text="interrupted (relay restart)")
        )
        masses = await _interrupt_orphan_mass_runs(s, now)
    if masses:
        log.warning("mass_runs_interrupted ids=%s (may have sent; not resent)", masses)
    log.info("reconciled_orphans requeued_jobs=%s parked_jobs=%s interrupted_runs=%s "
             "interrupted_masses=%s", jobs.rowcount, parked.rowcount, runs.rowcount, len(masses))


async def _active_models() -> int:
    off = select(AccountHealth.account_id).where(AccountHealth.deactivated_at.is_not(None))
    async with get_session() as s:
        return int((await s.execute(
            select(func.count()).select_from(Account).where(Account.id.not_in(off), *_owned_only(Account.id))
        )).scalar_one())


async def _size_slots(pool: run_slot.SlotPool, knob: str, auto, event: str) -> None:
    if lane_config.overridden(knob):
        return
    models = await _active_models()
    n = auto(models)
    if n != pool.n:
        log.info("%s from=%d to=%d active_models=%d", event, pool.n, n, models)
        pool.resize(n)
    lane_config.resolve(knob, n)
    lane_config.record_live(knob, n)


async def _size_run_slots(pool: run_slot.SlotPool) -> None:
    await _size_slots(pool, "AUTOMATION_MAX_CONCURRENT_RUNS", run_slot.auto_runs,
                      "automation_run_slots_resized")


async def _size_bulk_slots(pool: run_slot.SlotPool) -> None:
    await _size_slots(pool, "AUTOMATION_MAX_CONCURRENT_BULK", run_slot.auto_bulk,
                      "automation_bulk_slots_resized")


async def _drain_due_jobs_once() -> None:
    if send_ops.paused():
        return
    notes: _HoldNotes = {}
    try:
        await _materialize_due_rules(notes)
    except Exception:
        log.warning("automation_rule_materialize_failed", exc_info=True)
    try:
        await _sweep_expired_leases()
    except Exception:
        log.warning("automation_lease_sweep_failed", exc_info=True)

    global _session_probe_task
    if _session_probe_task is None or _session_probe_task.done():
        _session_probe_task = asyncio.create_task(_probe_dead_sessions())

    pairs = await _due_job_pairs(notes)
    if notes:
        await _record_hold_notes(notes)
    if not pairs:
        return

    served = dict(_last_served)

    global _run_sem, _bulk_sem
    if _run_sem is None:
        _run_sem = run_slot.SlotPool(_MAX_CONCURRENT_RUNS, reserve=_OPERATOR_RESERVED_RUNS)
    if _bulk_sem is None:
        _bulk_sem = run_slot.SlotPool(_MAX_CONCURRENT_BULK, reserve=_OPERATOR_RESERVED_BULK)
    try:
        await _size_run_slots(_run_sem)
    except Exception:
        log.warning("automation_run_slots_size_failed", exc_info=True)
    try:
        await _size_bulk_slots(_bulk_sem)
    except Exception:
        log.warning("automation_bulk_slots_size_failed", exc_info=True)

    per_fan = _per_fan_caps()

    async def _one(aid: str, kind: str, operator: bool, bulk: bool, key: tuple, per_fan_run: bool) -> None:
        sem = _bulk_sem if bulk else _run_sem
        ran = False
        try:
            async with run_slot.hold(sem, operator=operator):
                if _draining:
                    return
                _last_served[aid] = asyncio.get_running_loop().time()
                res = await run_once(aid, kind, **({"fan": key[2]} if per_fan_run else {}))
                ran = isinstance(res, dict) and res.get("status") in ("ok", "error")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning(
                "automation_run_dispatch_failed account=%s kind=%s",
                aid, kind, exc_info=True,
            )
        finally:
            _inflight_pairs.discard(key)
            if per_fan_run:
                _run_locks.pop(key, None)
                if ran:
                    wake_supervisor()

    for sp in dispatch_plan.plan_dispatch(pairs, _inflight_pairs, served, kind_priority, _BULK_KINDS, per_fan):
        key = dispatch_plan.run_key(sp.account_id, sp.kind, sp.fan, per_fan)
        _inflight_pairs.add(key)
        t = asyncio.create_task(_one(sp.account_id, sp.kind, sp.operator, sp.bulk, key, sp.kind in per_fan))
        _inflight_tasks.add(t)
        t.add_done_callback(_inflight_tasks.discard)


async def automation_supervisor() -> None:
    global _wake_event
    _wake_event = asyncio.Event()
    log.info(
        "automation_supervisor_started tick=%ds max_concurrent=%d",
        _TICK_INTERVAL_S, _MAX_CONCURRENT_RUNS,
    )
    try:
        await _reconcile_orphans()
    except Exception:
        log.warning("reconcile_orphans_failed", exc_info=True)
    while True:
        try:
            cycle_started = time.monotonic()
            await _drain_due_jobs_once()
            elapsed = time.monotonic() - cycle_started
            try:
                await asyncio.wait_for(
                    _wake_event.wait(), timeout=max(0.0, _TICK_INTERVAL_S - elapsed)
                )
            except asyncio.TimeoutError:
                pass
            _wake_event.clear()
        except asyncio.CancelledError:
            return
        except Exception:
            log.warning("automation supervisor cycle failed", exc_info=True)
            await asyncio.sleep(_TICK_INTERVAL_S)


from automations import scrape_chats as _scrape_chats  # noqa: E402,F401
