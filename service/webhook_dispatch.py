from __future__ import annotations

import logging
import asyncio
import contextlib
import json
import os
import random
import time
import weakref
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from db import write_telemetry
from db.engine import get_session
from db.models import (
    AccountAiConfig, Fan, FunnelState, MassRun, ScheduledJob,
    ScrapeHistory, SkipList,
)
import automation_executor as ax
import platforms
import relay_hooks
import webhook_dispatch_decide as decide
from automation_registry import kind_family

log = logging.getLogger("of-relay.webhook_dispatch")


# Two DMs of one fan ms apart would both read "no pending job" before either inserts: one lock per (account, fan).
_fan_locks: weakref.WeakValueDictionary[tuple[str, int], asyncio.Lock] = weakref.WeakValueDictionary()


def _fan_serial(account_id: str, fan_id: int) -> asyncio.Lock:
    key = (str(account_id), int(fan_id))
    return _fan_locks.get(key) or _fan_locks.setdefault(key, asyncio.Lock())

# List-audience blasts write no per-fan row: one bounded scrape on the first inbound lands the real copy inside the 4h window before mass unsend (~34 calls/day measured).
_BLAST_SCRAPE_WINDOW = timedelta(minutes=60)
_FAN_SCRAPE_DEDUP_S = 600
# In-process claim, not a pending-job scan: a RUNNING or FINISHED job would not stop a chatty fan buying a scrape per message; no await between check and set.
_fan_scrape_claims: dict[tuple[str, int], float] = {}
_FAN_SCRAPE_CLAIM_MAX = 4096


def _global_kill_switch() -> bool:
    import runtime_switches
    return runtime_switches.on("W7_WEBHOOK_DISPATCH_DISABLED")


@contextlib.asynccontextmanager
async def _reader(s):
    if s is not None:
        yield s
    else:
        async with get_session() as fresh:
            yield fresh


async def _load_config(account_id: str, *, s=None) -> dict | None:
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
    base = max(0.0, float(cfg.get("delay_seconds") or 0))
    jitter = max(0.0, float(cfg.get("jitter_seconds") or 0))
    return base + (random.uniform(0.0, jitter) if jitter > 0 else 0.0)


# asyncio.create_task keeps only a weak ref: a fire-and-forget wake can be GC'd mid-sleep and land minutes late.
_wake_tasks: set = set()


def _schedule_wake(delay_s: float) -> None:
    t = asyncio.create_task(_wake_after(delay_s))
    _wake_tasks.add(t)
    t.add_done_callback(_wake_tasks.discard)


async def _wake_after(delay_s: float) -> None:
    try:
        if delay_s > 0:
            await asyncio.sleep(delay_s)
        ax.wake_supervisor()
    except Exception:  # pragma: no cover — defensive
        pass


async def _fan_mid_funnel(account_id: str, fan_id: int, *, s=None) -> bool:
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
    return (await _classify(account_id, fan_id))[0]


async def _rule_gate(account_id: str, fan_id: int, kind: str, *, s=None) -> tuple[str | None, int | None]:
    rule_id = await ax.enabled_rule_id(account_id, kind, session=s)
    if rule_id is None:
        log.info("w7_skip_rule_off account=%s fan=%s kind=%s", account_id, fan_id, kind)
        return None, None
    return kind, rule_id


async def _classify(account_id: str, fan_id: int, *, s=None) -> tuple[str | None, int | None]:
    # Waking welcome_chatter_for_info for a skip-listed fan does nothing and the fan gets no reply.
    if await _fan_mid_funnel(account_id, fan_id, s=s):
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

    if skip is not None:
        return None, None

    return await _rule_gate(account_id, fan_id, "welcome_chatter_for_info", s=s)


async def _fan_paused_until(account_id: str, fan_id: int, *, s=None) -> datetime | None:
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
    return (await _imminent_pending_jobs(account_id, kind, [fan_id], within_s, s=s)).get(int(fan_id))


async def _imminent_pending_jobs(
    account_id: str, kind: str, fan_ids, within_s: float, *, s=None
) -> dict[int, tuple[datetime, dict]]:
    soon = datetime.utcnow() + timedelta(seconds=within_s)
    async with _reader(s) as s:
        rows = (
            await s.execute(
                select(ScheduledJob.run_at, ScheduledJob.payload_json).where(
                    ScheduledJob.account_id == str(account_id),
                    # kind_family: a pre-rename pending job must still dedup; this guard stands between a fan and a double send.
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
    return await _imminent_pending_job(account_id, kind, fan_id, within_s, s=s) is not None


async def _blasted_recently(account_id: str, *, s=None) -> bool:
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
    if not relay_hooks.blast_scrape_gates:
        return False
    async with _reader(s) as s:
        for gate in relay_hooks.blast_scrape_gates:
            if await gate(s, account_id):
                return True
    return False


async def _scrape_after_blast(account_id: str, fan_id: int, *, blasted: bool | None = None,
                              scrape_allowed: bool | None = None) -> None:
    try:
        if not (blasted if blasted is not None else await _blasted_recently(account_id)):
            return
        if not (scrape_allowed if scrape_allowed is not None else await _scrape_allowed(account_id)):
            return
        await enqueue_fan_scrape(account_id, fan_id, "blast_reply")
    except Exception:
        log.warning("blast_reply_scrape_failed account=%s fan=%s",
                    account_id, fan_id, exc_info=True)


async def enqueue_fan_scrape(account_id: str, fan_id: int, source: str, *, peek_only: bool = False) -> bool:
    key = (str(account_id), int(fan_id))
    clicked_at = _fan_scrape_claims.get((*key, "click"))
    if clicked_at is not None and time.monotonic() - clicked_at < _FAN_SCRAPE_DEDUP_S:
        return False
    payload = {"fan_ids": [key[1]], "source": source}
    if peek_only:
        payload["peek_only"] = True
    return await _enqueue_claimed(key, payload)


async def _enqueue_claimed(key: tuple, payload: dict) -> bool:
    global _fan_scrape_claims
    account_id, fan_id = key[:2]
    source = payload["source"]
    try:
        claimed, _fan_scrape_claims = decide.blast_claim(
            _fan_scrape_claims, key, time.monotonic(), _FAN_SCRAPE_DEDUP_S, _FAN_SCRAPE_CLAIM_MAX)
        if not claimed:
            return False
        await ax.enqueue_job(account_id, "scrape_fan", payload=payload, run_at=datetime.utcnow())
        ax.wake_supervisor()
        log.info("fan_scrape source=%s account=%s fan=%s", source, account_id, fan_id)
        return True
    except Exception:
        log.warning("fan_scrape_failed source=%s account=%s fan=%s",
                    source, account_id, fan_id, exc_info=True)
        return False


DEFERRED_HISTORY_SOURCE = "deferred_history"
GEN_INFO_PICK_SOURCE = "gen_info_pick"


async def history_deferred(account_id: str, fan_id: int, *, s=None) -> bool:
    async with _reader(s) as s:
        at = (await s.execute(
            select(ScrapeHistory.history_deferred_at).where(
                ScrapeHistory.account_id == str(account_id),
                ScrapeHistory.fan_id == int(fan_id))
        )).scalar_one_or_none()
    return at is not None


async def backfill_if_deferred(account_id: str, fan_id: int, at: int) -> None:
    try:
        if await history_deferred(account_id, fan_id):
            await _enqueue_claimed((str(account_id), int(fan_id), "click"), {
                "fan_ids": [int(fan_id)],
                "source": DEFERRED_HISTORY_SOURCE,
                "after_click_at": datetime.fromtimestamp(at / 1000, UTC).isoformat(),
            })
    except Exception:
        log.warning("fan_scrape_failed source=%s account=%s fan=%s",
                    DEFERRED_HISTORY_SOURCE, account_id, fan_id, exc_info=True)


async def _dispatch_inbound(account_id: str, fan_id: int, message_id: int) -> None:
    async with get_session() as s:
        try:
            blasted = await _blasted_recently(account_id, s=s)
        except Exception:
            log.warning("blast_reply_scrape_failed account=%s fan=%s",
                        account_id, fan_id, exc_info=True)
            blasted = False
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
            paused_until = await _fan_paused_until(account_id, fan_id, s=s) if kind is not None else None
            delay = _response_delay(cfg)
            now = datetime.utcnow()
            dup = kind is not None and await _has_imminent_pending_job(
                account_id, kind, fan_id, decide.dedup_within_s(paused_until, delay, now), s=s)

    await _scrape_after_blast(account_id, fan_id, blasted=blasted, scrape_allowed=scrape_allowed)
    if cfg is None:
        return

    # Defer to the moment the cooldown ends rather than drop to the slow sweep: fans reply inside the 45-90 s cooldown.
    act = decide.plan(kind, rule_id, fan_id, paused_until, delay, dup, now)
    if isinstance(act, decide.Skip):
        log.debug("w7_skip_%s account=%s fan=%s until=%s",
                  act.reason, account_id, fan_id, paused_until)
        return
    if isinstance(act, decide.WakeOnly):
        log.debug("w7_skip_dedup account=%s kind=%s fan=%s", account_id, kind, fan_id)
        ax.wake_supervisor()
        return

    await ax.enqueue_job(account_id, kind, payload=act.payload, run_at=act.run_at)
    if act.wait_s > 0:
        _schedule_wake(act.wait_s)
    else:
        ax.wake_supervisor()
    log.info(
        "w7_dispatch account=%s fan=%s kind=%s msg=%s wait=%.1fs%s",
        account_id, fan_id, kind, message_id, act.wait_s,
        " (deferred to cooldown end)" if act.deferred else "",
    )


_FULL_AI_PENDING_S = 86400.0


async def _full_ai_hook(account_id: str, fan_id: int, message_id: int) -> None:
    try:
        rule_id = await ax.enabled_rule_id(account_id, "full_ai_chat")
        if rule_id is None:
            return
        from automations import full_ai_chat, full_ai_live, full_ai_turn
        live = await full_ai_live.live_rule(account_id)
        if live is not None:
            cfg = (await full_ai_turn.stored_config(account_id))["checkpoint"]
            if cfg["reply_by_webhook"]:
                await full_ai_live.enqueue(account_id, fan_id, message_id, live)
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
    try:
        if _global_kill_switch():
            return
        async with _fan_serial(account_id, fan_id):
            try:
                await _dispatch_inbound(account_id, fan_id, message_id)
            except Exception:
                log.warning(
                    "w7_dispatch_failed account=%s fan=%s", account_id, fan_id, exc_info=True
                )
            await _full_ai_hook(account_id, fan_id, message_id)
    except Exception:
        log.warning(
            "w7_dispatch_failed account=%s fan=%s", account_id, fan_id, exc_info=True
        )


@write_telemetry.labelled("webhook_dispatch")
async def on_inbound_tip(account_id: str, fan_id: int, message_id: int,
                         tip_cents: int) -> None:
    try:
        from automations.customs_watch import order_floor, watch_flags
        if platforms.lack_refusal(account_id, platforms.Lack.TIP_LEDGER):
            return
        cw_on, cw_payload = await watch_flags(account_id)
        # Gated on the rule: a $100 DM tip is an order on male accounts but generosity on female ones; firing account-blind would gag the bot.
        if cw_on and int(tip_cents or 0) >= order_floor(cw_payload):
            # Enqueue the sweep, never mark inline: a second statement of "is this tip an order?" would drift from the customs rule.
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
    await on_inbound_message(account_id, fan_id, message_id)
    log.info("image_dispatch account=%s fan=%s msg=%s media=%s",
             account_id, fan_id, message_id, has_media)
