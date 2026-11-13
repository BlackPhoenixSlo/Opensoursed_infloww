#!/usr/bin/env python3
"""OF passthrough read timing line + chat detail cache/coalesce (chat slowness D2).

Over HTTP with real session cookies and a fake OF transport (the real OFClient
methods run; only the socket call is replaced, and it holds the client's real
signed slot, so no request leaves the process):

  • one `of_read_timing` line per timed read (messages, chats, users_list,
    chat) with every field; a held lane slot shows as lane_wait_ms, a held
    signed slot as signed_wait_ms, and neither is booked as of_ms;
  • a cache hit or coalesced joiner logs of_calls=0;
  • GET /chats/{id}: N concurrent reads of one (account, chat) = 1 OF call;
    a read within the 30 s TTL = no OF call, one after it = one;
  • our own chat writes (mark read, mute, pin/unpin, unsend), any recorded
    send and an inbound DM drop that chat's entry only; an OF-web outbound
    echo or a fan-less unsend drops the account's entries.

Run: ./venv/bin/python service/tests/test_of_read_timing.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import httpx  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts  # noqa: E402
import event_transcoder as et  # noqa: E402
import of_client  # noqa: E402
import relay_cache  # noqa: E402
import relay_coalesce  # noqa: E402
import server  # noqa: E402
import webhook_dispatch  # noqa: E402

IDS = fx.seed_two_agencies()
A = IDS["creator_a"]
accounts.upsert_account(A, nickname=f"creator {A}")
OWNER_A = fx.login_owner("agency_a_owner")


class _Resp:
    def __init__(self, url: str, status: int, body) -> None:
        self.url, self.status_code = url, status
        self.ok = 200 <= status < 300
        self.text = json.dumps(body)
        self.headers: dict = {}

    def json(self):
        return json.loads(self.text)


class _FakeOF:
    """An OFClient whose socket call holds the real signed slot, sleeps
    `delay_s` and answers `{"n": call number}`; records (method, path)."""

    def __init__(self, account_id: str) -> None:
        self.client = of_client.OFClient.__new__(of_client.OFClient)
        self.client.account_id = account_id
        self.client._signed_slots = threading.BoundedSemaphore(8)
        self.client._http_call = self._http_call
        self.calls: list[tuple[str, str]] = []
        self.delay_s = 0.0
        self._lock = threading.Lock()

    def _http_call(self, method: str, url: str, *, json_body=None):
        with self.client._signed_slot():
            if self.delay_s:
                time.sleep(self.delay_s)
            with self._lock:
                self.calls.append((method, of_client._short_path(url)))
                n = len(self.calls)
        path = of_client._short_path(url)
        if path.endswith("/messages"):
            return _Resp(url, 200, {"list": [], "hasMore": False, "n": n})
        if path == "/api2/v2/chats":
            return _Resp(url, 200, {"list": [], "hasMore": False})
        if path == "/api2/v2/users/list":
            return _Resp(url, 200, {})
        return _Resp(url, 200, {"n": n, "path": path})

    def gets(self, path: str) -> int:
        return sum(1 for m, p in self.calls if m == "GET" and p == path)


FAKE: list[_FakeOF] = []
server._get_client = lambda *_a, **_k: FAKE[0].client


class _Lines(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record) -> None:
        msg = record.getMessage()
        if msg.startswith("of_read_timing "):
            self.lines.append(msg)


LINES = _Lines()
server.log.addHandler(LINES)
server.log.setLevel(logging.INFO)

_FIELDS = ("route", "account", "chat", "prio", "status", "of_calls", "lane_wait_ms",
           "signed_wait_ms", "of_ms", "post_ms", "total_ms")


def _parse(line: str) -> dict[str, str]:
    kv = dict(re.findall(r"(\w+)=(\S+)", line))
    assert tuple(kv) == _FIELDS, f"fields {tuple(kv)} != {_FIELDS}: {line}"
    return kv


def _fresh() -> _FakeOF:
    relay_cache._cache.clear()
    relay_coalesce.reset_for_tests()
    FAKE[:] = [_FakeOF(A)]
    LINES.lines.clear()
    return FAKE[0]


def _get(path: str, **headers):
    r = OWNER_A.get(path, headers={"X-Account-Id": A, **headers})
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
    return r.json()


def _burst_paths(paths: list[str], **headers) -> list:
    async def go():
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver",
                                     cookies=dict(OWNER_A.cookies)) as c:
            return await asyncio.gather(*[
                c.get(p, headers={"X-Account-Id": A, **headers}) for p in paths])
    return asyncio.run(go())


def _burst(path: str, n: int, **headers) -> list:
    return _burst_paths([path] * n, **headers)


# ── The timing line ─────────────────────────────────────────────────────────

def case_each_timed_route_logs_one_line_with_every_field():
    fake = _fresh()
    fake.delay_s = 0.05
    _get("/api/of/v2/chats/77/messages")
    _get("/api/of/v2/chats?limit=10")
    _get("/api/of/v2/users/list?ids=5&ids=6")
    _get("/api/of/v2/chats/77")
    routes = [_parse(ln)["route"] for ln in LINES.lines]
    assert routes == ["messages", "chats", "users_list", "chat"], LINES.lines
    for ln in LINES.lines:
        kv = _parse(ln)
        assert kv["account"] == A and kv["status"] == "200" and kv["prio"] == "user", ln
        assert int(kv["of_calls"]) >= 1, ln
        assert int(kv["of_ms"]) >= 40, ln          # the fake's 50 ms upstream
        assert int(kv["total_ms"]) >= int(kv["of_ms"]), ln
    assert _parse(LINES.lines[0])["chat"] == "77" and _parse(LINES.lines[1])["chat"] == "-"


def case_a_held_lane_slot_is_lane_wait_not_of_time():
    fake = _fresh()
    total, _bg = server._lanes_for(A)
    held = 0
    while total.acquire(blocking=False):
        held += 1
    threading.Timer(0.5, lambda: [total.release() for _ in range(held)]).start()
    _get("/api/of/v2/chats/78")
    kv = _parse(LINES.lines[-1])
    assert int(kv["lane_wait_ms"]) >= 200, kv
    assert int(kv["of_ms"]) < 200, kv
    assert fake.gets("/api2/v2/chats/78") == 1


def case_a_background_read_queued_at_admission_shows_it_in_lane_wait_and_total():
    """The background sub-lane (2) admits before the route runs (`_bg_admission_route`):
    the third of three concurrent background reads waits there, and its line must
    still show that wait, inside total_ms."""
    fake = _fresh()
    fake.delay_s = 0.3
    replies = _burst_paths([f"/api/of/v2/chats/{c}" for c in (70, 71, 72)],
                           **{"X-Priority": "background"})
    assert [r.status_code for r in replies] == [200] * 3, [r.text for r in replies]
    rows = [_parse(ln) for ln in LINES.lines]
    assert max(int(kv["lane_wait_ms"]) for kv in rows) >= 200, rows
    for kv in rows:
        assert int(kv["total_ms"]) + 5 >= int(kv["lane_wait_ms"]) + int(kv["of_ms"]), kv


def case_a_held_signed_slot_is_signed_wait_not_of_time():
    fake = _fresh()
    fake.client._signed_slots = threading.BoundedSemaphore(1)
    fake.client._signed_slots.acquire()
    threading.Timer(0.5, fake.client._signed_slots.release).start()
    _get("/api/of/v2/chats/79/messages")
    kv = _parse(LINES.lines[-1])
    assert int(kv["signed_wait_ms"]) >= 200, kv
    assert int(kv["of_ms"]) < 200 and int(kv["lane_wait_ms"]) < 50, kv


def case_a_cache_hit_logs_no_of_call():
    _fresh()
    _get("/api/of/v2/chats/80")
    _get("/api/of/v2/chats/80")
    first, second = (_parse(ln) for ln in LINES.lines)
    assert first["of_calls"] == "1" and second["of_calls"] == "0", LINES.lines
    assert second["of_ms"] == "0" and second["lane_wait_ms"] == "0", second


def case_an_upstream_error_logs_its_status():
    fake = _fresh()
    fake.client._signed_slots = None
    fake.client._http_call = lambda method, url, json_body=None: _Resp(url, 400, {"error": "nope"})
    r = OWNER_A.get("/api/of/v2/chats/81", headers={"X-Account-Id": A})
    assert r.status_code == 502, r.text
    assert _parse(LINES.lines[-1])["status"] == "502", LINES.lines


# ── get_chat: coalesce + TTL ────────────────────────────────────────────────

def case_concurrent_get_chat_reads_share_one_upstream_call():
    fake = _fresh()
    fake.delay_s = 0.2
    replies = _burst("/api/of/v2/chats/90", 8, **{"X-Priority": "background"})
    assert [r.status_code for r in replies] == [200] * 8, [r.text for r in replies]
    assert len({r.text for r in replies}) == 1
    assert fake.gets("/api2/v2/chats/90") == 1, fake.calls
    assert sorted(_parse(ln)["of_calls"] for ln in LINES.lines) == ["0"] * 7 + ["1"], LINES.lines


def case_get_chat_ttl_hit_then_expiry():
    fake = _fresh()
    now = [1000.0]
    real_time = relay_cache.time
    relay_cache.time = type("Clock", (), {"monotonic": staticmethod(lambda: now[0])})
    try:
        _get("/api/of/v2/chats/91")
        now[0] += server._GET_CHAT_TTL - 1
        _get("/api/of/v2/chats/91")
        assert fake.gets("/api2/v2/chats/91") == 1, "a read within the TTL went to OF"
        now[0] += 2
        _get("/api/of/v2/chats/91")
        assert fake.gets("/api2/v2/chats/91") == 2, "a read after the TTL was served stale"
    finally:
        relay_cache.time = real_time
    assert server._GET_CHAT_TTL == 30.0


def case_other_chats_are_their_own_entries():
    fake = _fresh()
    _get("/api/of/v2/chats/92")
    _get("/api/of/v2/chats/93")
    assert fake.gets("/api2/v2/chats/92") == 1 and fake.gets("/api2/v2/chats/93") == 1


# ── Invalidation ────────────────────────────────────────────────────────────

def case_mark_read_and_mute_drop_that_chat_only():
    fake = _fresh()
    for cid in (94, 95):
        _get(f"/api/of/v2/chats/{cid}")
    r = OWNER_A.post("/api/of/v2/chats/94/mark-as-read", headers={"X-Account-Id": A})
    assert r.status_code == 200, r.text
    _get("/api/of/v2/chats/94")
    _get("/api/of/v2/chats/95")
    assert fake.gets("/api2/v2/chats/94") == 2 and fake.gets("/api2/v2/chats/95") == 1, fake.calls
    r = OWNER_A.post("/api/of/v2/chats/95/mute", headers={"X-Account-Id": A})
    assert r.status_code == 200, r.text
    _get("/api/of/v2/chats/95")
    assert fake.gets("/api2/v2/chats/95") == 2, fake.calls


def case_an_inbound_dm_drops_that_fans_detail():
    fake = _fresh()
    _get("/api/of/v2/chats/96")
    _get("/api/of/v2/chats/97")

    async def _noop(*_a, **_k):
        return None
    for name in ("on_inbound_tip", "on_inbound_message", "on_inbound_image"):
        setattr(webhook_dispatch, name, _noop)

    async def go():
        await et.transcode({"api2_chat_message": {
            "id": 555000111, "text": "hey", "price": 0, "isTip": False,
            "fromUser": {"id": 96}, "createdAt": "2026-11-13T10:00:00+00:00",
            "responseType": "message"}, "__account_id": A})
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*pending, return_exceptions=True)
    asyncio.run(go())
    _get("/api/of/v2/chats/96")
    _get("/api/of/v2/chats/97")
    assert fake.gets("/api2/v2/chats/96") == 2 and fake.gets("/api2/v2/chats/97") == 1, fake.calls


def case_pin_unpin_and_unsend_drop_that_chat_and_unsend_without_fan_drops_all():
    fake = _fresh()
    h = {"X-Account-Id": A}

    def warm():
        for cid in (60, 61):
            _get(f"/api/of/v2/chats/{cid}")

    def counts():
        return fake.gets("/api2/v2/chats/60"), fake.gets("/api2/v2/chats/61")

    warm()
    for method, path, want in (
        ("post", "/api/of/v2/messages/9001/pin/user/60", (2, 1)),
        ("delete", "/api/of/v2/messages/9001/pin/user/61", (2, 2)),
        ("delete", "/api/of/v2/chats/60/messages/pin", (3, 2)),
    ):
        r = getattr(OWNER_A, method)(path, headers=h)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
        warm()
        assert counts() == want, (path, counts(), fake.calls)
    r = OWNER_A.request("DELETE", "/api/of/v2/messages/9002", headers=h,
                        content=json.dumps({"withUserId": 61}))
    assert r.status_code == 200, r.text
    warm()
    assert counts() == (3, 3), (counts(), fake.calls)
    r = OWNER_A.request("DELETE", "/api/of/v2/messages/9003", headers=h)
    assert r.status_code == 200, r.text
    warm()
    assert counts() == (4, 4), (counts(), fake.calls)


def case_an_outbound_echo_drops_the_accounts_details():
    fake = _fresh()
    _get("/api/of/v2/chats/62")
    _get("/api/of/v2/chats/63")

    async def go():
        await et.transcode({"api2_chat_message": {
            "id": 555000222, "text": "sent from OF web", "price": 0, "isTip": False,
            "fromUser": {"id": int(A)}, "createdAt": "2026-11-13T10:00:00+00:00",
            "responseType": "message"}, "__account_id": A})
    asyncio.run(go())
    _get("/api/of/v2/chats/62")
    _get("/api/of/v2/chats/63")
    assert fake.gets("/api2/v2/chats/62") == 2 and fake.gets("/api2/v2/chats/63") == 2, fake.calls


def case_any_recorded_send_drops_that_fans_detail():
    from datetime import datetime
    import attribution
    fake = _fresh()
    _get("/api/of/v2/chats/64")
    _get("/api/of/v2/chats/65")
    asyncio.run(attribution.write_outbound_attribution(
        account_id=A, fan_id=64, message_id=555000333, sent_by_employee_id=None,
        body="automation send", price_cents=0, created_at=datetime.utcnow(),
        automation_kind="autoreply"))
    _get("/api/of/v2/chats/64")
    _get("/api/of/v2/chats/65")
    assert fake.gets("/api2/v2/chats/64") == 2 and fake.gets("/api2/v2/chats/65") == 1, fake.calls


_harness.run()
