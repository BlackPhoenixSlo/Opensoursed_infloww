"""OF's chat list read state at its wire, for scenarios/2026-11-20-all-models-shared-inbox.py. Installs into
lib/of_wire.FakeOF through its generic hook, `extra_routes` (answered before the built-ins):

  GET    /api2/v2/chats                     `chats[uid]` as the built-in pages it, plus `filter=unread` honoured
                                            (only rows with unreadMessagesCount > 0 or hasUnread; any other filter:
                                            every row, the built-in's status quo) and OF's per-response cap
                                            (PAGE_CAP rows whatever `limit` asks: service/chats_page.py:109, so the
                                            relay's 25-row page costs 3 reads as on OF), `hasMore`, `nextOffset`
  POST   /api2/v2/chats/{fan}/mark-as-read  that row read (unread 0, hasUnread false); `{"success": true}`
  DELETE /api2/v2/chats/{fan}/mark-as-read  that row unread (1)
  POST   /api2/v2/chats/mark-as-read        every row read
  GET    /api2/v2/users/me                  `chatMessagesCount` = the unread chats over the Creator's WHOLE list (not
                                            page 0), through the built-in's `profiles[uid]` overlay; recounted under
                                            `fake.lock` on every change (seed, DM, send, mark)

Each mark (t, Creator, fan, via) lands in `Wire.reads` (`via`: "relay" for the wire routes above, "of_web" for
`mark_read_out_of_band`, a read made on OF's own site that no relay call carries). Rows are replaced, never
mutated, and every change is made under `fake.lock` (h._record takes it too: answered after it is released).
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

PAGE_CAP = 10          # OF's /chats rows per response (service/chats_page.py:109 "OF caps /chats at ~10 rows")
_MARK_ONE = re.compile(r"/api2/v2/chats/(\d+)/mark-as-read")


def unread(row: dict) -> bool:
    return bool(row.get("hasUnread")) or (row.get("unreadMessagesCount") or 0) > 0


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


class Wire:
    def __init__(self, fake) -> None:
        self.fake = fake
        self.reads: list[dict] = []      # every mark, arrival order: {t, account, fan, via, read}

    def install(self):
        self.fake.extra_routes.append(self.handle)
        return self

    # ── world ────────────────────────────────────────────────────────────────
    def seed_chats(self, aid: str, fans: list[dict], n_unread: int, *, base_id: int,
                   deep_unread: tuple[int, ...] = ()) -> list[dict]:
        """`fans` as OF's chat list, newest first (one a minute back from now); the first `n_unread` and the rows at
        `deep_unread` (indexes, e.g. below page 0's 25) are unread (1-3 messages, the Fan's last), the rest read with
        the Creator's reply last."""
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
        """A Fan's message `msg` (the frame's api2_chat_message) on OF's list: that chat first, one more unread
        (a Fan not in the list joins it). The caller injects the frame (actors/fan_dm.inject)."""
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
        """The Creator's own message `sent` (a `fake.sends` record) heads that chat, read."""
        last = {k: sent.get(k) for k in ("id", "text", "fromUser", "isFree", "price", "createdAt")}
        with self.fake.lock:
            rows = list(self.fake.chats.get(aid, ()))
            old = next((r for r in rows if r["withUser"]["id"] == fan_id), None)
            base = old or {"withUser": {"id": fan_id, "_view": "s"}, "isMutedNotifications": False}
            row = {**base, "unreadMessagesCount": 0, "hasUnread": False, "lastMessage": last}
            self.fake.chats[aid] = [row] + [r for r in rows if r is not old]
            self._recount(aid)

    def mark_read_out_of_band(self, aid: str, fan_id: int) -> bool:
        """The chat read on OF's own site: OF's list says read from now on; no relay call says so. True when the
        row was unread."""
        return self._mark(aid, fan_id, True, "of_web")

    def chat_messages_count(self, aid: str) -> int:
        """What OF's `/users/me` says now: the Creator's unread chats over its whole list."""
        with self.fake.lock:
            return int(self.fake.profiles.get(aid, {}).get("chatMessagesCount") or 0)

    def _recount(self, aid: str) -> None:
        """Under `fake.lock`: `/users/me` `chatMessagesCount` from the whole list (the overlay dict replaced)."""
        n = len(self._unread_rows(aid))
        self.fake.profiles[aid] = {**self.fake.profiles.get(aid, {}), "chatMessagesCount": n}

    def _unread_rows(self, aid: str) -> list[dict]:
        """Under `fake.lock`: the rows OF counts and lists under `filter=unread`."""
        return [r for r in self.fake.chats.get(aid, ()) if unread(r)]

    def _unread_list(self, aid: str) -> list[dict]:
        return self._unread_rows(aid)

    def row(self, aid: str, fan_id: int) -> dict | None:
        with self.fake.lock:
            return next((dict(r) for r in self.fake.chats.get(aid, ()) if r["withUser"]["id"] == fan_id), None)

    def _mark(self, aid: str, fan_id: int | None, read: bool, via: str) -> bool:
        changed = False
        with self.fake.lock:
            rows = list(self.fake.chats.get(aid, ()))
            for i, r in enumerate(rows):
                if fan_id is not None and r["withUser"]["id"] != fan_id:
                    continue
                changed = changed or unread(r) == read
                rows[i] = {**r, "unreadMessagesCount": 0 if read else max(1, r.get("unreadMessagesCount") or 0),
                           "hasUnread": not read}
            self.fake.chats[aid] = rows
            self._recount(aid)
            self.reads.append({"t": time.time(), "account": aid, "fan": fan_id, "via": via, "read": read})
        return changed

    # ── the wire ─────────────────────────────────────────────────────────────
    def handle(self, h, method, u, uid, route, raw) -> bool:
        if method == "GET" and u.path == "/api2/v2/chats":
            q = parse_qs(u.query)
            off, lim = int((q.get("offset") or ["0"])[0]), int((q.get("limit") or ["10"])[0])
            n = max(1, min(lim, PAGE_CAP))
            with self.fake.lock:
                rows = (self._unread_list(uid) if (q.get("filter") or [""])[0] == "unread"
                        else list(self.fake.chats.get(uid, ())))
            h._record(uid, route, 200, {"list": rows[off:off + n], "hasMore": off + n < len(rows),
                                        "nextOffset": off + n})
            return True
        m = _MARK_ONE.fullmatch(u.path)
        if m and method in ("POST", "DELETE"):
            self._mark(uid, int(m.group(1)), method == "POST", "relay")
            h._record(uid, route, 200, {"success": True})
            return True
        if method == "POST" and u.path == "/api2/v2/chats/mark-as-read":
            self._mark(uid, None, True, "relay")
            h._record(uid, route, 200, {"success": True})
            return True
        return False


def install(fake) -> Wire:
    return Wire(fake).install()
