#!/usr/bin/env python3
"""
A12 unsend_messages — `case_unsend`:
  "marks messages.is_unsent + writes actions; uses the queue/per-chat delete
   per window."

Cases:
  case_per_chat_unsend (the acceptance):
      target a per-chat outbound message → of_client.unsend_message called with
      (message_id, with_user_id=fan), messages.is_unsent flips True, an actions
      row (action=unsend_message, employee_id NULL) is written, run status=ok.
  case_mass_unsend:
      a {queue_id, mass_run_id} target → cancel_scheduled(queue_id) called, ALL
      messages of that mass_run flip is_unsent, actions row action=unsend_mass.
  case_policy_sweep_per_chat_window:
      no explicit targets → DB sweep picks only outbound text bubbles older than
      text_hours AND still inside the 24h window (a 30h-old one is skipped, a
      media bubble is skipped), and unsends them.
  case_one_failure_does_not_sink_run:
      a target whose OF call raises is counted failed; the run still completes ok
      and a sibling good target still unsends.

Run: ./venv/bin/python service/tests/test_a12_unsend.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402 — shared _make_client seam
import automations.unsend_messages as a12  # noqa: E402,F401 — module under test (registers)
from automation_executor import enqueue_job, run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Action, AutomationRun, MassRun, Message, Post, ScheduledJob  # noqa: E402

KIND = "unsend_messages"


# ── Fake OFClient: records every unsend/cancel call, no network ───────

class FakeClient:
    def __init__(self, user_id: str = "999", fail_on: set | None = None):
        self.user_id = user_id
        self.unsend_calls: list[tuple] = []
        self.cancel_calls: list[int] = []
        self.delete_post_calls: list[int] = []
        self._fail_on = fail_on or set()

    def unsend_message(self, message_id, with_user_id=None):
        if message_id in self._fail_on:
            raise RuntimeError(f"OF refused unsend {message_id}")
        self.unsend_calls.append((int(message_id), with_user_id))
        return {"success": True}

    def cancel_scheduled(self, queue_id):
        self.cancel_calls.append(int(queue_id))
        return {"success": True}

    def delete_post(self, post_id):
        if post_id in self._fail_on:
            raise RuntimeError(f"OF refused delete_post {post_id}")
        self.delete_post_calls.append(int(post_id))
        return {"success": True}


def _use_fake(**kw) -> FakeClient:
    fake = FakeClient(**kw)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _add_message(
    aid: str, fan: int, mid: int, *, direction="out", created: datetime,
    media_count=0, is_unsent=False, mass_run_id=None,
) -> None:
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan, message_id=mid, direction=direction,
            body="hi", media_count=media_count, is_unsent=is_unsent,
            mass_run_id=mass_run_id, created_at=created,
        ))


# ── The acceptance: per-chat unsend flips is_unsent + actions row ────

async def case_per_chat_unsend():
    aid, fan, mid = "acc_a12_chat", 5001, 70001
    await _seed_account(aid)
    await _add_message(aid, fan, mid, created=datetime.utcnow() - timedelta(hours=10))
    fake = _use_fake()

    await enqueue_job(aid, KIND, payload={"targets": [{"message_id": mid, "fan_id": fan}]})
    res = await run_once(aid, KIND)

    assert res["status"] == "ok", res
    assert res["unsent"] == 1 and res["failed"] == 0, res
    assert res["rows_flipped"] == 1, res
    # OF reflects it: unsend_message called with withUserId=fan (mass-bubble seam).
    assert fake.unsend_calls == [(mid, fan)], fake.unsend_calls

    async with get_session() as s:
        m = await s.get(Message, (aid, fan, mid))
        assert m.is_unsent is True, "is_unsent flipped"
        assert m.unsent_at is not None and "automation" in (m.unsent_reason or "")
        acts = (await s.execute(
            select(Action).where(Action.account_id == aid)
        )).scalars().all()
        assert len(acts) == 1, f"one action row, got {len(acts)}"
        assert acts[0].action == "unsend_message", acts[0].action
        assert acts[0].employee_id is None, "automation attribution (NULL employee)"
        assert acts[0].target_id == str(mid)
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "ok", runs


# ── Mass unsend: cancel_scheduled + flip the whole run ───────────────

async def case_mass_unsend():
    aid, fan_a, fan_b = "acc_a12_mass", 5101, 5102
    qid, mrid = 88888, 42
    await _seed_account(aid)
    async with get_session() as s:
        s.add(MassRun(id=mrid, account_id=aid, recipient_count=2, status="done"))
    now = datetime.utcnow()
    await _add_message(aid, fan_a, 71001, created=now, mass_run_id=mrid)
    await _add_message(aid, fan_b, 71002, created=now, mass_run_id=mrid)
    fake = _use_fake()

    await enqueue_job(aid, KIND, payload={
        "targets": [{"queue_id": qid, "mass_run_id": mrid}],
    })
    res = await run_once(aid, KIND)

    assert res["status"] == "ok", res
    assert res["unsent"] == 1 and res["rows_flipped"] == 2, res
    assert fake.cancel_calls == [qid], fake.cancel_calls
    assert fake.unsend_calls == [], "mass path must not hit the per-chat endpoint"

    async with get_session() as s:
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert all(m.is_unsent for m in msgs), "every mass-run message flipped"
        acts = (await s.execute(
            select(Action).where(Action.account_id == aid)
        )).scalars().all()
        assert len(acts) == 1 and acts[0].action == "unsend_mass", acts
        assert acts[0].target_type == "queue" and acts[0].target_id == str(qid)


# ── Policy sweep respects the 24h window + text-only ─────────────────

async def case_policy_sweep_per_chat_window():
    aid, fan = "acc_a12_sweep", 5201
    await _seed_account(aid)
    now = datetime.utcnow()
    # Eligible: outbound text, 10h old (older than 9h, inside 24h).
    await _add_message(aid, fan, 72001, created=now - timedelta(hours=10))
    # Too fresh: 2h old — younger than text_hours.
    await _add_message(aid, fan, 72002, created=now - timedelta(hours=2))
    # Past the per-chat window: 30h old — unsend would 400, so skip.
    await _add_message(aid, fan, 72003, created=now - timedelta(hours=30))
    # Has media: not a text bubble — out of policy scope.
    await _add_message(aid, fan, 72004, created=now - timedelta(hours=10), media_count=3)
    # Inbound: never unsend the fan's messages.
    await _add_message(aid, fan, 72005, direction="in", created=now - timedelta(hours=10))
    fake = _use_fake()

    await enqueue_job(aid, KIND, payload={"policy": {"text_hours": 9}})
    res = await run_once(aid, KIND)

    assert res["status"] == "ok", res
    assert res["unsent"] == 1, f"only the one eligible bubble, got {res}"
    assert fake.unsend_calls == [(72001, fan)], fake.unsend_calls

    async with get_session() as s:
        m_ok = await s.get(Message, (aid, fan, 72001))
        assert m_ok.is_unsent is True
        for mid in (72002, 72003, 72004, 72005):
            assert (await s.get(Message, (aid, fan, mid))).is_unsent is False, mid


# ── One bad target does not sink the run ─────────────────────────────

async def case_one_failure_does_not_sink_run():
    aid, fan = "acc_a12_fail", 5301
    await _seed_account(aid)
    now = datetime.utcnow()
    await _add_message(aid, fan, 73001, created=now - timedelta(hours=10))  # will fail at OF
    await _add_message(aid, fan, 73002, created=now - timedelta(hours=10))  # good
    _use_fake(fail_on={73001})

    await enqueue_job(aid, KIND, payload={"targets": [
        {"message_id": 73001, "fan_id": fan},
        {"message_id": 73002, "fan_id": fan},
    ]})
    res = await run_once(aid, KIND)

    assert res["status"] == "ok", res
    assert res["unsent"] == 1 and res["failed"] == 1, res

    async with get_session() as s:
        assert (await s.get(Message, (aid, fan, 73001))).is_unsent is False, "failed stays sent"
        assert (await s.get(Message, (aid, fan, 73002))).is_unsent is True, "good one unsent"
        acts = (await s.execute(
            select(Action).where(Action.account_id == aid)
        )).scalars().all()
        assert len(acts) == 1, "only the successful unsend audits"


async def case_bad_target_id_skips_not_aborts():
    """A non-numeric payload id must skip that target (logged), NOT raise out of
    _norm_targets and abort the whole run — a valid target alongside it still
    gets unsent."""
    aid, fan, mid = "acc_a12_badid", 5401, 74001
    await _seed_account(aid)
    await _add_message(aid, fan, mid, created=datetime.utcnow() - timedelta(hours=10))
    fake = _use_fake()

    await enqueue_job(aid, KIND, payload={"targets": [
        {"queue_id": "not-a-number"},            # bad → skipped, never fatal
        {"message_id": mid, "fan_id": fan},      # valid → unsent
    ]})
    res = await run_once(aid, KIND)

    assert res["status"] == "ok", res
    assert res["unsent"] == 1, res               # only the valid target ran
    assert fake.unsend_calls == [(mid, fan)], fake.unsend_calls
    assert fake.cancel_calls == [], "the bad mass target was dropped before any OF call"


# ── W2g: dry_run previews targets without touching OF or our rows ────

async def case_dry_run_sends_nothing():
    """A `dry_run` payload returns the would-unsend list but makes NO OF call and
    flips NO rows — both an explicit-targets preview and a policy-sweep preview."""
    aid, fan = "acc_a12_dry", 5501
    await _seed_account(aid)
    now = datetime.utcnow()
    await _add_message(aid, fan, 75001, created=now - timedelta(hours=10))  # text, eligible
    fake = _use_fake()

    # (a) explicit targets, dry_run → preview only
    await enqueue_job(aid, KIND, payload={
        "dry_run": True,
        "targets": [{"message_id": 75001, "fan_id": fan}],
    })
    res = await run_once(aid, KIND)

    assert res["status"] == "ok", res
    assert res["dry_run"] is True, res
    assert res["targets"] == 1 and res["unsent"] == 0 and res["rows_flipped"] == 0, res
    assert res["would_unsend"] == [
        {"kind": "chat", "message_id": 75001, "fan_id": fan}
    ], res["would_unsend"]
    assert fake.unsend_calls == [] and fake.cancel_calls == [], "dry_run hit OF"

    # (b) policy sweep, dry_run → same preview, still no OF + row untouched
    await enqueue_job(aid, KIND, payload={"dry_run": True, "policy": {"text_hours": 9}})
    res2 = await run_once(aid, KIND)
    assert res2["dry_run"] is True and res2["targets"] == 1, res2
    assert res2["would_unsend"][0]["message_id"] == 75001, res2
    assert fake.unsend_calls == [], "dry_run sweep hit OF"

    async with get_session() as s:
        assert (await s.get(Message, (aid, fan, 75001))).is_unsent is False, "untouched"
        acts = (await s.execute(
            select(Action).where(Action.account_id == aid)
        )).scalars().all()
        assert acts == [], "dry_run writes no audit rows"


# ── W2g: media sweep is opt-in and respects policy.media_hours ───────

async def case_media_hours_sweep_window():
    """`policy.media_hours` revives media auto-unsend: a media bubble older than
    media_hours (inside 24h) is swept; a fresher one and an out-of-window one are
    not; text bubbles still honour text_hours alongside it."""
    aid, fan = "acc_a12_media", 5601
    await _seed_account(aid)
    now = datetime.utcnow()
    # Media, 14h old: older than media_hours(12), inside 24h → eligible.
    await _add_message(aid, fan, 76001, created=now - timedelta(hours=14), media_count=2)
    # Media, 6h old: younger than media_hours(12) → skip.
    await _add_message(aid, fan, 76002, created=now - timedelta(hours=6), media_count=2)
    # Media, 30h old: past the 24h per-chat window → skip (needs queue_id).
    await _add_message(aid, fan, 76003, created=now - timedelta(hours=30), media_count=2)
    # Text, 10h old: older than text_hours(9) → still swept alongside media.
    await _add_message(aid, fan, 76004, created=now - timedelta(hours=10))
    fake = _use_fake()

    await enqueue_job(aid, KIND, payload={"policy": {"text_hours": 9, "media_hours": 12}})
    res = await run_once(aid, KIND)

    assert res["status"] == "ok", res
    assert res["unsent"] == 2, f"media(14h) + text(10h) only, got {res}"
    sent = {c[0] for c in fake.unsend_calls}
    assert sent == {76001, 76004}, fake.unsend_calls

    async with get_session() as s:
        assert (await s.get(Message, (aid, fan, 76001))).is_unsent is True, "media eligible"
        assert (await s.get(Message, (aid, fan, 76004))).is_unsent is True, "text eligible"
        for mid in (76002, 76003):
            assert (await s.get(Message, (aid, fan, mid))).is_unsent is False, mid


async def case_media_skipped_without_media_hours():
    """Without `policy.media_hours`, media bubbles are NOT swept even when old —
    preserves the text-only default (and the existing sweep contract)."""
    aid, fan = "acc_a12_nomedia", 5701
    await _seed_account(aid)
    now = datetime.utcnow()
    await _add_message(aid, fan, 77001, created=now - timedelta(hours=14), media_count=2)
    fake = _use_fake()

    await enqueue_job(aid, KIND, payload={"policy": {"text_hours": 9}})
    res = await run_once(aid, KIND)

    assert res["status"] == "ok", res
    assert res["unsent"] == 0, f"media must not sweep without media_hours, got {res}"
    assert fake.unsend_calls == [], fake.unsend_calls


# ── P1: post-delete target deletes via /posts/{id} + flips posts row ──

async def case_post_delete():
    """A {post_id, local_post_id} target → delete_post(post_id) called, OUR posts
    row flips status='deleted', actions row action=delete_post (target_type=post).
    This is the cleanup leg the auto_posts automation enqueues."""
    aid = "acc_a12_post"
    of_post_id, local_id = 90001, 7
    await _seed_account(aid)
    async with get_session() as s:
        s.add(Post(
            id=local_id, account_id=aid, of_post_id=of_post_id,
            status="posted", text="self-cleaning post", media_ids="[]",
            posted_at=datetime.utcnow(),
        ))
    fake = _use_fake()

    await enqueue_job(aid, KIND, payload={
        "targets": [{"post_id": of_post_id, "local_post_id": local_id}],
    })
    res = await run_once(aid, KIND)

    assert res["status"] == "ok", res
    assert res["unsent"] == 1 and res["rows_flipped"] == 1, res
    assert fake.delete_post_calls == [of_post_id], fake.delete_post_calls
    assert fake.unsend_calls == [] and fake.cancel_calls == [], "post path is /posts only"

    async with get_session() as s:
        p = await s.get(Post, local_id)
        assert p.status == "deleted", p.status
        acts = (await s.execute(
            select(Action).where(Action.account_id == aid)
        )).scalars().all()
        assert len(acts) == 1, f"one action row, got {len(acts)}"
        assert acts[0].action == "delete_post", acts[0].action
        assert acts[0].target_type == "post" and acts[0].target_id == str(of_post_id)
        assert acts[0].employee_id is None, "automation attribution"


async def case_post_delete_by_of_id_only():
    """Without local_post_id, the row is matched by of_post_id — covers an
    operator-supplied target that only knows the OF id."""
    aid, of_post_id = "acc_a12_post_ofid", 90002
    await _seed_account(aid)
    async with get_session() as s:
        s.add(Post(
            account_id=aid, of_post_id=of_post_id, status="posted",
            text="x", media_ids="[]", posted_at=datetime.utcnow(),
        ))
    fake = _use_fake()

    await enqueue_job(aid, KIND, payload={"targets": [{"post_id": of_post_id}]})
    res = await run_once(aid, KIND)

    assert res["status"] == "ok" and res["unsent"] == 1, res
    assert res["rows_flipped"] == 1, "matched the posts row by of_post_id"
    assert fake.delete_post_calls == [of_post_id], fake.delete_post_calls

    async with get_session() as s:
        rows = (await s.execute(
            select(Post).where(Post.account_id == aid)
        )).scalars().all()
        assert len(rows) == 1 and rows[0].status == "deleted", rows


async def case_failed_post_delete_is_requeued_with_backoff_until_retries_are_spent():
    """A post delete OF refuses is not swallowed: it is re-queued alone (the
    good sibling is not), 15m later, then twice as late each time, and left
    failed after _POST_RETRY_MAX retries. The retry that succeeds flips the row."""
    aid = "acc_a12_post_retry"
    bad, good, local_bad = 90011, 90012, 11
    await _seed_account(aid)
    async with get_session() as s:
        s.add(Post(id=local_bad, account_id=aid, of_post_id=bad, status="posted",
                   text="s4s promo", media_ids="[]", posted_at=datetime.utcnow()))
    fake = _use_fake(fail_on={bad})

    before = datetime.utcnow()
    res = await a12.run(aid, {"targets": [{"post_id": bad, "local_post_id": local_bad},
                                         {"post_id": good}]}, run_id=0)
    assert res["unsent"] == 1 and res["failed"] == 1, res
    assert fake.delete_post_calls == [good], fake.delete_post_calls
    async with get_session() as s:
        job = await s.get(ScheduledJob, res["post_retry_job_id"])
        assert job.kind == KIND and job.account_id == aid and job.status == "pending", job
        assert json.loads(job.payload_json) == {
            "targets": [{"post_id": bad, "local_post_id": local_bad}], "post_retry": 1}, job.payload_json
        mins = (job.run_at - before).total_seconds() / 60
        assert 14.9 < mins < 15.2, mins

    # The 3rd retry backs off 15 * 2**2 = 60m; the last allowed one re-queues; past it, none.
    res = await a12.run(aid, {"targets": [{"post_id": bad}], "post_retry": 2}, run_id=0)
    async with get_session() as s:
        job = await s.get(ScheduledJob, res["post_retry_job_id"])
        assert json.loads(job.payload_json)["post_retry"] == 3
        assert 59.9 < (job.run_at - datetime.utcnow()).total_seconds() / 60 < 60.1
    res = await a12.run(aid, {"targets": [{"post_id": bad}], "post_retry": a12._POST_RETRY_MAX}, run_id=0)
    assert res["failed"] == 1 and res["post_retry_job_id"] is None, res

    # OF accepts on a retry: the row flips and nothing more is queued.
    fake._fail_on.clear()
    res = await a12.run(aid, {"targets": [{"post_id": bad, "local_post_id": local_bad}], "post_retry": 1}, run_id=0)
    assert res["unsent"] == 1 and res["post_retry_job_id"] is None, res
    async with get_session() as s:
        assert (await s.get(Post, local_bad)).status == "deleted"


_harness.run(
    case_per_chat_unsend,
    case_mass_unsend,
    case_policy_sweep_per_chat_window,
    case_one_failure_does_not_sink_run,
    case_bad_target_id_skips_not_aborts,
    case_dry_run_sends_nothing,
    case_media_hours_sweep_window,
    case_media_skipped_without_media_hours,
    case_post_delete,
    case_post_delete_by_of_id_only,
    case_failed_post_delete_is_requeued_with_backoff_until_retries_are_spent,
)
