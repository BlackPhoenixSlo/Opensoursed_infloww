#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import inspect  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import full_ai_revenue as rev  # noqa: E402
from automations.full_ai_decide import arm_of  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AiDecision, Message, Transaction  # noqa: E402

IDS = fx.seed_two_agencies()
T0 = datetime(2026, 10, 1, 12, 0, 0)
D = timedelta(days=1)
S = timedelta(seconds=1)
EMPTY = {"fans": 0, "in_window": 0, "complete": 0, "cents": 0, "cents_per_fan": None}


def _arm(fans, in_window, complete, cents, per):
    return {"fans": fans, "in_window": in_window, "complete": complete, "cents": cents, "cents_per_fan": per}



def case_readout_table():
    none = rev.readout(None, [(1, T0, "treatment")], [(1, T0, 500)], [("sell_now", 900, 1, "bought")],
                       T0 + 30 * D)
    assert none == {"live_since": None, "note": rev.NO_HOLDOUT, "arms": {}, "routes": []}, none
    now = T0 + 20 * D
    cohort = [(1, T0, "holdout"),
              (2, T0 + 6 * D, "treatment"),
              (3, T0 + 7 * D, "treatment"),
              (4, T0 + 2 * D, "treatment")]
    txs = [(1, T0 + D, 900), (2, T0 + 7 * D, 300), (3, T0 + 8 * D, 99_999)]
    got = rev.readout(T0, cohort, txs, [], now)
    assert got["live_since"] == "2026-10-01T12:00:00Z" and got["note"] == "no holdout: not a comparison", got
    assert got["arms"] == {"all": _arm(4, 1, 3, 1200, 400)}, got["arms"]
    split = rev.readout(T0, cohort, txs, [], now, holdout=True)
    assert split["note"] == rev.HOLDOUT, split
    assert split["arms"] == {"treatment": _arm(3, 1, 2, 300, 150), "holdout": _arm(1, 0, 1, 900, 900)}, split
    young = rev.readout(T0, [(3, T0 + 7 * D, "treatment")], txs, [], now)
    assert young["arms"] == {"all": _arm(1, 1, 0, 0, None)}, young
    assert rev.readout(T0, [], [], [], now)["arms"] == {"all": EMPTY}
    assert rev.readout(T0, [], [], [], now, holdout=True)["arms"] == {"treatment": EMPTY, "holdout": EMPTY}


def case_money_rules():
    e = T0
    txs = [(1, e - S, 1), (1, e + 14 * D, 2),
           (1, e + 13 * D, 1000),
           (1, e, 500),
           (2, e + D, 7)]
    got = rev.readout(T0, [(1, e, "treatment")], txs, [], T0 + 30 * D)
    assert got["arms"]["all"] == _arm(1, 0, 1, 1500, 1500), got


def case_routes():
    offers = [("sell_now", 1500, 11, "bought"), ("sell_now", 2000, 12, "declined"), ("sell_now", 1800, 13, None),
              ("sell_now", 1700, None, None),
              ("sell_now", 1600, None, "bought"),
              ("make_right", 0, 14, "bought"),
              ("tease", None, 15, None),
              ("chat", 900, 16, "bought")]
    got = rev.readout(T0, [], [], offers, T0)["routes"]
    assert got == [{"route": "chat", "offers": 1, "bought": 1, "cents": 900},
                   {"route": "sell_now", "offers": 3, "bought": 1, "cents": 1500}], got



_KEY = iter(range(1, 10**9))


async def _add(*rows) -> None:
    async with get_session() as s:
        s.add_all(rows)


def _dec(aid, fan, at, *, mode="live", route="chat", price=None, msg=None, outcome=None, arm=None):
    return AiDecision(account_id=aid, fan_id=fan, mode=mode, trigger_kind="inbound", trigger_key=str(next(_KEY)),
                      route=route, heat=2, route_row="otherwise", question_version="v", status="sent",
                      created_at=at, arm=arm, offer_price_cents=price, offer_message_id=msg, outcome=outcome)


def _msg(aid, fan, at, direction="in"):
    return Message(account_id=aid, fan_id=fan, message_id=next(_KEY), direction=direction, body="hi", created_at=at)


def _tx(aid, fan, at, cents, kind="tip", status="cleared"):
    return Transaction(account_id=aid, fan_id=fan, kind=kind, amount_cents=cents, occurred_at=at, status=status)


async def case_load_derives_enrolment():
    aid = "fa_rev_load"
    await _add(Account(id=aid))
    await _add(_dec(aid, 1, T0, mode="shadow"), _msg(aid, 1, T0 + D))
    assert await rev.load(aid) == (None, [], [], []), "Shadow rows set no live_since"
    assert (await rev.revenue(aid, now=T0 + 30 * D))["arms"] == {}
    live = T0 + 2 * D
    await _add(_dec(aid, 1, live),
               _msg(aid, 1, live + D),
               _msg(aid, 2, live + 2 * D),
               _msg(aid, 3, live + D, direction="out"))
    live_at, cohort, _txs, _offers = await rev.load(aid)
    assert live_at == live, live_at
    assert sorted(cohort) == [(1, live + D, arm_of(aid, 1)), (2, live + 2 * D, arm_of(aid, 2))], cohort


async def case_arm_split_is_arm_of_for_200_fans():
    aid = "fa_rev_arms"
    flip = {"treatment": "holdout", "holdout": "treatment"}
    await _add(Account(id=aid))
    await _add(*[_dec(aid, f, T0 + f * S, arm=flip[arm_of(aid, f)]) for f in range(1000, 1200)],
               *[_msg(aid, f, T0 + D) for f in range(1000, 1200)])
    live_at, cohort, txs, offers = await rev.load(aid)
    assert {f: a for f, _at, a in cohort} == {f: arm_of(aid, f) for f in range(1000, 1200)}
    got = rev.readout(live_at, cohort, txs, offers, T0 + 30 * D, holdout=True)["arms"]
    n_hold = sum(arm_of(aid, f) == "holdout" for f in range(1000, 1200))
    assert 0 < n_hold < 200 and (got["holdout"]["fans"], got["treatment"]["fans"]) == (n_hold, 200 - n_hold), got
    assert ".arm" not in inspect.getsource(rev).replace(".arm_of", ""), "no stored Arm read"


def _seed_api(aid: str, now: datetime) -> None:
    live, e1 = now - 30 * D, now - 20 * D
    asyncio.run(_add(
        _dec(aid, 1, live), _msg(aid, 1, now - 40 * D), _msg(aid, 1, e1), _msg(aid, 1, now - 19 * D),
        _msg(aid, 2, now - 3 * D), _msg(aid, 3, now - 25 * D), _msg(aid, 6, now - 55 * D),
        _msg(aid, 4, now - 10 * D, direction="out"),
        _tx(aid, 1, e1 - S, 999), _tx(aid, 1, e1 + 14 * D, 1200), _tx(aid, 1, e1 + D, 700, status="refunded"),
        _tx(aid, 1, e1 + D, 800, status="chargedback"), _tx(aid, 1, e1 + 13 * D, 1000, kind="subscription"),
        # pending sales count in every earnings total
        _tx(aid, 1, e1 + D, 500), _tx(aid, 1, e1 + 2 * D, 250, status="pending"),
        _tx(aid, 2, now - 2 * D, 5000), _tx(aid, 4, now - 9 * D, 3000),
        _dec(aid, 1, e1 + S, route="sell_now", price=1500, msg=9001, outcome="bought"),
        _dec(aid, 1, e1 + 2 * S, route="sell_now", price=2000, msg=9002, outcome="declined"),
        _dec(aid, 1, e1 + 3 * S, route="sell_now", price=1800),
        _dec(aid, 1, e1 + 4 * S, route="sell_now", price=1700, outcome="bought"),
        _dec(aid, 3, e1 + 5 * S, route="make_right", price=0, msg=9003, outcome="bought")))


def case_api_shape_owned_account():
    aid, now = IDS["creator_a"], datetime.utcnow()
    client = fx.login_owner("agency_a_owner")
    r = client.get(f"/admin/full-ai/revenue?account_id={aid}")
    assert r.status_code == 200 and r.json() == {"live_since": None, "note": rev.NO_HOLDOUT, "arms": {},
                                                  "routes": []}, (r.status_code, r.text)
    _seed_api(aid, now)
    r = client.get(f"/admin/full-ai/revenue?account_id={aid}")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got == {"live_since": (now - 30 * D).isoformat() + "Z", "note": "no holdout: not a comparison",
                   "arms": {"all": _arm(3, 1, 2, 1750, 875)},
                   "routes": [{"route": "sell_now", "offers": 2, "bought": 1, "cents": 1500}]}, got
    asyncio.run(_add(_dec(aid, 1, now - 60 * D, mode="shadow", route="sell_now", price=999, msg=9100,
                          outcome="bought"),
                     _dec(aid, -5, now - 50 * D, mode="test", route="sell_now", price=500, msg=9101,
                          outcome="bought")))
    again = client.get(f"/admin/full-ai/revenue?account_id={aid}")
    assert again.status_code == 200 and again.json() == got, again.text


def case_api_refuses_like_today():
    theirs = IDS["creator_b"]
    client = fx.login_owner("agency_a_owner")
    r = client.get(f"/admin/full-ai/revenue?account_id={theirs}")
    today = client.get(f"/admin/full-ai/today?account_id={theirs}")
    assert r.status_code in (403, 404), (r.status_code, r.text)
    assert (r.status_code, r.text) == (today.status_code, today.text), (r.text, today.text)
    anon = _harness.make_client().get(f"/admin/full-ai/revenue?account_id={IDS['creator_a']}")
    anon_today = _harness.make_client().get(f"/admin/full-ai/today?account_id={IDS['creator_a']}")
    assert anon.status_code == anon_today.status_code and anon.status_code in (401, 403), anon.status_code


async def case_no_enrolment_table_no_migration():
    async with get_session() as s:
        names = {n for (n,) in (await s.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).all()}
    assert "ai_decisions" in names and "ai_enrolments" not in names, sorted(n for n in names if "ai_" in n)
    versions = Path(__file__).resolve().parents[2] / "service/db/migrations/versions"
    hits = [p.name for p in versions.glob("*.py") if "ai_enrolments" in p.read_text()]
    assert hits == [], hits


_harness.run()
