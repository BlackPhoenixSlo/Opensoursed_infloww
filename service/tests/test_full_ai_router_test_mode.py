#!/usr/bin/env python3
"""test_full_ai_router_test_mode — Shadow's Jev request stays byte-frozen while the Router
gains its test-Mode questions (03b ticket 43; spec story 66).

A Shadow Turn through the inbound path (`webhook_dispatch.on_inbound_message` then
`automation_executor.run_once`), Jev faked at `_router_jev._client` (`FakeJev`), on the
_harness temp DB.

  case_shadow_request_golden   the recorded Jev request (state + questions + model,
                               serialized) equals the golden bytes, and the row's
                               `question_version` is Shadow's `QUESTION_VERSION` (pinned)
  case_golden_file_pinned      the golden file's sha256 is the one captured at 10481c760
                               (ticket 47 phase B: nobody regenerated it)
  case_wall_clock_caps         rwl-a F3: a hanging Router request fails at `timeout_s` (test
                               Mode's cap), no budget = "deadline" with no request; N6: every
                               caller, Shadow too, at `WALL_S`; a hanging Writer walk under `_capped` reads
                               as no Writer answering

The golden (`test_full_ai_router_test_mode.shadow_request.golden.json`) was captured from
the unchanged Router module at 10481c760, before ticket 43 edited `_router_jev.py`. Never
regenerate it: a diff here means Shadow's request changed, which is a 04a / 05 step after the
owner OKs the new questions' wording.

Run: ./venv/bin/python service/tests/test_full_ai_router_test_mode.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness

_harness.bootstrap()

import hashlib  # noqa: E402
import json  # noqa: E402
from datetime import timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from _full_ai_fixtures import KIND, QUIET, T0, FakeJev, _dm, _fake_jev, _msg, _rows, _seed  # noqa: E402
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Transaction  # noqa: E402

GOLDEN = Path(__file__).with_name("test_full_ai_router_test_mode.shadow_request.golden.json")
SHADOW_QUESTION_VERSION = "14f5d4f6222f"
GOLDEN_SHA256 = "c83e5dc592bd3d5cb04d5418256f056f354cc5936f1425217833e994aa1dba31"


def _request_bytes(call: dict) -> bytes:
    return json.dumps(
        {"model": call["model"], "state": call["state"],
         "questions": {qid: q.model_dump(mode="json") for qid, q in call["questions"].items()}},
        ensure_ascii=False, indent=1).encode() + b"\n"


async def _shadow_call(aid: str, fan: int) -> dict:
    await _seed(aid, rule=True, gate=False)
    for i, (d, body) in enumerate((("in", "hey gorgeous"), ("out", "<p>hi babe &amp; welcome</p>"),
                                   ("in", "what are you up to"))):
        await _msg(aid, fan, 8000 + i, d, body, T0 - timedelta(minutes=90 - 10 * i))
    await _msg(aid, fan, 8010, "out", "<p>just for you 😈</p>", T0 - timedelta(minutes=30),
               price_cents=1500, is_paid=False, automation_kind="reply_mass_funnel")
    async with get_session() as s:
        s.add(Transaction(account_id=aid, fan_id=fan, kind="tip", amount_cents=2500,
                          occurred_at=T0 - timedelta(hours=3)))
    await _msg(aid, fan, 8020, "in", "you there?", T0)
    await _dm(aid, fan, 8021, "send me something hot", T0 + timedelta(minutes=1))
    fake = FakeJev((QUIET, 1.0))
    with _fake_jev(fake):
        res = await run_once(aid, KIND)
    assert res["status"] == "ok", res
    assert len(fake.calls) == 1, fake.calls
    return fake.calls[0]


async def case_shadow_request_golden():
    call = await _shadow_call("fa_golden", 91)
    got = _request_bytes(call)
    assert got == GOLDEN.read_bytes(), got.decode()
    (r,) = await _rows("fa_golden")
    assert r.mode == "shadow", r.mode
    assert r.question_version == SHADOW_QUESTION_VERSION, r.question_version


async def case_golden_file_pinned():
    assert hashlib.sha256(GOLDEN.read_bytes()).hexdigest() == GOLDEN_SHA256


async def case_wall_clock_caps():
    import asyncio
    import time

    import tenant_keys
    from automations import _router_jev as rj
    from automations import full_ai_turn

    class Slow(FakeJev):
        async def system_one(self, state, questions, model=None):
            await asyncio.sleep(0.3)
            return await super().system_one(state, questions, model)

    saved = rj._client, tenant_keys.typesafe_key_for, rj.WALL_S

    async def key(_aid):
        return "k"
    tenant_keys.typesafe_key_for = key
    try:
        fake = Slow((QUIET, 1.0), (QUIET, 1.0))
        rj._client = lambda k: fake
        t0 = time.monotonic()
        try:
            await rj.ask({}, "a", mode="test", timeout_s=0.05)
            raise AssertionError("no cap")
        except rj.GateError as e:
            assert "TimeoutError" in str(e), e
        assert time.monotonic() - t0 < 0.25
        try:
            await rj.ask({}, "a", mode="test", timeout_s=0)
            raise AssertionError("no deadline")
        except rj.GateError as e:
            assert str(e) == "deadline", e
        assert fake.calls == [], fake.calls
        assert rj.WALL_S == rj.TIMEOUT_S * (1 + rj.MAX_RETRIES) == 20.0
        assert (await rj.ask({}, "a")).intensity == 1.0
        rj.WALL_S = 0.05
        for kw in ({}, {"mode": "test", "timeout_s": 60.0}):
            try:
                await rj.ask({}, "a", **kw)
                raise AssertionError(f"no wall cap {kw}")
            except rj.GateError as e:
                assert "TimeoutError" in str(e), (kw, e)
    finally:
        rj._client, tenant_keys.typesafe_key_for, rj.WALL_S = saved

    async def hang():
        await asyncio.sleep(5)
    res = await full_ai_turn._capped(hang(), time.monotonic() + 0.05)
    assert res.text is None and res.writer is None, res
    assert [a["outcome"] for a in res.attempts] == ["timeout"], res.attempts


_harness.run()
