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
GIF_FITS = {**QUIET, "gif_fits": 0.9}      # a GIF suits the reply: the sticker block's gate
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
    """The Jev seams faked: the Router's (`fake`), the info Jev's (`info`, quiet by default) and
    the Heat check's (`QuietHeatJev`: level 0, never over), so no Turn reaches TypeSafe."""
    from automations import _heat_jev as hj
    from automations import _info_jev as ij
    saved = rj._client, ij._client, hj._client
    info = info or FakeInfoJev()
    rj._client = lambda key: fake  # type: ignore[assignment]
    ij._client = lambda key: info  # type: ignore[assignment]
    hj._client = lambda key: QuietHeatJev()  # type: ignore[assignment]
    try:
        yield fake
    finally:
        rj._client, ij._client, hj._client = saved  # type: ignore[assignment]


class QuietHeatJev:
    """`_heat_jev._client` for suites that do not test the Heat check: her level 0, never over."""

    async def system_one(self, state, questions, model=None):
        return SimpleNamespace(scores={"reply_level": SimpleNamespace(score=0.0, probabilities={0: 1.0})})


class FakeWriterHTTP:
    """The Writers' wire (`llm_client.httpx.AsyncClient`): each request answers by its host
    (`script`: host -> `ok:<text> | <HTTP status> | timeout | empty | park[:<how>]`, or a list of
    those taken one per request), recorded as {host, model, body, timeout}. `park[:<how>]` waits
    for `.go` (set on `on()`'s exit), then answers `<how>` (default `ok:ok`); `.parked` is set and
    `.parking` counts the posts waiting now. `on_post(record)` runs at each post; `.clients` counts
    clients made. No `llm_client.chat` patch, so its real error mapping runs."""

    def __init__(self, script: dict[str, str | list[str]], on_post=None):
        self.script = dict(script)
        self.requests: list[dict] = []
        self.on_post = on_post
        self.go, self.parked = asyncio.Event(), asyncio.Event()
        self.parking = self.clients = 0

    def __call__(self, *_a, timeout=None, **_k):
        self.clients += 1
        return _WriterConn(self, timeout)

    @contextlib.contextmanager
    def on(self):
        saved = llm_client.httpx.AsyncClient
        llm_client.httpx.AsyncClient = self  # type: ignore[assignment]
        try:
            yield self
        finally:
            self.go.set()
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
        rec = {"host": host, "model": (json or {}).get("model"), "body": json, "timeout": self.timeout}
        self.fake.requests.append(rec)
        if self.fake.on_post:
            self.fake.on_post(rec)
        how = self.fake.script[host]
        if isinstance(how, list):
            how = how.pop(0)
        if how.startswith("park"):
            self.fake.parking += 1
            self.fake.parked.set()
            try:
                await self.fake.go.wait()
            finally:
                self.fake.parking -= 1
            how = how.removeprefix("park").removeprefix(":") or "ok:ok"
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


@contextlib.contextmanager
def _shape_drop(reason: str = "banned"):
    """`shape_parts` drops every draft with `reason` (the reply chain's drop, e.g. a banned word)."""
    from automations import _reply_shape
    real = _reply_shape.shape_parts
    _reply_shape.shape_parts = lambda raw, ctx: _reply_shape.Shaped(parts=[], dropped_reason=reason, banned_hits=[])
    try:
        yield
    finally:
        _reply_shape.shape_parts = real


# ── Mode live (04a): the shared world of the live_* suites ─────────────────────────────────────
LIVE_LINE = "ok:haha stop it. what are u doing later tonight"
LIVE_HOSTS = ("nano-gpt.com", "openrouter.ai", "api.z.ai", "api.deepseek.com")


@contextlib.contextmanager
def live_world(jev=None, n: int = 4):
    """`_of_fixtures.FakeOF` behind `ax._make_client`, unspaced OF writes, Jev (`jev`, default QUIET
    intensity 1, `n` answers) and the Writers' wire faked. Yields `w`: `w.of` (`.sent` dicts),
    `w.made` (clients built), `w.purposes` (send purposes), `w.jev` (FakeJev)."""
    import automation_executor as ax
    from _of_fixtures import FakeOF
    w = SimpleNamespace(of=FakeOF(), made=[], purposes=[], jev=FakeJev(*([jev or (QUIET, 1.0)] * n)))
    real_make, real_paced = ax._make_client, ax.of_write_paced

    async def unpaced(account_id, fn, **kw):
        w.purposes.append(kw.get("send_purpose"))
        return await real_paced(account_id, fn, **{**kw, "min_gap_s": 0.0, "pause_s": 0.0})

    def make(account_id):
        w.made.append(account_id)
        return w.of
    ax._make_client, ax.of_write_paced = make, unpaced
    os.environ.setdefault("NANOGPT_API_KEY", "test-nanogpt-house-key")
    os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-house-key")
    try:
        with FakeWriterHTTP(dict.fromkeys(LIVE_HOSTS, LIVE_LINE)).on(), _fake_jev(w.jev):
            yield w
    finally:
        ax._make_client, ax.of_write_paced = real_make, real_paced


async def seed_live(aid: str, *, gate: bool = False, every_s: int = 300) -> int:
    """`_seed` with the rule in Mode live (`trigger_json.mode`); the rule id."""
    from sqlalchemy import update
    rid = await _seed(aid, rule=True, gate=gate)
    async with get_session() as s:
        await s.execute(update(AutomationRule).where(AutomationRule.id == rid).values(
            trigger_json=json.dumps({"every_seconds": every_s, "mode": "live"})))
    return rid


async def clear_pause(aid: str, fan: int) -> None:
    """The Fan's `automation_paused_until` gone (his cooldown ends)."""
    from sqlalchemy import update
    from db.models import Fan
    async with get_session() as s:
        await s.execute(update(Fan).where(Fan.account_id == aid, Fan.fan_id == fan)
                        .values(automation_paused_until=None))
