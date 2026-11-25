#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

from _full_ai_fixtures import KIND, _msg, _rows, _run_row, _seed, clear_pause, live_world, seed_live  # noqa: E402
import automation_executor as ax  # noqa: E402,F401
import fan_lease  # noqa: E402
import webhook_dispatch as wd  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import full_ai_config, full_ai_live, full_ai_test  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AccountAiConfig, AutomationRule, ScheduledJob  # noqa: E402

CFG = full_ai_config.DEFAULTS
PROBE = "FAI_TRIGGER_PROBE"


@contextlib.contextmanager
def _logs(name: str):
    lines: list[str] = []

    class H(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())
    h, lg = H(), logging.getLogger(name)
    old = lg.level
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    try:
        yield lines
    finally:
        lg.removeHandler(h)
        lg.setLevel(old)


async def _jobs(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.status == "pending")
            .order_by(ScheduledJob.id))).scalars())


async def _time_passes(aid: str) -> None:
    async with get_session() as s:
        await s.execute(update(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.status == "pending")
            .values(run_at=datetime.utcnow() - timedelta(seconds=1)))


def _slow_mid(start: int, at_least_s: float = 30.0) -> int:
    mid = start
    while full_ai_test.hold(CFG, str(mid)) < at_least_s:
        mid += 1
    return mid


async def case_one_dm_waits_reply_speed():
    aid, fan = "fa_trig_wait", 601
    rid = await seed_live(aid)
    mid = _slow_mid(8101)
    at = datetime.utcnow().replace(microsecond=0)
    await _msg(aid, fan, mid, "in", "hey you, how was your day", at)
    wakes, real_wake = [], wd._schedule_wake
    with live_world() as w:
        wd._schedule_wake = wakes.append
        try:
            await wd.on_inbound_message(aid, fan, mid)
        finally:
            wd._schedule_wake = real_wake
        (job,) = await _jobs(aid)
        left = (job.run_at - datetime.utcnow()).total_seconds()
        assert len(wakes) == 1 and left - 2 <= wakes[0] <= left + 0.5, (wakes, left)   # woken at run_at
        assert job.kind == KIND and json.loads(job.payload_json) == {
            "only_fan_ids": [fan], "anchor": mid, "_rule_id": rid, "tries": 0}, job.payload_json
        want = at + timedelta(seconds=full_ai_test.hold(CFG, str(mid)))
        assert job.run_at == want, (job.run_at, want)
        early = await run_once(aid, KIND)
        assert early == {"status": "skipped", "reason": "no_job"}, early
        assert w.of.sent == [] and w.made == [] and await _rows(aid) == []
        await _time_passes(aid)
        res = await run_once(aid, KIND)
    assert res["status"] == "ok", res
    (row,) = await _rows(aid)
    assert (row.status, row.trigger_key) == ("sent", str(mid)), row
    assert w.of.sent and len(w.of.sent) == len(json.loads(row.reply_json)["parts"]), w.of.sent
    assert await _jobs(aid) == []


async def _probe(mid: int, at: datetime) -> None:
    aid, fan = "fa_trig_probe", 602
    await seed_live(aid)
    await _msg(aid, fan, mid, "in", "hi", at)
    assert await full_ai_live.enqueue(aid, fan, mid, 1)
    (job,) = await _jobs(aid)
    print(job.run_at.isoformat())


async def case_same_anchor_same_run_at():
    mid, at = 8201, datetime(2026, 11, 15, 12, 0, 0)
    dm = SimpleNamespace(message_id=mid, created_at=at)
    assert full_ai_live.due(CFG, dm) == full_ai_live.due(dict(CFG), dm)
    runs = []
    for aid, fan in (("fa_trig_same_a", 603), ("fa_trig_same_b", 604)):
        await seed_live(aid)
        await _msg(aid, fan, mid, "in", "hi", at)
        assert await full_ai_live.enqueue(aid, fan, mid, 1)
        runs += [j.run_at for j in await _jobs(aid)]
    out = subprocess.run([sys.executable, __file__], env={**os.environ, PROBE: f"{mid}|{at.isoformat()}"},
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    other = datetime.fromisoformat(out.stdout.strip().splitlines()[-1])
    assert runs[0] == runs[1] == other == full_ai_live.due(CFG, dm), (runs, other)


async def case_burst_one_reply():
    aid, fan = "fa_trig_burst", 605
    await seed_live(aid)
    at = datetime.utcnow() - timedelta(minutes=3)
    bodies = ("hey", "u up?", "miss u")
    with live_world() as w:
        for i, body in enumerate(bodies):
            await _msg(aid, fan, 8301 + i, "in", body, at + timedelta(seconds=5 * i))
            await wd.on_inbound_message(aid, fan, 8301 + i)
        jobs = await _jobs(aid)
        assert len(jobs) == 1 and json.loads(jobs[0].payload_json)["anchor"] == 8301, jobs
        await _time_passes(aid)
        res = await run_once(aid, KIND)
        assert res["status"] == "ok", res
        assert await run_once(aid, KIND) == {"status": "skipped", "reason": "no_job"}
    (row,) = await _rows(aid)
    assert (row.status, row.trigger_key) == ("sent", "8303"), (row.status, row.trigger_key)
    assert json.loads(row.jev_json)["state"]["fan_new_messages"] == list(bodies), row.jev_json
    assert len(w.jev.calls) >= 1 and w.of.sent, (w.jev.calls, w.of.sent)
    assert len(w.of.sent) == len(json.loads(row.reply_json)["parts"])


async def case_reply_by_webhook_off():
    aid, fan = "fa_trig_nohook", 606
    await seed_live(aid)
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, full_ai_config_json=json.dumps(
            {"checkpoint": {"reply_by_webhook": False}, "rev": 1})))
    await _msg(aid, fan, 8401, "in", "hey", datetime.utcnow() - timedelta(minutes=3))
    await wd.on_inbound_message(aid, fan, 8401)
    assert await _jobs(aid) == []


async def case_rule_off_while_waiting():
    aid, fan = "fa_trig_off", 607
    rid = await seed_live(aid)
    await _msg(aid, fan, 8501, "in", "hey", datetime.utcnow() - timedelta(minutes=3))
    with live_world() as w:
        await wd.on_inbound_message(aid, fan, 8501)
        assert len(await _jobs(aid)) == 1
        async with get_session() as s:
            await s.execute(update(AutomationRule).where(AutomationRule.id == rid).values(is_enabled=False))
        await _time_passes(aid)
        res = await run_once(aid, KIND)
    assert (res["status"], res["reason"]) == ("skipped", "rule_disabled"), res
    assert w.of.sent == [] and w.made == [] and await _rows(aid) == [] and await _jobs(aid) == []


async def _stats(res: dict) -> dict:
    assert res["status"] == "ok", res
    st = json.loads((await _run_row(res["run_id"])).stats_json or "{}")
    st.pop("duration_ms", None)
    return st


async def _busy_then(aid: str, fan: int, mid: int, free) -> None:
    rid = await full_ai_live.live_rule(aid)
    with live_world() as w:
        await wd.on_inbound_message(aid, fan, mid)
        t0 = datetime.utcnow()
        assert await _stats(await run_once(aid, KIND)) == {"skipped": "busy", "tries": 1}
        (job,) = await _jobs(aid)
        p = json.loads(job.payload_json)
        assert p == {"only_fan_ids": [fan], "anchor": mid, "_rule_id": rid, "tries": 1}, p
        assert t0 + timedelta(seconds=19) <= job.run_at <= datetime.utcnow() + timedelta(seconds=21), job.run_at
        assert w.of.sent == [] and w.made == [] and await _rows(aid) == []
        await _msg(aid, fan, mid + 1, "in", "hello??", datetime.utcnow() - timedelta(minutes=2))
        await wd.on_inbound_message(aid, fan, mid + 1)
        assert [j.id for j in await _jobs(aid)] == [job.id], "the retry absorbs his next DM"
        await free()
        await _time_passes(aid)
        assert (await run_once(aid, KIND))["status"] == "ok"
    (row,) = await _rows(aid)
    assert (row.status, row.trigger_key) == ("sent", str(mid + 1)) and w.of.sent, row.status
    assert await _jobs(aid) == []


async def _three_busy(aid: str, fan: int, mid: int) -> None:
    with live_world() as w:
        await wd.on_inbound_message(aid, fan, mid)
        for n in (1, 2, 3):
            await _time_passes(aid)
            stats = await _stats(await run_once(aid, KIND))
            jobs = await _jobs(aid)
            if n < 3:
                assert stats == {"skipped": "busy", "tries": n}, stats
                assert [json.loads(j.payload_json)["tries"] for j in jobs] == [n], jobs
        assert stats == {"skipped": "busy"}, stats
        assert await _jobs(aid) == [], "a fourth job"
        assert w.of.sent == [] and w.made == [] and await _rows(aid) == []


async def _retry_rule_off(aid: str, fan: int, mid: int) -> None:
    rid = await full_ai_live.live_rule(aid)
    with live_world() as w:
        await wd.on_inbound_message(aid, fan, mid)
        await run_once(aid, KIND)
        assert [json.loads(j.payload_json)["tries"] for j in await _jobs(aid)] == [1]
        async with get_session() as s:
            await s.execute(update(AutomationRule).where(AutomationRule.id == rid).values(is_enabled=False))
        await _time_passes(aid)
        res = await run_once(aid, KIND)
    assert (res["status"], res["reason"]) == ("skipped", "rule_disabled"), res
    assert w.of.sent == [] and w.made == [] and await _rows(aid) == [] and await _jobs(aid) == []


async def case_leased_fan_retried():
    aid, fan = "fa_trig_lease", 608
    await seed_live(aid)
    await _msg(aid, fan, 8601, "in", "hey", datetime.utcnow() - timedelta(minutes=3))
    assert await fan_lease.acquire_fan_lease(aid, fan, "welcome_chatter_for_info", ttl_s=600)

    async def free():
        await fan_lease.release_fan_lease(aid, fan, holder="welcome_chatter_for_info")
    await _busy_then(aid, fan, 8601, free)
    aid, fan = "fa_trig_lease3", 609
    await seed_live(aid)
    await _msg(aid, fan, 8611, "in", "hey", datetime.utcnow() - timedelta(minutes=3))
    assert await fan_lease.acquire_fan_lease(aid, fan, "welcome_chatter_for_info", ttl_s=600)
    await _three_busy(aid, fan, 8611)
    aid, fan = "fa_trig_lease_off", 614
    await seed_live(aid)
    await _msg(aid, fan, 8621, "in", "hey", datetime.utcnow() - timedelta(minutes=3))
    assert await fan_lease.acquire_fan_lease(aid, fan, "welcome_chatter_for_info", ttl_s=600)
    await _retry_rule_off(aid, fan, 8621)


async def case_cooldown_fan_retried():
    aid, fan = "fa_trig_cool", 610
    await seed_live(aid)
    await _msg(aid, fan, 8701, "in", "hey", datetime.utcnow() - timedelta(minutes=3))
    await fan_lease.start_fan_cooldown(aid, fan, cooldown_s=600)

    async def free():
        await clear_pause(aid, fan)
    await _busy_then(aid, fan, 8701, free)
    aid, fan = "fa_trig_cool3", 611
    await seed_live(aid)
    await _msg(aid, fan, 8711, "in", "hey", datetime.utcnow() - timedelta(minutes=3))
    await fan_lease.start_fan_cooldown(aid, fan, cooldown_s=600)
    await _three_busy(aid, fan, 8711)


async def case_shadow_rule_job_unchanged():
    aid, fan = "fa_trig_shadow", 612
    rid = await _seed(aid, rule=True, gate=False)
    t0 = datetime.utcnow()
    await _msg(aid, fan, 8801, "in", "hey you", t0 - timedelta(minutes=3))
    await wd.on_inbound_message(aid, fan, 8801)
    (job,) = await _jobs(aid)
    assert json.loads(job.payload_json) == {"only_fan_ids": [fan], "anchor": 8801, "_rule_id": rid}, job.payload_json
    assert t0 - timedelta(seconds=1) <= job.run_at <= datetime.utcnow(), job.run_at


async def case_hook_failure_keeps_w7():
    aid, fan = "fa_trig_hookfail", 613
    await seed_live(aid, gate=True)
    await _msg(aid, fan, 8901, "in", "hello", datetime.utcnow())
    real = full_ai_live.enqueue

    async def boom(*a, **kw):
        raise RuntimeError("queue down")
    full_ai_live.enqueue = boom
    try:
        with _logs("of-relay.webhook_dispatch") as lines:
            await wd.on_inbound_message(aid, fan, 8901)
    finally:
        full_ai_live.enqueue = real
    assert [j.kind for j in await _jobs(aid)] == ["welcome_chatter_for_info"], await _jobs(aid)
    assert any(l.startswith(f"full_ai_hook_failed account={aid} fan={fan}") for l in lines), lines


if os.environ.get(PROBE):
    _mid, _at = os.environ[PROBE].split("|")
    asyncio.run(_probe(int(_mid), datetime.fromisoformat(_at)))
    sys.exit(0)

_harness.run()
