#!/usr/bin/env python3
"""
event_transcoder — which inbound DM clears the money feeds' cache (phase-01 story 52).

The money feeds (`relay_cache._MONEY_FEED_NAMESPACES`: the notifications feed, its
badge counts and the chat pins) are cleared by `invalidate_money_feeds`. An inbound
`api2_chat_message` used to clear them on every DM; now only a frame that can move
money does:

  plain DM      isTip false and price 0          -> the money feeds stay cached
  tip DM        isTip true (any tipAmount)        -> cleared
  priced DM     price above 0                     -> cleared
  unclassifiable  isTip or price missing / not a bool or a number -> cleared

Unchanged by it: every inbound DM still drops `roster_count` (the unread badge).

Run: ./venv/bin/python service/tests/test_event_transcoder_money_bust.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import itertools  # noqa: E402

import event_transcoder as et  # noqa: E402
import relay_cache  # noqa: E402
import webhook_dispatch  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account  # noqa: E402

_AID = "8826001"
_FAN = 777260
_MONEY = (("notifications", (10, 0, "tip")), ("notifications_count", ()), ("chat_pinned", (_FAN,)))
_ids = itertools.count(2_600_000_001)


async def _noop(*_a, **_k):
    return None


webhook_dispatch.on_inbound_message = _noop  # type: ignore[assignment]
webhook_dispatch.on_inbound_tip = _noop      # type: ignore[assignment]
webhook_dispatch.on_inbound_image = _noop    # type: ignore[assignment]


async def _seed_account() -> None:
    async with get_session() as s:
        if await s.get(Account, _AID) is None:
            s.add(Account(id=_AID))


async def _drain() -> None:
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _warm(ns: str, extras: tuple) -> None:
    relay_cache.invalidate(ns, _AID)
    await relay_cache.get_or_fetch(ns, _AID, extras, 300.0, lambda: {"warm": True})


async def _kept(ns: str, extras: tuple) -> bool:
    """True when the cached body is still served (a cleared entry fetches anew)."""
    got = await relay_cache.get_or_fetch(ns, _AID, extras, 300.0, lambda: {"warm": False})
    return got == {"warm": True}


def _dm(**fields) -> dict:
    """An inbound api2_chat_message (a plain DM); `fields` override, a value of `...` drops the field."""
    m = {"id": next(_ids), "text": "<p>hey</p>", "price": 0, "isTip": False,
         "fromUser": {"id": _FAN}, "createdAt": "2026-11-09T10:00:00+00:00", "responseType": "message"}
    for k, v in fields.items():
        if v is ...:
            m.pop(k, None)
        else:
            m[k] = v
    return {"api2_chat_message": m, "__account_id": _AID}


async def _money_after(frame: dict) -> dict[str, bool]:
    """Each money namespace -> kept, after one inbound frame."""
    await _seed_account()
    for ns, extras in _MONEY:
        await _warm(ns, extras)
    await et.transcode(frame)
    await _drain()
    return {ns: await _kept(ns, extras) for ns, extras in _MONEY}


_ALL_KEPT = {ns: True for ns, _ in _MONEY}
_ALL_CLEARED = {ns: False for ns, _ in _MONEY}


async def case_plain_dm_keeps_the_money_feeds():
    for label, frame in (("price 0", _dm()), ("price 0.0", _dm(price=0.0)),
                         ("isFree, no media", _dm(isFree=True, mediaCount=0, media=[]))):
        got = await _money_after(frame)
        assert got == _ALL_KEPT, (label, got)


async def case_tip_dm_clears_them():
    for label, frame in (("tipAmount 10, price 0", _dm(isTip=True, tipAmount=10)),
                         ("no tipAmount, price 5", _dm(isTip=True, price=5.0)),
                         ("degenerate $0 tip", _dm(isTip=True, tipAmount=0))):
        got = await _money_after(frame)
        assert got == _ALL_CLEARED, (label, got)


async def case_priced_dm_clears_them():
    for label, frame in (("price 9.99", _dm(price=9.99)), ("price 3 (int)", _dm(price=3))):
        got = await _money_after(frame)
        assert got == _ALL_CLEARED, (label, got)


async def case_unclassifiable_dm_clears_them():
    for label, frame in (("no isTip", _dm(isTip=...)), ("no price", _dm(price=...)),
                         ("price null", _dm(price=None)), ("price a string", _dm(price="0")),
                         ("isTip not a bool", _dm(isTip=None)), ("neither", _dm(isTip=..., price=...))):
        got = await _money_after(frame)
        assert got == _ALL_CLEARED, (label, got)


async def case_plain_dm_still_drops_the_unread_badge():
    await _seed_account()
    await _warm("roster_count", ())
    await et.transcode(_dm())
    await _drain()
    assert not await _kept("roster_count", ()), "a plain DM must still drop roster_count"


_harness.run()
