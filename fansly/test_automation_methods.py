from __future__ import annotations

import sys

from fansly_client import FanslyAPIError, FanslySession
from fansly_shim import FanslyShimClient, FanslyUnsupported

US = "700237824869654528"
FAN = "900108301660352512"
WALL = "900264702215319552"
MSG = "900528581705445378"
POST = "900546198725955584"
LIST = "900537126601601024"
GROUP = "900604711209099999"
LATER = "900546198725955999"

# INVENTED: postTemplate's fields; the capture names only the key.
SCHEDULED = {"scheduledPosts": [
    {"postId": LATER, "accountId": US, "status": 1,
     "postTemplate": {"content": "later", "attachments": []}, "scheduledFor": 1788981187000},
    {"postId": POST, "accountId": US, "status": 1,
     "postTemplate": {"content": "soon", "attachments": []}, "scheduledFor": 1788894787000},
    {"postId": "900546198725955000", "accountId": US, "status": 3,
     "postTemplate": {"content": "cancelled"}, "scheduledFor": 1788894787000},
    {"accountId": US, "status": 1, "postTemplate": {}, "scheduledFor": 1788894787000},
], "aggregationData": {}}


def _client(*, fail: dict[str, str] | None = None,
            walls: list | None = None) -> tuple[FanslyShimClient, list]:
    c = FanslyShimClient(FanslySession({
        "accountId": US, "token": "t", "check_key": "k", "device_id": "d",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    }))
    calls: list[tuple[str, str, object, object]] = []
    fail = fail or {}

    def fake(method, path, *, params=None, json_body=None, **_kw):
        calls.append((method, path, json_body, params))
        if path in fail:
            raise FanslyAPIError(fail[path])
        if path == "/account/me":
            return {"account": {"id": US, "walls": walls if walls is not None
                                else [{"id": WALL, "mainWall": True}]}}
        if path == "/post":
            return {} if json_body.get("scheduledFor") else {"id": POST}
        if path == "/lists":
            return {"id": LIST, "type": 1, "label": json_body["label"]}
        if path == "/lists/commands":
            return json_body["listCommands"]
        if path == "/lists/account":
            return [{"id": LIST, "type": 1, "label": "vip"}]
        if path == "/post/scheduled":
            return SCHEDULED
        if path == "/group":
            return {"id": GROUP}
        if path == "/messaging/groups":
            return {"data": [], "aggregationData": {}}
        if path == "/message":
            return {"id": MSG, "groupId": json_body["groupId"],
                    "senderId": US, "content": json_body.get("content", ""),
                    "createdAt": 0, "attachments": []}
        return {"success": True}

    c._request = fake
    return c, calls


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    c, calls = _client()
    check(c.follow_user(FAN) == {"success": True}, "follow returns success")
    check(calls == [("POST", f"/account/{FAN}/followers", None, None)],
          f"follow must be POST /account/{{id}}/followers with no body: {calls}")
    c, calls = _client()
    c.unfollow_user(FAN)
    check(calls == [("POST", f"/account/{FAN}/followers/remove", None, None)],
          f"unfollow must be POST .../followers/remove with no body: {calls}")

    c, calls = _client(fail={f"/account/{FAN}/followers":
                             "HTTP 422 {'code': 5, 'details': 'you can not follow'}"})
    out = c.follow_user(FAN)
    check(out.get("success") is False and out.get("skipped"),
          f"a 422 follow must be a clean skip, got {out}")
    check(len(calls) == 1, "a 422 follow must never be retried")
    c, calls = _client(fail={f"/account/{FAN}/followers": "HTTP 500 boom"})
    try:
        c.follow_user(FAN)
        check(False, "a non-422 follow failure must raise")
    except FanslyAPIError:
        pass

    c, calls = _client()
    check(c.like_message(MSG, FAN) == {"success": True}, "like returns success")
    check(calls == [("POST", "/message/like",
                     {"messageId": MSG, "type": 1}, None)],
          f"like body must be {{messageId, type:1}} exactly: {calls}")
    check(isinstance(calls[0][2]["messageId"], str),
          "messageId must stay a string — Fansly ids exceed 2^53")
    c, calls = _client(fail={"/message/like": "HTTP 422 own message"})
    out = c.like_message(MSG)
    check(out.get("success") is False and out.get("skipped"),
          f"liking our own message must skip, not raise: {out}")

    c, calls = _client()
    check(c.unsend_message(MSG) == {"success": True}, "unsend returns success")
    check(calls == [("POST", "/message/delete", {"messageId": MSG}, None)],
          f"unsend must be ONE POST /message/delete {{messageId}}: {calls}")

    captured_post = {
        "content": "test", "fypFlags": 0, "inReplyTo": None,
        "quotedPostId": None, "attachments": [], "scheduledFor": 0,
        "expiresAt": 0, "postReplyPermissionFlags": [], "pinned": 0,
        "wallIds": [WALL], "pinWallIds": [],
    }
    c, calls = _client()
    out = c.create_post("test")
    posts = [b for m, p, b, _ in calls if p == "/post"]
    check(len(posts) == 1 and posts[0] == captured_post,
          f"create_post body drifted from the capture: {posts}")
    check(calls[0][1] == "/account/me",
          "the wall id must be read from the account, not baked in")
    check(out == {"success": True, "id": POST, "scheduled": False},
          f"create_post must surface the new post id as a string: {out}")
    c.create_post("again")
    check(sum(1 for _, p, _, _ in calls if p == "/account/me") == 1,
          "wall id must be cached across posts")

    c, calls = _client()
    out = c.create_post("later", scheduled_for=1788894787)
    body = next(b for _, p, b, _ in calls if p == "/post")
    check(body["scheduledFor"] == 1788894787000,
          f"scheduledFor must be converted to ms, got {body['scheduledFor']}")
    check(out == {"success": True, "id": None, "scheduled": True},
          f"a scheduled create has no id yet and must say so: {out}")

    c, calls = _client(walls=[])
    try:
        c.create_post("x")
        check(False, "create_post without a wall must raise")
    except FanslyAPIError:
        check(not [p for _, p, _, _ in calls if p == "/post"],
              "no wall means NO /post call")
    c, calls = _client()
    try:
        c.create_post("x", media_files=["1"])
        check(False, "create_post with media must raise (uncaptured)")
    except FanslyAPIError:
        check(not [p for _, p, _, _ in calls if p == "/post"],
              "refused media means NO /post call")

    c, calls = _client()
    c.delete_post(POST)
    check(calls == [("POST", f"/post/{POST}/delete", None, None)],
          f"delete_post must be POST /post/{{id}}/delete with no body: {calls}")
    c, calls = _client()
    c.cancel_scheduled(POST)
    check(calls == [("POST", f"/post/scheduled/{POST}/cancel", None, None)],
          f"cancel_scheduled must be POST /post/scheduled/{{id}}/cancel: {calls}")

    c, calls = _client()
    out = c.schedules(publish_date="2026-09-01", publish_date_end="2026-09-30", limit=20)
    check(calls == [("GET", "/post/scheduled", None, None)],
          f"schedules must be one GET /post/scheduled: {calls}")
    check(out == {"list": [
        {"id": POST, "type": "post", "publishDateTime": "2026-09-08T19:13:07+00:00",
         "entity": {"id": POST, "text": "soon"}},
        {"id": LATER, "type": "post", "publishDateTime": "2026-09-09T19:13:07+00:00",
         "entity": {"id": LATER, "text": "later"}},
    ], "hasMore": False}, f"schedules must be the live queue, ms read as ms, soonest first: {out}")
    c.cancel_scheduled(out["list"][0]["id"])
    check(calls[-1] == ("POST", f"/post/scheduled/{POST}/cancel", None, None),
          f"a queue item's id must cancel that post: {calls[-1]}")

    c, calls = _client()
    c.add_user_to_list(LIST, FAN)
    check(calls == [("POST", "/lists/commands", {"listCommands": [
        {"type": 1, "listItem": {"id": FAN, "listId": LIST}}]}, None)],
        f"list ADD must be type 1 with a singular listItem: {calls}")
    c, calls = _client()
    out = c.add_users_to_lists({int(LIST): [int(FAN), int(GROUP)]})
    check(calls == [("POST", "/lists/commands", {"listCommands": [
        {"type": 1, "listItem": {"id": FAN, "listId": LIST}},
        {"type": 1, "listItem": {"id": GROUP, "listId": LIST}}]}, None)],
        f"bulk list ADD must send one string-id listItem per fan: {calls}")
    check(out == {LIST: [FAN, GROUP]},
          f"bulk list ADD must return the echoed fan ids as strings: {out}")
    c, calls = _client()
    c.remove_user_from_list(LIST, FAN)
    check(calls == [("POST", "/lists/commands", {"listCommands": [
        {"type": 2, "listId": LIST, "itemIds": [FAN]}]}, None)],
        f"list REMOVE must be type 2 with a plural itemIds: {calls}")
    c, calls = _client()
    out = c.create_list("zz-capture-tmp")
    check(calls == [("POST", "/lists",
                     {"label": "zz-capture-tmp", "description": ""}, None)],
          f"create_list body must be {{label, description}}: {calls}")
    check(out == {"id": LIST, "name": "zz-capture-tmp"},
          f"create_list must return OF's {{id, name}}: {out}")
    c, calls = _client()
    out = c.get_lists()
    check(calls[0][:2] == ("GET", "/lists/account")
          and calls[0][3] == {"itemId": ""},
          f"get_lists must GET /lists/account?itemId=: {calls}")
    check(out == {"list": [{"id": LIST, "name": "vip"}], "hasMore": False},
          f"get_lists must return OF's list page: {out}")

    for name in ("pin_message", "unpin_message", "mark_chat_unread"):
        c, calls = _client()
        try:
            got = getattr(c, name)(MSG, FAN)
        except FanslyUnsupported:
            got = "raised"
        check(got == "raised", f"{name} must raise, not answer {got!r}")
        check(not calls, f"{name} must never touch the network: {calls}")
    expected = {
        "get_pinned_messages": [],
        "hide_vault_media": {"success": False},
        "vault_media_lookup_hash": None,
        "post_story_from_url": {"success": False},
        "delete_story": {"success": False},
    }
    for name, want in expected.items():
        c, calls = _client()
        got = getattr(c, name)(MSG, FAN, extra="ignored")
        check(got == want, f"{name} must return {want!r}, got {got!r}")
        check(not calls, f"{name} must never touch the network: {calls}")
        check(getattr(getattr(FanslyShimClient, name),
                      "platform_unsupported", None),
              f"{name} must carry the platform_unsupported marker")
    c, _ = _client()
    c.hide_vault_media(MSG)["success"] = "mutated"
    check(c.hide_vault_media(MSG) == {"success": False},
          "a no-op's return value must be fresh per call")

    c, calls = _client()
    c.send_message(FAN, "hey")
    paths = [(m, p) for m, p, _b, _q in calls]
    check(("POST", "/group") in paths,
          f"a stranger send must mint a group first: {paths}")
    grp = next(b for m, p, b, _q in calls if p == "/group")
    check([u["userId"] for u in grp["users"]] == [US, FAN] and grp["type"] == 1,
          f"POST /group must be a type-1 DM between us and the fan: {grp}")
    msg = next(b for m, p, b, _q in calls if p == "/message")
    check(msg["groupId"] == GROUP,
          f"the send must go to the MINTED group, not the fan id: {msg}")
    check(paths.index(("POST", "/group")) < paths.index(("POST", "/message")),
          "group creation must precede the send")
    calls.clear()
    c.send_message(FAN, "again")
    check(("POST", "/group") not in [(m, p) for m, p, _b, _q in calls],
          f"a known fan must not mint a second group: {calls}")

    c, calls = _client()
    c._known_group_ids.add(GROUP)
    c.send_message(GROUP, "hi")
    check([p for _m, p, _b, _q in calls] == ["/message"],
          f"a known group id must post directly: {calls}")

    if fails:
        print("FAILED:")
        for f in fails:
            print("  -", f)
        return 1
    print("all automation-method checks passed — bodies match the capture")
    return 0


if __name__ == "__main__":
    sys.exit(main())
