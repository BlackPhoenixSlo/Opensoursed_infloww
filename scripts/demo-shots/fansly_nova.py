from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_FANSLY = str(Path(__file__).resolve().parents[2] / "fansly")
if _FANSLY not in sys.path:
    sys.path.append(_FANSLY)

from dataset import Dataset, asset  # noqa: E402
from fansly_client import FanslyAPIError, FanslySession  # noqa: E402
from fansly_shim import FanslyShimClient  # noqa: E402
from fixtures import Fixtures  # noqa: E402

ACCOUNT = "900539700124344320"
FAN = "900539700124344321"
GROUP = "900539700124344322"
FIRST_MESSAGE = 900539700124344400
FIRST_GRANT = 900539700124344500
FIRST_MEDIA = 900539700124344550
ALBUM = "900539700124344600"
NAME = "Nova Reyes"
THREAD = {"route": f"/messages-pro/{ACCOUNT}/{FAN}", "creator": NAME}
SESSION = {"token": "demo-shots-throwaway", "user_agent": "demo-shots", "device_id": "demo-shots",
           "accountId": ACCOUNT}

LINES = [
    (52, True, "hey Nova, just found your page", None),
    (47, False, "hi! welcome, so glad you're here", None),
    (31, True, "what's new this week?", None),
    (29, False, "a beach set, here's a little peek", 0),
    (12, True, "wow, love it", None),
    (4, False, "more coming tonight", None),
]
VAULT_FILES = ["media/media-05.jpg", "media/media-09.jpg", "media/media-17.jpg", "media/media-22.jpg"]


def add(d: Dataset) -> None:
    d.creators.append({
        "id": ACCOUNT, "name": NAME, "username": "novareyes", "nickname": NAME, "color": "#0ea5e9",
        "avatar": asset("avatars/partner-03.jpg"), "target_cents": 0, "sub_price_cents": 999, "fan_count": 1,
        "created_at": d.now - timedelta(days=90), "online": True, "posts": 12, "media": len(VAULT_FILES),
        "likes": 900, "platform": "fansly", "fansly_session": SESSION,
    })


def raw_payloads(now: datetime) -> dict[str, Any]:
    me = {"id": ACCOUNT, "username": "novareyes", "displayName": NAME, "avatar": asset("avatars/partner-03.jpg")}
    fan = {"id": FAN, "username": "milesb", "displayName": "Miles B.", "avatar": asset("avatars/fan-12.jpg")}
    media = [{"id": str(FIRST_MEDIA + k), "accountId": ACCOUNT, "type": 1, "width": 360, "height": 450,
              "locations": [{"location": asset(f)}]} for k, f in enumerate(VAULT_FILES)]
    grants = [{"id": str(FIRST_GRANT + k), "accountId": ACCOUNT, "mediaId": m["id"], "access": True, "media": m}
              for k, m in enumerate(media)]
    messages = [{"id": str(FIRST_MESSAGE + i), "groupId": GROUP, "senderId": FAN if from_fan else ACCOUNT,
                 "content": text, "createdAt": int((now - timedelta(minutes=minutes)).timestamp()),
                 "totalTipAmount": 0,
                 "attachments": [] if m is None else [{"contentType": 1, "contentId": grants[m]["id"]}]}
                for i, (minutes, from_fan, text, m) in enumerate(LINES)][::-1]
    return {
        "me": me, "accounts": [me, fan], "media": media,
        "groups": {"data": [{"groupId": GROUP, "partnerAccountId": FAN, "partnerUsername": fan["username"],
                             "unreadCount": 0, "lastMessageId": messages[0]["id"], "flags": 0}],
                   "aggregationData": {"accounts": [fan], "messages": [messages[0]]}},
        "messages": {"messages": messages, "accountMedia": grants},
        "group": {"users": [{"userId": ACCOUNT}, {"userId": FAN}], "lastMessage": messages[0], "groupFlags": 0},
        "albums": [{"id": ALBUM, "accountId": ACCOUNT, "public": False, "pos": 0, "title": "Beach", "type": 0}],
    }


class FixtureShim(FanslyShimClient):
    def __init__(self, raw: dict[str, Any], process: str):
        super().__init__(FanslySession(dict(SESSION)))
        self.raw, self.process = raw, process

    def _refuse(self, method: str, path: str) -> None:
        with open(Path(os.environ["DEMO_SHOTS_TMP"]) / "server-offhost.jsonl", "a") as f:
            f.write(json.dumps({"process": self.process, "via": "fansly_stub", "target": f"{method} {path}",
                                "refused": True}) + "\n")
        raise FanslyAPIError(f"demo-shots: Fansly stub refused {method} {path}")

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, **_: Any) -> Any:
        p, raw = params or {}, self.raw
        if method != "GET":
            return self._refuse(method, path)
        if path == "/account/me":
            return {"account": raw["me"]}
        if path == "/account":
            ids = set((p.get("ids") or "").split(","))
            return [a for a in raw["accounts"] if a["id"] in ids]
        if path == "/messaging/groups":
            first = p.get("offset", "0") == "0" and not p.get("search") and p.get("flags", "0") == "0"
            return raw["groups"] if first else {"data": [], "aggregationData": {}}
        if path == "/message":
            return raw["messages"] if p.get("groupId") == GROUP and "before" not in p else {"messages": []}
        if path == f"/group/{GROUP}/":
            return raw["group"]
        if path == "/notifications":
            return {"notifications": []}
        if path == "/subscribers":
            return {"stats": {"totalActive": 1, "totalExpired": 0, "total": 1}, "subscriptions": []}
        if path == "/vault/albums":
            return raw["albums"]
        if path == "/media/vault":
            return raw["media"] if p.get("albumId") in (None, ALBUM) else []
        return self._refuse(method, path)


class FanslyFixtures(Fixtures):
    def __init__(self, d: Dataset):
        super().__init__(d)
        self.shim = FixtureShim(raw_payloads(d.now), "fixtures")
        self._chats[ACCOUNT] = self.shim.list_chats(limit=60)["list"]
        self.me = self.shim.me()

    def creator_user(self, c: dict[str, Any]) -> dict[str, Any]:
        return self.me if c["id"] == ACCOUNT else super().creator_user(c)

    def answer(self, method: str, path: str, q: dict[str, list[str]], account: str | None) -> Any:
        try:
            body = self._nova(path, q) if account == ACCOUNT and method == "GET" else None
        except FanslyAPIError:
            body = None
        return super().answer(method, path, q, account) if body is None else body

    def _nova(self, path: str, q: dict[str, list[str]]) -> Any:
        one = lambda k: (q.get(k) or [None])[0]  # noqa: E731
        num = lambda k, default: int(one(k) or default)  # noqa: E731
        if path == "/api/of/v2/users/me":
            return self.me
        if path == f"/api/of/v2/chats/{FAN}/messages":
            return self.shim.get_messages(FAN, limit=num("limit", 25), before_id=one("before_id"))
        if path == f"/api/of/v2/chats/{FAN}":
            return self.shim.get_chat(FAN)
        if path == f"/api/of/v2/users/{FAN}":
            return self.shim.get_user(FAN)
        if path == "/api/of/v2/users/list":
            return self.shim.list_users(q.get("ids", []) + q.get("ids[]", []))
        if path == "/api/of/v2/vault/lists":
            return self.shim.vault_lists(limit=num("limit", 10), offset=num("offset", 0))
        if path == "/api/of/v2/vault/media":
            return self.shim.vault_media(limit=num("limit", 24), offset=num("offset", 0), type=one("type") or "all",
                                         list_id=one("list_id"))
        return None
