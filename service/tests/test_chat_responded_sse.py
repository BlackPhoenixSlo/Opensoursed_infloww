#!/usr/bin/env python3
"""`chat_responded` from a person's send (server._record_fan_send): carries OF's answer cut to the row's preview
and an `at`, so every other tab moves the fan's row in its cached chat lists without a read (app
hooks/useInboxRealtime.ts). The chat-list cache is busted BEFORE it goes out: a list read served after the event
(a page whose `askedAt` is past `at`, left alone by the app) already holds the reply.

Run: venv/bin/python -m pytest service/tests/test_chat_responded_sse.py -q
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # pytest: tests/ is a package
import _harness  # noqa: E402  (first: temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402

import events  # noqa: E402
import server  # noqa: E402

AID, FAN = "acct-reply", 9101


def _send(result):
    """`_record_fan_send(result)`; returns the ordered log of busts and published events."""
    log: list = []
    orig = (events.publish, server._bust_chat_list_and_badges, server.unread_total.on_reply)
    events.publish = lambda e: log.append(("publish", e))
    server._bust_chat_list_and_badges = lambda aid, fan=None: log.append(("bust", aid, fan))
    server.unread_total.on_reply = lambda *args: log.append(("reply", *args))
    try:
        import relay_host
        asyncio.run(relay_host.record_fan_send(AID, FAN, result, employee_id=None, price=0, before_send_at=123))
    finally:
        events.publish, server._bust_chat_list_and_badges, server.unread_total.on_reply = orig
    return log


def test_reply_carries_message_after_bust():
    log = _send({"id": 501, "text": "hey you", "createdAt": "2026-11-20T10:00:00+00:00", "mediaCount": 2,
                 "price": 0, "fromUser": {"id": 1}})
    kinds = [x[0] for x in log if x[0] == "bust" or (x[0] == "publish" and "chat_responded" in x[1])]
    assert kinds == ["bust", "publish"], log
    ev = next(x[1] for x in log if x[0] == "publish" and "chat_responded" in x[1])
    assert ev["__account_id"] == AID, ev
    body = ev["chat_responded"]
    assert isinstance(body.pop("at"), int), body
    assert body == {"fan_id": FAN, "by": "", "message": {
        "id": 501, "text": "hey you", "createdAt": "2026-11-20T10:00:00+00:00", "mediaCount": 2, "price": 0.0}}, body


def test_reply_without_an_answer_body_still_announces():
    """A non-dict answer (a shim's odd shape) keeps the bell's announcement; tabs then have no row to patch."""
    log = _send(None)
    assert log[0] == ("reply", AID, FAN, 123), log
    ev = next(x[1] for x in log if x[0] == "publish" and "chat_responded" in x[1])
    assert "message" not in ev["chat_responded"] and ev["chat_responded"]["fan_id"] == FAN, ev


class _Req:
    headers: dict = {}

    async def is_disconnected(self) -> bool:
        return False


def _reply(aid: str) -> dict:
    return {"chat_responded": {"fan_id": FAN, "by": "Ann", "at": 1,
                               "message": {"id": 7, "text": "secret", "price": 25.0}}, "__account_id": aid}


async def _datas(gen, n: int) -> list[dict]:
    """The next `n` frames' JSON data, a batch frame's members flattened (comment/id-only frames skipped)."""
    import json
    out: list[dict] = []
    while len(out) < n:
        raw = (await asyncio.wait_for(gen.__anext__(), 3)).decode()
        data = next((ln[6:] for ln in raw.split("\n") if ln.startswith("data: ")), None)
        if data is None or data == "{}":
            continue
        got = json.loads(data)
        out.extend(m["data"] for m in got) if isinstance(got, list) else out.append(got)
    return out


def test_reply_text_reaches_only_sessions_whose_role_reads_that_creators_chats():
    """W30-mu #25: a chatter whose role does not grant B's chat history (`readable` without B, server.sse_events)
    gets B's `chat_responded` without `message` (reply text, price), live and on replay; A's keeps it, and an
    owner/unclamped stream (`readable` None) gets every one whole."""
    other = "acct-other"

    async def run():
        events._subs.clear()
        events._ring = events.ed.Rings(events._EPOCH)
        clamp = frozenset({AID, other})
        live = events.sse_stream(_Req(), f"model:{AID}", accounts=clamp, readable=frozenset({AID}))
        whole = events.sse_stream(_Req(), "all", accounts=None)
        for g in (live, whole):
            await g.__anext__(), await g.__anext__()     # connected, head
        await events.broadcast(_reply(other))
        await events.broadcast(_reply(AID))
        got = await _datas(live, 2)
        assert [("message" in d["chat_responded"], d["__account_id"]) for d in got] == \
            [(False, other), (True, AID)], got
        assert got[0]["chat_responded"] == {"fan_id": FAN, "by": "Ann", "at": 1}, got[0]
        assert all("message" in d["chat_responded"] for d in await _datas(whole, 2))
        await live.aclose()
        await whole.aclose()
        # Replay: a reconnect from before both gets the same cut.
        first = events.ed.Rings(events._EPOCH)
        replay = events.sse_stream(_Req(), f"model:{AID}", accounts=clamp, readable=frozenset({AID}),
                                   last_event_id=f"{first.epoch}.0")
        await replay.__anext__()
        got = await _datas(replay, 2)
        assert [("message" in d["chat_responded"], d["__account_id"]) for d in got] == \
            [(False, other), (True, AID)], got
        await replay.aclose()
        # The ring itself still holds the whole frame (another session's replay is unaffected).
        held = [f for ring in events._ring.rings.values() for _, f in ring]
        assert len(held) == 2 and all("message" in f["chat_responded"] for f in held), held

    asyncio.run(run())


def test_a_permissions_change_ends_the_stream_so_the_reconnect_reads_the_new_grant():
    """W30-mu #39: `readable` is decided at connect (server.sse_events). A roles write (`permissions_changed`,
    Agency-wide) ends the stream after it, as `assignment_changed` does, so a chatter whose role lost a Creator's
    chat history gets no more reply text on the old grant: the browser's reconnect reads the new one."""
    owner = "owner-39"

    async def run():
        events._subs.clear()
        events._ring = events.ed.Rings(events._EPOCH)
        gen = events.sse_stream(_Req(), "all", accounts=frozenset({AID}), agencies=frozenset({owner}),
                                readable=frozenset({AID}))
        await gen.__anext__(), await gen.__anext__()     # connected, head
        events.publish_state("permissions_changed", agency=owner)
        assert await _datas(gen, 1) == [{"permissions_changed": {}, "__agency": owner}]
        await events.broadcast(_reply(AID))
        try:
            got = await _datas(gen, 1)
            raise AssertionError(f"the stream outlived the roles write: {got}")
        except StopAsyncIteration:
            pass
        assert events.subscriber_count() == 0

    asyncio.run(run())


async def _drain(gen, budget: float = 3.0) -> tuple[list[dict], bool]:
    """Every frame's JSON data until the stream ends (True) or goes quiet for `budget` s (False)."""
    import json
    out: list[dict] = []
    while True:
        try:
            raw = (await asyncio.wait_for(gen.__anext__(), budget)).decode()
        except StopAsyncIteration:
            return out, True
        except asyncio.TimeoutError:
            await gen.aclose()
            return out, False
        for ln in raw.split("\n"):
            if ln.startswith("data: ") and ln[6:] != "{}":
                got = json.loads(ln[6:])
                out.extend(m["data"] for m in got) if isinstance(got, list) else out.append(got)


def _texts(frames: list[dict]) -> list:
    return [f["chat_responded"]["message"]["text"] for f in frames
            if "message" in (f.get("chat_responded") or {})]


def test_replies_flooding_the_queue_after_a_revocation_carry_no_text_and_the_stream_ends():
    """W30-mu #39 (reopened): more replies than the queue holds, published after `permissions_changed`, used to
    evict that frame (the stream sent `resync`, then the reply text on the revoked grant, and never ended). The
    stream is marked ended when the frame is handed to it: nothing later is queued and it ends on draining.
    Batching off (SSE_BATCH_WINDOW_MS=0) so each reply is its own queue item."""
    owner = "owner-39a"

    async def run():
        events.SSE_BATCH_WINDOW_MS = 0
        events._subs.clear()
        events._ring = events.ed.Rings(events._EPOCH)
        gen = events.sse_stream(_Req(), "all", accounts=frozenset({AID}), agencies=frozenset({owner}),
                                readable=frozenset({AID}))
        await gen.__anext__(), await gen.__anext__()     # connected, head
        events.publish_state("permissions_changed", agency=owner)
        for _ in range(events._QUEUE_MAX + 50):
            await events.broadcast(_reply(AID))
        got, ended = await _drain(gen)
        assert _texts(got) == [] and ended, (len(_texts(got)), ended)
        assert events.subscriber_count() == 0

    window = events.SSE_BATCH_WINDOW_MS
    try:
        asyncio.run(run())
    finally:
        events.SSE_BATCH_WINDOW_MS = window


def test_a_revocation_between_the_grant_read_and_the_stream_opening_ends_the_stream_with_no_text():
    """W30-mu #39 (reopened): server.sse_events reads `readable` (an await), then the body registers later. A
    roles write and a reply landing in between used to replay to a reconnect on the old grant. The stream now
    ends before any frame when a stream-ending frame took a seq after the grant read (`granted_at`)."""
    owner = "owner-39b"

    class _Chatter:
        id = 39
        owner_user_ids = frozenset({owner})

    async def revoke_meanwhile(accounts):
        events.publish_state("permissions_changed", agency=owner)
        await events.broadcast(_reply(AID))
        return frozenset({AID})                          # the grant as read before the write

    async def run():
        events._subs.clear()
        events._ring = events.ed.Rings(events._EPOCH)
        saved = (server._require_actor_account_ids, server._get_request_user, server._get_request_chatter,
                 server._chats_readable)
        server._require_actor_account_ids = lambda: frozenset({AID})
        server._get_request_user = lambda: None
        server._get_request_chatter = lambda: _Chatter()
        server._chats_readable = revoke_meanwhile
        try:
            resp = await server.sse_events(_Req(), scope="all", last_event_id=f"{events._EPOCH}.0", lease="1")
        finally:
            (server._require_actor_account_ids, server._get_request_user, server._get_request_chatter,
             server._chats_readable) = saved
        got, ended = await _drain(resp.body_iterator)
        assert _texts(got) == [] and ended, (got, ended)
        assert events.subscriber_count() == 0

    asyncio.run(run())


if __name__ == "__main__":
    test_reply_carries_message_after_bust()
    test_reply_without_an_answer_body_still_announces()
    test_reply_text_reaches_only_sessions_whose_role_reads_that_creators_chats()
    test_a_permissions_change_ends_the_stream_so_the_reconnect_reads_the_new_grant()
    test_replies_flooding_the_queue_after_a_revocation_carry_no_text_and_the_stream_ends()
    test_a_revocation_between_the_grant_read_and_the_stream_opening_ends_the_stream_with_no_text()
    print("ok")
