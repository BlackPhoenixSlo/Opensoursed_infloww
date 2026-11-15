#!/usr/bin/env python3
"""test_full_ai_live_sweep — the missed-message sweep (04a ticket 68, full_ai_live.sweep).

A live rule's interval job (`anchor` None) queues the Fan's job for each due Turn end the webhook
never delivered. DMs are written straight to `messages` (no hook) unless a case says otherwise.
OF, Jev and the Writers faked (`_full_ai_fixtures.live_world`). Temp DB only.

  case_missed_dm_answered           due in the past: one job queued; it sends one reply, row `sent`
  case_not_due_yet                  due in the future: not queued; queued once now >= due
  case_turn_with_row_skipped        a live row on the Turn key (unconfirmed, no_send): not queued
  case_pending_job_not_doubled      two passes: one job
  case_her_outbound_newest          her newest row (another Lane, a human): not queued
  case_older_than_a_day             inbound older than 24 h: not queued
  case_dm_saved_by_chat_read        his DM in `messages`, `fans.last_message_received_at` a week old
                                    (saved by a chat read after a socket drop): queued
  case_prelook_stands_down          a fake last-look check standing down: not queued, no Jev call
  case_cap_twenty_oldest_first      25 Turn ends: 20 queued (oldest), the next pass the other 5
  case_webhook_off_sweep_answers    reply_by_webhook off + a hook-delivered DM: only the sweep queues
  case_dead_run_reaped              a `sending` row is `unconfirmed` after the pass
  case_welcome_cooldown_no_of       DM then welcome: queued; a Fan on cooldown: not queued, pass after
                                    pass; the fake OF got 0 calls and no client was built in any pass
  case_shadow_rule_unanchored       a Shadow rule's interval job still returns `unanchored`

Run: ./venv/bin/python service/tests/test_full_ai_live_sweep.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

from _full_ai_fixtures import KIND, _msg, _rows, _run_row, _seed, live_world, seed_live  # noqa: E402
import automation_executor as ax  # noqa: E402
import fan_lease  # noqa: E402
import webhook_dispatch as wd  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import full_ai_config, full_ai_live, full_ai_test  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AccountAiConfig, AiDecision, Fan, ScheduledJob  # noqa: E402

CFG = full_ai_config.DEFAULTS                     # reply_speed "0-2m"
EPOCH = datetime(2000, 1, 1)                      # the interval job sorts ahead of every Fan job


async def _dm(aid: str, fan: int, mid: int, at: datetime, body: str = "hey you") -> None:
    """His DM in `messages` and `fans.last_message_received_at`, as ingestion leaves them; no hook."""
    await _msg(aid, fan, mid, "in", body, at)
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        if f is None:
            s.add(Fan(account_id=aid, fan_id=fan, last_message_received_at=at))
        else:
            f.last_message_received_at = at


async def _jobs(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.status == "pending")
            .order_by(ScheduledJob.id))).scalars())


async def _fan_jobs(aid: str) -> list[dict]:
    return [json.loads(j.payload_json) for j in await _jobs(aid)]


async def _pass(aid: str) -> dict:
    """One sweep pass: the rule's interval job (no anchor) through run_once; its stats."""
    rid = await full_ai_live.live_rule(aid) or None
    await ax.enqueue_job(aid, KIND, payload={}, run_at=EPOCH, rule_id=rid)
    res = await run_once(aid, KIND)
    assert res["status"] == "ok", res
    st = json.loads((await _run_row(res["run_id"])).stats_json or "{}")
    st.pop("duration_ms", None)
    return st


async def _row(aid: str, fan: int, key: str, status: str) -> None:
    async with get_session() as s:
        s.add(AiDecision(account_id=aid, fan_id=fan, mode="live", trigger_kind="inbound", trigger_key=key,
                         route="chat", heat=1, route_row="chat", question_version="x", status=status,
                         created_at=datetime.utcnow()))


def _ago(minutes: float) -> datetime:
    return datetime.utcnow() - timedelta(minutes=minutes)


async def case_missed_dm_answered():
    aid, fan, mid = "fa_sw_missed", 701, 9101
    rid = await seed_live(aid)
    await _dm(aid, fan, mid, _ago(3))
    with live_world() as w:
        assert await _pass(aid) == {"swept": 1, "queued": 1}
        assert await _fan_jobs(aid) == [{"only_fan_ids": [fan], "anchor": mid, "_rule_id": rid, "tries": 0}]
        assert w.of.sent == [] and w.made == []
        assert (await run_once(aid, KIND))["status"] == "ok"
    (row,) = await _rows(aid)
    assert (row.status, row.trigger_key) == ("sent", str(mid)), row
    assert w.of.sent and len(w.of.sent) == len(json.loads(row.reply_json)["parts"])
    with live_world() as w:
        assert await _pass(aid) == {"swept": 0, "queued": 0}       # answered: her outbound is newest
    assert await _jobs(aid) == []


async def case_not_due_yet():
    aid, fan = "fa_sw_notdue", 702
    await seed_live(aid)
    mid = 9201
    while full_ai_test.hold(CFG, str(mid)) < 60:
        mid += 1
    await _dm(aid, fan, mid, datetime.utcnow())
    with live_world():
        assert await _pass(aid) == {"swept": 0, "queued": 0}
        assert await _jobs(aid) == []
        async with get_session() as s:      # time passes: his DM is now older than its wait
            from db.models import Message
            m = await s.get(Message, (aid, fan, mid))
            m.created_at = datetime.utcnow() - timedelta(seconds=full_ai_test.hold(CFG, str(mid)) + 1)
        assert await _pass(aid) == {"swept": 1, "queued": 1}
    assert [p["anchor"] for p in await _fan_jobs(aid)] == [mid]


async def case_turn_with_row_skipped():
    aid = "fa_sw_row"
    await seed_live(aid)
    for fan, mid, status in ((703, 9301, "unconfirmed"), (704, 9302, "no_send"), (705, 9303, "failed")):
        await _dm(aid, fan, mid, _ago(3))
        await _row(aid, fan, str(mid), status)
    with live_world():
        assert await _pass(aid) == {"swept": 0, "queued": 0}
    assert await _jobs(aid) == []


async def case_pending_job_not_doubled():
    aid, fan, mid = "fa_sw_twice", 706, 9401
    await seed_live(aid)
    await _dm(aid, fan, mid, _ago(3))
    with live_world():
        assert await _pass(aid) == {"swept": 1, "queued": 1}
        assert await _pass(aid) == {"swept": 0, "queued": 0}
    assert len(await _jobs(aid)) == 1


async def case_her_outbound_newest():
    aid = "fa_sw_out"
    await seed_live(aid)
    await _dm(aid, 707, 9501, _ago(10))
    await _msg(aid, 707, 9502, "out", "hey babe", _ago(8), automation_kind="autoreply")
    await _dm(aid, 708, 9511, _ago(10))
    await _msg(aid, 708, 9512, "out", "typed in the OF app", _ago(8))      # a human: no kind
    with live_world():
        assert await _pass(aid) == {"swept": 0, "queued": 0}
    assert await _jobs(aid) == []


async def case_older_than_a_day():
    aid = "fa_sw_old"
    await seed_live(aid)
    await _dm(aid, 709, 9601, datetime.utcnow() - timedelta(hours=25))
    with live_world():
        assert await _pass(aid) == {"swept": 0, "queued": 0}
    assert await _jobs(aid) == []


async def case_dm_saved_by_chat_read():
    aid, fan = "fa_sw_read", 720
    await seed_live(aid)
    await _dm(aid, fan, 9651, datetime.utcnow() - timedelta(days=6))       # fans row: 6 days old
    await _msg(aid, fan, 9652, "out", "hey", datetime.utcnow() - timedelta(days=5))
    await _msg(aid, fan, 9653, "in", "Yeah", _ago(3))                      # no fans bump (a chat read)
    with live_world():
        assert await _pass(aid) == {"swept": 1, "queued": 1}
    assert [(p["only_fan_ids"], p["anchor"]) for p in await _fan_jobs(aid)] == [([fan], 9653)]


async def case_prelook_stands_down():
    aid, fan = "fa_sw_look", 710
    await seed_live(aid)
    await _dm(aid, fan, 9701, _ago(3))
    seen = []

    def no(look):
        seen.append((look.client, look.row, look.bubble, look.index, look.sent))
        return "test_says_no"
    full_ai_live.LAST_LOOK.insert(0, ("fake", None, no))
    try:
        with live_world() as w:
            assert await _pass(aid) == {"swept": 1, "queued": 0}
    finally:
        full_ai_live.LAST_LOOK.pop(0)
    assert seen == [(None, None, None, -1, 0)], seen
    assert await _jobs(aid) == [] and w.jev.calls == [] and w.made == [] and await _rows(aid) == []


async def case_cap_twenty_oldest_first():
    aid = "fa_sw_cap"
    await seed_live(aid)
    for i in range(25):
        await _dm(aid, 800 + i, 9800 + i, _ago(60 - i))         # fan 800 is the oldest
    with live_world():
        assert await _pass(aid) == {"swept": 25, "queued": 20}
        assert sorted(p["only_fan_ids"][0] for p in await _fan_jobs(aid)) == list(range(800, 820))
        assert await _pass(aid) == {"swept": 5, "queued": 5}
    assert sorted(p["only_fan_ids"][0] for p in await _fan_jobs(aid)) == list(range(800, 825))


async def case_webhook_off_sweep_answers():
    aid, fan, mid = "fa_sw_nohook", 711, 9901
    await seed_live(aid)
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, full_ai_config_json=json.dumps(
            {"checkpoint": {"reply_by_webhook": False}, "rev": 1})))
    await _dm(aid, fan, mid, _ago(3))
    with live_world() as w:
        await wd.on_inbound_message(aid, fan, mid)
        assert await _jobs(aid) == []
        assert await _pass(aid) == {"swept": 1, "queued": 1}
        assert (await run_once(aid, KIND))["status"] == "ok"
    (row,) = await _rows(aid)
    assert row.status == "sent" and w.of.sent, row.status


async def case_dead_run_reaped():
    aid, fan = "fa_sw_reap", 712
    await seed_live(aid)
    await _msg(aid, fan, 9950, "in", "hey", _ago(30))
    await _msg(aid, fan, 9951, "out", "bubble one", _ago(29), automation_kind=KIND)
    await _row(aid, fan, "9950", "sending")
    with live_world() as w:
        assert await _pass(aid) == {"swept": 0, "queued": 0}
    (row,) = await _rows(aid)
    assert row.status == "unconfirmed", row.status
    assert w.of.sent == [] and await _jobs(aid) == []


async def case_welcome_cooldown_no_of():
    aid = "fa_sw_welcome"
    await seed_live(aid)
    await _dm(aid, 713, 9961, _ago(5))
    await _msg(aid, 713, 9962, "out", "welcome babe!", _ago(4), automation_kind="welcome")
    await _dm(aid, 714, 9971, _ago(5))
    await fan_lease.start_fan_cooldown(aid, 714, cooldown_s=3600)     # a Human yield
    with live_world() as w:
        assert await _pass(aid) == {"swept": 1, "queued": 1}
        assert [(p["only_fan_ids"], p["anchor"]) for p in await _fan_jobs(aid)] == [([713], 9961)]
        for _ in range(3):
            assert await _pass(aid) == {"swept": 0, "queued": 0}
        assert len(await _jobs(aid)) == 1
        assert w.of.sent == [] and w.made == [], (w.of.sent, w.made)


async def case_shadow_rule_unanchored():
    aid = "fa_sw_shadow"
    rid = await _seed(aid, rule=True, gate=False)          # no `mode`: Shadow
    await _dm(aid, 715, 9981, _ago(3))
    await ax.enqueue_job(aid, KIND, payload={}, run_at=EPOCH, rule_id=rid)
    res = await run_once(aid, KIND)
    st = json.loads((await _run_row(res["run_id"])).stats_json or "{}")
    assert st.get("skipped") == "unanchored", st
    assert await _jobs(aid) == []


_harness.run()
