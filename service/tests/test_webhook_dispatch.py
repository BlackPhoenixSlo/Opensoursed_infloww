#!/usr/bin/env python3
"""
W7 — webhook-priority dispatch tests (plan/AUTOMATIONS_BUILD_PROMPTS.md §WAVE 7).

Covers the event-driven dispatch path and the manual-chatter HARD YIELD:

  case_gate_off_no_enqueue:
      account gate absent/disabled → on_inbound_message enqueues nothing.
  case_global_kill_switch:
      gate ON but W7_WEBHOOK_DISPATCH_DISABLED set → no enqueue.
  case_inbound_enqueues_ai_chat:
      gate ON, plain fan → enqueues exactly one welcome_chatter_for_info job due now + wakes.
  case_inbound_mid_funnel_enqueues_funnel:
      gate ON, fan has a pending funnel_state → enqueues reply_mass_funnel.
  case_inbound_on_cooldown_skips:
      gate ON but fan_on_cooldown → no enqueue (stands down for a human).
  case_dedup_single_pending:
      two inbounds for the same (account,kind) → exactly one pending job.
  case_concurrent_same_fan_one_job / case_concurrent_two_fans_neither_waits:
      DMs dispatched at once: one fan → one job (per-fan serial), two fans →
      two jobs with neither waiting; the per-fan lock dict empties after.
  case_supervisor_wakes_on_event:
      wake_supervisor() makes the supervisor drain a due job well under 30s.
  case_hard_yield_human_send_sets_cooldown:
      write_outbound_attribution with a HUMAN emp + mass_run_id=None → fan paused;
      the Automation sentinel and a manual BROADCAST (mass_run_id set) do NOT.

Run: ./venv/bin/python service/tests/test_webhook_dispatch.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import webhook_dispatch as wd  # noqa: E402 — module under test
from attribution import write_outbound_attribution  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    AccountAiConfig,
    AutomationRule,
    Employee,
    Fan,
    FunnelState,
    MassRun,
    Message,
    ScheduledJob,
    SkipList,
)


# ── Seeding helpers ──────────────────────────────────────────────────

async def _seed_account(
    aid: str, *, webhook_enabled: bool | None, config_extra: dict | None = None,
) -> None:
    """Account + (optionally) an AccountAiConfig with the W7 gate set.
    `config_extra` merges extra webhook_config_json knobs (e.g. delay_seconds)."""
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
            # W7 only wakes these two while their rule is ON (the rule IS their
            # switch) — every account here runs both, as a live one would.
            for kind in ("welcome_chatter_for_info", "reply_mass_funnel"):
                s.add(AutomationRule(account_id=aid, name=kind, kind=kind,
                                     trigger_json=json.dumps({"every_seconds": 60}),
                                     steps_json="{}", is_enabled=True))
        if webhook_enabled is not None and await s.get(AccountAiConfig, aid) is None:
            cfg = {"enabled": webhook_enabled, **(config_extra or {})}
            s.add(AccountAiConfig(
                account_id=aid,
                webhook_config_json=json.dumps(cfg),
            ))


async def _pending_jobs(aid: str, kind: str | None = None) -> list[ScheduledJob]:
    async with get_session() as s:
        q = select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.status == "pending",
        )
        if kind is not None:
            q = q.where(ScheduledJob.kind == kind)
        return list((await s.execute(q)).scalars().all())


def _knobs(job: ScheduledJob) -> dict:
    """A job's payload minus the `_rule_id` tag W7 stamps on rule-gated kinds
    (welcome_chatter_for_info / reply_mass_funnel) — the tag is asserted on its
    own; these checks are about what the run is scoped to."""
    p = json.loads(job.payload_json)
    rid = p.pop("_rule_id", None)
    if job.kind in ("welcome_chatter_for_info", "reply_mass_funnel"):
        assert isinstance(rid, int), ("rule-gated W7 job must carry its rule id", job.payload_json)
    return p


async def _seed_funnel_fan(aid: str, fan_id: int) -> None:
    """A mass run + a pending funnel_state row so the fan reads as mid-funnel."""
    async with get_session() as s:
        mr = MassRun(account_id=aid, status="ok")
        s.add(mr)
        await s.flush()
        s.add(FunnelState(mass_run_id=mr.id, fan_id=fan_id, status="pending"))


# ── Cases ────────────────────────────────────────────────────────────

async def case_gate_off_no_enqueue():
    aid, fan = "w7_off", 4001
    await _seed_account(aid, webhook_enabled=None)          # no config row at all
    await wd.on_inbound_message(aid, fan, 1)
    assert await _pending_jobs(aid) == [], "gate-off must not enqueue"

    aid2 = "w7_disabled"
    await _seed_account(aid2, webhook_enabled=False)        # config present, disabled
    await wd.on_inbound_message(aid2, fan, 1)
    assert await _pending_jobs(aid2) == [], "disabled gate must not enqueue"


async def case_global_kill_switch():
    aid, fan = "w7_kill", 4002
    await _seed_account(aid, webhook_enabled=True)
    os.environ["W7_WEBHOOK_DISPATCH_DISABLED"] = "1"
    try:
        await wd.on_inbound_message(aid, fan, 1)
    finally:
        os.environ.pop("W7_WEBHOOK_DISPATCH_DISABLED", None)
    assert await _pending_jobs(aid) == [], "global kill-switch must suppress dispatch"


async def case_inbound_enqueues_ai_chat():
    aid, fan = "w7_chat", 4003
    await _seed_account(aid, webhook_enabled=True)
    woke = {"n": 0}
    orig = ax.wake_supervisor
    ax.wake_supervisor = lambda: woke.__setitem__("n", woke["n"] + 1)
    try:
        await wd.on_inbound_message(aid, fan, 99)
    finally:
        ax.wake_supervisor = orig
    jobs = await _pending_jobs(aid)
    assert len(jobs) == 1, f"expected 1 job, got {len(jobs)}"
    assert jobs[0].kind == "welcome_chatter_for_info", f"expected welcome_chatter_for_info, got {jobs[0].kind}"
    assert jobs[0].run_at <= datetime.utcnow() + timedelta(seconds=2), "job must be due ~now"
    # Fan-scoped: the job targets ONLY this fan (no full-account sweep).
    assert _knobs(jobs[0]) == {"only_fan_ids": [fan]}, jobs[0].payload_json
    assert woke["n"] == 1, "must wake the supervisor exactly once"


async def case_two_fans_each_get_a_job():
    """Per-fan dedup: two DIFFERENT fans replying must each get their own scoped
    welcome_chatter_for_info job (the old per-kind dedup would wrongly block the second fan)."""
    aid = "w7_twofans"
    await _seed_account(aid, webhook_enabled=True)
    await wd.on_inbound_message(aid, 5501, 1)
    await wd.on_inbound_message(aid, 5502, 2)
    jobs = await _pending_jobs(aid, "welcome_chatter_for_info")
    scoped = sorted(json.loads(j.payload_json)["only_fan_ids"][0] for j in jobs)
    assert scoped == [5501, 5502], f"both fans must get a scoped job, got {scoped}"


async def case_inbound_mid_funnel_enqueues_funnel():
    aid, fan = "w7_funnel", 4004
    await _seed_account(aid, webhook_enabled=True)
    await _seed_funnel_fan(aid, fan)
    await wd.on_inbound_message(aid, fan, 1)
    jobs = await _pending_jobs(aid)
    assert len(jobs) == 1, f"expected 1 job, got {len(jobs)}"
    assert jobs[0].kind == "reply_mass_funnel", f"mid-funnel must route to funnel, got {jobs[0].kind}"


async def _seed_skip(aid: str, fan_id: int, reason: str) -> None:
    async with get_session() as s:
        s.add(SkipList(account_id=aid, fan_id=fan_id, reason=reason))


async def case_inbound_graduated_fan_no_enqueue():
    """A graduated fan (skip_list reason 'info') must dispatch NOTHING from the
    W7 router: welcome_chatter_for_info would skip him anyway, so nobody replies."""
    aid, fan = "w7_grad", 4101
    await _seed_account(aid, webhook_enabled=True)
    await _seed_skip(aid, fan, "info")
    await wd.on_inbound_message(aid, fan, 1)
    assert await _pending_jobs(aid) == [], "graduated ('info') fan must not dispatch"


async def case_inbound_terminal_no_enqueue():
    """Terminal fans (any skip_list row: spent/too_long/…) must dispatch NOTHING —
    a human owns the chat and waking a sweep would be pure waste."""
    aid = "w7_terminal"
    await _seed_account(aid, webhook_enabled=True)
    await _seed_skip(aid, 4201, "spent")
    await wd.on_inbound_message(aid, 4201, 1)
    assert await _pending_jobs(aid) == [], "spent fan must not dispatch"


async def case_inbound_on_cooldown_skips():
    # A FAR cooldown (the 30-min welcome/followup rest, > decide.MAX_DEFER_S) is too
    # long to park a chat reply on → fall back to the periodic sweep, no enqueue.
    aid, fan = "w7_cooldown", 4005
    await _seed_account(aid, webhook_enabled=True)
    await ax.start_fan_cooldown(aid, fan)  # default 30-min rest
    await wd.on_inbound_message(aid, fan, 1)
    assert await _pending_jobs(aid) == [], "a far-cooled fan must fall to the sweep"


async def case_inbound_short_cooldown_defers():
    # A SHORT cooldown (chat's 45-90s rest, the common case when a fan replies
    # within ~30s) must NOT be dropped to the sweep — defer the reply to the
    # moment the cooldown ends so a fast replier is answered in ~a minute.
    aid, fan = "w7_defer", 4015
    await _seed_account(aid, webhook_enabled=True)
    await ax.start_fan_cooldown(aid, fan, cooldown_s=60)  # bot just replied
    # Stub the delayed wake so no real sleeper lingers past the case.
    orig = wd._wake_after

    async def _noop(_d):  # noqa: ANN001
        return None
    wd._wake_after = _noop
    try:
        await wd.on_inbound_message(aid, fan, 1)
    finally:
        wd._wake_after = orig
    jobs = await _pending_jobs(aid, "welcome_chatter_for_info")
    assert len(jobs) == 1, f"short cooldown must DEFER (enqueue), got {len(jobs)} jobs"
    # run_at should land just after the 60s cooldown end (+ the response delay).
    assert jobs[0].run_at >= datetime.utcnow() + timedelta(seconds=50), (
        f"deferred job should fire ~after cooldown end, got run_at={jobs[0].run_at}"
    )


async def case_dedup_single_pending():
    aid, fan = "w7_dedup", 4006
    await _seed_account(aid, webhook_enabled=True)
    await wd.on_inbound_message(aid, fan, 1)
    await wd.on_inbound_message(aid, fan, 2)  # second reply, same kind, imminent
    jobs = await _pending_jobs(aid, "welcome_chatter_for_info")
    assert len(jobs) == 1, f"dedup must keep exactly one pending job, got {len(jobs)}"


def _stale_dup_read(hold):
    """Wrap `_has_imminent_pending_job` so its answer comes back only after
    `hold(fan_id)` returns: the read is taken first, then held, so without the
    per-fan serial a second dispatch reads before the first one's insert.
    Twin: slop/lib/w7_faults.py `_unserialized` (same wrapper, relay side)."""
    real = wd._has_imminent_pending_job

    async def held(account_id, kind, fan_id, within_s, *, s=None):
        got = await real(account_id, kind, fan_id, within_s, s=s)
        await hold(fan_id)
        return got
    return real, held


async def case_concurrent_same_fan_one_job():
    """Two (and five) DMs of one fan dispatched at once (the transcoder fires a
    task per DM) → exactly one job: the 2nd dispatch reads after the 1st's insert.
    The per-fan lock dict is empty once the burst is done (no leak)."""
    aid, fan = "w7_burst_same", 4021
    await _seed_account(aid, webhook_enabled=True)
    real, held = _stale_dup_read(lambda _f: asyncio.sleep(0.05))
    wd._has_imminent_pending_job = held
    try:
        await asyncio.gather(wd.on_inbound_message(aid, fan, 1), wd.on_inbound_message(aid, fan, 2))
        assert len(await _pending_jobs(aid, "welcome_chatter_for_info")) == 1
        await asyncio.gather(*(wd.on_inbound_message(aid, fan + 1, m) for m in range(5)))
        jobs = await _pending_jobs(aid, "welcome_chatter_for_info")
    finally:
        wd._has_imminent_pending_job = real
    per_fan = sorted(_knobs(j)["only_fan_ids"][0] for j in jobs)
    assert per_fan == [fan, fan + 1], per_fan
    assert len(wd._fan_locks) == 0, list(wd._fan_locks)


async def case_concurrent_two_fans_neither_waits():
    """Two fans at once → 2 jobs, and fan B's dispatch finishes while fan A's is
    still held mid-dispatch: the serial is per fan, never a write cap."""
    aid, a, b = "w7_burst_two", 4031, 4032
    await _seed_account(aid, webhook_enabled=True)
    release_a = asyncio.Event()

    async def hold(fid):
        if fid == a:
            await release_a.wait()
    real, held = _stale_dup_read(hold)
    wd._has_imminent_pending_job = held
    try:
        ta = asyncio.create_task(wd.on_inbound_message(aid, a, 1))
        await asyncio.sleep(0.05)
        assert not ta.done()
        await asyncio.wait_for(wd.on_inbound_message(aid, b, 1), timeout=5)
        mid = sorted(_knobs(j)["only_fan_ids"][0] for j in await _pending_jobs(aid))
        assert mid == [b], ("fan B waited on fan A", mid)
        assert list(wd._fan_locks) == [(aid, a)], list(wd._fan_locks)
        release_a.set()
        await asyncio.wait_for(ta, timeout=5)
    finally:
        release_a.set()
        wd._has_imminent_pending_job = real
    got = sorted(_knobs(j)["only_fan_ids"][0] for j in await _pending_jobs(aid))
    assert got == [a, b], got
    assert len(wd._fan_locks) == 0, list(wd._fan_locks)


async def case_inbound_delay_schedules_future_job():
    aid, fan = "w7_delay", 4007
    await _seed_account(aid, webhook_enabled=True, config_extra={"delay_seconds": 30})
    # Stub the delayed wake so no real 30s sleeper task lingers past the case.
    orig = wd._wake_after

    async def _noop(_d):  # noqa: ANN001
        return None
    wd._wake_after = _noop
    try:
        await wd.on_inbound_message(aid, fan, 1)
    finally:
        wd._wake_after = orig
    jobs = await _pending_jobs(aid)
    assert len(jobs) == 1, f"expected 1 job, got {len(jobs)}"
    assert jobs[0].run_at >= datetime.utcnow() + timedelta(seconds=25), (
        f"delayed job should be ~30s out, got run_at={jobs[0].run_at}"
    )


async def case_supervisor_wakes_on_event():
    aid = "w7_wake"
    await _seed_account(aid, webhook_enabled=True)
    # A registered no-op automation kind so the drain has something to claim
    # without touching the network. Enqueue a due job, then run the supervisor
    # briefly and assert it drains FAST (woken), not after the 30s tick.
    ran = {"ok": False}

    from automation_registry import register

    @register("w7_test_noop")
    async def _noop(account_id, payload, *, run_id):  # noqa: ANN001
        ran["ok"] = True
        return {}

    await ax.enqueue_job(aid, "w7_test_noop", payload={})

    sup = asyncio.create_task(ax.automation_supervisor())
    try:
        await asyncio.sleep(0.05)   # let the supervisor create its wake Event
        ax.wake_supervisor()
        # Poll for the drain to complete; must happen WELL under the 30s tick.
        for _ in range(100):        # up to ~5s budget
            if ran["ok"]:
                break
            await asyncio.sleep(0.05)
        # Grace: let the in-flight run_once finish COMMITTING its automation_runs
        # row before we cancel — cancelling mid-write would leave a SQLite write
        # lock that bleeds into the next case ("database is locked").
        await asyncio.sleep(0.2)
    finally:
        sup.cancel()
        try:
            await sup
        except asyncio.CancelledError:
            pass
        # Drop the closed-loop wake Event so a later case can never .set() it.
        ax._wake_event = None  # type: ignore[attr-defined]
    assert ran["ok"], "supervisor must drain the due job after wake (well under 30s)"


async def _seed_employee(display_name: str, *, is_active: bool) -> int:
    async with get_session() as s:
        e = Employee(display_name=display_name, is_active=is_active)
        s.add(e)
        await s.flush()
        return e.id


async def _paused_until(aid: str, fan_id: int):
    async with get_session() as s:
        return (await s.execute(
            select(Fan.automation_paused_until).where(
                Fan.account_id == aid, Fan.fan_id == fan_id,
            )
        )).scalar_one_or_none()


async def case_hard_yield_human_send_sets_cooldown():
    aid = "w7_yield"
    await _seed_account(aid, webhook_enabled=None)
    # The system Automation sentinel (display_name='Automation', is_active=False)
    # — get_automation_employee_id() resolves to this; migration 0011 makes it in
    # prod, but init_db (create_all) does not, so the test seeds it.
    auto_id = await _seed_employee("Automation", is_active=False)
    human_id = await _seed_employee("Alice", is_active=True)

    now = datetime.utcnow()

    # HUMAN 1:1 send → fan rested.
    await write_outbound_attribution(
        account_id=aid, fan_id=5001, message_id=1, sent_by_employee_id=human_id,
        body="hey", price_cents=0, created_at=now, mass_run_id=None,
    )
    pu = await _paused_until(aid, 5001)
    assert pu is not None and pu > now, "human 1:1 send must rest the fan (hard yield)"

    # AUTOMATION send (sentinel) → NOT rested by the hard yield.
    await write_outbound_attribution(
        account_id=aid, fan_id=5002, message_id=2, sent_by_employee_id=auto_id,
        body="auto", price_cents=0, created_at=now, mass_run_id=None,
    )
    assert await _paused_until(aid, 5002) is None, "automation send must NOT trip the hard yield"

    # MANUAL BROADCAST (human emp but mass_run_id set) → NOT rested (don't pause
    # the whole audience). Seed a real mass_runs row so the Message actually
    # INSERTS (FK) and it's the mass_run_id guard — not a failed write — that
    # skips the cooldown.
    async with get_session() as s:
        mr = MassRun(account_id=aid, status="ok")
        s.add(mr)
        await s.flush()
        broadcast_run_id = mr.id
    await write_outbound_attribution(
        account_id=aid, fan_id=5003, message_id=3, sent_by_employee_id=human_id,
        body="blast", price_cents=0, created_at=now, mass_run_id=broadcast_run_id,
    )
    # Confirm the row really landed, so the assertion below tests the guard.
    async with get_session() as s:
        row = (await s.execute(select(Message.message_id).where(
            Message.account_id == aid, Message.fan_id == 5003, Message.message_id == 3,
        ))).scalar_one_or_none()
    assert row is not None, "broadcast message row must insert (FK satisfied)"
    assert await _paused_until(aid, 5003) is None, "manual broadcast must NOT cooldown recipients"


# ── inbound IMAGE: the hook hands off the words ──────────────────────
#
# `event_transcoder` does not fire on_inbound_message for a media DM (its
# `is_media_dm`), so on_inbound_image OWNS that fan's text reply. A media DM must
# never lose its reply.

_IMG_FAN = 6100


async def _seed_his_photo(aid: str, message_id: int) -> None:
    """The inbound media row the hook is called for."""
    async with get_session() as s:
        if await s.get(Fan, (aid, _IMG_FAN)) is None:
            s.add(Fan(account_id=aid, fan_id=_IMG_FAN))
        s.add(Message(account_id=aid, fan_id=_IMG_FAN, message_id=int(message_id),
                      direction="in", body="", media_count=1,
                      created_at=datetime.utcnow()))


async def case_inbound_image_hands_off_one_words_job():
    """An ordinary media DM gets exactly ONE words job, scoped to him."""
    aid, mid = "w7_img_words", 7101
    await _seed_account(aid, webhook_enabled=True)
    await _seed_his_photo(aid, mid)
    await wd.on_inbound_image(aid, _IMG_FAN, mid, has_media=True)

    jobs = await _pending_jobs(aid)
    assert len(jobs) == 1, ("exactly ONE words job off one photo",
                            [(j.kind, j.payload_json) for j in jobs])
    assert jobs[0].kind == "welcome_chatter_for_info", jobs[0].kind
    assert _knobs(jobs[0]) == {"only_fan_ids": [_IMG_FAN]}, jobs[0].payload_json


async def case_inbound_image_gif_is_not_stranded():
    """A Giphy DM carries no media, but it rides this hook (the transcoder sends
    it here) and must not lose its words."""
    aid, mid = "w7_img_gif", 7105
    await _seed_account(aid, webhook_enabled=True)
    await _seed_his_photo(aid, mid)
    await wd.on_inbound_image(aid, _IMG_FAN, mid, has_media=False)

    jobs = await _pending_jobs(aid)
    assert len(jobs) == 1, ("a gif gets words", [(j.kind, j.payload_json) for j in jobs])
    assert _knobs(jobs[0]) == {"only_fan_ids": [_IMG_FAN]}, jobs[0].payload_json


async def case_inbound_image_gate_off_account_enqueues_nothing():
    """W7 off: on_inbound_message returns at `cfg is None`, so the media DM's words
    come from the periodic sweep exactly as a text DM's do. The hand-off must not
    invent a job on an account that opted out."""
    aid, mid = "w7_img_gateoff", 7109
    await _seed_account(aid, webhook_enabled=False)
    await _seed_his_photo(aid, mid)
    await wd.on_inbound_image(aid, _IMG_FAN, mid, has_media=True)
    assert await _pending_jobs(aid) == [], "W7 off means no dispatch, image or not"


# ── plans/blast-splice Part C — the copy, ingested on the first reply ────────
#
# A list-audience blast writes NO per-fan row, and on the blast accounts no
# `scrape_chats` cadence rule runs — so the man who answers a blast has our own
# line missing from his thread, and the 4h mass unsend then erases it OF-side too.
# One bounded one-fan scrape on the first inbound after a blast lands the real copy
# with its media and OF's `queueId`, inside the window we ourselves leave open.

async def _seed_blast_run(aid: str, *, minutes_ago: float) -> None:
    async with get_session() as s:
        sent = datetime.utcnow() - timedelta(minutes=minutes_ago)
        s.add(MassRun(account_id=aid, queue_id=int(minutes_ago * 1000) + 7,
                      audience_filter="{}", recipient_count=0,
                      automation_kind="mass_premade", status="ok",
                      completed_at=sent, body="just say please", sent_at=sent))


def _clear_claims() -> None:
    wd._blast_scrape_claims.clear()


async def case_inbound_after_a_blast_enqueues_a_one_fan_scrape():
    """One job for the fan, now — and exactly one however many times he writes.

    The dedup is an IN-PROCESS CLAIM and not a pending-job scan, and that is the
    whole of it: `_has_imminent_pending_job` sees `status='pending'` only, so a job
    that is RUNNING or has already FINISHED stops nothing. Both are asserted below,
    plus two handlers racing on the same loop."""
    aid, fan = "w7_blast", 6301
    await _seed_account(aid, webhook_enabled=True)
    _clear_claims()
    await _seed_blast_run(aid, minutes_ago=5)

    await wd.on_inbound_message(aid, fan, 1)
    jobs = await _pending_jobs(aid, "scrape_chats")
    assert len(jobs) == 1, [j.payload_json for j in jobs]
    assert json.loads(jobs[0].payload_json) == {
        "fan_ids": [fan], "source": "blast_reply"}, jobs[0].payload_json
    assert jobs[0].run_at <= datetime.utcnow() + timedelta(seconds=2), jobs[0].run_at

    # …while it is PENDING,
    await wd.on_inbound_message(aid, fan, 2)
    # …after it is marked RUNNING,
    async with get_session() as s:
        row = await s.get(ScheduledJob, jobs[0].id)
        row.status = "running"
    await wd.on_inbound_message(aid, fan, 3)
    # …and after it COMPLETED. A pending-only dedup lets both of these through.
    async with get_session() as s:
        row = await s.get(ScheduledJob, jobs[0].id)
        row.status = "done"
    await wd.on_inbound_message(aid, fan, 4)
    async with get_session() as s:
        total = len((await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == "scrape_chats")
        )).scalars().all())
    assert total == 1, f"{total} scrapes for one fan inside the dedup window"

    # Two inbound handlers racing on one loop: the claim is set with no await
    # between the check and the set, so they serialise on it.
    aid2, fan2 = "w7_blast_race", 6302
    await _seed_account(aid2, webhook_enabled=True)
    _clear_claims()
    await _seed_blast_run(aid2, minutes_ago=5)
    await asyncio.gather(wd.on_inbound_message(aid2, fan2, 1),
                         wd.on_inbound_message(aid2, fan2, 2))
    async with get_session() as s:
        raced = len((await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid2,
                                       ScheduledJob.kind == "scrape_chats")
        )).scalars().all())
    assert raced == 1, f"two concurrent handlers queued {raced} scrapes"


async def case_a_human_of_app_blast_triggers_the_scrape_too():
    """A blast the creator composed in the OF APP leaves us no `mass_runs` row at
    all — the only signal is OF's own `chat_queue_finish` frame, which the
    transcoder now keeps in a per-account ring. Driven THROUGH `transcode` with the
    exact envelope `event_inbox` stores.

    A CANCELED queue records nothing (nobody can be replying to a blast that was
    pulled back), and a later cancel removes an entry that was already recorded."""
    import event_transcoder as et  # noqa: E402
    aid, fan = "w7_blast_frame", 6303
    await _seed_account(aid, webhook_enabled=True)
    _clear_claims()
    et._queue_finishes.clear()

    frame = {"chat_queue_finish": {
        "id": 46605849959, "date": "2026-09-10T14:49:05+00:00", "isReady": True,
        "isDone": True, "total": 23, "pending": 0, "canUnsend": True,
        "unsendSeconds": 1000000, "hasError": False, "isCanceled": False,
        "isCouplePeopleMedia": False}, "__account_id": aid}
    await et.transcode(dict(frame))
    await wd.on_inbound_message(aid, fan, 1)
    assert len(await _pending_jobs(aid, "scrape_chats")) == 1, "frame ignored"

    # A canceled frame is not a blast anyone is answering.
    aid2, fan2 = "w7_blast_cancel", 6304
    await _seed_account(aid2, webhook_enabled=True)
    _clear_claims()
    et._queue_finishes.clear()
    canceled = {"chat_queue_finish": {**frame["chat_queue_finish"],
                                      "isCanceled": True},
                "__account_id": aid2}
    await et.transcode(dict(canceled))
    await wd.on_inbound_message(aid2, fan2, 1)
    assert await _pending_jobs(aid2, "scrape_chats") == [], "canceled frame counted"

    # …and a cancel that arrives AFTER the finish frame removes it.
    aid3, fan3 = "w7_blast_late_cancel", 6305
    await _seed_account(aid3, webhook_enabled=True)
    _clear_claims()
    et._queue_finishes.clear()
    await et.transcode({**frame, "__account_id": aid3})
    await et.transcode({"chat_queue_update": {"id": 46605849959, "total": 23,
                                              "pending": 0, "isCanceled": True},
                        "__account_id": aid3})
    await wd.on_inbound_message(aid3, fan3, 1)
    assert await _pending_jobs(aid3, "scrape_chats") == [], "late cancel ignored"

    # Control: no blast in the window at all → no scrape, on either source.
    aid4, fan4 = "w7_no_blast", 6306
    await _seed_account(aid4, webhook_enabled=True)
    _clear_claims()
    et._queue_finishes.clear()
    await _seed_blast_run(aid4, minutes_ago=90)      # older than the 60-min window
    await wd.on_inbound_message(aid4, fan4, 1)
    assert await _pending_jobs(aid4, "scrape_chats") == [], "scraped without a blast"


async def case_the_scrape_runs_even_for_a_fan_nobody_will_answer():
    """ABOVE `_classify_kind`, deliberately. A terminal-stage fan — skip-listed, or
    a whale a human owns — gets NO chat job, and his inbox needs the copy MORE than
    anyone's, not less. Same reasoning as the customs mark in `on_inbound_tip`."""
    aid, fan = "w7_blast_terminal", 6307
    await _seed_account(aid, webhook_enabled=True)
    _clear_claims()
    await _seed_blast_run(aid, minutes_ago=5)
    await _seed_skip(aid, fan, "unreachable")

    await wd.on_inbound_message(aid, fan, 1)
    scrapes = await _pending_jobs(aid, "scrape_chats")
    assert len(scrapes) == 1, [j.kind for j in await _pending_jobs(aid)]
    chat = [j for j in await _pending_jobs(aid) if j.kind != "scrape_chats"]
    assert chat == [], [j.kind for j in chat]


_harness.run(
    case_gate_off_no_enqueue,
    case_global_kill_switch,
    case_inbound_enqueues_ai_chat,
    case_inbound_mid_funnel_enqueues_funnel,
    case_two_fans_each_get_a_job,
    case_inbound_graduated_fan_no_enqueue,
    case_inbound_terminal_no_enqueue,
    case_inbound_on_cooldown_skips,
    case_inbound_short_cooldown_defers,
    case_dedup_single_pending,
    case_inbound_delay_schedules_future_job,
    case_supervisor_wakes_on_event,
    case_hard_yield_human_send_sets_cooldown,
    case_inbound_image_hands_off_one_words_job,
    case_inbound_image_gif_is_not_stranded,
    case_inbound_image_gate_off_account_enqueues_nothing,
    case_inbound_after_a_blast_enqueues_a_one_fan_scrape,
    case_a_human_of_app_blast_triggers_the_scrape_too,
    case_the_scrape_runs_even_for_a_fan_nobody_will_answer,
    case_concurrent_same_fan_one_job,
    case_concurrent_two_fans_neither_waits,
)
