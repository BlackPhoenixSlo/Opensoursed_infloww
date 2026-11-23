from __future__ import annotations

import contextlib
import http.client
import json
import threading
import time
import urllib.error
import urllib.request

from websockets.sync.client import connect

from slop.lib import badge_metrics, badge_wire, of_wire

AID = "500"
COUNTER_KEYS = {"chat_messages", "count_priority_chat", "count_call_request_chat", "unread_tips"}


def _fans(n: int, *, unread: int = 0, base: int = 1000) -> list[dict]:
    return [{"id": base + k, "unread": k < unread, "muted": False, "restricted": False, "awaiting": False}
            for k in range(n)]


@contextlib.contextmanager
def _world(**kw):
    with of_wire.FakeOF(latency_s=0.0) as fake:
        wire = badge_wire.BadgeWire(fake, **kw).install()
        try:
            yield fake, wire
        finally:
            wire.close()


def _http(fake, aid: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{fake.origin}{path}", data=data, method=method,
                                 headers={"User-ID": aid, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())


class _Client:
    def __init__(self, fake, aid: str):
        _, me = _http(fake, aid, "GET", "/api2/v2/users/me")
        self.ws = connect(me["wsUrl"])
        self.ws.send(json.dumps({"act": "connect", "token": me["wsAuthToken"]}))
        assert json.loads(self.ws.recv(10)) == {"connected": True, "v": "5.4.0"}
        self.frames: list[tuple[float, dict]] = []
        self._t = threading.Thread(target=self._read, daemon=True)
        self._t.start()

    def _read(self) -> None:
        with contextlib.suppress(Exception):
            for raw in self.ws:
                self.frames.append((time.monotonic(), json.loads(raw)))

    def wait(self, n: int, timeout: float = 5.0) -> list[tuple[float, dict]]:
        end = time.monotonic() + timeout
        while len(self.frames) < n and time.monotonic() < end:
            time.sleep(0.01)
        return list(self.frames)

    def close(self) -> None:
        self.ws.close()


def _kind(frame: dict) -> str:
    if "api2_chat_message" in frame:
        return "echo" if "fromUser" not in frame["api2_chat_message"] else "dm"
    return "counter" if set(frame) == COUNTER_KEYS else "other"


def test_case_counter_after_api_mark():
    with _world() as (fake, wire):
        fans = _fans(3, unread=3)
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        t0 = time.monotonic()
        assert _http(fake, AID, "POST", f"/api2/v2/chats/{fans[0]['id']}/mark-as-read")[0] == 200
        got = c.wait(1)
        assert len(got) == 1
        t, fr = got[0]
        assert fr == {"chat_messages": 2, "count_priority_chat": 0, "count_call_request_chat": 0, "unread_tips": 0}
        assert 0.23 <= t - t0 <= 1.25
        _http(fake, AID, "DELETE", f"/api2/v2/chats/{fans[0]['id']}/mark-as-read")
        assert c.wait(2)[1][1]["chat_messages"] == 3
        assert [(f["account"], f["kind"], f["value"]) for f in wire.frames] == [(AID, "counter", 2),
                                                                                (AID, "counter", 3)]
        assert [(r["fan"], r["via"], r["read"]) for r in wire.reads] == [(fans[0]["id"], "relay", True),
                                                                         (fans[0]["id"], "relay", False)]
        c.close()


def test_case_noop_mark_no_frame():
    with _world() as (fake, wire):
        fans = _fans(2, unread=1)
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        _http(fake, AID, "POST", f"/api2/v2/chats/{fans[1]['id']}/mark-as-read")     # already read
        _http(fake, AID, "DELETE", f"/api2/v2/chats/{fans[0]['id']}/mark-as-read")   # already unread
        wire.read_elsewhere(AID, fans[1]["id"])
        time.sleep(1.2)
        assert c.frames == [] and wire.frames == []
        assert len(wire.reads) == 3
        c.close()


def test_case_parallel_flips_same_value():
    # a 1 s mark delay keeps both flips inside one frame's window even when the loaded machine spaces the two calls
    with _world(delays={**badge_wire.DELAYS, "api_mark": 1.0}) as (fake, wire):
        fans = _fans(4, unread=4)
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        go = threading.Barrier(2)

        def flip(fan_id: int) -> None:
            go.wait()
            _http(fake, AID, "POST", f"/api2/v2/chats/{fan_id}/mark-as-read")
        ts = [threading.Thread(target=flip, args=(f["id"],)) for f in fans[:2]]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        c.wait(2)
        time.sleep(0.3)
        assert [fr["chat_messages"] for _, fr in c.frames] == [2, 2]
        assert [f["value"] for f in wire.frames] == [2, 2]
        c.close()


def test_case_dm_then_counter_1ms():
    with _world() as (fake, wire):
        fans = _fans(3, unread=1)
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        wire.push_dm(AID, fans[2])
        got = c.wait(2)
        assert [_kind(fr) for _, fr in got] == ["dm", "counter"]
        dm = got[0][1]["api2_chat_message"]
        assert dm["fromUser"]["id"] == fans[2]["id"]
        assert got[1][1]["chat_messages"] == 2
        assert got[1][0] - got[0][0] <= 0.25
        assert wire.row(AID, fans[2]["id"])["hasUnread"] is True
        assert [(f["kind"], f["value"]) for f in wire.frames] == [("dm", fans[2]["id"]), ("counter", 2)]
        c.close()


def test_case_echo_then_counter():
    with _world() as (fake, wire):
        fans = _fans(2, unread=2)
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        fan = fans[0]["id"]
        t0 = time.monotonic()
        status, sent = _http(fake, AID, "POST", f"/api2/v2/chats/{fan}/messages", {"text": "hi there"})
        assert status == 200
        row = wire.row(AID, fan)
        assert row["hasUnread"] is False
        assert (row["lastMessage"]["id"], row["lastMessage"]["fromUser"]) == (sent["id"], {"id": int(AID)})
        assert fake.chats[AID][0]["withUser"]["id"] == fan
        got = c.wait(2)
        assert [_kind(fr) for _, fr in got] == ["echo", "counter"]
        echo = got[0][1]["api2_chat_message"]
        assert set(echo) == {"id", "text", "price", "isFree", "mediaCount", "media", "createdAt", "toUser",
                             "chatUserId", "queueId", "cancelSeconds", "isFromQueue", "isNew"}
        assert "fromUser" not in echo
        assert echo["toUser"] == {"id": fan} and echo["chatUserId"] == fan
        assert echo["id"] == echo["queueId"] == sent["id"] and echo["text"] == "hi there"
        assert (echo["cancelSeconds"], echo["isFromQueue"], echo["isNew"]) == (86399, False, True)
        assert got[1][1]["chat_messages"] == 1
        assert 0.7 <= got[0][0] - t0 <= 1.7
        assert 0.85 <= got[1][0] - t0 <= 1.85
        assert [(f["kind"], f["value"]) for f in wire.frames] == [("echo", fan), ("counter", 1)]
        assert (wire.reads[-1]["fan"], wire.reads[-1]["via"], wire.reads[-1]["read"]) == (fan, "relay_send", True)

        conn = http.client.HTTPConnection(fake.origin.removeprefix("http://"), timeout=10)
        hdr = {"User-ID": AID, "Content-Type": "application/json"}
        conn.request("POST", f"/api2/v2/chats/{fans[1]['id']}/messages", json.dumps({"text": "again"}), hdr)
        r = conn.getresponse()
        assert r.status == 200 and json.loads(r.read())["text"] == "again"
        for _ in range(2):
            conn.request("GET", "/api2/v2/users/me", headers=hdr)
            r = conn.getresponse()
            assert r.status == 200 and json.loads(r.read())["id"] == int(AID)
        conn.close()
        c.wait(4)
        time.sleep(1.2)
        assert [_kind(fr) for _, fr in c.frames] == ["echo", "counter", "echo", "counter"]
        assert [r["via"] for r in wire.reads].count("relay_send") == 2
        c.close()


def test_case_reply_elsewhere_echo_off():
    with _world() as (fake, wire):
        fans = _fans(2, unread=2)
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        wire.reply_elsewhere(AID, fans[0]["id"], echo=False)
        c.wait(1)
        time.sleep(0.5)
        assert [(_kind(fr), fr.get("chat_messages")) for _, fr in c.frames] == [("counter", 1)]
        assert wire.row(AID, fans[0]["id"])["hasUnread"] is False
        wire.reply_elsewhere(AID, fans[1]["id"])
        got = c.wait(3)
        assert [_kind(fr) for _, fr in got] == ["counter", "echo", "counter"]
        assert got[1][1]["api2_chat_message"]["chatUserId"] == fans[1]["id"]
        assert got[2][1]["chat_messages"] == 0
        c.close()


def test_case_sender_not_on_ws_loop():
    aids = [str(600 + k) for k in range(5)]
    with _world() as (fake, wire):
        for k, aid in enumerate(aids):
            wire.seed(aid, _fans(5, base=2000 + 100 * k))
        clients = {aid: _Client(fake, aid) for aid in aids}
        queued = threading.Event()

        def from_the_ws_loop() -> None:
            for k, aid in enumerate(aids):
                for j in range(5):
                    wire.push_dm(aid, {"id": 2000 + 100 * k + j})
            queued.set()
        t0 = time.monotonic()
        fake._ws_loop.call_soon_threadsafe(from_the_ws_loop)
        assert queued.wait(2), "push_dm blocked the WS loop"
        for aid, c in clients.items():
            c.wait(10, timeout=2.0 - (time.monotonic() - t0))
        assert time.monotonic() - t0 <= 2.0
        for k, aid in enumerate(aids):
            got = clients[aid].frames
            assert len(got) == 10
            logged = [(f["kind"], f["value"]) for f in wire.frames if f["account"] == aid]
            seen = [("dm", fr["api2_chat_message"]["fromUser"]["id"]) if _kind(fr) == "dm"
                    else ("counter", fr["chat_messages"]) for _, fr in got]
            assert seen == logged
            assert [v for kind, v in seen if kind == "dm"] == [2000 + 100 * k + j for j in range(5)]
        for c in clients.values():
            c.close()


def test_case_counter_frames_off():
    with _world(counter_frames=False) as (fake, wire):
        fans = _fans(3, unread=1)
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        wire.push_dm(AID, fans[2])
        _http(fake, AID, "POST", f"/api2/v2/chats/{fans[1]['id']}/messages", {"text": "yo"})
        _http(fake, AID, "POST", f"/api2/v2/chats/{fans[0]['id']}/mark-as-read")
        c.wait(2)
        time.sleep(1.2)
        assert [_kind(fr) for _, fr in c.frames] == ["dm", "echo"]
        assert [f["kind"] for f in wire.frames] == ["dm", "echo"]
        wire.counter_frames = True
        _http(fake, AID, "DELETE", f"/api2/v2/chats/{fans[0]['id']}/mark-as-read")
        got = c.wait(3)
        assert _kind(got[-1][1]) == "counter" and got[-1][1]["chat_messages"] == 2
        c.close()


MSG_ROUTE = "GET /api2/v2/chats/{id}/messages"


def _status(fake, aid: str, method: str, path: str) -> int:
    try:
        return _http(fake, aid, method, path)[0]
    except urllib.error.HTTPError as e:
        return e.code


def _unread_list(fake, aid: str, **q) -> list[dict]:
    pages, off = [], 0
    while True:
        query = "&".join(f"{k}={v}" for k, v in {"filter": "unread", "offset": off, **q}.items())
        body = _http(fake, aid, "GET", f"/api2/v2/chats?{query}")[1]
        pages.append(body)
        if not body["hasMore"]:
            return pages
        off = body["nextOffset"]


def _ids(pages: list[dict]) -> set[int]:
    return {r["withUser"]["id"] for p in pages for r in p["list"]}


def test_case_first_page_marks_read():
    with _world() as (fake, wire):
        fans = _fans(3, unread=3)
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        t0 = time.monotonic()
        assert _status(fake, AID, "GET", f"/api2/v2/chats/{fans[0]['id']}/messages?limit=50&order=desc") == 200
        got = c.wait(1)
        assert got[0][1]["chat_messages"] == 2
        assert 0.9 <= got[0][0] - t0 <= 1.9
        assert _status(fake, AID, "GET", f"/api2/v2/chats/{fans[1]['id']}/messages?limit=10&order=asc&offset=0") == 200
        assert c.wait(2)[1][1]["chat_messages"] == 1
        assert _status(fake, AID, "GET", f"/api2/v2/chats/{fans[2]['id']}/messages?limit=10&filter=pinned") == 200
        assert c.wait(3)[2][1]["chat_messages"] == 0
        assert all(wire.row(AID, f["id"])["hasUnread"] is False for f in fans)
        assert [(r["fan"], r["via"], r["read"]) for r in wire.reads] == [(f["id"], "relay_get", True) for f in fans]
        c.close()


def test_case_peek_and_cursor_pages_never_mark():
    with _world() as (fake, wire):
        fans = _fans(2, unread=2)
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        fan = fans[0]["id"]
        for q in ("id=9223372036854775807&order=desc&limit=10", "id=8000123&limit=10", "before_id=8000123&limit=10",
                  "order=asc&offset=10&limit=10", "order=desc&offset=10&limit=10"):
            assert _status(fake, AID, "GET", f"/api2/v2/chats/{fan}/messages?{q}") == 200
        time.sleep(1.3)
        assert c.frames == [] and wire.frames == [] and wire.reads == []
        assert wire.row(AID, fan)["hasUnread"] is True and wire.raw_counter(AID) == 2
        c.close()


def test_case_unpeeked_first_page_is_flagged_by_the_sweep_checks():
    with _world() as (fake, wire):
        fans = _fans(3, unread=3)
        wire.seed(AID, fans)
        before = {AID: wire.raw_counter(AID)}
        peek = f"/api2/v2/chats/{fans[1]['id']}/messages?limit=50&id=9223372036854775807"
        assert _status(fake, AID, "GET", peek) == 200
        assert _status(fake, AID, "GET", f"/api2/v2/chats/{fans[2]['id']}/messages?limit=50&order=asc&offset=50") == 200
        time.sleep(1.3)
        assert badge_metrics.relay_marks(wire.reads) == [] and badge_metrics.counter_moves(wire.frames, before) == []
        assert _status(fake, AID, "GET", f"/api2/v2/chats/{fans[0]['id']}/messages?limit=50") == 200
        end = time.monotonic() + 3
        while not wire.frames and time.monotonic() < end:
            time.sleep(0.02)
        assert [(m["account"], m["fan"]) for m in badge_metrics.relay_marks(wire.reads)] == [(AID, fans[0]["id"])]
        assert [(f["account"], f["value"]) for f in badge_metrics.counter_moves(wire.frames, before)] == [(AID, 2)]


def test_case_failed_get_never_marks():
    with _world() as (fake, wire):
        fans = _fans(2, unread=2)
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        fan = fans[0]["id"]
        path = f"/api2/v2/chats/{fan}/messages?limit=10&order=desc"
        fake.throttle[(AID, MSG_ROUTE)] = 1
        assert _status(fake, AID, "GET", path) == 429
        fake.fail.add((AID, MSG_ROUTE))
        assert _status(fake, AID, "GET", path) == 500
        time.sleep(1.3)
        assert c.frames == [] and wire.reads == []
        assert wire.row(AID, fan)["hasUnread"] is True and wire.raw_counter(AID) == 2
        fake.fail.discard((AID, MSG_ROUTE))
        assert _status(fake, AID, "GET", path) == 200
        assert c.wait(1)[0][1]["chat_messages"] == 1
        c.close()


def test_case_filter_unread_excludes_muted_keeps_restricted_10_per_page():
    with _world() as (fake, wire):
        fans = _fans(20, unread=15)
        for f in fans[:2]:
            f["restricted"] = True
        for f in fans[12:15]:
            f["muted"] = True
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        wire.restrict_elsewhere(AID, fans[2]["id"])
        pages = _unread_list(fake, AID, limit=25)
        assert [len(p["list"]) for p in pages] == [10, 2]
        assert _ids(pages) == {f["id"] for f in fans[:12]} == wire.truth_unread(AID)
        assert len(_ids(pages)) == wire.raw_counter(AID) == 12
        time.sleep(1.0)
        assert c.frames == [] and wire.reads == []
        c.close()


def test_case_mute_marks_read_unmute_does_not_readd():
    with _world() as (fake, wire):
        fans = _fans(4, unread=4)
        fans[3]["muted"] = True
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        a, b, m = fans[0]["id"], fans[1]["id"], fans[3]["id"]
        t0 = time.monotonic()
        assert _status(fake, AID, "POST", f"/api2/v2/chats/{a}/mute") == 200
        got = c.wait(1)
        assert got[0][1]["chat_messages"] == 2 and 0.23 <= got[0][0] - t0 <= 1.25
        row = wire.row(AID, a)
        assert (row["isMutedNotifications"], row["hasUnread"]) == (True, False)
        assert _status(fake, AID, "DELETE", f"/api2/v2/chats/{a}/mute") == 200
        wire.mute_elsewhere(AID, b)
        assert c.wait(2)[1][1]["chat_messages"] == 1
        wire.mute_elsewhere(AID, b, muted=False)
        assert _status(fake, AID, "DELETE", f"/api2/v2/chats/{m}/mute") == 200
        time.sleep(1.2)
        assert len(c.frames) == 2
        assert wire.row(AID, a)["isMutedNotifications"] is False and wire.row(AID, a)["hasUnread"] is False
        row = wire.row(AID, m)
        assert (row["isMutedNotifications"], row["hasUnread"]) == (False, True)
        assert wire.raw_counter(AID) == 1 and _ids(_unread_list(fake, AID)) == {fans[2]["id"]}
        wire.mark_unread_elsewhere(AID, m)
        time.sleep(1.2)
        assert len(c.frames) == 2 and wire.raw_counter(AID) == 1
        wire.push_dm(AID, fans[3])
        assert c.wait(4)[3][1]["chat_messages"] == 2
        assert [(r["fan"], r["via"]) for r in wire.reads[:2]] == [(a, "relay_mute"), (b, "of_web_mute")]
        c.close()


def test_case_restrict_no_frame():
    with _world() as (fake, wire):
        fans = _fans(3, unread=3)
        fans[2]["cannot_send"] = "only_friends"
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        red = wire.truth_red(AID)
        assert red == 2
        a, b = fans[0]["id"], fans[1]["id"]
        assert _status(fake, AID, "POST", f"/api2/v2/users/{a}/restrict") == 200
        wire.restrict_elsewhere(AID, b)
        assert wire.row(AID, a)["withUser"]["isRestricted"] is True
        assert wire.row(AID, b)["withUser"]["isRestricted"] is True
        assert (wire.row(AID, a)["canSendMessage"], wire.row(AID, a)["canNotSendReason"]) == (False, "muted")
        assert wire.truth_red(AID) == red - 2 and wire.raw_counter(AID) == 3
        assert {a, b} <= _ids(_unread_list(fake, AID))
        assert _status(fake, AID, "DELETE", f"/api2/v2/users/{a}/restrict") == 200
        wire.restrict_elsewhere(AID, b, restricted=False)
        assert wire.row(AID, a)["withUser"]["isRestricted"] is False
        assert wire.row(AID, a)["hasUnread"] is True and wire.truth_red(AID) == red
        assert (wire.row(AID, a)["canSendMessage"], wire.row(AID, a)["canNotSendReason"]) == (True, None)
        time.sleep(1.2)
        assert c.frames == [] and wire.frames == [] and wire.reads == []
        assert wire.registry[AID] == set()
        c.close()


def test_case_hold_unread_snapshot():
    with _world() as (fake, wire):
        fans = _fans(4, unread=3)
        wire.seed(AID, fans)
        held = {f["id"] for f in fans[:3]}
        wire.hold_unread_snapshot(AID)
        wire.read_elsewhere(AID, fans[0]["id"])
        wire.push_dm(AID, fans[3])
        wire.mark_unread_elsewhere(AID, fans[0]["id"])
        wire.read_elsewhere(AID, fans[1]["id"])
        assert _ids(_unread_list(fake, AID)) == held
        assert wire.truth_unread(AID) == {fans[0]["id"], fans[2]["id"], fans[3]["id"]}
        wire.release(AID)
        assert _ids(_unread_list(fake, AID)) == wire.truth_unread(AID)
        assert [(r["fan"], r["via"], r["read"]) for r in wire.reads] == [
            (fans[0]["id"], "of_web", True), (fans[0]["id"], "of_web", False), (fans[1]["id"], "of_web", True)]


def _worked_example() -> list[dict]:
    fans = _fans(14, unread=14)
    for f in fans[7:11]:
        f["cannot_send"] = "only_friends"
    for f in fans[11:13]:
        f["cannot_send"] = "chat_unavailable"
    fans[13]["muted"] = True
    return fans


def test_case_only_friends_worked_example():
    with _world() as (fake, wire):
        fans = _worked_example()
        wire.seed(AID, fans)
        assert wire.raw_counter(AID) == 11
        assert _http(fake, AID, "GET", "/api2/v2/users/me")[1]["chatMessagesCount"] == 11
        pages = _unread_list(fake, AID, limit=10)
        assert [len(p["list"]) for p in pages] == [10, 1]
        rows = {r["withUser"]["id"]: r for p in pages for r in p["list"]}
        assert set(rows) == {f["id"] for f in fans[:11]}
        assert all((rows[f["id"]]["canSendMessage"], rows[f["id"]]["canNotSendReason"]) == (True, None)
                   for f in fans[:7])
        assert all((rows[f["id"]]["canSendMessage"], rows[f["id"]]["canNotSendReason"]) == (False, "only_friends")
                   for f in fans[7:11])
        assert (wire.row(AID, fans[11]["id"])["canSendMessage"],
                wire.row(AID, fans[11]["id"])["canNotSendReason"]) == (False, "chat_unavailable")
        assert wire.truth_red(AID) == 7


def test_case_truth_red_is_counter_minus_restricted():
    with _world() as (fake, wire):
        fans = _worked_example()
        wire.seed(AID, fans)
        extra = {"id": 1999}
        wire.registry[AID].add(extra["id"])
        wire.push_dm(AID, extra)
        assert (wire.raw_counter(AID), wire.truth_red(AID)) == (12, 7)
        wire.read_elsewhere(AID, extra["id"])
        assert (wire.raw_counter(AID), wire.truth_red(AID)) == (11, 7)
        wire.read_elsewhere(AID, fans[7]["id"])
        assert (wire.raw_counter(AID), wire.truth_red(AID)) == (10, 7)
        wire.read_elsewhere(AID, fans[0]["id"])
        assert (wire.raw_counter(AID), wire.truth_red(AID)) == (9, 6)
        for f in fans[1:7]:
            wire.read_elsewhere(AID, f["id"])
        assert (wire.raw_counter(AID), wire.truth_red(AID)) == (3, 0)
        for f in fans[8:11]:
            wire.read_elsewhere(AID, f["id"])
        assert (wire.raw_counter(AID), wire.truth_red(AID)) == (0, 0)



def test_case_truth_amber_read_fan_last_not_muted_not_excluded():
    with _world() as (fake, wire):
        fans = _fans(7)
        for f in fans[:5]:
            f["awaiting"] = True
        fans[1]["muted"] = True
        fans[2]["restricted"] = True
        fans[3]["cannot_send"] = "only_friends"
        fans[5]["unread"] = True
        wire.seed(AID, fans)
        assert wire.truth_amber(AID) == 2
        wire.reply_elsewhere(AID, fans[4]["id"], echo=False)
        assert wire.truth_amber(AID) == 1
        wire.read_elsewhere(AID, fans[5]["id"])
        assert wire.truth_amber(AID) == 2
        wire.mark_unread_elsewhere(AID, fans[0]["id"])
        assert wire.truth_amber(AID) == 1


def test_case_queue_elsewhere_heads_chats_without_echo_then_finish_frame():
    with _world() as (fake, wire):
        fans = _fans(7, unread=1)
        for f in fans[1:]:
            f["awaiting"] = True
        wire.seed(AID, fans)
        c = _Client(fake, AID)
        assert wire.truth_amber_fans(AID) == {f["id"] for f in fans[1:]}
        assert wire.fan_last(AID) == {f["id"] for f in fans}
        t0 = time.monotonic()
        qid = wire.queue_elsewhere(AID, [f["id"] for f in fans[1:6]])
        assert wire.truth_amber_fans(AID) == {fans[6]["id"]} and wire.raw_counter(AID) == 1
        assert wire.fan_last(AID) == {fans[0]["id"], fans[6]["id"]}
        got = c.wait(1)
        time.sleep(0.3)
        assert len(c.frames) == 1 and 1.0 <= got[0][0] - t0 <= 2.0
        fin = got[0][1]["chat_queue_finish"]
        assert (fin["id"], fin["total"], fin["isDone"], fin["isCanceled"]) == (qid, 5, True, False)
        assert [(f["kind"], f["value"]) for f in wire.frames] == [("queue", None)]
        assert [r["via"] for r in wire.reads] == ["queue"] * 5
        c.close()
