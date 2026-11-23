from __future__ import annotations

import heapq
import itertools
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs

from service.unread_total_decide import excluded_from_badges, of_counts
from slop.actors import fan_dm
from slop.lib.all_models_wire import Wire, unread

DELAYS = {"api_mark": 0.23, "first_page": 0.9, "click": 0.8, "dm_counter": 0.001, "echo": 0.7, "echo_counter": 0.85,
          "queue_finish": 1.0}
ECHO_ID_BASE = 9_700_000_000_000
_SEND = re.compile(r"/api2/v2/chats/(\d+)/messages")
_MUTE = re.compile(r"/api2/v2/chats/(\d+)/mute")
_RESTRICT = re.compile(r"/api2/v2/users/(\d+)/restrict")
RESTRICTED_REASON = "of_restricted"   # service/automations/_skiplist.py OF_RESTRICTED_REASON


# OF answers a Restricted chat with canSendMessage false, canNotSendReason "muted".
RESTRICTED_SEND_REASON = "muted"
_KIND_REASON = {"only_friends": "only_friends", "restricted": RESTRICTED_SEND_REASON}


def chat_plan(fans: list[dict], runs: list[tuple[str, int, bool]]) -> list[dict]:
    """A Creator's chat list for `BadgeWire.seed`: `runs` are `(kind, count, unread)` laid in order over `fans`; kind
    only_friends | restricted | muted, any other (plain, deep, ...) a plain chat; each row's kind in `kind`."""
    out, it = [], iter(fans)
    for kind, count, is_unread in runs:
        for f in itertools.islice(it, count):
            out.append({"id": f["id"], "unread": is_unread, "muted": kind == "muted",
                        "restricted": kind == "restricted", "awaiting": False,
                        "cannot_send": _KIND_REASON.get(kind), "kind": kind})
    return out


def restrict_in_relay(con, seeds: dict[str, list[dict]]) -> None:
    """The Relay's registry row (`skip_list`, RESTRICTED_REASON) for every `restricted` chat of `seeds`
    ({aid: chat_plan rows}), on an open world connection; the caller commits."""
    from slop.seed import ts
    now = ts(datetime.utcnow())
    con.executemany("INSERT OR REPLACE INTO skip_list (account_id, fan_id, reason, added_at) VALUES (?, ?, ?, ?)",
                    [(aid, f["id"], RESTRICTED_REASON, now) for aid, fans in seeds.items() for f in fans
                     if f.get("restricted")])


def _fan_last(row: dict) -> bool:
    return ((row.get("lastMessage") or {}).get("fromUser") or {}).get("id") == row["withUser"]["id"]


def _first_page(u) -> bool:
    q = parse_qs(u.query)
    return "id" not in q and "before_id" not in q and (q.get("offset") or ["0"])[0] == "0"


class _Sender:
    # FakeOF.push_ws blocks on the WS loop (run_coroutine_threadsafe(...).result), so frames go out from this
    # thread, never from a WS-loop callback, which would deadlock.
    def __init__(self, wire: "BadgeWire", aid: str) -> None:
        self.wire, self.aid = wire, aid
        self.q: list[tuple[float, int, str, int | None, dict | None]] = []
        self.cv = threading.Condition()
        self.stopped = False
        threading.Thread(target=self._run, name=f"badge-sender-{aid}", daemon=True).start()

    def put(self, due: float, seq: int, kind: str, fan: int | None, frame: dict | None = None) -> None:
        with self.cv:
            heapq.heappush(self.q, (due, seq, kind, fan, frame))
            self.cv.notify()

    def stop(self) -> None:
        with self.cv:
            self.stopped = True
            self.cv.notify()

    def _run(self) -> None:
        while True:
            with self.cv:
                while not self.stopped and (not self.q or self.q[0][0] > time.monotonic()):
                    self.cv.wait(None if not self.q else self.q[0][0] - time.monotonic())
                if self.stopped:
                    return
                _, _, kind, fan, frame = heapq.heappop(self.q)
            self.wire._send(self.aid, kind, fan, frame)


class BadgeWire(Wire):
    def __init__(self, fake, *, counter_frames: bool = True, delays: dict | None = None) -> None:
        super().__init__(fake)
        self.frames: list[dict] = []
        self.counter_frames = counter_frames
        self.delays = {**DELAYS, **(delays or {})}
        self._mark_delay = {"relay": self.delays["api_mark"], "of_web": self.delays["click"],
                            "relay_get": self.delays["first_page"], "relay_mute": self.delays["api_mark"],
                            "of_web_mute": self.delays["api_mark"]}
        self.registry: dict[str, set[int]] = {}
        self._uncounted: dict[str, set[int]] = {}
        self._held: dict[str, list[dict]] = {}
        self._senders: dict[str, _Sender] = {}
        self._closed = False
        self._seq = itertools.count()
        self._ids = itertools.count(ECHO_ID_BASE)
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            senders, self._senders = list(self._senders.values()), {}
        for s in senders:
            s.stop()

    # ── world ────────────────────────────────────────────────────────────────
    def seed(self, aid: str, fans: list[dict]) -> list[dict]:
        now = datetime.now(timezone.utc)
        rows = []
        for k, f in enumerate(fans):
            fan_last = bool(f.get("unread") or f.get("awaiting"))
            n = 1 if f.get("unread") else 0
            reason = f.get("cannot_send")
            rows.append({
                "withUser": {"id": f["id"], "_view": "s", "username": f"fan{f['id']}", "name": f"Fan {f['id']}",
                             "isRestricted": bool(f.get("restricted"))},
                "unreadMessagesCount": n, "hasUnread": n > 0, "isMutedNotifications": bool(f.get("muted")),
                "canSendMessage": reason is None, "canNotSendReason": reason,
                "lastMessage": {"id": 7_000_000 + k, "text": "hey there" if fan_last else "talk soon",
                                "fromUser": {"id": f["id"] if fan_last else int(aid)}, "isFree": True, "price": 0,
                                "createdAt": (now.replace(microsecond=0)).isoformat()}})
        with self.fake.lock:
            self.registry[aid] = {f["id"] for f in fans if f.get("restricted")}
            self._uncounted[aid] = set()
            self.fake.chats[aid] = rows
            self._recount(aid)
        return rows

    def push_dm(self, aid: str, fan: dict, msg: dict | None = None) -> dict:
        fan = {"username": f"fan{fan['id']}", "name": f"Fan {fan['id']}", **fan}
        frame = {"api2_chat_message": msg} if msg else fan_dm.frame(next(self._ids), fan, "slop dm")
        with self.fake.lock:
            self._uncounted.get(aid, set()).discard(fan["id"])
        super().push_dm(aid, fan, frame["api2_chat_message"])
        now = time.monotonic()
        self._enqueue(aid, 0.0, "dm", fan["id"], now, frame)
        self._enqueue(aid, self.delays["dm_counter"], "counter", fan["id"], now)
        return frame

    def relay_send_echo(self, aid: str, fan: int, sent: dict) -> None:
        self._creator_sent(aid, fan, sent, "relay_send", True)

    def reply_elsewhere(self, aid: str, fan: int, *, echo: bool = True) -> None:
        sent = {"id": next(self._ids), "text": "replied elsewhere", "fromUser": {"id": int(aid)}, "isFree": True,
                "price": 0, "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")}
        self._creator_sent(aid, fan, sent, "reply_elsewhere", echo)

    def queue_elsewhere(self, aid: str, fans: list[int]) -> int:
        """A mass message to read `fans` sent on OF's site or in Infloww: each chat headed by it and read, no per-Fan
        echo (OF pushes none for a mass), then OF's `chat_queue_finish` frame; its queue id."""
        qid = next(self._ids)
        at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        for fan in fans:
            self.head_from_send(aid, fan, {"id": next(self._ids), "text": "slop mass", "fromUser": {"id": int(aid)},
                                           "isFree": True, "price": 0, "createdAt": at})
        with self.fake.lock:
            self.reads += [{"t": time.time(), "account": aid, "fan": fan, "via": "queue", "read": True} for fan in fans]
        self._enqueue(aid, self.delays["queue_finish"], "queue", None, None, {"chat_queue_finish": {
            "id": qid, "date": at, "isReady": True, "isDone": True, "total": len(fans), "pending": 0,
            "canUnsend": True, "unsendSeconds": 1000000, "hasError": False, "isCanceled": False}})
        return qid

    read_elsewhere = Wire.mark_read_out_of_band

    def mark_unread_elsewhere(self, aid: str, fan: int) -> bool:
        return self._mark(aid, fan, False, "of_web")

    def mute_elsewhere(self, aid: str, fan: int, *, muted: bool = True) -> None:
        self._mute(aid, fan, muted, "of_web_mute")

    def restrict_elsewhere(self, aid: str, fan: int, *, restricted: bool = True) -> None:
        def flip(r: dict) -> dict:
            sendable = {"canSendMessage": False, "canNotSendReason": RESTRICTED_SEND_REASON} if restricted else (
                {"canSendMessage": True, "canNotSendReason": None}
                if r.get("canNotSendReason") == RESTRICTED_SEND_REASON else {})
            return {**r, **sendable, "withUser": {**r["withUser"], "isRestricted": restricted}}
        self._replace(aid, fan, flip)

    def hold_unread_snapshot(self, aid: str) -> None:
        with self.fake.lock:
            self._held[aid] = self._unread_rows(aid)

    def release(self, aid: str) -> None:
        with self.fake.lock:
            self._held.pop(aid, None)

    # ── truth ────────────────────────────────────────────────────────────────
    def raw_counter(self, aid: str) -> int:
        return self.chat_messages_count(aid)

    def truth_unread(self, aid: str) -> set[int]:
        with self.fake.lock:
            return {r["withUser"]["id"] for r in self._unread_rows(aid)}

    def truth_red(self, aid: str) -> int:
        with self.fake.lock:
            raw = int(self.fake.profiles.get(aid, {}).get("chatMessagesCount") or 0)
            reg = self.registry.get(aid, set())
            excluded = sum(1 for r in self._unread_rows(aid) if excluded_from_badges(r["withUser"]["id"], r, reg))
        return max(0, raw - excluded)

    def truth_amber(self, aid: str) -> int:
        return len(self.truth_amber_fans(aid))

    def truth_amber_fans(self, aid: str) -> set[int]:
        with self.fake.lock:
            reg = self.registry.get(aid, set())
            return {r["withUser"]["id"] for r in self.fake.chats.get(aid, ())
                    if not unread(r) and not r.get("isMutedNotifications") and _fan_last(r)
                    and not excluded_from_badges(r["withUser"]["id"], r, reg)}

    def fan_last(self, aid: str) -> set[int]:
        with self.fake.lock:
            return {r["withUser"]["id"] for r in self.fake.chats.get(aid, ()) if _fan_last(r)}

    # ── state ────────────────────────────────────────────────────────────────
    def _counts(self, aid: str, row: dict) -> bool:
        return of_counts(row) and row["withUser"]["id"] not in self._uncounted.get(aid, ())

    def _unread_rows(self, aid: str) -> list[dict]:
        return [r for r in self.fake.chats.get(aid, ()) if self._counts(aid, r)]

    def _unread_list(self, aid: str) -> list[dict]:
        return self._held[aid] if aid in self._held else self._unread_rows(aid)

    def _replace(self, aid: str, fan: int, fn) -> dict | None:
        with self.fake.lock:
            rows = list(self.fake.chats.get(aid, ()))
            for i, r in enumerate(rows):
                if r["withUser"]["id"] == fan:
                    rows[i] = fn(r)
                    self.fake.chats[aid] = rows
                    return r
        return None

    def _mute(self, aid: str, fan: int, muted: bool, via: str) -> None:
        def flip(r: dict) -> dict:
            if not muted and r.get("isMutedNotifications") and unread(r):
                # OF leaves an unread chat unmuted out of its counter (sandbox r1): it counts again on its next read
                # or DM. Added under the same lock as the flip, so no reader counts it in between.
                self._uncounted.setdefault(aid, set()).add(fan)
            return {**r, "isMutedNotifications": muted}
        if self._replace(aid, fan, flip) is not None and muted:
            self._mark(aid, fan, True, via)

    def _mark(self, aid: str, fan_id: int | None, read: bool, via: str) -> bool:
        if read:
            with self.fake.lock:
                if fan_id is None:
                    self._uncounted.get(aid, set()).clear()
                else:
                    self._uncounted.get(aid, set()).discard(fan_id)
        changed = super()._mark(aid, fan_id, read, via)
        if changed and via in self._mark_delay:
            self._enqueue(aid, self._mark_delay[via], "counter", fan_id)
        return changed

    def _creator_sent(self, aid: str, fan: int, sent: dict, via: str, echo: bool) -> None:
        self.head_from_send(aid, fan, sent)
        with self.fake.lock:
            self.reads.append({"t": time.time(), "account": aid, "fan": fan, "via": via, "read": True})
        now = time.monotonic()
        if echo:
            self._enqueue(aid, self.delays["echo"], "echo", fan, now, {"api2_chat_message": {
                "id": sent["id"], "text": sent.get("text") or "", "price": sent.get("price") or 0,
                "isFree": sent.get("isFree", True), "mediaCount": 0, "media": [], "createdAt": sent["createdAt"],
                "toUser": {"id": fan}, "chatUserId": fan, "queueId": sent["id"], "cancelSeconds": 86399,
                "isFromQueue": False, "isNew": True}})
        self._enqueue(aid, self.delays["echo_counter"], "counter", fan, now)

    # ── frames ───────────────────────────────────────────────────────────────
    def _enqueue(self, aid: str, delay: float, kind: str, fan: int | None, now: float | None = None,
                 frame: dict | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            s = self._senders.get(aid)
            if s is None:
                s = self._senders[aid] = _Sender(self, aid)
        s.put((time.monotonic() if now is None else now) + delay, next(self._seq), kind, fan, frame)

    def _send(self, aid: str, kind: str, fan: int | None, frame: dict | None) -> None:
        if kind == "counter":
            if not self.counter_frames:
                return
            value = self.raw_counter(aid)
            frame = {"chat_messages": value, "count_priority_chat": 0, "count_call_request_chat": 0,
                     "unread_tips": 0}
        else:
            value = fan
        self.fake.push_ws(aid, frame)
        with self._lock:
            self.frames.append({"t": time.time(), "account": aid, "kind": kind, "value": value})

    # ── the wire ─────────────────────────────────────────────────────────────
    def handle(self, h, method, u, uid, route, raw) -> bool:
        m = _SEND.fullmatch(u.path)
        if method == "POST" and m:
            fan = int(m.group(1))

            def sent(body) -> None:
                if isinstance(body, dict) and "id" in body:
                    self.relay_send_echo(uid, fan, body)
            _on_answer(h, sent)
            return False
        if method == "GET" and m:
            if _first_page(u):
                fan = int(m.group(1))
                _on_answer(h, lambda _body: self._mark(uid, fan, True, "relay_get"))
            return False
        mm, mr = _MUTE.fullmatch(u.path), _RESTRICT.fullmatch(u.path)
        if method in ("POST", "DELETE") and (mm or mr):
            if mm:
                self._mute(uid, int(mm.group(1)), method == "POST", "relay_mute")
            else:
                self.restrict_elsewhere(uid, int(mr.group(1)), restricted=method == "POST")
            h._record(uid, route, 200, {"success": True})
            return True
        return super().handle(h, method, u, uid, route, raw)


def _on_answer(h, fn) -> None:
    # FakeOF's built-in routes answer through h._record: wrapping it on this request's handler sees a 200 answer
    # before the response goes out, without re-implementing the route. One-shot: a keep-alive connection reuses
    # this handler for its next requests.
    record = h._record

    def answered(uid_, route_, status, body, *a, **kw):
        h._record = record
        if status == 200:
            fn(body)
        return record(uid_, route_, status, body, *a, **kw)
    h._record = answered
