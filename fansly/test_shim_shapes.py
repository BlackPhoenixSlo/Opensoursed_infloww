"""
Prove the inbox shim emits OF's shape — offline, against the captured HAR.

Same gate philosophy as test_har_replay: don't trust the reshaper until it
reproduces the shape the relay's inbox actually reads, on real Fansly bodies.
No network.

    ../venv/bin/python test_shim_shapes.py [path/to/fanslycalls.har]
"""
from __future__ import annotations

import base64
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlsplit

import fansly_shim as shim

HERE = Path(__file__).resolve().parent
DEFAULT_HAR = HERE / "fanslycalls.har"
ACCOUNT_ID = "700237824869654528"   # us, in the capture


def _bodies(har_path: Path, path: str, method: str = "GET") -> list[dict]:
    har = json.loads(har_path.read_text())
    out = []
    for entry in har["log"]["entries"]:
        req = entry["request"]
        parts = urlsplit(req["url"])
        if parts.netloc != "apiv3.fansly.com" or req["method"] != method:
            continue
        if parts.path != path:
            continue
        content = entry["response"].get("content", {})
        text = content.get("text") or ""
        if content.get("encoding") == "base64":
            try:
                text = base64.b64decode(text).decode("utf-8", "replace")
            except Exception:
                continue
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        if payload.get("success") and isinstance(payload.get("response"), dict):
            out.append(payload["response"])
    return out


def check(cond: bool, label: str, fails: list[str]) -> None:
    if not cond:
        fails.append(label)


def main(argv: list[str]) -> int:
    har_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_HAR
    if not har_path.exists():
        print(f"no HAR at {har_path}", file=sys.stderr)
        return 1

    fails: list[str] = []

    # ---- /messaging/groups -> OF /chats -------------------------------
    groups = _bodies(har_path, "/api/v1/messaging/groups")
    check(bool(groups), "no /messaging/groups body in HAR", fails)
    if groups:
        page = shim.of_chats_page(groups[0], account_id=ACCOUNT_ID, limit=20)
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

    # ---- /message -> OF messages --------------------------------------
    messages = _bodies(har_path, "/api/v1/message")
    check(bool(messages), "no /message body in HAR", fails)
    if messages:
        page = shim.of_messages_page(messages[0], account_id=ACCOUNT_ID, limit=25)
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
        # Prove the outbound flag: a message from us reads as fromUser.id == me.
        by_us = [x for x in page["list"] if x["fromUser"]["id"] == ACCOUNT_ID]
        by_fan = [x for x in page["list"] if x["fromUser"]["id"] != ACCOUNT_ID]
        print(f"messages: {len(page['list'])} msg(s); {len(by_us)} ours / "
              f"{len(by_fan)} theirs; sample text={m['text']!r} at {m['createdAt']}")

    # ---- roster badge rule: OF's "a reply clears unread", on Fansly data ----
    # Fansly keeps counting unread fan messages after we reply (OF zeroes them),
    # so emitting `unreadCount` verbatim pinned the roster badge blue forever:
    # _roster_counts_from_rows tests unread FIRST, so a replied-to chat could
    # never reach the orange "owe reply" state. The membership's own two
    # pointers settle who spoke last without another call.
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

    # Absent pointers mean "can't tell" — never hide a waiting fan.
    unknown = shim.of_chat_row(
        {"groupId": "g3", "unreadCount": 2}, None, None, account_id=ACCOUNT_ID)
    check(unknown["unreadMessagesCount"] == 2,
          "no read-state pointers -> unread preserved (fail safe)", fails)
    print("badge rule: a reply clears unread; fan-last and unknown stay blue")

    # ---- read receipt: POST /message/ack (captured in messageread.har) ------
    # Opening an unread thread in Fansly web posts
    #   {"messageIds": ["<lastUnreadMessageId>"], "type": 2} -> {"success": true}
    # mark_chat_read was a STUB returning success without calling Fansly, so the
    # badge went orange on open and the next poll restored the blue.
    # Unread is per-MESSAGE, so the ack sends EVERY unread id, not just the
    # membership's lastUnreadMessageId. Measured live: on a thread with
    # unreadCount 2, acking only the newest id succeeded and left the count at
    # 2; acking both took it to 0. This probe is where that stays fixed.
    class _AckProbe(shim.FanslyShimClient):
        """Drives mark_chat_read with no network: records the calls it makes."""
        def __init__(self, *, unread=(), fail=False):  # noqa: D107
            self.calls = []
            self._unread = list(unread)
            self._fail = fail
            class _S:  # minimal session stand-in
                account_id = ACCOUNT_ID
            self.session = _S()

        def _as_group_id(self, chat_id):
            return str(chat_id)

        def _request(self, method, path, *, params=None, json_body=None, **kw):
            self.calls.append((method, path, json_body))
            if path == "/message":
                # Newest-first, mixed with one of OUR OWN sends (which carries
                # an interaction for the FAN, never for us) and one already-read
                # fan message — neither may be acked.
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

    # A stale pointer (Fansly names a message it will not ack) must not turn an
    # ordinary chat-open into a 502 — the route is fire-and-forget.
    stale = _AckProbe(unread=["900307747011272705"], fail=True)
    check(stale.mark_chat_read("g1") == {"success": False, "reason": "ack_rejected"},
          "ack: a rejected ack degrades instead of raising", fails)
    print("read receipt: acks EVERY unread id; no-ops when clean; survives a reject")

    # ---- the same probe against REAL captured bodies (prompt 06, 2026-09-02) --
    # Three DMs sent live from a second account (fantester) to this one, with
    # the raw /message and /messaging/groups rows saved BEFORE the ack. This is
    # the multi-id ack gated on real Fansly shapes, not only the hand-built rows
    # above: interactions[].readAt is a literal 0 (not null), deliveredAt is ms,
    # and the thread reported unreadCount 3 with a single lastUnreadMessageId.
    fx_path = HERE / "capture" / "fixtures_a2_thread.json"
    if fx_path.exists():
        fx = json.loads(fx_path.read_text())
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
              "ack/real: fixture is a 3-unread thread", fails)
        check(len(real_ids) > 1 and grp["lastUnreadMessageId"] in real_ids,
              "ack/real: pointer names only ONE of the unread ids", fails)
        check(rp._unread_message_ids(grp["groupId"]) == real_ids,
              f"ack/real: scan returns all three real ids, got "
              f"{rp._unread_message_ids(grp['groupId'])}", fails)
        rp.mark_chat_read(grp["groupId"])
        acks = [c for c in rp.calls if c[1] == "/message/ack"]
        check(acks and acks[0][2] == {"messageIds": real_ids, "type": 2},
              "ack/real: acks all three captured ids in one call", fails)
        print("read receipt (real bodies): 3 live ids scanned and acked together")
    else:
        print("read receipt (real bodies): fixture missing, SKIPPED", file=sys.stderr)

    # mark-all is the same ack off ONE groups listing, and it is the only path
    # that can fan out — so the cap is part of its contract, not a detail.
    class _MarkAllProbe(_AckProbe):
        """mark_all_chats_read with no network. `groups` is [(id, unreadCount)]."""
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
                # One unread id per group, named after the group it came from.
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

    # The cap is the safety net the plan requires — a bug upstream must not be
    # able to ack the whole inbox.
    huge = _MarkAllProbe([(f"g{i}", 1) for i in range(120)])
    huge.mark_all_chats_read()
    check(len(huge.scanned) == shim.FanslyShimClient._MARK_ALL_CAP,
          f"mark-all: fan-out capped at {shim.FanslyShimClient._MARK_ALL_CAP}, "
          f"scanned {len(huge.scanned)}", fails)
    print("mark-all: batched ack of every unread id; capped; clean inbox no-ops")

    # ── notifications ────────────────────────────────────────────────────
    # These were empty stubs. Fansly's rows are bare ids + an int `type` in the
    # `serviceId * 1000 + eventType` namespace, so the whole feature is the
    # code->OF-type map plus one batch profile hydration. Only 15011 has ever
    # been observed live on this account; the rest of the table is mapped from
    # the client's own filter list, so this test is where the mapping is pinned.
    class _NotifProbe(shim.FanslyShimClient):
        """Serves a fixed notification page with no network."""
        def __init__(self, rows, *, accounts=True):  # noqa: D107
            self.rows = rows
            self._accounts = accounts
            self.calls = []

        def _request(self, method, path, *, params=None, json_body=None, **kw):
            self.calls.append((method, path))
            if path == "/notifications":
                return {"notifications": self.rows}
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
          f"notif: subscribe/follow codes -> 'subscribed', got {got}", fails)
    check(got.get(7001) == "tip", f"notif: 7001 -> 'tip', got {got.get(7001)}", fails)
    check(got.get(2007) == "purchases",
          f"notif: 2007 -> 'purchases', got {got.get(2007)}", fails)
    # An unmapped code must NOT fall into a real OF bucket — a mislabeled money
    # event is worse than a hidden one.
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

    # `type=` filters client-side on the MAPPED type, so send_welcome's
    # type="subscribed" call selects follow/subscribe codes unchanged.
    subs = notif.notifications(type="subscribed", limit=20)["list"]
    check([i["fanslyType"] for i in subs] == [15006, 3002],
          f"notif: type filter selects the subscribe bucket, got {subs}", fails)

    # The badge counts UNREAD rows only, off the same fetch the feed uses.
    counts = notif.notifications_count()
    check(counts["subscribes"] == 2 and counts["tips"] == 1,
          f"notif: badge buckets by mapped type, got {counts}", fails)
    check(counts["all"] == 4,
          f"notif: acked row excluded from the badge, got all={counts['all']}", fails)

    # Profile hydration is decoration: losing it must not empty the feed.
    # The shim logs that failure with a traceback (correct in production); mute
    # it here so an EXPECTED exception doesn't read as a test blowing up.
    blind = _NotifProbe([_row("1", 7001)], accounts=False)
    logging.getLogger("of-relay.fansly.shim").setLevel(logging.CRITICAL)
    try:
        degraded = blind.notifications(limit=20)["list"]
    finally:
        logging.getLogger("of-relay.fansly.shim").setLevel(logging.NOTSET)
    check(len(degraded) == 1 and degraded[0]["user"] is None,
          "notif: a failed profile lookup degrades, it does not empty the feed", fails)
    print("notifications: type codes map to OF buckets; unmapped stay namespaced")

    # Which correlation id is the ACTOR differs per code — observed live on
    # 2026-09-02 (prompt 06): a follow puts the follower in correlationGroupId,
    # a post like puts the liker in correlationId (and the post in
    # correlationGroupId), and a message like / post reply carry NO account id
    # at all. Before this the shim hydrated correlationGroupId for every code,
    # which looked up a post id as a profile for 1002 and left the liker blank.
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

    # ── subscribers (REAL row, captured 2026-09-02) ──────────────────────
    # The first subscriber this account ever had: a gift-code trial from a
    # second account. Money is 1/1000 $ (5000 == $5), times are MS on this
    # object, and the fan is hydrated from subscriberId.
    sub_fx = HERE / "capture" / "fixtures_subscribers.json"
    if sub_fx.exists():
        payload = json.loads(sub_fx.read_text())

        class _SubProbe(shim.FanslyShimClient):
            def __init__(self):  # noqa: D107
                class _S:
                    account_id = ACCOUNT_ID
                self.session = _S()

            def _subscribers_payload(self):
                return payload

            def _request(self, method, path, *, params=None, json_body=None, **kw):
                if path == "/account":
                    return [{"id": "900604711209099264", "username": "fantester",
                             "flags": 16, "statusId": 1}]
                return {}

        sp = _SubProbe()
        fans = sp.subscribers(type="active", limit=10)["list"]
        check(len(fans) == 1 and fans[0]["id"] == "900604711209099264"
              and fans[0]["username"] == "fantester",
              "subs/real: row hydrates to the fan object keyed by subscriberId", fails)
        check(fans[0]["subscribedBy"] is True and fans[0]["subscribePrice"] == 5.0
              and fans[0]["currentSubscribePrice"] == 0.0,
              f"subs/real: status 3 is active, 5000 units == $5.00, trial == $0, got "
              f"{fans[0]['subscribePrice']}/{fans[0]['currentSubscribePrice']}", fails)
        check(fans[0]["subscribedByExpireDate"] == "2026-09-09T07:44:25+00:00",
              f"subs/real: endsAt is ms -> ISO, got {fans[0]['subscribedByExpireDate']}", fails)
        check(sp.subscribers(type="expired")["list"] == [],
              "subs/real: an active row is not in the expired filter", fails)
        check([f["id"] for f in sp.iter_online_subscribers(max_fans=5)] == ["900604711209099264"],
              "subs/real: iter_online_subscribers yields the online fan", fails)
        check(sp.subscription_counts() == {"active": 1, "expired": 0, "all": 1},
              "subs/real: counts come off stats", fails)
        print("subscribers: real row reshaped to OF's fan object; online walk works")
    else:
        print("subscribers: fixture missing, SKIPPED", file=sys.stderr)

    # ---- PPV unlock: a purchase, and ONLY the buyer's own, opens a bubble ----
    # Fansly never reports isOpened for the creator; the signal is a 2007/2008
    # notification naming the accountMedia GRANT the fan bought. Values are the
    # live ones from the real $3 unlock (fan 900604711209099264 buying grant
    # 900640044332167168) — see of_message's isOpened note.
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
    # BUNDLES. `_resolve_attachments` expands a contentType:2 bundle into its
    # members and DROPS the bundle id, so matching only on media[] would miss a
    # purchase recorded against the bundle. Whether Fansly reports the bundle or
    # a member grant is unverified (no bundle has been bought on this account),
    # so both must match — otherwise every bundled PPV stays locked forever.
    BUNDLE, MEMBER = "bundle-77", "member-88"
    bundle_att = [{"contentId": BUNDLE, "contentType": 2}]
    check(opened(9.0, [MEMBER], [MEMBER], bundle_att) is True,
          "ppv/bundle: a purchase naming a MEMBER grant unlocks", fails)
    check(opened(9.0, [MEMBER], [BUNDLE], bundle_att) is True,
          "ppv/bundle: a purchase naming the BUNDLE id also unlocks", fails)
    check(opened(9.0, [MEMBER], ["someone-elses"], bundle_att) is False,
          "ppv/bundle: an unrelated purchase still leaves it locked", fails)
    print("ppv unlock: purchase notifications open exactly the buyer's own message")

    # The feed is ACCOUNT-WIDE, so it must be fetched once and indexed by buyer
    # — not re-fetched per fan. A per-fan cache turned a 50-row inbox into 50
    # identical requests that each discarded 49/50ths of the answer.
    class _FeedSpy(shim.FanslyShimClient):
        def __init__(self):  # no session: we only exercise the pure indexing
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
    spy._purchases_by_fan()  # a second read must be served from cache
    check(spy.calls == 1, f"ppv: the feed is fetched ONCE for many fans, got {spy.calls}", fails)
    check(a == {"g1", "g2"}, f"ppv: both of fanA's purchases indexed, got {a}", fails)
    check(b == {"g3"}, f"ppv: fanB gets only their own purchase, got {b}", fails)
    check(c == frozenset(), "ppv: a fan who bought nothing yields an empty set", fails)
    check("not-a-buy" not in a, "ppv: a non-purchase notification is not a purchase", fails)
    print("ppv unlock: account-wide feed read once, indexed per buyer")

    # --- purchase notifications carry their dollar amount -------------------
    # The money surfaces (MoneyRail.amountFrom) regex the figure OUT OF THE
    # ROW TEXT, so a priced row that doesn't say its price renders a sale with
    # a blank amount. Shape confirmed live 2026-09-02 on a real $3 sale:
    # metadata is a JSON *string* of {"accountMediaPrice": <1/1000 dollars>}.
    price_cases = [
        ('{"accountMediaPrice":3000}', 3.0, "the live $3 capture's exact shape"),
        ({"accountMediaPrice": 3000}, 3.0, "an already-decoded dict"),
        ('{"price":101000}', 101.0, "the $101 send's unit"),
        (None, 0.0, "a social row with null metadata"),
        ("not json", 0.0, "unparseable metadata never invents revenue"),
        ("[]", 0.0, "a non-dict payload never invents revenue"),
        ('{"accountMediaPrice":"abc"}', 0.0, "a non-numeric price never invents revenue"),
        ('{"accountMediaPrice":0}', 0.0, "a free grant stays honestly free"),
    ]
    for meta, want, why in price_cases:
        got = shim._notif_price_usd({"metadata": meta})
        check(got == want, f"notif price: {why} -> {got}, want {want}", fails)
    check(shim._notif_price_usd({}) == 0.0,
          "notif price: a row with no metadata key at all is free", fails)
    print("notif price: purchase rows report their dollar amount, junk reports 0")

    # --- purchases(): the public "what did fans pay for" read ---------------
    # service/fansly_revenue banks these into the money ledger, so this method
    # is the boundary where Fansly's notification codes, its 1/1000-dollar
    # unit and its metadata layout stop being anyone else's problem.
    class _PurchaseFeed(shim.FanslyShimClient):
        def __init__(self, rows):
            self._rows = rows

        def _notification_rows(self):
            return self._rows

    live = {"id": "900642430324908036", "type": 2007,
            "correlationId": "900640044332167168",
            "correlationGroupId": "900604711209099264",
            "createdAt": 1788335912,
            "metadata": '{"accountMediaPrice":3000}'}
    got = _PurchaseFeed([live]).purchases()
    check(len(got) == 1, f"purchases: the live $3 sale is reported, got {got}", fails)
    if got:
        p = got[0]
        check(p["id"] == "900642430324908036", "purchases: the stable notification id is the dedup key", fails)
        check(p["fan_id"] == "900604711209099264", "purchases: correlationGroupId is the BUYER", fails)
        check(p["grant_id"] == "900640044332167168", "purchases: correlationId is the media bought", fails)
        check(p["price_usd"] == 3.0, f"purchases: 3000 units is $3.00, got {p['price_usd']}", fails)
        check(p["created_at"] == 1788335912, "purchases: epoch seconds pass through", fails)

    # Social rows are not sales, and a priced row we cannot read is omitted
    # rather than reported at 0.0 — a caller that writes money must not see a
    # free unlock and an unreadable price as the same thing.
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
    check(quiet == [], f"purchases: only proven, priced sales are reported, got {quiet}", fails)
    check(45012 in _PurchaseFeed([]).unbanked_purchase_codes(),
          "purchases: an unproven purchase code is surfaced, not silently dropped", fails)
    check(2007 not in _PurchaseFeed([]).unbanked_purchase_codes(),
          "purchases: a proven code is not reported as unbanked", fails)
    # A drop is right either way (fail-closed: understate, never fabricate),
    # but a row with NO known price key means the metadata SHAPE CHANGED and
    # real sales are being dropped. The feed is one page with no cursor, so
    # those scroll off for good — that has to be loud, while a genuine free
    # unlock (an explicit price of 0) stays quiet.
    import logging as _logging

    class _Catch(_logging.Handler):
        def __init__(self):
            super().__init__()
            self.hits = []

        def emit(self, rec):
            self.hits.append(rec.getMessage())

    def _warns(meta):
        cap = _Catch()
        lg = shim.log            # the module's own logger, not a guessed name
        lg.addHandler(cap)
        try:
            _PurchaseFeed([{"id": "n", "type": 2007, "correlationGroupId": "5",
                            "correlationId": "g", "createdAt": 1,
                            "metadata": meta}]).purchases()
        finally:
            lg.removeHandler(cap)
        return any("SALES ARE BEING DROPPED" in h for h in cap.hits)

    check(_warns('{"mediaPrice":3000}'),
          "purchases: a drifted metadata shape warns instead of silently losing a sale", fails)
    check(not _warns('{"accountMediaPrice":0}'),
          "purchases: a genuine free unlock does NOT cry drift", fails)
    check(not _warns('{"accountMediaPrice":3000}'),
          "purchases: a normal priced sale does NOT cry drift", fails)
    print("purchases: a metadata shape change is loud; a free unlock is quiet")

    print("purchases: proven sales only, priced in dollars, buyer + grant named")

    for f in fails:
        print(f"  FAIL {f}", file=sys.stderr)
    if fails:
        print(f"{len(fails)} check(s) failed", file=sys.stderr)
        return 1
    print("all shape checks passed — shim emits OF's inbox shape")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
