#!/usr/bin/env python3
"""Chatting statistics (roadmap W5 5.1, 5.2): the message side read from `messages` at query time
(`msg_stats`) and Employee reports' `GET /admin/stats/chatting-stats`.

  sends     an Employee's own sends only (no mass, automation, Automation sentinel or inbound message); PPVs
            are priced sends, unlocks counted on the PPV's send date, an unsent message still counts; fans
            chatted are distinct per Creator.
  replies   a wait begins at a fan's message after ours and ends at our next message of any kind; it counts
            only when that message is an Employee's own send. A wait that began before the window is paired
            through the lookback; `system` rows are skipped; an unreplied fan adds nothing.
  sales     by channel to the credited Employee: direct (a sale of its message), mass (of a mass message),
            chat tips (credited by the 7-day lookback); a sale reassigned by hand moves with it; an
            automation's sale, an OF-native mass copy (no sender), a post tip and a refunded sale are in
            none. "Exclude the 20% OnlyFans fee" applies by each sale's time when it changes in the window.
            A Priority mass message's sale is its own channel, to its launcher (or by hand); its sends are
            not direct.
  report    the endpoint's derived figures (golden ratio, unlock rate, fan CVR, average reply, per clocked
            hour), no Automation row, and Role enforcement: a role without Employee reports is refused, a
            "self" scope sees only its own row and no clocked time; `chatter_only` keeps the Chatter role's.
  creators  Creator reports' engagement columns (per-model, 5.3): the same sends per Creator, each fan once.
  plans    the sends read seeks ix_messages_chatter_sends; the reply read walks each chat on the covering
            ix_messages_chat_seq.

Seeded straight into the temp DB; no network.

Run: ./venv/bin/python service/tests/test_chatting_stats.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from sqlalchemy import text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import employees  # noqa: E402
import msg_stats  # noqa: E402
from _clock_fixtures import IDS, employee as _employee, event as _clock_event  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Employee, Transaction, UserAccount  # noqa: E402

ENGINE = sa.create_engine(os.environ["CHATTERLY_DB_URL"])  # no FK pragma: a mass_run_id needs no mass run
OWNER_A = fx.login_owner("agency_a_owner")
CHATTER_A = fx.login_chatter("chatter_a")


def _creator(aid: str) -> str:
    async def _seed():
        async with get_session() as s:
            s.add(Account(id=aid, nickname=f"cs_creator_{aid[-2:]}", color="#aaaaaa"))
        async with get_session() as s:
            s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=aid))
    (account_registry.ACCOUNTS_DIR / aid).mkdir()
    asyncio.run(_seed())
    return aid


def _sentinel() -> int:
    async def _seed():
        async with get_session() as s:
            row = Employee(display_name="Automation", is_active=False)
            s.add(row)
            await s.flush()
            return row.id
    return asyncio.run(_seed())


_mid = iter(range(70_000_001, 70_100_000))


def _msg(aid: str, fan: int, sender: int | None, at: datetime, direction: str = "out", body: str = "x",
         price: int = 0, paid: bool | None = None, unsent: bool = False, mass_run_id: int | None = None,
         automation_kind: str | None = None) -> int:
    mid = next(_mid)
    with ENGINE.begin() as conn:
        conn.execute(text(
            "INSERT INTO messages (account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
            "media_count, price_cents, is_paid, is_tip, is_unsent, is_promise, sent_by_employee_id, mass_run_id, "
            "automation_kind, created_at, ingested_at) VALUES (:a, :f, :m, :d, '', :b, '[]', 0, :p, :paid, 0, :u, 0, "
            ":e, :r, :k, :c, :c)"),
            {"a": aid, "f": fan, "m": mid, "d": direction, "b": body, "p": price, "paid": paid, "u": unsent,
             "e": sender, "r": mass_run_id, "k": automation_kind, "c": at.strftime("%Y-%m-%d %H:%M:%S.%f")})
    return mid


def _sale(aid: str, kind: str, cents: int, at: datetime, fan: int, message_id: int | None = None,
          status: str = "cleared", net: int | None = None, reassigned_to: int | None = None) -> None:
    async def _seed():
        async with get_session() as s:
            s.add(Transaction(account_id=aid, fan_id=fan, kind=kind, message_id=message_id, amount_cents=cents,
                              net_cents=net, attributed_employee_id=reassigned_to, occurred_at=at, status=status,
                              currency="USD", source="ledger"))
    asyncio.run(_seed())


def _read(fn, **kw) -> list:
    async def _run():
        async with get_session() as s:
            return await fn(s, **kw)
    return asyncio.run(_run())


def _by_key(rows, *keys: str, fields: tuple[str, ...]) -> dict:
    return {tuple(getattr(r, k) for k in keys): tuple(getattr(r, f) for f in fields) for r in rows}


C1, C2, C3, C4 = _creator("5200001"), _creator("5200002"), _creator("5200003"), _creator("5200004")
E1, E2 = _employee("cs_emp_1"), _employee("cs_emp_2")
AUTO = _sentinel()
DAY = datetime(2026, 4, 10)
SENDS = ("messages", "ppvs", "unlocked", "chars", "fans")

# Creator 1 and 2 on 10 April: the sends the report and the sends read count.
_msg(C1, 1, None, DAY.replace(hour=10), direction="in")
SENT_TEXT = _msg(C1, 1, E1, DAY.replace(hour=10, minute=5), body="hello")
SENT_PPV = _msg(C1, 1, E1, DAY.replace(hour=10, minute=20), body="abc", price=1000, paid=True)
_msg(C1, 2, E1, DAY.replace(hour=11), body="", price=500, paid=False, unsent=True)  # unsent: still sent
_msg(C1, 3, E1, DAY.replace(hour=11, minute=5), mass_run_id=1)                     # one recipient of a mass message
_msg(C1, 4, E1, DAY.replace(hour=11, minute=6), automation_kind="autoreply")        # an automation's, credited to E1
_msg(C1, 5, AUTO, DAY.replace(hour=11, minute=7))                                   # the Automation sentinel's
_msg(C1, 1, E2, DAY.replace(hour=10, minute=30), body="yo")
_msg(C2, 1, E1, DAY.replace(hour=12), body="hey")                                   # the same fan id, another Creator
_msg(C1, 6, E1, DAY - timedelta(hours=1))                                           # before the window
_sale(C1, "ppv_message", 1000, DAY.replace(hour=10, minute=40), fan=1, message_id=SENT_PPV)
_clock_event(E1, DAY.replace(hour=9), DAY.replace(hour=11))
WINDOW = dict(start=DAY, end=DAY.replace(hour=23, minute=59, second=59))


def case_sends_count_only_an_employees_own_and_fans_are_distinct_per_group():
    rows = _read(msg_stats.send_stats, account_ids=[C1, C2], **WINDOW)
    assert _by_key(rows, "account_id", "employee_id", fields=SENDS) == {
        (C1, E1): (3, 2, 1, 8, 2), (C1, E2): (1, 0, 0, 2, 1), (C2, E1): (1, 0, 0, 3, 1)}, rows


REPLY_DAY = datetime(2026, 5, 2)


def _seed_replies() -> None:
    d = REPLY_DAY
    _msg(C3, 1, None, d - timedelta(minutes=10), direction="in")          # waits since 23:50 the day before
    _msg(C3, 1, E1, d.replace(minute=10))                                  # 1200 s
    _msg(C3, 2, None, d.replace(hour=1), direction="in")
    _msg(C3, 2, None, d.replace(hour=1, minute=5), direction="in")
    _msg(C3, 2, None, d.replace(hour=1, minute=7), direction="system")
    _msg(C3, 2, E1, d.replace(hour=1, minute=10))                          # 600 s, from the first of the two
    _msg(C3, 2, E1, d.replace(hour=1, minute=20))                          # no wait: not a reply
    _msg(C3, 3, None, d.replace(hour=2), direction="in")
    _msg(C3, 3, E1, d.replace(hour=2, minute=1), mass_run_id=9)            # a mass message ends the wait
    _msg(C3, 3, E1, d.replace(hour=2, minute=30))
    _msg(C3, 4, None, d.replace(hour=3), direction="in")
    _msg(C3, 4, None, d.replace(hour=3, minute=1), automation_kind="autoreply")
    _msg(C3, 5, None, d.replace(hour=4), direction="in")                   # unreplied
    _msg(C3, 6, None, d - timedelta(hours=14), direction="in")
    _msg(C3, 6, E2, d - timedelta(hours=13, minutes=55))                   # replied before the window
    _msg(C3, 7, None, d.replace(hour=5), direction="in")
    _msg(C3, 7, E2, d.replace(hour=5, minute=30))                          # 1800 s
    _msg(C3, 8, None, d.replace(hour=6), direction="in")
    _msg(C3, 8, AUTO, d.replace(hour=6, minute=2))                         # the sentinel's reply counts for no one


_seed_replies()
REPLY_WINDOW = dict(start=REPLY_DAY, end=REPLY_DAY.replace(hour=23, minute=59, second=59))


def case_a_reply_counts_for_the_employee_whose_own_send_ends_the_wait():
    rows = _read(msg_stats.reply_stats, account_ids=[C3], **REPLY_WINDOW)
    got = _by_key(rows, "employee_id", fields=("replies", "reply_seconds"))
    assert {k: (n, round(sec)) for k, (n, sec) in got.items()} == {(E1,): (2, 1800), (E2,): (1, 1800)}, got


def case_a_wait_begun_before_the_window_is_paired_only_through_the_lookback():
    rows = _read(msg_stats.reply_stats, account_ids=[C3], lookback=timedelta(0), **REPLY_WINDOW)
    got = {r.employee_id: (r.replies, round(r.reply_seconds)) for r in rows}
    assert got[E1] == (1, 600), got  # the 00:10 reply's wait is not seen without the lookback


def case_sales_split_by_channel_to_the_credited_employee_net_of_the_fee_once_it_is_excluded():
    d = datetime(2026, 6, 1)
    direct = _msg(C4, 1, E1, d.replace(hour=8), price=1000)
    mass = _msg(C4, 2, E1, d.replace(hour=8), price=500, mass_run_id=5)
    auto = _msg(C4, 3, E1, d.replace(hour=8), price=700, automation_kind="autoreply")
    _msg(C4, 4, E1, d.replace(hour=7))
    native = _msg(C4, 5, None, d.replace(hour=8), price=900)               # an OF-native mass copy: no sender
    refunded = _msg(C4, 6, E1, d.replace(hour=8), price=400)
    reassigned = _msg(C4, 7, E1, d.replace(hour=8), price=600)
    late = _msg(C4, 8, E1, d.replace(hour=8), price=250)
    _sale(C4, "ppv_message", 1000, d.replace(hour=9), fan=1, message_id=direct)
    _sale(C4, "ppv_message", 500, d.replace(hour=9), fan=2, message_id=mass, status="pending")
    _sale(C4, "ppv_message", 700, d.replace(hour=9), fan=3, message_id=auto)
    _sale(C4, "tip", 300, d.replace(hour=10), fan=4)                       # lookback: E1's 07:00 send
    _sale(C4, "tip_post", 200, d.replace(hour=10), fan=4)
    _sale(C4, "ppv_message", 900, d.replace(hour=9), fan=5, message_id=native)
    _sale(C4, "ppv_message", 400, d.replace(hour=11), fan=6, message_id=refunded, status="refunded")
    # "Exclude the 20% OnlyFans fee" from 12:00: the later sales count fee-less (stored net, else 80%).
    r = OWNER_A.put("/admin/settings/sales", json={"exclude_of_fee": True},
                    params={"effective_from": "2026-06-01T12:00:00Z"})
    assert r.status_code == 200, r.text
    _sale(C4, "ppv_message", 600, d.replace(hour=13), fan=7, message_id=reassigned, reassigned_to=E2)
    _sale(C4, "ppv_message", 250, d.replace(hour=14), fan=8, message_id=late, net=200)
    rows = _read(msg_stats.channel_sales, account_ids=[C4], start=d, end=d.replace(hour=23))
    got = _by_key(rows, "account_id", "employee_id", fields=("direct_cents", "mass_cents", "tip_cents", "spenders"))
    assert got == {(C4, E1): (1200, 500, 300, 3), (C4, E2): (480, 0, 0, 1)}, got
    # Before 12:00 the Rules hold all along, so the sums are read grouped: gross.
    rows = _read(msg_stats.channel_sales, account_ids=[C4], start=d, end=d.replace(hour=11, minute=59))
    got = _by_key(rows, "account_id", "employee_id", fields=("direct_cents", "mass_cents", "tip_cents", "spenders"))
    assert got == {(C4, E1): (1000, 500, 300, 2)}, got


def case_a_priority_mass_sale_is_its_own_channel_and_its_sends_are_not_direct():
    d = datetime(2026, 6, 5)
    c5 = _creator("5200005")
    prio = _msg(c5, 1, E1, d.replace(hour=8), price=800, automation_kind=msg_stats.PRIORITY_MASS_KIND)
    other = _msg(c5, 2, E1, d.replace(hour=8), price=300, automation_kind=msg_stats.PRIORITY_MASS_KIND)
    _sale(c5, "ppv_message", 800, d.replace(hour=9), fan=1, message_id=prio, status="pending")
    _sale(c5, "ppv_message", 300, d.replace(hour=9), fan=2, message_id=other, reassigned_to=E2)
    rows = _read(msg_stats.channel_sales, account_ids=[c5], start=d, end=d.replace(hour=23))
    got = _by_key(rows, "employee_id", fields=("direct_cents", "mass_cents", "priority_cents", "spenders"))
    # The fee is excluded since 1 June 12:00 (the channel case above): 80%.
    assert got == {(E1,): (0, 0, 640, 0), (E2,): (0, 0, 240, 0)}, got
    assert _read(msg_stats.send_stats, account_ids=[c5], start=d, end=d.replace(hour=23)) == []
    r = OWNER_A.get("/admin/stats/chatting-stats?from=2026-06-05&to=2026-06-05")
    assert r.status_code == 200, r.text
    e1 = {e["employee_id"]: e for e in r.json()["employees"]}[E1]
    assert (e1["priority_mass_message_sales_cents"], e1["direct_messages_sent"]) == (640, 0), e1


def _report(client=OWNER_A, status: int = 200) -> dict:
    r = client.get("/admin/stats/chatting-stats?from=2026-04-10&to=2026-04-10")
    assert r.status_code == status, f"{r.status_code} {r.text}"
    return r.json()


def case_the_report_derives_infloww_figures_and_shows_no_automation_row():
    rows = {e["employee_id"]: e for e in _report()["employees"]}
    assert AUTO not in rows and None not in rows, rows.keys()
    e1 = rows[E1]
    want = {"direct_messages_sent": 4, "direct_ppvs_sent": 2, "golden_ratio": 50.0, "ppvs_unlocked": 1,
            "unlock_rate": 50.0, "fans_chatted": 3, "character_count": 11, "sales_cents": 1000,
            "direct_message_sales_cents": 1000, "mass_message_sales_cents": 0, "fans_who_spent": 1,
            "fan_cvr": 33.33, "avg_spend_per_fan_cents": 1000, "replies": 1, "avg_reply_seconds": 300,
            "clocked_minutes": 120, "sales_per_clocked_hour_cents": 500, "messages_per_clocked_hour": 2.0,
            "fans_chatted_per_clocked_hour": 1.5}
    assert {k: e1[k] for k in want} == want, e1
    assert e1["per_account"] == [{"account_id": C1, "account_nickname": "cs_creator_01"},
                                 {"account_id": C2, "account_nickname": "cs_creator_02"}], e1["per_account"]
    assert rows[E2]["golden_ratio"] == 0.0 and rows[E2]["fan_cvr"] == 0.0, rows[E2]
    assert rows[E2]["avg_reply_seconds"] is None and rows[E2]["clocked_minutes"] == 0, rows[E2]


def _roles(enforce: bool, pages: dict, scope: str, emp: int) -> None:
    r = OWNER_A.put("/admin/settings/roles", json={
        "enforce": enforce, "assignments": {str(emp): "role-cs"},
        "roles": [{"id": "role-cs", "name": "Fixture role-cs", "description": "", "permissions": pages,
                   "scope": scope}]})
    assert r.status_code == 200, r.text


def case_role_enforcement_refuses_without_employee_reports_and_a_self_scope_sees_its_own_row():
    emp_a = asyncio.run(employees.get_or_create_mirror_employee(
        IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color="#bbbbbb"))
    _msg(IDS["creator_a"], 41, emp_a, DAY.replace(hour=13))
    _msg(IDS["creator_a"], 42, E2, DAY.replace(hour=13))
    try:
        _roles(True, {"/messages-pro": True}, "all", emp_a)
        assert _report(CHATTER_A, 403) == {"detail": "Your role does not allow Employee reports"}
        _roles(True, {"/analytics/employee-reports": True}, "self", emp_a)
        rows = _report(CHATTER_A)["employees"]
        assert [e["employee_id"] for e in rows] == [emp_a]
        # Clocked time is the Timesheet's, which refuses chatters.
        assert (rows[0]["clocked_minutes"], rows[0]["messages_per_clocked_hour"]) == (None, None), rows[0]
        _roles(True, {"/analytics/employee-reports": True}, "all", emp_a)
        assert {e["employee_id"] for e in _report(CHATTER_A)["employees"]} >= {emp_a, E2}
    finally:
        OWNER_A.put("/admin/settings/roles", json={"enforce": False})


def case_creator_reports_engagement_columns_count_own_sends_and_each_fan_once_per_creator():
    """Creator reports' Reply time, Fans chatted, Messages sent and PPVs sent (roadmap W5 5.3): Creator 1's
    four own sends (no mass, automated or sentinel one), two of them PPVs, to fans 1 and 2 (fan 1 by two
    Employees, counted once), and one reply after 300 s; Creator 2 had no reply to time. Only with
    `engagement=true`: the Dashboard's read stays as it was, Messages sent alone."""
    r = OWNER_A.get("/admin/stats/per-model?from=2026-04-10&to=2026-04-10&engagement=true")
    assert r.status_code == 200, r.text
    rows = {m["account_id"]: m for m in r.json()["per_model"]}
    cols = ("messages_sent", "ppvs_sent", "fans_chatted", "avg_reply_seconds")
    assert {aid: tuple(rows[aid][c] for c in cols) for aid in (C1, C2)} == {
        C1: (4, 2, 2, 300), C2: (1, 0, 1, None)}, rows
    assert tuple(rows[C4][c] for c in cols) == (0, 0, 0, None), rows[C4]
    plain = {m["account_id"]: m for m in OWNER_A.get("/admin/stats/per-model?from=2026-04-10&to=2026-04-10")
             .json()["per_model"]}
    assert (plain[C1]["messages_sent"], plain[C2]["messages_sent"]) == (4, 1), plain
    assert not {"ppvs_sent", "fans_chatted", "avg_reply_seconds"} & plain[C1].keys(), plain[C1]


def case_chatter_only_keeps_the_chatter_roles_employees():
    """Employee reports' "Show employees with chatter role only" (roadmap W5 5.13): only the Employees
    assigned the built-in Chatter role, on both reads; an unassigned Employee and the Unattributed bucket
    are left out. (A login is given the Chatter role when its Employee is made, so chatter_a's is in too.)"""
    r = OWNER_A.put("/admin/settings/roles", json={"enforce": False, "assignments": {str(E1): "chatter"}})
    assert r.status_code == 200, r.text
    try:
        q = "from=2026-04-10&to=2026-04-10"
        every = {e["employee_id"] for e in OWNER_A.get(f"/admin/stats/chatting-stats?{q}").json()["employees"]}
        assert {E1, E2} <= every, every
        held = OWNER_A.get("/admin/settings/roles").json()["config"]["assignments"]
        chatters = {int(eid) for eid, rid in held.items() if rid == "chatter"}
        assert E1 in chatters and E2 not in chatters, held
        only = OWNER_A.get(f"/admin/stats/chatting-stats?{q}&chatter_only=true").json()["employees"]
        assert {e["employee_id"] for e in only} == every & chatters, only
        per = OWNER_A.get(f"/admin/stats/per-employee?{q}&chatter_only=true").json()["employees"]
        assert E1 in {e["employee_id"] for e in per} and {e["employee_id"] for e in per} <= chatters, per
    finally:
        OWNER_A.put("/admin/settings/roles", json={"enforce": False, "assignments": {}})


def _plan(sql: str, params: dict) -> str:
    async def _run():
        async with get_session() as s:
            await s.execute(text("ANALYZE"))
            return (await s.execute(text("EXPLAIN QUERY PLAN " + sql), params)).all()
    return " | ".join(str(r[-1]) for r in asyncio.run(_run()))


def case_the_sends_read_seeks_the_chatter_sends_index():
    plan = _plan(*asyncio.run(msg_stats.send_stats_sql(account_ids=[C1, C2], **WINDOW)))
    assert "USING INDEX ix_messages_chatter_sends (account_id=? AND direction=? AND created_at>? AND created_at<?)" \
        in plan, plan


def case_the_creator_sends_read_seeks_the_chatter_sends_index_and_reads_no_body():
    sql, params = asyncio.run(msg_stats.creator_sends_sql(account_ids=[C1, C2], **WINDOW))
    assert "body" not in sql, sql
    assert "USING INDEX ix_messages_chatter_sends (account_id=? AND direction=? AND created_at>? AND created_at<?)" \
        in _plan(sql, params), sql


def case_the_reply_read_walks_each_chat_on_the_covering_chat_index():
    sql, params = asyncio.run(msg_stats.reply_stats_sql(account_ids=[C3], **REPLY_WINDOW))
    plan = _plan(sql, params)
    assert "COVERING INDEX ix_messages_chat_seq (account_id=? AND fan_id=? AND created_at>? AND created_at<?)" \
        in plan, plan


_harness.run()
