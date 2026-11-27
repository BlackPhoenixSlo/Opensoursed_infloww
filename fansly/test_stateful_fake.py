from __future__ import annotations

import sys
from pathlib import Path

from fansly_client import API_BASE
from stateful_fake import ROUTES, StatefulFansly, Unmodelled

HERE = Path(__file__).resolve().parent
RECIPES = HERE / "capture" / "RECIPES.md"

FAN = "900000000000000002"
FAN_GROUP = "900000000000000101"
NEW_FAN = "900000000000000009"
FAN_MESSAGE = "900000000000000304"
LOCKED_MESSAGE = "900000000000000303"
OTHER_FAN = "900000000000000003"
FLAGS = ("INVENTED: ", "ASSUMPTION: ")
FLAGGED = {("POST", "/group"), ("GET", "/lists/itemsnew"), ("GET", "/message"),
           ("POST", "/message"), ("GET", "/subscribers"), ("GET", "/account/me"), ("POST", "/message/ack")}


def _raises(fn) -> bool:
    try:
        fn()
    except Unmodelled:
        return True
    return False


def _members(c, list_id: str) -> list[str]:
    rows = c._request("GET", "/lists/itemsnew",
                      params={"listId": list_id, "limit": "50", "sortMode": "3"})
    return [r["id"] for r in rows]


def _sent_body(content: str, group_id: str, body: dict) -> dict:
    return {"type": 1, "attachments": [], "likes": [], "content": content,
            "groupId": group_id, "scheduledFor": 0, "inReplyTo": None,
            "createdAt": body.get("createdAt")}


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    headings = {line.strip() for line in RECIPES.read_text().splitlines() if line.startswith("#")}
    for route in ROUTES:
        check([s for s in route.sources if not s.startswith(FLAGS)],
              f"{route.method} {route.pattern} cites no source")
        for src in route.sources:
            if src.startswith(FLAGS):
                check(len(src) > 20, f"{route.method} {route.pattern}: empty flag {src!r}")
            elif src.startswith("RECIPES.md: "):
                check(src.removeprefix("RECIPES.md: ") in headings,
                      f"{route.method} {route.pattern}: no RECIPES heading {src!r}")
            else:
                check((HERE / src).is_file(), f"{route.method} {route.pattern}: no fixture {src!r}")
    flagged = {(r.method, r.pattern) for r in ROUTES if any(s.startswith(FLAGS) for s in r.sources)}
    check(flagged == FLAGGED, f"flagged routes changed: {flagged}")

    fake = StatefulFansly()
    c = fake.client()
    first = c.send_message(FAN, "hello")
    posts = [(m, p, b) for m, p, b, _q in fake.calls if m == "POST"]
    check(posts == [("POST", "/message", _sent_body("hello", FAN_GROUP, posts[0][2]))],
          f"a send to a fan with a thread must be one POST /message as captured: {posts}")
    check(isinstance(posts[0][2]["createdAt"], float), "createdAt must be float seconds")
    page = c.get_messages(FAN_GROUP)
    check(page["list"][0]["id"] == first["id"] and page["list"][0]["text"] == "hello",
          f"the send must read back as the thread's newest message: {page['list'][:1]}")
    second = c.send_message(FAN, "again")
    ids = [m["id"] for m in c.get_messages(FAN_GROUP)["list"]]
    check(second["id"] != first["id"] and ids[:2] == [second["id"], first["id"]],
          f"a repeated send must be a second message: {ids}")
    fake.calls.clear()
    c.unsend_message(first["id"])
    check(fake.calls == [("POST", "/message/delete", {"messageId": first["id"]}, {})],
          f"unsend must be one POST /message/delete as captured: {fake.calls}")
    raw = c._request("GET", "/message", params={"groupId": FAN_GROUP, "limit": "25"})["messages"]
    gone = next(m for m in raw if m["id"] == first["id"])
    check(gone.get("deletedAt"), f"an unsent message must read back with deletedAt: {gone}")
    check(fake.unmodelled == [], f"a modelled flow must record no unmodelled call: {fake.unmodelled}")
    check(_raises(lambda: c.unsend_message(first["id"])), "a repeated unsend is not captured and must raise")
    check(len(fake.unmodelled) == 1, f"every raise must be recorded on the fake: {fake.unmodelled}")
    check(_raises(lambda: c.get_messages(FAN_GROUP, before_id=second["id"])),
          "id-based paging on GET /message is not captured and must raise")
    check(_raises(lambda: c.get_messages(FAN_GROUP, limit=1)),
          "limit=1 was measured to answer empty; a row back would be invented, so it must raise")

    fake = StatefulFansly()
    c = fake.client()
    page = c.list_chats()
    check([p for m, p, _b, _q in fake.calls if m == "GET"] == ["/messaging/groups"],
          f"the captured groups page carries each last message; no per-thread GET /message: {fake.calls}")
    check(page["list"][0]["lastMessage"]["text"] == "synthetic tip note",
          f"the last message must come from aggregationData.messages: {page['list'][:1]}")
    locked = next(m for m in c.get_messages(FAN_GROUP)["list"] if m["id"] == LOCKED_MESSAGE)
    check(locked["media"], f"the captured accountMedia must back the locked message: {locked}")
    sent = c.send_message(FAN, "newest")
    check(c.list_chats()["list"][0]["lastMessage"]["id"] == sent["id"],
          "a send must read back as the thread's last message on the groups page")
    check(fake.unmodelled == [], f"a modelled flow must record no unmodelled call: {fake.unmodelled}")
    check(_raises(lambda: c.list_chats(filter="unread")), "flags=2 is not captured and must raise")
    check(_raises(lambda: c.list_chats(query="synth")), "a search is not captured and must raise")
    try:
        c.payout_balances()
    except Exception:
        pass
    check(len(fake.unmodelled) == 3 and "/payments/wallets" in fake.unmodelled[-1],
          f"a raise the Shim swallows must still be recorded: {fake.unmodelled}")
    check(_raises(lambda: fake.request("GET", API_BASE + "/notifications",
                                       params={"before": "0", "after": "0", "type": ""})),
          "a call without ngsw-bypass must raise")
    check(_raises(lambda: c._request("GET", "/notifications",
                                     params={"before": "0", "after": "0", "type": "1"})),
          "a query value that differs from the capture must raise")

    fake = StatefulFansly()
    fake.client().send_message(NEW_FAN, "first")
    groups = [b for m, p, b, _q in fake.calls if (m, p) == ("POST", "/group")]
    check(groups == [{"users": [{"userId": fake.account_id, "permissionFlags": 0},
                                {"userId": NEW_FAN, "permissionFlags": 0}],
                      "recipients": [], "lastMessage": None, "userSettings": None, "type": 1}],
          f"a first send must mint one DM group as captured: {groups}")
    fake.calls.clear()
    fake.client().send_message(NEW_FAN, "second")
    check(not [p for _m, p, _b, _q in fake.calls if p == "/group"],
          f"a repeat send from a fresh client must find the minted group, not mint again: {fake.calls}")

    fake = StatefulFansly()
    c = fake.client()
    made = c.create_list("vip")
    check({"id": made["id"], "name": "vip"} in c.get_lists()["list"], "a created list must read back")
    fake.calls.clear()
    c.add_user_to_list(made["id"], FAN)
    check(fake.calls == [("POST", "/lists/commands", {"listCommands": [
        {"type": 1, "listItem": {"id": FAN, "listId": made["id"]}}]}, {})],
        f"list add must be the captured type-1 command: {fake.calls}")
    check(_members(c, made["id"]) == [FAN], "an added member must read back")
    check(_raises(lambda: c.add_user_to_list(made["id"], FAN)), "a repeated add is not captured and must raise")
    check(_members(c, made["id"]) == [FAN], "a refused repeat add must change nothing")
    fake.calls.clear()
    c.remove_user_from_list(made["id"], FAN)
    check(fake.calls == [("POST", "/lists/commands", {"listCommands": [
        {"type": 2, "listId": made["id"], "itemIds": [FAN]}]}, {})],
        f"list remove must be the captured type-2 command: {fake.calls}")
    check(_members(c, made["id"]) == [], "a removed member must be gone on read back")
    check(_raises(lambda: c.remove_user_from_list(made["id"], FAN)),
          "removing a non-member is not captured and must raise")
    other = c.create_list("other")["id"]
    added = c.add_users_to_lists({made["id"]: [FAN, OTHER_FAN]})
    check(added == {made["id"]: [FAN, OTHER_FAN]}, f"a captured multi-add batch must echo both: {added}")
    check(_members(c, made["id"]) == [FAN, OTHER_FAN], "a multi-add batch must read back")
    check(_raises(lambda: c._request("POST", "/lists/commands", json_body={"listCommands": [
        {"type": 2, "listId": made["id"], "itemIds": [FAN, OTHER_FAN]}]})),
        "a multi-id remove is not captured and must raise")
    check(_raises(lambda: c._request("POST", "/lists/commands", json_body={"listCommands": [
        {"type": 1, "listItem": {"id": FAN, "listId": other}},
        {"type": 2, "listId": made["id"], "itemIds": [FAN]}]})),
        "a mixed add/remove batch is not captured and must raise")
    check(_members(c, made["id"]) == [FAN, OTHER_FAN] and _members(c, other) == [],
          "a refused batch must change nothing")
    check(_raises(lambda: c._request("GET", "/lists/itemsnew",
                                     params={"listId": other, "limit": "25", "sortMode": "3"})),
          "a list read with an uncaptured limit must raise")

    fake = StatefulFansly()
    c = fake.client()
    check(c.follow_user(FAN) == {"success": True}, "follow returns success")
    check(fake.calls == [("POST", f"/account/{FAN}/followers", None, {})],
          f"follow must be the captured bodyless POST: {fake.calls}")
    check(fake.following == {FAN}, "a follow must be held")
    check(_raises(lambda: c.follow_user(FAN)), "a repeated follow is not captured and must raise")
    fake.calls.clear()
    c.unfollow_user(FAN)
    check(fake.calls == [("POST", f"/account/{FAN}/followers/remove", None, {})],
          f"unfollow must be the captured bodyless POST: {fake.calls}")
    check(fake.following == set(), "an unfollow must undo the follow")

    fake = StatefulFansly()
    c = fake.client()
    lid = c.create_list("vip")["id"]
    check(_raises(lambda: c._request("POST", "/message", json_body={
        "type": 2, "attachments": [], "likes": [], "content": "x", "groupId": FAN_GROUP,
        "scheduledFor": 0, "inReplyTo": None, "createdAt": 1.5})),
        "a message type other than the captured 1 must raise")
    check(_raises(lambda: c._request("POST", "/lists/commands", json_body={"listCommands": [
        {"type": 1, "listItem": {"id": FAN, "listId": lid}},
        {"type": 1, "listId": lid, "itemIds": [FAN]}]})),
        "an add carrying the remove shape must raise")
    check(_members(c, lid) == [], "a refused batch must change nothing")
    check(_raises(lambda: c._request("POST", "/lists", json_body={
        "label": "x", "description": "", "type": 1})), "an extra body key must raise")

    fake = StatefulFansly()
    c = fake.client()
    check(c._request("GET", "/subscribers") == fake.subscribers, "the subscriber list must read back as captured")
    fake.renewal_off(1767830400001)
    sub = c._request("GET", "/subscribers")["subscriptions"][0]
    check((sub["autoRenew"], sub["endsAt"]) == (0, 1767830400001), f"renewal_off must read back: {sub}")
    known = next(iter(fake.profiles))
    check([a["id"] for a in c._request("GET", "/account", params={"ids": known})] == [known],
          "a captured account must read back by id")
    check(_raises(lambda: c._request("GET", "/account", params={"ids": OTHER_FAN})),
          "an account the capture lacks must raise")
    wall = c._request("GET", "/account/me")["account"]["walls"][0]["id"]
    post = c._request("POST", "/post", json_body={
        "content": "new post", "fypFlags": 0, "inReplyTo": None, "quotedPostId": None, "attachments": [],
        "scheduledFor": 0, "expiresAt": 0, "postReplyPermissionFlags": [], "pinned": 0,
        "wallIds": [wall], "pinWallIds": []})
    check(fake.posts == {post["id"]: post}, f"a created post must be held: {fake.posts}")
    c._request("POST", f"/post/{post['id']}/delete")
    check(fake.posts == {}, "a deleted post must be gone")
    check(_raises(lambda: c._request("POST", f"/post/{post['id']}/delete")),
          "a repeated delete is not captured and must raise")
    group = fake.groups[fake.messages[FAN_MESSAGE]["groupId"]]
    group["unreadCount"] = 1
    c._request("POST", "/message/ack", json_body={"messageIds": [FAN_MESSAGE], "type": 2})
    check(group["unreadCount"] == 0, "an ack of an inbound message must clear the thread's unread count")
    check(_raises(lambda: c._request("POST", "/message/ack", json_body={"messageIds": [NEW_FAN], "type": 2})),
          "an ack of an unknown message must raise")
    own = c.send_message(FAN, "mine")["id"]
    check(_raises(lambda: c._request("POST", "/message/ack", json_body={"messageIds": [own], "type": 2})),
          "an ack of an own message is not captured and must raise")

    check(_raises(lambda: c.like_message(FAN_MESSAGE)),
          "an unmodelled write must raise through the Shim, not be swallowed as a skip")
    check(_raises(c.payout_balances), "an unmodelled read must raise")
    check(_raises(lambda: c._request("DELETE", "/lists")), "an unmodelled method must raise")

    if fails:
        print("FAILED:")
        for f in fails:
            print("  -", f)
        return 1
    print(f"stateful fake: {len(ROUTES)} modelled requests, each cited; write, read back, repeat and undo hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
