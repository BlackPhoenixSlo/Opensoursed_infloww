#!/usr/bin/env python3
"""test_full_ai_human_yield — Human yield (spec 04b ticket 79): pure tables, the loader's `human` fact over a
temp DB and a faked OF client, and `start_human_yield`'s cooldown.

  case_of_app_human_table     empty; only Fan items; our own row; a queue (mass) item; a creator item older than
                              the anchor; newer -> its time; no fromUser -> its time; two hits -> the earliest
  case_queue_id_matches       the pure queue-id read agrees with messages._queue_id_of on the same frames
  case_yield_left_table       fresh = full; half elapsed; elapsed = 0; disabled (0) = 0
  case_loader_rows            employee-stamped outbound after the anchor -> "human"; before -> None; tagged
                              full_ai_chat / welcome_chatter_for_info / reply_mass_funnel -> None; an untagged mass
                              copy -> None; an untagged one-off -> "human"
  case_loader_no_live_read    live_read False: 0 OF calls
  case_loader_live_read       live_read True, Full AI on: exactly 1 OF call (off: none); an unknown creator item -> "human_of_app" + its
                              time; rows win over the OF app; the client raising -> None
  case_who_owns_order         human / human_of_app below off, list, hard skip, audience; above funnel_walk
  case_start_human_yield      default -> paused ~60 s after sent_at; manual_yield_minutes 60 -> ~1 h; a send older
                              than the yield -> no write; fan_on_cooldown reads true / false; a longer rest stays

Run: ./venv/bin/python service/tests/test_full_ai_human_yield.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import contextlib  # noqa: E402
import dataclasses  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import fan_lease  # noqa: E402
from automations import full_ai_owner as fo  # noqa: E402
from automations import full_ai_owner_io as io  # noqa: E402
from automations.full_ai_owner import OwnerFacts, Stop, of_app_human, who_owns, yield_left_s  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, AutomationRule, Employee, Fan, Message  # noqa: E402
from messages_unsent import _queue_id_of  # noqa: E402

FAN = 4242
T = datetime(2026, 11, 15, 12, 0, 0)
_ids = itertools.count(7_000_000_000_000)
_n = 0


def _item(at: datetime, *, sender: int | None = 1, mid: int | None = None, **kw) -> dict:
    m = {"id": mid if mid is not None else next(_ids), "createdAt": at.isoformat() + "+00:00", "text": "x", **kw}
    if sender is not None:
        m["fromUser"] = {"id": sender}
    return m


def case_of_app_human_table():
    a = T
    f = lambda items, known=frozenset(): of_app_human(items, fan_id=FAN, anchor_at=a, known_ids=set(known))  # noqa: E731
    later, later2 = a + timedelta(minutes=2), a + timedelta(minutes=1)
    ours = _item(later, mid=99)
    assert f([]) is None
    assert f([_item(later, sender=FAN), _item(later2, sender=FAN)]) is None
    assert f([ours], {99}) is None                                    # our own row
    assert f([_item(later, queueId=123)]) is None                     # a mass copy
    assert f([_item(later, queueId="456")]) is None
    assert f([_item(a - timedelta(minutes=1))]) is None               # older than the anchor
    assert f([_item(a)]) is None                                      # at the anchor: not newer
    assert f([_item(later)]) == later                                 # a creator item, newer
    assert f([_item(later, sender=None)]) == later                    # no fromUser = human
    assert f([{**_item(later), "fromUser": {}}]) == later             # no readable sender id = human
    assert f([_item(later), _item(later2)]) == later2                 # the earliest of two
    assert f([_item(later, queueId=True)]) == later                   # a bool queueId is not one
    assert f([{**_item(later), "createdAt": "nonsense"}]) is None     # no readable time
    z = {"id": 5, "createdAt": "2026-11-15T12:03:00Z", "fromUser": {"id": 1}}
    assert f([z]) == datetime(2026, 11, 15, 12, 3)
    off = {"id": 6, "createdAt": "2026-11-15T14:03:00+02:00", "fromUser": {"id": 1}}
    assert f([off]) == datetime(2026, 11, 15, 12, 3)
    assert f(["junk", None, _item(later)]) == later


def case_queue_id_matches():
    for frame in ({"queueId": 1}, {"queueId": "12"}, {"queueId": "x"}, {"queueId": True}, {"queueId": None},
                  {}, {"queueId": 3.0}):
        assert fo.queue_id(frame) == _queue_id_of(json.dumps(frame)), frame


def case_yield_left_table():
    assert yield_left_s(T, T, 60) == 60
    assert yield_left_s(T, T + timedelta(seconds=30), 60) == 30
    assert yield_left_s(T, T + timedelta(seconds=60), 60) == 0
    assert yield_left_s(T, T + timedelta(hours=2), 60) == 0
    assert yield_left_s(T, T, 0) == 0
    assert yield_left_s(T, T + timedelta(minutes=30), 3600) == 1800


async def _account(*, yield_minutes: float | None = None) -> str:
    global _n
    _n += 1
    aid = f"acc-hy-{_n}"
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(AutomationRule(account_id=aid, name="Full AI Chat", kind="full_ai_chat", trigger_json="{}",
                             steps_json="{}", is_enabled=True))
        if yield_minutes is not None:
            s.add(AccountAiConfig(account_id=aid,
                                  webhook_config_json=json.dumps({"manual_yield_minutes": yield_minutes})))
    return aid


async def _out(aid: str, at: datetime, body: str = "typed for u", fan: int = FAN, **kw) -> int:
    mid = next(_ids)
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=mid, direction="out", body=body, created_at=at, **kw))
    return mid


async def _employee() -> int:
    async with get_session() as s:
        e = Employee(display_name=f"chatter{next(_ids)}")
        s.add(e)
        await s.flush()
        return e.id


class ChatOF:
    def __init__(self, items: list[dict] | None = None, *, fail: bool = False):
        self.items, self.fail, self.calls = items or [], fail, []

    def get_messages(self, chat_id, *, limit=10, **kw):
        self.calls.append((int(chat_id), limit))
        if self.fail:
            raise RuntimeError("OF 500")
        return {"list": self.items, "hasMore": False}


async def case_loader_rows():
    emp = await _employee()
    anchor = datetime.utcnow() - timedelta(minutes=10)
    aid = await _account()
    await _out(aid, anchor + timedelta(minutes=1), sent_by_employee_id=emp)
    assert (await io.load(aid, FAN, anchor)).human == "human"
    before = await _account()
    await _out(before, anchor - timedelta(minutes=1), sent_by_employee_id=emp)
    assert (await io.load(before, FAN, anchor)).human is None
    for kind in ("full_ai_chat", "welcome_chatter_for_info", "reply_mass_funnel"):
        tagged = await _account()
        await _out(tagged, anchor + timedelta(minutes=1), automation_kind=kind)
        assert (await io.load(tagged, FAN, anchor)).human is None, kind
    mass = await _account()                                           # one body to 5 fans = a mass copy
    for fan in range(FAN, FAN + 5):
        await _out(mass, anchor + timedelta(minutes=1), body="new set out now 🔥", fan=fan)
    assert (await io.load(mass, FAN, anchor)).human is None
    untagged = await _account()                                       # a one-off from the OF app, synced
    await _out(untagged, anchor + timedelta(minutes=1), body="just for u")
    assert (await io.load(untagged, FAN, anchor)).human == "human"


async def case_loader_no_live_read():
    aid = await _account()
    fake = ChatOF([_item(datetime.utcnow())])
    f = await io.load(aid, FAN, datetime.utcnow() - timedelta(minutes=5), client=fake, live_read=False)
    assert f.human is None and fake.calls == [], (f, fake.calls)


@contextlib.contextmanager
def _live():
    """Full AI on for every Creator (`_live` true): the OF-app read runs only then (ticket 81)."""
    real = io._live

    async def on(_account_id):
        return True
    io._live = on
    try:
        yield
    finally:
        io._live = real


async def case_loader_live_read():
    with _live():
        await _loader_live_read()
    off = await _account()                     # Full AI off (`_live` false = off_mode): no OF read
    fake = ChatOF([_item(datetime.utcnow())])
    f = await io.load(off, FAN, datetime.utcnow() - timedelta(minutes=5), client=fake, live_read=True)
    assert (f.off, f.human, fake.calls) == ("off_mode", None, []), (f, fake.calls)


async def _loader_live_read():
    anchor = datetime.utcnow().replace(microsecond=0) - timedelta(minutes=10)
    aid = await _account()
    ours = await _out(aid, anchor + timedelta(minutes=1), automation_kind="full_ai_chat")
    sent = anchor + timedelta(minutes=3)
    fake = ChatOF([_item(anchor + timedelta(minutes=4), sender=FAN), _item(anchor + timedelta(minutes=1), mid=ours),
                   _item(sent)])
    f = await io.load(aid, FAN, anchor, client=fake, live_read=True)
    assert (f.human, f.human_at) == ("human_of_app", sent), f
    assert fake.calls == [(FAN, 10)], fake.calls
    only_ours = ChatOF([_item(anchor + timedelta(minutes=1), mid=ours)])
    assert (await io.load(aid, FAN, anchor, client=only_ours, live_read=True)).human is None
    assert len(only_ours.calls) == 1
    # rows win over the OF app
    rows = await _account()
    await _out(rows, anchor + timedelta(minutes=2), sent_by_employee_id=await _employee())
    both = ChatOF([_item(sent)])
    f = await io.load(rows, FAN, anchor, client=both, live_read=True)
    assert (f.human, f.human_at) == ("human", None), f
    # the read failing = no Stop
    broken = ChatOF(fail=True)
    f = await io.load(aid, FAN, anchor, client=broken, live_read=True)
    assert f.human is None and len(broken.calls) == 1, f
    # no client = no read
    assert (await io.load(aid, FAN, anchor, client=None, live_read=True)).human is None


def case_who_owns_order():
    clear = OwnerFacts(off=None, listed=True, hard_skip=False, audience_ok=True, human=None, human_at=None,
                       walk_advancing=False, spend_cents=0, top_spend_cents=100000)
    for h in ("human", "human_of_app"):
        hf = dataclasses.replace(clear, human=h, human_at=T)
        assert who_owns(hf) == Stop(h)
        assert who_owns(dataclasses.replace(hf, walk_advancing=True, spend_cents=10**9)) == Stop(h)
        for above, change in (("off_mode", {"off": "off_mode"}), ("not_listed", {"listed": False}),
                              ("hard_skip", {"hard_skip": True}), ("audience", {"audience_ok": False})):
            assert who_owns(dataclasses.replace(hf, **change)) == Stop(above), (h, above)


async def _paused(aid: str) -> datetime | None:
    async with get_session() as s:
        fan = await s.get(Fan, (aid, FAN))
    return fan.automation_paused_until if fan else None


def _near(a: datetime, b: datetime, slack_s: float = 5) -> bool:
    return abs((a - b).total_seconds()) <= slack_s


async def case_start_human_yield():
    now = datetime.utcnow()
    aid = await _account()                                            # default 60 s
    sent = now - timedelta(seconds=20)
    await io.start_human_yield(aid, FAN, sent)
    until = await _paused(aid)
    assert until is not None and _near(until, sent + timedelta(seconds=60)), (until, sent)
    assert await fan_lease.fan_on_cooldown(aid, FAN) is True
    hour = await _account(yield_minutes=60)
    await io.start_human_yield(hour, FAN, sent)
    assert _near(await _paused(hour), sent + timedelta(hours=1)), await _paused(hour)
    old = await _account()
    await io.start_human_yield(old, FAN, now - timedelta(minutes=5))  # older than the 60 s yield
    assert await _paused(old) is None
    assert await fan_lease.fan_on_cooldown(old, FAN) is False
    off = await _account(yield_minutes=0)                             # disabled
    await io.start_human_yield(off, FAN, now)
    assert await _paused(off) is None
    longer = await _account()                                         # a longer rest already stands
    far = now + timedelta(hours=3)
    async with get_session() as s:
        s.add(Fan(account_id=longer, fan_id=FAN, automation_paused_until=far))
    await io.start_human_yield(longer, FAN, now)
    assert await _paused(longer) == far


if __name__ == "__main__":
    _harness.run()
