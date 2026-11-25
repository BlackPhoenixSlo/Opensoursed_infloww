from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from automations import full_ai_config
from isotime import parse_iso

log = logging.getLogger("of-relay.automation.full_ai_catchup")

# Most recent chats a pass reads and the most Turns it queues; 200 was too many.
CHATS = 40
MAX_AGE_S = 7 * 86400
SCRAPE_GRACE_S = 60
SOURCE = "full_ai_catchup"
BOOT_DELAY_S = 60
RECONNECT_DELAY_S = 10

_sleep = asyncio.sleep
_tasks: dict[str, asyncio.Task] = {}


Schedule = tuple[tuple[int, ...], int]


def schedule(cfg: dict | None) -> Schedule:
    cm = (cfg or {}).get("catchup_minutes")
    if full_ai_config.catchup_error(cm) is not None:
        cm = full_ai_config.DEFAULTS["catchup_minutes"]
    return tuple(60 * m for m in cm["after_live"]), 60 * cm["then_every"]


DEFAULT_SCHEDULE: Schedule = schedule(None)


def offset_s(step: int, sched: Schedule = DEFAULT_SCHEDULE) -> int:
    first, every = sched
    if step < len(first):
        return first[step]
    return first[-1] + every * (step - len(first) + 1)


def gap_s(step: int, sched: Schedule = DEFAULT_SCHEDULE) -> int:
    return offset_s(step + 1, sched) - offset_s(step, sched)


async def _schedule(account_id: str) -> Schedule:
    from automations import full_ai_turn
    try:
        return schedule((await full_ai_turn.stored_config(account_id))["checkpoint"])
    except Exception:  # noqa: BLE001 — a bad read never ends the loop
        log.warning("full_ai_catchup_config_failed account=%s", account_id, exc_info=True)
        return DEFAULT_SCHEDULE


def waiting(rows: list[dict], account_id: str, now: datetime) -> list[dict]:
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
    # Skip, not None: the loop keeps its schedule and resumes once the Creator is healthy; the dispatcher would never run its jobs.
    if runtime_switches.on(full_ai_owner_io.OFF_SWITCH):
        return {"skipped": "off_switch"}
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
    if first := offset_s(0, await _schedule(account_id)):
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
    aid = str(account_id)
    stop(aid)
    task = asyncio.get_running_loop().create_task(_loop(aid, delay_s), name=f"full-ai-catchup:{aid}")
    _tasks[aid] = task
    task.add_done_callback(lambda t: _tasks.pop(aid, None) if _tasks.get(aid) is t else None)
    return task


# OF's socket replays nothing after a drop: DMs sent meanwhile never arrive as frames.
def reconnected(account_id: str) -> None:
    if str(account_id) in _tasks:
        start(account_id, RECONNECT_DELAY_S)


def stop(account_id: str) -> None:
    task = _tasks.pop(str(account_id), None)
    if task is not None:
        task.cancel()


async def boot() -> None:
    from automations import full_ai_live
    for aid in sorted(await full_ai_live.live_accounts()):
        start(aid, BOOT_DELAY_S)
