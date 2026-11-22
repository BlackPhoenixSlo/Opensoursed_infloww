#!/usr/bin/env python3
"""read_flip.after_write: what follows a read flip that landed (the relay's mark read / unread / mark all read routes,
and the automations' mark read after a reply): local unread set, cached chat list + roster badges + chat detail
dropped, `chat_read_changed` published. A write that did not land (the Fansly shim's 200 `{"success": false}`
rejected ack) does none of it; a raise never reaches it. welcome_chatter_for_info's mark read goes through it
(full_ai_live's: test_full_ai_live_typing case_mark_read).

No network, no DB writes (set_local_unread recorded). Run: venv/bin/python -m pytest service/tests/test_read_flip_helper.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # pytest: tests/ is a package
import _harness  # noqa: E402  (first: temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import events  # noqa: E402
import read_flip  # noqa: E402
import relay_cache  # noqa: E402
from automations import welcome_chatter_for_info as wcfi  # noqa: E402

AID, FAN = "acct-flip", 4242


@contextlib.contextmanager
def _recorded():
    """(local sets, cache busts, published events) while the block runs; all put back."""
    local, busted, published = [], [], []

    async def _local(account_id, *, fan_id, value, at=None):
        local.append((account_id, fan_id, value))

    orig = (read_flip.set_local_unread, relay_cache.invalidate, events.publish)
    read_flip.set_local_unread = _local
    relay_cache.invalidate = lambda ep, aid, **kw: busted.append((ep, aid, "match" in kw and kw["match"] is not None))
    events.publish = published.append
    try:
        yield local, busted, published
    finally:
        read_flip.set_local_unread, relay_cache.invalidate, events.publish = orig


def _flip(e):
    assert list(e) == ["chat_read_changed", "__account_id"] and e["__account_id"] == AID, e
    return {k: e["chat_read_changed"][k] for k in ("fan_id", "unread")}


def test_landed_read_clears_busts_publishes():
    for result in ({"success": True}, None, {"counters": {}}):    # OF body, 204, any other 2xx body
        with _recorded() as (local, busted, pub):
            assert asyncio.run(read_flip.after_write(AID, FAN, 0, result)) is True
        assert local == [(AID, FAN, 0)], local
        assert busted == [("list_chats", AID, False), ("roster_count", AID, False), ("get_chat", AID, True)], busted
        assert [_flip(e) for e in pub] == [{"fan_id": FAN, "unread": 0}], pub


def test_mark_all():
    with _recorded() as (local, busted, pub):
        assert asyncio.run(read_flip.after_write(AID, None, 0, {"success": True})) is True
    assert local == [(AID, None, 0)] and ("get_chat", AID, False) in busted, (local, busted)
    assert [_flip(e) for e in pub] == [{"fan_id": "all", "unread": 0}], pub


def test_partial_mark_all_clears_only_the_acked_fans_and_is_not_landed():
    """W30-mu #2: a capped / partly failed mark-all (the Fansly shim's `partial`) never clears or announces "all"."""
    with _recorded() as (local, _busted, pub):
        assert asyncio.run(read_flip.after_write(
            AID, None, 0, {"success": True, "partial": True, "acked_fan_ids": [11, 12]})) is False
    assert local == [(AID, 11, 0), (AID, 12, 0)], local
    assert [_flip(e) for e in pub] == [{"fan_id": 11, "unread": 0}, {"fan_id": 12, "unread": 0}], pub
    with _recorded() as (local, busted, pub):
        assert asyncio.run(read_flip.after_write(AID, None, 0, {"success": True, "partial": True})) is False
    assert local == [] and busted == [] and pub == [], (local, busted, pub)


def test_rejected_ack_does_nothing():
    with _recorded() as (local, busted, pub):
        assert asyncio.run(read_flip.after_write(AID, FAN, 0, {"success": False, "reason": "ack_rejected"})) is False
    assert local == [] and busted == [] and pub == [], (local, busted, pub)


def test_a_publish_or_bust_failure_never_raises():
    def _boom(*_a, **_k):
        raise RuntimeError("down")
    with _recorded():
        relay_cache.invalidate = events.publish = _boom
        assert asyncio.run(read_flip.after_write(AID, FAN, 0, {"success": True})) is True


def _wcfi_turn(client):
    return SimpleNamespace(client=client, c=SimpleNamespace(fan_id=FAN), cfg=SimpleNamespace(account_id=AID))


class _OF:
    def __init__(self, answer=None, fail=False):
        self.answer, self.fail, self.read = answer, fail, []

    def mark_chat_read(self, chat_id):
        self.read.append(chat_id)
        if self.fail:
            raise RuntimeError("OF 500 on mark-as-read")
        return self.answer


def test_wcfi_mark_read_goes_through_read_flip():
    of = _OF({"success": True})
    with _recorded() as (local, _busted, pub):
        asyncio.run(wcfi._turn_mark_read(_wcfi_turn(of)))
    assert of.read == [FAN] and local == [(AID, FAN, 0)], (of.read, local)
    assert [_flip(e) for e in pub] == [{"fan_id": FAN, "unread": 0}], pub


def test_wcfi_failed_or_rejected_read_publishes_nothing():
    for of in (_OF(fail=True), _OF({"success": False, "reason": "ack_rejected"})):
        with _recorded() as (local, busted, pub):
            asyncio.run(wcfi._turn_mark_read(_wcfi_turn(of)))    # never raises: the send already landed
        # W30-mu #1: the local unread is only ever cleared after the write landed; nothing follows a miss
        assert of.read == [FAN] and local == [] and busted == [] and pub == [], (local, busted, pub)


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


def test_the_flip_carries_the_stamp_taken_before_the_write():
    with _recorded() as (_local, _busted, published):
        assert asyncio.run(read_flip.after_write(AID, FAN, 0, {"success": True}, at=1234)) is True
    assert published[0]["chat_read_changed"]["at"] == 1234
