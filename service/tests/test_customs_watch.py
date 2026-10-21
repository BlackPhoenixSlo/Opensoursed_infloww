#!/usr/bin/env python3
"""test_customs_watch.py — the automation that turns a tip into owed work.

`test_customs.py` covers the pure helpers. This covers the thing that actually
writes: it reads transactions and stamps `fans.customs_owed_at`. Every case below
is a way it could have silently done the wrong thing to a live account.

⚠️ IT NO LONGER TOUCHES ONLYFANS, AND `_no_of()` BELOW ENFORCES THAT. The debt
used to be a " Custom" suffix pushed to the fan's OF display name, which the chat
engines rebuilt from structured facts every 60s — so the mark was erased about a
minute after it was written, on both surfaces. The moment this module reaches for
an OF client again, the ledger is back in the path of the thing that erased it.

House style: plain assert, no pytest; _harness temp DB; a fake OF client so
nothing leaves the box.

Run:  ./venv/bin/python service/tests/test_customs_watch.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import os  # noqa: E402

# The context cases drive admin route coroutines directly, with no signed-in
# principal. assert_account_owned fails closed on anonymous since 2026-08-10;
# this env flag is its documented escape hatch, read per call so tests can flip it.
os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

from datetime import datetime, timedelta  # noqa: E402

import automation_executor as ax  # noqa: E402
from automations import _customs  # noqa: E402
from automations import customs_watch as cw  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AutomationRule, Fan, Message, MessageMedia,
    ScheduledJob, Transaction,
)

_NOW = datetime.utcnow()


def _no_of() -> None:
    """TRIPWIRE, not a stub. `customs_watch` must never build an OF client — see
    the module docstring. Any attempt fails the case that made it."""
    def _boom(*a, **k):
        raise AssertionError(
            "customs_watch built an OF client — the owed marker must never go "
            "back onto a nickname (see automations/_customs)"
        )
    ax._make_client = _boom  # type: ignore[assignment]


async def _seed(aid: str, fid: int, *, nick=None, tip_cents=None,
                tip_kind="tip", tip_age_h=1.0) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        if await s.get(Fan, (aid, fid)) is None:
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name="Bob",
                      custom_nickname=nick))
        if tip_cents is not None:
            s.add(Transaction(account_id=aid, fan_id=fid, kind=tip_kind,
                              amount_cents=tip_cents,
                              occurred_at=_NOW - timedelta(hours=tip_age_h)))
        await s.commit()


async def _send_media(aid: str, fid: int, msg_id: int, mtype: str,
                      *, price_cents: int = 0, age_h: float = 0.5,
                      direction: str = "out") -> None:
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fid, message_id=msg_id,
                      direction=direction, sender_name="", body="",
                      media_ids="[]", media_count=1, price_cents=price_cents,
                      is_tip=False, is_unsent=False,
                      created_at=_NOW - timedelta(hours=age_h)))
        s.add(MessageMedia(account_id=aid, fan_id=fid, message_id=msg_id,
                           media_id=msg_id, type=mtype))
        await s.commit()


async def _owed(aid: str, fid: int) -> bool:
    """Is he owed a custom? The ledger, read the way every engine reads it."""
    async with get_session() as s:
        f = await s.get(Fan, (aid, fid))
        return _customs.is_owed(f)


async def _nick(aid: str, fid: int) -> str | None:
    async with get_session() as s:
        f = await s.get(Fan, (aid, fid))
        return f.custom_nickname if f else None


async def case_a_dm_tip_marks_the_fan_and_leaves_his_name_alone():
    aid, fid = "cw_mark", 1
    await _seed(aid, fid, nick="Alex (VIP)", tip_cents=20_000)
    _no_of()

    st = await cw.run(aid, {}, run_id=1)
    assert st["marked"] == 1, st
    assert await _owed(aid, fid)
    # The debt is a column. His NAME is untouched — that is the whole fix.
    assert await _nick(aid, fid) == "Alex (VIP)"


async def case_running_twice_does_not_double_mark():
    """The scanner runs every tick over the same tip. "Alex Custom Custom" would
    be both ugly and un-clearable in one operator gesture."""
    aid, fid = "cw_twice", 1
    await _seed(aid, fid, nick="Alex", tip_cents=20_000)
    _no_of()

    await cw.run(aid, {}, run_id=1)
    st = await cw.run(aid, {}, run_id=2)
    assert st["already_marked"] == 1, st
    assert st["marked"] == 0, st
    assert await _owed(aid, fid)


async def case_a_post_tip_is_generosity_not_an_order():
    aid, fid = "cw_post", 1
    await _seed(aid, fid, nick="Alex", tip_cents=20_000, tip_kind="tip_post")
    _no_of()

    st = await cw.run(aid, {}, run_id=1)
    assert st["marked"] == 0, st
    assert await _nick(aid, fid) == "Alex"


async def case_a_stacked_burst_marks_like_one_big_tip():
    """The watch judges the ORDER, not each transaction — the same
    `_customs.orders_per_fan` the /customs queue displays. Two $30 tips
    minutes apart are a $60 order at the $50 floor; the per-tip SQL prefilter
    used to drop both halves and the queue showed an order the watch would
    never mark."""
    aid, fid = "cw_burst", 1
    await _seed(aid, fid, nick="Alex", tip_cents=3_000, tip_age_h=0.2)
    await _seed(aid, fid, tip_cents=3_000, tip_age_h=0.1)
    _no_of()

    st = await cw.run(aid, {}, run_id=1)
    assert st["marked"] == 1, st
    assert await _owed(aid, fid)


async def case_two_sub_floor_tips_far_apart_stay_generosity():
    """Outside the burst window they are two separate sub-floor tips — two
    acts of generosity, not one stacked order."""
    aid, fid = "cw_burst_far", 1
    await _seed(aid, fid, nick="Alex", tip_cents=3_000, tip_age_h=5.0)
    await _seed(aid, fid, tip_cents=3_000, tip_age_h=0.1)
    _no_of()

    st = await cw.run(aid, {}, run_id=1)
    assert st["marked"] == 0, st
    assert not await _owed(aid, fid)


async def case_under_the_floor_is_not_an_order():
    aid, fid = "cw_small", 1
    await _seed(aid, fid, nick="Alex", tip_cents=4_000)
    _no_of()

    st = await cw.run(aid, {}, run_id=1)
    assert st["marked"] == 0, st


async def case_a_tip_already_fulfilled_is_never_resurrected():
    """Switching the feature on must not mark work that was already done —
    otherwise the first run creates a queue of phantom debt and the account
    stops selling to everyone who ever bought a custom."""
    aid, fid = "cw_done", 1
    await _seed(aid, fid, nick="Alex", tip_cents=20_000, tip_age_h=3)
    await _send_media(aid, fid, 9001, "audio", age_h=1)   # after the tip
    _no_of()

    st = await cw.run(aid, {}, run_id=1)
    assert st["skipped_delivered"] == 1, st
    assert st["marked"] == 0, st
    assert not await _owed(aid, fid)


async def case_a_voice_note_clears_the_marker():
    """The operator clearing it by hand is the authority — but a hand-clear that
    is FORGOTTEN leaves the account unable to sell to its best fan forever, and
    the brake has no timeout on purpose."""
    aid, fid = "cw_clear", 1
    await _seed(aid, fid, nick="Alex", tip_cents=20_000, tip_age_h=3)
    _no_of()

    await cw.run(aid, {}, run_id=1)
    assert await _owed(aid, fid)

    await _send_media(aid, fid, 9002, "audio", age_h=1)
    st = await cw.run(aid, {}, run_id=2)
    assert st["cleared"] == 1, st
    assert not await _owed(aid, fid)


async def case_no_video_priced_or_free_ever_clears_a_debt():
    """The product is a voice note, so only a voice note can settle one.

    A PRICED video never could — it is a new sale, and the live male accounts
    carry 170 of them against 9 free ones. A FREE video used to, for a "short
    video" product that is not being built, and that was a live false-clear: the
    clear loop fell back to its 72h sweep window when the originating tip aged
    out, so ANY free outbound video in three days settled an older debt. A mass
    send would do it. So would a tip_reward freebie."""
    aid, fid = "cw_ppv", 1
    await _seed(aid, fid, nick="Alex", tip_cents=20_000, tip_age_h=3)
    _no_of()
    await cw.run(aid, {}, run_id=1)

    await _send_media(aid, fid, 9003, "video", price_cents=4_444, age_h=1)
    st = await cw.run(aid, {}, run_id=2)
    assert st["cleared"] == 0, st
    assert await _owed(aid, fid), "a PPV cleared the debt"

    await _send_media(aid, fid, 9004, "video", price_cents=0, age_h=0.5)
    st2 = await cw.run(aid, {}, run_id=3)
    assert st2["cleared"] == 0, st2
    assert await _owed(aid, fid), "a free video cleared the debt"

    # Only the voice note does.
    await _send_media(aid, fid, 9006, "audio", age_h=0.25)
    st3 = await cw.run(aid, {}, run_id=4)
    assert st3["cleared"] == 1, st3
    assert not await _owed(aid, fid)


async def case_an_inbound_video_never_counts_as_delivery():
    """A fan sending HIS video is not the creator delivering one."""
    aid, fid = "cw_inbound", 1
    await _seed(aid, fid, nick="Alex", tip_cents=20_000, tip_age_h=3)
    _no_of()
    await cw.run(aid, {}, run_id=1)

    await _send_media(aid, fid, 9005, "audio", age_h=1, direction="in")
    st = await cw.run(aid, {}, run_id=2)
    assert st["cleared"] == 0, st
    assert await _owed(aid, fid)


async def case_customer_service_is_not_owed_a_custom():
    """gen_info writes job titles into nicknames, and prod has
    "Johny/Colombia/31/Customer Service". A substring match marks him owed
    forever AND chews "Customer" out of his name when it clears."""
    aid, fid = "cw_trap", 1
    await _seed(aid, fid, nick="Johny/Colombia/31/Customer Service")
    _no_of()

    st = await cw.run(aid, {}, run_id=1)
    assert st["cleared"] == 0, st
    assert not await _owed(aid, fid)
    assert await _nick(aid, fid) == "Johny/Colombia/31/Customer Service"


async def case_dry_run_writes_nothing():
    aid, fid = "cw_dry", 1
    await _seed(aid, fid, nick="Alex", tip_cents=20_000)
    _no_of()

    st = await cw.run(aid, {"dry_run": True}, run_id=1)
    assert st["marked"] == 1, st
    assert not await _owed(aid, fid), "dry run mutated the DB"


async def case_money_that_did_not_arrive_is_not_an_order():
    """A refunded or charged-back tip must not put a man in the work queue.

    This query never filtered `Transaction.status`, while the (since-removed)
    ai_chatter `_tip_sum_since` always had — so the two engines disagreed about whether the
    same $200 was real, and the only way out of a phantom debt was a human
    noticing. 'pending' DOES count: it is money in flight, and the fan believes
    he ordered."""
    for status, expect_marked in (("cleared", 1), ("pending", 1),
                                  ("refunded", 0), ("chargeback", 0)):
        aid, fid = f"cw_status_{status}", 1
        await _seed(aid, fid, nick="Alex")
        async with get_session() as s:
            s.add(Transaction(account_id=aid, fan_id=fid, kind="tip",
                              amount_cents=20_000, status=status,
                              occurred_at=_NOW - timedelta(hours=1)))
            await s.commit()
        _no_of()
        st = await cw.run(aid, {}, run_id=1)
        assert st["marked"] == expect_marked, (status, st)
        assert await _owed(aid, fid) is bool(expect_marked), status


async def case_the_lookback_bounds_what_switching_it_on_marks():
    """72h by default so enabling the feature does not mark every historical
    $200 an account has ever taken."""
    aid, fid = "cw_old", 1
    await _seed(aid, fid, nick="Alex", tip_cents=20_000, tip_age_h=200)
    _no_of()

    st = await cw.run(aid, {}, run_id=1)
    assert st["marked"] == 0, st
    # …and it is a knob, so an operator can deliberately sweep further back.
    st2 = await cw.run(aid, {"lookback_hours": 500}, run_id=2)
    assert st2["marked"] == 1, st2


async def case_an_operator_clear_is_not_undone_by_the_next_sweep():
    """THE defect the review found, and the one that made the feature actively
    annoying rather than merely incomplete.

    "Owed" used to be derived entirely from live conditions — a qualifying tip in
    the window, no marker, no DETECTED delivery — so there was no "done" state at
    all and clearing the marker was indistinguishable from never having marked
    it. The operator hits Sent, and 15 minutes later the scanner sees the same
    tip still inside its 72h window and re-marks it. On a loop, for three days,
    while the account stays unable to sell to that fan.

    The delivery detector hid this in every other test here: seeding a voice note
    makes the re-mark path unreachable. The real case is a custom delivered by
    any route OnlyFans cannot see, which is most of them."""
    aid, fid = "cw_resettle", 1
    await _seed(aid, fid, nick="Alex", tip_cents=20_000, tip_age_h=2)
    _no_of()

    await cw.run(aid, {}, run_id=1)
    assert await _owed(aid, fid)

    # The operator hits Sent on /customs, with NO OF-visible delivery. That is
    # exactly `_customs.clear`: blank the debt AND stamp settled.
    async with get_session() as s:
        f = await s.get(Fan, (aid, fid))
        assert _customs.clear(f)
        await s.commit()

    st = await cw.run(aid, {}, run_id=2)
    assert st["already_settled"] == 1, st
    assert st["marked"] == 0, st
    assert not await _owed(aid, fid), "the operator's clear was undone"


async def case_a_tip_after_the_clear_is_a_new_order():
    """Settling must not deafen the fan permanently — a man who buys a second
    custom after the first shipped is owed a second one."""
    aid, fid = "cw_second", 1
    await _seed(aid, fid, nick="Alex", tip_cents=20_000, tip_age_h=5)
    _no_of()
    await cw.run(aid, {}, run_id=1)

    async with get_session() as s:
        f = await s.get(Fan, (aid, fid))
        f.customs_owed_at = None
        f.customs_cleared_at = _NOW - timedelta(hours=4)
        await s.commit()

    # …he orders again, AFTER the settle.
    async with get_session() as s:
        s.add(Transaction(account_id=aid, fan_id=fid, kind="tip",
                          amount_cents=20_000,
                          occurred_at=_NOW - timedelta(hours=1)))
        await s.commit()

    st = await cw.run(aid, {}, run_id=2)
    assert st["marked"] == 1, st
    assert await _owed(aid, fid)


# ── the queue API: order totals, the anchor, and the backread ───────────────
#
# `customs_api` had no coverage at all until the second review — a public
# endpoint doing auth, timestamp parsing, two queries and HTML stripping, shipped
# on a manual curl.

async def case_an_order_is_the_burst_total_not_the_biggest_tip():
    """Fans STACK tips to reach a price, and prod is full of it: $200+$100 25s
    apart, $200+$80 at 28min, $200+$50 at 5min, $150+$80, $100+$54.

    The first version filtered each transaction against the floor in SQL and
    summed the survivors, which — at the $100 floor of the day — understated
    every one of those by the sub-floor half and made $60+$60 invisible
    entirely. The floor is a question about the ORDER; asking it of each
    transaction asks the wrong thing about the wrong noun. The asserts below
    re-tell that story with halves under today's $50 floor."""
    import customs_api as api
    n = datetime(2026, 6, 19, 3, 34, 13)

    def tip(cents, mins_before):
        return ("a", 1, cents, n - timedelta(minutes=mins_before), None)

    def total(rows):
        got = _customs.orders_per_fan(rows)
        return got[("a", 1)][0] if ("a", 1) in got else None

    assert total([tip(20_000, 0), tip(4_000, 28)]) == 24_000, "sub-floor half dropped"
    assert total([tip(3_000, 0), tip(3_000, 5)]) == 6_000, "$30+$30 is a real order"
    assert total([tip(4_000, 0)]) is None, "one sub-floor tip is not an order"
    # Far apart is a PREVIOUS order, not part of this one.
    assert total([tip(20_000, 0), tip(8_000, 300)]) == 20_000

    # The anchor is the NEWEST tip in the burst — what "waiting since" counts
    # from and what the chat link opens on.
    _, at, _ = _customs.orders_per_fan([tip(10_000, 0), tip(10_000, 10)])[("a", 1)]
    assert at == n


async def case_context_anchor_converts_a_zoned_timestamp():
    """`.replace(tzinfo=None)` DISCARDS an offset instead of converting, so
    "03:11:48+02:00" anchored at 03:11 rather than 01:11 and read two hours of
    the wrong conversation. The column is tz-naive UTC."""
    import customs_api as api
    aid, fid = "cw_tz", 1
    await _seed(aid, fid)
    for i, (body, mins) in enumerate(
            [("two hours before", 130), ("at the anchor", 0)]):
        async with get_session() as s:
            s.add(Message(account_id=aid, fan_id=fid, message_id=7000 + i,
                          direction="in", sender_name="", body=f"<p>{body}</p>",
                          media_ids="[]", media_count=0, price_cents=0,
                          is_tip=False, is_unsent=False,
                          created_at=datetime(2026, 6, 19, 1, 11, 48)
                          - timedelta(minutes=mins)))
            await s.commit()

    zoned = await api.customs_context(account_id=aid, fan_id=fid,
                                      at="2026-06-19T03:11:48+02:00",
                                      before=5, after=0)
    assert zoned["anchor_at"].startswith("2026-06-19T01:11:48"), zoned["anchor_at"]
    # Naive input is already UTC by the same convention and must NOT move.
    naive = await api.customs_context(account_id=aid, fan_id=fid,
                                      at="2026-06-19T01:11:48", before=5, after=0)
    assert naive["anchor_at"] == zoned["anchor_at"]


async def case_context_reads_around_the_tip_and_strips_html():
    """The backread is the answer to "how do we know what to do with this row" —
    the tip says a man paid, the messages around it say what he paid FOR."""
    import customs_api as api
    aid, fid = "cw_ctx", 1
    await _seed(aid, fid)
    base = datetime(2026, 6, 19, 3, 0, 0)
    rows = [("<p>what do i get for 100</p>", "in", -20),
            ("<p>make it 150 and i go over 6 min</p>", "out", -10),
            ("I sent you a $150.00 tip", "in", 0),
            ("<p>lingerie and stockings please</p>", "in", 5)]
    for i, (body, direction, mins) in enumerate(rows):
        async with get_session() as s:
            s.add(Message(account_id=aid, fan_id=fid, message_id=8000 + i,
                          direction=direction, sender_name="", body=body,
                          media_ids="[]", media_count=0, price_cents=0,
                          is_tip=(mins == 0), is_unsent=False,
                          created_at=base + timedelta(minutes=mins)))
            await s.commit()

    res = await api.customs_context(account_id=aid, fan_id=fid,
                                    at=base.isoformat(), before=5, after=5)
    texts = [m["text"] for m in res["messages"]]
    assert "what do i get for 100" in texts, texts          # HTML stripped
    assert "lingerie and stockings please" in texts, "after-window missing"
    assert texts == sorted(texts, key=lambda t: texts.index(t))  # chronological
    assert any(m["is_tip"] for m in res["messages"])
    assert res["messages"][0]["from_fan"] is True

    # `before`/`after` are the bound — a count window, because a TIME window is
    # empty on a slow thread and unbounded on a fast one.
    tight = await api.customs_context(account_id=aid, fan_id=fid,
                                      at=base.isoformat(), before=1, after=0)
    assert len(tight["messages"]) == 1, tight


async def case_context_survives_a_fan_with_nothing_stored():
    import customs_api as api
    aid, fid = "cw_empty", 1
    await _seed(aid, fid)
    # `at=None` explicitly: calling the endpoint function directly bypasses
    # FastAPI's dependency resolution, so an omitted arg is the Query object
    # rather than its default — truthy, and it would reach the parser.
    res = await api.customs_context(account_id=aid, fan_id=fid, at=None,
                                    before=5, after=5)
    assert res["messages"] == [], res
    assert res["anchor_at"] is None


async def _rule(aid: str, *, enabled: bool = True, steps: dict | None = None) -> None:
    """Give `aid` a customs_watch rule — the switch the live dispatcher reads."""
    import json as _json
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(AutomationRule(
            account_id=aid, name="customs_watch", kind="customs_watch",
            trigger_json=_json.dumps({"every_seconds": 900}),
            steps_json=_json.dumps(steps or {}), is_enabled=enabled))
        await s.commit()


async def _queued(aid: str, kind: str) -> list[dict]:
    """The jobs the dispatcher actually enqueued, payloads decoded."""
    import json as _json
    from sqlalchemy import select
    async with get_session() as s:
        rows = (await s.execute(
            select(ScheduledJob.payload_json).where(
                ScheduledJob.account_id == aid, ScheduledJob.kind == kind)
        )).all()
    return [_json.loads(r[0] or "{}") for r in rows]


# ── The send-side brake ──────────────────────────────────────────────
# `_customs.is_owed` needs a Fan row, so it only ever bound the three engines that
# TALK. The engines that SELL on their own schedule build an EXCLUDE SET and never
# load a Fan — so a man who had just paid $200 for a voice note could still be
# sent a PPV blast, a tip ask, or a re-engagement DM on the next tick.


async def case_the_owed_set_is_exactly_the_men_who_paid():
    aid = "cw_owedset"
    await _seed(aid, 1, tip_cents=20_000)     # will be marked
    await _seed(aid, 2, tip_cents=4_000)      # under the floor — not an order
    await _seed(aid, 3)                       # never tipped
    _no_of()
    await cw.run(aid, {}, run_id=1)

    owed = await _customs.owed_fan_ids(aid)
    assert owed == {1}, owed
    # Account-scoped: another model's debt is not this one's exclude set.
    assert await _customs.owed_fan_ids("cw_nobody") == set()


# ── The live tip hook ────────────────────────────────────────────────
# The sweep is a 900s rule, so up to 15 minutes late. The tip's Transaction row
# is written live by the WS pump, so only the CADENCE was slow.


async def case_a_live_tip_marks_him_without_waiting_for_the_sweep():
    import webhook_dispatch as wd
    aid, fid = "cw_live", 5
    await _rule(aid)
    await _seed(aid, fid, tip_cents=20_000, tip_age_h=0.0)
    _no_of()

    await wd.on_inbound_tip(aid, fid, message_id=1, tip_cents=20_000)
    jobs = await _queued(aid, "customs_watch")
    assert len(jobs) == 1, jobs
    assert jobs[0].get("only_fan_ids") == [fid], jobs
    # And that job, when it runs, marks him — the fast path reuses the SAME rule.
    await cw.run(aid, jobs[0], run_id=2)
    assert await _owed(aid, fid)


async def case_the_live_hook_is_deaf_where_a_big_tip_is_generosity():
    """A $100 DM tip is an ORDER on the male accounts and was GENEROSITY five
    times last month on the female ones. Firing account-blind would gag the bot on
    every generous fan — Amia took 47 such tips in 90 days."""
    import webhook_dispatch as wd
    aid, fid = "cw_live_norule", 7
    await _seed(aid, fid, tip_cents=20_000, tip_age_h=0.0)   # NO rule at all
    _no_of()
    await wd.on_inbound_tip(aid, fid, message_id=1, tip_cents=20_000)
    assert await _queued(aid, "customs_watch") == []

    off, off_fid = "cw_live_ruleoff", 8                       # rule present, OFF
    await _rule(off, enabled=False)
    await _seed(off, off_fid, tip_cents=20_000, tip_age_h=0.0)
    await wd.on_inbound_tip(off, off_fid, message_id=1, tip_cents=20_000)
    assert await _queued(off, "customs_watch") == []


async def case_the_live_hook_honours_the_per_account_floor():
    """The fast path and the sweep read ONE floor — the rule's own payload."""
    import webhook_dispatch as wd
    aid = "cw_live_floor"
    # ABOVE the global default on purpose: fan 2's tip clears the default but
    # not this floor, so a hook that fell back to the default would queue him.
    await _rule(aid, steps={"min_cents": 15_000})    # this account: $150 is an order
    await _seed(aid, 1, tip_cents=20_000, tip_age_h=0.0)
    await _seed(aid, 2, tip_cents=6_000, tip_age_h=0.0)
    _no_of()

    await wd.on_inbound_tip(aid, 1, message_id=1, tip_cents=20_000)
    await wd.on_inbound_tip(aid, 2, message_id=2, tip_cents=6_000)
    jobs = await _queued(aid, "customs_watch")
    assert len(jobs) == 1 and jobs[0]["only_fan_ids"] == [1], jobs
    # The rule's payload rides along, so the job cannot run on a different floor.
    assert jobs[0].get("min_cents") == 15_000, jobs


async def case_a_dispatch_failure_never_costs_the_message():
    """The WS pump calls this. It must not raise, whatever the DB does."""
    import webhook_dispatch as wd
    from automations import customs_watch as _cw

    async def _boom(*a, **k):
        raise RuntimeError("db gone")
    orig, _cw.watch_flags = _cw.watch_flags, _boom
    try:
        await wd.on_inbound_tip("cw_live_boom", 9, message_id=1, tip_cents=20_000)
    finally:
        _cw.watch_flags = orig



async def case_the_queue_ships_the_handle_the_operator_pastes():
    """Operator ruling 2026-09-05: *"you need to copy and paste the exact
    username, which account, and what the customer said"*.

    The row used to carry only `display_name`, which FALLS BACK to the username
    — so on a fan with a handle the two render identically and the omission is
    invisible, and on a fan with a display name ("Bob") the operator copies a
    string that OnlyFans search cannot find. `of_username` therefore ships as its
    own field, empty when we genuinely have no handle, so the UI can say so
    instead of passing a display name off as one."""
    import customs_api
    aid = "cw_handle"
    await _seed(aid, 1, tip_cents=20_000)          # display name only, no handle
    await _seed(aid, 2, tip_cents=20_000)
    async with get_session() as s:
        f = await s.get(Fan, (aid, 2))
        f.of_username = "dennis_x"
        f.of_display_name = "Dennis 🔥"
        await s.commit()
    _no_of()
    await cw.run(aid, {}, run_id=1)

    rows = {r["fan_id"]: r
            for r in (await customs_api.list_customs(account_id=aid))["customs"]}
    assert set(rows) == {1, 2}, rows
    # The handle is present and is NOT the display name.
    assert rows[2]["of_username"] == "dennis_x", rows[2]
    assert rows[2]["display_name"] == "Dennis 🔥", rows[2]
    # No handle stored → None, never a display name wearing one's clothes.
    assert rows[1]["of_username"] is None, rows[1]
    assert rows[1]["display_name"] == "Bob", rows[1]
    # And the account, the operator's second line, rides with it.
    assert rows[2]["account_name"], rows[2]


async def _say(aid: str, fid: int, when: datetime, direction: str, body: str,
               *, mid: int, is_tip: bool = False) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        if await s.get(Fan, (aid, fid)) is None:
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name="F"))
        s.add(Message(account_id=aid, fan_id=fid, message_id=mid,
                      direction=direction, sender_name="", body=body,
                      media_ids="[]", media_count=0, price_cents=0,
                      is_tip=is_tip, is_unsent=False, created_at=when))
        await s.commit()


async def case_the_order_is_found_two_months_behind_the_tip():
    """THE OPERATOR'S 2026-09-05 COMPLAINT, reproduced from live Blake1.

    Fan 80000815 placed his order on 2026-07-06 and was still paying it off in
    $100 instalments on 2026-09-02 — a LAYAWAY custom. The tip that put him on
    the queue is 58 days and several hundred messages after the ask, so every
    window measured around the money reads small talk: what `customs_context`
    actually returns for him is "Not much sir what's up with you".

    The words below are his, lifted from the live thread. The assertion is the
    whole feature: the sentence that says what to record has to come back."""
    import customs_api
    aid, fid = "cw_order_layaway", 80000815
    ask = ("I'd love for in the custom you send me to talk about making a law "
           "to force all fags to transition")
    base = datetime(2026, 7, 6, 3, 27)
    await _say(aid, fid, base, "in", f"<p>{ask}</p>", mid=1)
    # 58 days of chat carrying no order talk, then the tip that surfaces him.
    for i in range(40):
        await _say(aid, fid, base + timedelta(days=1, hours=i),
                   "in", "<p>Not much sir what's up with you</p>", mid=100 + i)
    await _say(aid, fid, base + timedelta(days=57), "in",
               "I sent you a $100.00 tip", mid=900, is_tip=True)

    res = await customs_api.customs_order(account_id=aid, fan_id=fid)
    texts = " | ".join(l["text"] for l in res["lines"])
    assert "force all fags to transition" in texts, texts
    # The small talk is what the old window returned INSTEAD; it must not be
    # what drowns the ask now.
    assert res["count"] <= 12, res["count"]


async def case_a_finished_older_order_is_not_mixed_into_the_live_one():
    """Live Blake1 fan 370246851 has a COMPLETED 2024 custom and a live 2026 one
    in the same thread. Without the gap rule the span opens in November 2024 and
    the operator reads two years of two different jobs as though they were one.

    Also pins the other half of that row: his spec is SPLIT across two messages
    31 hours apart and then renegotiated BY US ("ten minutes, no cuts"), so a
    longest-single-message or fan-only view loses the order that was agreed."""
    import customs_api
    aid, fid = "cw_order_twojobs", 370246851
    await _say(aid, fid, datetime(2024, 11, 20, 23, 17), "in",
               "<p>How much for a custom video where you coach me</p>", mid=1)
    await _say(aid, fid, datetime(2024, 12, 2, 6, 1), "out",
               "<p>you will have to tip for the custom vid first</p>", mid=2)
    # …16 months of nothing, then the LIVE order.
    await _say(aid, fid, datetime(2026, 9, 3, 4, 6), "in",
               "<p>remind me- how much for a custom trainer</p>", mid=10)
    await _say(aid, fid, datetime(2026, 9, 3, 4, 11), "in",
               "<p>Just train me to the mindset, wore the hat and shirtless</p>",
               mid=11)
    await _say(aid, fid, datetime(2026, 9, 4, 11, 24), "in",
               "<p>five minute video. what I described is the content</p>", mid=12)
    await _say(aid, fid, datetime(2026, 9, 4, 19, 29), "out",
               "<p>ten mnutes, no cuts, that covers the hat, the toy</p>", mid=13)

    res = await customs_api.customs_order(account_id=aid, fan_id=fid)
    texts = " | ".join(l["text"] for l in res["lines"])
    assert res["opened_at"].startswith("2026-09-03"), res["opened_at"]
    assert "coach me" not in texts, "the finished 2024 job leaked into the span"
    # Both halves of the split ask, and OUR renegotiation — the spec is settled
    # in the back-and-forth, so a fan-only view is not the order.
    assert "wore the hat" in texts, texts
    assert "five minute video" in texts, texts
    assert "ten mnutes, no cuts" in texts, texts


async def case_our_own_mass_marketing_is_not_his_order():
    """Our PPV blast copy is the loudest thing in the thread and is written in
    exactly the words an order is written in ("every set, every clip"). On the
    live rows a plain keyword scan returned mostly this, which IS the operator's
    "not clear enough". A line we sent to more than one fan is marketing."""
    import customs_api
    aid = "cw_order_blast"
    blast = ("<p>75% off the full bundle, unlock it and you get every set, "
             "every clip, the stuff that never goes on the feed</p>")
    # HIS ask goes FIRST and the blast lands AFTER it, because the span runs
    # from his anchor FORWARDS: a blast seeded before the ask is excluded by the
    # span boundary and never reaches `_own_words` at all, so the case passes
    # whole with the filter deleted. Ordered this way the line is inside the
    # span and only `_is_blast` can keep it out.
    await _say(aid, 1, datetime(2026, 9, 1, 10, 0), "in",
               "<p>can you do a custom where you say my name</p>", mid=3)
    # The SAME copy, byte for byte, to two fans — that is what makes it a blast,
    # and SQL groups the two identical bodies into one row of 2. The variants
    # case below covers the other half: the same copy in DIFFERENT wrappers.
    await _say(aid, 1, datetime(2026, 9, 2, 10, 0), "out", blast, mid=1)
    await _say(aid, 2, datetime(2026, 9, 2, 10, 0), "out", blast, mid=2)

    res = await customs_api.customs_order(account_id=aid, fan_id=1)
    texts = " | ".join(l["text"] for l in res["lines"])
    assert "say my name" in texts, texts
    assert "full bundle" not in texts, "our mass marketing leaked into the order"


async def case_a_blast_in_html_variants_is_still_a_blast():
    """THE SAME COPY, WRAPPED DIFFERENTLY, IS ONE BLAST — and the counting has to
    say so.

    `GROUP BY Message.body` groups on the RAW body, so a blast stored once with a
    `<p>` wrapper, once with `<br/>`s and once bare comes back as THREE rows. They
    all strip to the same text, so they collapse onto one normalised key — and if
    that key is ASSIGNED rather than SUMMED, each variant keeps its own count of 1
    and `_is_blast`'s `> 1` passes our PPV copy off as the fan's own order.

    The sibling case above cannot catch this: its two sends are byte-identical, so
    SQL already groups them into a single row of 2 and the fold never runs. This
    one gives every recipient a DIFFERENT wrapper, which is what the live rows
    look like."""
    import customs_api
    aid = "cw_order_blast_variants"
    body = ("75% off the full bundle, unlock it and you get every set, every "
            "clip, the stuff that never goes on the feed")
    # HIS ask opens the span; the blast lands AFTER it, which is the only way a
    # line reaches `_own_words` at all — the span runs from his anchor forwards.
    await _say(aid, 1, datetime(2026, 9, 1, 10, 0), "in",
               "<p>can you do a custom where you say my name</p>", mid=1)
    # One blast, three fans, three wrappers — three SQL groups of 1 each.
    await _say(aid, 1, datetime(2026, 9, 2, 10, 0), "out", f"<p>{body}</p>", mid=2)
    await _say(aid, 2, datetime(2026, 9, 2, 10, 0), "out",
               body.replace(", ", ",<br/>"), mid=3)
    await _say(aid, 3, datetime(2026, 9, 2, 10, 0), "out", body, mid=4)

    res = await customs_api.customs_order(account_id=aid, fan_id=1)
    texts = " | ".join(l["text"] for l in res["lines"])
    assert "say my name" in texts, texts
    assert "full bundle" not in texts, \
        "an HTML variant of our blast leaked into the order — the counts were " \
        "overwritten onto the normalised key instead of summed"


_harness.run()
