"""automations/full_ai_look.py — Full AI live's last look (spec 04a seam 4, ticket 66), moved out of
`full_ai_live`.

`LAST_LOOK` is one ordered check list: each slot's loader (fresh every call) fills `look.facts[name]`,
then its check reads only those facts; the first reason stands the Turn down. `full_ai_live` runs it as
the job's pre-look (before the Router), the sweep's pre-look (`Look.client` None: no OF read) and before
each bubble; `gate` runs it again as the bubble's `before_write` (after the account write
gate's grant, right before the POST), DB and in-process caches only (`Look.of_read` False: no OF read,
the Fans list off its cache), then the global switch once more after its last read.

  Look                       what a check reads; checks do no I/O
  LAST_LOOK                  the slots (name, loader, check)
  last_look(look)            run the slots in order -> (name, reason) | None; a broken loader / check
                             is reason "error" (fail closed); a lost Run slot propagates
  gate(look)                 `LAST_LOOK` on a no-OF-read copy of the bubble's look, then the switch; a reason
                             raises `Stand`
  after_look(look, why)      what a look leaves (never raises): his newest OF item it read saved, a
                             human's OF-app answer starts the Human yield
  newest_inbound(aid, fan)   his newest inbound DM in `messages` (created_at, message_id)

No OF client factory, lease, DM rate or send (AST scan in test_full_ai_live.py).
"""
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
    """What a last-look check reads; checks do no I/O (spec 04a › Interfaces)."""
    account_id: str
    fan_id: int
    anchor: tuple[datetime, int]         # the Turn's Anchor (created_at, message_id)
    client: Any | None                   # the job's OF client; None on the sweep's pre-look
    row: dict | None                     # the Turn's row dict, row["id"] set once reserved; None on the pre-look
    bubble: dict | None                  # {"text"} | {"text","ppv":{...}} | {"gif","tag"}; None on the pre-look
    index: int                           # bubble index; -1 on the pre-look
    sent: int                            # bubbles of this Turn already on OF
    facts: dict[str, Any] = field(default_factory=dict)   # each loader's result, keyed by check name
    before_write: Callable[[], Awaitable[None]] | None = None   # the sender's `of_write_paced` hook (`gate`)
    of_read: bool = True                 # False: `gate`'s re-look, no OF read (Fans list cached only)


Check = Callable[[Look], "str | None"]          # None = go; str = stand-down reason
Loader = Callable[[Look], Awaitable[Any]]       # reads only; the one write allowed is 05's settle_pull


async def newest_inbound(account_id: str, fan_id: int) -> tuple[datetime, int] | None:
    """His newest inbound DM in `messages`: (created_at, message_id), or None."""
    async with get_session() as s:
        got = (await s.execute(select(Message.created_at, Message.message_id).where(
            Message.account_id == account_id, Message.fan_id == fan_id,
            Message.direction == "in").order_by(Message.created_at.desc(), Message.message_id.desc())
            .limit(1))).first()
    return tuple(got) if got is not None else None


def _of_newest(look: Look) -> dict | None:
    """His newest OF item after the Anchor the off_switch slot's OF read saw (`OwnerFacts.fan_newest`)."""
    return getattr(look.facts.get("off_switch"), "fan_newest", None)


async def _newest_inbound(look: Look) -> tuple[datetime, int] | None:
    """His newest inbound DM (created_at, message_id): the newer of `messages` and the off_switch slot's OF
    read (an item not saved yet; `after_look` saves it). Reads only."""
    db = await newest_inbound(look.account_id, look.fan_id)
    item = _of_newest(look)
    at = full_ai_owner.of_time(item.get("createdAt")) if item is not None else None
    of = (at, int(item["id"])) if at is not None else None
    return max((x for x in (db, of) if x is not None), default=None)


def overtaken(look: Look) -> str | None:
    """He wrote again after the Anchor and none of her bubbles is out yet: the next Turn answers both."""
    newest = look.facts.get("overtaken")
    return "overtaken" if look.sent == 0 and newest is not None and tuple(newest) > tuple(look.anchor) else None


async def _owner(look: Look) -> full_ai_owner.OwnerFacts:
    """04b's facts (`full_ai_owner_io.load`), once per look. The OF-app read (a client needed, so never
    the sweep's; never the gate's): the job's pre-look, the look before the Turn's first bubble out, and
    the look before its `ppv` bubble (a human may answer while the Writer runs: measured 2026-11-16); every
    other bubble's look reads the DB only. The gate's (`of_read` False) reads the Fans list off its cache
    only (`cached`: never an OF crawl after the write gate's grant; a miss = not listed). This Turn's sent
    bubbles (`message_id` on its parts) count as ours."""
    read = look.of_read and look.client is not None and (look.sent == 0 or "ppv" in (look.bubble or {}))
    ours = {int(p["message_id"]) for p in ((look.row or {}).get("reply_json") or {}).get("parts") or ()
            if isinstance(p, dict) and p.get("message_id")}
    return await full_ai_owner_io.load(look.account_id, look.fan_id, look.anchor[0], client=look.client,
                                       live_read=read, ours=ours, cached=not look.of_read)


def _owned_by(look: Look, mine) -> str | None:
    """`who_owns`' reason over the off_switch slot's facts, when `mine(reason)`."""
    stop = full_ai_owner.who_owns(look.facts["off_switch"])
    return stop.reason if stop is not None and mine(stop.reason) else None


def off_switch(look: Look) -> str | None:
    return _owned_by(look, full_ai_owner.OFF_REASONS.__contains__)


def fans_list(look: Look) -> str | None:
    return _owned_by(look, "not_listed".__eq__)


def who_owns(look: Look) -> str | None:
    """Every other `who_owns` reason (the complement: a new reason stops the Turn here)."""
    return _owned_by(look, lambda r: r not in (*full_ai_owner.OFF_REASONS, "not_listed", *full_ai_owner.HUMAN_REASONS))


def human_yield(look: Look) -> str | None:
    return _owned_by(look, full_ai_owner.HUMAN_REASONS.__contains__)


async def _offer_facts(look: Look) -> tuple[list, full_ai_owned.Sold] | None:
    """05's facts, for the bubble that carries `ppv` only: settle first (a landed unconfirmed
    Offer links and stops blocking), then the Fan's fresh live rows and what he bought anywhere."""
    if not look.bubble or "ppv" not in look.bubble:
        return None
    await full_ai_settle.settle_pull(look.account_id, look.fan_id)
    async with get_session() as s:
        rows = list((await s.execute(select(AiDecision).where(
            AiDecision.account_id == look.account_id, AiDecision.fan_id == look.fan_id,
            AiDecision.mode == MODE).order_by(AiDecision.id))).scalars())
    return rows, await full_ai_owned.load_sold(look.account_id, look.fan_id)


def offer_valid(look: Look) -> str | None:
    """"owned" (he came to own a piece of it) | "unconfirmed" (a priced Offer of ours may be on
    OF unseen) | None. This Turn's own row (reserved from bubble 1 on) is not read: a Free item's
    row would count its own media as Owned (`owned_of`)."""
    got = look.facts.get("offer_valid")
    if got is None:
        return None
    own = (look.row or {}).get("id")
    rows, sold = [r for r in got[0] if r.id != own], got[1]
    return full_ai_owned.offer_still_valid(look.bubble["ppv"], full_ai_owned.owned_live(rows, sold.cross), rows,
                                           datetime.utcnow(), own)


# Ordered; first reason wins. Pinned slots (spec 04a seam 4): off_switch, fans_list, who_owns,
# human_yield (04b), overtaken (here), offer_valid (05). Others add one tuple at their slot.
LAST_LOOK: list[tuple[str, Loader | None, Check]] = [
    ("off_switch", _owner, off_switch),
    ("fans_list", None, fans_list),
    ("who_owns", None, who_owns),
    ("human_yield", None, human_yield),
    ("overtaken", _newest_inbound, overtaken),
    ("offer_valid", _offer_facts, offer_valid),
]


async def last_look(look: Look) -> tuple[str, str] | None:
    """Run `LAST_LOOK` in order: each loader (fresh every call) into `look.facts[name]`, then its check;
    the first reason wins. A loader or check that raises stands down with reason "error" (fail closed:
    never a bubble on a broken read); a lost Run slot still propagates."""
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
    """`gate` stood the bubble down after the write gate's grant: nothing sent."""

    def __init__(self, why: tuple[str, str], look: Look):
        super().__init__("%s:%s" % why)
        self.why, self.look = why, look


async def gate(look: Look) -> None:
    """`before_write` of every bubble's POST (after the write gate's grant): every `LAST_LOOK` slot again on a
    no-OF-read copy of the bubble's look (its own look made the OF read just before), so a switch flipped, a
    human's answer, his new DM or his purchase of the media during the gate wait (`_offer_facts`: `ppv`
    bubbles only) still stops it; then the global switch once more, after the slots' last await (no read
    between it and the claim). Raises `Stand` (a failed read too: fail closed)."""
    g = replace(look, facts={}, before_write=None, of_read=False)
    why = await last_look(g)
    if why is None and (off := full_ai_owner_io.global_off()) is not None:
        why = ("off_switch", off)
    if why is not None:
        raise Stand(why, g)


async def after_look(look: Look, why: tuple[str, str] | None) -> None:
    """What a job's look leaves behind; never raises. His newest OF item the look read (`OwnerFacts.fan_newest`)
    is saved (`scrape_chats.upsert_message`): the after-burst check and his next Turn read `messages`. A
    stand-down on a human's OF-app answer (`human_of_app`, given with its time) starts the Human yield: the
    next Turns rest too."""
    try:    # the yield first, on its own: a failed save must not leave a human's chat unrested
        if why == ("human_yield", "human_of_app"):
            await full_ai_owner_io.start_human_yield(look.account_id, look.fan_id, look.facts["off_switch"].human_at)
    except Exception:  # noqa: BLE001 — the look's verdict stands
        log.warning("full_ai_live human yield start failed account=%s fan=%s", look.account_id, look.fan_id,
                    exc_info=True)
    try:
        item = _of_newest(look)
        if item is not None:
            from automations.scrape_chats import upsert_message   # lazy: scrape_chats imports widely
            await upsert_message(look.account_id, look.fan_id, str(getattr(look.client, "user_id", "") or ""), item)
    except Exception:  # noqa: BLE001 — the look's verdict stands
        log.warning("full_ai_live after look save failed account=%s fan=%s", look.account_id, look.fan_id,
                    exc_info=True)
