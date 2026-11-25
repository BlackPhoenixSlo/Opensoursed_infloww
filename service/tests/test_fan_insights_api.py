#!/usr/bin/env python3
import _harness

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

import auth  # noqa: E402
import chatters  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Message, Transaction  # noqa: E402
from fan_insights_api import chargeback_label, fan_insights, spending_power_label  # noqa: E402
from fans import FanUpdateBody, get_fan, update_fan  # noqa: E402

_A, _B, _OTHER = "fi_a", "fi_b", "fi_other"
_FAN = 70001


def _as_org(fn):
    async def wrapped():
        tok = auth._request_user.set(auth.AuthedUser("u-fi", "fi_owner", frozenset({_A, _B})))
        try:
            return await fn()
        finally:
            auth._request_user.reset(tok)
    return wrapped


async def _tx(account_id, fan_id, cents, *, status="cleared", days_ago=1, kind="ppv_message"):
    async with get_session() as s:
        s.add(Transaction(account_id=account_id, fan_id=fan_id, kind=kind, amount_cents=cents,
                          occurred_at=datetime.utcnow() - timedelta(days=days_ago), status=status))
        await s.commit()


async def _ppv(fan_id, message_id, cents, *, paid, direction="out", unsent=False, minutes_ago=0):
    async with get_session() as s:
        s.add(Message(account_id=_A, fan_id=fan_id, message_id=message_id, direction=direction,
                      price_cents=cents, is_paid=paid, is_unsent=unsent,
                      created_at=datetime.utcnow() - timedelta(minutes=minutes_ago)))
        await s.commit()


async def _seed_accounts():
    async with get_session() as s:
        for aid in (_A, _B, _OTHER):
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid))
        await s.commit()


def case_labels():
    assert spending_power_label(0, 1, 0, False) == "No Spending History"
    assert spending_power_label(500, 1, 19, True) == "Insufficient Data"
    assert spending_power_label(0, 30, 30, True) == "Bottom"
    assert spending_power_label(900, 1, 100, True) == "Top 1%"
    assert spending_power_label(900, 2, 100, True) == "Top 5%"
    assert spending_power_label(900, 50, 100, True) == "Top 50%"
    assert spending_power_label(900, 51, 100, True) == "Bottom"
    assert chargeback_label(None) is None
    assert chargeback_label(0) == "Low" and chargeback_label(33) == "Low"
    assert chargeback_label(50) == "Medium" and chargeback_label(66) == "Medium"
    assert chargeback_label(66.1) == "High"


async def case_no_history():
    await _seed_accounts()
    resp = await _as_org(lambda: fan_insights(_A, _FAN + 999))()
    assert resp["spending_power"]["label"] == "No Spending History", resp
    assert resp["chargeback_risk"] == {"label": None, "pct": None, "paid_cents": 0,
                                       "reversed_cents": 0}, resp
    assert resp["ppv_recent"]["count"] == 0 and resp["ppv_recent"]["buy_rate_pct"] is None, resp


async def case_spending_power_ranks_org_wide():
    for i in range(24):
        await _tx(_A if i % 2 else _B, 80000 + i, 1000 + 100 * i)
    await _tx(_A, _FAN, 3000)
    await _tx(_B, _FAN, 2000)
    await _tx(_OTHER, 80100, 999_900)
    await _tx(_A, 80101, 999_900, status="chargedback")
    await _tx(_A, 80102, 999_900, days_ago=45)
    sp = (await _as_org(lambda: fan_insights(_A, _FAN))())["spending_power"]
    assert sp == {"label": "Top 5%", "spend_30d_cents": 5000, "population": 25}, sp


async def case_bottom_when_nothing_this_month():
    sp = (await _as_org(lambda: fan_insights(_A, 80102))())["spending_power"]
    assert sp["label"] == "Bottom" and sp["spend_30d_cents"] == 0, sp


async def case_chargeback_risk_org_lifetime():
    await _tx(_B, _FAN, 4000, status="chargedback", days_ago=90)
    await _tx(_A, _FAN, 1000, status="refunded")
    await _tx(_A, _FAN, 7777, status="failed")
    await _tx(_OTHER, _FAN, 50_000, status="chargedback")
    cb = (await _as_org(lambda: fan_insights(_A, _FAN))())["chargeback_risk"]
    assert cb == {"label": "Medium", "pct": 50.0, "paid_cents": 10000, "reversed_cents": 5000}, cb


async def case_chatter_sees_only_its_accounts():
    identity = chatters.ChatterIdentity(
        id_="ch-fi", username="fi_chatter", display_name=None, color=None,
        owner_user_ids=frozenset({"u-fi"}), account_ids=frozenset({_A}))
    tok = chatters._request_chatter.set(identity)
    try:
        resp = await fan_insights(_A, _FAN)
        try:
            await fan_insights(_B, _FAN)
        except Exception as e:  # noqa: BLE001
            assert getattr(e, "status_code", None) == 403, e
        else:
            raise AssertionError("expected 403 for an account outside the chatter's set")
    finally:
        chatters._request_chatter.reset(tok)
    assert resp["spending_power"] == {"label": "Insufficient Data", "spend_30d_cents": 3000,
                                      "population": 13}, resp
    assert resp["chargeback_risk"] == {"label": "Low", "pct": 25.0, "paid_cents": 4000,
                                       "reversed_cents": 1000}, resp


async def case_ppv_recent_last_30():
    await _ppv(_FAN, 1, 100, paid=False, minutes_ago=500)
    await _ppv(_FAN, 2, 9900, paid=True, minutes_ago=499)
    for i in range(30):
        await _ppv(_FAN, 10 + i, 500 + 100 * i, paid=(i % 3 == 0), minutes_ago=100 - i)
    await _ppv(_FAN, 90, 50_000, paid=False, unsent=True)
    await _ppv(_FAN, 91, 50_000, paid=None, direction="in")
    await _ppv(_FAN, 92, 0, paid=None)
    pt = (await _as_org(lambda: fan_insights(_A, _FAN))())["ppv_recent"]
    assert pt == {"count": 30, "bought": 10, "buy_rate_pct": 33,
                  "highest_cents": 3400, "lowest_cents": 500}, pt


async def case_local_timezone():
    async with get_session() as s:
        s.add(Fan(account_id=_A, fan_id=_FAN, home_city="Chicago", home_country="USA"))
        s.add(Fan(account_id=_A, fan_id=_FAN + 1, home_country="United States"))
        await s.commit()
    assert (await _as_org(lambda: get_fan(_A, _FAN))())["local_timezone"] == "America/Chicago"
    assert (await _as_org(lambda: get_fan(_A, _FAN + 1))())["local_timezone"] is None
    row = await _as_org(lambda: update_fan(_A, _FAN + 1, FanUpdateBody(home_city="Denver")))()
    assert row["local_timezone"] == "America/Denver", row


async def case_outside_org_is_403():
    try:
        await _as_org(lambda: fan_insights(_OTHER, _FAN))()
    except Exception as e:  # noqa: BLE001
        assert getattr(e, "status_code", None) == 403, e
    else:
        raise AssertionError("expected 403 for an account outside the org")


async def case_salary_fields_patch():
    body = FanUpdateBody(salary="  $4k / month ", salary_frequency="biweekly",
                         last_pay_date="2026-10-15")
    await _as_org(lambda: update_fan(_A, _FAN, body))()
    row = await _as_org(lambda: get_fan(_A, _FAN))()
    assert (row["salary"], row["salary_frequency"], row["last_pay_date"]) == \
        ("$4k / month", "biweekly", "2026-10-15"), row
    await _as_org(lambda: update_fan(_A, _FAN, FanUpdateBody(salary="", last_pay_date="")))()
    row = await _as_org(lambda: get_fan(_A, _FAN))()
    assert row["salary"] is None and row["last_pay_date"] is None, row
    for bad in ({"salary_frequency": "daily"}, {"last_pay_date": "15/10/2026"},
                {"last_pay_date": "2026-2-1"}):
        try:
            FanUpdateBody(**bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


_harness.run()
