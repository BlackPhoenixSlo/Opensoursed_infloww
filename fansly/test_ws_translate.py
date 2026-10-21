"""
Prove the Fansly WS pump translates wsv3 frames into the event the relay's
transcoder already routes on — offline, against the frames captured in
capture/RECIPES.md. No network, no socket.

The pump's whole value is that `event_transcoder.transcode` needs no edit, and
that rests on two things this file pins: the triple-decode is done right, and
the yielded key is exactly `api2_chat_message`.

    ../venv/bin/python test_ws_translate.py
"""
from __future__ import annotations

import json
import sys

from fansly_ws import FanslyWebSocket

ACCOUNT_ID = "700237824869654528"   # us, in the capture
FAN_ID = "500251712226222080"       # the fan, in the run-20260901-2049 capture


class _FakeSession:
    token = "SECRET-TOKEN"
    user_agent = "Mozilla/5.0 (captured)"
    account_id = ACCOUNT_ID


class _FakeClient:
    """Just the surface FanslyWebSocket reads off a client."""
    session = _FakeSession()
    account_id = ACCOUNT_ID
    user_agent = _FakeSession.user_agent
    proxy_url = None

    def __init__(self):
        self.typed = []

    def typing(self, group_id):
        self.typed.append(group_id)

    def _as_group_id(self, fan_id):
        return "900544249083420672"


def _frame(service_id: int, event: dict) -> dict:
    """Build a real wsv3 t:10000 frame — triple-encoded, like the wire."""
    return {"t": 10000,
            "d": json.dumps({"serviceId": service_id,
                             "event": json.dumps(event)})}


def check(cond, label, fails):
    if not cond:
        fails.append(label)


# ── the captured frames (RECIPES §"Captured events") ────────────────────

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

PRESENCE = {"type": 1, "status": {
    "accountId": ACCOUNT_ID, "statusId": 1,
    "lastSeenAt": 1788284489386, "updatedAt": 1788284489386}}


def main(argv) -> int:
    fails: list[str] = []
    ws = FanslyWebSocket(_FakeClient())

    # ── the inbound message: the whole point of the pump ────────────────
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
        # Snowflakes exceed 2^53; a float/int here would corrupt the id.
        check(isinstance(m["id"], str) and isinstance(m["fromUser"]["id"], str),
              "ids are STRINGS (snowflakes exceed 2^53)", fails)
        check(m["mediaCount"] == 1,
              "attachment counted even though the frame carries no accountMedia[]", fails)
        # createdAt is float epoch SECONDS on this socket, not ms.
        check(m["createdAt"].startswith("2026-"),
              f"createdAt parsed as epoch seconds (got {m['createdAt']})", fails)
    print("inbound: triple-decoded and reshaped into api2_chat_message")

    # ── the outbound echo passes through; the transcoder decides direction ──
    ev = ws._translate(_frame(5, OUTBOUND_ECHO))
    check(ev is not None, "outbound echo is NOT dropped by the pump", fails)
    if ev:
        check(ev["api2_chat_message"]["fromUser"]["id"] == ACCOUNT_ID,
              "echo's fromUser.id == us, so transcode marks it 'out'", fails)
    print("outbound echo: passed through — direction is the transcoder's call")

    # ── duplicates are normal on this socket ───────────────────────────
    dup = ws._translate(_frame(5, INBOUND))
    check(dup is None, "a repeated frame is deduped on (serviceId, type, id)", fails)
    # ...and the dedupe ring must stay bounded on a pump that lives for weeks.
    for i in range(700):
        ws._translate(_frame(5, {"type": 1, "message": {
            "id": f"9512285817054{i:05d}", "senderId": FAN_ID,
            "content": "x", "createdAt": 1788284926.39, "attachments": []}}))
    check(len(ws._seen) <= 512 and len(ws._seen_order) <= 512,
          f"dedupe ring stays bounded (got {len(ws._seen)})", fails)
    print(f"dedupe: duplicates dropped, ring bounded at {len(ws._seen)}")

    # ── frames we don't translate yield NOTHING, never a raw envelope ───
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

    # ── the token comes off the session, never from me() ────────────────
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
