"""_full_ai_live_fixtures — the live sender's send-path world (tickets 65, 66), over
`_full_ai_live_helpers` (its `world`, `seed_live`, `live_rows`, `clear_pause`).

`world()` = the helpers' world with a `LiveOF` and `dm_rate` turns / releases counted
(`World.turns`, `World.released`; `slot_lost(n)` true raises `run_slot.SlotLost` on rate turn n,
1-based). Temp DB only (the caller's `_harness`). Every id here is invented.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select, text

from _full_ai_fixtures import KIND, QUIET, _msg
from _full_ai_live_helpers import HOSTS, clear_pause, live_rows, seed_live
from _full_ai_live_helpers import world as _helpers_world
from _of_fixtures import FakeOF
import dm_rate
import run_slot
from db.engine import get_session
from db.models import Fan, Message

__all__ = ["LINE3", "LiveOF", "World", "world", "seed_live", "live_rows", "clear_pause", "dm", "payload",
           "out_rows", "leases", "paused"]
# Three bubbles after the reply chain for most fans (callers that need >= 3 assert it).
LINE3 = "ok:omg hiii babe. i just got out of the shower lol. what are u up to tonight?"


class LiveOF(FakeOF):
    """FakeOF whose `before(n, text)` runs before DM n (1-based) is taken and `after(n, text)`
    once OF took it: raise there to kill the run mid-send (`asyncio.CancelledError` = a relay
    stop) or fail the send."""

    def __init__(self, before: Callable[[int, str], None] | None = None,
                 after: Callable[[int, str], None] | None = None, **kw):
        super().__init__(**kw)
        self.before, self.after = before, after
        self.calls = 0

    def send_message(self, chat_id, text, **kw) -> dict:
        self.calls += 1
        if self.before is not None:
            self.before(self.calls, text)
        res = super().send_message(chat_id, text, **kw)
        if self.after is not None:
            self.after(self.calls, text)
        return res


@dataclass
class World:
    of: LiveOF
    jev: Any
    writer: Any
    turns: int = 0
    released: int = 0


@contextlib.contextmanager
def world(of: LiveOF | None = None, *, line: str = LINE3, jev=(QUIET, 1.0),
          slot_lost: Callable[[int], bool] | None = None):
    of = of or LiveOF()
    real_turn, real_release = dm_rate.turn, dm_rate.release
    with _helpers_world(of, jev, writers=dict.fromkeys(HOSTS, line)) as (_of, jevs, _info, fw):
        w = World(of, jevs, fw)

        async def turn(account_id, **kw):
            if "release_budget_s" not in kw:    # the sender's own turn under the loop's: no new place
                return await real_turn(account_id, **kw)
            w.turns += 1
            if slot_lost is not None and slot_lost(w.turns):
                raise run_slot.SlotLost("test: slot lost")
            return await real_turn(account_id, **kw)

        def release(account_id):
            w.released += 1
            return real_release(account_id)

        dm_rate.turn, dm_rate.release = turn, release
        try:
            yield w
        finally:
            dm_rate.turn, dm_rate.release = real_turn, real_release


async def dm(aid: str, fan: int, mid: int, body: str = "hey you, how was your day", *,
             ago_s: int = 30) -> None:
    await _msg(aid, fan, mid, "in", body, datetime.utcnow() - timedelta(seconds=ago_s))


def payload(fan: int, mid: int, rule_id: int) -> dict:
    return {"only_fan_ids": [fan], "anchor": mid, "_rule_id": rule_id}


async def out_rows(aid: str, fan: int) -> list[Message]:
    async with get_session() as s:
        return list((await s.execute(select(Message).where(
            Message.account_id == aid, Message.fan_id == fan, Message.direction == "out",
            Message.automation_kind == KIND).order_by(Message.created_at, Message.message_id))).scalars())


async def leases(aid: str) -> list[tuple]:
    async with get_session() as s:
        return [tuple(r) for r in (await s.execute(text(
            "SELECT * FROM fan_lease WHERE account_id = :a"), {"a": aid})).all()]


async def paused(aid: str, fan: int) -> datetime | None:
    async with get_session() as s:
        return (await s.execute(select(Fan.automation_paused_until).where(
            Fan.account_id == aid, Fan.fan_id == fan))).scalar_one_or_none()
