#!/usr/bin/env python3
"""
Message dashboard (roadmap 5.7) filters and reply time, and mass-message sales
attribution from local rows (5.8). No network: everything reads the temp DB.

  case_text_price_unsent_filters:
      `q` searches the body, `min/max_price_cents` bound the price,
      `unsent_only` keeps only unsent rows.
  case_sender_type_splits_employee_from_automation:
      employee = outbound with no automation_kind; automation = the rest of
      outbound; inbound never matches either.
  case_kind_direct_vs_mass:
      direct drops every mass row (and the summary); mass keeps only the
      summary row.
  case_reply_time_against_the_fans_previous_message:
      a reply 90s after the fan's message reads 90; a follow-up after our own
      message reads None; a blast in between does not break the reply.
  case_mass_summary_carries_local_sales:
      the collapsed run row counts bought copies once per fan, at the price;
      a bought funnel follow-up and a refunded copy stay out, a pending one
      counts; the follow-up does not move the row's send time.
  case_filters_pick_runs_but_totals_cover_every_copy:
      an unsent filter that matches one copy shows the run with its full
      recipient count and sales.
  case_mass_list_purchased_and_earnings:
      Settings/Smart Messages' sent list gets purchasedCount/earningsCents
      from the run's copies AND untagged copies carrying OF's queueId; other
      queues and unbought copies stay out.
  case_bad_filter_values_are_400:
      a short or over-long `q`, a negative price, an unknown sender_type or
      kind refuse.

Run: ./venv/bin/python service/tests/test_message_dashboard.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import mass_broadcast_cache  # noqa: E402
from attribution import mass_placeholder_message_id  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, MassBroadcastCache, MassRun, Message, Transaction  # noqa: E402
from messages import list_paid_messages  # noqa: E402

_NOW = datetime(2026, 10, 1, 12, 0, 0)
_FROM = (_NOW - timedelta(days=30)).isoformat()
_TO = (_NOW + timedelta(days=1)).isoformat()


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _add(aid: str, fan_id: int, msg_id: int, *, ago: timedelta,
               direction: str = "out", **kw) -> None:
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=msg_id,
                      direction=direction, created_at=_NOW - ago, **kw))


async def _fetch(aid: str, **kw):
    args = dict(
        request=None, from_=_FROM, to=_TO, account_id=aid,
        employee_id=None, status="all", type_="all", direction="any",
        fan_id=None, fan_query=None, collapse_mass=True, format="json",
        limit=50, before_sent_at=None, before_id=None,
    )
    args.update(kw)
    return (await list_paid_messages(**args))["rows"]


def _ids(rows) -> set[int]:
    return {r["message_id"] for r in rows}


async def case_text_price_unsent_filters():
    aid = "md_filters"
    await _seed_account(aid)
    await _add(aid, 1, 101, ago=timedelta(hours=1), body="Want the shower video?", price_cents=1500)
    await _add(aid, 2, 102, ago=timedelta(hours=2), body="good morning", price_cents=0)
    await _add(aid, 3, 103, ago=timedelta(hours=3), body="SHOWER pics", price_cents=5000,
               is_unsent=True)

    assert _ids(await _fetch(aid, q="shower")) == {101, 103}, "text search is a case-insensitive substring"
    assert _ids(await _fetch(aid, q="%%")) == set(), "a typed % is a character, not a wildcard"
    assert _ids(await _fetch(aid, min_price_cents=1000, max_price_cents=2000)) == {101}
    assert _ids(await _fetch(aid, min_price_cents=1)) == {101, 103}
    rows = await _fetch(aid, unsent_only=True)
    assert _ids(rows) == {103}, rows
    assert rows[0]["is_unsent"] is True


async def case_sender_type_splits_employee_from_automation():
    aid = "md_sender"
    await _seed_account(aid)
    await _add(aid, 1, 201, ago=timedelta(hours=1), body="typed")
    await _add(aid, 2, 202, ago=timedelta(hours=2), body="bot", automation_kind="autoreply")
    await _add(aid, 3, 203, ago=timedelta(hours=3), body="fan says hi", direction="in")

    assert _ids(await _fetch(aid, sender_type="employee")) == {201}
    assert _ids(await _fetch(aid, sender_type="automation")) == {202}
    assert _ids(await _fetch(aid)) == {201, 202, 203}


async def _add_run(aid: str, *, run_id: int, queue_id: int, ago: timedelta,
                   fans: list[int], price_cents: int, bought: set[int]) -> int:
    """A run with one placeholder copy per fan; `bought` fans' copies paid."""
    synth = mass_placeholder_message_id(run_id)
    async with get_session() as s:
        s.add(MassRun(id=run_id, account_id=aid, queue_id=queue_id,
                      audience_filter="{}", recipient_count=len(fans)))
    for fid in fans:
        await _add(aid, fid, synth, ago=ago, body="blast", price_cents=price_cents,
                   mass_run_id=run_id, is_paid=fid in bought)
    return synth


async def case_kind_direct_vs_mass():
    aid = "md_kind"
    await _seed_account(aid)
    await _add(aid, 1, 301, ago=timedelta(hours=1), body="1:1")
    synth = await _add_run(aid, run_id=3001, queue_id=93001, ago=timedelta(hours=2),
                           fans=[5, 6], price_cents=0, bought=set())

    assert _ids(await _fetch(aid, kind="direct")) == {301}
    mass = await _fetch(aid, kind="mass")
    assert _ids(mass) == {synth} and mass[0]["is_mass_summary"], mass


async def case_reply_time_against_the_fans_previous_message():
    aid = "md_reply"
    await _seed_account(aid)
    base = timedelta(hours=5)
    await _add(aid, 1, 401, ago=base, direction="in", body="hey")
    await _add(aid, 1, 402, ago=base - timedelta(seconds=90), body="hi babe")
    await _add(aid, 1, 403, ago=base - timedelta(seconds=300), body="u there?")
    # Fan 2: the fan writes, a blast lands, then the chatter answers.
    async with get_session() as s:
        s.add(MassRun(id=4001, account_id=aid, audience_filter="{}"))
    await _add(aid, 2, 411, ago=base, direction="in", body="hello")
    await _add(aid, 2, 412, ago=base - timedelta(seconds=30), body="blast",
               mass_run_id=4001, automation_kind="send_mass_message")
    await _add(aid, 2, 413, ago=base - timedelta(seconds=60), body="sorry, here now")

    rows = {r["message_id"]: r for r in await _fetch(aid, kind="direct")}
    assert rows[402]["reply_seconds"] == 90, rows[402]
    assert rows[403]["reply_seconds"] is None, "a follow-up to our own message is not a reply"
    assert rows[401]["reply_seconds"] is None, "inbound rows carry no reply time"
    assert rows[413]["reply_seconds"] == 60, "a blast in between must not hide the reply"


async def _add_tx(aid: str, fan_id: int, msg_id: int, status: str) -> None:
    async with get_session() as s:
        s.add(Transaction(account_id=aid, fan_id=fan_id, message_id=msg_id,
                          kind="ppv_message", amount_cents=1200, status=status,
                          occurred_at=_NOW - timedelta(hours=1)))


async def case_mass_summary_carries_local_sales():
    aid = "md_summary"
    await _seed_account(aid)
    synth = await _add_run(aid, run_id=5001, queue_id=95001, ago=timedelta(hours=2),
                           fans=[1, 2, 3, 4], price_cents=1200, bought={1, 3, 4})
    # Fan 2 bought the funnel's follow-up step, which rides the run's id: that
    # is the follow-up's sale, not the blast's.
    await _add(aid, 2, 50002, ago=timedelta(hours=1), body="step 2", price_cents=900,
               mass_run_id=5001, funnel_step=2, is_paid=True)
    await _add_tx(aid, 1, synth, "pending")      # pending counts (owner rule)
    await _add_tx(aid, 4, synth, "chargedback")  # refunded / charged back does not
    m = next(r for r in await _fetch(aid) if r["is_mass_summary"])
    assert m["purchased_count"] == 2, m
    assert m["earnings_cents"] == 2400, m
    assert m["sent_at"] == (_NOW - timedelta(hours=2)).isoformat(), \
        "the later follow-up must not move the broadcast's send time"


async def case_filters_pick_runs_but_totals_cover_every_copy():
    aid = "md_pick"
    await _seed_account(aid)
    synth = await _add_run(aid, run_id=5101, queue_id=95101, ago=timedelta(hours=2),
                           fans=[1, 2, 3], price_cents=500, bought={2, 3})
    async with get_session() as s:
        row = await s.get(Message, {"account_id": aid, "fan_id": 1, "message_id": synth})
        row.is_unsent = True
    rows = await _fetch(aid, unsent_only=True)
    assert _ids(rows) == {synth}, rows
    m = rows[0]
    assert (m["recipient_count"], m["purchased_count"], m["earnings_cents"]) == (3, 2, 1000), m


async def case_mass_list_purchased_and_earnings():
    aid = "md_masslist"
    await _seed_account(aid)
    sent = _NOW - timedelta(hours=6)
    # Queue A: our run (two placeholder copies, one bought) plus an untagged
    # scraped copy carrying OF's queueId (bought), plus that buyer's
    # placeholder still standing beside it (must count once).
    await _add_run(aid, run_id=6001, queue_id=96001, ago=timedelta(hours=6),
                   fans=[1, 2, 3], price_cents=1000, bought={1, 3})
    await _add(aid, 3, 70003, ago=timedelta(hours=6), body="blast", price_cents=1000,
               is_paid=True, raw_json=json.dumps({"id": 70003, "queueId": 96001}))
    await _add(aid, 4, 70004, ago=timedelta(hours=6), body="blast", price_cents=1000,
               is_paid=True, raw_json=json.dumps({"id": 70004, "queueId": 96001}))
    # Queue B: a copy bought, but of another broadcast; and an unbought copy.
    await _add(aid, 5, 70005, ago=timedelta(hours=6), body="other", price_cents=800,
               is_paid=True, raw_json=json.dumps({"id": 70005, "queueId": 96002}))
    await _add(aid, 6, 70006, ago=timedelta(hours=6), body="other", price_cents=800,
               is_paid=False, raw_json=json.dumps({"id": 70006, "queueId": 96002}))
    async with get_session() as s:
        for qid in (96001, 96002, 96003):
            s.add(MassBroadcastCache(account_id=aid, queue_id=qid, sent_at=sent,
                                     sent_count=10, fetched_at=_NOW))

    items = {i["id"]: i for i in await mass_broadcast_cache.list_for_account(aid)}
    assert (items[96001]["purchasedCount"], items[96001]["earningsCents"]) == (3, 3000), items[96001]
    assert (items[96002]["purchasedCount"], items[96002]["earningsCents"]) == (1, 800), items[96002]
    assert (items[96003]["purchasedCount"], items[96003]["earningsCents"]) == (0, 0), items[96003]


async def case_bad_filter_values_are_400():
    for kw in ({"q": "x"}, {"q": "x" * 201}, {"min_price_cents": -1},
               {"max_price_cents": -5}, {"sender_type": "robot"}, {"kind": "group"}):
        try:
            await _fetch("md_filters", **kw)
        except HTTPException as e:
            assert e.status_code == 400, (kw, e.status_code)
        else:
            raise AssertionError(f"{kw} was accepted")


_harness.run(
    case_text_price_unsent_filters,
    case_sender_type_splits_employee_from_automation,
    case_kind_direct_vs_mass,
    case_reply_time_against_the_fans_previous_message,
    case_mass_summary_carries_local_sales,
    case_filters_pick_runs_but_totals_cover_every_copy,
    case_mass_list_purchased_and_earnings,
    case_bad_filter_values_are_400,
)
