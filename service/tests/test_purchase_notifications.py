#!/usr/bin/env python3
"""Purchase-notification → is_paid flip (service/purchase_notifications.py).

OF sends no purchase event on the WebSocket and the earnings ledger lands hours
late, so `GET users/notifications?type=purchases` is the only fresh signal that a
PPV was bought. It names the exact message id, which is what lets us skip the
payment→message linker entirely (that linker bails `ambiguous` whenever a fan
holds two unpaid same-priced PPVs — the bug that stranded offers on "waiting on
tip").

It is also the only thing that can TELL a chatter a sale landed: OF pushes no
purchase frame and no purchase toast, so the live announce added here is the
browser's sole real-time signal for a buy.

Proven here:
  * a real captured payload parses to (fan, message, amount);
  * a fresh buy announces exactly once, carrying OF's real notification id —
    the key the rail/bell dedupe on, so the ping and the eventual feed row
    collapse into one row instead of listing the sale twice;
  * the deep backfill NEVER announces (it walks months of old purchases);
  * a stale purchase does not ping, so a relay restart can't storm the tab;
  * a buy that lands while every tab is closed is NOT counted as announced —
    SSE has no mailbox, so it is re-offered until a browser is there to hear
    it, and then fires exactly once;
  * announcing does not wait on the is_paid flip, and a retrying notification
    still only pings once;
  * the flip is scoped — it never marks an INBOUND or a FREE message paid, and
    never touches another fan's message with the same id;
  * it is idempotent, so re-seeing the notification every 30s does nothing;
  * non-chat purchase subtypes and junk are ignored.

Run:
  cd service/tests && PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python \
      test_purchase_notifications.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import events  # noqa: E402
import purchase_notifications as pn  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Message  # noqa: E402

_ACC = "acc_pn"
_FAN = 800000741
_MSG = 10491720677794
_NOW = datetime(2026, 7, 21, 15, 26, 0)

# Captured verbatim from prod (account/fan ids are the ones under test).
_REAL = {
    "id": 117301756206,
    "type": "paided_message",
    "subType": "subscriber_pay_for_chat_message",
    "createdAt": "2026-07-21T15:26:00+00:00",
    "isRead": True,
    "text": ("has purchased your <a href='https://onlyfans.com/my/chats/chat/"
             "800000741?firstId=10491720677794'>message</a> for $6.00!"),
    "replacePairs": {
        "{NAME}": "Daniel",
        "{MESSAGE_LINK}": ("<a href='https://onlyfans.com/my/chats/chat/"
                           "800000741?firstId=10491720677794'>message</a>"),
        "{AMOUNT}": "$6.00",
    },
    "canGoToProfile": True,
}


class _FakeResp:
    def __init__(self, payload): self._p = payload
    def json(self): return self._p


class _FakeClient:
    """Only `get` is touched; returns the notifications envelope."""
    def __init__(self, items): self.items = items; self.calls = 0
    def get(self, path):
        self.calls += 1
        assert "type=purchases" in path, path
        return _FakeResp({"list": self.items})


async def _seed(*, msg_id: int = _MSG, fan_id: int = _FAN,
                direction: str = "out", price_cents: int = 600) -> None:
    async with get_session() as s:
        if await s.get(Account, _ACC) is None:
            s.add(Account(id=_ACC))
        if await s.get(Fan, (_ACC, fan_id)) is None:
            s.add(Fan(account_id=_ACC, fan_id=fan_id))
        s.add(Message(account_id=_ACC, fan_id=fan_id, message_id=msg_id,
                      direction=direction, price_cents=price_cents,
                      is_paid=False, created_at=_NOW))
        await s.commit()


async def _is_paid(msg_id: int = _MSG, fan_id: int = _FAN) -> bool:
    async with get_session() as s:
        m = await s.get(Message, (_ACC, fan_id, msg_id))
    return bool(m.is_paid) if m else False


# ── Parsing ──────────────────────────────────────────────────────────

async def case_parses_real_payload() -> None:
    p = pn.parse_purchase(_REAL)
    assert p is not None, "the real captured payload must parse"
    assert p["fan_id"] == _FAN, p
    assert p["message_id"] == _MSG, p           # the exact PPV bought
    assert p["amount_cents"] == 600, p          # "$6.00" → 600
    assert p["notif_id"] == 117301756206, p


async def case_ignores_non_chat_and_junk() -> None:
    # A post/stream purchase has no chat message — must never flip anything.
    other = dict(_REAL, subType="subscriber_pay_for_post")
    assert pn.parse_purchase(other) is None, "non-chat subtype must be ignored"
    # Wrong bucket entirely.
    assert pn.parse_purchase(dict(_REAL, type="favorited")) is None
    # No message link at all.
    assert pn.parse_purchase({"type": "paided_message", "text": "hi"}) is None
    for junk in (None, "", 42, [], {}):
        assert pn.parse_purchase(junk) is None, junk


_POST = {"id": 5, "type": "paided_post", "subType": "your_post_purchased",
         "replacePairs": {"{POST_URL}": "https://onlyfans.com/123456/handle",
                          "{PRICE}": "$10.00"},
         "user": {"id": 77}}

_CLASSIFY_TABLE = [
    ("real chat buy", _REAL, "chat_purchase"),
    ("chat, subType missing", {k: v for k, v in _REAL.items() if k != "subType"},
     "chat_purchase"),
    ("chat, link only in text", {k: v for k, v in _REAL.items() if k != "replacePairs"},
     "chat_purchase"),
    ("chat, foreign subType", dict(_REAL, subType="subscriber_pay_for_post"), "other"),
    ("chat, no link", {"type": "paided_message", "text": "hi"}, "other"),
    ("wall post buy", _POST, "post_purchase"),
    ("post, subType missing", {k: v for k, v in _POST.items() if k != "subType"},
     "post_purchase"),
    ("post, foreign subType", dict(_POST, subType="stream_purchased"), "other"),
    ("post, no fan", {k: v for k, v in _POST.items() if k != "user"}, "other"),
    ("post, no url", dict(_POST, replacePairs={}), "other"),
    ("favorited", dict(_REAL, type="favorited"), "other"),
    ("None", None, "other"),
    ("str", "", "other"),
    ("int", 42, "other"),
    ("list", [], "other"),
    ("empty dict", {}, "other"),
]


async def case_classify_table() -> None:
    for name, item, want in _CLASSIFY_TABLE:
        got = pn.classify(item)
        assert got == want, f"{name}: classify -> {got!r}, want {want!r}"


# ── The flip is scoped and idempotent ────────────────────────────────

async def case_flip_and_idempotent() -> None:
    await _seed()
    assert not await _is_paid(), "starts unpaid"

    client = _FakeClient([_REAL])
    r1 = await pn.poll_purchases(_ACC, client)
    assert r1 == {"seen": 1, "flipped": 1, "posts": 0, "stamped": 0}, r1
    assert await _is_paid(), "the purchased message must be marked paid"

    # The notification stays in the feed; re-polling must change nothing.
    r2 = await pn.poll_purchases(_ACC, client)
    assert r2 == {"seen": 1, "flipped": 0, "posts": 0, "stamped": 0}, r2
    assert await _is_paid()


async def case_never_flips_inbound_or_free() -> None:
    inbound_msg, free_msg = 555001, 555002
    await _seed(msg_id=inbound_msg, direction="in", price_cents=600)
    await _seed(msg_id=free_msg, direction="out", price_cents=0)

    # Unique notif ids per event (feed reality) — the done-cache keys on them,
    # so reusing _REAL's id would skip-pass without exercising the guard.
    for off, mid in enumerate((inbound_msg, free_msg)):
        n = dict(_REAL, id=117301756300 + off, replacePairs=dict(
            _REAL["replacePairs"],
            **{"{MESSAGE_LINK}": f"/chats/chat/{_FAN}?firstId={mid}"}))
        res = await pn.poll_purchases(_ACC, _FakeClient([n]))
        assert res["flipped"] == 0, (mid, res)
        assert not await _is_paid(mid), (
            "an inbound or free message must never be marked purchased")


async def case_scoped_to_the_right_fan() -> None:
    """Same message id under a DIFFERENT fan must not be touched."""
    other_fan = 999888
    await _seed(msg_id=777001, fan_id=other_fan)
    n = dict(_REAL, id=117301756400, replacePairs=dict(
        _REAL["replacePairs"],
        **{"{MESSAGE_LINK}": f"/chats/chat/{_FAN}?firstId=777001"}))
    res = await pn.poll_purchases(_ACC, _FakeClient([n]))
    assert res["flipped"] == 0, res
    assert not await _is_paid(777001, other_fan), "wrong-fan row must stay unpaid"


# ── The whole point: the existing resolver now sees it ───────────────

async def case_poll_survives_a_broken_feed() -> None:
    """A notifications hiccup must never break the ingest tick it rides on."""
    class _Boom:
        def get(self, path): raise RuntimeError("OF 500")
    _empty = {"seen": 0, "flipped": 0, "posts": 0, "stamped": 0}
    assert await pn.poll_purchases(_ACC, _Boom()) == _empty
    assert await pn.poll_purchases(_ACC, _FakeClient("not-a-list")) == _empty


def _fresh_notif(notif_id: int, *, fan_id: int, msg_id: int, age_s: int = 5) -> dict:
    """The captured payload, re-stamped relative to now. `_REAL` is frozen at
    its capture date, so it reads as ancient to the announce freshness gate."""
    when = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    link = (f"<a href='https://onlyfans.com/my/chats/chat/{fan_id}"
            f"?firstId={msg_id}'>message</a>")
    return {**_REAL, "id": notif_id, "createdAt": when.isoformat(),
            "text": f"has purchased your {link} for $6.00!",
            "replacePairs": {**_REAL["replacePairs"], "{MESSAGE_LINK}": link}}


async def _drain(q) -> list:
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except asyncio.QueueEmpty:
            break
    return out


async def case_live_poll_announces_the_buy_once() -> None:
    """The whole point: a sale reaches the browser live, carrying OF's REAL
    notification id so the rail/bell can dedupe it against the feed row."""
    fan, msg = 5551, 991001
    await _seed(msg_id=msg, fan_id=fan)
    item = _fresh_notif(900001, fan_id=fan, msg_id=msg)
    q = await events.subscribe(f"model:{_ACC}")
    try:
        await pn.poll_purchases(_ACC, _FakeClient([item]))
        first = await _drain(q)
        # The feed re-serves the same notification every 30s until it ages
        # out — that must not re-toast.
        await pn.poll_purchases(_ACC, _FakeClient([item]))
        second = await _drain(q)
    finally:
        await events.unsubscribe(f"model:{_ACC}", q)

    assert len(first) == 1, f"a fresh buy must announce once, got {len(first)}"
    p = first[0]["purchase_notified"]
    assert first[0]["__account_id"] == _ACC, first[0]
    assert p["notif_id"] == "900001", p     # OF's id verbatim — the dedupe key
    assert p["fan_id"] == fan and p["message_id"] == msg, p
    assert p["amount_cents"] == 600 and p["name"] == "Daniel", p
    assert second == [], f"a re-sighting must stay silent, got {second}"


async def case_backfill_never_announces() -> None:
    """A deep repair walks months of purchases — announcing them would fire
    hundreds of toasts for sales long past."""
    fan, msg = 5552, 991002
    await _seed(msg_id=msg, fan_id=fan)
    item = _fresh_notif(900002, fan_id=fan, msg_id=msg)
    q = await events.subscribe(f"model:{_ACC}")
    try:
        await pn.backfill_purchases(_ACC, _FakeClient([item]), page_size=50)
        evs = await _drain(q)
    finally:
        await events.unsubscribe(f"model:{_ACC}", q)

    assert evs == [], f"backfill must be silent, got {evs}"
    # Silent, but still doing its real job.
    assert await _is_paid(msg, fan), "backfill must still flip is_paid"


async def case_stale_purchase_is_not_announced() -> None:
    """Bounds the noise when the relay restarts and re-walks a feed page it
    already announced before the restart."""
    fan, msg = 5553, 991003
    await _seed(msg_id=msg, fan_id=fan)
    item = _fresh_notif(900003, fan_id=fan, msg_id=msg, age_s=6 * 60 * 60)
    q = await events.subscribe(f"model:{_ACC}")
    try:
        await pn.poll_purchases(_ACC, _FakeClient([item]))
        evs = await _drain(q)
    finally:
        await events.unsubscribe(f"model:{_ACC}", q)

    assert evs == [], f"a 6h-old purchase must not toast, got {evs}"
    assert await _is_paid(msg, fan), "stale or not, it must still flip is_paid"


async def case_announce_does_not_wait_on_the_flip() -> None:
    """A purchase whose message row hasn't been scraped yet still pings — and
    keeps pinging exactly once while it retries.

    This is the case _ANNOUNCED_NOTIFS exists for. An unresolved notification
    is deliberately NOT marked done, so it re-enters the dispatch on every
    poll; without a separate announced-memo it would re-toast every 30s until
    the message row lands. (The resolved path is covered above, where
    _DONE_NOTIFS short-circuits the re-sighting first.)
    """
    fan, msg = 5554, 991004          # deliberately NOT seeded — nothing to flip
    item = _fresh_notif(900004, fan_id=fan, msg_id=msg)
    q = await events.subscribe(f"model:{_ACC}")
    try:
        await pn.poll_purchases(_ACC, _FakeClient([item]))
        first = await _drain(q)
        await pn.poll_purchases(_ACC, _FakeClient([item]))
        second = await _drain(q)
    finally:
        await events.unsubscribe(f"model:{_ACC}", q)

    assert not await _is_paid(msg, fan), "precondition: nothing to flip"
    assert len(first) == 1, f"an unflippable buy must still announce, got {len(first)}"
    assert second == [], f"a retrying buy must not re-toast, got {second}"


async def case_name_is_coerced_at_the_wire_edge() -> None:
    """The `name` wire field is str-or-None, whatever OF puts in {NAME}. A
    non-string replacePair (OF format drift) must reach the browser as its
    str() — never a raw object the toast render would choke on — and an
    absent/empty {NAME} must go out as None, not ''."""
    fan_a, fan_b = 5555, 5556       # NOT seeded — the no-flip announce route
    weird = _fresh_notif(900005, fan_id=fan_a, msg_id=991005)
    weird["replacePairs"] = {**weird["replacePairs"], "{NAME}": 12345}
    nameless = _fresh_notif(900006, fan_id=fan_b, msg_id=991006)
    nameless["replacePairs"] = {k: v for k, v in nameless["replacePairs"].items()
                                if k != "{NAME}"}
    q = await events.subscribe(f"model:{_ACC}")
    try:
        await pn.poll_purchases(_ACC, _FakeClient([weird, nameless]))
        evs = await _drain(q)
    finally:
        await events.unsubscribe(f"model:{_ACC}", q)

    assert len(evs) == 2, f"both buys must announce, got {len(evs)}"
    by_id = {e["purchase_notified"]["notif_id"]: e["purchase_notified"] for e in evs}
    assert by_id["900005"]["name"] == "12345", by_id["900005"]
    assert by_id["900006"]["name"] is None, by_id["900006"]


async def case_a_buy_with_nobody_watching_pings_when_a_tab_arrives() -> None:
    """The sale that goes unnoticed. OF names the purchase, the relay parses
    it, and the ping fans out to ZERO SSE queues because every tab is closed.

    SSE has no mailbox: that broadcast is a loss, not a delivery. So the
    announcement must stay unclaimed and be re-offered on the next 30s poll —
    and crucially it must survive the notification being marked fully resolved
    first, which is what happens here (the silent poll flips is_paid and marks
    it done). Reading _DONE_NOTIFS before the announce lane meant the retry
    could never be reached, and the sale was never toasted at all.
    """
    fan, msg = 5557, 991007
    await _seed(msg_id=msg, fan_id=fan)
    item = _fresh_notif(900007, fan_id=fan, msg_id=msg)

    await pn.poll_purchases(_ACC, _FakeClient([item]))      # nobody home
    assert await _is_paid(msg, fan), "the unheard poll must still do its real job"

    q = await events.subscribe(f"model:{_ACC}")
    try:
        await pn.poll_purchases(_ACC, _FakeClient([item]))
        arrived = await _drain(q)
        await pn.poll_purchases(_ACC, _FakeClient([item]))
        after = await _drain(q)
    finally:
        await events.unsubscribe(f"model:{_ACC}", q)

    assert len(arrived) == 1, f"the buy must ping once a tab is open, got {len(arrived)}"
    assert arrived[0]["purchase_notified"]["notif_id"] == "900007", arrived[0]
    assert after == [], f"and exactly once — got {after}"


async def case_an_all_scope_tab_counts_as_somebody_watching() -> None:
    """Delivery is counted off `broadcast`'s own fan-out, so every scope it
    routes to counts. A tab on scope "all" receives account events, so it must
    also retire the announcement: a delivery test that only saw "model:<id>"
    would re-toast the same sale at every all-scope viewer, every 30s."""
    fan, msg = 5558, 991008
    await _seed(msg_id=msg, fan_id=fan)
    item = _fresh_notif(900008, fan_id=fan, msg_id=msg)
    q = await events.subscribe("all")
    try:
        await pn.poll_purchases(_ACC, _FakeClient([item]))
        first = await _drain(q)
        await pn.poll_purchases(_ACC, _FakeClient([item]))
        second = await _drain(q)
    finally:
        await events.unsubscribe("all", q)

    assert len(first) == 1, f"an all-scope tab must be pinged, got {len(first)}"
    assert second == [], f"and the claim must stick, got {second}"


_harness.run(
    case_parses_real_payload,
    case_ignores_non_chat_and_junk,
    case_classify_table,
    case_flip_and_idempotent,
    case_never_flips_inbound_or_free,
    case_scoped_to_the_right_fan,
    case_poll_survives_a_broken_feed,
    case_live_poll_announces_the_buy_once,
    case_backfill_never_announces,
    case_stale_purchase_is_not_announced,
    case_announce_does_not_wait_on_the_flip,
    case_name_is_coerced_at_the_wire_edge,
    case_a_buy_with_nobody_watching_pings_when_a_tab_arrives,
    case_an_all_scope_tab_counts_as_somebody_watching,
)
