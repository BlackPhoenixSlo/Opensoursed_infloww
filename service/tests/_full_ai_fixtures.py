"""_full_ai_fixtures — the Jev fake, the Writer HTTP fake, seeding and one-run
helpers that the Full AI Chat suites share (test_full_ai_shadow.py,
test_full_ai_routes.py, test_full_ai_test_chat.py).

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

import httpx

import llm_client
import webhook_dispatch as wd
from automation_executor import run_once
from automations import _router_jev as rj
from automations import full_ai_config

# The sext scene (config `sext_scene`, default on) changes test-Mode Turns. The suites written
# before it pin the flag-off behaviour (= the old one) through this one switch; the scene suites
# turn it on in the config they pass or store (test_full_ai_scene*.py).
full_ai_config.DEFAULTS["sext_scene"] = False
from db.engine import get_session
from db.models import Account, AccountAiConfig, AiDecision, AutomationRule, AutomationRun, Message

os.environ["TYPESAFE_API_KEY"] = "test-key-not-real"
KIND = "full_ai_chat"
# The Router's one request (spec story 20): 11 Nouls + the `intensity` Score.
NOULS = {"promo", "says_under_18", "complains_now", "asks_if_ai", "stop", "price",
         "wants_content", "declines_buying", "says_yes_to_offer", "sexual_now", "gif_fits"}
QUIET = dict.fromkeys(NOULS, 0.05)
# A quiet test-Mode `answers` (03b), sext scene off; `QUIET_SCENE` with config `sext_scene` on.
QUIET_TEST = {**QUIET, **dict.fromkeys((q for q in rj.TEST_NOULS if q not in rj.SCENE), 0.05)}
QUIET_SCENE = {**QUIET, **dict.fromkeys(rj.TEST_NOULS, 0.05)}
T0 = datetime.utcnow().replace(microsecond=0) - timedelta(hours=1)


class FakeJev:
    """The TypeSafe client: each `system_one` pops the next verdict
    ((answers, intensity), (answers, intensity, choices) or an exception) and records what it was
    asked. A test-Mode request (03b) also gets its `TEST_NOULS` (from `answers`, else 0.05) and its
    `TEST_CHOICES`: `choices` maps a Choice id to a label (P 0.9) or a label -> P map; an unnamed
    Choice answers its `CHOICE_DEFAULT` (anything / any). Shadow's request gets neither."""

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
        answers, score, *rest = v
        answers = {**{q: 0.05 for q in rj.TEST_NOULS if q in questions}, **answers}
        res = SimpleNamespace(
            model="jev-1.14.0",
            nouls={q: SimpleNamespace(noul=p) for q, p in answers.items()},
            scores={"intensity": SimpleNamespace(
                score=score, probabilities={0: .05, 1: .1, 2: .2, 3: .6, 4: .05})})
        asked = [q for q in rj.TEST_CHOICES if q in questions]
        if asked:
            given = rest[0] if rest else {}
            res.choices = {}
            for q in asked:
                p = given.get(q, rj.CHOICE_DEFAULT[q])
                p = {p: 0.9} if isinstance(p, str) else dict(p)
                res.choices[q] = SimpleNamespace(choice=max(p, key=p.get), probabilities=p)
        return res


class FakeInfoJev:
    """The info Jev's TypeSafe client (`_info_jev._client`): each `system_one` pops the next
    verdict ((stated, pick): `stated` field -> P(yes), the rest 0.05; `pick` the Choice's label,
    "none" for none; or an exception) and records what it was asked. With no verdict left it
    answers quiet: nothing stated, `none`."""

    def __init__(self, *verdicts):
        self.verdicts = list(verdicts)
        self.calls: list[dict] = []

    async def system_one(self, state, questions, model=None):
        self.calls.append({"state": state, "questions": questions, "model": model})
        v = self.verdicts.pop(0) if self.verdicts else ({}, "none")
        if isinstance(v, Exception):
            raise v
        stated, pick = v
        nouls = {q: SimpleNamespace(noul=stated.get(q.removeprefix("stated_"), 0.05))
                 for q in questions if q.startswith("stated_")}
        return SimpleNamespace(model="jev-1.14.0", nouls=nouls, choices={
            "next_question": SimpleNamespace(choice=pick, probabilities={pick: 0.9})})


@contextlib.contextmanager
def _fake_jev(fake: FakeJev, info: FakeInfoJev | None = None):
    """Both Jev seams faked: the Router's (`fake`) and the info Jev's (`info`, quiet by default),
    so no Turn reaches TypeSafe."""
    from automations import _info_jev as ij
    saved = rj._client, ij._client
    info = info or FakeInfoJev()
    rj._client = lambda key: fake  # type: ignore[assignment]
    ij._client = lambda key: info  # type: ignore[assignment]
    try:
        yield fake
    finally:
        rj._client, ij._client = saved  # type: ignore[assignment]


class FakeWriterHTTP:
    """The Writers' wire (`llm_client.httpx.AsyncClient`): each request answers by its host
    (`script`: host -> `ok:<text> | <HTTP status> | timeout | empty`, or a list of those taken
    one per request), recorded as
    {host, model, body, timeout}. No `llm_client.chat` patch, so its real error mapping runs."""

    def __init__(self, script: dict[str, str | list[str]]):
        self.script = dict(script)
        self.requests: list[dict] = []

    def __call__(self, *_a, timeout=None, **_k):
        return _WriterConn(self, timeout)

    @contextlib.contextmanager
    def on(self):
        saved = llm_client.httpx.AsyncClient
        llm_client.httpx.AsyncClient = self  # type: ignore[assignment]
        try:
            yield self
        finally:
            llm_client.httpx.AsyncClient = saved  # type: ignore[assignment]


class _WriterResp:
    def __init__(self, url: str, status: int, data: dict):
        self.status_code, self._data, self._url = status, data, url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "fake", request=httpx.Request("POST", self._url),
                response=httpx.Response(self.status_code, text="busy"))

    def json(self):
        return self._data


class _WriterConn:
    def __init__(self, fake: FakeWriterHTTP, timeout):
        self.fake, self.timeout = fake, timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        host = httpx.URL(str(url)).host
        self.fake.requests.append({"host": host, "model": (json or {}).get("model"),
                                   "body": json, "timeout": self.timeout})
        how = self.fake.script[host]
        if isinstance(how, list):
            how = how.pop(0)
        if how == "timeout":
            raise httpx.ReadTimeout("timed out")
        if how.isdigit():
            return _WriterResp(str(url), int(how), {})
        text = "" if how == "empty" else how.removeprefix("ok:")
        return _WriterResp(str(url), 200, {
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


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
