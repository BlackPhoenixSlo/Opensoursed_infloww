#!/usr/bin/env python3
"""_full_ai_sell_helpers — shared setup for the Full AI selling Test chat suites (phase 03b).

Imported by test_full_ai_sell_chat.py (ticket 42) and test_full_ai_settle_chat.py (44); defines no
`case_*`. Importing it bootstraps the temp DB, seeds the two-Agency world plus one row in every
invariant table (content_offers included), and logs A's owner in, once per process. Every Turn runs
inside `_guarded`: full-row snapshots of messages, transactions, vault_sends, content_offers,
fan_lease and fans equal before and after, no `automation_runs` row, every send path plus
`ownership.stamp_media_owned` patched to raise and never hit.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import delete, func, select, text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from _full_ai_fixtures import QUIET, FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
import automation_executor as ax  # noqa: E402
import client_pool  # noqa: E402
import dm_rate  # noqa: E402
import fan_lease  # noqa: E402
import of_client  # noqa: E402
import ownership  # noqa: E402
import tenant_keys  # noqa: E402
import vault_jev_rules  # noqa: E402
from automations import _price_jev, full_ai_sell, full_ai_test  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    AccountAiConfig, AiDecision, AutomationRun, CatalogItem, ContentOffer, Fan, FanLease, Message, Transaction, VaultItem, VaultSend,
)

os.environ.setdefault("NANOGPT_API_KEY", "test-nanogpt-house-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-house-key")

IDS = fx.seed_two_agencies()
A = IDS["creator_a"]
OWNER_A = fx.login_owner("agency_a_owner")
NANO, OPENROUTER = "nano-gpt.com", "openrouter.ai"
TURN, CONFIG = "/admin/full-ai/test/turn", "/admin/full-ai/config"
PICS = "send me pics"
OFFER_COLS = ("offer_price_cents", "offer_list_cents", "offer_media_json", "offer_item_ref",
              "offer_message_id", "outcome", "outcome_at", "join_src")
T0 = datetime(2026, 7, 1)


def _db(fn):
    return asyncio.run(fn())


async def _seed_world() -> None:
    """A's (fake) NanoGPT key, a cap far above any test spend, and one existing row in every table
    the invariant snapshots (content_offers' row hangs off a catalog item)."""
    t = datetime(2026, 11, 1, 12, 0)
    await tenant_keys.set_keys(IDS["agency_a_owner"], {"nanogpt": "test-nanogpt-agency-key",
                                                      "openrouter": "test-openrouter-agency-key"})
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=A, daily_cost_cap_cents=1_000_000))
        s.add(Fan(account_id=A, fan_id=5, real_name="Sam"))
        s.add(Message(account_id=A, fan_id=5, message_id=1, direction="in", body="hi", created_at=t))
        s.add(Transaction(account_id=A, fan_id=5, kind="tip", amount_cents=500, occurred_at=t))
        s.add(VaultSend(account_id=A, fan_id=5, media_id=9, price_cents=0))
        s.add(FanLease(account_id=A, fan_id=5, automation_kind="autoreply",
                       leased_until=t + timedelta(minutes=5)))
        item = CatalogItem(account_id=A)
        s.add(item)
        await s.flush()
        s.add(ContentOffer(account_id=A, fan_id=5, item_id=item.id, price_cents=1000))


_db(_seed_world)


# ── Invariants (test_full_ai_test_chat.py `_guarded` + content_offers + the owned stamp) ──

_SEND_PATHS = ((ax, "_make_client"), (of_client.OFClient, "request"),
               (of_client.OFClient, "_http_call"), (of_client.OFClient, "_proxy_retry"),
               (fan_lease, "acquire_fan_lease"), (fan_lease, "start_fan_cooldown"),
               (ax, "acquire_fan_lease"), (ax, "start_fan_cooldown"), (dm_rate, "turn"),
               (ownership, "stamp_media_owned"), (client_pool, "get"))
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
    assert before["content_offers"], "the content_offers snapshot must hold a row"


@contextlib.contextmanager
def _picks():
    """`full_ai_sell.pick` spied: the list of its results, one per call."""
    real, got = full_ai_sell.pick, []

    def spy(*a, **k):
        got.append(real(*a, **k))
        return got[-1]
    full_ai_sell.pick = spy
    try:
        yield got
    finally:
        full_ai_sell.pick = real


def _post(body: dict, script: dict | str, *, jev=None):
    """One test turn under the invariants: (response, Writer fake, Pick results)."""
    script = {NANO: script} if isinstance(script, str) else script
    fake_w = FakeWriterHTTP({NANO: "ok:hii", OPENROUTER: "ok:hii", **script})
    with _guarded(), _picks() as picks, fake_w.on(), _fake_jev(FakeJev(jev or (_hot(wants_content=0.9), 1.0))):
        r = OWNER_A.post(TURN, json=body)
    assert r.status_code == 200, r.text
    return r, fake_w, picks


def _hot(**qs) -> dict[str, float]:
    return {**QUIET, **qs}


def _body(pair: str, text: str = PICS, *, side: str = "draft", n: int = 1) -> dict:
    return {"account_id": A, "pair": pair, "side": side, "n": n, "text": text}


def _rows(pair: str) -> list[AiDecision]:
    async def q():
        async with get_session() as s:
            return list((await s.execute(select(AiDecision).where(
                AiDecision.account_id == A, AiDecision.fan_id == full_ai_test.test_fan_id(pair))
                .order_by(AiDecision.id))).scalars().all())
    return _db(q)


def _reply(row: AiDecision) -> dict:
    return json.loads(row.reply_json)


def _system(fw: FakeWriterHTTP, i: int = 0) -> str:
    return fw.requests[i]["body"]["messages"][0]["content"]


def _no_offer(row: AiDecision) -> None:
    assert all(getattr(row, c) is None for c in OFFER_COLS), {c: getattr(row, c) for c in OFFER_COLS}


def _ppvs(parts: list[dict]) -> list[int]:
    return [i for i, p in enumerate(parts) if "ppv" in p]


# ── Config + vault ────────────────────────────────────────────────────

def _put_draft(draft: dict) -> int:
    rev = OWNER_A.get(CONFIG, params={"account_id": A}).json()["rev"]
    r = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": draft, "rev": rev})
    assert r.status_code == 200, r.text
    return r.json()["rev"]


@contextlib.contextmanager
def _sell_draft(**cfg):
    """A's draft side sells (put through the config API), `cfg` over it; the checkpoint keeps
    DEFAULTS (sell off)."""
    _put_draft({**DEFAULTS, "sell_on": True, **cfg})
    try:
        yield
    finally:
        _put_draft(dict(DEFAULTS))


# test_full_ai_sell.py's DRESSED still: sfw, solo, every region covered, priced by its Jev lane alone.
DRESSED = {"clothing_state": "dressed", "acts": ["posing"], "penetration": "none", "explicitness": "sfw",
           "underwear_visible": True, "vulva_vis": "covered", "breasts_vis": "covered",
           "anus_vis": "not_in_frame", "over_vulva": "jeans", "over_breasts": "t-shirt",
           "people_count": 1, "partner_visible": False, "description": "a mirror selfie in jeans"}


def _jev(lane5: str, tags: dict | None = None) -> dict:
    return {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": lane5, "state": {}, "kind": "photo",
            "breasts_bare": "n", "crotch_bare": "n", "penetration": "n", "tags": dict(tags or {})}


@contextlib.contextmanager
def _vault(items: dict[int, str], *, tags: dict | None = None):
    """A's vault for the block: media id -> Jev lane (`review` = unpriced), then removed; `tags`
    are every item's Jev tags (03d: toy photos for the Bundle)."""
    async def add():
        async with get_session() as s:
            for mid, lane in items.items():
                s.add(VaultItem(account_id=A, media_id=mid, kind="photo",
                                created_at=T0 + timedelta(days=mid), tags="[]",
                                describe_status="described", of_folder_ids="[]",
                                ai_fields_json=json.dumps({**DRESSED, vault_jev_rules.JEV_KEY: _jev(lane, tags)})))

    async def drop():
        async with get_session() as s:
            await s.execute(delete(VaultItem).where(VaultItem.account_id == A))
    _db(add)
    try:
        yield
    finally:
        _db(drop)


class FakePriceJev:
    """`_price_jev._client` faked (03d): one `price` score per call, each call's state recorded."""

    def __init__(self, score):
        self.score, self.calls = score, []

    async def system_one(self, state, questions, model=None):
        self.calls.append(state)
        return SimpleNamespace(scores={"price": SimpleNamespace(score=self.score, probabilities={1: .5, 2: .5})})


@contextlib.contextmanager
def _price(fake):
    real = _price_jev._client
    _price_jev._client = lambda key: fake
    try:
        yield fake
    finally:
        _price_jev._client = real


PRICED = {101: "$10", 202: "$50"}
