from __future__ import annotations

import copy
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fansly_client import API_BASE, NGSW_PARAMS, FanslySession
from fansly_shim import FanslyShimClient

HERE = Path(__file__).resolve().parent
READS = HERE / "fixtures" / "reads.json"
WRITES = HERE / "fixtures" / "writes.json"

SEND = "RECIPES.md: ## `POST /api/v1/message` — send"
UNSEND = "RECIPES.md: ## `POST /api/v1/message/delete` — unsend a message"
READS_RUN = "RECIPES.md: ## Reads confirmed this run"
LISTS = "RECIPES.md: ## Lists (OF's `add_user_to_list` family)"
LISTS_1126 = "RECIPES.md: ### Lists (§6.1–6.3) — M"
FOLLOW = "RECIPES.md: ## Follow / unfollow"
BLOCK = "RECIPES.md: ### Block / mute (§6.4) — M"
SUBSCRIBERS = "RECIPES.md: ### A6/A7 — the first subscriber (gift-code trial, paid with a card on file)"
PRESENCE = "RECIPES.md: ## Presence — and why `statusId` is NOT the online flag"
POSTS = "RECIPES.md: ## Posts — create and delete"
ACK = "RECIPES.md: ## `POST /api/v1/message/ack` — mark messages read"
READS_FIXTURE = "fixtures/reads.json"
WRITES_FIXTURE = "fixtures/writes.json"

MINTED_ROW = "INVENTED: the listing row for a freshly minted thread; the capture has rows only for older threads"
SORT_IDS = "INVENTED: sortId values; the capture names only the key"
UNSENT_READ = "ASSUMPTION: an unsent message still reads back, with deletedAt set"
LAST_MOVES = "ASSUMPTION: a send moves its thread's lastMessageId to the new message"
BARE_SUBSCRIBERS = "ASSUMPTION: a GET /subscribers without limit/offset answers the captured envelope unpaged"
RENEWAL_OFF = ("INVENTED: renewal_off's autoRenew 0 and future endsAt; the capture has only autoRenew 1 "
               "and an endsAt already past")
ACK_ANSWER = "ASSUMPTION: the ack's `response` field; the recipe shows only the success flag"
REFUSED_REMOVE = ("INVENTED: a refused remove keeps the member and echoes the batch without its command; "
                  "no refused remove is captured")
IGNORED_ID = "ASSUMPTION: ignoredId is a digit string, as in every captured Fansly id body; the recipe names only keys"
EDIT_ECHO = "ASSUMPTION: /lists/edit answers the list in the POST /lists row shape; the recipe says only `the list`"
ME_WALLS = "INVENTED: the /account/me envelope and wall object; the capture names only the `walls` field and one wall id"
WALL = "900264702215319552"


class Unmodelled(AssertionError):
    pass


ID, TEXT, SECONDS = object(), object(), object()


def _expect(value: Any, template: Any, where: str) -> None:
    if template is ID:
        ok = isinstance(value, str) and value.isdigit()
    elif template is TEXT:
        ok = isinstance(value, str)
    elif template is SECONDS:
        ok = isinstance(value, float)
    elif isinstance(template, dict):
        if not isinstance(value, dict) or sorted(value) != sorted(template):
            raise Unmodelled(f"{where}: keys {sorted(value) if isinstance(value, dict) else value!r} "
                             f"!= captured {sorted(template)}")
        for key, sub in template.items():
            _expect(value[key], sub, f"{where}.{key}")
        return
    elif isinstance(template, list):
        if not isinstance(value, list) or len(value) != len(template):
            raise Unmodelled(f"{where}: {value!r} != captured {template!r}")
        for i, (v, t) in enumerate(zip(value, template)):
            _expect(v, t, f"{where}[{i}]")
        return
    else:
        ok = type(value) is type(template) and value == template
    if not ok:
        raise Unmodelled(f"{where}: {value!r} is not the captured value")


def _expect_params(params: dict, captured: dict, where: str) -> None:
    if set(params) != set(captured) or any(v is not TEXT and params[k] != v for k, v in captured.items()):
        raise Unmodelled(f"{where}: params {params!r} are not the captured {sorted(captured)}")


@dataclass(frozen=True)
class Route:
    method: str
    pattern: str
    sources: tuple[str, ...]
    handler: Callable[..., Any]


ROUTES: list[Route] = []


def _route(method: str, pattern: str, *sources: str):
    def register(fn):
        ROUTES.append(Route(method, pattern, sources, fn))
        return fn
    return register


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def json(self) -> Any:
        return self._payload


class StatefulFansly:
    def __init__(self) -> None:
        reads = json.loads(READS.read_text())["responses"]
        groups = reads["/api/v1/messaging/groups"]
        self.notifications = copy.deepcopy(reads["/api/v1/notifications"]["notifications"])
        self.account_id = self.notifications[0]["accountId"]
        self.accounts = {a["id"]: a for a in copy.deepcopy(groups["aggregationData"]["accounts"])}
        self.groups = {g["groupId"]: g for g in copy.deepcopy(groups["data"])}
        thread = reads["/api/v1/message"]
        self.messages = {m["id"]: m for m in copy.deepcopy(
            groups["aggregationData"]["messages"] + thread["messages"])}
        self.account_media = {m["id"]: m for m in copy.deepcopy(thread["accountMedia"])}
        self.subscribers = copy.deepcopy(reads["/api/v1/subscribers"])
        self.profiles = {a["id"]: a for a in copy.deepcopy(reads["/api/v1/account"])}
        self.lists: dict[str, dict] = {}
        self.members: dict[str, list[str]] = {}
        self.following: set[str] = set()
        self.blocked: set[str] = set()
        self.refused_removes: set[str] = set()
        self.posts: dict[str, dict] = {}
        self.calls: list[tuple[str, str, Any, dict]] = []
        self.unmodelled: list[str] = []
        self._next_id = 900_000_000_000_005_000

    def client(self) -> FanslyShimClient:
        headers = json.loads(WRITES.read_text())["headers"]
        c = FanslyShimClient(FanslySession({
            "token": "stateful-fake", "accountId": self.account_id,
            "id": headers["fansly-session-id"], "device_id": headers["fansly-client-id"],
            "device_id_ts": 9e12, "user_agent": headers["user-agent"],
        }))
        c.http = self
        return c

    def renewal_off(self, ends_at_ms: int) -> None:
        row = self.subscribers["subscriptions"][0]
        row["autoRenew"], row["endsAt"] = 0, ends_at_ms

    def mint(self) -> str:
        self._next_id += 1
        return str(self._next_id)

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        params = dict(params or {})
        path = url.removeprefix(API_BASE)
        query = {k: v for k, v in params.items() if k not in NGSW_PARAMS}
        self.calls.append((method, path, copy.deepcopy(json), query))
        try:
            return self._dispatch(method, url, path, params, query, json)
        except Unmodelled as e:
            self.unmodelled.append(str(e))
            raise

    def _dispatch(self, method, url, path, params, query, json):
        if path == url or any(params.get(k) != v for k, v in NGSW_PARAMS.items()):
            raise Unmodelled(f"{method} {url}: not an apiv3 call with ngsw-bypass")
        for route in ROUTES:
            match = re.fullmatch(route.pattern, path)
            if route.method == method and match:
                return _Response({"success": True,
                                  "response": route.handler(self, query, json, *match.groups())})
        raise Unmodelled(f"{method} {path}: no captured request")


@_route("GET", "/messaging/groups", READS_FIXTURE)
def _groups(fake: StatefulFansly, params: dict, body: Any) -> dict:
    _expect(body, None, "GET /messaging/groups body")
    _expect_params(params, {"sortOrder": "1", "flags": "0", "subscriptionTierId": "", "listIds": "",
                            "search": "", "limit": TEXT, "offset": TEXT}, "GET /messaging/groups")
    offset, limit = int(params["offset"]), int(params["limit"])
    rows = list(fake.groups.values())[offset:offset + limit]
    partners = {r["partnerAccountId"] for r in rows}
    last = {r["lastMessageId"] for r in rows}
    return {"data": copy.deepcopy(rows),
            "aggregationData": {"accounts": [a for i, a in fake.accounts.items() if i in partners],
                                "messages": copy.deepcopy([m for i, m in fake.messages.items() if i in last])}}


@_route("POST", "/group", WRITES_FIXTURE, MINTED_ROW)
def _create_group(fake: StatefulFansly, params: dict, body: Any) -> dict:
    _expect(body, {"users": [{"userId": fake.account_id, "permissionFlags": 0},
                             {"userId": ID, "permissionFlags": 0}],
                   "recipients": [], "lastMessage": None, "userSettings": None, "type": 1},
            "POST /group")
    fan = body["users"][1]["userId"]
    if any(g["partnerAccountId"] == fan for g in fake.groups.values()):
        raise Unmodelled(f"POST /group: a second DM group for {fan} is not captured")
    gid = fake.mint()
    fake.groups[gid] = {"groupId": gid, "partnerAccountId": fan, "partnerUsername": "",
                        "unreadCount": 0, "lastMessageId": None, "lastUnreadMessageId": None, "flags": 0}
    return {"id": gid, "type": 1, "users": [{"userId": fake.account_id, "permissionFlags": 65535},
                                            {"userId": fan, "permissionFlags": 65535}]}


@_route("POST", "/message", SEND, WRITES_FIXTURE, LAST_MOVES)
def _send(fake: StatefulFansly, params: dict, body: Any) -> dict:
    _expect(body, {"type": 1, "attachments": [], "likes": [], "content": TEXT, "groupId": ID,
                   "scheduledFor": 0, "inReplyTo": None, "createdAt": SECONDS}, "POST /message")
    group = fake.groups.get(body["groupId"])
    if group is None:
        raise Unmodelled(f"POST /message: group {body['groupId']} is not a known thread")
    mid = fake.mint()
    fake.messages[mid] = {"id": mid, "type": 1, "groupId": body["groupId"], "senderId": fake.account_id,
                          "content": body["content"], "attachments": [], "createdAt": int(body["createdAt"])}
    group["lastMessageId"] = mid
    return copy.deepcopy(fake.messages[mid])


@_route("GET", "/message", READS_FIXTURE, UNSENT_READ)
def _messages(fake: StatefulFansly, params: dict, body: Any) -> dict:
    _expect(body, None, "GET /message body")
    _expect_params(params, {"groupId": TEXT, "limit": TEXT}, "GET /message")
    if params["limit"] == "1":
        raise Unmodelled("GET /message: limit=1 was measured to answer an empty array")
    rows = [m for m in fake.messages.values() if m["groupId"] == params["groupId"]]
    rows.sort(key=lambda m: int(m["id"]), reverse=True)
    rows = rows[:int(params["limit"])]
    media = {a["contentId"] for m in rows for a in m["attachments"] if a["contentType"] == 1}
    return {"messages": copy.deepcopy(rows),
            "accountMedia": copy.deepcopy([a for i, a in fake.account_media.items() if i in media]),
            "accountMediaBundles": []}


@_route("POST", "/message/delete", UNSEND)
def _unsend(fake: StatefulFansly, params: dict, body: Any) -> dict:
    _expect(body, {"messageId": ID}, "POST /message/delete")
    msg = fake.messages.get(body["messageId"])
    if msg is None or msg["senderId"] != fake.account_id or msg.get("deletedAt"):
        raise Unmodelled(f"POST /message/delete: only an undeleted own message was captured: {msg}")
    msg["deletedAt"] = int(time.time())
    return copy.deepcopy(msg)


@_route("POST", "/message/ack", ACK, ACK_ANSWER)
def _ack(fake: StatefulFansly, params: dict, body: Any) -> bool:
    if not isinstance(body, dict) or not body.get("messageIds"):
        raise Unmodelled(f"POST /message/ack: {body!r} is not the captured shape")
    _expect(body, {"messageIds": [ID] * len(body["messageIds"]), "type": 2}, "POST /message/ack")
    msgs = [fake.messages.get(i) for i in body["messageIds"]]
    if not all(m and m["senderId"] != fake.account_id for m in msgs):
        raise Unmodelled(f"POST /message/ack: only known inbound message ids were captured: {body['messageIds']}")
    for m in msgs:
        group = fake.groups[m["groupId"]]
        group["unreadCount"], group["lastUnreadMessageId"] = 0, None
    return True


@_route("GET", "/notifications", READS_RUN, READS_FIXTURE)
def _notifications(fake: StatefulFansly, params: dict, body: Any) -> dict:
    _expect(body, None, "GET /notifications body")
    _expect_params(params, {"before": "0", "after": "0", "type": ""}, "GET /notifications")
    return {"notifications": copy.deepcopy(fake.notifications)}


@_route("POST", "/lists", LISTS)
def _create_list(fake: StatefulFansly, params: dict, body: Any) -> dict:
    _expect(body, {"label": TEXT, "description": TEXT}, "POST /lists")
    lid = fake.mint()
    fake.lists[lid] = {"accountId": fake.account_id, "type": 1, "label": body["label"], "id": lid}
    fake.members[lid] = []
    return copy.deepcopy(fake.lists[lid])


@_route("GET", "/lists/account", READS_RUN, LISTS)
def _lists(fake: StatefulFansly, params: dict, body: Any) -> list:
    _expect(body, None, "GET /lists/account body")
    _expect_params(params, {"itemId": ""}, "GET /lists/account")
    return copy.deepcopy(list(fake.lists.values()))


_ADD = {"type": 1, "listItem": {"id": ID, "listId": ID}}


@_route("POST", "/lists/commands", LISTS, WRITES_FIXTURE, REFUSED_REMOVE)
def _list_commands(fake: StatefulFansly, params: dict, body: Any) -> list:
    if not isinstance(body, dict) or list(body) != ["listCommands"] or not body["listCommands"]:
        raise Unmodelled(f"POST /lists/commands: {body!r} is not a captured command batch")
    cmds = body["listCommands"]
    kinds = {cmd.get("type") if isinstance(cmd, dict) else None for cmd in cmds}
    if kinds not in ({1}, {2}) or (kinds == {2} and len(cmds) != 1):
        raise Unmodelled(f"POST /lists/commands: only an all-add batch or one remove was captured: {cmds!r}")
    staged, echo = copy.deepcopy(fake.members), []
    for i, cmd in enumerate(cmds):
        if cmd["type"] == 1:
            _expect(cmd, _ADD, f"POST /lists/commands[{i}]")
            lid, uid = cmd["listItem"]["listId"], cmd["listItem"]["id"]
        else:
            _expect(cmd, {"type": 2, "listId": ID, "itemIds": [ID]}, f"POST /lists/commands[{i}]")
            lid, uid = cmd["listId"], cmd["itemIds"][0]
        if lid not in staged:
            raise Unmodelled(f"POST /lists/commands[{i}]: list {lid} does not exist")
        if (uid in staged[lid]) == (cmd["type"] == 1):
            raise Unmodelled(f"POST /lists/commands[{i}]: a repeat add or a non-member remove is not captured")
        if cmd["type"] == 1:
            staged[lid].append(uid)
        elif uid in fake.refused_removes:
            continue
        else:
            staged[lid].remove(uid)
        echo.append(cmd)
    fake.members = staged
    return copy.deepcopy(echo)


@_route("GET", "/lists/itemsnew", LISTS_1126, SORT_IDS)
def _list_items(fake: StatefulFansly, params: dict, body: Any) -> list:
    _expect(body, None, "GET /lists/itemsnew body")
    _expect_params(params, {"listId": TEXT, "limit": "50", "sortMode": "3"}, "GET /lists/itemsnew")
    lid = params["listId"]
    if lid not in fake.lists:
        raise Unmodelled(f"GET /lists/itemsnew: list {lid} does not exist")
    return [{"id": m, "sortId": str(i), "listId": lid, "type": 1, "metadata": ""}
            for i, m in enumerate(fake.members[lid])]


@_route("POST", "/lists/edit", LISTS_1126, EDIT_ECHO)
def _rename_list(fake: StatefulFansly, params: dict, body: Any) -> dict:
    _expect(body, {"id": ID, "accountId": ID, "pos": None, "type": 1, "label": TEXT}, "POST /lists/edit")
    if body["accountId"] != fake.account_id or body["id"] not in fake.lists:
        raise Unmodelled(f"POST /lists/edit: list {body['id']} of account {body['accountId']} does not exist")
    fake.lists[body["id"]]["label"] = body["label"]
    return copy.deepcopy(fake.lists[body["id"]])


@_route("POST", "/lists/remove", LISTS_1126)
def _delete_list(fake: StatefulFansly, params: dict, body: Any) -> None:
    _expect(body, {"listId": ID}, "POST /lists/remove")
    lid = body["listId"]
    if lid not in fake.lists:
        raise Unmodelled(f"POST /lists/remove: list {lid} does not exist")
    del fake.lists[lid], fake.members[lid]
    return None


@_route("POST", r"/account/(\d+)/followers", FOLLOW, WRITES_FIXTURE)
def _follow(fake: StatefulFansly, params: dict, body: Any, who: str) -> dict:
    _expect(body, None, f"POST /account/{who}/followers body")
    if who in fake.following:
        raise Unmodelled(f"POST /account/{who}/followers: a repeat follow is not captured")
    fake.following.add(who)
    return {"followerId": fake.account_id, "accountId": who, "id": fake.mint(),
            "accountSortOrder": 0, "followerSortOrder": 0}


@_route("POST", r"/account/(\d+)/followers/remove", FOLLOW, WRITES_FIXTURE)
def _unfollow(fake: StatefulFansly, params: dict, body: Any, who: str) -> dict:
    _expect(body, None, f"POST /account/{who}/followers/remove body")
    if who not in fake.following:
        raise Unmodelled(f"POST /account/{who}/followers/remove: unfollowing a non-follow is not captured")
    fake.following.discard(who)
    return {"followerId": fake.account_id, "accountId": who, "id": fake.mint(), "createdAt": int(time.time())}


@_route("GET", "/ignore", BLOCK)
def _ignoring(fake: StatefulFansly, params: dict, body: Any) -> dict:
    _expect(body, None, "GET /ignore body")
    _expect_params(params, {"noAggregation": "true"}, "GET /ignore")
    if fake.blocked:
        raise Unmodelled(f"GET /ignore: only the empty read is captured, not one holding {sorted(fake.blocked)}")
    return {"ignoring": [], "accounts": []}


@_route("POST", "/account/ignore", BLOCK, IGNORED_ID)
def _block(fake: StatefulFansly, params: dict, body: Any) -> dict:
    _expect(body, {"ignoredId": ID, "ignoreFlags": 2}, "POST /account/ignore")
    if body["ignoredId"] in fake.blocked:
        raise Unmodelled(f"POST /account/ignore: a repeat block of {body['ignoredId']} is not captured")
    fake.blocked.add(body["ignoredId"])
    return {"accountId": fake.account_id, **body}


@_route("GET", "/subscribers", SUBSCRIBERS, READS_FIXTURE, BARE_SUBSCRIBERS, RENEWAL_OFF)
def _subscribers(fake: StatefulFansly, params: dict, body: Any) -> dict:
    _expect(body, None, "GET /subscribers body")
    _expect_params(params, {}, "GET /subscribers")
    return copy.deepcopy(fake.subscribers)


@_route("GET", "/account", PRESENCE, READS_FIXTURE)
def _accounts(fake: StatefulFansly, params: dict, body: Any) -> list:
    _expect(body, None, "GET /account body")
    _expect_params(params, {"ids": TEXT}, "GET /account")
    ids = params["ids"].split(",")
    if not all(i in fake.profiles for i in ids):
        raise Unmodelled(f"GET /account: no captured account for {sorted(set(ids) - set(fake.profiles))}")
    return copy.deepcopy([fake.profiles[i] for i in ids])


@_route("GET", "/account/me", POSTS, SUBSCRIBERS, ME_WALLS)
def _me(fake: StatefulFansly, params: dict, body: Any) -> dict:
    _expect(body, None, "GET /account/me body")
    _expect_params(params, {}, "GET /account/me")
    return {"account": {"id": fake.account_id, "walls": [{"id": WALL}]}}


@_route("POST", "/post", POSTS)
def _create_post(fake: StatefulFansly, params: dict, body: Any) -> dict:
    _expect(body, {"content": TEXT, "fypFlags": 0, "inReplyTo": None, "quotedPostId": None, "attachments": [],
                   "scheduledFor": 0, "expiresAt": 0, "postReplyPermissionFlags": [], "pinned": 0,
                   "wallIds": [WALL], "pinWallIds": []}, "POST /post")
    pid = fake.mint()
    fake.posts[pid] = {"id": pid, "accountId": fake.account_id, "content": body["content"]}
    return copy.deepcopy(fake.posts[pid])


@_route("POST", r"/post/(\d+)/delete", POSTS)
def _delete_post(fake: StatefulFansly, params: dict, body: Any, pid: str) -> None:
    _expect(body, None, f"POST /post/{pid}/delete body")
    if fake.posts.pop(pid, None) is None:
        raise Unmodelled(f"POST /post/{pid}/delete: only a live own post was captured")
    return None
