from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Awaitable, Callable

from sqlalchemy import select

import run_slot
from automations import full_ai_owned, full_ai_owner, full_ai_owner_io, full_ai_settle
from db.engine import get_session
from db.models import AiDecision, Message

log = logging.getLogger("of-relay.automation.full_ai_live")

MODE = "live"


@dataclass(frozen=True)
class Look:
    account_id: str
    fan_id: int
    anchor: tuple[datetime, int]
    client: Any | None
    row: dict | None
    bubble: dict | None
    index: int
    sent: int
    facts: dict[str, Any] = field(default_factory=dict)
    before_write: Callable[[], Awaitable[None]] | None = None
    of_read: bool = True


Check = Callable[[Look], "str | None"]
Loader = Callable[[Look], Awaitable[Any]]


async def newest_inbound(account_id: str, fan_id: int) -> tuple[datetime, int] | None:
    async with get_session() as s:
        got = (await s.execute(select(Message.created_at, Message.message_id).where(
            Message.account_id == account_id, Message.fan_id == fan_id,
            Message.direction == "in").order_by(Message.created_at.desc(), Message.message_id.desc())
            .limit(1))).first()
    return tuple(got) if got is not None else None


def _of_newest(look: Look) -> dict | None:
    return getattr(look.facts.get("off_switch"), "fan_newest", None)


async def _newest_inbound(look: Look) -> tuple[datetime, int] | None:
    db = await newest_inbound(look.account_id, look.fan_id)
    item = _of_newest(look)
    at = full_ai_owner.of_time(item.get("createdAt")) if item is not None else None
    of = (at, int(item["id"])) if at is not None else None
    return max((x for x in (db, of) if x is not None), default=None)


def overtaken(look: Look) -> str | None:
    newest = look.facts.get("overtaken")
    return "overtaken" if look.sent == 0 and newest is not None and tuple(newest) > tuple(look.anchor) else None


async def _owner(look: Look) -> full_ai_owner.OwnerFacts:
    read = look.of_read and look.client is not None and (look.sent == 0 or "ppv" in (look.bubble or {}))
    ours = {int(p["message_id"]) for p in ((look.row or {}).get("reply_json") or {}).get("parts") or ()
            if isinstance(p, dict) and p.get("message_id")}
    return await full_ai_owner_io.load(look.account_id, look.fan_id, look.anchor[0], client=look.client,
                                       live_read=read, ours=ours, cached=not look.of_read)


def _owned_by(look: Look, mine) -> str | None:
    stop = full_ai_owner.who_owns(look.facts["off_switch"])
    return stop.reason if stop is not None and mine(stop.reason) else None


def off_switch(look: Look) -> str | None:
    return _owned_by(look, full_ai_owner.OFF_REASONS.__contains__)


def fans_list(look: Look) -> str | None:
    return _owned_by(look, "not_listed".__eq__)


def who_owns(look: Look) -> str | None:
    return _owned_by(look, lambda r: r not in (*full_ai_owner.OFF_REASONS, "not_listed", *full_ai_owner.HUMAN_REASONS))


def human_yield(look: Look) -> str | None:
    return _owned_by(look, full_ai_owner.HUMAN_REASONS.__contains__)


async def _offer_facts(look: Look) -> tuple[list, full_ai_owned.Sold] | None:
    if not look.bubble or "ppv" not in look.bubble:
        return None
    await full_ai_settle.settle_pull(look.account_id, look.fan_id)
    async with get_session() as s:
        rows = list((await s.execute(select(AiDecision).where(
            AiDecision.account_id == look.account_id, AiDecision.fan_id == look.fan_id,
            AiDecision.mode == MODE).order_by(AiDecision.id))).scalars())
    return rows, await full_ai_owned.load_sold(look.account_id, look.fan_id)


def offer_valid(look: Look) -> str | None:
    got = look.facts.get("offer_valid")
    if got is None:
        return None
    own = (look.row or {}).get("id")
    rows, sold = [r for r in got[0] if r.id != own], got[1]
    return full_ai_owned.offer_still_valid(look.bubble["ppv"], full_ai_owned.owned_live(rows, sold.cross), rows,
                                           datetime.utcnow(), own)


LAST_LOOK: list[tuple[str, Loader | None, Check]] = [
    ("off_switch", _owner, off_switch),
    ("fans_list", None, fans_list),
    ("who_owns", None, who_owns),
    ("human_yield", None, human_yield),
    ("overtaken", _newest_inbound, overtaken),
    ("offer_valid", _offer_facts, offer_valid),
]


async def last_look(look: Look) -> tuple[str, str] | None:
    for name, loader, check in LAST_LOOK:
        try:
            if loader is not None:
                look.facts[name] = await loader(look)
            reason = check(look)
        except run_slot.SlotLost:
            raise
        except Exception:  # noqa: BLE001 — a broken check never lets a bubble through
            log.warning("full_ai_live last look failed account=%s fan=%s check=%s",
                        look.account_id, look.fan_id, name, exc_info=True)
            reason = "error"
        if reason:
            return name, str(reason)
    return None


class Stand(Exception):

    def __init__(self, why: tuple[str, str], look: Look):
        super().__init__("%s:%s" % why)
        self.why, self.look = why, look


# Re-looks without OF reads after the write gate's grant; the global switch is checked once more after the last await.
async def gate(look: Look) -> None:
    g = replace(look, facts={}, before_write=None, of_read=False)
    why = await last_look(g)
    if why is None and (off := full_ai_owner_io.global_off()) is not None:
        why = ("off_switch", off)
    if why is not None:
        raise Stand(why, g)


# Yield first, on its own: a failed save must not leave a human's chat unrested.
async def after_look(look: Look, why: tuple[str, str] | None) -> None:
    try:
        if why == ("human_yield", "human_of_app"):
            await full_ai_owner_io.start_human_yield(look.account_id, look.fan_id, look.facts["off_switch"].human_at)
    except Exception:  # noqa: BLE001 — the look's verdict stands
        log.warning("full_ai_live human yield start failed account=%s fan=%s", look.account_id, look.fan_id,
                    exc_info=True)
    try:
        item = _of_newest(look)
        if item is not None:
            from automations.scrape_chats import upsert_message
            await upsert_message(look.account_id, look.fan_id, str(getattr(look.client, "user_id", "") or ""), item)
    except Exception:  # noqa: BLE001 — the look's verdict stands
        log.warning("full_ai_live after look save failed account=%s fan=%s", look.account_id, look.fan_id,
                    exc_info=True)
