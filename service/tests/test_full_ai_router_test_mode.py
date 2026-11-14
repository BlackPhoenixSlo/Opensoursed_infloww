#!/usr/bin/env python3
"""test_full_ai_router_test_mode — Shadow's Jev request stays byte-frozen while the Router
gains its test-Mode questions (03b ticket 43; spec story 66).

A Shadow Turn through the inbound path (`webhook_dispatch.on_inbound_message` then
`automation_executor.run_once`), Jev faked at `_router_jev._client` (`FakeJev`), on the
_harness temp DB.

  case_shadow_request_golden   the recorded Jev request (state + questions + model,
                               serialized) equals the golden bytes, and the row's
                               `question_version` is the pre-03b `QUESTION_VERSION`

The golden (`test_full_ai_router_test_mode.shadow_request.golden.json`) was captured from
the unchanged Router module at 10481c760, before ticket 43 edited `_router_jev.py`. Never
regenerate it: a diff here means Shadow's request changed, which is a 04a / 05 step after the
owner OKs the new questions' wording.

Run: ./venv/bin/python service/tests/test_full_ai_router_test_mode.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from _full_ai_fixtures import KIND, QUIET, T0, FakeJev, _dm, _fake_jev, _msg, _rows, _seed  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Transaction  # noqa: E402

GOLDEN = Path(__file__).with_name("test_full_ai_router_test_mode.shadow_request.golden.json")
# `_router_jev.QUESTION_VERSION` at 10481c760 (Phase 01 + `gif_fits`), before ticket 43.
PRE_03B_QUESTION_VERSION = "b3202b420ab0"


def _request_bytes(call: dict) -> bytes:
    """One recorded Jev request as bytes: the state, every question in request order
    (`model_dump` carries the SDK type: noul / score / choice) and the model pin."""
    return json.dumps(
        {"model": call["model"], "state": call["state"],
         "questions": {qid: q.model_dump(mode="json") for qid, q in call["questions"].items()}},
        ensure_ascii=False, indent=1).encode() + b"\n"


async def _shadow_call(aid: str, fan: int) -> dict:
    """A thread with every state field filled (lines, her priced unbought message, his tip),
    his two-DM Turn, one Shadow run: the one Jev request it made."""
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
    assert r.question_version == PRE_03B_QUESTION_VERSION, r.question_version


_harness.run()
