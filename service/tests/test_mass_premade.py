#!/usr/bin/env python3
"""
P3 mass_premade — timed broadcasts (send → resend → unsend, 2 ways).

A thin orchestrator over send_mass_message + unsend_messages; it owns only the
timers. We drive it with an `online_only` audience so the send needs no explicit
recipients (OF resolves "online" server-side) — keeping the test about the
SCHEDULING, not mass persistence (covered by test_send_mass).

Cases:
  case_send_and_schedule_unsend (acceptance):
      one message with unsend_after_hours → send_mass_message fires, and a
      one-shot unsend_messages job is enqueued ~now+ttl with {queue_id, mass_run_id}.
  case_resend_chain (Way 1):
      resend_count=1 + resend_after_hours → a mass_premade job is enqueued
      ~now+resend_after with resend_count decremented to 0.
  case_no_resend_when_zero:
      resend_count=0 → no resend job is enqueued.
  case_drip_list (Way 2):
      a 2-message list sends the first and re-enqueues mass_premade with the rest.
  case_dry_run_plans_nothing:
      dry_run returns the plan, sends nothing, enqueues nothing.
  case_enqueue_raises_after_broadcast_parks:
      send once: the broadcast went out, then enqueueing its unsend raised ->
      exactly 1 broadcast, the claimed job ends 'error' ("may have sent"), and
      a second run finds nothing to claim (no re-broadcast).

Run: ./venv/bin/python service/tests/test_mass_premade.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import automations.mass_premade as mp  # noqa: E402,F401 — registers
import automations.send_mass_message as smm  # noqa: E402,F401 — registers (delegate)
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, MassRun, ScheduledJob  # noqa: E402

KIND = "mass_premade"


class FakeClient:
    """Records send_mass_message calls; returns an incrementing OF queue id."""

    def __init__(self, start_id: int = 880000):
        self.user_id = "999"
        self.send_calls: list[dict] = []
        self._next = start_id

    def send_mass_message(self, text, **kw) -> dict:
        self._next += 1
        self.send_calls.append({"text": text, **kw})
        return {"id": self._next, "createdAt": "2026-06-05T10:00:00+00:00"}


def _use_fake(**kw) -> FakeClient:
    fake = FakeClient(**kw)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _jobs(aid: str, kind: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.kind == kind
            )
        )).scalars().all()


# ── Acceptance: send + schedule the unsend ───────────────────────────

async def case_send_and_schedule_unsend():
    aid = "acc_mp_unsend"
    await _seed_account(aid)
    fake = _use_fake()

    res = await run_once(aid, KIND, payload={"messages": [
        {"text": "<p>premade</p>", "online_only": True, "unsend_after_hours": 8},
    ]})

    assert res["status"] == "ok" and res["sent"] == 1, res
    assert len(fake.send_calls) == 1, fake.send_calls
    assert fake.send_calls[0]["online_only"] is True, fake.send_calls[0]
    queue_id = res["queue_id"]
    assert queue_id is not None and res["mass_run_id"] is not None, res

    dels = await _jobs(aid, "unsend_messages")
    assert len(dels) == 1, dels
    tgt = json.loads(dels[0].payload_json)["targets"][0]
    assert tgt["queue_id"] == queue_id and tgt["mass_run_id"] == res["mass_run_id"], tgt
    delta_h = (dels[0].run_at - datetime.utcnow()).total_seconds() / 3600
    assert 7.5 < delta_h < 8.5, delta_h
    # No resend, single message → no mass_premade follow-up.
    assert await _jobs(aid, KIND) == []
    # wave6 B7: the broadcast is attributed to mass_premade, not send_mass_message.
    async with get_session() as s:
        mr = await s.get(MassRun, res["mass_run_id"])
    assert mr.automation_kind == KIND, mr.automation_kind


# ── Way 1: resend chain decrements the count ─────────────────────────

async def case_resend_chain():
    aid = "acc_mp_resend"
    await _seed_account(aid)
    _use_fake()

    res = await run_once(aid, KIND, payload={"messages": [
        {"text": "<p>resend me</p>", "online_only": True,
         "resend_count": 1, "resend_after_hours": 24, "unsend_after_hours": 6},
    ]})

    assert res["status"] == "ok", res
    assert res["resend_job_id"] is not None and res["resends_left"] == 0, res

    resends = await _jobs(aid, KIND)
    assert len(resends) == 1, resends
    msgs = json.loads(resends[0].payload_json)["messages"]
    assert len(msgs) == 1 and msgs[0]["resend_count"] == 0, msgs
    delta_h = (resends[0].run_at - datetime.utcnow()).total_seconds() / 3600
    assert 23.5 < delta_h < 24.5, delta_h
    # And it still scheduled the first send's unsend.
    assert len(await _jobs(aid, "unsend_messages")) == 1


async def case_no_resend_when_zero():
    aid = "acc_mp_noresend"
    await _seed_account(aid)
    _use_fake()

    res = await run_once(aid, KIND, payload={"messages": [
        {"text": "<p>once</p>", "online_only": True, "resend_count": 0,
         "resend_after_hours": 24},
    ]})

    assert res["status"] == "ok" and res["resend_job_id"] is None, res
    assert await _jobs(aid, KIND) == [], "resend_count=0 must not chain"


# ── Way 2: a list drips the remainder forward ────────────────────────

async def case_drip_list():
    aid = "acc_mp_drip"
    await _seed_account(aid)
    fake = _use_fake()

    res = await run_once(aid, KIND, payload={"messages": [
        {"text": "<p>m1</p>", "online_only": True, "unsend_after_hours": 4},
        {"text": "<p>m2</p>", "online_only": True, "delay_minutes": 15},
    ]})

    assert res["status"] == "ok" and res["remaining"] == 1, res
    assert len(fake.send_calls) == 1, "only the first message goes out this run"

    drips = await _jobs(aid, KIND)
    assert len(drips) == 1, drips
    rest = json.loads(drips[0].payload_json)["messages"]
    assert len(rest) == 1 and rest[0]["text"] == "<p>m2</p>", rest
    delta_min = (drips[0].run_at - datetime.utcnow()).total_seconds() / 60
    assert 13 < delta_min < 17, delta_min


# ── dry_run: full plan, zero side effects ────────────────────────────

async def case_dry_run_plans_nothing():
    aid = "acc_mp_dry"
    await _seed_account(aid)
    fake = _use_fake()

    res = await run_once(aid, KIND, payload={
        "dry_run": True,
        "messages": [
            {"text": "a", "online_only": True, "unsend_after_hours": 6, "resend_count": 2,
             "included_users": [42], "list_ids": [7]},
            {"text": "b", "delay_minutes": 20},
        ],
    })

    assert res["dry_run"] is True and res["messages"] == 2 and res["sent"] == 0, res
    assert res["plan"][0]["resend_count"] == 2 and res["plan"][1]["delay_minutes"] == 20, res["plan"]
    # wave6 B7: the plan names the audience, so a dry run can confirm WHO gets it.
    assert res["plan"][0]["included_users"] == [42], res["plan"][0]
    assert res["plan"][0]["list_ids"] == [7], res["plan"][0]
    assert fake.send_calls == [], "dry_run must not send"
    assert await _jobs(aid, KIND) == [] and await _jobs(aid, "unsend_messages") == []


# ── Randomiser: one text from the pool + sampled media per fire ──────

async def case_randomizer():
    aid = "acc_mp_rand"
    await _seed_account(aid)
    fake = _use_fake()

    texts = ["<p>a</p>", "<p>b</p>"]
    pool = [11, 12, 13, 14]
    res = await run_once(aid, KIND, payload={"messages": [{
        "texts": texts, "media_files": pool, "media_count": 2,
        "online_only": True,
    }]})

    assert res["status"] == "ok" and res["sent"] == 1, res
    call = fake.send_calls[0]
    assert call["text"] in texts, call["text"]
    assert len(call["media_files"]) == 2 and len(set(call["media_files"])) == 2, call["media_files"]
    assert set(call["media_files"]) <= set(pool), call["media_files"]
    assert call["online_only"] is True


async def case_enqueue_raises_after_broadcast_parks():
    aid = "acc_mp_once"
    await _seed_account(aid)
    fake = _use_fake()
    job_id = await ax.enqueue_job(aid, KIND, payload={"messages": [
        {"text": "<p>once</p>", "online_only": True, "unsend_after_hours": 8}]})
    real = ax.enqueue_job

    async def boom(account_id, kind, **kw):
        if kind == "unsend_messages":
            raise RuntimeError("database is locked")
        return await real(account_id, kind, **kw)
    ax.enqueue_job = boom
    try:
        res = await run_once(aid, KIND)
        again = await run_once(aid, KIND)
    finally:
        ax.enqueue_job = real
    assert res["status"] == "error", res
    assert len(fake.send_calls) == 1, f"one broadcast, got {len(fake.send_calls)}"
    async with get_session() as s:
        job = await s.get(ScheduledJob, job_id)
    assert job.status == "error", f"job {job.status}: a sent broadcast must not be retried"
    assert "may have sent" in (job.last_error or ""), job.last_error
    assert again.get("reason") == "no_job", again
    assert len(fake.send_calls) == 1, "no re-broadcast"


_harness.run(
    case_send_and_schedule_unsend,
    case_resend_chain,
    case_no_resend_when_zero,
    case_drip_list,
    case_dry_run_plans_nothing,
    case_randomizer,
    case_enqueue_raises_after_broadcast_parks,
)
