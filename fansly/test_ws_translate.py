from __future__ import annotations

import asyncio
import json
import sys
import threading

import fansly_shim as shim
from fansly_ws import FanslyWebSocket

ACCOUNT_ID = "700237824869654528"   # us, in the capture
FAN_ID = "500251712226222080"       # the fan, in the run-20260901-2049 capture


class _FakeSession:
    token = "SECRET-TOKEN"
    user_agent = "Mozilla/5.0 (captured)"
    account_id = ACCOUNT_ID


class _FakeClient:
    session = _FakeSession()
    account_id = ACCOUNT_ID
    user_agent = _FakeSession.user_agent
    proxy_url = None

    def __init__(self):
        self._group_to_fan = {"700241627807342593": "500365665494917120"}


def _frame(service_id: int, event: dict) -> dict:
    return {"t": 10000,
            "d": json.dumps({"serviceId": service_id,
                             "event": json.dumps(event)})}


def check(cond, label, fails):
    if not cond:
        fails.append(label)



INBOUND = {"type": 1, "message": {
    "type": 1, "senderId": FAN_ID,
    "groupId": "900544249083420672", "id": "900544249226047488",
    "correlationId": "900544249037303808",
    "attachments": [{"contentType": 1, "contentId": "700306063047811072",
                     "messageId": "900544249226047488", "pos": 0}],
    "interactions": [{"groupId": "900544249083420672", "userId": ACCOUNT_ID,
                      "readAt": 0, "deliveredAt": 0,
                      "messageId": "900544249226047488"}],
    "createdAt": 1788288661.818, "embeds": [], "content": "hey there"}}

OUTBOUND_ECHO = {"type": 1, "message": {
    "type": 1, "attachments": [], "content": "hey",
    "groupId": "700241627807342593", "senderId": ACCOUNT_ID, "inReplyTo": "",
    "interactions": [{"groupId": "700241627807342593",
                      "userId": "500365665494917120", "readAt": 0,
                      "deliveredAt": 0, "messageId": "900528581705445378"}],
    "id": "900528581705445378", "createdAt": 1788284926.39, "embeds": []}}

TYPING = {"type": 22, "typingAnnounceEvent": {
    "accountId": ACCOUNT_ID, "groupId": "700241627807342593",
    "lastAnnounce": 1788284544531}}

READ_RECEIPT = {"type": 2, "ackCommand": {
    "groupId": "700241627807342593", "messageIds": ["900522640977133571"],
    "userId": ACCOUNT_ID, "userReadReceiptsEnabled": True, "type": 2}}

FAN_UNSEND = {"type": 10, "message": {
    "type": 1, "senderId": FAN_ID,
    "groupId": "900544249083420672", "id": "900544249226047511",
    "attachments": [], "inReplyTo": "",
    "interactions": [{"groupId": "900544249083420672", "userId": ACCOUNT_ID,
                      "readAt": 0, "deliveredAt": 1788288662001,
                      "messageId": "900544249226047511"}],
    "createdAt": 1788288661, "deletedAt": 1788288700, "embeds": [],
    "content": "take it back"}}

CREATOR_UNSEND = {"type": 10, "message": {
    "type": 1, "attachments": [], "content": "hey",
    "groupId": "700241627807342593", "senderId": ACCOUNT_ID, "inReplyTo": "",
    "interactions": [{"groupId": "700241627807342593",
                      "userId": "500365665494917120", "readAt": 0,
                      "deliveredAt": 1788284931529, "messageId": "900528581705445378"}],
    "id": "900528581705445378", "createdAt": 1788284926,
    "deletedAt": 1788285922, "embeds": []}}

PRESENCE = {"type": 1, "status": {
    "accountId": ACCOUNT_ID, "statusId": 1,
    "lastSeenAt": 1788284489386, "updatedAt": 1788284489386}}


class _TypingShim(shim.FanslyShimClient):
    def __init__(self, threads=None):
        self.threads = dict(threads or {})
        self.scans = 0
        self.created = []
        self.posts = []
        self.fail = False
        self.in_post = threading.Event()
        self.release: threading.Event | None = None

    def find_group_with(self, account_id, scan_limit=100):
        self.scans += 1
        return self.threads.get(str(account_id))

    def create_group(self, account_id):
        gid = f"g-{account_id}"
        self.created.append(account_id)
        self.threads[str(account_id)] = gid
        return gid

    def typing(self, group_id):
        self.posts.append(group_id)
        if self.release is not None:
            self.in_post.set()
            self.release.wait(timeout=5)
        if self.fail:
            raise RuntimeError("POST /message/typing 500")


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def typing_checks(fails: list[str]) -> None:
    group = "900544249083420672"

    def socket(threads=None):
        client = _TypingShim(threads)
        clock = _Clock()
        return client, clock, FanslyWebSocket(client, clock=clock)

    def typed(ws, fan=FAN_ID):
        return asyncio.run(ws.send_typing(fan))

    client, clock, ws = socket({FAN_ID: group})
    results = []
    for t in (0.0, 2.5, 4.9, 5.0, 7.5, 10.0):
        clock.now = 1000.0 + t
        results.append(typed(ws))
    check(results == [True] * 6, f"throttled calls still report True (got {results})", fails)
    check(client.posts == [group] * 3,
          f"one POST per group per 5 s: t=0, 5, 10 (got {len(client.posts)})", fails)

    client, clock, ws = socket({FAN_ID: group})
    client.release = threading.Event()

    async def overlap():
        first = asyncio.create_task(ws.send_typing(FAN_ID))
        await asyncio.to_thread(client.in_post.wait, 5)
        second = await ws.send_typing(FAN_ID)
        client.release.set()
        return [await first, second]
    both = asyncio.run(overlap())
    check(both == [True, True] and len(client.posts) == 1,
          f"two overlapping calls give one POST (got {both}, {len(client.posts)} POSTs)", fails)

    client, clock, ws = socket({FAN_ID: group})
    client.fail = True
    check(typed(ws) is False, "a failed POST reports False", fails)
    client.fail = False
    clock.now += 0.1
    check(typed(ws) is True and len(client.posts) == 2,
          f"a failed POST frees the slot: the next call POSTs (got {len(client.posts)} POSTs)", fails)

    client, clock, ws = socket()
    check(typed(ws) is False, "fan with no Thread: typing reports False", fails)
    check(client.posts == [], f"fan with no Thread: zero POSTs (got {client.posts})", fails)
    check(client.created == [], f"fan with no Thread: typing creates no group (got {client.created})", fails)

    client, clock, ws = socket({FAN_ID: group})
    for t in (0.0, 1.0, 6.0, 12.0):
        clock.now = 1000.0 + t
        typed(ws)
    check(client.scans == 1, f"hit then repeat: one scan total (got {client.scans})", fails)

    client, clock, ws = socket()
    for t in (0.0, 2.5, 5.0, 7.5):
        clock.now = 1000.0 + t
        typed(ws)
    check(client.scans == 1, f"miss: one scan per hold of 2.5 s re-emits (got {client.scans})", fails)
    sent_to = client._group_for_send(FAN_ID)
    scans = client.scans
    clock.now = 1008.0
    check(typed(ws) is True and client.posts == [sent_to],
          f"miss, then the send path creates the Thread: typing POSTs to it (got {client.posts})", fails)
    check(client.scans == scans, f"...with no scan (got {client.scans - scans})", fails)

    client, clock, ws = socket()
    for t in (0.0, 2.5, 7.5, 9.0):
        clock.now = 1000.0 + t
        typed(ws)
    check(client.scans == 2, f"a 5 s gap lapses the miss and a new hold re-scans once (got {client.scans})", fails)

    print("typing: one POST per group per 5 s, never without a group, lookups cached")


def main(argv) -> int:
    fails: list[str] = []
    typing_checks(fails)
    ws = FanslyWebSocket(_FakeClient())

    ev = ws._translate(_frame(5, INBOUND))
    check(ev is not None, "inbound message translates at all", fails)
    if ev:
        check(list(ev) == ["api2_chat_message"],
              "yields exactly the `api2_chat_message` key transcode routes on", fails)
        m = ev["api2_chat_message"]
        check(m["id"] == "900544249226047488", "message id preserved", fails)
        check(m["fromUser"]["id"] == FAN_ID,
              "fromUser.id is the FAN — this is what makes direction 'in'", fails)
        check(m["text"] == "hey there", "text carried", fails)
        check(isinstance(m["id"], str) and isinstance(m["fromUser"]["id"], str),
              "ids are STRINGS (snowflakes exceed 2^53)", fails)
        check(m["mediaCount"] == 1,
              "attachment counted even though the frame carries no accountMedia[]", fails)
        check(m["createdAt"].startswith("2026-"),
              f"createdAt parsed as epoch seconds (got {m['createdAt']})", fails)
    print("inbound: triple-decoded and reshaped into api2_chat_message")

    ev = ws._translate(_frame(5, OUTBOUND_ECHO))
    check(ev is not None, "outbound echo is NOT dropped by the pump", fails)
    if ev:
        check(ev["api2_chat_message"]["fromUser"]["id"] == ACCOUNT_ID,
              "echo's fromUser.id == us, so transcode marks it 'out'", fails)
    print("outbound echo: passed through — direction is the transcoder's call")

    dup = ws._translate(_frame(5, INBOUND))
    check(dup is None, "a repeated frame is deduped on (serviceId, type, id)", fails)
    for i in range(700):
        ws._translate(_frame(5, {"type": 1, "message": {
            "id": f"9512285817054{i:05d}", "senderId": FAN_ID,
            "content": "x", "createdAt": 1788284926.39, "attachments": []}}))
    check(len(ws._seen) <= 512 and len(ws._seen_order) <= 512,
          f"dedupe ring stays bounded (got {len(ws._seen)})", fails)
    print(f"dedupe: duplicates dropped, ring bounded at {len(ws._seen)}")

    for label, sid, frame in (("typing announce", 5, TYPING),
                              ("read receipt", 4, READ_RECEIPT),
                              ("presence", 8, PRESENCE)):
        check(ws._translate(_frame(sid, frame)) is None,
              f"{label} yields nothing (a raw envelope would log as unknown forever)",
              fails)
    check(ws._translate({"t": 1, "d": '{"session":{}}'}) is None,
          "the auth reply is not an event", fails)
    check(ws._translate({"t": 2, "d": '{"lastPing":1}'}) is None,
          "the pong is not an event", fails)
    check(ws._translate({"t": 10000, "d": "not json"}) is None,
          "a malformed envelope is dropped, not raised", fails)
    print("untranslated frames: dropped silently, no raw envelopes escape")

    ws = FanslyWebSocket(_FakeClient())
    ev = ws._translate(_frame(5, FAN_UNSEND))
    check(ev == {"chat_message_deleted": {"id": "900544249226047511", "fan_id": FAN_ID}},
          f"fan unsend: one chat_message_deleted, fan from senderId (got {ev})", fails)
    check(ws._translate(_frame(5, OUTBOUND_ECHO)) is not None, "echo of the later-unsent send", fails)
    ev = ws._translate(_frame(5, CREATOR_UNSEND))
    check(ev == {"chat_message_deleted": {"id": "900528581705445378",
                                          "fan_id": "500365665494917120"}},
          f"Creator unsend: fan from the group map, not dedupe-blocked by its type-1 echo (got {ev})",
          fails)
    check(ws._translate(_frame(5, FAN_UNSEND)) is None, "a replayed unsend emits once", fails)
    check(ws._translate(_frame(5, CREATOR_UNSEND)) is None, "a replayed Creator unsend emits once", fails)
    no_id = {"type": 10, "message": {**FAN_UNSEND["message"], "id": ""}}
    check(ws._translate(_frame(5, no_id)) is None, "an unsend without a message id is dropped", fails)
    unknown_group = {"type": 10, "message": {**CREATOR_UNSEND["message"],
                                             "id": "900528581705445999", "groupId": "1"}}
    check(ws._translate(_frame(5, unknown_group)) is None,
          "a Creator unsend in an unmapped group is dropped", fails)
    check(ws._translate(_frame(5, {"type": 10})) is None, "an unsend with no message is dropped", fails)

    print("unsend: type 10 becomes chat_message_deleted, deduped, unresolvable dropped")

    check(ws._read_token() == "SECRET-TOKEN", "token read from the session", fails)

    class _NoToken:
        class session:
            token = ""
        account_id = ACCOUNT_ID
    try:
        FanslyWebSocket(_NoToken())._read_token()
        check(False, "a tokenless session raises rather than auth-looping", fails)
    except RuntimeError:
        pass
    print("auth: token read off the session object per connect")

    for f in fails:
        print(f"  FAIL {f}", file=sys.stderr)
    if fails:
        print(f"{len(fails)} check(s) failed", file=sys.stderr)
        return 1
    print("all WS translation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
