from __future__ import annotations

import json
import logging
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import fansly_shim as shim

HERE = Path(__file__).resolve().parent
READS = HERE / "fixtures" / "reads.json"
ACCOUNT_ID = "900000000000000001"


def check(cond: bool, label: str, fails: list[str]) -> None:
    if not cond:
        fails.append(label)


@contextmanager
def shim_clock(now_ms: int):
    real = shim.time
    shim.time = types.SimpleNamespace(time=lambda: now_ms / 1000)
    try:
        yield
    finally:
        shim.time = real


def main() -> int:
    class _PurchaseFeed(shim.FanslyShimClient):
        def __init__(self, rows):
            self._rows = rows

        def _notification_rows(self):
            return self._rows

    fixture = json.loads(READS.read_text())
    reads = {**fixture["responses"], "unread_thread": fixture["unread_thread"]}
    used: set[str] = set()

    def fixture_read(key: str):
        used.add(key)
        return reads[key]

    fails: list[str] = []

    page = shim.of_chats_page(fixture_read("/api/v1/messaging/groups"), account_id=ACCOUNT_ID, limit=20)
    check("list" in page and "hasMore" in page, "chats page: {list, hasMore}", fails)
    check(isinstance(page["list"], list) and bool(page["list"]),
          "chats page: non-empty list", fails)
    for row in page["list"]:
        for key in ("id", "withUser", "lastMessage", "unreadMessagesCount",
                    "hasUnreadMessages", "canSendMessage"):
            check(key in row, f"chat row missing {key}", fails)
        wu = row["withUser"]
        for key in ("id", "name", "username"):
            check(key in wu, f"withUser missing {key}", fails)
        check(isinstance(row["id"], str) and row["id"].isdigit(),
              f"chat id not a snowflake string: {row['id']!r}", fails)
        check(isinstance(row["unreadMessagesCount"], int),
              "unreadMessagesCount not int", fails)
    sample = page["list"][0]
    print(f"chats: {len(page['list'])} row(s); sample "
          f"id={sample['id']} fan={sample['withUser']['name']!r} "
          f"unread={sample['unreadMessagesCount']}")

    page = shim.of_messages_page(fixture_read("/api/v1/message"), account_id=ACCOUNT_ID, limit=25)
    check("list" in page and "hasMore" in page, "messages page: {list, hasMore}", fails)
    check(bool(page["list"]), "messages page: non-empty list", fails)
    for msg in page["list"]:
        for key in ("id", "text", "fromUser", "createdAt", "isTip",
                    "price", "mediaCount"):
            check(key in msg, f"message missing {key}", fails)
        check("id" in msg["fromUser"], "fromUser missing id", fails)
        check(msg["createdAt"] is None or "T" in msg["createdAt"],
              f"createdAt not ISO-8601: {msg['createdAt']!r}", fails)
    m = page["list"][0]
    by_us = [x for x in page["list"] if x["fromUser"]["id"] == ACCOUNT_ID]
    by_fan = [x for x in page["list"] if x["fromUser"]["id"] != ACCOUNT_ID]
    print(f"messages: {len(page['list'])} msg(s); {len(by_us)} ours / "
          f"{len(by_fan)} theirs; sample text={m['text']!r} at {m['createdAt']}")

    thread = fixture_read("/api/v1/message")
    rows = fixture_read("/api/v1/notifications")["notifications"]
    feed = _PurchaseFeed(rows)
    unlocks = [r for r in rows if r.get("type") == 2008]
    check(bool(unlocks), "fixture: no 2008 row", fails)
    for row in unlocks:
        fan, grant = str(row["correlationGroupId"]), str(row["correlationId"])
        page = shim.of_messages_page(thread, account_id=ACCOUNT_ID, limit=25,
                                     purchased_ids=feed._purchases_by_fan().get(fan))
        bought = [x for x in page["list"] if grant in {md["id"] for md in x["media"]}]
        check(bool(bought) and all(x["price"] and x["isOpened"] for x in bought),
              f"2008: grant {grant} bought by {fan} opens its priced message", fails)
    paid = feed.purchases()
    check(paid == {"sales": [], "unbanked_seen": {"2008": len(unlocks)}},
          f"2008: unlocks but banks nothing, got {paid}", fails)
    tips = [x for x in shim.of_messages_page(thread, account_id=ACCOUNT_ID, limit=25)["list"]
            if x["isTip"]]
    check(bool(tips) and all("tipAmount" not in x for x in tips),
          f"fixture tip: isTip with no tipAmount, got {tips}", fails)
    print("2008 unlocks the fan's priced message and banks nothing; tips carry no amount")

    class _PageProbe(shim.FanslyShimClient):
        def __init__(self, pages):
            self.pages = list(pages)
            self.calls = []
            class _S:
                account_id = ACCOUNT_ID
            self.session = _S()

        def _as_group_id(self, chat_id):
            return str(chat_id)

        def _fan_id_for_group(self, group_id):
            return None

        def _purchases_by_fan(self):
            return {}

        def _request(self, method, path, *, params=None, json_body=None, **kw):
            self.calls.append((method, path, dict(params or {})))
            return {"messages": self.pages.pop(0)}

    def _msg(i, deleted=None):
        return {"id": str(i), "senderId": "777", "content": f"m{i}",
                "createdAt": 1764000000000 + i, "deletedAt": deleted}

    def _ids(page):
        return [x["id"] for x in page["list"]]

    def _befores(probe):
        return [c[2].get("before") for c in probe.calls]

    pp = _PageProbe([[_msg(5), _msg(4, 1764000009000), _msg(3)]])
    got = pp.get_messages("g1", limit=3)
    check(_ids(got) == ["5", "3"] and got["hasMore"] is True and len(pp.calls) == 1,
          f"messages: one deleted row drops, others in order, raw hasMore kept, got {got} {pp.calls}", fails)
    pp = _PageProbe([[_msg(5), _msg(4, 1764000009000), _msg(3)]])
    got = pp.get_messages("g1", limit=4)
    check(_ids(got) == ["5", "3"] and got["hasMore"] is False,
          f"messages: short raw page with a deleted row keeps hasMore false, got {got}", fails)

    pp = _PageProbe([[_msg(9, 1), _msg(8, 1)], [_msg(7), _msg(6)]])
    got = pp.get_messages("g1", limit=2)
    check(_ids(got) == ["7", "6"] and got["hasMore"] is True
          and _befores(pp) == [None, "8"] and all(c[2]["limit"] == "2" for c in pp.calls),
          f"messages: all-deleted page walks before its lowest raw id, got {got} {pp.calls}", fails)

    pp = _PageProbe([[_msg(9, 1), _msg(8, 1)], [_msg(7, 1), _msg(6, 1)],
                     [_msg(5, 1), _msg(4, 1)], [_msg(3, 1), _msg(2, 1)], [_msg(1)]])
    got = pp.get_messages("g1", limit=2, before_id=10)
    check(_befores(pp) == ["10", "8", "6", "4"] and _ids(got) == [] and got["hasMore"] is True,
          f"messages: walk stops after 3 extra pages, got {got} {pp.calls}", fails)

    pp = _PageProbe([[_msg(2, 1), _msg(1, 1)]])
    got = pp.get_messages("g1", limit=3)
    check(_ids(got) == [] and got["hasMore"] is False and len(pp.calls) == 1,
          f"messages: all-deleted last page gives no rows and hasMore false, got {got} {pp.calls}", fails)
    print("messages: deleted rows drop, raw hasMore kept, an all-deleted page walks at most 3 more")

    replied = shim.of_chat_row(
        {"groupId": "g1", "unreadCount": 3,
         "lastMessageId": "200", "lastUnreadMessageId": "100"},
        None, None, account_id=ACCOUNT_ID)
    check(replied["unreadMessagesCount"] == 0 and replied["hasUnreadMessages"] is False,
          "newest msg is newer than newest unread (we replied) -> unread cleared", fails)

    fan_last = shim.of_chat_row(
        {"groupId": "g2", "unreadCount": 3,
         "lastMessageId": "100", "lastUnreadMessageId": "100"},
        None, None, account_id=ACCOUNT_ID)
    check(fan_last["unreadMessagesCount"] == 3 and fan_last["hasUnreadMessages"] is True,
          "newest msg IS the newest unread (fan spoke last) -> still blue", fails)

    unknown = shim.of_chat_row(
        {"groupId": "g3", "unreadCount": 2}, None, None, account_id=ACCOUNT_ID)
    check(unknown["unreadMessagesCount"] == 2,
          "no read-state pointers -> unread preserved (fail safe)", fails)
    print("badge rule: a reply clears unread; fan-last and unknown stay blue")

    class _AckProbe(shim.FanslyShimClient):
        def __init__(self, *, unread=(), fail=False):  # noqa: D107
            self.calls = []
            self._unread = list(unread)
            self._fail = fail
            class _S:
                account_id = ACCOUNT_ID
            self.session = _S()

        def _as_group_id(self, chat_id):
            return str(chat_id)

        def _request(self, method, path, *, params=None, json_body=None, **kw):
            self.calls.append((method, path, json_body))
            if path == "/message":
                msgs = [{"id": mid, "senderId": "fan1",
                         "interactions": [{"userId": ACCOUNT_ID, "readAt": 0}]}
                        for mid in self._unread]
                msgs.append({"id": "ours", "senderId": ACCOUNT_ID,
                             "interactions": [{"userId": "fan1", "readAt": 0}]})
                msgs.append({"id": "already-read", "senderId": "fan1",
                             "interactions": [{"userId": ACCOUNT_ID,
                                               "readAt": 1788284544}]})
                return {"messages": msgs}
            if path == "/message/ack":
                if self._fail:
                    raise shim.FanslyAPIError(
                        "POST /message/ack -> 400 code=99 'error ack messages'")
                return {"success": True}
            return {}

    probe = _AckProbe(unread=["900505751051792384", "900505751051792383"])
    res = probe.mark_chat_read("g1")
    acks = [c for c in probe.calls if c[1] == "/message/ack"]
    check(res.get("success") is True, "ack: success on a normal read", fails)
    # Unread is per message: acking only the newest id left the count at 2 (measured live); every unread id must be sent.
    check(len(acks) == 1, "ack: ONE batched /message/ack call", fails)
    check(acks and acks[0][2] == {
              "messageIds": ["900505751051792384", "900505751051792383"],
              "type": 2},
          f"ack: acks EVERY unread id, got {acks[0][2] if acks else None}", fails)

    nothing = _AckProbe(unread=[])
    check(nothing.mark_chat_read("g1").get("success") is True,
          "ack: nothing unread still succeeds", fails)
    check(not [c for c in nothing.calls if c[1] == "/message/ack"],
          "ack: nothing unread makes NO ack call", fails)

    stale = _AckProbe(unread=["900307747011272705"], fail=True)
    check(stale.mark_chat_read("g1") == {"success": False, "reason": "ack_rejected"},
          "ack: a rejected ack degrades instead of raising", fails)
    print("read receipt: acks EVERY unread id; no-ops when clean; survives a reject")

    fx = fixture_read("unread_thread")
    real_msgs = fx["messages"]
    real_ids = [m["id"] for m in real_msgs]
    grp = fx["groups_before"][0]

    class _RealProbe(_AckProbe):
        def _request(self, method, path, *, params=None, json_body=None, **kw):
            self.calls.append((method, path, json_body))
            if path == "/message":
                return {"messages": real_msgs}
            if path == "/message/ack":
                return {"success": True}
            return {}

    rp = _RealProbe()
    check(grp["unreadCount"] == len(real_ids) == 3,
          "ack/fixture: fixture is a 3-unread thread", fails)
    check(len(real_ids) > 1 and grp["lastUnreadMessageId"] in real_ids,
          "ack/fixture: pointer names only ONE of the unread ids", fails)
    check(rp._unread_message_ids(grp["groupId"]) == (real_ids, True),
          f"ack/fixture: scan returns all three ids, got "
          f"{rp._unread_message_ids(grp['groupId'])}", fails)
    rp.mark_chat_read(grp["groupId"])
    acks = [c for c in rp.calls if c[1] == "/message/ack"]
    check(acks and acks[0][2] == {"messageIds": real_ids, "type": 2},
          "ack/fixture: acks all three ids in one call", fails)
    print("read receipt (fixture bodies): 3 unread ids scanned and acked together")

    class _MarkAllProbe(_AckProbe):
        def __init__(self, groups):  # noqa: D107
            super().__init__(unread=["m1"])
            self.groups = groups
            self.scanned = []

        def _request(self, method, path, *, params=None, json_body=None, **kw):
            if path == "/messaging/groups":
                self.calls.append((method, path, json_body))
                return {"data": [{"groupId": g, "unreadCount": u}
                                 for g, u in self.groups]}
            if path == "/message":
                self.scanned.append(params.get("groupId"))
                return {"messages": [
                    {"id": f"unread-{params['groupId']}", "senderId": "fan1",
                     "interactions": [{"userId": ACCOUNT_ID, "readAt": 0}]}]}
            return super()._request(method, path, params=params,
                                    json_body=json_body, **kw)

    ma = _MarkAllProbe([("g1", 2), ("g2", 0), ("g3", 1)])
    check(ma.mark_all_chats_read().get("success") is True,
          "mark-all: success", fails)
    ma_acks = [c for c in ma.calls if c[1] == "/message/ack"]
    check(len(ma_acks) == 1, "mark-all: ONE batched /message/ack", fails)
    check(ma.scanned == ["g1", "g3"],
          f"mark-all: scans only groups with unreadCount>0, got {ma.scanned}", fails)
    check(ma_acks and ma_acks[0][2] == {
              "messageIds": ["unread-g1", "unread-g3"], "type": 2},
          f"mark-all: acks every unread id, got {ma_acks[0][2] if ma_acks else None}",
          fails)

    clean = _MarkAllProbe([("g1", 0), ("g2", 0)])
    check(clean.mark_all_chats_read().get("success") is True
          and not [c for c in clean.calls if c[1] == "/message/ack"],
          "mark-all: a clean inbox makes NO ack call", fails)

    huge = _MarkAllProbe([(f"g{i}", 1) for i in range(120)])
    huge.mark_all_chats_read()
    check(len(huge.scanned) == shim.FanslyShimClient._MARK_ALL_CAP,
          f"mark-all: fan-out capped at {shim.FanslyShimClient._MARK_ALL_CAP}, "
          f"scanned {len(huge.scanned)}", fails)
    print("mark-all: batched ack of every unread id; capped; clean inbox no-ops")

    class _NotifProbe(shim.FanslyShimClient):
        def __init__(self, rows, *, accounts=True, unack=None):  # noqa: D107
            self.rows = rows
            self._accounts = accounts
            self._unack = unack
            self.calls = []

        def _request(self, method, path, *, params=None, json_body=None, **kw):
            self.calls.append((method, path))
            if path == "/notifications":
                return {"notifications": self.rows}
            if path == "/notifications/unack":
                if isinstance(self._unack, Exception):
                    raise self._unack
                return self._unack
            if path == "/account":
                if not self._accounts:
                    raise shim.FanslyAPIError("GET /account -> 500")
                return [{"id": "99", "username": "fan99", "displayName": "Fan Ninety"}]
            return {}

    def _row(nid, code, *, acked=0):
        return {"id": nid, "type": code, "correlationGroupId": "99",
                "correlationId": "1", "acknowledgedAt": acked,
                "createdAt": 1788284544, "metadata": None}

    notif = _NotifProbe([_row("1", 15006), _row("2", 3002), _row("3", 7001),
                         _row("4", 2007, acked=1788), _row("5", 15011)])
    feed = notif.notifications(limit=20)
    got = {i["fanslyType"]: i["type"] for i in feed["list"]}
    check(got.get(15006) == "subscribed" and got.get(3002) == "subscribed",
          f"notif: subscribe codes -> 'subscribed', got {got}", fails)
    follow = _NotifProbe([_row("6", 3003), _row("7", 15016)]).notifications(limit=20)["list"]
    check({i["fanslyType"]: i["type"] for i in follow} == {3003: "followed", 15016: "subscribed"},
          f"notif: a 3003 follow is 'followed', never 'subscribed', got {follow}", fails)
    check(got.get(7001) == "tip", f"notif: 7001 -> 'tip', got {got.get(7001)}", fails)
    check(got.get(2007) == "purchases",
          f"notif: 2007 -> 'purchases', got {got.get(2007)}", fails)
    check(got.get(15011) == "fansly:15011",
          f"notif: unmapped code stays namespaced, got {got.get(15011)}", fails)
    check(len([c for c in notif.calls if c[1] == "/account"]) == 1,
          "notif: ONE batch profile fetch for the whole page", fails)
    first = feed["list"][0]
    check(first["user"] and first["user"]["name"] == "Fan Ninety",
          "notif: correlationGroupId hydrates the user object", fails)
    check(first["createdAt"] == "2026-09-01T17:42:24+00:00",
          f"notif: createdAt is ISO from epoch seconds, got {first['createdAt']}", fails)
    check(all(i["metadata"] is None for i in feed["list"]),
          "notif: metadata passes through, never invented", fails)

    subs = notif.notifications(type="subscribed", limit=20)["list"]
    check([i["fanslyType"] for i in subs] == [15006, 3002],
          f"notif: type filter selects the subscribe bucket, got {subs}", fails)

    mixed = _NotifProbe([_row("1", 15016), _row("2", 1002), _row("3", 15006), _row("4", 7001)])
    pages = [mixed.notifications(type="subscribed", limit=1, offset=n) for n in range(3)]
    check([([i["fanslyType"] for i in p["list"]], p["hasMore"]) for p in pages]
          == [([15016], True), ([15006], False), ([], False)],
          f"notif: a filtered page ends paging at the last filtered row, got {pages}", fails)

    unack = fixture_read("/api/v1/notifications/unack")
    counted = _NotifProbe([_row("1", 7001)], unack=unack)
    counts = counted.notifications_count()
    check(counts == {"subscribes": 1, "tips": 0, "comments": 1, "mentions": 0,
                     "hearts": 2, "gifts": 0, "all": 6},
          f"notif: badge is the /unack per-code totals (bell 6 = their sum), got {counts}", fails)
    check([c[1] for c in counted.calls] == ["/notifications/unack"],
          f"notif: the badge reads /unack only, got {counted.calls}", fails)
    for label, answer in (("a fetch error", shim.FanslyAPIError("GET /notifications/unack -> 500")),
                          ("a non-list answer", {"total": 6}),
                          ("a row without a total", [{"type": 3003}])):
        try:
            got_counts = _NotifProbe([], unack=answer).notifications_count()
            fails.append(f"notif: {label} must raise, never read as zero, got {got_counts}")
        except shim.FanslyAPIError:
            pass

    # Profile hydration is decoration: losing it must not empty the feed.
    blind = _NotifProbe([_row("1", 7001)], accounts=False)
    logging.getLogger("of-relay.fansly.shim").setLevel(logging.CRITICAL)
    try:
        degraded = blind.notifications(limit=20)["list"]
    finally:
        logging.getLogger("of-relay.fansly.shim").setLevel(logging.NOTSET)
    check(len(degraded) == 1 and degraded[0]["user"] is None,
          "notif: a failed profile lookup degrades, it does not empty the feed", fails)
    print("notifications: type codes map to OF buckets; unmapped stay namespaced")

    real = [
        {"id": "a", "type": 3003, "correlationId": "follow-row",
         "correlationGroupId": "99", "acknowledgedAt": None,
         "createdAt": 1788331251, "metadata": None},
        {"id": "b", "type": 1002, "correlationId": "99",
         "correlationGroupId": "post-1", "acknowledgedAt": None,
         "createdAt": 1788331848, "metadata": None},
        {"id": "c", "type": 5003, "correlationId": "like-row",
         "correlationGroupId": "message-1", "acknowledgedAt": None,
         "createdAt": 1788331763, "metadata": None},
        {"id": "d", "type": 1004, "correlationId": "reply-post",
         "correlationGroupId": "post-1", "acknowledgedAt": None,
         "createdAt": 1788331893, "metadata": None},
    ]
    actor = _NotifProbe(real)
    by = {i["fanslyType"]: i for i in actor.notifications(limit=20)["list"]}
    check(by[3003]["user"] and by[3003]["user"]["username"] == "fan99",
          "notif/actor: 3003 hydrates the follower from correlationGroupId", fails)
    check(by[1002]["user"] and by[1002]["user"]["username"] == "fan99",
          "notif/actor: 1002 hydrates the liker from correlationId", fails)
    check(by[5003]["user"] is None and by[1004]["user"] is None,
          "notif/actor: message-like and post-reply rows carry no actor", fails)
    check(by[1002]["text"] == "Fan Ninety liked your post"
          and by[5003]["text"] == "liked your message",
          f"notif/actor: text uses the actor only when there is one, got "
          f"{by[1002]['text']!r} / {by[5003]['text']!r}", fails)
    print("notifications: actor field resolved per code (follow/post-like/none)")

    presence = json.loads((HERE / "fixtures" / "presence.json").read_text())
    with shim_clock(presence["now"]):
        seen = {k: shim.of_user(a).get("isOnline") for k, a in presence["accounts"].items()}
    check(seen == {"dormant": None, "recent": True, "stale": None},
          f"presence: lastSeenAt decides, statusId 1 on all three does not, got {seen}", fails)
    print("presence: dormant/recent/stale -> offline/online/offline")

    payload = fixture_read("/api/v1/subscribers")
    accounts = fixture_read("/api/v1/account")
    sub_fan = str(payload["subscriptions"][0]["subscriberId"])

    class _SubProbe(shim.FanslyShimClient):
        def __init__(self):  # noqa: D107
            class _S:
                account_id = ACCOUNT_ID
            self.session = _S()

        def _subscribers_payload(self):
            return payload

        def _request(self, method, path, *, params=None, json_body=None, **kw):
            return accounts if path == "/account" else {}

    sp = _SubProbe()
    fans = sp.subscribers(type="active", limit=10)["list"]
    check(len(fans) == 1 and fans[0]["id"] == sub_fan
          and fans[0]["username"] == accounts[0]["username"],
          "subs: row hydrates to the fan object keyed by subscriberId", fails)
    check(fans[0]["subscribedBy"] is True and fans[0]["subscribePrice"] == 5.0
          and fans[0]["currentSubscribePrice"] == 0.0,
          f"subs: status 3 is active, 5000 units == $5.00, trial == $0, got "
          f"{fans[0]['subscribePrice']}/{fans[0]['currentSubscribePrice']}", fails)
    check(fans[0]["subscribedByExpireDate"] == "2026-01-08T00:00:00+00:00",
          f"subs: endsAt is ms -> ISO, got {fans[0]['subscribedByExpireDate']}", fails)
    check(sp.subscribers(type="expired")["list"] == [],
          "subs: an active row is not in the expired filter", fails)
    with shim_clock(presence["now"]):
        accounts[0]["lastSeenAt"] = presence["accounts"]["recent"]["lastSeenAt"]
        check([f["id"] for f in sp.iter_online_subscribers(max_fans=5)] == [sub_fan],
              "subs: iter_online_subscribers yields the fan seen inside the window", fails)
        accounts[0]["lastSeenAt"] = presence["accounts"]["stale"]["lastSeenAt"]
        check(sp.iter_online_subscribers(max_fans=5) == [],
              "subs: iter_online_subscribers drops a fan last seen days ago", fails)
        del accounts[0]["lastSeenAt"]
    check(sp.subscription_counts() == {"active": 1, "expired": 0, "all": 1},
          "subs: counts come off stats", fails)
    check("renew" not in fans[0]["subscribedOnData"] and fans[0]["fanslySubscription"]["autoRenew"] == 1,
          f"subs: no renew key, raw autoRenew passes through, got {fans[0]['subscribedOnData']}", fails)
    check(sp.subscribers(type="active", limit=10)["hasMore"] is False,
          "subs: a roster whose ids match totalActive is complete", fails)
    print("subscribers: fixture row reshaped to OF's fan object; online walk works")

    expired = json.loads((HERE / "fixtures" / "subscribers_expired.json").read_text())
    gone_fan = expired["subscriptions"][0]["subscriberId"]

    def roster(stats, *rows):
        probe = _SubProbe()
        probe._subscribers_payload = lambda: {"stats": stats, "subscriptions": list(rows)}
        return probe

    def sub(sid, status):
        return {**payload["subscriptions"][0], "subscriberId": sid, "status": status}

    ep = roster(expired["stats"], *expired["subscriptions"])
    got = ep.subscribers(type="expired", limit=10)
    check([f["id"] for f in got["list"]] == [gone_fan] and got["hasMore"] is True,
          f"subs: status 5 is expired and the expired roster is never complete, got {got}", fails)
    check(ep.subscribers(type="active", limit=10) == {"list": [], "hasMore": False},
          "subs: an expired row is not active", fails)
    odd = roster({"totalActive": 1}, sub("900000000000000002", 3), sub("900000000000000003", 2))
    for want in ("active", "expired", "all"):
        got = odd.subscribers(type=want, limit=10)
        check("900000000000000003" not in [f["id"] for f in got["list"]] and got["hasMore"] is True,
              f"subs: an unknown status is in no roster and flags {want} incomplete, got {got}", fails)
    for label, probe in (("short", roster({"totalActive": 2}, sub("900000000000000002", 3))),
                         ("duplicate", roster({"totalActive": 2}, sub("900000000000000002", 3),
                                              sub("900000000000000002", 3))),
                         ("bad id", roster({"totalActive": 2}, sub("900000000000000002", 3), sub("", 3))),
                         ("no total", roster({}, sub("900000000000000002", 3)))):
        got = probe.subscribers(type="active", limit=10)
        check(got["hasMore"] is True, f"subs: {label} active roster is incomplete, got {got}", fails)
        try:
            probe.iter_online_subscribers(max_fans=5)
            fails.append(f"subs: iter_online_subscribers must refuse a {label} roster")
        except shim.FanslyUnsupported as e:
            check(e.reason == "platform_lacks:subscribers:incomplete", f"subs: refusal reason {e!r}", fails)
    class MissingProfiles(_SubProbe):
        def _request(self, method, path, **kwargs):
            if path == "/account":
                if self.failed:
                    raise shim.FanslyAPIError("profile read failed")
                return []
            return super()._request(method, path, **kwargs)

    for failed in (False, True):
        probe = MissingProfiles()
        probe.failed = failed
        try:
            probe.iter_online_subscribers()
            fails.append(f"subs: missing profile coverage must refuse, request failed={failed}")
        except shim.FanslyUnsupported as e:
            check(e.reason == probe.ROSTER_INCOMPLETE, f"subs: refusal reason {e!r}", fails)
    many = [sub(str(900000000000000100 + i), 3) for i in range(5)]
    full = roster({"totalActive": 5}, *many)
    pages = [full.subscribers(type="active", limit=2, offset=off) for off in (0, 2, 4)]
    check([[f["id"] for f in p["list"]] for p in pages] == [[r["subscriberId"] for r in many[i:i + 2]]
                                                            for i in (0, 2, 4)]
          and [p["hasMore"] for p in pages] == [True, True, False],
          f"subs: a complete roster pages by offset to its end, got {pages}", fails)
    print("subscribers: 3 active, 5 expired, any other status, a count mismatch or expired read is incomplete")

    GRANT, OTHER = "900640044332167168", "900712726843187200"
    priced = {"id": "1", "senderId": "700237824869654528", "content": "ppv"}

    def opened(price, media_ids, purchased, attachments=None):
        msg = dict(priced)
        if attachments is not None:
            msg["attachments"] = attachments
        m = shim.of_message(
            msg, account_id="700237824869654528",
            media=[{"id": i} for i in media_ids], price=price,
            purchased_ids=set(purchased) if purchased is not None else None)
        return m["isOpened"]

    check(opened(3.0, [GRANT], [GRANT]) is True,
          "ppv: the grant this fan actually bought reports opened", fails)
    check(opened(3.0, [GRANT], []) is False,
          "ppv: no purchase on record stays LOCKED (never claim a fan paid)", fails)
    check(opened(3.0, [OTHER], [GRANT]) is False,
          "ppv: a purchase of a DIFFERENT grant must not open this message", fails)
    check(opened(0, [], []) is True,
          "ppv: a free message is open regardless (isPPV is false anyway)", fails)
    check(opened(3.0, [OTHER, GRANT], [GRANT]) is True,
          "ppv: buying any one locked grant opens the whole message", fails)
    check(opened(3.0, [GRANT], None) is False,
          "ppv: an unknown purchase set degrades to locked, not unlocked", fails)
    BUNDLE, MEMBER = "bundle-77", "member-88"
    bundle_att = [{"contentId": BUNDLE, "contentType": 2}]
    check(opened(9.0, [MEMBER], [MEMBER], bundle_att) is True,
          "ppv/bundle: a purchase naming a MEMBER grant unlocks", fails)
    check(opened(9.0, [MEMBER], [BUNDLE], bundle_att) is True,
          "ppv/bundle: a purchase naming the BUNDLE id also unlocks", fails)
    check(opened(9.0, [MEMBER], ["someone-elses"], bundle_att) is False,
          "ppv/bundle: an unrelated purchase still leaves it locked", fails)
    print("ppv unlock: purchase notifications open exactly the buyer's own message")

    # The purchase feed is account-wide: fetch once and index by buyer, never per fan (a 50-row inbox became 50 identical requests).
    class _FeedSpy(shim.FanslyShimClient):
        def __init__(self):
            self.calls = 0
        def _notification_rows(self):
            self.calls += 1
            return [
                {"type": 2007, "correlationGroupId": "fanA", "correlationId": "g1"},
                {"type": 2008, "correlationGroupId": "fanA", "correlationId": "g2"},
                {"type": 2007, "correlationGroupId": "fanB", "correlationId": "g3"},
                {"type": 3003, "correlationGroupId": "fanA", "correlationId": "not-a-buy"},
                {"type": "bogus", "correlationGroupId": "fanA", "correlationId": "x"},
            ]

    spy = _FeedSpy()
    by_fan = spy._purchases_by_fan()
    a, b, c = (by_fan.get("fanA", frozenset()), by_fan.get("fanB", frozenset()),
               by_fan.get("fanC", frozenset()))
    spy._purchases_by_fan()
    check(spy.calls == 1, f"ppv: the feed is fetched ONCE for many fans, got {spy.calls}", fails)
    check(a == {"g1", "g2"}, f"ppv: both of fanA's purchases indexed, got {a}", fails)
    check(b == {"g3"}, f"ppv: fanB gets only their own purchase, got {b}", fails)
    check(c == frozenset(), "ppv: a fan who bought nothing yields an empty set", fails)
    check("not-a-buy" not in a, "ppv: a non-purchase notification is not a purchase", fails)
    print("ppv unlock: account-wide feed read once, indexed per buyer")

    price_cases = [
        ('{"accountMediaPrice":3000}', 3.0, "the live $3 capture's exact shape"),
        ({"accountMediaPrice": 3000}, 3.0, "an already-decoded dict"),
        ('{"price":101000}', 101.0, "the $101 send's unit"),
        # A priced row we cannot read is omitted, never reported as 0.0: a money writer must not see a free unlock and an unreadable price as the same thing.
        (None, 0.0, "a social row with null metadata"),
        ("not json", 0.0, "unparseable metadata never invents revenue"),
        ("[]", 0.0, "a non-dict payload never invents revenue"),
        ('{"accountMediaPrice":"abc"}', 0.0, "a non-numeric price never invents revenue"),
        ('{"accountMediaPrice":0}', 0.0, "a free grant stays honestly free"),
    ]
    for meta, want, why in price_cases:
        got = shim._notif_price_usd({"metadata": meta}, None)
        check(got == want, f"notif price: {why} -> {got}, want {want}", fails)
    check(shim._notif_price_usd({}, None) == 0.0,
          "notif price: a row with no metadata key at all is free", fails)
    for code, want in ((2007, 0.0), ("2007", 0.0), (2007.9, 0.0), (2008, 3.0)):
        item = _PurchaseFeed([])._of_notification({"type": code, "metadata": {"price": 3000}}, {})
        check(item["fanslyPriceUsd"] == want and ("$3.00" in item["text"]) == bool(want),
              f"notif price: code {code} fallback, got {item}", fails)
    print("notif price: purchase rows report their dollar amount, junk reports 0")

    live = {"id": "900642430324908036", "type": 2007,
            "correlationId": "900640044332167168",
            "correlationGroupId": "900604711209099264",
            "createdAt": 1788335912,
            "metadata": '{"accountMediaPrice":3000}'}
    got = _PurchaseFeed([live]).purchases()["sales"]
    check(len(got) == 1, f"purchases: the live $3 sale is reported, got {got}", fails)
    if got:
        p = got[0]
        check(p["id"] == "900642430324908036", "purchases: the stable notification id is the dedup key", fails)
        check(p["fan_id"] == "900604711209099264", "purchases: correlationGroupId is the BUYER", fails)
        check(p["grant_id"] == "900640044332167168", "purchases: correlationId is the media bought", fails)
        check(p["price_usd"] == 3.0, f"purchases: 3000 units is $3.00, got {p['price_usd']}", fails)
        check(p["created_at"] == 1788335912, "purchases: epoch seconds pass through", fails)

    noise = [
        {"id": "1", "type": 3003, "correlationGroupId": "5", "createdAt": 1},
        {"id": "2", "type": 15011, "correlationGroupId": "5", "createdAt": 1},
        {"id": "3", "type": 2007, "correlationGroupId": "5", "createdAt": 1,
         "metadata": None},
        {"id": "4", "type": 2007, "correlationGroupId": "5", "createdAt": 1,
         "metadata": '{"accountMediaPrice":0}'},
        {"id": "5", "type": 45012, "correlationGroupId": "5", "createdAt": 1,
         "metadata": '{"accountMediaPrice":9000}'},
    ]
    quiet = _PurchaseFeed(noise).purchases()
    check(quiet == {"sales": [], "unbanked_seen": {"2007_unpriced": 1, "45012": 1}},
          f"purchases: only Banking-set sales; unbanked codes counted, got {quiet}", fails)
    print("purchases: proven sales only, priced in dollars, buyer + grant named")

    tipped = shim.of_message({"id": "1", "senderId": "5", "totalTipAmount": 3000},
                             account_id=ACCOUNT_ID)
    check(tipped["isTip"] is True and "tipAmount" not in tipped,
          f"of_message: a tip keeps isTip and carries no amount, got {tipped}", fails)

    class _ListProbe(shim.FanslyShimClient):
        def __init__(self):
            self.calls = []

        def _request(self, method, path, *, params=None, json_body=None, **kw):
            self.calls.append((method, path, json_body))
            return json_body["listCommands"]

    lp = _ListProbe()
    added = lp.add_users_to_lists({"900000000000000201": [900000000000000002, 900000000000000003],
                                   900000000000000202: ["900000000000000002"]})
    check(lp.calls == [("POST", "/lists/commands", {"listCommands": [
        {"type": 1, "listItem": {"id": "900000000000000002", "listId": "900000000000000201"}},
        {"type": 1, "listItem": {"id": "900000000000000003", "listId": "900000000000000201"}},
        {"type": 1, "listItem": {"id": "900000000000000002", "listId": "900000000000000202"}}]})],
          f"list-add: one type-1 singular listItem per fan, ids as strings, got {lp.calls}", fails)
    check(added == {"900000000000000201": ["900000000000000002", "900000000000000003"],
                    "900000000000000202": ["900000000000000002"]},
          f"list-add: returns string ids read from the echo, got {added}", fails)
    print("list-add: recipe body, string ids back")

    class _RemoveProbe(_ListProbe):
        def __init__(self, echo):
            super().__init__()
            self.echo = echo

        def _request(self, method, path, *, params=None, json_body=None, **kw):
            self.calls.append((method, path, json_body))
            return self.echo(json_body["listCommands"])

    lid, fid = "900000000000000201", "900000000000000002"
    rp = _RemoveProbe(lambda cmds: cmds)
    check(rp.remove_user_from_list(int(lid), int(fid)) == {"success": True}
          and rp.calls == [("POST", "/lists/commands", {"listCommands": [
              {"type": 2, "listId": lid, "itemIds": [fid]}]})],
          f"list-remove: recipe type-2 body, echoed command confirms, got {rp.calls}", fails)
    for label, echo in (
            ("an empty echo", lambda _c: []),
            ("a non-list echo", lambda _c: None),
            ("an add echo for the fan", lambda _c: [{"type": 1, "listItem": {"id": fid, "listId": lid}}]),
            ("a remove of another fan", lambda _c: [{"type": 2, "listId": lid, "itemIds": ["900000000000000003"]}]),
            ("a remove from another list", lambda _c: [{"type": 2, "listId": "900000000000000202", "itemIds": [fid]}])):
        try:
            _RemoveProbe(echo).remove_user_from_list(lid, fid)
        except shim.FanslyAPIError:
            continue
        fails.append(f"list-remove: {label} must raise")
    print("list-remove: counts only when the type-2 command for that fan is echoed")

    dp = _RemoveProbe(lambda _c: None)
    dp._request = lambda method, path, *, params=None, json_body=None, **kw: dp.calls.append(
        (method, path, json_body))
    check(dp.delete_list(int(lid)) == {"success": True}
          and dp.calls == [("POST", "/lists/remove", {"listId": lid})],
          f"list-delete: recipe body, null answer confirms, got {dp.calls}", fails)
    try:
        bad = _ListProbe()
        bad._request = lambda *a, **k: {"id": lid}
        bad.delete_list(lid)
        fails.append("list-delete: a non-null answer must raise")
    except shim.FanslyAPIError:
        pass
    check(getattr(shim.FanslyShimClient.delete_list, "platform_live_check", None),
          "list-delete: marked platform_live_check", fails)
    print("list-delete: POST /lists/remove {listId}, null answer, Live-check marked")

    class _ReadProbe(_ListProbe):
        def __init__(self, rows, lists=(lid,)):
            super().__init__()
            self.rows, self.lists = rows, lists
            self.session = type("S", (), {"account_id": ACCOUNT_ID})()

        def _request(self, method, path, *, params=None, json_body=None, **kw):
            self.calls.append((method, path, params, json_body))
            if path == "/lists/account":
                if not isinstance(self.lists, tuple):
                    return self.lists
                return [{"id": i, "label": "x", "type": 1, "accountId": ACCOUNT_ID} for i in self.lists]
            if path == "/lists/edit":
                return self.rows(json_body)
            return self.rows

    def member(i, **kw):
        return {"id": i, "sortId": "0", "listId": lid, "type": 1, "metadata": "", **kw}

    lists_read = ("GET", "/lists/account", {"itemId": ""}, None)
    items_read = ("GET", "/lists/itemsnew", {"listId": lid, "limit": "50", "sortMode": "3"}, None)
    rp = _ReadProbe([member(fid)])
    check(rp.list_users_in(int(lid)) == {"list": [{"id": fid}], "hasMore": False}
          and rp.calls == [lists_read, items_read],
          f"list-read: account lists, then one itemsnew page as {{list, hasMore}}, got {rp.calls}", fails)
    full = _ReadProbe([member(str(900000000000001000 + i)) for i in range(50)])
    page = full.list_users_in(lid)
    check(page["hasMore"] is True and len(page["list"]) == 50 and full.calls == [lists_read, items_read],
          f"list-read: a 50-row page is hasMore and never a second GET, got {full.calls}", fails)
    over = _ReadProbe([member(str(900000000000001000 + i)) for i in range(51)])
    check(over.list_users_in(lid)["hasMore"] is True and over.calls == [lists_read, items_read],
          f"list-read: a 51-row page is hasMore too, got {over.calls}", fails)
    for label, args, kw in (("a built-in key", ("fans",), {}), ("limit 20", (lid,), {"limit": 20}),
                            ("offset 50", (lid,), {"offset": 50}), ("a query", (lid,), {"query": "a"}),
                            ("an empty query", (lid,), {"query": ""})):
        probe = _ReadProbe([member(fid)])
        try:
            probe.list_users_in(*args, **kw)
            fails.append(f"list-read: {label} must raise")
        except shim.FanslyUnsupported as e:
            check(e.reason == "platform_lacks:list_users_in" and probe.calls == [],
                  f"list-read: {label} must refuse before any request, got {e.reason} {probe.calls}", fails)
    gone = _ReadProbe([member(fid)], lists=())
    try:
        gone.list_users_in(lid)
        fails.append("list-read: a list absent from /lists/account must raise, never read empty")
    except shim.ListGone as e:
        check(gone.calls == [lists_read],
              f"list-read: an unknown list refuses after the account read, got {e} {gone.calls}", fails)
    for label, answer in (("a null", None), ("a dict", {"list": [{"id": lid}]}),
                          ("a row without an id", [{"label": "misformed"}])):
        odd = _ReadProbe([member(fid)], lists=answer)
        try:
            odd.list_users_in(lid)
            fails.append(f"list-read: {label} /lists/account answer must raise")
        except shim.FanslyUnsupported:
            fails.append(f"list-read: {label} /lists/account answer is a bad answer, not a gone list")
        except shim.FanslyAPIError:
            check(odd.calls == [lists_read], f"list-read: {label} account answer stops there, got {odd.calls}", fails)
    for label, rows in (("a type-2 row", [member(fid, type=2)]), ("a numeric id", [member(int(fid))]),
                        ("a non-digit id", [member("abc")]), ("an empty id", [member("")]),
                        ("a malformed row beside the Proof fan", [member(fid), member("x1")]),
                        ("a dict answer", {"list": []}), ("a null answer", None)):
        try:
            _ReadProbe(rows).list_users_in(lid)
            fails.append(f"list-read: {label} must raise")
        except shim.FanslyUnsupported:
            fails.append(f"list-read: {label} is a bad answer, not a refusal")
        except shim.FanslyAPIError:
            pass
    print("list-read: one itemsnew page, hasMore from 50 rows, refusals before any request, unknown list refused")

    np = _ReadProbe(lambda body: {"accountId": ACCOUNT_ID, "type": 1, "id": body["id"], "label": body["label"]})
    check(np.rename_list(int(lid), "renamed") == {"id": lid, "name": "renamed"}
          and np.calls == [("POST", "/lists/edit", None, {"id": lid, "accountId": ACCOUNT_ID, "pos": None,
                                                          "type": 1, "label": "renamed"})],
          f"list-rename: recipe body, echoed label confirms, got {np.calls}", fails)
    for label, echo in (("another label", lambda b: {"id": b["id"], "label": "old"}),
                        ("another list", lambda b: {"id": "900000000000000202", "label": b["label"]}),
                        ("a null echo", lambda _b: None), ("a list echo", lambda _b: [])):
        try:
            _ReadProbe(echo).rename_list(lid, "renamed")
            fails.append(f"list-rename: an echo of {label} must raise")
        except shim.FanslyAPIError:
            pass
    for key in ("fans", "", "12a"):
        probe = _ReadProbe(lambda b: b)
        try:
            probe.rename_list(key, "renamed")
            fails.append(f"list-rename: list id {key!r} must raise")
        except shim.FanslyUnsupported as e:
            check(e.reason == "platform_lacks:rename_list" and probe.calls == [],
                  f"list-rename: list id {key!r} must refuse before any request, got {e.reason} {probe.calls}", fails)
    check(not getattr(shim.FanslyShimClient.rename_list, "platform_live_check", None),
          "list-rename: built without a Live check", fails)
    print("list-rename: POST /lists/edit, echo of that list and label confirms, non-numeric id refused, no Live check")

    class _BlockProbe(_ListProbe):
        def __init__(self, ignore, echo=None):
            super().__init__()
            self.ignore, self.echo = ignore, echo

        def _request(self, method, path, *, params=None, json_body=None, **kw):
            self.calls.append((method, path, params, json_body))
            if path == "/ignore":
                return self.ignore
            return self.echo if self.echo is not None else {"accountId": ACCOUNT_ID, **json_body}

    read = ("GET", "/ignore", {"noAggregation": "true"}, None)
    bp = _BlockProbe({"ignoring": [], "accounts": []})
    check(bp.block_user(int(fid)) == {"success": True}
          and bp.calls == [read, ("POST", "/account/ignore", None, {"ignoredId": fid, "ignoreFlags": 2})],
          f"block: empty /ignore read, then ignoreFlags 2 for that fan, got {bp.calls}", fails)
    for label, ignore in (
            ("a populated read", {"ignoring": [{"ignoredId": fid, "ignoreFlags": 2}], "accounts": []}),
            ("an extra key", {"ignoring": [], "accounts": [], "more": True}),
            ("a null read", None),
            ("a list read", [])):
        probe = _BlockProbe(ignore)
        try:
            probe.block_user(fid)
            fails.append(f"block: {label} must raise")
        except shim.FanslyUnsupported as e:
            check(e.reason == "platform_lacks:block_user", f"block: {label} reason {e.reason!r}", fails)
        check(probe.calls == [read], f"block: {label} must stop before any POST, got {probe.calls}", fails)
    for label, echo in (("another fan", {"ignoredId": "900000000000000003", "ignoreFlags": 2}),
                        ("a mute", {"ignoredId": fid, "ignoreFlags": 1}), ("no echo", [])):
        try:
            _BlockProbe({"ignoring": [], "accounts": []}, echo).block_user(fid)
            fails.append(f"block: an echo of {label} must raise")
        except shim.FanslyAPIError:
            pass
    check(getattr(shim.FanslyShimClient.block_user, "platform_live_check", None),
          "block: marked platform_live_check", fails)
    check(getattr(shim.FanslyShimClient.unblock_user, "platform_blocked", None),
          "unblock: stays platform_blocked", fails)
    print("block: GET /ignore empty, then POST /account/ignore flags 2, Live-check marked; unblock Blocked")

    class _PromoProbe(_ListProbe):
        def _request(self, method, path, *, params=None, json_body=None, **kw):
            self.calls.append((method, path, json_body))
            if path == "/subscriptions/tiers":
                return [{"id": "t1", "plans": [{"id": "p1", "status": 1, "price": 5000}]}]
            return {"id": "g1", "status": 1, "maxUses": json_body["maxUses"], "duration": json_body["duration"]}

    for label, kw in (("type all", {"type": "all"}), ("type expired", {"type": "expired"}),
                      ("a type list", {"type": ["all", "expired"]}), ("finish_days", {"finish_days": 3}),
                      ("finish_days 0", {"finish_days": 0}), ("unlimited claims", {"subscribe_counts": 0})):
        pp = _PromoProbe()
        try:
            pp.create_promo(**{"discount": 50, "subscribe_counts": 3, **kw})
        except shim.FanslyUnsupported as e:
            check(pp.calls == [], f"create_promo {label}: raised after a request {pp.calls}", fails)
            check(e.reason == ("platform_lacks:promotion_type" if "type" in kw else None),
                  f"create_promo {label}: reason {e.reason!r}", fails)
            continue
        fails.append(f"create_promo: {label} must raise before any request, sent {pp.calls}")
    pp = _PromoProbe()
    try:
        pp.create_promo(discount=50, subscribe_counts=3, mirror=True)
        fails.append(f"create_promo: an unknown kwarg must raise, sent {pp.calls}")
    except TypeError:
        check(pp.calls == [], f"create_promo unknown kwarg: raised after a request {pp.calls}", fails)
    pp = _PromoProbe()
    made = pp.create_promo(discount=50, subscribe_counts=3, subscribe_days=7, type="new", finish_days=None)
    check([c[:2] for c in pp.calls] == [("GET", "/subscriptions/tiers"), ("POST", "/subscriptions/giftcodes")]
          and pp.calls[1][2]["newSubscribersOnly"] == 1 and pp.calls[1][2]["maxUses"] == 3
          and made["subscribeCounts"] == 3,
          f"create_promo: a new-subscriber giftcode still posts, got {pp.calls}", fails)
    print("create_promo: type other than new, finish_days and unlimited claims raise before any request")

    chart_reason = ("Fansly reports subscriber TOTALS only, with no per-day series; "
                    "synthesising one would be invented analytics")
    for kw in ({}, {"start": "2026-10-01 00:00:00", "end": "2026-10-31 23:59:59", "by": "new"}):
        cp = _PromoProbe()
        try:
            got = cp.subscribers_chart(**kw)
            fails.append(f"subscribers_chart {kw}: answered {got!r} instead of raising")
        except shim.FanslyUnsupported as e:
            check(str(e) == f"subscribers_chart: {chart_reason}" and cp.calls == [],
                  f"subscribers_chart {kw}: {e} after {cp.calls}", fails)
    print("subscribers_chart: raises with no returns, before any request")

    missing = set(reads) - used
    check(not missing, f"fixture reads not used: {sorted(missing)}", fails)

    for f in fails:
        print(f"  FAIL {f}", file=sys.stderr)
    if fails:
        print(f"{len(fails)} check(s) failed", file=sys.stderr)
        return 1
    print("all shape checks passed — shim emits OF's inbox shape")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
