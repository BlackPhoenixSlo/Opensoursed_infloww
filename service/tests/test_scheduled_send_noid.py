#!/usr/bin/env python3
"""
scheduled_send — characterisation of the no-id send path (pins TODAY's behaviour).

OF can answer a send with 200 + `{"success": true}` and NO message id (a silent
drop). The automated senders (welcome_chatter_for_info, send_followup,
purchase_followup) answer that with `quarantine_if_undeliverable`: probe
`get_user`, and on `subscribedOn` falsy mark the fan `expired` + pause a week.

scheduled_send does NOT do that today. It is a human-deferred one-shot: on a
no-id answer it returns `sent_no_id`, writes no outbound row, sets no cooldown,
never probes `get_user`, and the job is still marked done (never re-fired).
These cases pin exactly that, so a future change to it is a deliberate one.

  case_no_id_send_returns_sent_no_id:
      the send goes out once to the target fan only; result `sent_no_id`,
      message_id None; no `messages` row; job `done` (a second tick sends
      nothing); and though get_user would say `subscribedOn: False`,
      scheduled_send never asks: no get_user call, subscription_status
      untouched, no pause, no skip_list row.
  case_id_send_still_sets_cooldown:
      control: the SAME fan with an id'd answer gets an outbound row + cooldown
      (proves the no-id assertions above are not vacuous).

Run: ./venv/bin/python service/tests/test_scheduled_send_noid.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
from automations import scheduled_send  # noqa: E402,F401 — registers the kind
from automation_executor import enqueue_job, run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Message, ScheduledJob, SkipList  # noqa: E402


class NoIdOF:
    """send_message answers 200 with no id; get_user reports a LAPSED sub."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.probed: list[int] = []

    def send_message(self, chat_id, text, **kw) -> dict:
        self.sent.append((int(chat_id), text))
        return {"success": True}

    def get_user(self, user_id) -> dict:
        self.probed.append(int(user_id))
        return {"id": int(user_id), "subscribedOn": False}


class IdOF(NoIdOF):
    def __init__(self) -> None:
        super().__init__()
        self._next_id = 9_200_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._next_id += 1
        self.sent.append((int(chat_id), text))
        return {"id": self._next_id, "text": f"<p>{text}</p>",
                "createdAt": "2026-06-13T15:38:00+00:00"}


def _use(fake):
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed(aid: str, fid: int) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        if await s.get(Fan, (aid, fid)) is None:
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name="Bob",
                      subscription_status="active"))


async def _enqueue_due(aid: str, payload: dict) -> int:
    return await enqueue_job(
        aid, "scheduled_send", payload=payload,
        run_at=datetime.utcnow() - timedelta(seconds=60),
    )


async def _snapshot(aid: str, fid: int, job_id: int):
    async with get_session() as s:
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fid)
        )).scalars().all()
        fan = await s.get(Fan, (aid, fid))
        skip = await s.get(SkipList, (aid, fid))
        job = await s.get(ScheduledJob, job_id)
        return msgs, fan, skip, job


# ── Cases ─────────────────────────────────────────────────────────────

async def case_no_id_send_returns_sent_no_id():
    aid, fid = "acc_ss_noid1", 4101
    await _seed(aid, fid)
    fake = _use(NoIdOF())
    job_id = await _enqueue_due(aid, {"fan_id": fid, "text": "later babe",
                                      "send_purpose": "manual"})

    res = await run_once(aid, "scheduled_send")
    assert res["status"] == "sent_no_id", res
    assert res["message_id"] is None and res["fan_id"] == fid, res
    assert fake.sent == [(fid, "later babe")], fake.sent   # only the target, once
    # Pinned gap: no quarantine_if_undeliverable probe on this path.
    assert fake.probed == [], f"get_user probed: {fake.probed}"

    msgs, fan, skip, job = await _snapshot(aid, fid, job_id)
    assert msgs == [], "no outbound row without an OF id"
    assert fan.subscription_status == "active", fan.subscription_status
    assert fan.automation_paused_until is None, fan.automation_paused_until
    assert skip is None, f"skip_list row written: {skip.reason}"
    assert job is not None and job.status == "done", job and job.status

    # The job is consumed: a second tick sends nothing more.
    again = await run_once(aid, "scheduled_send", job_only=True)
    assert again["status"] == "skipped", again
    assert fake.sent == [(fid, "later babe")], fake.sent


async def case_id_send_still_sets_cooldown():
    aid, fid = "acc_ss_noid3", 4301
    await _seed(aid, fid)
    fake = _use(IdOF())
    job_id = await _enqueue_due(aid, {"fan_id": fid, "text": "here u go",
                                      "send_purpose": "manual"})

    res = await run_once(aid, "scheduled_send")
    assert res["status"] == "ok" and res["message_id"], res
    assert fake.sent == [(fid, "here u go")], fake.sent
    assert fake.probed == [], fake.probed

    msgs, fan, skip, job = await _snapshot(aid, fid, job_id)
    assert len(msgs) == 1 and msgs[0].direction == "out", msgs
    assert fan.automation_paused_until is not None, "cooldown set on an id'd send"
    assert fan.automation_paused_until < datetime.utcnow() + timedelta(days=1), \
        fan.automation_paused_until   # a short rest, not a quarantine week
    assert skip is None and job.status == "done", (skip, job.status)


_harness.run(
    case_no_id_send_returns_sent_no_id,
    case_id_send_still_sets_cooldown,
)
