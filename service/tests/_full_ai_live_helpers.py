"""_full_ai_live_helpers — a scripted live Turn for the 04a / 05 / 06 live suites (facts, folds,
sell, scene). No case here: import after `_harness.bootstrap()`.

OF faked at `ax._make_client` (`_of_fixtures.FakeOF` or a subclass), `of_write_paced` unspaced,
the Router (`FakeJev`), the info Jev (`FakeInfoJev`) and the Writers' wire (`FakeWriterHTTP`,
the DeepSeek extract included) faked. Temp DB only; no paid call, no real OF call.
"""
from __future__ import annotations

import contextlib
import json
import os
from datetime import datetime, timedelta

from sqlalchemy import select, update

from _full_ai_fixtures import KIND, QUIET, FakeInfoJev, FakeJev, FakeWriterHTTP, _fake_jev, _msg, _seed
from _of_fixtures import FakeOF
import automation_executor as ax
from automations import full_ai_live
from automations.full_ai_config import DEFAULTS
from automations.welcome_chatter_for_info import _EXTRACT_FIELDS
from db.engine import get_session
from db.models import AccountAiConfig, AiDecision, AutomationRule, Fan

for _k, _v in (("NANOGPT_API_KEY", "test-nanogpt-house-key"), ("OPENROUTER_API_KEY", "test-openrouter-house-key"),
               ("DEEPSEEK_API_KEY", "test-deepseek-house-key")):
    os.environ.setdefault(_k, _v)
LINE = "ok:haha stop it. what are u doing later tonight"
NANO, DEEPSEEK = "nano-gpt.com", "api.deepseek.com"
HOSTS = (NANO, "openrouter.ai", "api.z.ai", DEEPSEEK)


def extract_says(**vals) -> str:
    """The faked DeepSeek extract's reply: wcfi's JSON with `vals` filled."""
    return "ok:" + json.dumps({**dict.fromkeys(_EXTRACT_FIELDS, ""), "likes_boobs": False,
                               "likes_ass": False, "recent_events": [], "her_claims": [], **vals})


@contextlib.contextmanager
def world(fake=None, jev=None, info: FakeInfoJev | None = None, writers: dict | None = None,
          heat=None, price=None):
    """`fake` (default FakeOF) behind the client factory, unspaced OF writes, faked Jevs and
    Writers; `heat` / `price` replace the Heat check's / the price Jev's client when given.
    Yields (fake OF, FakeJev, FakeInfoJev, FakeWriterHTTP)."""
    from automations import _heat_jev, _price_jev
    fake = fake or FakeOF()
    jevs = jev if isinstance(jev, FakeJev) else FakeJev(*([jev or (QUIET, 1.0)] * 6))
    info = info or FakeInfoJev()
    fw = FakeWriterHTTP({**dict.fromkeys(HOSTS, LINE), **(writers or {})})
    real_make, real_paced = ax._make_client, ax.of_write_paced

    async def unpaced(account_id, fn, **kw):
        return await real_paced(account_id, fn, **{**kw, "min_gap_s": 0.0, "pause_s": 0.0})

    ax._make_client, ax.of_write_paced = (lambda account_id: fake), unpaced
    real_price = _price_jev._client
    try:
        with fw.on(), _fake_jev(jevs, info):
            if heat is not None:            # `_fake_jev` restores the real client on exit
                _heat_jev._client = lambda key: heat
            if price is not None:
                _price_jev._client = lambda key: price
            yield fake, jevs, info, fw
    finally:
        ax._make_client, ax.of_write_paced = real_make, real_paced
        _price_jev._client = real_price


async def seed_live(aid: str, config: dict | None = None, *, exists: bool = False) -> int:
    """An account (`exists`: already seeded, e.g. `_full_ai_sell_helpers.A`) with an enabled
    `full_ai_chat` rule in Mode live; `config` = its checkpoint (over `DEFAULTS`)."""
    async with get_session() as s:
        if exists:
            r = AutomationRule(account_id=aid, name="Full AI Chat", kind=KIND, steps_json="{}", is_enabled=True,
                               trigger_json="{}")
            s.add(r)
            await s.flush()
            rid = r.id
    if not exists:
        rid = await _seed(aid, rule=True, gate=False)
    await set_config(aid, config)
    async with get_session() as s:
        await s.execute(update(AutomationRule).where(AutomationRule.id == rid).values(
            trigger_json=json.dumps({"every_seconds": 300, "mode": "live"})))
    return rid


async def set_config(aid: str, config: dict | None) -> None:
    """The account's stored checkpoint = `DEFAULTS` + `config` (None: leave it)."""
    if config is None:
        return
    blob = json.dumps({"checkpoint": {**DEFAULTS, **config}})
    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
        if row is None:
            s.add(AccountAiConfig(account_id=aid, full_ai_config_json=blob))
        else:
            row.full_ai_config_json = blob


async def fan_row(aid: str, fan: int, **cols) -> None:
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fan, **cols))


async def get_fan(aid: str, fan: int) -> Fan | None:
    async with get_session() as s:
        return await s.get(Fan, (aid, fan))


async def clear_pause(aid: str, fan: int) -> None:
    async with get_session() as s:
        await s.execute(update(Fan).where(Fan.account_id == aid, Fan.fan_id == fan)
                        .values(automation_paused_until=None))


async def live_rows(aid: str, fan: int | None = None) -> list[AiDecision]:
    async with get_session() as s:
        q = select(AiDecision).where(AiDecision.account_id == aid)
        if fan is not None:
            q = q.where(AiDecision.fan_id == fan)
        return list((await s.execute(q.order_by(AiDecision.id))).scalars())


async def dm_turn(aid: str, fan: int, mid: int, body: str, *, at: datetime | None = None, **world_kw):
    """His DM lands; one live job runs for it (`full_ai_live.run`, the job body). Returns
    (job result, fake OF, FakeJev, FakeInfoJev, FakeWriterHTTP). The 10 s cooldown is cleared
    after, so the next Turn runs."""
    await _msg(aid, fan, mid, "in", body, at or datetime.utcnow())
    payload = {"only_fan_ids": [fan], "anchor": mid, "_rule_id": await full_ai_live.live_rule(aid)}
    with world(**world_kw) as (fake, jevs, info, fw):
        res = await full_ai_live.run(aid, payload, run_id=0)
    await clear_pause(aid, fan)
    return res, fake, jevs, info, fw


async def her_reply(aid: str, fan: int, mid: int, body: str = "mm hey", at: datetime | None = None,
                    **kw) -> None:
    """An outbound of hers (another Lane or a human), so his next DM starts a new run."""
    await _msg(aid, fan, mid, "out", body, at or datetime.utcnow() - timedelta(seconds=40), **kw)


def reply(r: AiDecision) -> dict:
    return json.loads(r.reply_json or "{}")


__all__ = ["KIND", "QUIET", "FakeInfoJev", "FakeJev", "LINE", "NANO", "DEEPSEEK", "extract_says", "world",
           "seed_live", "set_config", "fan_row", "get_fan", "clear_pause", "live_rows", "dm_turn", "her_reply", "reply"]
