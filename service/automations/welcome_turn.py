from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import select

import automation_executor as ax
from ._inbound import worded_inbound_where
from ._skiplist import is_hard_skipped
from db.engine import get_session
from db.models import Message


log = logging.getLogger("of-relay.automation.send_welcome")

# The only brake pacing a new sub's first reply: the fan lease is handed back on a confirmed send so the generic timeout cannot outrank it.
WELCOME_REST_S = 150

# Handoff must be due after WELCOME_REST_S or it dies on the send loop's own cooldown.
HANDOFF_DELAY_PAD_S = 15



async def newest_worded_inbound(account_id: str, fan_id: int
                                 ) -> tuple[datetime, int] | None:
    async with get_session() as s:
        row = (await s.execute(
            select(Message.created_at, Message.message_id).where(
                Message.account_id == str(account_id),
                Message.fan_id == int(fan_id),
                # Words decide, not type: a bare tip or captionless media is not a reply (tip rows can land 5 min late).
                Message.direction == "in",
                Message.is_unsent.is_(False),
                *worded_inbound_where(),
            )
            .order_by(Message.created_at.desc(), Message.message_id.desc())
            .limit(1)
        )).first()
    return (row[0], int(row[1])) if row is not None else None


async def fan_replied_since(account_id: str, fan_id: int,
                             anchor: tuple[datetime, int] | None
                             ) -> tuple[datetime, int] | None:
    try:
        # Compare inside the try: a None created_at TypeError must not kill the fan's whole welcome task; any failure reads as no reply.
        newest = await newest_worded_inbound(account_id, fan_id)
        if newest is None:
            return None
        return newest if (anchor is None or newest > anchor) else None
    except Exception:
        log.warning("send_welcome reply check failed account=%s fan=%s — "
                    "finishing the burst", account_id, fan_id, exc_info=True)
        return None


async def rule_enabled(account_id: str, kind: str) -> bool:
    return await ax.enabled_rule_id(account_id, kind) is not None


async def handoff_engine(account_id: str) -> str | None:
    if await rule_enabled(account_id, "welcome_chatter_for_info"):
        return "welcome_chatter_for_info"
    return None


async def enqueue_turn_handoff(account_id: str, fan_id: int) -> str | None:
    run_at = datetime.utcnow() + timedelta(
        seconds=WELCOME_REST_S + HANDOFF_DELAY_PAD_S)
    full_ai = await _full_ai_handoff(account_id, fan_id)
    if full_ai is not None:
        from automations import full_ai_live
        rule_id, anchor = full_ai
        await full_ai_live.enqueue(account_id, int(fan_id), anchor, rule_id, not_before=run_at)
        return "full_ai_chat"
    kind = await handoff_engine(account_id)
    if kind is None:
        return None
    await ax.enqueue_job(
        account_id, kind,
        payload={"only_fan_ids": [int(fan_id)], "force_ids": [int(fan_id)],
                 "turn_handoff_ids": [int(fan_id)]},
        run_at=run_at)
    return kind


async def _full_ai_handoff(account_id: str, fan_id: int) -> tuple[int, int] | None:
    try:
        from automations import full_ai_owner_io
        if int(fan_id) not in await full_ai_owner_io.claimed_ids(account_id, [int(fan_id)]):
            return None
        async with get_session() as s:
            anchor = (await s.execute(
                select(Message.message_id).where(
                    Message.account_id == str(account_id),
                    Message.fan_id == int(fan_id),
                    Message.direction == "in",
                    Message.is_unsent.is_(False),
                )
                .order_by(Message.created_at.desc(), Message.message_id.desc())
                .limit(1)
            )).scalar_one_or_none()
        if anchor is None:
            return None
        from automations import full_ai_live
        rule_id = await full_ai_live.live_rule(account_id)
        return None if rule_id is None else (int(rule_id), int(anchor))
    except Exception:
        log.warning("welcome handoff full_ai check failed account=%s fan=%s — "
                    "today's handoff", account_id, fan_id, exc_info=True)
        return None


class Landed(NamedTuple):
    created_at: datetime
    message_id: int
    provider_stamped: bool



async def hand_back_turn(
    account_id: str, fan_id: int, *,
    anchor: tuple[datetime, int] | None, check_reply: bool,
    aborted: tuple[datetime, int] | None, last_landed: Landed | None,
    landed: int,
) -> str:
    his_reply = aborted
    if check_reply and his_reply is None:
        his_reply = await fan_replied_since(account_id, fan_id, anchor)
    if his_reply is None:
        return "quiet"

    his_turn = last_landed is None or (
        last_landed.provider_stamped
        and his_reply > (last_landed.created_at, last_landed.message_id))
    log.info("send_welcome saw a reply mid-burst account=%s fan=%s "
             "landed=%d stopped=%s turn=%s", account_id, fan_id,
             landed, aborted is not None, "his" if his_turn else "handoff")
    if his_turn:
        return "his"
    try:
        if await is_hard_skipped(account_id, fan_id):
            log.info("send_welcome skipped the turn handoff for a restricted "
                     "fan account=%s fan=%s", account_id, fan_id)
            return "restricted"
        kind = await enqueue_turn_handoff(account_id, fan_id)
        if kind is None:
            log.warning("send_welcome ate a reply and this account runs no chat "
                        "engine account=%s fan=%s", account_id, fan_id)
            return "no_engine"
        log.info("send_welcome handed the turn to %s account=%s fan=%s",
                 kind, account_id, fan_id)
        return "handoff"
    except Exception:
        log.warning("send_welcome turn handoff failed account=%s fan=%s — his "
                    "welcome already landed", account_id, fan_id, exc_info=True)
        return "failed"
