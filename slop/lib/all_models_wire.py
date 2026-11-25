from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

from slop.lib.of_wire import FakeOF, chat_mark_request, chat_page, unread, unread_rows

PAGE_CAP = 10  # OF caps /chats at ~10 rows per response  # OF caps /chats at ~10 rows per response


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


class Wire:
    def __init__(self, fake) -> None:
        self.fake = fake
        self.reads: list[dict] = []

    def install(self):
        self.fake.extra_routes.append(self.handle)
        return self

    def seed_chats(self, aid: str, fans: list[dict], n_unread: int, *, base_id: int,
                   deep_unread: tuple[int, ...] = ()) -> list[dict]:
        now = datetime.now(timezone.utc)
        rows = []
        for k, f in enumerate(fans):
            fan_last = k < n_unread or k in deep_unread
            n = 1 + k % 3 if fan_last else 0
            rows.append({
                "withUser": {"id": f["id"], "_view": "s", "username": f["username"], "name": f["name"]},
                "unreadMessagesCount": n, "hasUnread": n > 0, "isMutedNotifications": False,
                "lastMessage": {"id": base_id + k, "text": "hey there" if fan_last else "talk soon",
                                "fromUser": {"id": f["id"] if fan_last else int(aid)}, "isFree": True, "price": 0,
                                "createdAt": _iso(now - timedelta(minutes=k + 1))}})
        with self.fake.lock:
            self.fake.chats[aid] = rows
            self._recount(aid)
        return rows

    def push_dm(self, aid: str, fan: dict, msg: dict) -> None:
        last = {k: msg.get(k) for k in ("id", "text", "fromUser", "isFree", "price", "createdAt")}
        with self.fake.lock:
            rows = list(self.fake.chats.get(aid, ()))
            old = next((r for r in rows if r["withUser"]["id"] == fan["id"]), None)
            base = old or {"withUser": {"id": fan["id"], "_view": "s", "username": fan["username"],
                                        "name": fan["name"]}, "unreadMessagesCount": 0,
                           "isMutedNotifications": False}
            n = (base.get("unreadMessagesCount") or 0) + 1
            row = {**base, "unreadMessagesCount": n, "hasUnread": True, "lastMessage": last}
            self.fake.chats[aid] = [row] + [r for r in rows if r is not old]
            self._recount(aid)

    def head_from_send(self, aid: str, fan_id: int, sent: dict) -> None:
        last = {k: sent.get(k) for k in ("id", "text", "fromUser", "isFree", "price", "createdAt")}
        with self.fake.lock:
            rows = list(self.fake.chats.get(aid, ()))
            old = next((r for r in rows if r["withUser"]["id"] == fan_id), None)
            base = old or {"withUser": {"id": fan_id, "_view": "s"}, "isMutedNotifications": False}
            row = {**base, "unreadMessagesCount": 0, "hasUnread": False, "lastMessage": last}
            self.fake.chats[aid] = [row] + [r for r in rows if r is not old]
            self._recount(aid)

    def mark_read_out_of_band(self, aid: str, fan_id: int) -> bool:
        return self._mark(aid, fan_id, True, "of_web")

    def chat_messages_count(self, aid: str) -> int:
        with self.fake.lock:
            return int(self.fake.profiles.get(aid, {}).get("chatMessagesCount") or 0)

    def _recount(self, aid: str) -> None:
        n = len(self._unread_rows(aid))
        self.fake.profiles[aid] = {**self.fake.profiles.get(aid, {}), "chatMessagesCount": n}

    def _unread_rows(self, aid: str) -> list[dict]:
        return unread_rows(self.fake.chats.get(aid, []))

    def _unread_list(self, aid: str) -> list[dict]:
        return self._unread_rows(aid)

    def row(self, aid: str, fan_id: int) -> dict | None:
        with self.fake.lock:
            return next((dict(r) for r in self.fake.chats.get(aid, ()) if r["withUser"]["id"] == fan_id), None)

    def _mark(self, aid: str, fan_id: int | None, read: bool, via: str) -> bool:
        with self.fake.lock:
            changed = FakeOF.mark(self.fake, aid, fan_id, read)
            self._recount(aid)
            self.reads.append({"t": time.time(), "account": aid, "fan": fan_id, "via": via, "read": read})
        return changed

    def handle(self, h, method, u, uid, route, raw) -> bool:
        if method == "GET" and u.path == "/api2/v2/chats":
            q = parse_qs(u.query)
            with self.fake.lock:
                rows = (self._unread_list(uid) if q.get("filter", [""])[0] == "unread"
                        else list(self.fake.chats.get(uid, ())))
                page = chat_page(q, rows, cap=PAGE_CAP)
            h._record(uid, route, 200, page)
            return True
        if mark := chat_mark_request(method, u.path):
            self._mark(uid, *mark, "relay")
            h._record(uid, route, 200, {"success": True})
            return True
        return False


def install(fake) -> Wire:
    return Wire(fake).install()
