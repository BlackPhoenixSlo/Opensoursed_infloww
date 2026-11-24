#!/usr/bin/env python3
"""`chat_restrict_changed` (server._publish_restrict_changed): an OF restrict or lift through the relay tells every
tab of the Creator, so another tab's cached chat lists drop or show "User is restricted" without a re-read (app
hooks/useAccountStateEvents.ts). Only once OF took the write. Any-scope: an All Models tab holds every Creator's rows.

OF client faked (no network). Run: venv/bin/python service/tests/test_chat_restrict_changed_sse.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # pytest: tests/ is a package
import _harness  # noqa: E402  (first: temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402

import events  # noqa: E402
import events_decide as ed  # noqa: E402
import server  # noqa: E402
from automations import _common  # noqa: E402

AID, FAN = "acct-restrict", 9002


class _Client:
    def __init__(self, fail=False):
        self.fail = fail

    def _call(self, *_a):
        if self.fail:
            raise RuntimeError("OF said no")
        return {"success": True}

    restrict_user = unrestrict_user = hide_chat = unhide_chat = _call


def _run(route, *args, client=None, **kw):
    """`route(*args, **kw)` with `client` as the OF client; returns (published events, raised)."""
    published = []

    async def _skip(*_a, **_k):
        return None

    async def _ids(*_a, **_k):
        return set()

    orig = (server._get_client, server._resolve_account_id, _common.set_of_restricted_skip,
            _common.load_of_restricted_ids, server._bust_chat_list_and_badges, events.publish)
    server._get_client = lambda *_a: client or _Client()
    server._resolve_account_id = lambda *_a: AID
    _common.set_of_restricted_skip = _skip
    _common.load_of_restricted_ids = _ids
    server._bust_chat_list_and_badges = lambda *_a, **_k: None
    events.publish = published.append
    raised = None
    try:
        asyncio.run(route(*args, **kw))
    except Exception as e:  # noqa: BLE001 — _proxy's 502
        raised = e
    finally:
        (server._get_client, server._resolve_account_id, _common.set_of_restricted_skip,
         _common.load_of_restricted_ids, server._bust_chat_list_and_badges, events.publish) = orig
    return published, raised


def _restrict(client=None):
    return _run(server.of_restrict_user, FAN, None, ack=False, hide=True, client=client)


def _lift(client=None):
    return _run(server.of_unrestrict_user, FAN, None, unhide=True, client=client)


def test_restrict_publishes_restricted_true():
    pub, raised = _restrict()
    assert raised is None, raised
    assert pub == [{"chat_restrict_changed": {"fan_id": FAN, "restricted": True}, "__account_id": AID}], pub


def test_lift_publishes_restricted_false():
    pub, raised = _lift()
    assert raised is None, raised
    assert pub == [{"chat_restrict_changed": {"fan_id": FAN, "restricted": False}, "__account_id": AID}], pub


def test_a_failed_of_write_publishes_nothing():
    for go in (_restrict, _lift):
        pub, raised = go(_Client(fail=True))
        assert raised is not None and pub == [], (go.__name__, pub)


def test_reaches_every_tab_of_the_creator():
    e = {"chat_restrict_changed": {"fan_id": FAN, "restricted": False}, "__account_id": AID}
    assert "chat_restrict_changed" in ed.SSE_TYPES
    mine = frozenset({AID, "other"})
    assert ed.wants(f"model:{AID}", mine, frozenset(), e)
    assert ed.wants("model:other", mine, frozenset(), e)
    assert ed.wants("all", mine, frozenset(), e)
    assert not ed.wants("model:x", frozenset({"x"}), frozenset(), e)


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
