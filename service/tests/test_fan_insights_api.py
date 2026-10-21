#!/usr/bin/env python3
"""GET /admin/fans/{aid}/{fid}/insights — Fan insights' computed figures.

Contract under test:
  • Spending power ranks the fan's org-wide 30-day spend against every org
    spender; "No Spending History" with no spend ever, "Insufficient Data" under
    20 spenders, "Bottom" with nothing this month. Accounts outside the
    principal's org never count, and a chargeback is not spend.
  • Chargeback risk = reversed cents / paid cents, org lifetime; High >66,
    Medium >33, else Low; None (the drawer's "—") with nothing paid.
  • A chatter scoped to some of the org's accounts sees only those accounts'
    totals, and gets a 403 on an account outside the set.
  • ppv_recent reads the last 30 priced messages this creator sent: Buy rate
    = unlocked / sent, Highest and Lowest price; unsent and inbound rows drop.
  • The fan row's local_timezone resolves the stored city / country, None if
    ambiguous.
  • The fan PATCH validates and stores Salary, Salary frequency, Last pay date.

Run: ./venv/bin/python service/tests/test_fan_insights_api.py  (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

import auth  # noqa: E402
import chatters  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Message, Transaction  # noqa: E402
from fan_insights_api import chargeback_label, fan_insights, spending_power_label  # noqa: E402
from fans import FanUpdateBody, get_fan, update_fan  # noqa: E402

_A, _B, _OTHER = "fi_a", "fi_b", "fi_other"   # _A and _B are one org; _OTHER is not
_FAN = 70001


def _as_org(fn):
    """Run `fn` signed in as the owner of _A and _B."""
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
    # 24 other org spenders at $10..$33 across both org accounts; our fan spends
    # $30 on _A plus $20 on _B = $50, so he is rank 1 of 25 (4%): Top 5%.
    for i in range(24):
        await _tx(_A if i % 2 else _B, 80000 + i, 1000 + 100 * i)
    await _tx(_A, _FAN, 3000)
    await _tx(_B, _FAN, 2000)
    # Ignored: another org's whale, a chargeback, and spend older than 30 days.
    await _tx(_OTHER, 80100, 999_900)
    await _tx(_A, 80101, 999_900, status="chargedback")
    await _tx(_A, 80102, 999_900, days_ago=45)
    sp = (await _as_org(lambda: fan_insights(_A, _FAN))())["spending_power"]
    assert sp == {"label": "Top 5%", "spend_30d_cents": 5000, "population": 25}, sp


async def case_bottom_when_nothing_this_month():
    # 80102 spent only 45 days ago: history, but nothing in the window.
    sp = (await _as_org(lambda: fan_insights(_A, 80102))())["spending_power"]
    assert sp["label"] == "Bottom" and sp["spend_30d_cents"] == 0, sp


async def case_chargeback_risk_org_lifetime():
    # _FAN so far: $50 paid. Add a $40 chargeback on _B and a $10 refund on _A,
    # plus a failed row and another org's chargeback (both ignored).
    await _tx(_B, _FAN, 4000, status="chargedback", days_ago=90)
    await _tx(_A, _FAN, 1000, status="refunded")
    await _tx(_A, _FAN, 7777, status="failed")
    await _tx(_OTHER, _FAN, 50_000, status="chargedback")
    cb = (await _as_org(lambda: fan_insights(_A, _FAN))())["chargeback_risk"]
    # 5000 reversed of 10000 paid = 50% → Medium.
    assert cb == {"label": "Medium", "pct": 50.0, "paid_cents": 10000, "reversed_cents": 5000}, cb


async def case_chatter_sees_only_its_accounts():
    # A chatter on _A alone. _FAN's _A rows: $30 cleared, $10 refunded, a failed
    # row; _B's $20 and $40 chargeback are not his to see. 13 fans spent on _A in
    # the window (12 of the 24 plus _FAN), under 20: Insufficient Data.
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
    # 1000 refunded of 4000 paid = 25% -> Low.
    assert resp["chargeback_risk"] == {"label": "Low", "pct": 25.0, "paid_cents": 4000,
                                       "reversed_cents": 1000}, resp


async def case_ppv_recent_last_30():
    # 32 sent PPVs, newest first by minutes_ago; the two oldest ($1 and $99) fall
    # outside the window. Of the newest 30, every third is unlocked (10 of 30).
    await _ppv(_FAN, 1, 100, paid=False, minutes_ago=500)
    await _ppv(_FAN, 2, 9900, paid=True, minutes_ago=499)
    for i in range(30):
        await _ppv(_FAN, 10 + i, 500 + 100 * i, paid=(i % 3 == 0), minutes_ago=100 - i)
    # Dropped: an unsent PPV, an inbound priced row, a free message.
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
    # A multi-zone country alone is ambiguous: no guess.
    assert (await _as_org(lambda: get_fan(_A, _FAN + 1))())["local_timezone"] is None
    # It follows Location: a PATCH's response carries the new zone.
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
    # "" clears; bad values are refused.
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


# Definition order matters: later cases add to the earlier cases' rows.
_harness.run()
