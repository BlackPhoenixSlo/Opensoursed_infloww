#!/usr/bin/env python3
"""`chat_read_changed` (read_flip.publish): a read flip through the relay (mark read, mark unread, mark all
read) tells every tab of the Creator, so another chatter's cached chat lists flip the row without a re-read
(app hooks/useAccountStateEvents.ts). Only once OF took the write: a failed write, or a platform without it (501),
publishes nothing. Any-scope: an All Models tab holds every Creator's rows.

OF client faked (no network). Run: venv/bin/python -m pytest service/tests/test_chat_read_changed_sse.py -q
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # pytest: tests/ is a package
import _harness  # noqa: E402  (first: temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402

import events  # noqa: E402
import events_decide as ed  # noqa: E402
import read_flip  # noqa: E402
import server  # noqa: E402

AID, FAN = "acct-read", 9001


class _Client:
    def __init__(self, fail=False):
        self.fail = fail

    def _call(self, *_a):
        if self.fail:
            raise RuntimeError("OF said no")
        return {"success": True}

    mark_chat_read = mark_all_chats_read = mark_chat_unread = _call


def _run(route, *args, client=None):
    """`route(*args)` with `client` as the OF client; returns (published events, raised)."""
    published = []

    async def _no_local(*_a, **_k):
        return None

    orig = (server._get_client, server._resolve_account_id, read_flip.set_local_unread, events.publish)
    server._get_client = lambda *_a: client or _Client()
    server._resolve_account_id = lambda *_a: AID
    read_flip.set_local_unread = _no_local
    events.publish = published.append
    raised = None
    try:
        asyncio.run(route(*args))
    except Exception as e:  # noqa: BLE001 — _proxy's 502 / 501, or the client's own raise
        raised = e
    finally:
        server._get_client, server._resolve_account_id, read_flip.set_local_unread, events.publish = orig
    return published, raised


def _body(e):
    assert list(e) == ["chat_read_changed", "__account_id"], e
    assert e["__account_id"] == AID, e
    b = e["chat_read_changed"]
    assert isinstance(b["at"], int) and b["at"] > 1_700_000_000_000, b
    return {k: b[k] for k in ("fan_id", "unread")}


def test_mark_read_publishes_unread_0():
    pub, raised = _run(server.of_mark_chat_read, FAN)
    assert raised is None and [_body(e) for e in pub] == [{"fan_id": FAN, "unread": 0}], pub


def test_mark_unread_publishes_unread_1():
    pub, raised = _run(server.of_mark_chat_unread, FAN)
    assert raised is None and [_body(e) for e in pub] == [{"fan_id": FAN, "unread": 1}], pub


def test_mark_all_read_publishes_all():
    pub, raised = _run(server.of_mark_all_chats_read)
    assert raised is None and [_body(e) for e in pub] == [{"fan_id": "all", "unread": 0}], pub


def test_a_failed_of_write_publishes_nothing():
    for route, args in ((server.of_mark_chat_read, (FAN,)), (server.of_mark_chat_unread, (FAN,)),
                        (server.of_mark_all_chats_read, ())):
        pub, raised = _run(route, *args, client=_Client(fail=True))
        assert raised is not None and pub == [], (route.__name__, pub)


def test_a_rejected_ack_publishes_nothing():
    class _Rejected(_Client):   # the Fansly shim's 200 answer to an ack Fansly refused
        def _call(self, *_a):
            return {"success": False, "reason": "ack_rejected"}
        mark_chat_read = mark_all_chats_read = _call
    for route, args in ((server.of_mark_chat_read, (FAN,)), (server.of_mark_all_chats_read, ())):
        pub, raised = _run(route, *args, client=_Rejected())
        assert raised is None and pub == [], (route.__name__, raised, pub)


def test_a_platform_without_unread_publishes_nothing():
    class _Fansly(_Client):
        mark_chat_unread = None  # the shim lacks it: 501
    pub, raised = _run(server.of_mark_chat_unread, FAN, client=_Fansly())
    assert raised is not None and raised.status_code == 501 and pub == [], (raised, pub)


def test_reaches_every_tab_of_the_creator():
    e = {"chat_read_changed": {"fan_id": FAN, "unread": 0, "at": 1}, "__account_id": AID}
    assert "chat_read_changed" in ed.SSE_TYPES
    mine = frozenset({AID, "other"})
    assert ed.wants(f"model:{AID}", mine, frozenset(), e)
    assert ed.wants("model:other", mine, frozenset(), e)    # any-scope: its cached All Models lists
    assert ed.wants("all", mine, frozenset(), e)
    assert not ed.wants("model:x", frozenset({"x"}), frozenset(), e)  # never outside the clamp


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
