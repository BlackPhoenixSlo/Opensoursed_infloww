"""W7 webhook-priority dispatch — turn an inbound WS event into real-time
automation dispatch instead of waiting for the next 30s supervisor tick.

`event_transcoder._transcode_chat_message` calls `on_inbound_message` (fire-and-
forget) right after it persists an INBOUND DM. We:

  1. gate on a per-account flag (default OFF) + a global env kill-switch,
  2. pick the owning automation (a fan mid-funnel → reply_mass_funnel, else the
     generic welcome_chatter_for_info sweep),
  3. if the fan is on a per-fan cooldown (a human is handling them, or the bot
     just replied — W3's shared guard), DEFER the reply to the moment that
     cooldown ends rather than dropping it to the slow periodic sweep,
  4. enqueue a job (deduped) and WAKE the supervisor at the due time.

We do NOT send here and we do NOT rewrite the senders: we enqueue + wake the
EXISTING sweep, which finds the just-replied fan via its normal "fan spoke last"
gate (welcome_chatter_for_info.py: `c.last_dir == "in"`). W3's fan-lease + cooldown already
prevent double-sends, so kicking the sweep early is safe.

Design notes:
  • Whole body is wrapped so a dispatch failure can never abort the persist that
    called us — the transcoder is fire-and-forget but we belt-and-suspenders it.
  • The per-account gate lives in account_ai_config.webhook_config_json
    ({"enabled": bool}); absent/NULL → OFF. The global kill-switch is the env
    var W7_WEBHOOK_DISPATCH_DISABLED (set to 1/true to disable everywhere).
  • Memory: the live detector must NEVER run on founder (its inbound is stranger/
    promo spam). The default-OFF gate enforces that — enable Ava first.
"""
from __future__ import annotations

import logging
import asyncio
import contextlib
import json
import os
import random
import time
import weakref
from datetime import datetime, timedelta

from sqlalchemy import select

from db import write_telemetry
from db.engine import get_session
from db.models import (
    AccountAiConfig, Fan, FunnelState, MassRun, ScheduledJob,
    ScrapeHistory, SkipList,
)
import automation_executor as ax
import relay_hooks
import webhook_dispatch_decide as decide
from automation_registry import kind_family

log = logging.getLogger("of-relay.webhook_dispatch")


# One in-flight dispatch per (account, fan): two DMs of one fan ms apart each
# get their own `on_inbound_message` task (the transcoder fires one per DM), and
# without this both read "no pending job" before either inserts → 2 jobs. The
# lock is per pair, so another fan never waits; weak values, so an entry goes
# when its last holder/waiter drops the lock (no growth with the fan count).
# Not a write cap: the DM is already persisted before we run.
_fan_locks: weakref.WeakValueDictionary[tuple[str, int], asyncio.Lock] = weakref.WeakValueDictionary()


def _fan_serial(account_id: str, fan_id: int) -> asyncio.Lock:
    key = (str(account_id), int(fan_id))
    return _fan_locks.get(key) or _fan_locks.setdefault(key, asyncio.Lock())

# ── The inbound-after-a-blast scrape (plans/blast-splice Part C) ───────
# A list-audience blast writes NO per-fan row, so the man who answers it has our
# own line missing from his thread — ours AND his newest history, because on
# these accounts no `scrape_chats` cadence rule runs and the inbox poll only ever
# writes each chat's `lastMessage`. One bounded one-fan scrape on the first
# inbound after a blast lands the real copy (with its media and OF's `queueId`)
# inside the 4h window we ourselves leave open before the mass unsend erases it.
# ~34 calls/day fleet-wide, measured against 238 blind inbounds a week.
# Only on accounts a registered scrape gate allows (`_scrape_after_blast`).
# Background reads must peek (a first-page thread GET marks the chat read on OF).
_BLAST_SCRAPE_WINDOW = timedelta(minutes=60)
# One claim per fan for the one-fan scrape triggers (`enqueue_fan_scrape`): the
# after-blast scrape and a gen_info pick; a deferred chat's Click read has its own.
_FAN_SCRAPE_DEDUP_S = 600
# The dedup is an IN-PROCESS CLAIM, not a pending-job scan, and the difference is
# the whole point: `_has_imminent_pending_job` sees `status='pending'` only, so a
# job that is RUNNING or already FINISHED stops nothing and a chatty fan would buy
# a scrape per message. Checked and set with NO await in between, so two inbound
# handlers on one loop serialise on it. A restart costs at most one extra scrape
# per fan, which is the cheap direction.
_fan_scrape_claims: dict[tuple[str, int], float] = {}
_FAN_SCRAPE_CLAIM_MAX = 4096


def _global_kill_switch() -> bool:
    """True when W7 dispatch is disabled process-wide: the Settings → System
    override, else env W7_WEBHOOK_DISPATCH_DISABLED (1/true/yes/on). A cached
    read (runtime_switches), cheap on every inbound DM."""
    import runtime_switches
    return runtime_switches.on("W7_WEBHOOK_DISPATCH_DISABLED")


@contextlib.asynccontextmanager
async def _reader(s):
    """`s` when the caller already holds a read session (on_inbound_message
    reads everything through one), else a fresh one. Reads only: SQLite opens
    no snapshot for a bare SELECT here, so every read is still fresh."""
    if s is not None:
        yield s
    else:
        async with get_session() as fresh:
            yield fresh


async def _load_config(account_id: str, *, s=None) -> dict | None:
    """Per-account gate + knobs: account_ai_config.webhook_config_json.

    Shape: {"enabled": bool, "delay_seconds": number, "jitter_seconds": number}.
    Returns the parsed dict when ENABLED, else None (absent/NULL/disabled/bad
    JSON → OFF, the safe default)."""
    async with _reader(s) as s:
        cfg = await s.get(AccountAiConfig, str(account_id))
    if cfg is None or not cfg.webhook_config_json:
        return None
    try:
        data = json.loads(cfg.webhook_config_json) or {}
    except Exception:
        log.warning("bad_webhook_config_json account=%s", account_id, exc_info=True)
        return None
    if not (isinstance(data, dict) and data.get("enabled")):
        return None
    return data


def _response_delay(cfg: dict) -> float:
    """How long the AI waits before its reply lands: a fixed `delay_seconds`
    base plus a uniform-random 0..`jitter_seconds` wiggle. Makes the bot feel
    human AND gives a live human chatter a head start (if the human sends during
    the wait, the cooldown is set and the bot stands down when its job runs).
    Both default to 0 → instant, current behavior. Negatives are clamped."""
    base = max(0.0, float(cfg.get("delay_seconds") or 0))
    jitter = max(0.0, float(cfg.get("jitter_seconds") or 0))
    return base + (random.uniform(0.0, jitter) if jitter > 0 else 0.0)


# Hold strong refs to in-flight delayed-wake tasks. asyncio.create_task() only
# keeps a WEAK reference, so a fire-and-forget task can be garbage-collected
# mid-sleep — which silently drops the wake and leaves the delayed job sitting
# until an unrelated drain (observed live: a +9s reply landed ~3 min late).
_wake_tasks: set = set()


def _schedule_wake(delay_s: float) -> None:
    """Spawn a delayed-wake task and KEEP a reference so it can't be GC'd."""
    t = asyncio.create_task(_wake_after(delay_s))
    _wake_tasks.add(t)
    t.add_done_callback(_wake_tasks.discard)


async def _wake_after(delay_s: float) -> None:
    """Wake the supervisor once a delayed job becomes due. Without this the
    delayed job would sit until the next 30s fallback tick. Never raises."""
    try:
        if delay_s > 0:
            await asyncio.sleep(delay_s)
        ax.wake_supervisor()
    except Exception:  # pragma: no cover — defensive
        pass


async def _fan_mid_funnel(account_id: str, fan_id: int, *, s=None) -> bool:
    """True iff this fan has a pending funnel_state row under one of this
    account's mass runs — i.e. reply_mass_funnel owns the fan through a
    multi-step flow and welcome_chatter_for_info must not interleave it (Wave-3 overlap)."""
    async with _reader(s) as s:
        row = (
            await s.execute(
                select(FunnelState.fan_id)
                .join(MassRun, MassRun.id == FunnelState.mass_run_id)
                .where(
                    MassRun.account_id == str(account_id),
                    FunnelState.fan_id == int(fan_id),
                    FunnelState.status == "pending",
                )
                .limit(1)
            )
        ).first()
    return row is not None


async def _classify_kind(account_id: str, fan_id: int) -> str | None:
    """The kind `_classify` picks (see there), without its rule id."""
    return (await _classify(account_id, fan_id))[0]


async def _rule_gate(account_id: str, fan_id: int, kind: str, *, s=None) -> tuple[str | None, int | None]:
    """W7 may only wake `kind` (welcome_chatter_for_info / reply_mass_funnel —
    no config switch of their own, the rule IS their on/off) while the account
    has an ENABLED rule of it. Returns (kind, rule_id), or (None, None) + a skip
    log when that switch reads OFF. The job W7 queues carries the id in its
    payload (`_rule_id`) so the executor drops it if the rule goes OFF first."""
    rule_id = await ax.enabled_rule_id(account_id, kind, session=s)
    if rule_id is None:
        log.info("w7_skip_rule_off account=%s fan=%s kind=%s", account_id, fan_id, kind)
        return None, None
    return kind, rule_id


async def _classify(account_id: str, fan_id: int, *, s=None) -> tuple[str | None, int | None]:
    """Pick the automation that OWNS this fan's current stage — or None when no
    automation should reply (a human owns the chat). Routing to the wrong sweep
    is pure waste: welcome_chatter_for_info skips ANY skip-listed fan, so waking it for a fan
    it will refuse does nothing AND the fan gets no reply. Stages:

      • funnel      — pending funnel_state       → reply_mass_funnel
      • terminal    — any skip_list row ('info' graduation, spent/too_long,
                      hard blocks, …) → None
      • ai_chat     — still gathering (not skip-listed) → welcome_chatter_for_info

    The skip_list is the ONE stage marker, mirroring the automations' OWN gates
    (welcome_chatter_for_info _load_stop_lists / _graduate), so we never wake an automation
    that would just skip this fan.

    Returns (kind, rule_id): rule_id is the enabled rule a rule-gated kind was
    found under (see `_rule_gate`), else None.
    """
    if await _fan_mid_funnel(account_id, fan_id, s=s):
        # Funnels only advance while an enabled walker rule exists (catalog);
        # with it OFF the operator has stopped funnels — don't walk this one.
        return await _rule_gate(account_id, fan_id, "reply_mass_funnel", s=s)

    async with _reader(s) as s:
        skip = (
            await s.execute(
                select(SkipList.reason).where(
                    SkipList.account_id == str(account_id),
                    SkipList.fan_id == int(fan_id),
                )
            )
        ).first()

    if skip is not None:  # skip-listed (any reason) → no automation replies
        return None, None

    # Not skip-listed → still in the welcome_chatter_for_info stage. Its switch
    # is its rule (ScriptsTab / Automations): Reply Instant ON must not wake it
    # while that switch reads OFF.
    return await _rule_gate(account_id, fan_id, "welcome_chatter_for_info", s=s)


async def _fan_paused_until(account_id: str, fan_id: int, *, s=None) -> datetime | None:
    """The fan's automation_paused_until (their per-fan cooldown end), or None.
    Read fresh — a sender that paused this fan earlier in the same tick must be
    visible so we defer to the real end, not a stale snapshot."""
    async with _reader(s) as s:
        until = (
            await s.execute(
                select(Fan.automation_paused_until).where(
                    Fan.account_id == str(account_id),
                    Fan.fan_id == int(fan_id),
                )
            )
        ).scalar_one_or_none()
    return until


async def _imminent_pending_job(
    account_id: str, kind: str, fan_id: int, within_s: float, *, s=None
) -> tuple[datetime, dict] | None:
    """The pending (account, kind) job already targeting THIS fan and due within
    `within_s` seconds — `(run_at, payload)` — or None if there is none.

    Per-fan (not per-kind) because W7 is fan-scoped now: two different fans
    replying must each get their own job. The window spans our response delay so
    two quick replies from the SAME fan don't double-queue.

    Returns the LATEST-due match. W7 callers only want the boolean and take
    `_has_imminent_pending_job` below; the full_ai hook reads the payload."""
    return (await _imminent_pending_jobs(account_id, kind, [fan_id], within_s, s=s)).get(int(fan_id))


async def _imminent_pending_jobs(
    account_id: str, kind: str, fan_ids, within_s: float, *, s=None
) -> dict[int, tuple[datetime, dict]]:
    """`_imminent_pending_job` for many fans in one read: fan id -> its
    LATEST-due `(run_at, payload)`, only the fans of `fan_ids` that have one
    (Full AI's sweep asks for a whole pass)."""
    soon = datetime.utcnow() + timedelta(seconds=within_s)
    async with _reader(s) as s:
        rows = (
            await s.execute(
                select(ScheduledJob.run_at, ScheduledJob.payload_json).where(
                    ScheduledJob.account_id == str(account_id),
                    # kind_family: a pre-rename pending job must still dedup —
                    # this guard is what stands between a fan and a double send.
                    ScheduledJob.kind.in_(kind_family(kind)),
                    ScheduledJob.status == "pending",
                    ScheduledJob.run_at <= soon,
                )
            )
        ).all()
    fids = {int(f) for f in fan_ids}
    best: dict[int, tuple[datetime, dict]] = {}
    for run_at, pj in rows:
        try:
            p = json.loads(pj or "{}")
        except Exception:
            continue
        if not isinstance(p, dict):
            continue
        at = run_at or datetime.utcnow()
        for fid in fids:
            if decide.targets_fan(p, fid) and (fid not in best or at > best[fid][0]):
                best[fid] = (at, p)
    return best


async def _has_imminent_pending_job(
    account_id: str, kind: str, fan_id: int, within_s: float, *, s=None
) -> bool:
    """Is a job already queued for this fan? → skip a second enqueue.

    The predicate form of `_imminent_pending_job`, for the callers that only ask
    the yes/no question."""
    return await _imminent_pending_job(account_id, kind, fan_id, within_s, s=s) is not None


async def _blasted_recently(account_id: str, *, s=None) -> bool:
    """Did this account broadcast in the last `_BLAST_SCRAPE_WINDOW`?

    Two sources, and each covers the other's blind spot: `mass_runs.sent_at` (our
    own sends — durable, survives a restart, indexed by
    `ix_mass_runs_account_sent`) and the transcoder's in-process `chat_queue_finish`
    ring (a blast the creator composed in the OF APP, which leaves us no row at
    all). The ring is checked first because it costs nothing."""
    from event_transcoder import blasted_within
    if blasted_within(account_id, seconds=_BLAST_SCRAPE_WINDOW.total_seconds()):
        return True
    async with _reader(s) as s:
        hit = (await s.execute(
            select(MassRun.id).where(
                MassRun.account_id == str(account_id),
                MassRun.sent_at.is_not(None),
                MassRun.sent_at >= datetime.utcnow() - _BLAST_SCRAPE_WINDOW,
            ).limit(1)
        )).first()
    return hit is not None


async def _scrape_allowed(account_id: str, *, s=None) -> bool:
    """Does a registered gate (`relay_hooks.blast_scrape_gates`) allow the
    after-blast scrape on this account? Any yes → yes; none registered → no.
    Each gate owns its own reading (and its reasons), over the one session
    passed in."""
    if not relay_hooks.blast_scrape_gates:
        return False
    async with _reader(s) as s:
        for gate in relay_hooks.blast_scrape_gates:
            if await gate(s, account_id):
                return True
    return False


async def _scrape_after_blast(account_id: str, fan_id: int, *, blasted: bool | None = None,
                              scrape_allowed: bool | None = None) -> None:
    """First inbound from a fan after a blast → one bounded `scrape_fan` job for
    HIM, now, but ONLY when a registered scrape gate allows it. Never raises:
    this is an inbox repair, and the chat dispatch it sits in front of must not
    care whether it worked.

    Gated per Creator by `_scrape_allowed` (the plugin gates), and NOT on
    `_load_config` (W7's own switch). Background reads must peek (a first-page
    thread GET marks the chat read on OF): the scrape's page 1 does. A gate
    answers per account, not per blast or fan.

    What the scrape brings back is the newest rows since his last scrape — his
    inbound, our replies, and the blast copy with its real id, media and
    `raw_json.queueId`. The promise is THE COPY, not "the gap closes": a fan with
    more than 100 rows since a days-old cursor keeps his middle gap, because
    `_fetch_recent_end` stops at 100 and the cursor then jumps to the newest id.
    The blast, sent under an hour ago, is always inside that newest 100."""
    try:
        if not (blasted if blasted is not None else await _blasted_recently(account_id)):
            return
        if not (scrape_allowed if scrape_allowed is not None else await _scrape_allowed(account_id)):
            return
        await enqueue_fan_scrape(account_id, fan_id, "blast_reply")
    except Exception:
        log.warning("blast_reply_scrape_failed account=%s fan=%s",
                    account_id, fan_id, exc_info=True)


async def enqueue_fan_scrape(account_id: str, fan_id: int, source: str) -> bool:
    """One bounded one-fan `scrape_fan` job `{"fan_ids": [fan], "source": source}`
    (scrape_chats' handler on the sender lane, its own run key: never queued behind
    the account's sweep, automations/scrape_chats.py), due now, supervisor woken, unless the fan's scrape is claimed inside
    `_FAN_SCRAPE_DEDUP_S`: the other triggers (a blast reply, a gen_info pick) share one
    claim, so they make one job per fan per window. A Click read's backfill
    (DEFERRED_HISTORY_SOURCE) has its own claim, which also covers the others: theirs
    keep a deferred row's asc pass deferred, so it must never be swallowed by one of them.
    True = this call enqueued it. Never raises.
    ⚠️ NO AWAIT BETWEEN THE CHECK AND THE SET (`decide.blast_claim` is sync): that is
    what makes two concurrent triggers produce one job instead of two."""
    try:
        global _fan_scrape_claims
        key, now = (str(account_id), int(fan_id)), time.monotonic()
        if source == DEFERRED_HISTORY_SOURCE:
            key = (*key, DEFERRED_HISTORY_SOURCE)
        else:
            clicked_at = _fan_scrape_claims.get((*key, DEFERRED_HISTORY_SOURCE))
            if clicked_at is not None and now - clicked_at < _FAN_SCRAPE_DEDUP_S:
                return False
        claimed, _fan_scrape_claims = decide.blast_claim(
            _fan_scrape_claims, key, now, _FAN_SCRAPE_DEDUP_S, _FAN_SCRAPE_CLAIM_MAX)
        if not claimed:
            return False
        await ax.enqueue_job(
            account_id, "scrape_fan",
            payload={"fan_ids": [int(fan_id)], "source": source},
            run_at=datetime.utcnow())
        ax.wake_supervisor()
        log.info("fan_scrape source=%s account=%s fan=%s", source, account_id, fan_id)
        return True
    except Exception:
        log.warning("fan_scrape_failed source=%s account=%s fan=%s",
                    source, account_id, fan_id, exc_info=True)
        return False


# ── A deferred chat's backfill (fetch-diet phase-03) ───────────────────
# A `{}` sweep keeps page 1 of a Silent mass-only chat, or the recent end of an unread one, and
# defers its deep history (`scrape_history.history_deferred_at`, automations/scrape_chats.py). Only a Click read
# (a plain head read or a landed mark-as-read, deferred_history_wiring.py) buys the backfill's asc pass, source
# DEFERRED_HISTORY_SOURCE: the read already marked the chat read on OF. A gen_info
# thin-history pick (GEN_INFO_PICK_SOURCE) or any other one-fan scrape walks the recent end
# only and keeps the deferral. His DM buys nothing: it would only hold the fan's claim.
DEFERRED_HISTORY_SOURCE = "deferred_history"
GEN_INFO_PICK_SOURCE = "gen_info_pick"


async def history_deferred(account_id: str, fan_id: int, *, s=None) -> bool:
    """Is the fan's chat history deferred (a ScrapeHistory row with the mark set)?"""
    async with _reader(s) as s:
        at = (await s.execute(
            select(ScrapeHistory.history_deferred_at).where(
                ScrapeHistory.account_id == str(account_id),
                ScrapeHistory.fan_id == int(fan_id))
        )).scalar_one_or_none()
    return at is not None


async def backfill_if_deferred(account_id: str, fan_id: int) -> None:
    """The Click read trigger (a plain head read or a landed mark-as-read of the chat): a deferred chat gets its
    backfill. Never raises."""
    try:
        if await history_deferred(account_id, fan_id):
            await enqueue_fan_scrape(account_id, fan_id, DEFERRED_HISTORY_SOURCE)
    except Exception:
        log.warning("fan_scrape_failed source=%s account=%s fan=%s",
                    DEFERRED_HISTORY_SOURCE, account_id, fan_id, exc_info=True)


async def _dispatch_inbound(account_id: str, fan_id: int, message_id: int) -> None:
    """on_inbound_message's body, under its per-fan serial: load -> plan -> apply."""
    # Every read below goes through ONE session (one pool checkout per DM,
    # not one per question); the writes (enqueue_job) keep their own.
    async with get_session() as s:
        try:
            blasted = await _blasted_recently(account_id, s=s)
        except Exception:   # an inbox repair: must not cost the dispatch
            log.warning("blast_reply_scrape_failed account=%s fan=%s",
                        account_id, fan_id, exc_info=True)
            blasted = False
        # Read only after a blast (most DMs skip it); fail closed: a gate
        # that raises is a no.
        scrape_allowed = False
        if blasted:
            try:
                scrape_allowed = await _scrape_allowed(account_id, s=s)
            except Exception:
                log.warning("blast_reply_scrape_failed account=%s fan=%s",
                            account_id, fan_id, exc_info=True)
        cfg = await _load_config(account_id, s=s)
        if cfg is not None:
            kind, rule_id = await _classify(account_id, fan_id, s=s)
            # Read fresh, right here — a sender that paused this fan earlier
            # in the same tick must be visible (see _fan_paused_until).
            paused_until = await _fan_paused_until(account_id, fan_id, s=s) if kind is not None else None
            delay = _response_delay(cfg)
            now = datetime.utcnow()
            # Dedup over the FULL wait (cooldown remainder + delay) so a second
            # message during the rest doesn't queue its own deferred job.
            dup = kind is not None and await _has_imminent_pending_job(
                account_id, kind, fan_id, decide.dedup_within_s(paused_until, delay, now), s=s)

    # ── The blast this man may be answering (plans/blast-splice C.1) ──
    # Above every return below: its gate is the plugin scrape gate, not W7's
    # switch or his stage (see `_scrape_after_blast`). Own try/except inside.
    await _scrape_after_blast(account_id, fan_id, blasted=blasted, scrape_allowed=scrape_allowed)
    if cfg is None:
        return

    # A fan a human is handling, or one the bot just replied to, is on a
    # per-fan cooldown (W3's shared cross-tick guard, 45-90s for chat). Rather
    # than DROP this reply to the slow periodic sweep — fans usually reply
    # within ~30s, INSIDE the cooldown, so they'd always wait out the next
    # sweep — we DEFER the reply to the moment the cooldown ends. The chat
    # engines re-check the cooldown at run time, so if a human keeps the fan
    # paused the deferred job simply skips: deferring is safe either way (too
    # far out: decide.MAX_DEFER_S).
    act = decide.plan(kind, rule_id, fan_id, paused_until, delay, dup, now)
    if isinstance(act, decide.Skip):
        # terminal: skip-listed, or a stage whose rule is off — a human owns this
        # fan, don't wake a sweep for nothing. cooldown_far: the sweep catches it.
        log.debug("w7_skip_%s account=%s fan=%s until=%s",
                  act.reason, account_id, fan_id, paused_until)
        return
    if isinstance(act, decide.WakeOnly):
        log.debug("w7_skip_dedup account=%s kind=%s fan=%s", account_id, kind, fan_id)
        ax.wake_supervisor()  # still wake so the already-pending job drains
        return

    await ax.enqueue_job(account_id, kind, payload=act.payload, run_at=act.run_at)
    # Wake now if due immediately; otherwise wake once the (possibly deferred)
    # job is due so it doesn't wait for the next fallback tick.
    if act.wait_s > 0:
        _schedule_wake(act.wait_s)  # keeps a ref so the wake can't be GC'd
    else:
        ax.wake_supervisor()
    log.info(
        "w7_dispatch account=%s fan=%s kind=%s msg=%s wait=%.1fs%s",
        account_id, fan_id, kind, message_id, act.wait_s,
        " (deferred to cooldown end)" if act.deferred else "",
    )


# The window for a pending full_ai_chat job, whenever it is due: Shadow's are due
# now, or JOB_RETRY_BACKOFF_S out after a failed attempt; a live job waits its
# reply speed (≤ 3600 s, full_ai_live.due) or a busy retry's 20 s.
# ASSUMPTION: a day's window covers every pending job (rung 5); overturned if a
# producer ever queues one further out.
_FULL_AI_PENDING_S = 86400.0


async def _full_ai_hook(account_id: str, fan_id: int, message_id: int) -> None:
    """Full AI Chat in Shadow mode sees every inbound DM of a Creator whose
    `full_ai_chat` rule is on: one one-Fan job anchored on this DM, beside (not
    instead of) W7's dispatch, whatever its gate or `_classify` say. The job only
    decides and records (ADR-0033). A pending job whose catch-up decides this
    DM's Turn too (`full_ai_chat.decides`) makes it only wake. A rule in Mode
    live instead queues the Fan's reply at its reply speed (`full_ai_live.enqueue`)
    unless the checkpoint's `reply_by_webhook` is off (then the sweep answers).
    Own try: a failure here never costs W7's reply. Never raises."""
    try:
        rule_id = await ax.enabled_rule_id(account_id, "full_ai_chat")
        if rule_id is None:
            return
        from automations import full_ai_chat, full_ai_live, full_ai_turn   # lazy: imports widely
        live = await full_ai_live.live_rule(account_id)
        if live is not None:
            cfg = (await full_ai_turn.stored_config(account_id))["checkpoint"]
            if cfg["reply_by_webhook"]:
                await full_ai_live.enqueue(account_id, fan_id, message_id, live)   # wakes at run_at
            return
        hit = await _imminent_pending_job(account_id, "full_ai_chat", fan_id, _FULL_AI_PENDING_S)
        if hit is not None and await full_ai_chat.decides(account_id, fan_id, hit[1], message_id):
            ax.wake_supervisor()
            return
        await ax.enqueue_job(account_id, "full_ai_chat", payload={
            "only_fan_ids": [int(fan_id)], "anchor": int(message_id), "_rule_id": rule_id})
        ax.wake_supervisor()
    except Exception:
        log.warning("full_ai_hook_failed account=%s fan=%s", account_id, fan_id, exc_info=True)


@write_telemetry.labelled("webhook_dispatch")
async def on_inbound_message(account_id: str, fan_id: int, message_id: int) -> None:
    """React to one inbound fan DM: enqueue + wake the owning sweep so the bot
    replies in seconds instead of at the next tick; then Full AI's hook, even
    when W7's dispatch failed. Never raises."""
    try:
        if _global_kill_switch():
            return
        # One dispatch per (account, fan) at a time: the second DM of a burst
        # reads the pending jobs only after the first one's insert (_fan_serial).
        # Taken before the read session so a waiter holds no pool connection.
        async with _fan_serial(account_id, fan_id):
            try:
                await _dispatch_inbound(account_id, fan_id, message_id)
            except Exception:   # a W7 failure must not mute Full AI's hook below
                log.warning(
                    "w7_dispatch_failed account=%s fan=%s", account_id, fan_id, exc_info=True
                )
            await _full_ai_hook(account_id, fan_id, message_id)   # own try inside
    except Exception:
        log.warning(
            "w7_dispatch_failed account=%s fan=%s", account_id, fan_id, exc_info=True
        )


@write_telemetry.labelled("webhook_dispatch")
async def on_inbound_tip(account_id: str, fan_id: int, message_id: int,
                         tip_cents: int) -> None:
    """A fan just tipped → mark a customs order owed (when customs_watch is on).
    Gated SEPARATELY from the W7 reply dispatch above: it should fire even on a
    terminal-stage fan that no chat automation would reply to. Never raises."""
    # ── customs: mark him owed NOW, not up to 15 minutes from now ──────
    #
    # `customs_watch` sweeps on a 900s rule, so a man could tip $200 for a voice
    # note and wait up to 15 minutes before anything recorded that he had bought
    # one. The tip's `Transaction` row is ALREADY written live by
    # `event_transcoder._record_inbound_payment` (the WS frame carries the dollars
    # in `tipAmount`), so the sweep's own data is there within a second — only the
    # CADENCE was slow. This closes that window to one job hop.
    try:
        from automations.customs_watch import order_floor, watch_flags
        cw_on, cw_payload = await watch_flags(account_id)
        # GATED ON THE RULE, and that gate is load-bearing: a $100 DM tip is an
        # ORDER on the male accounts and was GENEROSITY five times last month on
        # the female ones. Firing this account-blind would gag the bot on every
        # generous fan — Amia alone took 47 such tips in 90 days.
        if cw_on and int(tip_cents or 0) >= order_floor(cw_payload):
            # ENQUEUE THE SWEEP, DO NOT MARK INLINE. Marking here would be a second
            # expression of "is this tip an order?" — it would have to restate the
            # settled-status filter, the `customs_cleared_at` re-mark guard and the
            # already-delivered check. This codebase's own lesson is that a safety
            # property restated in two voices is a safety property with no owner
            # (the since-removed customs sell fence shipped exactly that drift). So the fast
            # path runs the SAME `run`, scoped to one fan and carrying the rule's
            # own payload, so the floor and dry_run cannot diverge.
            await ax.enqueue_job(
                account_id, "customs_watch",
                payload={**cw_payload, "only_fan_ids": [int(fan_id)]},
            )
            ax.wake_supervisor()
            log.info("customs_watch_dispatch account=%s fan=%s msg=%s cents=%s",
                     account_id, fan_id, message_id, tip_cents)
    except Exception:
        log.warning("customs_watch_dispatch_failed account=%s fan=%s",
                    account_id, fan_id, exc_info=True)


@write_telemetry.labelled("webhook_dispatch")
async def on_inbound_image(account_id: str, fan_id: int, message_id: int,
                           has_media: bool = True) -> None:
    """A fan sent media (a non-tip photo/clip DM, or a Giphy gif) → hand the words
    off to `on_inbound_message`. `event_transcoder` does not fire
    `on_inbound_message` for a media DM (see its `is_media_dm`), so the words for
    it are this hook's to hand off, on every path.

    `has_media=False` = the DM carried no media, only a Giphy id; the hand-off
    is the same either way. Never raises."""
    await on_inbound_message(account_id, fan_id, message_id)
    log.info("image_dispatch account=%s fan=%s msg=%s media=%s",
             account_id, fan_id, message_id, has_media)
