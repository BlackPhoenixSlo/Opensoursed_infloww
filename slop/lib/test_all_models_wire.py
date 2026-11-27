import json
import threading
import types
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import pytest

from slop.lib import all_models_wire, of_wire

AID = "500"


def _fans(n: int) -> list[dict]:
    return [{"id": 1000 + k, "username": f"f{k}", "name": f"Fan {k}"} for k in range(n)]


def _fake():
    return types.SimpleNamespace(lock=threading.Lock(), chats={}, profiles={}, extra_routes=[])


def _whole(fake) -> int:
    return sum(1 for r in fake.chats[AID] if all_models_wire.unread(r))


def _call(wire, method: str, path: str) -> dict:
    got = {}
    h = types.SimpleNamespace(_record=lambda uid, route, status, body: got.update(status=status, body=body))
    assert wire.handle(h, method, urlsplit(path), AID, f"{method} {path}", b"")
    return got


def test_seed_counts_deep_unread_rows_below_page_0():
    fake = _fake()
    wire = all_models_wire.install(fake)
    wire.seed_chats(AID, _fans(30), 6, base_id=1, deep_unread=(26, 28))
    assert wire.chat_messages_count(AID) == 8 == _whole(fake)
    page0 = sum(1 for r in fake.chats[AID][:25] if all_models_wire.unread(r))
    assert page0 == 6, "a rows-based page-0 count misses the deep ones"
    assert fake.profiles[AID]["chatMessagesCount"] == 8


def test_profile_overlay_keeps_other_fields():
    fake = _fake()
    fake.profiles[AID] = {"name": "Kept"}
    all_models_wire.install(fake).seed_chats(AID, _fans(3), 1, base_id=1)
    assert fake.profiles[AID] == {"name": "Kept", "chatMessagesCount": 1}


def test_dm_counts_chats_not_messages():
    fake = _fake()
    wire = all_models_wire.install(fake)
    fans = _fans(10)
    wire.seed_chats(AID, fans, 2, base_id=1)
    msg = {"id": 9, "text": "hi", "fromUser": {"id": fans[5]["id"]}}
    wire.push_dm(AID, fans[5], msg)
    assert wire.chat_messages_count(AID) == 3
    wire.push_dm(AID, fans[5], msg)
    wire.push_dm(AID, fans[0], msg)
    assert wire.chat_messages_count(AID) == 3
    new = {"id": 4242, "username": "new", "name": "New"}
    wire.push_dm(AID, new, msg)
    assert wire.chat_messages_count(AID) == 4 == _whole(fake)


def test_send_reads_the_chat():
    fake = _fake()
    wire = all_models_wire.install(fake)
    fans = _fans(5)
    wire.seed_chats(AID, fans, 3, base_id=1)
    wire.head_from_send(AID, fans[1]["id"], {"id": 7, "text": "yo", "fromUser": {"id": int(AID)}})
    assert wire.chat_messages_count(AID) == 2
    wire.head_from_send(AID, fans[4]["id"], {"id": 8, "text": "yo", "fromUser": {"id": int(AID)}})
    assert wire.chat_messages_count(AID) == 2 == _whole(fake)


def test_marks_on_the_wire_and_on_of_web():
    fake = _fake()
    wire = all_models_wire.install(fake)
    fans = _fans(30)
    wire.seed_chats(AID, fans, 4, base_id=1, deep_unread=(27,))
    assert wire.chat_messages_count(AID) == 5
    assert _call(wire, "POST", f"/api2/v2/chats/{fans[0]['id']}/mark-as-read")["status"] == 200
    assert wire.chat_messages_count(AID) == 4
    assert wire.mark_read_out_of_band(AID, fans[27]["id"]) is True
    assert wire.chat_messages_count(AID) == 3
    assert wire.mark_read_out_of_band(AID, fans[27]["id"]) is False
    assert wire.chat_messages_count(AID) == 3
    _call(wire, "DELETE", f"/api2/v2/chats/{fans[10]['id']}/mark-as-read")
    assert wire.chat_messages_count(AID) == 4
    _call(wire, "POST", "/api2/v2/chats/mark-as-read")
    assert wire.chat_messages_count(AID) == 0 == _whole(fake)


def test_unseeded_creator_counts_zero():
    assert all_models_wire.install(_fake()).chat_messages_count("nobody") == 0


def test_users_me_serves_the_counter_through_the_real_fake():
    with of_wire.FakeOF(latency_s=0.0) as fake:
        wire = all_models_wire.install(fake)
        fans = _fans(30)
        wire.seed_chats(AID, fans, 6, base_id=1, deep_unread=(26, 28))
        wire.mark_read_out_of_band(AID, fans[1]["id"])

        def me() -> dict:
            req = urllib.request.Request(f"{fake.origin}/api2/v2/users/me", headers={"User-ID": AID})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())
        body = me()
        assert body["chatMessagesCount"] == 7 and body["id"] == int(AID)
        wire.push_dm(AID, fans[20], {"id": 5, "text": "x", "fromUser": {"id": fans[20]["id"]}})
        assert me()["chatMessagesCount"] == 8


def test_fakeof_can_hold_the_response_after_accepting():
    accepted, release = threading.Event(), threading.Event()
    path = "/api2/v2/chats/2/messages"
    with of_wire.FakeOF(latency_s=0.0) as fake, ThreadPoolExecutor(1) as pool:
        fake.hold_response["1", path] = accepted, release
        request = urllib.request.Request(fake.origin + path, data=b'{"text":"held"}', headers={"User-ID": "1"})

        def post():
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status

        response = pool.submit(post)
        try:
            assert accepted.wait(3)
            assert [call["status"] for call in fake.calls] == [200]
            assert len(fake.sends["1"]) == 1 and not response.done()
        finally:
            release.set()
        assert response.result(timeout=5) == 200


def test_fakeof_records_an_accepted_send_whose_hold_times_out():
    with of_wire.FakeOF(latency_s=0.0) as fake:
        path = "/api2/v2/chats/2/messages"
        accepted = threading.Event()
        fake.hold_response["1", path] = accepted, types.SimpleNamespace(wait=lambda timeout: False)
        request = urllib.request.Request(fake.origin + path, data=b'{"text":"held"}', headers={"User-ID": "1"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=5)
        assert exc.value.code == 504
        assert accepted.is_set()
        assert len(fake.sends["1"]) == 1
        assert fake.hold_timeouts == [("1", path)]
