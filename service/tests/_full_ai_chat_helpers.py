#!/usr/bin/env python3
"""_full_ai_chat_helpers — shared setup for the Full AI Test chat suites (phase 03a).

Imported by test_full_ai_test_chat.py (tickets 32/33/36), test_full_ai_routes_chat.py (34),
test_full_ai_info_chat.py (35), test_full_ai_config_chat.py (37), test_full_ai_choices_chat.py (43)
and test_full_ai_applied_draft_chat.py (57; Do mode's OF fake `_OF` / `_of_fake`); defines no `case_*`.
Importing it bootstraps the temp DB, seeds the two-Agency world and logs both owners in, once per
process. A test file imports `_harness` first, then this module, before any db import.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import func, select, text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from _full_ai_fixtures import QUIET, FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
import automation_executor as ax  # noqa: E402
import client_pool  # noqa: E402
import dm_rate  # noqa: E402
import fan_lease  # noqa: E402
import of_client  # noqa: E402
import ownership  # noqa: E402
import tenant_keys  # noqa: E402
from automations import _reply_shape, _typos, full_ai_test  # noqa: E402
from automations._nonnative import NONNATIVE_OUTPUTS  # noqa: E402
from automations._outbound import finalize_draft  # noqa: E402
from automations._prompt_rules import STYLE_MAX_BUBBLES  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    AccountAiConfig, AiDecision, AutomationRun, CatalogItem, ContentOffer, Fan, FanLease, Message,
    Transaction, VaultSend,
)

os.environ.setdefault("NANOGPT_API_KEY", "test-nanogpt-house-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-house-key")

IDS = fx.seed_two_agencies()
A, B = IDS["creator_a"], IDS["creator_b"]
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
NANO = "nano-gpt.com"
TURN = "/admin/full-ai/test/turn"
KEYS = {"row_id", "route", "heat", "route_row", "dropped", "parts", "writer", "attempts", "wait_s",
        "status", "fan_info", "offer"}
REPLY_KEYS = {"parts", "attempts", "floor_reason", "dropped_reason", "leak", "side", "config_rev",
              "wait_s", "turn_ms", "fan_info", "asked", "typo_state", "info_error"}


def _db(fn):
    return asyncio.run(fn())


async def _seed_world() -> None:
    """Each Agency's (fake) NanoGPT key, per-account caps far above any test spend, and one existing row in every table the
    invariant snapshots, so an UPDATE would show as well as an INSERT."""
    t = datetime(2026, 11, 1, 12, 0)
    for owner in ("agency_a_owner", "agency_b_owner"):   # fake keys: the Writer wire is faked
        await tenant_keys.set_keys(IDS[owner], {"nanogpt": "test-nanogpt-agency-key"})
    async with get_session() as s:
        for aid in (A, B):
            s.add(AccountAiConfig(account_id=aid, daily_cost_cap_cents=1_000_000))
        s.add(Fan(account_id=A, fan_id=5, real_name="Sam"))
        s.add(Message(account_id=A, fan_id=5, message_id=1, direction="in", body="hi", created_at=t))
        s.add(Transaction(account_id=A, fan_id=5, kind="tip", amount_cents=500, occurred_at=t))
        s.add(VaultSend(account_id=A, fan_id=5, media_id=9, price_cents=0))
        s.add(FanLease(account_id=A, fan_id=5, automation_kind="autoreply",
                       leased_until=t + timedelta(minutes=5)))
        item = CatalogItem(account_id=A)       # content_offers' row hangs off a catalog item
        s.add(item)
        await s.flush()
        s.add(ContentOffer(account_id=A, fan_id=5, item_id=item.id, price_cents=1000))


_db(_seed_world)


# ── Invariants ────────────────────────────────────────────────────────

# Every send path at each binding a sender looks it up by (test_full_ai_shadow.py `_SEND_PATHS`),
# plus the DM rate test skips and the Sell executor's ownership stamp (03b).
_SEND_PATHS = ((ax, "_make_client"), (of_client.OFClient, "request"),
               (of_client.OFClient, "_http_call"), (of_client.OFClient, "_proxy_retry"),
               (fan_lease, "acquire_fan_lease"), (fan_lease, "start_fan_cooldown"),
               (ax, "acquire_fan_lease"), (ax, "start_fan_cooldown"), (dm_rate, "turn"),
               (ownership, "stamp_media_owned"))
_SNAPSHOT = ("messages", "transactions", "vault_sends", "content_offers", "fan_lease", "fans")


class SendReached(Exception):
    pass


async def _snapshot() -> dict[str, list]:
    out = {}
    async with get_session() as s:
        for t in _SNAPSHOT:
            out[t] = [tuple(r) for r in (await s.execute(text(f"SELECT * FROM {t} ORDER BY 1, 2"))).all()]
        out["automation_runs"] = (await s.execute(select(func.count()).select_from(AutomationRun))).scalar_one()
    return out


@contextlib.contextmanager
def _guarded():
    """Every send path records its hit and raises; the hit list is the proof."""
    hits: list[str] = []
    saved = [(o, n, getattr(o, n)) for o, n in _SEND_PATHS]
    for o, n, real in saved:
        name = f"{o.__name__}.{n}"

        def hit(*_a, _name=name, **_k):
            hits.append(_name)
            raise SendReached(_name)

        async def ahit(*a, _hit=hit, **k):
            _hit(*a, **k)
        setattr(o, n, ahit if inspect.iscoroutinefunction(real) else hit)
    before = _db(_snapshot)
    try:
        yield hits
    finally:
        for o, n, real in saved:
            setattr(o, n, real)
    after = _db(_snapshot)
    assert hits == [], hits
    assert after == before, {t: (before[t], after[t]) for t in before if before[t] != after[t]}
    assert after["automation_runs"] == 0, after["automation_runs"]


def _post(client, body: dict, writer: str, *, jev=(QUIET, 1.0)):
    """One test turn under the invariants: (response, Writer fake, Jev fake, wall seconds)."""
    fake_w, fake_j = FakeWriterHTTP({NANO: writer}), FakeJev(jev)
    with _guarded(), fake_w.on(), _fake_jev(fake_j):
        t0 = time.perf_counter()
        r = client.post(TURN, json=body)
        wall = time.perf_counter() - t0
    return r, fake_w, fake_j, wall


def _body(pair: str, n: int = 1, text: str = "hey you, how was your day", *, side: str = "checkpoint",
          aid: str = A) -> dict:
    return {"account_id": aid, "pair": pair, "side": side, "n": n, "text": text}


def _rows(aid: str, pair: str) -> list[AiDecision]:
    async def q():
        async with get_session() as s:
            return list((await s.execute(select(AiDecision).where(
                AiDecision.account_id == aid, AiDecision.fan_id == full_ai_test.test_fan_id(pair))
                .order_by(AiDecision.id))).scalars().all())
    return _db(q)


def _reply(row: AiDecision) -> dict:
    return json.loads(row.reply_json)


def _direct(raw: str, fid: int, his: str, *, girl: bool) -> list[dict]:
    """The shared chain called directly with the context `run_turn` must build for a first Turn."""
    async def go():
        t, _ = await finalize_draft(raw, account_id=A, fan_id=fid, purpose="full_ai_writer")
        mb = STYLE_MAX_BUBBLES if girl else 2
        shaped = _reply_shape.shape_parts(t, _reply_shape.ShapeCtx(
            seed_id=fid, max_bubbles=mb, max_chars=600, lang=None, echo_of=his, style_on=girl,
            recent_out=[], allow_empty=False, banned_words=[], banned_mode="mask",
            nonnative_on=girl, spacing_on=girl, name_protect=[]))
        parts = shaped.parts
        if girl:
            parts = await _typos.apply_typo_throttle(A, fid, parts, random.Random(f"{fid}:{t}"),
                                                     protect=list(NONNATIVE_OUTPUTS), max_bubbles=mb,
                                                     state={})
        return [{"text": p} for p in parts]
    return _db(go)


def _store_config(aid: str, stored: dict) -> None:
    async def go():
        async with get_session() as s:
            (await s.get(AccountAiConfig, aid)).full_ai_config_json = json.dumps(stored)
    _db(go)



# ── Writer chain hosts and fakes (ticket 33; the info and config suites use them too) ──

OPENROUTER, ZAI, DEEPSEEK = "openrouter.ai", "api.z.ai", "api.deepseek.com"
OK_LINE = "ok:haha stop it, what are u doing later tonight"


@contextlib.contextmanager
def _agency_keys(values: dict):
    """Creator A's Agency keys set for the block (fake values: the wire is faked), then restored."""
    owner = IDS["agency_a_owner"]
    before = {p: _db(lambda p=p: tenant_keys.get_key(owner, p)) for p in values}
    _db(lambda: tenant_keys.set_keys(owner, values))
    try:
        yield
    finally:
        _db(lambda: tenant_keys.set_keys(owner, before))


_CHAIN_KEYS = {"openrouter": "test-openrouter-agency-key", "zai": "test-zai-agency-key",
               "deepseek": "test-deepseek-agency-key"}


def _chain_post(body: dict, script: dict, *, jev=(QUIET, 1.0), fake_w=None, fake_j=None):
    """One test turn under the invariants with every Writer host scripted (a host left out
    answers OK_LINE): (response, Writer fake)."""
    full = {NANO: OK_LINE, OPENROUTER: OK_LINE, ZAI: OK_LINE, DEEPSEEK: OK_LINE, **script}
    fake_w = fake_w or FakeWriterHTTP(full)
    with _agency_keys(_CHAIN_KEYS), _guarded(), fake_w.on(), _fake_jev(fake_j or FakeJev(jev)):
        r = OWNER_A.post(TURN, json=body)
    assert r.status_code == 200, r.text
    return r, fake_w



class _Clock:
    """The Turn's monotonic clock, advanced only by the slow fakes below."""

    def __init__(self):
        self.t = 1000.0

    def now(self) -> float:
        return self.t


class _SlowJev(FakeJev):
    def __init__(self, clock: _Clock, took_s: float, *verdicts):
        super().__init__(*verdicts)
        self.clock, self.took_s = clock, took_s

    async def system_one(self, state, questions, model=None):
        self.clock.t += self.took_s
        return await super().system_one(state, questions, model)


# The GIF the Routes and config suites' GIF Turns name (ticket 34).
_GIF_TAG = "laugh"


# ── OF for Do mode (03c: test_full_ai_assistant_config.py, test_full_ai_applied_draft_chat.py) ──

class _OF:
    """client_pool.get's recording fake: `get_lists` → [] is the one allowed read; anything else
    (any send) raises and is recorded (Do mode's `_read_lists` swallows exceptions: the record is the proof)."""

    def __init__(self):
        self.calls: list[str] = []

    def get(self, account_id):
        self.calls.append(f"get:{account_id}")
        return self

    def get_lists(self, **kw):
        self.calls.append("get_lists")
        return []

    def __getattr__(self, name):
        def refuse(*_a, **_k):
            self.calls.append(name)
            raise AssertionError(f"OF {name} reached")
        return refuse


@contextlib.contextmanager
def _of_fake():
    fake, real = _OF(), client_pool.get
    client_pool.get = fake.get
    try:
        yield fake
    finally:
        client_pool.get = real
