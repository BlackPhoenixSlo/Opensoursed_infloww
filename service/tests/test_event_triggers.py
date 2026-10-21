#!/usr/bin/env python3
"""Event-driven purchase and welcome triggers (roadmap W2 2.10).

A purchase (the 30s purchases poll proving one, or a WS unlock frame) pokes the
`purchase_followup` rule, and a `subscribed` toast pokes `send_welcome`
(`automation_executor.poke_rule`). The next materializer pass treats a poked
interval rule as due without waiting for its cadence, and changes nothing
else. Pinned here against the real materializer and a temp DB:

  • a poke materializes the rule's own job (rule_id, steps payload) before
    the cadence has elapsed; without a poke the cadence still holds;
  • no double-fire: repeated pokes over repeated passes give ONE job; a poke
    while that job is still pending adds nothing and is spent; a poke while it
    RUNS fires once more after it, never during it;
  • the floor: a poke within min(every_seconds, 60 s) of the last fire is
    spent without firing, and the cadence covers it;
  • no rule, a disabled rule, or quiet hours: a poke enqueues nothing;
  • the hooks: a fresh purchase notification pokes once, its re-sighting and
    a stale one do not; a `subscribed` toast pokes send_welcome and a
    `favorited` one does not; a WS unlock frame pokes purchase_followup.

No network: no OF client is built, nothing runs a job.

Run: ./venv/bin/python service/tests/test_event_triggers.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import automation_executor as ax  # noqa: E402
import event_transcoder  # noqa: E402
import ownership  # noqa: E402
import purchase_notifications as pn  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, AutomationRule, ScheduledJob  # noqa: E402

FOLLOWUP, WELCOME = "purchase_followup", "send_welcome"
_STEPS = {"enabled": False, "text": "thanks {name}"}   # never sends: no job runs here
_N = 0


async def _rule(kind: str, *, every: int = 3600, enabled: bool = True,
                quiet: list[int] | None = None) -> str:
    """A fresh account with one interval rule of `kind`; returns the account id."""
    global _N
    _N += 1
    aid = f"evt_{kind}_{_N}"
    async with get_session() as s:
        s.add(Account(id=aid))
        if quiet is not None:   # a clock, or quiet hours do not apply (rhythm)
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
    """Make every job of `aid` `seconds` old (the cadence and poke-floor anchor)."""
    async with get_session() as s:
        await s.execute(update(ScheduledJob).where(ScheduledJob.account_id == aid)
                        .values(created_at=datetime.utcnow() - timedelta(seconds=seconds)))


async def _fired_once(aid: str, kind: str) -> None:
    """The rule's first fire (no prior job, so it is due), then marked done and
    aged past the poke floor: from here on its cadence is NOT elapsed, but a
    poke may fire it."""
    await ax._materialize_due_rules()
    assert len(await _jobs(aid, kind)) == 1
    await _set_status(aid, "done")
    await _age(aid, ax._POKE_FLOOR_S + 1)


# ── The materializer ────────────────────────────────────────────────────────

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
    await ax._materialize_due_rules()            # first fire: a pending job
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
    await _age(aid, ax._POKE_FLOOR_S + 1)   # a sweep long enough to outlast the floor
    await ax._materialize_due_rules()
    await ax._materialize_due_rules()
    jobs = await _jobs(aid, FOLLOWUP)
    assert [j.status for j in jobs] == ["done", "pending"], [j.status for j in jobs]


async def case_a_poke_under_the_floor_is_spent_and_the_cadence_covers_it():
    aid = await _rule(WELCOME, every=300)
    await ax._materialize_due_rules()
    await _set_status(aid, "done")
    await _age(aid, 10)                        # last fire 10 s ago: under the 60 s floor
    ax.poke_rule(aid, WELCOME)
    await ax._materialize_due_rules()
    assert len(await _jobs(aid, WELCOME)) == 1, "a poke under the floor fired the rule"
    assert ax._poked == set(), "the floored poke was kept"
    await _age(aid, ax._POKE_FLOOR_S + 1)
    await ax._materialize_due_rules()
    assert len(await _jobs(aid, WELCOME)) == 1, "the spent poke fired later"
    await _age(aid, 301)                       # the cadence backstop
    await ax._materialize_due_rules()
    assert len(await _jobs(aid, WELCOME)) == 2


async def case_no_rule_a_disabled_rule_or_quiet_hours_enqueue_nothing():
    ax.poke_rule("evt_no_rule", FOLLOWUP)
    off = await _rule(FOLLOWUP, enabled=False)
    ax.poke_rule(off, FOLLOWUP)
    quiet = await _rule(WELCOME, quiet=[0, 24])   # a band covering every hour
    ax.poke_rule(quiet, WELCOME)
    await ax._materialize_due_rules()
    assert await _jobs("evt_no_rule", FOLLOWUP) == []
    assert await _jobs(off, FOLLOWUP) == []
    assert await _jobs(quiet, WELCOME) == [], "a poke broke through quiet hours"
    assert ax._poked == set(), ax._poked


# ── The hooks ───────────────────────────────────────────────────────────────

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
            assert p.seen == [("evt_buy", FOLLOWUP)], p.seen   # once per batch
            await pn._handle_items("evt_buy", None, items)
            assert p.seen == [("evt_buy", FOLLOWUP)], "a re-sighting poked again"
            await pn._handle_items("evt_buy", None, [_purchase(9_003, now - timedelta(days=1))])
            assert p.seen == [("evt_buy", FOLLOWUP)], "a stale purchase poked"
    finally:
        pn._flip_paid, ownership.try_stamp_message = orig_flip, orig_stamp


async def case_a_subscribed_toast_pokes_the_welcome_and_other_toasts_do_not():
    with _Pokes() as p:
        await event_transcoder.transcode({"toasts": [{"type": "favorited", "data": {}}],
                                          "__account_id": "evt_toast"})
        assert p.seen == [], p.seen
        await event_transcoder.transcode({
            "toasts": [{"id": 1, "type": "subscribed", "title": "New subscriber",
                        "data": {"relatedUser": {"id": 77, "name": "Al"}}}],
            "__account_id": "evt_toast"})
        assert p.seen == [("evt_toast", WELCOME)], p.seen
        await event_transcoder.transcode({"toasts": {"type": "subscribed"},
                                          "__account_id": "evt_toast2"})
        assert p.seen[-1] == ("evt_toast2", WELCOME), p.seen


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
