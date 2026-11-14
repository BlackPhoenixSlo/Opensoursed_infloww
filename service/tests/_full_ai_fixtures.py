"""_full_ai_fixtures — the Jev fake, seeding and one-run helpers that the Full
AI Chat inbound-path suites share (test_full_ai_shadow.py, test_full_ai_routes.py).

Import it after `_harness` (which binds the temp DB) and `_harness.bootstrap()`.
"""
from __future__ import annotations

import _harness  # noqa: F401 — binds the temp DB before any db import

import asyncio
import contextlib
import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

import webhook_dispatch as wd
from automation_executor import run_once
from automations import _router_jev as rj
from db.engine import get_session
from db.models import Account, AccountAiConfig, AiDecision, AutomationRule, AutomationRun, Message

os.environ["TYPESAFE_API_KEY"] = "test-key-not-real"
KIND = "full_ai_chat"
# The Router's one request (spec story 20): 11 Nouls + the `intensity` Score.
NOULS = {"promo", "says_under_18", "complains_now", "asks_if_ai", "stop", "price",
         "wants_content", "declines_buying", "says_yes_to_offer", "sexual_now", "gif_fits"}
QUIET = dict.fromkeys(NOULS, 0.05)
T0 = datetime.utcnow().replace(microsecond=0) - timedelta(hours=1)


class FakeJev:
    """The TypeSafe client: each `system_one` pops the next verdict
    ((answers, intensity) or an exception) and records what it was asked."""

    def __init__(self, *verdicts):
        self.verdicts = list(verdicts)
        self.calls: list[dict] = []

    async def system_one(self, state, questions, model=None):
        self.calls.append({"state": state, "questions": questions, "model": model})
        await asyncio.sleep(0.02)          # a measurable wall time
        v = self.verdicts.pop(0)
        if isinstance(v, Exception):
            raise v
        if isinstance(v, SimpleNamespace):      # a raw response, as Jev sent it
            return v
        answers, score = v
        return SimpleNamespace(
            model="jev-1.14.0",
            nouls={q: SimpleNamespace(noul=p) for q, p in answers.items()},
            scores={"intensity": SimpleNamespace(
                score=score, probabilities={0: .05, 1: .1, 2: .2, 3: .6, 4: .05})})


@contextlib.contextmanager
def _fake_jev(fake: FakeJev):
    saved = rj._client
    rj._client = lambda key: fake  # type: ignore[assignment]
    try:
        yield fake
    finally:
        rj._client = saved  # type: ignore[assignment]


# ── Seeding ───────────────────────────────────────────────────────────

async def _seed(aid: str, *, rule: bool, gate: bool) -> int | None:
    """An account; its `full_ai_chat` rule (on/off) and W7's gate."""
    async with get_session() as s:
        s.add(Account(id=aid))
        for kind in ("welcome_chatter_for_info", "reply_mass_funnel"):
            s.add(AutomationRule(account_id=aid, name=kind, kind=kind,
                                 trigger_json=json.dumps({"every_seconds": 60}),
                                 steps_json="{}", is_enabled=True))
        if gate:
            s.add(AccountAiConfig(account_id=aid, webhook_config_json=json.dumps({"enabled": True})))
        r = AutomationRule(account_id=aid, name="Full AI Chat", kind=KIND,
                           trigger_json=json.dumps({"every_seconds": 86400}),
                           steps_json="{}", is_enabled=rule)
        s.add(r)
        await s.flush()
        return r.id


async def _msg(aid: str, fan: int, mid: int, direction: str, body: str, at: datetime,
               **kw) -> None:
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=mid, direction=direction,
                      body=body, created_at=at, **kw))


async def _dm(aid: str, fan: int, mid: int, body: str, at: datetime) -> None:
    """His DM lands and reaches the hook."""
    await _msg(aid, fan, mid, "in", body, at)
    await wd.on_inbound_message(aid, fan, mid)


async def _rows(aid: str) -> list[AiDecision]:
    async with get_session() as s:
        return list((await s.execute(select(AiDecision).where(AiDecision.account_id == aid)
                                     .order_by(AiDecision.id))).scalars().all())


async def _run_row(run_id: int) -> AutomationRun:
    async with get_session() as s:
        return await s.get(AutomationRun, run_id)


async def _run(aid: str, fake: FakeJev) -> tuple[dict, dict]:
    """One run_once with Jev faked; the result and its persisted summary."""
    with _fake_jev(fake):
        res = await run_once(aid, KIND)
    run = await _run_row(res["run_id"]) if res.get("run_id") else None
    return res, (json.loads(run.stats_json) if run is not None and run.stats_json else {})


async def _one_turn(aid: str, fan: int, verdict, *, offer: bool = False) -> tuple[dict, AiDecision]:
    """His one DM (after her priced unbought message when `offer`), one run
    with Jev giving `verdict`: the run result and its one row."""
    await _seed(aid, rule=True, gate=False)
    if offer:
        await _msg(aid, fan, 7000, "out", "for you", T0 - timedelta(minutes=5), price_cents=1500,
                   is_paid=False, automation_kind="reply_mass_funnel")
    await _dm(aid, fan, 7001, "hey you", T0)
    res, _stats = await _run(aid, FakeJev(verdict))
    (r,) = await _rows(aid)
    return res, r


def _raw(nouls: dict, scores: dict) -> SimpleNamespace:
    return SimpleNamespace(model="jev-1.14.0", nouls={q: SimpleNamespace(noul=p) for q, p in nouls.items()},
                           scores=scores)
