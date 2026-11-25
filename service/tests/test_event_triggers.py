#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import automation_executor as ax  # noqa: E402
import automations.promo_reactivate as pr  # noqa: E402
import dispatch_plan  # noqa: E402
import event_transcoder  # noqa: E402
import ownership  # noqa: E402
import purchase_notifications as pn  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, AutomationRule, ScheduledJob  # noqa: E402

FOLLOWUP, WELCOME, PROMO = "purchase_followup", "send_welcome", "promo_reactivate"
_STEPS = {"enabled": False, "text": "thanks {name}"}
_N = 0


async def _rule(kind: str, *, every: int = 3600, enabled: bool = True,
                quiet: list[int] | None = None) -> str:
    global _N
    _N += 1
    aid = f"evt_{kind}_{_N}"
    async with get_session() as s:
        s.add(Account(id=aid))
        if quiet is not None:
            s.add(AccountAiConfig(account_id=aid, utc_offset=0, timezone="UTC"))
        s.add(AutomationRule(
            account_id=aid, name=f"{kind} {aid}", kind=kind, is_enabled=enabled,
            trigger_json=json.dumps({"every_seconds": every}),
            steps_json=json.dumps(_STEPS),
            quiet_hours_json=json.dumps(quiet) if quiet is not None else None))
    return aid


async def _jobs(aid: str, kind: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == kind)
            .order_by(ScheduledJob.id))).scalars())


async def _set_status(aid: str, status: str) -> None:
    async with get_session() as s:
        await s.execute(update(ScheduledJob).where(ScheduledJob.account_id == aid)
                        .values(status=status))


async def _age(aid: str, seconds: float) -> None:
    async with get_session() as s:
        await s.execute(update(ScheduledJob).where(ScheduledJob.account_id == aid)
                        .values(created_at=datetime.utcnow() - timedelta(seconds=seconds)))


async def _fired_once(aid: str, kind: str) -> None:
    await ax._materialize_due_rules()
    assert len(await _jobs(aid, kind)) == 1
    await _set_status(aid, "done")
    await _age(aid, dispatch_plan.POKE_FLOOR_S + 1)



async def case_a_poke_fires_the_rules_own_job_before_its_cadence():
    aid = await _rule(FOLLOWUP)
    await _fired_once(aid, FOLLOWUP)
    await ax._materialize_due_rules()
    assert len(await _jobs(aid, FOLLOWUP)) == 1, "fired again without a poke"
    ax.poke_rule(aid, FOLLOWUP)
    await ax._materialize_due_rules()
    jobs = await _jobs(aid, FOLLOWUP)
    assert len(jobs) == 2, [j.status for j in jobs]
    rule_id = jobs[0].rule_id
    assert jobs[1].rule_id == rule_id and rule_id is not None
    assert json.loads(jobs[1].payload_json) == _STEPS and jobs[1].status == "pending"
    assert ax._poked == set(), ax._poked


async def case_repeated_pokes_over_repeated_passes_give_one_job():
    aid = await _rule(WELCOME, every=300)
    await _fired_once(aid, WELCOME)
    for _ in range(3):
        ax.poke_rule(aid, WELCOME)
        ax.poke_rule(aid, WELCOME)
        await ax._materialize_due_rules()
    jobs = await _jobs(aid, WELCOME)
    assert [j.status for j in jobs] == ["done", "pending"], [j.status for j in jobs]


async def case_a_poke_on_a_job_not_yet_started_is_spent_and_adds_nothing():
    aid = await _rule(FOLLOWUP)
    await ax._materialize_due_rules()
    ax.poke_rule(aid, FOLLOWUP)
    await ax._materialize_due_rules()
    assert len(await _jobs(aid, FOLLOWUP)) == 1
    await _set_status(aid, "done")
    await ax._materialize_due_rules()
    assert len(await _jobs(aid, FOLLOWUP)) == 1, "the spent poke fired after the job"


async def case_a_poke_during_a_run_fires_once_after_it_never_during():
    aid = await _rule(FOLLOWUP)
    await ax._materialize_due_rules()
    await _set_status(aid, "running")
    ax.poke_rule(aid, FOLLOWUP)
    for _ in range(2):
        await ax._materialize_due_rules()
        assert len(await _jobs(aid, FOLLOWUP)) == 1, "a job stacked on a running one"
    await _set_status(aid, "done")
    await _age(aid, dispatch_plan.POKE_FLOOR_S + 1)
    await ax._materialize_due_rules()
    await ax._materialize_due_rules()
    jobs = await _jobs(aid, FOLLOWUP)
    assert [j.status for j in jobs] == ["done", "pending"], [j.status for j in jobs]


async def case_a_poke_under_the_floor_is_deferred_to_the_first_pass_past_it():
    aid = await _rule(PROMO, every=300)
    await ax._materialize_due_rules()
    await _set_status(aid, "done")
    await _age(aid, 10)
    ax.poke_rule(aid, PROMO)
    for _ in range(2):
        await ax._materialize_due_rules()
        assert len(await _jobs(aid, PROMO)) == 1, "a poke under the floor fired the rule"
        assert (aid, PROMO) in ax._poked, "the floored poke was spent"
    await _age(aid, dispatch_plan.POKE_FLOOR_S + 1)
    await ax._materialize_due_rules()
    jobs = await _jobs(aid, PROMO)
    assert [j.status for j in jobs] == ["done", "pending"], [j.status for j in jobs]
    assert ax._poked == set(), ax._poked
    await _set_status(aid, "done")
    await _age(aid, dispatch_plan.POKE_FLOOR_S + 1)
    await ax._materialize_due_rules()
    assert len(await _jobs(aid, PROMO)) == 2, "the deferred poke fired twice"
    aid = await _rule(WELCOME, every=300)
    await ax._materialize_due_rules()
    await _set_status(aid, "done")
    await _age(aid, 10)
    ax.poke_rule(aid, WELCOME)
    await ax._materialize_due_rules()
    assert (aid, WELCOME) not in ax._poked, "send_welcome kept a poke under the floor"
    await _age(aid, dispatch_plan.POKE_FLOOR_S + 1)
    await ax._materialize_due_rules()
    assert len(await _jobs(aid, WELCOME)) == 1, "a spent welcome poke fired later"


async def case_a_deferred_poke_is_cleared_when_its_rule_goes_off():
    aid = await _rule(PROMO, every=300)
    await ax._materialize_due_rules()
    await _set_status(aid, "done")
    await _age(aid, 10)
    ax.poke_rule(aid, PROMO)
    await ax._materialize_due_rules()
    assert (aid, PROMO) in ax._poked
    async with get_session() as s:
        await s.execute(update(AutomationRule).where(AutomationRule.account_id == aid)
                        .values(is_enabled=False))
    await ax._materialize_due_rules()
    assert ax._poked == set(), "a poke with no enabled rule was kept"


async def case_no_rule_a_disabled_rule_or_quiet_hours_enqueue_nothing():
    ax.poke_rule("evt_no_rule", FOLLOWUP)
    off = await _rule(FOLLOWUP, enabled=False)
    ax.poke_rule(off, FOLLOWUP)
    quiet = await _rule(WELCOME, quiet=[0, 24])
    ax.poke_rule(quiet, WELCOME)
    await ax._materialize_due_rules()
    assert await _jobs("evt_no_rule", FOLLOWUP) == []
    assert await _jobs(off, FOLLOWUP) == []
    assert await _jobs(quiet, WELCOME) == [], "a poke broke through quiet hours"
    assert ax._poked == set(), ax._poked


async def case_w30_f10_a_quiet_hours_poke_is_kept_for_the_end_of_the_band():
    aid = await _rule(PROMO, quiet=[])
    await _fired_once(aid, PROMO)
    async with get_session() as s:
        await s.execute(update(AutomationRule).where(AutomationRule.account_id == aid)
                        .values(quiet_hours_json=json.dumps([0, 24])))
    ax.poke_rule(aid, PROMO)
    await ax._materialize_due_rules()
    assert len(await _jobs(aid, PROMO)) == 1, "a poke broke through quiet hours"
    assert (aid, PROMO) in ax._poked, "the quiet-hours skip spent the promo poke"
    async with get_session() as s:
        await s.execute(update(AutomationRule).where(AutomationRule.account_id == aid)
                        .values(quiet_hours_json=None))
    await ax._materialize_due_rules()
    assert [j.status for j in await _jobs(aid, PROMO)] == ["done", "pending"]
    assert ax._poked == set(), ax._poked



class _Pokes:
    def __enter__(self):
        self.seen: list[tuple[str, str]] = []
        self._orig = ax.poke_rule
        ax.poke_rule = lambda aid, kind: self.seen.append((str(aid), kind))
        return self

    def __exit__(self, *exc):
        ax.poke_rule = self._orig


def _purchase(notif_id: int, created: datetime) -> dict:
    link = f"<a href='https://onlyfans.com/my/chats/chat/4242?firstId={notif_id + 7}'>message</a>"
    return {"id": notif_id, "type": "paided_message",
            "subType": "subscriber_pay_for_chat_message",
            "createdAt": created.isoformat(),
            "replacePairs": {"{NAME}": "Dan", "{MESSAGE_LINK}": link, "{AMOUNT}": "$6.00"}}


async def case_a_fresh_purchase_pokes_the_followup_once_and_never_on_a_re_sighting():
    orig_flip, orig_stamp = pn._flip_paid, ownership.try_stamp_message

    async def flipped(*_a, **_k):
        return True

    async def stamped(*_a, **_k):
        return 0

    pn._flip_paid, ownership.try_stamp_message = flipped, stamped
    now = datetime.now(timezone.utc)
    try:
        with _Pokes() as p:
            items = [_purchase(9_001, now), _purchase(9_002, now)]
            await pn._handle_items("evt_buy", None, items)
            assert p.seen == [("evt_buy", FOLLOWUP)], p.seen
            await pn._handle_items("evt_buy", None, items)
            assert p.seen == [("evt_buy", FOLLOWUP)], "a re-sighting poked again"
            await pn._handle_items("evt_buy", None, [_purchase(9_003, now - timedelta(days=1))])
            assert p.seen == [("evt_buy", FOLLOWUP)], "a stale purchase poked"
    finally:
        pn._flip_paid, ownership.try_stamp_message = orig_flip, orig_stamp


async def case_a_subscribed_toast_pokes_the_welcome_and_promo_and_other_toasts_do_not():
    with _Pokes() as p:
        await event_transcoder.transcode({"toasts": [{"type": "favorited", "data": {}}],
                                          "__account_id": "evt_toast"})
        assert p.seen == [], p.seen
        await event_transcoder.transcode({
            "toasts": [{"id": 1, "type": "subscribed", "title": "New subscriber",
                        "data": {"relatedUser": {"id": 77, "name": "Al"}}}],
            "__account_id": "evt_toast"})
        assert p.seen == [("evt_toast", WELCOME), ("evt_toast", PROMO)], p.seen
        await event_transcoder.transcode({"toasts": {"type": "subscribed"},
                                          "__account_id": "evt_toast2"})
        assert p.seen[-2:] == [("evt_toast2", WELCOME), ("evt_toast2", PROMO)], p.seen


async def case_w30_f28_replayed_subscribe_toast_pokes_once():
    def frame(*ids):
        return {"toasts": [{"type": "subscribed", **({} if i is None else {"id": i})} for i in ids],
                "__account_id": "evt_replay"}
    with _Pokes() as p:
        await event_transcoder.transcode(frame(901))
        assert p.seen == [("evt_replay", WELCOME), ("evt_replay", PROMO)], p.seen
        await event_transcoder.transcode(frame(901))
        assert len(p.seen) == 2, f"a replay poked again: {p.seen}"
        await event_transcoder.transcode(frame(901, 902))
        await event_transcoder.transcode(frame(None))
        assert len(p.seen) == 6, p.seen


def _gate(aid, claims, *, cap=50, preempt=True, age_s=0.0, ends_in_s=None):
    fin = None if ends_in_s is None else \
        (datetime.utcnow() + timedelta(seconds=ends_in_s)).isoformat() + "+00:00"
    pr._set_gate(aid, {"claims_present": True, "subscriber_count": claims,
                       "subscribe_counts": cap, "finished_at": fin},
                 SimpleNamespace(preempt=preempt), time.monotonic() - age_s)


async def _toast(aid, n=1):
    await event_transcoder.transcode({"toasts": [{"type": "subscribed"}] * n, "__account_id": aid})


async def case_toast_far_from_threshold_no_poke():
    _gate("gate_far", 2)
    with _Pokes() as p:
        for _ in range(5):
            await _toast("gate_far")
        assert p.seen == [("gate_far", WELCOME)] * 5, p.seen


async def case_toast_near_threshold_pokes():
    _gate("gate_near", 42)
    with _Pokes() as p:
        await _toast("gate_near")
        assert ("gate_near", PROMO) not in p.seen, p.seen
        await _toast("gate_near")
        assert p.seen[-1] == ("gate_near", PROMO), p.seen


async def case_toast_burst_in_one_frame_counts_each():
    _gate("gate_burst", 41)
    with _Pokes() as p:
        await _toast("gate_burst", 3)
        assert p.seen == [("gate_burst", WELCOME), ("gate_burst", PROMO)], p.seen


async def case_toast_no_or_stale_read_pokes():
    pr._set_gate("gate_none", None, None, time.monotonic())
    _gate("gate_stale", 2, age_s=601)
    with _Pokes() as p:
        await _toast("gate_none")
        await _toast("gate_stale")
        assert ("gate_none", PROMO) in p.seen and ("gate_stale", PROMO) in p.seen, p.seen


async def case_f15_stale_gate_keeps_no_toast_history():
    _gate("gate_stale_many", 2, age_s=601)
    pr._gate.pop("gate_gone", None)
    with _Pokes() as p:
        for _ in range(20):
            await _toast("gate_stale_many", 3)
            await _toast("gate_gone", 3)
        assert p.seen.count(("gate_stale_many", PROMO)) == 20, p.seen
        assert p.seen.count(("gate_gone", PROMO)) == 20, p.seen
    assert not pr._toasts.get("gate_stale_many") and not pr._toasts.get("gate_gone"), \
        (len(pr._toasts.get("gate_stale_many", ())), len(pr._toasts.get("gate_gone", ())))


async def case_toast_end_near_pokes():
    _gate("gate_end", 2, ends_in_s=300)
    with _Pokes() as p:
        await _toast("gate_end")
        assert p.seen[-1] == ("gate_end", PROMO), p.seen


async def case_toast_without_preempt_waits_for_the_cap():
    _gate("gate_cap", 44, preempt=False)
    with _Pokes() as p:
        await _toast("gate_cap", 4)
        assert ("gate_cap", PROMO) not in p.seen, p.seen
        await _toast("gate_cap")
        assert p.seen[-1] == ("gate_cap", PROMO), p.seen


async def case_a_ws_unlock_frame_pokes_the_followup():
    async with get_session() as s:
        s.add(Account(id="evt_ws"))
    with _Pokes() as p:
        await event_transcoder.transcode({
            "paidMessage": {"id": 555001, "price": 5, "fromUser": {"id": 4243},
                            "createdAt": datetime.now(timezone.utc).isoformat()},
            "__account_id": "evt_ws"})
        assert p.seen == [("evt_ws", FOLLOWUP)], p.seen


_harness.run()
