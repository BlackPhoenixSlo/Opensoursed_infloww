#!/usr/bin/env python3
"""Employee reports credit each sale by the Sales Settings rule for its revenue
kind (docs/spec/phase-04-apply-stored-settings.md, Sales attribution rules;
ticket 25, stories 41-48 and 52-54), with the welcome-message and OnlyFans-fee
exclusions applied, and the Timesheet's Recorded earnings credited the same
way (ticket 26, stories 49-51).

The seam is the Relay over HTTP with real owner sessions from the shared
two-Agency fixture: `GET /admin/stats/per-employee?by_account=true` over
messages, transactions and Clock events seeded straight into the temp DB with
fixed past timestamps. Sales Settings and Time tracking are saved through
`PUT /admin/settings/{tab}`. Each case seeds its own Creator, so its figures
are read from that Creator's `per_account` entries alone. Every expected figure
is a worked example written out by hand.

Run: ./venv/bin/python service/tests/test_sales_attribution_rules.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
from _clock_fixtures import (  # noqa: E402
    IDS, agency_wide_event as _agency_wide_event, employee as _employee, event as _event, shift as _seed_shift,
)
from db.engine import get_session  # noqa: E402
from db.models import Account, Message, Transaction, UserAccount  # noqa: E402

FALLBACK = "Shift schedule needs Time tracking on; credited by Converters."
DAY = "2026-05-04"
REPORT = f"/admin/stats/per-employee?from={DAY}&to={DAY}&by_account=true"
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
MASTER = fx.login_owner("agency_master")


def _at(hhmm: str, day: str = DAY) -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}:00")


async def _apply_view() -> None:
    # init_db (create_all) builds no views: apply the shipped attribution view,
    # as test_timesheet_api.py does.
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "db", "migrations", "versions", "20260710_0200_attr_view_orphan_rows.py")
    spec = importlib.util.spec_from_file_location("mig_attr_view", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    async with get_session() as s:
        await s.execute(text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
        await s.execute(text(mig._NEW_VIEW_SQL))


asyncio.run(_apply_view())


def _creator(aid: str, owner: str = "agency_a_owner") -> str:
    """A Creator of `owner`'s Agency used by one case only."""
    async def _seed():
        async with get_session() as s:
            s.add(Account(id=aid, nickname=f"sa_creator_{aid[-2:]}", color="#aaaaaa"))
        async with get_session() as s:
            s.add(UserAccount(user_id=IDS[owner], account_id=aid))
    (account_registry.ACCOUNTS_DIR / aid).mkdir()
    asyncio.run(_seed())
    return aid


_next_id = iter(range(7_000_001, 7_100_000))


def _message(aid: str, fan: int, sender: int | None, at: datetime, automation_kind: str | None = None) -> int:
    """One outbound message on `aid` to `fan`; returns its message id."""
    mid = next(_next_id)

    async def _seed():
        async with get_session() as s:
            s.add(Message(account_id=aid, fan_id=fan, message_id=mid, direction="out", body="x",
                          sent_by_employee_id=sender, created_at=at, ingested_at=at,
                          automation_kind=automation_kind))
    asyncio.run(_seed())
    return mid


def _sale(aid: str, kind: str, cents: int, at: datetime, fan: int | None = 1, message_id: int | None = None,
          manual: int | None = None, net: int | None = None) -> None:
    async def _seed():
        async with get_session() as s:
            s.add(Transaction(account_id=aid, fan_id=fan, kind=kind, message_id=message_id, amount_cents=cents,
                              occurred_at=at, status="cleared", currency="USD", source="ledger",
                              attributed_employee_id=manual, net_cents=net))
    asyncio.run(_seed())


# Backdated to the start (Settings are versioned, roadmap W6 6.4), so the rules
# credit every fixture sale, as a save did before versioning.
SINCE_THE_START = {"effective_from": "1970-01-01T00:00:00Z"}


def _put(client, tab: str, blob: dict) -> None:
    r = client.put(f"/admin/settings/{tab}", json=blob, params=SINCE_THE_START)
    assert r.status_code == 200, f"PUT {tab}: {r.status_code} {r.text}"


def _rules(client, messages: str, posts_tips: str, opt_in: bool = False, time_tracking: bool = True,
           exclude_welcome: bool = False, exclude_of_fee: bool = False) -> None:
    _put(client, "sales", {"exclude_welcome": exclude_welcome, "exclude_of_fee": exclude_of_fee,
                           "attribution": {"messages": messages, "posts_tips": posts_tips,
                                           "subscriptions_chatter_opt_in": opt_in}})
    _put(client, "time-tracking", {"enabled": time_tracking})


def _report(client) -> dict:
    r = client.get(REPORT)
    assert r.status_code == 200, f"per-employee: {r.status_code} {r.text}"
    return r.json()


def _credited(client, aid: str, field: str = "revenue_cents") -> dict:
    """`{employee_id: cents}` credited on one Creator (None is Unattributed)."""
    out = {}
    for row in _report(client)["employees"]:
        for sub in row.get("per_account", []):
            value = sub["revenue_by_kind"] if field == "revenue_by_kind" else sub[field]
            if sub["account_id"] == aid and (value if field != "revenue_by_kind" else any(value.values())):
                out[row["employee_id"]] = value
    return out


# ── Converters: today's figures ─────────────────────────────────────────────

C1 = _creator("2000001")
E1, E2, E3 = _employee("sa_emp_1"), _employee("sa_emp_2"), _employee("sa_emp_3")


def _seed_converters() -> None:
    """On C1, every shape test_ppv_link_attribution's case_view_exactly_once
    seeds: a PPV unlocked from E1's message (1000), a tip on E1's message
    (400), a standalone tip whose fan E2 wrote to two days before (500), a
    standalone tip from a fan nobody wrote to (300), a PPV whose message was
    never ingested (700), a PPV with no message id at all (650), a tip on a
    never-ingested message reassigned by hand to E2 (350); plus a PPV on E1's
    message reassigned by hand to E3 (200) and a standalone tip whose fan E2
    wrote to, reassigned by hand to E3 (150)."""
    m1 = _message(C1, 11, E1, _at("09:00"))
    m2 = _message(C1, 12, E1, _at("09:30"))
    m3 = _message(C1, 16, E1, _at("09:45"))
    _message(C1, 13, E2, _at("10:00", "2026-05-02"))
    _sale(C1, "ppv_message", 1000, _at("10:00"), fan=11, message_id=m1)
    _sale(C1, "tip", 400, _at("10:05"), fan=12, message_id=m2)
    _sale(C1, "tip", 500, _at("10:10"), fan=13)
    _sale(C1, "tip", 300, _at("10:15"), fan=14)
    _sale(C1, "ppv_message", 700, _at("10:20"), fan=15, message_id=6_999_999)
    _sale(C1, "ppv_message", 200, _at("10:25"), fan=16, message_id=m3, manual=E3)
    _sale(C1, "ppv_message", 650, _at("10:30"), fan=17)
    _sale(C1, "tip", 350, _at("10:35"), fan=18, message_id=6_999_997, manual=E2)
    _sale(C1, "tip", 150, _at("10:40"), fan=13, manual=E3)


_seed_converters()
TODAY = {E1: 1400, E2: 850, E3: 350, None: 1650}


def case_converters_reproduces_the_attribution_views_figures():
    _rules(OWNER_A, "converters", "converters")
    assert _credited(OWNER_A, C1) == TODAY
    assert _credited(OWNER_A, C1, "revenue_by_kind") == {
        E1: {"ppv": 1000, "tip": 400}, E2: {"ppv": 0, "tip": 850},
        E3: {"ppv": 200, "tip": 150}, None: {"ppv": 1350, "tip": 300}}
    assert _credited(OWNER_A, C1, "ppv_conversions") == {E1: 1, E3: 1, None: 2}
    assert _report(OWNER_A)["attribution_fallback"] is None


def case_converters_matches_the_view_per_employee_and_creator():
    """With both Agencies on Converters, the Master's report equals the view's
    GROUP BY employee, Creator on every Creator. C5 is left out: it carries the
    Subscriptions, Streams & Referrals kinds, which the opt-in rule credits
    and the view does not."""
    _rules(OWNER_A, "converters", "converters")
    _rules(OWNER_B, "converters", "converters")
    report = {}
    for row in _report(MASTER)["employees"]:
        for sub in row.get("per_account", []):
            if sub["account_id"] != C5 and sub["revenue_cents"]:
                report[(row["employee_id"], sub["account_id"])] = sub["revenue_cents"]

    async def _view():
        async with get_session() as s:
            rows = (await s.execute(text(
                "SELECT sent_by_employee_id, account_id, SUM(amount_cents) "
                "FROM per_employee_revenue_with_attribution WHERE date(occurred_at) = :d AND account_id != :c5 "
                "GROUP BY sent_by_employee_id, account_id"), {"d": DAY, "c5": C5})).all()
        return {(e, a): cents for e, a, cents in rows if cents}
    view = asyncio.run(_view())
    assert {a for _, a in view} >= {C1, C2, C3, CA, CB}, view
    assert report == view, (report, view)


def case_never_saved_rules_with_time_tracking_off_credit_by_converters_and_say_so():
    async def _forget():
        async with get_session() as s:
            await s.execute(text("DELETE FROM settings_versions WHERE user_id = :u AND tab IN ('sales','time-tracking')"),
                            {"u": IDS["agency_a_owner"]})
    asyncio.run(_forget())
    body = _report(OWNER_A)
    assert body["attribution_fallback"] == FALLBACK
    assert _credited(OWNER_A, C1) == TODAY


def case_time_tracking_off_falls_back_from_shift_to_converters_with_the_line():
    _rules(OWNER_A, "shift", "shift", time_tracking=False)
    assert _credited(OWNER_A, C1) == TODAY
    assert _report(OWNER_A)["attribution_fallback"] == FALLBACK
    _rules(OWNER_A, "converters", "shift", time_tracking=False)
    assert _report(OWNER_A)["attribution_fallback"] == FALLBACK
    _rules(OWNER_A, "sender", "converters", time_tracking=False)
    assert _report(OWNER_A)["attribution_fallback"] is None


# ── Message sender ──────────────────────────────────────────────────────────

C2 = _creator("2000002")
_m = _message(C2, 21, E1, _at("08:00"))
_sale(C2, "ppv_message", 1000, _at("11:00"), fan=21, message_id=_m)
_sale(C2, "ppv", 600, _at("11:05"), fan=22)
_sale(C2, "ppv_message", 250, _at("11:10"), fan=23, message_id=6_999_998)


def case_message_sender_credits_the_linked_sender_and_leaves_an_unlinked_sale_unattributed():
    """Message sender reaches only the Messages group under the spec's kind
    map, and there it gives the Converters answer for every sale (the
    lookback serves only tips with no message, which are Posts and Tips). So
    this case pins that equivalence rather than story 43's "visibly
    stricter" rule (sales_attribution.py ASSUMPTION, for Needs-the-human)."""
    _rules(OWNER_A, "sender", "converters")
    assert _credited(OWNER_A, C2) == {E1: 1000, None: 850}
    _rules(OWNER_A, "converters", "converters")
    assert _credited(OWNER_A, C2) == {E1: 1000, None: 850}


# ── Shift schedule ──────────────────────────────────────────────────────────

C3 = _creator("2000003")
E4, E5, E6, E7 = (_employee(f"sa_emp_{n}") for n in (4, 5, 6, 7))
_sale(C3, "ppv_message", 1000, _at("11:00"), fan=31, message_id=_message(C3, 31, E1, _at("08:00")))  # E2 alone
_sale(C3, "ppv_message", 900, _at("13:00"), fan=31, message_id=_message(C3, 31, E1, _at("08:00")))   # nobody
_sale(C3, "ppv_message", 1000, _at("15:00"), fan=31, message_id=_message(C3, 31, E1, _at("08:00")))  # E4-E6
_sale(C3, "tip_post", 120, _at("18:00"), fan=32)                     # E7 still clocked in
_event(E2, _at("10:00"), _at("12:00"), account_id=C3)
_event(E3, _at("10:00"), _at("12:00"), account_id=C1)  # another Creator: no credit on C3
# Another Agency's Clock event on C3: not the owning Agency's, so no credit.
_event(_employee("sa_emp_c3_other_agency", "agency_b_owner"), _at("10:30"), _at("11:30"),
       owner="agency_b_owner", account_id=C3)
for _e in (E6, E4, E5):
    _event(_e, _at("14:00"), _at("16:00"), account_id=C3)
_event(E7, _at("17:00"), None, account_id=C3)


def case_shift_schedule_credits_the_clocked_in_employees_and_splits_the_remainder_to_the_lowest_id():
    _rules(OWNER_A, "shift", "shift")
    lowest, *others = sorted((E4, E5, E6))
    assert _credited(OWNER_A, C3) == {E2: 1000, None: 900, lowest: 334, others[0]: 333, others[1]: 333,
                                      E7: 120}
    assert _report(OWNER_A)["attribution_fallback"] is None


# ── Subscriptions opt-in and the manual override ───────────────────────────

C5 = _creator("2000005")
_event(E1, _at("10:00"), _at("12:00"), account_id=C5)
_sale(C5, "subscription", 900, _at("11:00"), fan=51)
_sale(C5, "tip_stream", 70, _at("11:20"), fan=54)
_sale(C5, "rebill", 100, _at("11:30"), fan=None)
_sale(C5, "subscription", 50, _at("11:40"), fan=52, manual=E2)
_m = _message(C5, 53, E3, _at("09:00"))
_sale(C5, "ppv_message", 400, _at("11:50"), fan=53, message_id=_m, manual=E2)


def case_opt_in_off_leaves_subscriptions_out_and_streams_unattributed_and_on_credits_them_by_shift_schedule():
    """Opt-in off: the subscription (900) and rebill (100) stay out of the
    report as before, the tip_stream (70) is Unattributed, and E2 keeps its
    manual subscription (50) and PPV (400). Opt-in on: E1, clocked in on C5,
    takes 900 + 100 + 70."""
    _rules(OWNER_A, "converters", "converters", opt_in=False)
    assert _credited(OWNER_A, C5) == {None: 70, E2: 450}
    _rules(OWNER_A, "converters", "converters", opt_in=True)
    assert _credited(OWNER_A, C5) == {E1: 1070, E2: 450}


def case_a_manual_override_wins_over_every_rule():
    for messages in ("shift", "sender", "converters"):
        for opt_in in (False, True):
            _rules(OWNER_A, messages, "shift", opt_in=opt_in)
            got = _credited(OWNER_A, C5)
            assert got[E2] == 450, (messages, opt_in, got)
            assert E3 not in got, (messages, opt_in, got)


# ── The Master: each Creator by its own Agency's rules ──────────────────────

CA, CB = _creator("2000006"), _creator("2000007", owner="agency_b_owner")
EA_SENDER, EA_SHIFT = _employee("sa_emp_a_sender"), _employee("sa_emp_a_shift")
EB_SENDER, EB_SHIFT = (_employee("sa_emp_b_sender", "agency_b_owner"),
                       _employee("sa_emp_b_shift", "agency_b_owner"))
for _aid, _sender, _shift, _owner in ((CA, EA_SENDER, EA_SHIFT, "agency_a_owner"),
                                      (CB, EB_SENDER, EB_SHIFT, "agency_b_owner")):
    _m = _message(_aid, 61, _sender, _at("09:00"))
    _sale(_aid, "ppv_message", 800, _at("10:30"), fan=61, message_id=_m)
    _event(_shift, _at("10:00"), _at("11:00"), owner=_owner, account_id=_aid)


def case_the_master_sees_each_creator_credited_by_its_own_agencys_rules():
    _rules(OWNER_A, "shift", "shift", time_tracking=True)
    _rules(OWNER_B, "converters", "converters", time_tracking=True)
    assert _credited(MASTER, CA) == {EA_SHIFT: 800}
    assert _credited(MASTER, CB) == {EB_SENDER: 800}
    _rules(OWNER_B, "shift", "shift", time_tracking=True)
    assert _credited(MASTER, CB) == {EB_SHIFT: 800}
    assert _credited(MASTER, CA) == {EA_SHIFT: 800}
    # Agency A's own report never reads Agency B's Creator.
    assert _credited(OWNER_A, CB) == {}


# ── Exclude welcome messages ────────────────────────────────────────────────

C8 = _creator("2000008")
E8 = _employee("sa_emp_8")
for _kind, _cents in (("send_welcome", 1000), ("welcome", 200), ("welcome_chatter_for_info", 300),
                      ("send_followup", 400), (None, 500)):
    _sale(C8, "tip" if _kind == "welcome" else "ppv_message", _cents, _at("12:00"), fan=81,
          message_id=_message(C8, 81, E8, _at("09:00"), automation_kind=_kind))
# A welcome sale reassigned by hand: the toggle still drops it.
_sale(C8, "ppv_message", 60, _at("12:05"), fan=82, manual=E2,
      message_id=_message(C8, 82, E8, _at("09:00"), automation_kind="send_welcome"))


def case_exclude_welcome_drops_each_welcome_kinds_sales_and_keeps_the_rest():
    """Off: E8 keeps 1000 + 200 + 300 + 400 + 500 and E2 its manual 60. On:
    the send_welcome (1000), welcome (200) and welcome_chatter_for_info (300)
    sales and the manual welcome sale (60) go; the send_followup (400) and
    the plain message's sale (500) stay."""
    _rules(OWNER_A, "converters", "converters", exclude_welcome=False)
    assert _credited(OWNER_A, C8) == {E8: 2400, E2: 60}
    _rules(OWNER_A, "converters", "converters", exclude_welcome=True)
    assert _credited(OWNER_A, C8) == {E8: 900}
    assert _credited(OWNER_A, C8, "ppv_conversions") == {E8: 2}


# ── Exclude the 20% OnlyFans fee ────────────────────────────────────────────

C9 = _creator("2000009")
E9 = _employee("sa_emp_9")
_sale(C9, "ppv_message", 1000, _at("12:00"), fan=91, net=820,
      message_id=_message(C9, 91, E9, _at("09:00")))
_sale(C9, "tip", 999, _at("12:05"), fan=92, message_id=_message(C9, 92, E9, _at("09:00")))
_sale(C9, "tip", 55, _at("12:10"), fan=93)  # nobody wrote to fan 93: Unattributed


def case_exclude_of_fee_uses_the_stored_net_else_80_percent_rounded_down():
    """On: the PPV shows its stored net 820 (not 800), the 999 tip with no
    net shows 799 (799.2 rounded down), the Unattributed 55 tip shows 44."""
    _rules(OWNER_A, "converters", "converters", exclude_of_fee=False)
    assert _credited(OWNER_A, C9) == {E9: 1999, None: 55}
    _rules(OWNER_A, "converters", "converters", exclude_of_fee=True)
    assert _credited(OWNER_A, C9) == {E9: 1619, None: 44}
    assert _credited(OWNER_A, C9, "revenue_by_kind") == {E9: {"ppv": 820, "tip": 799}, None: {"ppv": 0, "tip": 44}}


# ── The Timesheet's Recorded earnings agree with Employee reports ───────────

C10 = _creator("2000010")
E10A, E10B = _employee("sa_emp_10a"), _employee("sa_emp_10b")
_event(E10A, _at("10:00"), _at("12:00"), account_id=C10)
_event(E10B, _at("11:00"), _at("12:00"), account_id=C10)
_sale(C10, "ppv_message", 1000, _at("10:30"), fan=101, message_id=_message(C10, 101, E10A, _at("09:00")))
_sale(C10, "ppv_message", 999, _at("11:30"), fan=102, net=900,
      message_id=_message(C10, 102, E10A, _at("09:00")))
_sale(C10, "tip", 500, _at("11:15"), fan=103,
      message_id=_message(C10, 103, E10A, _at("09:00"), automation_kind="send_welcome"))
_sale(C10, "tip_post", 250, _at("11:45"), fan=104)  # nobody wrote to fan 104
# Off the clock: E10A clocked out at 12:00.
_sale(C10, "ppv_message", 700, _at("13:00"), fan=105, message_id=_message(C10, 105, E10A, _at("09:00")))


def _timesheet(client, group: str) -> dict:
    r = client.get(f"/admin/shifts/timesheet?from={DAY}T00:00:00Z&to=2026-05-05T00:00:00Z&group={group}")
    assert r.status_code == 200, f"timesheet: {r.status_code} {r.text}"
    return {row["key"]: row["recorded_earnings_cents"] for row in r.json()["rows"]}


def _per_employee_totals(client) -> dict:
    return {row["employee_id"]: row["revenue_cents"] for row in _report(client)["employees"]}


def case_the_timesheets_recorded_earnings_equal_the_per_employee_figures_under_the_same_settings():
    """Shift schedule with both toggles on: E10A takes the 1000 PPV as 800,
    half of the 999 PPV's stored net 900 (450) and half of the 250 tip_post
    as 200 (100), 1350 in all; E10B takes 450 + 100 = 550; the welcome tip
    (500) goes, and the 13:00 PPV has nobody on the clock (Unattributed)."""
    _rules(OWNER_A, messages="shift", posts_tips="shift", exclude_welcome=True, exclude_of_fee=True)
    want = {E10A: 1350, E10B: 550}
    per_employee = _per_employee_totals(OWNER_A)
    timesheet = _timesheet(OWNER_A, "employee")
    for eid, cents in want.items():
        assert timesheet[str(eid)] == cents, (eid, timesheet)
        assert per_employee.get(eid, 0) == cents, (eid, per_employee)
    assert _timesheet(OWNER_A, "account")[C10] == sum(want.values())


def case_an_off_clock_sale_counts_in_employee_reports_but_not_in_the_timesheet():
    """The ASSUMPTION at shifts_api.timesheet: under Converters E10A, the
    sender, is credited the 700 PPV sold at 13:00, after her 12:00
    clock-out, so Employee reports show 2499 + 700 = 3199 while the
    Timesheet keeps worked time only and shows 2499 (1000 + 999 + 500
    inside the Clock event); E10B, who sent nothing, takes 0."""
    _rules(OWNER_A, messages="converters", posts_tips="converters")
    assert _per_employee_totals(OWNER_A).get(E10A) == 3199
    timesheet = _timesheet(OWNER_A, "employee")
    assert timesheet[str(E10A)] == 2499, timesheet
    assert timesheet[str(E10B)] == 0, timesheet
    assert _timesheet(OWNER_A, "account")[C10] == 2499


# ── Read path only ──────────────────────────────────────────────────────────

def _attribution_columns() -> tuple:
    async def _read():
        async with get_session() as s:
            msgs = (await s.execute(text(
                "SELECT account_id, fan_id, message_id, sent_by_employee_id FROM messages ORDER BY 1, 2, 3"))).all()
            txs = (await s.execute(text(
                "SELECT id, attributed_employee_id FROM transactions ORDER BY id"))).all()
        return [tuple(r) for r in msgs], [tuple(r) for r in txs]
    return asyncio.run(_read())


def case_no_messages_or_transactions_attribution_column_changes():
    before = _attribution_columns()
    assert before[0] and before[1]
    for messages in ("shift", "sender", "converters"):
        for posts_tips in ("shift", "converters"):
            for opt_in in (False, True):
                for tt in (False, True):
                    _rules(OWNER_A, messages, posts_tips, opt_in=opt_in, time_tracking=tt)
                    for client in (OWNER_A, MASTER):
                        _report(client)
    assert _attribution_columns() == before



# ── The agency-wide clock (w4-a) ────────────────────────────────────────────

# An event on no Creator at 21:00-22:00, an hour no other case sells in, so it
# changes no other case's figures. EW holds CW in a Shift until 21:45 only, and
# CW2 not at all.
CW, CW2, CWB = _creator("2000091"), _creator("2000093"), _creator("2000092", owner="agency_b_owner")
EW = _employee("sa_emp_wide")
_seed_shift(_at("21:00"), _at("21:45"), [(EW, CW)])
_agency_wide_event(EW, _at("21:00"), _at("22:00"))
_agency_wide_event(_employee("sa_emp_wide_b", "agency_b_owner"), _at("21:00"), _at("22:00"), owner="agency_b_owner")
_event(E1, _at("21:00"), _at("22:00"), account_id=CW)
for _aid, _fan, _hhmm in ((CW, 91, "21:30"), (CW, 93, "21:50"), (CW2, 94, "21:30"), (CWB, 92, "21:30")):
    _sale(_aid, "ppv_message", 1000, _at(_hhmm), fan=_fan, message_id=_message(_aid, _fan, E3, _at("20:00")))


def case_shift_schedule_credits_an_agency_wide_clock_event_only_on_the_creator_its_shift_holds_then():
    """EW, clocked in on no Creator, shares CW's 21:30 sale with E1, clocked
    in on CW, because EW's Shift holds CW then; E1 alone takes the 21:50 sale,
    after that Shift ends, and nobody CW2's, a Creator EW holds in no Shift
    (no dilution across the Agency's Creators). Agency B's agency-wide event
    never reaches Agency A's Creator, nor EW Agency B's."""
    _rules(OWNER_A, "shift", "shift")
    _rules(OWNER_B, "shift", "shift")
    assert _credited(OWNER_A, CW) == {E1: 1500, EW: 500}
    assert _credited(OWNER_A, CW2) == {None: 1000}
    assert EW not in _credited(MASTER, CWB) and EW not in _credited(OWNER_B, CWB)


_harness.run()
