from __future__ import annotations

import _harness

_harness.bootstrap()

import types  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from unittest.mock import patch  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import accounts as account_registry  # noqa: E402
import of_pacing  # noqa: E402
from of_client import OFAPIError  # noqa: E402

_harness.make_client()
import server  # noqa: E402

AID = "acc_absorb_429"
account_registry.get_account = lambda aid: {"id": aid, "nickname": aid}
account_registry.get_platform = lambda aid: "onlyfans"
of_pacing.RETRY_MAX_S, of_pacing.JITTER_S, of_pacing.PAGE_GAP_S = 0.01, 0.0, 0.0
of_pacing.COOLDOWNS_S = (0.01,)
_BUDGET = of_pacing.READ_BUDGET_S


class _Resp:
    status_code = 429
    text = '{"error":{"code":0,"message":"Too many requests. Please allow 1 seconds.","payload":{"retry":1}}}'


def _calls(n429: int):
    n: list[int] = []

    def call():
        guard = server.PRE_DISPATCH.get()
        if guard is not None:
            guard()
        n.append(1)
        total, _bg = server._lanes_for(AID)
        assert total._value == server._ACCOUNT_LANE_TOTAL - 1, "the call holds one lane slot"
        if len(n) <= n429:
            raise OFAPIError("429", response=_Resp())
        return {"ok": True}
    return call, n


def _run(method: str | None, call, priority: str = "user", **kw):
    req = None if method is None else types.SimpleNamespace(
        method=method, headers={"x-account-id": AID, "x-priority": priority}, query_params={})
    token = server._request_ctx.set(req)
    try:
        return server._proxy(call, **kw)
    except HTTPException as e:
        return e
    finally:
        server._request_ctx.reset(token)


def _lane_free() -> bool:
    total, _bg = server._lanes_for(AID)
    return total._value == server._ACCOUNT_LANE_TOTAL


def case_get_absorbs_429():
    for prio in ("user", "background"):
        of_pacing._gates.clear()
        call, n = _calls(2)
        assert _run("GET", call, prio) == {"ok": True} and len(n) == 3, (prio, n)
        assert _lane_free()


def case_entry_point_decides_the_gate_class():
    seen = []
    real = of_pacing.absorb_429

    def spy(aid, call, **kw):
        seen.append((kw["prio"], kw.get("send_deadline") is not None))
        return real(aid, call, **kw)
    with patch.object(of_pacing, "absorb_429", spy):
        for method, prio, send in [("GET", "user", False), ("GET", "background", False),
                                   ("POST", "user", True), ("POST", "background", True)]:
            of_pacing._gates.clear()
            call, _ = _calls(0)
            assert _run(method, call, prio, send=send) == {"ok": True}
    assert seen == [(of_pacing.USER_READ, False), (of_pacing.BACKGROUND, False),
                    (of_pacing.PERSON_SEND, True), (of_pacing.PERSON_SEND, True)], seen


def case_get_past_budget_answers_429():
    of_pacing.READ_BUDGET_S = 0.025
    of_pacing._gates.clear()
    try:
        call, n = _calls(99)
        e = _run("GET", call)
        assert isinstance(e, HTTPException) and e.status_code == 502, e
        assert e.detail["upstream_status"] == 429 and 2 <= len(n) <= 4, (e.detail, n)
        assert _lane_free()
    finally:
        of_pacing.READ_BUDGET_S = _BUDGET


def case_write_not_retried():
    call, n = _calls(1)
    e = _run("POST", call)
    assert isinstance(e, HTTPException) and e.detail["upstream_status"] == 429 and len(n) == 1, (e, n)


def case_send_retry_429():
    of_pacing._gates.clear()
    call, n = _calls(1)
    assert _run("POST", call, send=True) == {"ok": True} and len(n) == 2, n
    of_pacing.READ_BUDGET_S = 0.025
    of_pacing._gates.clear()
    try:
        call, n = _calls(5)
        assert _run("POST", call, send=True) == {"ok": True} and len(n) == 6, n
        assert _lane_free()
    finally:
        of_pacing.READ_BUDGET_S = _BUDGET


def case_requestless_not_retried():
    n: list[int] = []

    def call():
        n.append(1)
        raise OFAPIError("429", response=_Resp())
    try:
        server._proxy(call)
        raise AssertionError("expected the 429")
    except HTTPException as e:
        assert e.detail["upstream_status"] == 429 and len(n) == 1, (e.detail, n)


def case_send_retry_cannot_dispatch_after_lane_wait():
    of_pacing._gates.clear()
    call, calls = _calls(2)
    real_lane = server._priority_lane
    delay = 0
    real_clock = server._time_mod.monotonic

    @contextmanager
    def lane(aid):
        nonlocal delay
        with real_lane(aid):
            if calls:
                delay = 60
            yield

    with patch.object(server, "_priority_lane", lane), patch.object(
        server._time_mod, "monotonic", side_effect=lambda: real_clock() + delay,
    ):
        out = _run("POST", call, send=True)
    assert out.status_code == 502 and out.detail["upstream_status"] == 429
    assert len(calls) == 1 and _lane_free()


def case_send_cutoff_counts_from_request_arrival():
    of_pacing._gates.clear()
    call, n = _calls(0)
    started = server._time_mod.monotonic() - of_pacing.SEND_BUDGET_S - 1
    out = _run("POST", call, send=True, started=started)
    assert isinstance(out, HTTPException) and out.status_code == 504 and not n, (out, n)
    assert _lane_free()


def case_send_retry_cannot_dispatch_after_signing_wait():
    from of_client import OFClient

    of_pacing._gates.clear()
    signed, posted = [], []
    delay = 0
    real_clock = server._time_mod.monotonic
    client = OFClient({"headers": {"user_id": AID, "x_bc": "bc", "x_of_rev": "rev", "user_agent": "ua"},
                       "signing": {"rules": {"static_param": "s", "start": "1", "end": "2",
                                             "checksum_indexes": [1], "checksum_constant": 1}},
                       "cookies": []})
    client.account_id = AID
    client._x_hash = "h"
    real_sign = client._signed_headers

    def sign(url):
        nonlocal delay
        signed.append(url)
        if len(signed) == 2:
            delay = 60
        return real_sign(url)

    def post(method, url, **_kw):
        posted.append((method, url))
        return types.SimpleNamespace(status_code=429, ok=False, text=_Resp.text, url=url, headers={})

    client._signed_headers = sign
    client.http = types.SimpleNamespace(request=post)
    with patch.object(server._time_mod, "monotonic", side_effect=lambda: real_clock() + delay):
        out = _run("POST", lambda: client.post_json("/api2/v2/chats/42/messages", json_body={}),
                   send=True)
    assert out.status_code == 502 and out.detail["upstream_status"] == 429
    assert len(signed) == 2 and len(posted) == 1 and _lane_free()


async def case_send_bookkeeping_once_for_two_429s():
    import dm_rate
    import sends_inflight
    from db.engine import get_session
    from db.models import Account, Message
    from of_client import OFClient
    from sqlalchemy import select

    of_pacing._gates.clear()
    dm_rate._reset()
    client = object.__new__(OFClient)
    client.account_id = AID
    posts = []

    def post(path, *, json_body):
        posts.append((path, json_body))
        if len(posts) <= 2:
            raise OFAPIError("429", response=_Resp())
        assert sends_inflight._open[(AID, 42)].posting == 1
        return {"id": 41234, "text": json_body["text"]}

    client.post_json = post
    async with get_session() as session:
        session.add(Account(id=AID, nickname=AID))
        await session.commit()

    req = types.SimpleNamespace(method="POST", headers={"x-account-id": AID}, query_params={})
    token = server._request_ctx.set(req)
    try:
        with patch.object(server, "_load_client", return_value=client):
            result = await server.send_message(req, 42, server.SendMessageBody(text="hello"))
        assert result["id"] == 41234
        assert len(posts) == 3 and posts[0] == posts[1] == posts[2]
        assert dm_rate.snapshot()[AID]["now"] == 1
        assert not sends_inflight.pending(AID, 42)
        async with get_session() as session:
            row = (await session.execute(select(Message).where(Message.message_id == 41234))).scalar_one()
            assert row.account_id == AID
    finally:
        server._request_ctx.reset(token)


async def case_cotag_recovery_does_not_replay_on_429():
    import dm_rate
    from of_client import OFClient, _CoTagRetry

    of_pacing._gates.clear()
    dm_rate._reset()
    posts = []
    client = object.__new__(OFClient)
    client.account_id = AID
    client._apply_cotags = lambda *_: _CoTagRetry([], True)

    def post(path, *, json_body):
        posts.append(path)
        if len(posts) == 1:
            raise OFAPIError("bad tag", response=types.SimpleNamespace(status_code=400))
        if len(posts) == 2:
            raise OFAPIError("429", response=_Resp())
        raise AssertionError("co-tag recovery replayed")

    client.post_json = post
    req = types.SimpleNamespace(method="POST", headers={"x-account-id": AID}, query_params={})
    token = server._request_ctx.set(req)
    try:
        with patch.object(server, "_load_client", return_value=client):
            try:
                await server.send_message(req, 43, server.SendMessageBody(text="hello"))
            except HTTPException as e:
                assert e.status_code == 502 and e.detail["upstream_status"] == 429
            else:
                raise AssertionError("expected the 429")
        assert len(posts) == 2
        assert dm_rate.snapshot()[AID]["now"] == 1
    finally:
        server._request_ctx.reset(token)


_harness.run()
