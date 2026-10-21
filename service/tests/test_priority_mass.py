#!/usr/bin/env python3
"""Priority mass message (automations/priority_mass + priority_mass_api) sends
ONE direct message per fan of an audience frozen before the first send: read
off OF's rosters (fail closed), minus every exclusion, at most 5,000 fans; job
legs of at most `_LEG` paced, gated sends, chained until done; a claim left by a
crash is never resent, a sent fan never again; cancel stops it, resume restarts
a dead chain. Mocked OnlyFans only (FakeOF); nothing reaches the network.

Run: ./venv/bin/python service/tests/test_priority_mass.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import automation_executor as executor  # noqa: E402
import automations.priority_mass as pm  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Blacklist, Fan, List as ListModel, ListMember, Message,
    PriorityMassRecipient, PriorityMassRun, ScheduledJob, SensitiveWord, SkipList,
    VaultSend,
)
from priority_mass_api import sensitive_hits  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_MIGRATIONS = _REPO / "service" / "db" / "migrations"
IDS = fx.seed_two_agencies()
CREATOR_A = IDS["creator_a"]
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
ROUTE = "/admin/priority-mass/runs"

_REAL_MAKE_CLIENT = executor._make_client
_REAL_PACED = executor.of_write_paced
_REAL_MAX = pm.MAX_RECIPIENTS


class RateLimited(Exception):
    pass


class FakeOF:
    """`fans` / `following` / `lists` are the rosters OF returns; every send is recorded."""
    def __init__(self, fans=(), *, following=(), lists=None, with_id=True):
        self.fans = [{"id": f} for f in fans]
        self.following_rows = [{"id": f} for f in following]
        self.lists = {int(k): [{"id": f} for f in v] for k, v in (lists or {}).items()}
        self.with_id = with_id
        self.sent: list[tuple[int, str, dict]] = []
        self.fail: dict[int, Exception] = {}
        self.truncate = False
        self._next_id = 9_200_000_000_000

    def _page(self, rows, limit, offset):
        if self.truncate:       # a roster that never ends: the crawl hits its backstop
            return {"list": [{"id": 10_000_000 + offset + i} for i in range(limit)], "hasMore": True}
        return {"list": rows[offset:offset + limit], "hasMore": offset + limit < len(rows)}

    def subscribers(self, *, type="active", limit=10, offset=0, **kw):
        return self._page(self.fans, limit, offset)

    def following(self, *, type="active", limit=10, offset=0, **kw):
        return self._page(self.following_rows, limit, offset)

    def list_users_in(self, list_id, *, limit=10, offset=0, **kw):
        return self.lists.get(int(list_id), [])[offset:offset + limit]

    def send_message(self, chat_id, text, **kw):
        if int(chat_id) in self.fail:
            raise self.fail.pop(int(chat_id))
        self._next_id += 1
        self.sent.append((int(chat_id), text, kw))
        if not self.with_id:
            return {"success": True}
        return {"id": self._next_id, "text": f"<p>{text}</p>", "createdAt": "2026-10-20T12:00:00+00:00"}

    def get_user(self, fan_id):
        return {"id": int(fan_id), "subscribedOn": "2026-01-01"}


PACED: list[dict] = []


async def _unpaced(account_id, fn, **kw):
    PACED.append({k: kw.get(k) for k in ("send_purpose", "tries")})
    return await _REAL_PACED(account_id, fn, **{**kw, "min_gap_s": 0.0, "pause_s": 0.0})


def _use_fake(fake: FakeOF) -> FakeOF:
    executor._make_client = lambda account_id: fake
    executor.of_write_paced = _unpaced
    PACED.clear()
    return fake


def _sandboxed(go) -> None:
    try:
        asyncio.run(go())
    finally:
        executor._make_client = _REAL_MAKE_CLIENT
        executor.of_write_paced = _REAL_PACED
        pm.MAX_RECIPIENTS = _REAL_MAX


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _new_run(aid: str, *, lists=("fans",), excluded=(), text="hey {name}",
                   price_cents=0, media=(), status=pm.RESOLVING) -> int:
    async with get_session() as s:
        row = PriorityMassRun(
            account_id=aid, status=status, text=text, media_json=json.dumps(list(media)),
            previews_json="[]", price_cents=price_cents, locked_text=False,
            audience_json=json.dumps({"user_lists": list(lists),
                                      "excluded_user_lists": list(excluded)}))
        s.add(row)
        await s.flush()
        return int(row.id)


async def _leg(aid: str, rid: int) -> dict:
    return await pm.run(aid, {"run_id": rid}, run_id=0)


async def _drain(aid: str, *, max_legs: int = 50) -> list[dict]:
    """Run queued legs through the executor until none is due."""
    out = []
    for _ in range(max_legs):
        async with get_session() as s:
            await s.execute(update(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.kind == pm.KIND,
                ScheduledJob.status == "pending").values(run_at=datetime.utcnow()))
        res = await executor.run_once(aid, pm.KIND)
        if res.get("reason") == "no_job":
            return out
        out.append(res)
    raise AssertionError(f"chain did not end: {out[-3:]}")


async def _recipients(rid: int) -> dict[int, tuple[str, str | None]]:
    async with get_session() as s:
        return {int(r.fan_id): (r.status, r.reason) for r in (await s.execute(
            select(PriorityMassRecipient).where(PriorityMassRecipient.run_id == rid))).scalars()}


async def _run_row(rid: int) -> PriorityMassRun:
    async with get_session() as s:
        row = await s.get(PriorityMassRun, rid)
        s.expunge(row)
        return row


async def _queued_legs(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == pm.KIND,
            ScheduledJob.status == "pending"))).scalars())


# ── engine ────────────────────────────────────────────────────────────

def case_the_audience_is_frozen_before_any_send_minus_every_exclusion():
    async def go():
        aid = "pm_freeze"
        await _seed_account(aid)
        b = 7_000_000       # the blacklist is global: ids no other case uses
        fake = _use_fake(FakeOF(fans=range(b + 1, b + 11), following=[b + 11, b + 12],
                                lists={77: [b + 3]}))
        now = datetime.utcnow()
        async with get_session() as s:
            s.add(SkipList(account_id=aid, fan_id=b + 1, reason="manual_restrict"))
            s.add(Blacklist(fan_id=b + 2))
            s.add(Message(account_id=aid, fan_id=b + 4, message_id=1, direction="in",
                          body="hi", created_at=now - timedelta(minutes=30)))
            s.add(Message(account_id=aid, fan_id=b + 5, message_id=2, direction="out",
                          body="yo", created_at=now - timedelta(hours=2)))
            lst = ListModel(account_id=aid, name="MASSdmEXCLUDE", kind="exclude")
            s.add(lst)
            await s.flush()
            s.add(ListMember(list_id=lst.id, fan_id=b + 6))
        rid = await _new_run(aid, lists=("fans", "following"), excluded=(77,))
        res = await _leg(aid, rid)
        assert res["resolved"] == 11 and res["excluded"] == 5 and res["claimed"] == 6, res
        run = await _run_row(rid)
        assert run.status == pm.RUNNING and run.capped_count == 0, run.status
        rows = await _recipients(rid)
        # +1 skip-listed, +2 blacklisted, +3 on the excluded list, +4 wrote to us,
        # +5 heard from us, +6 opted out of mass DMs.
        want = [b + i for i in range(7, 13)]
        assert sorted(rows) == want, rows
        # The first leg also sent to the frozen fans, at most `_LEG` of them.
        assert sorted(f for f, _, _ in fake.sent) == want, fake.sent
        assert all(p == {"send_purpose": "gated", "tries": 1} for p in PACED), PACED
    _sandboxed(go)


def case_an_unreadable_audience_stops_the_run_and_sends_nothing():
    async def go():
        aid = "pm_unread"
        await _seed_account(aid)
        fake = _use_fake(FakeOF(fans=range(1, 4)))
        rid = await _new_run(aid, lists=("tagged",))       # a list we cannot read
        res = await _leg(aid, rid)
        assert res.get("reason") == "audience_unresolved", res
        fake.truncate = True
        rid2 = await _new_run(aid)
        res = await _leg(aid, rid2)
        assert res.get("reason") == "audience_unresolved", res
        assert fake.sent == [] and await _recipients(rid) == {} and await _recipients(rid2) == {}
        assert (await _run_row(rid)).status == pm.ERROR and (await _run_row(rid2)).status == pm.ERROR
    _sandboxed(go)


def case_legs_chain_until_every_fan_has_one_message_and_the_run_is_done():
    async def go():
        aid = "pm_chain"
        await _seed_account(aid)
        fans = list(range(101, 126))                     # 25 fans = 3 legs of 10
        fake = _use_fake(FakeOF(fans=fans))
        async with get_session() as s:
            s.add(Fan(account_id=aid, fan_id=101, real_name="Rob Smith", is_name_real=True))
        rid = await _new_run(aid)
        await pm.ensure_leg(aid, rid)
        legs = await _drain(aid)
        assert [r.get("sent") for r in legs[:3]] == [10, 10, 5], legs
        assert sorted(f for f, _, _ in fake.sent) == fans, fake.sent
        assert fake.sent[0][1] == "hey Rob", fake.sent[0]
        assert (await _run_row(rid)).status == pm.DONE
        assert set(await _recipients(rid)) == set(fans)
        assert {s for s, _ in (await _recipients(rid)).values()} == {pm.SENT}
        async with get_session() as s:
            rows = (await s.execute(select(Message).where(
                Message.account_id == aid, Message.automation_kind == pm.KIND))).scalars().all()
        assert sorted(r.fan_id for r in rows) == fans, len(rows)
        # Sent fans rest, a fan with no local row too (he gets one), and
        # nothing is ever sent twice.
        async with get_session() as s:
            fan = await s.get(Fan, (aid, 101))
            rowless = await s.get(Fan, (aid, 102))
        assert fan.automation_paused_until > datetime.utcnow(), fan.automation_paused_until
        assert rowless is not None and rowless.automation_paused_until > datetime.utcnow(), rowless
        await pm.ensure_leg(aid, rid)
        await _drain(aid)
        assert len(fake.sent) == 25, len(fake.sent)
    _sandboxed(go)


def case_a_crash_left_claim_is_unknown_and_never_resent_a_sent_fan_never_again():
    async def go():
        aid = "pm_resume"
        await _seed_account(aid)
        fake = _use_fake(FakeOF(fans=[1, 2, 3, 4]))
        rid = await _new_run(aid, status=pm.RUNNING)
        async with get_session() as s:
            await s.execute(PriorityMassRecipient.__table__.insert(), [
                {"run_id": rid, "fan_id": 1, "status": pm.SENT, "message_id": 5},
                {"run_id": rid, "fan_id": 2, "status": pm.CLAIMED, "message_id": None},
                {"run_id": rid, "fan_id": 3, "status": pm.PENDING, "message_id": None},
                {"run_id": rid, "fan_id": 4, "status": pm.PENDING, "message_id": None}])
        res = await _leg(aid, rid)
        assert res["interrupted"] == 1 and res["sent"] == 2, res
        assert [f for f, _, _ in fake.sent] == [3, 4], fake.sent
        rows = await _recipients(rid)
        assert rows[1][0] == pm.SENT and rows[2] == (pm.UNKNOWN, "interrupted"), rows
    _sandboxed(go)


def case_a_fan_who_writes_in_mid_leg_is_skipped_at_his_claim():
    async def go():
        aid = "pm_midleg"
        await _seed_account(aid)
        fake2 = _use_fake(FakeOF())
        rid2 = await _new_run(aid, status=pm.RUNNING)
        async with get_session() as s:
            await s.execute(PriorityMassRecipient.__table__.insert(), [
                {"run_id": rid2, "fan_id": f, "status": pm.PENDING, "message_id": None}
                for f in (11, 12)])
        real_cooldown = executor.start_fan_cooldown

        async def cooldown_then_fan_12_writes(account_id, fan_id, **kw):
            out = await real_cooldown(account_id, fan_id, **kw)
            if fan_id == 11:            # after the leg began, before 12's claim
                async with get_session() as s:
                    s.add(Message(account_id=aid, fan_id=12, message_id=77, direction="in",
                                  body="hey", created_at=datetime.utcnow()))
            return out
        executor.start_fan_cooldown = cooldown_then_fan_12_writes
        try:
            res = await _leg(aid, rid2)
        finally:
            executor.start_fan_cooldown = real_cooldown
        assert [f for f, _, _ in fake2.sent] == [11], fake2.sent
        assert (await _recipients(rid2))[12] == (pm.SKIPPED, "recently_contacted"), res
    _sandboxed(go)


def case_a_timeout_may_have_sent_so_the_fan_is_unknown_a_refusal_is_failed():
    async def go():
        aid = "pm_transport"
        await _seed_account(aid)
        fake = _use_fake(FakeOF(fans=[1, 2]))

        class Resp:
            status_code = 403

            def json(self):
                return {}

        refused = Exception("403 forbidden")
        refused.response = Resp()
        fake.fail[1] = TimeoutError("read timed out")
        fake.fail[2] = refused
        rid = await _new_run(aid)
        res = await _leg(aid, rid)
        rows = await _recipients(rid)
        assert rows[1] == (pm.UNKNOWN, "transport") and rows[2] == (pm.FAILED, "error"), rows
        assert res["unknown"] == 1 and res["failed"] == 1, res
        await _drain(aid)
        assert fake.sent == [], fake.sent       # neither is ever retried
    _sandboxed(go)


def case_a_slow_leg_yields_its_slot_and_chains():
    async def go():
        aid = "pm_budget"
        await _seed_account(aid)
        fake = _use_fake(FakeOF(fans=[1, 2, 3]))
        real = pm._LEG_BUDGET_S
        pm._LEG_BUDGET_S = -1           # over budget at once: the leg sends nothing
        try:
            rid = await _new_run(aid)
            res = await _leg(aid, rid)
        finally:
            pm._LEG_BUDGET_S = real
        assert res["sent"] == 0 and fake.sent == [], res
        assert len(await _queued_legs(aid)) == 1
        await _drain(aid)
        assert sorted(f for f, _, _ in fake.sent) == [1, 2, 3], fake.sent
    _sandboxed(go)


def case_the_cap_keeps_the_first_fans_and_counts_the_rest():
    async def go():
        aid = "pm_cap"
        await _seed_account(aid)
        _use_fake(FakeOF(fans=range(1, 9)))
        pm.MAX_RECIPIENTS = 3
        rid = await _new_run(aid)
        res = await _leg(aid, rid)
        assert res["claimed"] == 3 and res["capped"] == 5, res
        assert sorted(await _recipients(rid)) == [1, 2, 3]
        assert (await _run_row(rid)).capped_count == 5
    _sandboxed(go)


def case_send_outcomes_unreachable_no_id_rate_limit_and_rejected_media():
    async def go():
        aid = "pm_outcomes"
        await _seed_account(aid)
        fake = _use_fake(FakeOF(fans=[1, 2, 3]))
        fake.fail[1] = Exception("Cannot send message to this user")
        fake.fail[2] = Exception('400 {"message":"Please allow 10 seconds"}')
        rid = await _new_run(aid)
        res = await _leg(aid, rid)
        rows = await _recipients(rid)
        # 1 is unreachable (skip-listed); 2 hit the rate limit: back to pending,
        # the leg stops and the next one waits a minute.
        assert rows[1] == (pm.SKIPPED, "unreachable") and rows[2][0] == pm.PENDING, rows
        assert rows[3][0] == pm.PENDING and fake.sent == [], (rows, fake.sent)
        legs = await _queued_legs(aid)
        assert len(legs) == 1 and legs[0].run_at > datetime.utcnow() + timedelta(seconds=30), legs
        res = await _leg(aid, rid)
        assert res["sent"] == 2, res

        no_id = _use_fake(FakeOF(fans=[5], with_id=False))
        rid2 = await _new_run(aid)
        await _leg(aid, rid2)
        assert (await _recipients(rid2))[5] == (pm.FAILED, "no_id"), await _recipients(rid2)
        assert len(no_id.sent) == 1

        class Resp:
            status_code = 400

            def json(self):
                return {"errors": {"mediaFiles": ["bad"]}}

        bad = Exception("400 media")
        bad.response = Resp()
        media = _use_fake(FakeOF(fans=[6, 7]))
        media.fail[6] = bad
        rid3 = await _new_run(aid, media=(900,))
        res = await _leg(aid, rid3)
        assert res.get("reason") == "media_rejected" and media.sent == [], res
        run = await _run_row(rid3)
        assert run.status == pm.ERROR and "media" in run.last_error, run.last_error
    _sandboxed(go)


def case_priced_runs_skip_fans_who_own_the_media_and_send_the_price():
    async def go():
        aid = "pm_priced"
        await _seed_account(aid)
        fake = _use_fake(FakeOF(fans=[1, 2]))
        async with get_session() as s:
            s.add(VaultSend(account_id=aid, fan_id=1, media_id=900, was_purchased=True))
        rid = await _new_run(aid, price_cents=1500, media=(900,))
        res = await _leg(aid, rid)
        assert res["excluded"] == 1 and [f for f, _, _ in fake.sent] == [2], (res, fake.sent)
        kw = fake.sent[0][2]
        assert kw["price"] == 15 and kw["media_files"] == [900], kw
    _sandboxed(go)


def case_busy_fans_wait_quarantined_fans_are_skipped():
    async def go():
        aid = "pm_busy"
        await _seed_account(aid)
        fake = _use_fake(FakeOF(fans=[1, 2, 3]))
        now = datetime.utcnow()
        async with get_session() as s:
            s.add(Fan(account_id=aid, fan_id=1, automation_paused_until=now + timedelta(minutes=2)))
            s.add(Fan(account_id=aid, fan_id=2, automation_paused_until=now + timedelta(days=7)))
        await executor.acquire_fan_lease(aid, 3, "autoreply")
        rid = await _new_run(aid)
        res = await _leg(aid, rid)
        rows = await _recipients(rid)
        assert rows[1][0] == pm.PENDING and rows[2] == (pm.SKIPPED, "paused"), rows
        assert rows[3][0] == pm.PENDING and fake.sent == [], (rows, fake.sent)
        assert res["deferred"] == 2, res
        legs = await _queued_legs(aid)
        assert len(legs) == 1, legs
    _sandboxed(go)


def case_a_cancelled_run_sends_nothing_more():
    async def go():
        aid = "pm_cancel"
        await _seed_account(aid)
        fake = _use_fake(FakeOF(fans=[1, 2]))
        rid = await _new_run(aid)
        async with get_session() as s:
            await s.execute(update(PriorityMassRun).where(PriorityMassRun.id == rid)
                            .values(status=pm.CANCELLED))
        res = await _leg(aid, rid)
        assert res.get("reason") == pm.CANCELLED and fake.sent == [], res
        assert await _recipients(rid) == {}
    _sandboxed(go)


# ── API ───────────────────────────────────────────────────────────────

def _body(**kw) -> dict:
    return {"account_id": CREATOR_A, "text": "hey you", "user_lists": ["fans"], **kw}


def _clear_runs() -> None:
    async def go():
        async with get_session() as s:
            await s.execute(sa.delete(PriorityMassRecipient))
            await s.execute(sa.delete(PriorityMassRun))
            await s.execute(sa.delete(ScheduledJob).where(ScheduledJob.kind == pm.KIND))
    asyncio.run(go())


def case_the_create_route_validates_refuses_sensitive_words_and_repeats():
    _clear_runs()
    for bad in ({"user_lists": []}, {"user_lists": ["tagged"]}, {"text": "", "media_files": []},
                {"price": 2, "media_files": [5]}, {"price": 10}, {"previews": [9], "media_files": [5]},
                {"excluded_user_lists": ["fans"]}):
        r = OWNER_A.post(ROUTE, json=_body(**bad))
        assert r.status_code == 422, (bad, r.status_code, r.text)
    asyncio.run(_add_sensitive(IDS["agency_a_owner"], "Snap chat"))
    r = OWNER_A.post(ROUTE, json=_body(text="add me on snap   CHAT"))
    assert r.status_code == 422 and "check the contents" in r.text, r.text
    assert OWNER_B.post(ROUTE, json=_body()).status_code == 403
    r = OWNER_A.post(ROUTE, json=_body(media_files=[5], price=9.5, previews=[5]))
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == pm.RESOLVING and run["price"] == 9.5 and not run["stalled"], run
    assert OWNER_A.post(ROUTE, json=_body(media_files=[5], price=9.5)).status_code == 409
    legs = asyncio.run(_queued_legs(CREATOR_A))
    assert [json.loads(j.payload_json) for j in legs] == [{"run_id": run["id"]}], legs


async def _add_sensitive(agency: str, word: str) -> None:
    async with get_session() as s:
        s.add(SensitiveWord(agency_user_id=agency, word=word, word_key=word.lower()))


def case_the_list_counts_recipients_and_cancel_and_resume_work():
    _clear_runs()
    fake = FakeOF(fans=range(1, 31))

    async def go():
        _use_fake(fake)
        run = OWNER_A.post(ROUTE, json=_body(text="list me")).json()
        await executor.run_once(CREATOR_A, pm.KIND)       # freeze + first leg
        got = OWNER_A.get(ROUTE, params={"account_id": CREATOR_A}).json()
        row = got["runs"][0]
        assert row["id"] == run["id"] and row["total"] == 30, row
        assert row["counts"] == {"sent": 10, "pending": 20}, row["counts"]
        assert got["max_recipients"] == 5000 and got["hourly_rate"] == 300, got
        # The chain dies (its job is lost): stalled, and Resume requeues it.
        async with get_session() as s:
            await s.execute(sa.delete(ScheduledJob).where(ScheduledJob.kind == pm.KIND))
        assert OWNER_A.get(ROUTE, params={"account_id": CREATOR_A}).json()["runs"][0]["stalled"]
        assert OWNER_B.post(f"{ROUTE}/{run['id']}/resume").status_code == 403
        r = OWNER_A.post(f"{ROUTE}/{run['id']}/resume")
        assert r.status_code == 200 and not r.json()["stalled"], r.text
        r = OWNER_A.post(f"{ROUTE}/{run['id']}/cancel")
        assert r.status_code == 200 and r.json()["status"] == pm.CANCELLED, r.text
        assert r.json()["counts"] == {"sent": 10, "skipped": 20}, r.json()
        assert OWNER_A.post(f"{ROUTE}/{run['id']}/cancel").status_code == 409
        await _drain(CREATOR_A)
        assert len(fake.sent) == 10, len(fake.sent)
        assert OWNER_B.get(ROUTE, params={"account_id": CREATOR_A}).status_code == 403
    _sandboxed(go)


def case_the_sensitive_matcher_matches_between_boundaries_only():
    assert sensitive_hits("you are in my class", ["ass"]) == []
    assert sensitive_hits("nice ASS!", ["ass"]) == ["ass"]
    assert sensitive_hits("text me on Tele\tgram", ["tele gram"]) == ["tele gram"]
    assert sensitive_hits("cashapp_me", ["cashapp"]) == ["cashapp"]


# ── the migration ─────────────────────────────────────────────────────

def _load_migration():
    found = sorted((_MIGRATIONS / "versions").glob("*_priority_mass.py"))
    assert len(found) == 1, found
    spec = importlib.util.spec_from_file_location(found[0].stem, found[0])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def case_the_migration_is_on_the_single_head_and_round_trips():
    mod = _load_migration()
    env = {**os.environ, "PYTHONPATH": str(_REPO)}
    r = subprocess.run([sys.executable, "-m", "alembic", "-c", str(_MIGRATIONS / "alembic.ini"), "heads"],
                       cwd=_REPO, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    heads = [line for line in r.stdout.splitlines() if line.strip()]
    assert len(heads) == 1 and heads[0].endswith("(head)"), r.stdout
    h = subprocess.run([sys.executable, "-m", "alembic", "-c", str(_MIGRATIONS / "alembic.ini"), "history"],
                       cwd=_REPO, env=env, capture_output=True, text=True, timeout=300)
    assert h.returncode == 0 and f"-> {mod.revision}" in h.stdout, h.stdout[-2000:]

    path = Path(tempfile.mkdtemp(prefix="priority_mass_migration_")) / "mig.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE accounts (id VARCHAR PRIMARY KEY)")
    conn.execute("CREATE TABLE employees (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    engine = sa.create_engine(f"sqlite:///{path}")

    def tables() -> set[str]:
        return set(sa.inspect(engine).get_table_names())

    def step(fn) -> None:
        with engine.begin() as c:
            with Operations.context(MigrationContext.configure(c)):
                fn()
    try:
        step(mod.upgrade)
        assert {"priority_mass_runs", "priority_mass_recipients"} <= tables(), tables()
        step(mod.upgrade)       # idempotent
        step(mod.downgrade)
        assert not {"priority_mass_runs", "priority_mass_recipients"} & tables(), tables()
        step(mod.upgrade)
        assert {"priority_mass_runs", "priority_mass_recipients"} <= tables(), tables()
    finally:
        engine.dispose()


_harness.run()
