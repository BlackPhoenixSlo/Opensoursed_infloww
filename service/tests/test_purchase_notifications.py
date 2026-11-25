#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import json  # noqa: E402
from urllib.parse import parse_qs, urlsplit  # noqa: E402

import events  # noqa: E402
import purchase_notifications as pn  # noqa: E402
from of_client import OFAPIError  # noqa: E402
from purchase_poll_decide import Outcome  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Message  # noqa: E402

_ACC = "acc_pn"
_FAN = 800000741
_MSG = 10491720677794
_NOW = datetime(2026, 7, 21, 15, 26, 0)
_OK = Outcome("ok")

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


class _FakeClient:
    def __init__(self, items): self.items = items; self.calls = 0
    def get_json(self, path):
        self.calls += 1
        assert "type=purchases" in path, path
        return {"list": self.items}


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



async def case_parses_real_payload() -> None:
    p = pn.parse_purchase(_REAL)
    assert p is not None, "the real captured payload must parse"
    assert p["fan_id"] == _FAN, p
    assert p["message_id"] == _MSG, p
    assert p["amount_cents"] == 600, p
    assert p["notif_id"] == 117301756206, p


async def case_ignores_non_chat_and_junk() -> None:
    other = dict(_REAL, subType="subscriber_pay_for_post")
    assert pn.parse_purchase(other) is None, "non-chat subtype must be ignored"
    assert pn.parse_purchase(dict(_REAL, type="favorited")) is None
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



async def case_flip_and_idempotent() -> None:
    await _seed()
    assert not await _is_paid(), "starts unpaid"

    client = _FakeClient([_REAL])
    r1 = await pn.poll_purchases(_ACC, client)
    assert r1 == {"seen": 1, "flipped": 1, "posts": 0, "stamped": 0, "outcome": _OK}, r1
    assert await _is_paid(), "the purchased message must be marked paid"

    r2 = await pn.poll_purchases(_ACC, client)
    assert r2 == {"seen": 1, "flipped": 0, "posts": 0, "stamped": 0, "outcome": _OK}, r2
    assert await _is_paid()


async def case_never_flips_inbound_or_free() -> None:
    inbound_msg, free_msg = 555001, 555002
    await _seed(msg_id=inbound_msg, direction="in", price_cents=600)
    await _seed(msg_id=free_msg, direction="out", price_cents=0)

    for off, mid in enumerate((inbound_msg, free_msg)):
        n = dict(_REAL, id=117301756300 + off, replacePairs=dict(
            _REAL["replacePairs"],
            **{"{MESSAGE_LINK}": f"/chats/chat/{_FAN}?firstId={mid}"}))
        res = await pn.poll_purchases(_ACC, _FakeClient([n]))
        assert res["flipped"] == 0, (mid, res)
        assert not await _is_paid(mid), (
            "an inbound or free message must never be marked purchased")


async def case_scoped_to_the_right_fan() -> None:
    other_fan = 999888
    await _seed(msg_id=777001, fan_id=other_fan)
    n = dict(_REAL, id=117301756400, replacePairs=dict(
        _REAL["replacePairs"],
        **{"{MESSAGE_LINK}": f"/chats/chat/{_FAN}?firstId=777001"}))
    res = await pn.poll_purchases(_ACC, _FakeClient([n]))
    assert res["flipped"] == 0, res
    assert not await _is_paid(777001, other_fan), "wrong-fan row must stay unpaid"



async def case_poll_survives_a_broken_feed() -> None:
    class _Boom:
        def get_json(self, path): raise RuntimeError("OF 500")
    _empty = {"seen": 0, "flipped": 0, "posts": 0, "stamped": 0}
    assert await pn.poll_purchases(_ACC, _Boom()) == {**_empty, "outcome": Outcome("error")}
    assert await pn.poll_purchases(_ACC, _FakeClient("not-a-list")) == {**_empty, "outcome": _OK}


class _Resp:
    def __init__(self, status: int, body, headers=None):
        self.status_code, self._body = status, body
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.headers = headers or {}
        self.url = "https://onlyfans.com/api2/v2/users/notifications"

    def json(self):
        return json.loads(self.text)


class _Answers:
    def __init__(self, status: int, body, headers=None): self.r = _Resp(status, body, headers); self.calls = 0
    def get_json(self, path):
        self.calls += 1
        raise OFAPIError(f"{self.r.status_code} for {self.r.url}\n{self.r.text[:500]}", response=self.r)


async def case_poll_outcome_per_answer() -> None:
    too_many = {"error": {"code": 0, "message": "Too many requests. Please allow 7 seconds"}}
    rows = [
        (_FakeClient([]), _OK),
        (_Answers(429, {"error": {"code": 0, "message": "Too many requests."}}, {"Retry-After": "45"}),
         Outcome("rate_limited", retry_after_s=45.0)),
        (_Answers(429, too_many, {"Retry-After": "12"}), Outcome("rate_limited", retry_after_s=12.0)),
        (_Answers(429, too_many), Outcome("rate_limited", retry_after_s=7.0)),
        (_Answers(429, too_many, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
         Outcome("rate_limited", retry_after_s=7.0)),
        (_Answers(429, {"error": {"code": 0, "message": "Too many requests."}}), Outcome("rate_limited")),
        (_Answers(400, {"error": {"code": 301, "message": "Wrong user."}}), Outcome("dead", reason="wrong_user")),
        (_Answers(400, {"error": {"code": 101, "message": "Confirm", "payload": {"otpState": {}, "strong": False}}}),
         Outcome("dead", reason="otp_required")),
        (_Answers(401, {"error": {"code": 401, "message": "Unauthorized"}}), Outcome("unauthorized")),
        (_Answers(500, {"error": {"code": 0, "message": "internal"}}), Outcome("error")),
        (_Answers(403, "<html>cf</html>"), Outcome("error")),
    ]
    for client, want in rows:
        got = await pn.poll_purchases(_ACC, client)
        assert got["outcome"] == want, (client, got, want)
        assert got["seen"] == 0 or want == _OK


class _Paged:
    def __init__(self, items): self.items = items; self.offsets = []
    def get_json(self, path):
        q = parse_qs(urlsplit(path).query)
        off, lim = int(q["offset"][0]), int(q["limit"][0])
        self.offsets.append(off)
        return {"list": self.items[off:off + lim]}


async def case_catch_up_pages_back_to_a_seen_notification() -> None:
    base_msg, base_id = 991_000, 117_400_000
    await _seed(msg_id=base_msg)
    old = _fresh_notif(base_id, fan_id=_FAN, msg_id=base_msg, age_s=600)
    assert (await pn.poll_purchases(_ACC, _Paged([old])))["flipped"] == 1
    new = []
    for i in range(1, 13):
        await _seed(msg_id=base_msg + i)
        new.append(_fresh_notif(base_id + i, fan_id=_FAN, msg_id=base_msg + i, age_s=60 - i))
    new.reverse()
    tail = [_fresh_notif(base_id - j, fan_id=_FAN, msg_id=1 + j, age_s=900) for j in range(1, 20)]
    feed = _Paged(new + [old] + tail)
    got = await pn.poll_purchases(_ACC, feed, limit=10, pages=3)
    assert feed.offsets == [0, 10], f"stops at the page holding the seen one, read {feed.offsets}"
    assert got["flipped"] == 12 and got["outcome"] == _OK, got
    for i in range(1, 13):
        assert await _is_paid(base_msg + i), i
    many = [_fresh_notif(117_500_000 + i, fan_id=_FAN, msg_id=992_000 + i) for i in range(40)]
    feed = _Paged(many)
    got = await pn.poll_purchases(_ACC, feed, limit=10, pages=3)
    assert feed.offsets == [0, 10, 20] and got["seen"] == 30, (feed.offsets, got)
    feed = _Paged(many)
    await pn.poll_purchases(_ACC, feed, limit=10)
    assert feed.offsets == [0], feed.offsets
    feed = _Paged(many[:4])
    await pn.poll_purchases(_ACC, feed, limit=10, pages=3)
    assert feed.offsets == [0], feed.offsets
    class _Second(_Paged):
        def get_json(self, path):
            if self.offsets:
                self.offsets.append(-1)
                raise OFAPIError("429 for x\n{}", response=_Resp(429, {"error": {"message": "Too many"}}))
            return super().get_json(path)
    feed = _Second([_fresh_notif(117_600_000 + i, fan_id=_FAN, msg_id=993_000 + i) for i in range(15)])
    got = await pn.poll_purchases(_ACC, feed, limit=10, pages=3)
    assert got["seen"] == 10 and got["outcome"] == Outcome("rate_limited"), got


async def case_failed_catch_up_resumes_past_its_own_pages() -> None:
    base_msg, base_id = 994_000, 117_700_000
    items = []
    for i in range(15):
        await _seed(msg_id=base_msg + i)
        items.append(_fresh_notif(base_id - i, fan_id=_FAN, msg_id=base_msg + i, age_s=60 + i))

    class _FailOnce(_Paged):
        failed = False
        def get_json(self, path):
            if self.offsets and not _FailOnce.failed:
                _FailOnce.failed = True
                self.offsets.append(-1)
                raise OFAPIError("500 for x\n{}", response=_Resp(500, {"error": {"message": "x"}}))
            return super().get_json(path)

    got = await pn.poll_purchases(_ACC, _FailOnce(items), limit=10, pages=3)
    assert got["flipped"] == 10 and got["outcome"] == Outcome("error"), got
    feed = _FailOnce(items)
    got = await pn.poll_purchases(_ACC, feed, limit=10, pages=3)
    assert feed.offsets == [0, 10], f"the retry must read page 1, read {feed.offsets}"
    assert got["flipped"] == 5 and got["outcome"] == _OK, got
    for i in range(15):
        assert await _is_paid(base_msg + i), i
    feed = _Paged(items)
    await pn.poll_purchases(_ACC, feed, limit=10, pages=3)
    assert feed.offsets == [0], f"a finished catch-up stops at the memo again, read {feed.offsets}"


def _fresh_notif(notif_id: int, *, fan_id: int, msg_id: int, age_s: int = 5) -> dict:
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
    fan, msg = 5551, 991001
    await _seed(msg_id=msg, fan_id=fan)
    item = _fresh_notif(900001, fan_id=fan, msg_id=msg)
    q = await events.subscribe(f"model:{_ACC}")
    try:
        await pn.poll_purchases(_ACC, _FakeClient([item]))
        first = await _drain(q)
        await pn.poll_purchases(_ACC, _FakeClient([item]))
        second = await _drain(q)
    finally:
        await events.unsubscribe(f"model:{_ACC}", q)

    assert len(first) == 1, f"a fresh buy must announce once, got {len(first)}"
    p = first[0]["purchase_notified"]
    assert first[0]["__account_id"] == _ACC, first[0]
    assert p["notif_id"] == "900001", p
    assert p["fan_id"] == fan and p["message_id"] == msg, p
    assert p["amount_cents"] == 600 and p["name"] == "Daniel", p
    assert second == [], f"a re-sighting must stay silent, got {second}"


async def case_backfill_never_announces() -> None:
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
    assert await _is_paid(msg, fan), "backfill must still flip is_paid"


async def case_stale_purchase_is_not_announced() -> None:
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
    fan, msg = 5554, 991004
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
    fan_a, fan_b = 5555, 5556
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
    fan, msg = 5557, 991007
    await _seed(msg_id=msg, fan_id=fan)
    item = _fresh_notif(900007, fan_id=fan, msg_id=msg)

    # SSE has no mailbox: with no tab the ping stays unclaimed and is re-offered on the next poll
    await pn.poll_purchases(_ACC, _FakeClient([item]))
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
    case_poll_outcome_per_answer,
    case_catch_up_pages_back_to_a_seen_notification,
    case_failed_catch_up_resumes_past_its_own_pages,
    case_live_poll_announces_the_buy_once,
    case_backfill_never_announces,
    case_stale_purchase_is_not_announced,
    case_announce_does_not_wait_on_the_flip,
    case_name_is_coerced_at_the_wire_edge,
    case_a_buy_with_nobody_watching_pings_when_a_tab_arrives,
    case_an_all_scope_tab_counts_as_somebody_watching,
)
