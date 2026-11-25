#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
from automations import scheduled_send  # noqa: E402,F401 — registers the kind
from automation_executor import enqueue_job, run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Message, ScheduledJob, SkipList  # noqa: E402


class NoIdOF:

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



async def case_no_id_send_returns_sent_no_id():
    aid, fid = "acc_ss_noid1", 4101
    await _seed(aid, fid)
    fake = _use(NoIdOF())
    job_id = await _enqueue_due(aid, {"fan_id": fid, "text": "later babe",
                                      "send_purpose": "manual"})

    res = await run_once(aid, "scheduled_send")
    assert res["status"] == "sent_no_id", res
    assert res["message_id"] is None and res["fan_id"] == fid, res
    assert fake.sent == [(fid, "later babe")], fake.sent
    # Pinned gap: scheduled_send never runs quarantine_if_undeliverable on a no-id answer.
    assert fake.probed == [], f"get_user probed: {fake.probed}"

    msgs, fan, skip, job = await _snapshot(aid, fid, job_id)
    assert msgs == [], "no outbound row without an OF id"
    assert fan.subscription_status == "active", fan.subscription_status
    assert fan.automation_paused_until is None, fan.automation_paused_until
    assert skip is None, f"skip_list row written: {skip.reason}"
    assert job is not None and job.status == "done", job and job.status

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
        fan.automation_paused_until
    assert skip is None and job.status == "done", (skip, job.status)


_harness.run(
    case_no_id_send_returns_sent_no_id,
    case_id_send_still_sets_cooldown,
)
