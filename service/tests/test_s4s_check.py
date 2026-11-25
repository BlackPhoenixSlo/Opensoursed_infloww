#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402 — the shared _make_client seam
import automations.s4s_check as s4s_check  # noqa: E402 — module under test (registers)
from db.engine import get_session  # noqa: E402
from db.models import Account, Action, Post, S4SRequest, S4SSlot  # noqa: E402

POSTER, PARTNER = "5550001", "5550002"


def case_tamper_reason_table():
    tr = s4s_check.tamper_reason
    then = {"text": "<p>Hi <b>there</b></p>"}
    rows = [
        (None, then, "Hi there", 1, "post_deleted"),
        ({"isDeleted": True, "isArchived": True}, then, "", 1, "post_deleted"),
        ({"isDeleted": 1, "text": "Hi there"}, then, "", 1, "post_deleted"),
        ({"isArchived": True, "text": "other"}, then, "", 1, "post_archived"),
        ({"isDeleted": False, "isArchived": False, "text": "Hi there", "media": [{"id": 1}]},
         then, "", 1, None),
        ({"text": "Hi there edited", "media": [{"id": 1}]}, then, "", 1, "post_edited"),
        ({"text": "Hi There", "media": [{"id": 1}]}, then, "", 1, "post_edited"),
        ({"text": "  Hi\n\nthere ", "media": [{"id": 1}]}, then, "", 1, None),
        ({"text": "<i>Hi</i> there", "media": [{"id": 1}]}, then, "", 1, None),
        ({"text": "Tom & Jerry"}, {"text": "Tom &amp; Jerry"}, "", 0, None),
        ({"rawText": "Hi there", "text": "<p>else</p>"}, then, "", 0, None),
        ({"rawText": "Hi there"}, {"rawText": "Hi there", "text": "x"}, "", 0, None),
        ({"text": "Hi there", "media": [{"id": 1}]}, then, "", 2, "post_edited"),
        ({"text": "Hi there", "media": []}, then, "", 1, "post_edited"),
        ({"text": "Hi there", "media": [{"id": 1}, {"id": 2}]}, then, "", 1, "post_edited"),
        ({"text": "Hi there", "media": None}, then, "", 0, None),
        ({"text": "Hi there", "media": None}, then, "", 1, "post_edited"),
        ({"text": "Hi there"}, then, "", 5, None),
        ({"text": "cap @x #advertisement"}, {"id": 9}, "cap @x\n#advertisement", 0, None),
        ({"text": "cap @x"}, {}, "cap @x\n#advertisement", 0, "post_edited"),
        ({"text": ""}, {}, "", 0, None),
        ({}, then, "", 0, "post_edited"),
    ]
    for now, th, sent_text, sent_media, want in rows:
        got = tr(now, th, sent_text, sent_media)
        assert got == want, (now, th, sent_text, sent_media, got, want)
    assert s4s_check.DELETED == "post_deleted" and s4s_check.ARCHIVED == "post_archived"
    assert s4s_check.EDITED == "post_edited"


class FakeOF:

    def __init__(self, now):
        self.now = now
        self.calls: list[tuple] = []

    def get_post(self, post_id):
        self.calls.append(("get_post", int(post_id)))
        return self.now

    def __getattr__(self, name):
        def _rec(*a, **k):
            self.calls.append((name, a, k))
            return {}
        return _rec


def _use(fake: FakeOF) -> FakeOF:
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed_posted_slot(of_post_id: int) -> int:
    async with get_session() as s:
        for aid in (POSTER, PARTNER):
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid, nickname=f"acct{aid}"))
        await s.flush()
        req = S4SRequest(from_account_id=PARTNER, to_account_id=POSTER,
                         slot_at=datetime.utcnow() - timedelta(hours=23),
                         from_caption="partner caption", to_caption="poster caption",
                         from_projection_json="{}", to_projection_json="{}",
                         from_media_json=json.dumps([{"id": 11, "media_type": "photo"},
                                                     {"id": 12, "media_type": "photo"}]),
                         to_media_json=None, status="accepted")
        s.add(req)
        await s.flush()
        post = Post(account_id=POSTER, of_post_id=of_post_id, status="posted",
                    text="partner caption @p\n#advertisement",
                    raw_json=json.dumps({"id": of_post_id,
                                         "text": "partner caption @p\n#advertisement",
                                         "media": [{"id": 1}]}))
        s.add(post)
        await s.flush()
        slot = S4SSlot(request_id=req.id, poster_account_id=POSTER,
                       partner_account_id=PARTNER, text="partner caption @p",
                       slot_at=req.slot_at, status="posted", post_id=post.id,
                       of_post_id=of_post_id, posted_at=req.slot_at)
        s.add(slot)
        await s.flush()
        return slot.id


async def _slot(slot_id: int) -> tuple:
    async with get_session() as s:
        row = await s.get(S4SSlot, slot_id)
        return row.status, row.reason


async def _tamper_audits(slot_id: int) -> list[Action]:
    async with get_session() as s:
        return list((await s.execute(select(Action).where(
            Action.action == "s4s.slot_tamper",
            Action.target_id == str(slot_id)))).scalars().all())


async def case_run_reads_once_and_fails_only_a_tampered_slot():
    slot_id = await _seed_posted_slot(81001)
    text = "partner caption @p #advertisement"

    fake = _use(FakeOF({"id": 81001, "text": text, "media": [{"id": 1}, {"id": 2}]}))
    res = await s4s_check.run(POSTER, {"slot_id": slot_id}, run_id=0)
    assert res == {"status": "ok", "slot_id": slot_id, "tamper": None}, res
    assert fake.calls == [("get_post", 81001)], fake.calls
    assert await _slot(slot_id) == ("posted", None)
    assert await _tamper_audits(slot_id) == []

    fake = _use(FakeOF({"id": 81001, "text": text, "media": [{"id": 1}]}))
    res = await s4s_check.run(POSTER, {"slot_id": slot_id}, run_id=0)
    assert res == {"status": "ok", "slot_id": slot_id, "tamper": "post_edited",
                   "moved": True}, res
    assert fake.calls == [("get_post", 81001)], fake.calls
    assert await _slot(slot_id) == ("failed", "post_edited")
    (audit,) = await _tamper_audits(slot_id)
    assert audit.account_id == POSTER, audit.account_id
    assert json.loads(audit.payload_json)["reason"] == "post_edited", audit.payload_json

    fake = _use(FakeOF(None))
    res = await s4s_check.run(POSTER, {"slot_id": slot_id}, run_id=0)
    assert res == {"status": "skipped", "reason": "failed", "slot_id": slot_id}, res
    assert fake.calls == [], fake.calls
    assert len(await _tamper_audits(slot_id)) == 1


async def case_skip_reason_table():
    slot_id = await _seed_posted_slot(82001)
    rows = [
        (POSTER, {}, {"status": "skipped", "reason": "no_slot_id"}),
        (PARTNER, {"slot_id": slot_id},
         {"status": "skipped", "reason": "not_the_poster", "slot_id": slot_id}),
    ]
    for aid, payload, want in rows:
        fake = _use(FakeOF(None))
        res = await s4s_check.run(aid, payload, run_id=0)
        assert res == want, (aid, payload, res, want)
        assert fake.calls == [], (aid, payload, fake.calls)
    assert await _slot(slot_id) == ("posted", None), "a skip never moves the slot"


_harness.run(
    case_tamper_reason_table,
    case_skip_reason_table,
    case_run_reads_once_and_fails_only_a_tampered_slot,
)
