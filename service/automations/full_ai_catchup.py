"""automations/full_ai_catchup.py — Full AI Chat's waiting-chats catch-up (owner 2026-11-15).

Fans may already wait when a Creator goes Live (unread chats he wrote last, never seen on the
socket: written before Live, or during a disconnect / deploy). Per Creator in Live a process-local
loop runs a pass at Live (PUT /admin/full-ai/mode `start`), or `BOOT_DELAY_S` after relay start
(`boot`: a deploy's reads not all at once with the socket connects), then +5 min, +15 min, then every
25 min: the checkpoint's `catchup_minutes` (`schedule`; read before each wait, so a saved change bites
at the next wait without a restart; an unreadable or invalid one runs the defaults). Off (`stop`) or a
rule no longer live ends it. A pass (`run_pass`): OF's top `CHATS` chats, most recent first
(`chats_page`, paced as a background walk) -> the chats whose last message is the Fan's and at most `MAX_AGE_S` old
(`waiting`, pure) -> those Full AI claims (`full_ai_owner_io.claimed_ids`) -> their last message
saved as the inbox saves it (`messages.reconcile_chats_from_of`, insert-only) and, when it was not
in `messages`, a one-Fan scrape (`webhook_dispatch.enqueue_fan_scrape`) -> the sweep's checks over
just them (`full_ai_live.catchup_queue`: no row on the Turn key, no pending job, no cooldown, a
clear pre-look) -> one Turn each. Sends nothing; a scrape GET never marks a chat read.

The OF client comes from `full_ai_live.catchup_client` (the only Full AI module naming the client
factory, test_full_ai_live.py's AST scan).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from automations import full_ai_config
from isotime import parse_iso

log = logging.getLogger("of-relay.automation.full_ai_catchup")

CHATS = 200                     # OF's most recent chats a pass reads (and the most Turns it queues)
MAX_AGE_S = 7 * 86400           # an older waiting DM is left to humans (owner to confirm)
SCRAPE_GRACE_S = 60             # a DM only just saved: its Turn waits this long for the chat's scrape
SOURCE = "full_ai_catchup"      # the one-Fan scrape's source and the walk's kind
BOOT_DELAY_S = 60               # relay start: the first pass waits this long (Mode -> Live: at once)

_sleep = asyncio.sleep          # tests swap it
_tasks: dict[str, asyncio.Task] = {}


Schedule = tuple[tuple[int, ...], int]     # (pass offsets in s from the loop's start, then every s)


def schedule(cfg: dict | None) -> Schedule:
    """A side's `catchup_minutes` in seconds; missing or invalid (`full_ai_config.catchup_error`) = DEFAULTS'.
    Pure."""
    cm = (cfg or {}).get("catchup_minutes")
    if full_ai_config.catchup_error(cm) is not None:
        cm = full_ai_config.DEFAULTS["catchup_minutes"]
    return tuple(60 * m for m in cm["after_live"]), 60 * cm["then_every"]


DEFAULT_SCHEDULE: Schedule = schedule(None)   # 0, +5, +15 min, then every 25 min


def offset_s(step: int, sched: Schedule = DEFAULT_SCHEDULE) -> int:
    """Seconds from the loop's start to pass `step`."""
    first, every = sched
    if step < len(first):
        return first[step]
    return first[-1] + every * (step - len(first) + 1)


def gap_s(step: int, sched: Schedule = DEFAULT_SCHEDULE) -> int:
    """The wait after pass `step`."""
    return offset_s(step + 1, sched) - offset_s(step, sched)


async def _schedule(account_id: str) -> Schedule:
    """The Creator's checkpoint schedule (what live runs on); a failed read runs the defaults."""
    from automations import full_ai_turn
    try:
        return schedule((await full_ai_turn.stored_config(account_id))["checkpoint"])
    except Exception:  # noqa: BLE001 — a bad read never ends the loop
        log.warning("full_ai_catchup_config_failed account=%s", account_id, exc_info=True)
        return DEFAULT_SCHEDULE


def waiting(rows: list[dict], account_id: str, now: datetime) -> list[dict]:
    """OF chat items (of the first `CHATS`) whose last message is the Fan's own and at most
    `MAX_AGE_S` old, one per Fan, in OF's order."""
    out, seen = [], set()
    for ch in rows[:CHATS]:
        fan = (ch.get("withUser") or {}).get("id")
        lm = ch.get("lastMessage") or {}
        sender = (lm.get("fromUser") or {}).get("id")
        at = parse_iso(lm.get("createdAt"))
        if fan is None or lm.get("id") is None or sender is None or at is None:
            continue
        if str(sender) != str(fan) or str(sender) == str(account_id) or int(fan) in seen:
            continue
        if now - at > timedelta(seconds=MAX_AGE_S):
            continue
        seen.add(int(fan))
        out.append(ch)
    return out


async def run_pass(account_id: str) -> dict | None:
    """One catch-up pass; None when the Creator is not Live (the loop ends). Stats: `chats` read,
    `waiting`, `claimed`, `saved` (DMs not in `messages` before), the sweep's `swept` / `queued`."""
    import account_health
    import chats_page
    import messages
    import of_pacing
    import runtime_switches
    import webhook_dispatch
    from sqlalchemy import select

    from automations import full_ai_live, full_ai_owner_io
    from db.engine import get_session
    from db.models import Message
    aid, now = str(account_id), datetime.utcnow()
    if await full_ai_live.live_rule(aid) is None:
        return None
    if runtime_switches.on(full_ai_owner_io.OFF_SWITCH):
        return {"skipped": "off_switch"}
    # The dispatcher's gate (automation_executor.run_once): its jobs would never run, so no OF read.
    # A skip, not None: the loop keeps its schedule and resumes once the Creator is healthy.
    if await account_health.is_deactivated(aid):
        return {"skipped": "account_deactivated"}
    if await account_health.is_session_dead(aid):
        return {"skipped": "session_dead"}
    client = await full_ai_live.catchup_client(aid)
    page = await of_pacing.walk(aid, SOURCE, lambda: asyncio.to_thread(
        chats_page.assemble_chats_page, client, limit=CHATS, offset=0, order="recent"))
    picks = waiting(page.rows, aid, now)
    claimed = await full_ai_owner_io.claimed_ids(aid, [c["withUser"]["id"] for c in picks], client=client)
    picks = [c for c in picks if int(c["withUser"]["id"]) in claimed]
    missing: set[int] = set()
    if picks:
        mids = {int(c["lastMessage"]["id"]): int(c["withUser"]["id"]) for c in picks}
        async with get_session() as s:
            have = {(int(f), int(m)) for f, m in (await s.execute(select(Message.fan_id, Message.message_id).where(
                Message.account_id == aid, Message.message_id.in_(list(mids))))).all()}
        missing = {f for m, f in mids.items() if (f, m) not in have}
        await messages.reconcile_chats_from_of(aid, picks)
        for fan in sorted(missing):
            await webhook_dispatch.enqueue_fan_scrape(aid, fan, SOURCE)
    res = await full_ai_live.catchup_queue(
        aid, sorted(int(c["withUser"]["id"]) for c in picks), max_age_s=MAX_AGE_S, cap=CHATS,
        late=missing, not_before=datetime.utcnow() + timedelta(seconds=SCRAPE_GRACE_S))
    out = {"chats": len(page.rows), "waiting": len(picks), "claimed": len(claimed), "saved": len(missing), **res}
    log.info("full_ai_catchup account=%s %s", aid, " ".join(f"{k}={v}" for k, v in out.items()))
    return out


async def _loop(account_id: str, delay_s: float = 0) -> None:
    if delay_s:
        await _sleep(delay_s)
    if first := offset_s(0, await _schedule(account_id)):   # after_live not starting at 0
        await _sleep(first)
    step = 0
    while True:
        try:
            if await run_pass(account_id) is None:
                return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a failed pass never ends the schedule
            log.warning("full_ai_catchup_failed account=%s step=%d", account_id, step, exc_info=True)
        await _sleep(gap_s(step, await _schedule(account_id)))
        step += 1


def start(account_id: str, delay_s: float = 0) -> asyncio.Task:
    """(Re)start the Creator's schedule: after `delay_s` (0: at once), passes on `catchup_minutes` (`schedule`; default 0/5/15, then 25)."""
    aid = str(account_id)
    stop(aid)
    task = asyncio.get_running_loop().create_task(_loop(aid, delay_s), name=f"full-ai-catchup:{aid}")
    _tasks[aid] = task
    task.add_done_callback(lambda t: _tasks.pop(aid, None) if _tasks.get(aid) is t else None)
    return task


def stop(account_id: str) -> None:
    """Mode Off: the Creator's schedule ends (a pass in flight is cancelled)."""
    task = _tasks.pop(str(account_id), None)
    if task is not None:
        task.cancel()


async def boot() -> None:
    """Relay start: every Creator already Live starts its schedule, first pass in `BOOT_DELAY_S`."""
    from automations import full_ai_live
    for aid in sorted(await full_ai_live.live_accounts()):
        start(aid, BOOT_DELAY_S)
