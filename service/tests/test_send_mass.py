#!/usr/bin/env python3
"""
A10 send_mass_message — automation tests.

The acceptance bar (PROMPTS ▶ A10): a mass send creates a `mass_runs` row and a
per-recipient `messages` row, reusing the T-MASS optimistic persistence. The
automation reads funnels / lists / fans, fires `of_client.send_mass_message`
(POST /messages/queue — no DOM), and is driven through the executor's `run_once`
seam exactly like a real scheduled job.

  case_run:
      enqueue a job → run_once → a mass_runs row (linked to the funnel) + one
      optimistic `messages` row per known recipient (explicit fans + DB-list
      members, minus exclusions); automation_runs status=ok.
  case_echoed_real_rows:
      when OF echoes per-fan message ids, the REAL row is written (real OF id,
      not the synthetic placeholder) and no optimistic placeholder lingers.
  case_skips_empty:
      no text / no audience → a skipped run, no mass_runs row.
  case_list_broadcast_syncs_exclude_list:
      a userLists broadcast with the DEFAULT-ON guard mirrors the exclude ids
      into the Auto_Exclude OF list (stale members removed) and attaches it via
      excluded_user_lists — OF has NO per-user exclusion field on broadcasts
      (excludedUsers is silently dropped; verified live 2026-06-12).
  case_exclude_sync_failure_fails_closed:
      the Auto_Exclude sync failing must SKIP the broadcast — blasting
      without the guard is the over-send bug itself.

Run: ./venv/bin/python service/tests/test_send_mass.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402 — shared _make_client seam
import automations.send_mass_message as a10  # noqa: E402,F401 — module under test (registers)
from attribution import mass_placeholder_message_id  # noqa: E402
from audiences import pending_send_fan_ids  # noqa: E402 — L2 #31 pending-send dedup
from automation_executor import enqueue_job, run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    AutomationRun,
    FunnelResponder,
    List,
    ListMember,
    MassMessageFunnel,
    MassRun,
    Message,
)


# ── Fakes (no network, no session files) ─────────────────────────────

class FakeClient:
    """Stand-in for OFClient. Records the broadcast body it was called with and
    returns a canned `/messages/queue` response (a queue object by default —
    no per-fan ids — so the optimistic path is exercised)."""

    def __init__(self, response: dict | None = None, user_id: str = "999"):
        self.user_id = user_id
        self.sent: list[dict] = []
        self._response = response if response is not None else {
            "id": 770001, "createdAt": "2026-06-04T10:00:00+00:00",
        }

    def send_mass_message(self, text, **kw) -> dict:
        self.sent.append({"text": text, **kw})
        return self._response


class FakeListClient(FakeClient):
    """FakeClient + the fan-list API audiences.ensure_exclude_list syncs
    through (get/create list, read/add/remove members)."""

    AUTO_LID = 555_001

    def __init__(self, **kw):
        super().__init__(**kw)
        self.lists: list[dict] = []
        self.members: dict[int, set[int]] = {}
        self.removed: list[tuple[int, int]] = []

    def get_lists(self, *, limit=20, offset=0):
        return {"list": self.lists[offset:offset + limit],
                "hasMore": offset + limit < len(self.lists)}

    def create_list(self, name):
        lst = {"id": self.AUTO_LID, "name": name}
        self.lists.append(lst)
        self.members[self.AUTO_LID] = set()
        return lst

    def list_users_in(self, list_id, *, limit=20, offset=0):
        ids = sorted(self.members.get(int(list_id), set()))
        return {"list": [{"id": i} for i in ids[offset:offset + limit]],
                "hasMore": offset + limit < len(ids)}

    def add_user_to_list(self, list_id, user_id):
        self.members.setdefault(int(list_id), set()).add(int(user_id))

    def remove_user_from_list(self, list_id, user_id):
        self.members.get(int(list_id), set()).discard(int(user_id))
        self.removed.append((int(list_id), int(user_id)))


def _use_fake(fake: FakeClient) -> None:
    """Override the shared OFClient construction seam for the current case."""
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_funnel(name: str, opening: str) -> int:
    async with get_session() as s:
        f = MassMessageFunnel(
            name=name, opening_message=opening,
            media_indices="[]", steps_json="[]",
        )
        s.add(f)
        await s.flush()
        return int(f.id)


async def _seed_list(aid: str, name: str, member_fan_ids: list[int]) -> int:
    async with get_session() as s:
        lst = List(account_id=aid, name=name, kind="regular")
        s.add(lst)
        await s.flush()
        for fid in member_fan_ids:
            s.add(ListMember(list_id=lst.id, fan_id=fid))
        return int(lst.id)


async def _seed_message(aid: str, fan_id: int, direction: str, msg_id: int) -> None:
    """A recent chat row so audiences.recent_chat_fan_ids picks the fan up."""
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan_id, message_id=msg_id,
            direction=direction, body="hi", created_at=datetime.utcnow(),
        ))


# ── case_run — mass_runs + per-recipient optimistic rows ─────────────

async def case_run():
    aid = "acc_mass1"
    await _seed_account(aid)
    funnel_id = await _seed_funnel("strokes", "How many strokes? 😈")
    # Audience: 1 explicit fan + a 2-member list, with one of those excluded.
    list_id = await _seed_list(aid, "Mass_Audience", [2002, 2003])
    fake = FakeClient()
    _use_fake(fake)

    job_id = await enqueue_job(aid, "send_mass_message", payload={
        "funnel_id": funnel_id,
        "included_users": [2001],
        "list_ids": [list_id],
        "excluded_users": [2003],
        "price": 0,
    })
    res = await run_once(aid, "send_mass_message")

    assert res["status"] == "ok", res
    assert res["job_id"] == job_id, res
    # 2001 + 2002 (2003 excluded) = 2 known recipients, all optimistic.
    assert res["recipients"] == 2, res
    assert res["optimistic_rows"] == 2, res
    assert res["echoed_rows"] == 0, res

    # The funnel text was the broadcast body, audience passed to OF.
    assert fake.sent and fake.sent[0]["text"] == "How many strokes? 😈", fake.sent
    assert sorted(fake.sent[0]["included_users"]) == [2001, 2002], fake.sent[0]

    async with get_session() as s:
        runs = (await s.execute(
            select(MassRun).where(MassRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 1, f"one mass_runs row, got {len(runs)}"
        mr = runs[0]
        assert mr.funnel_id == funnel_id, mr.funnel_id
        assert mr.status == "ok" and mr.completed_at is not None, (mr.status, mr.completed_at)
        assert mr.recipient_count == 2, mr.recipient_count

        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert len(msgs) == 2, f"one row per recipient, got {len(msgs)}"
        assert sorted(m.fan_id for m in msgs) == [2001, 2002], [m.fan_id for m in msgs]
        ph = mass_placeholder_message_id(mr.id)
        for m in msgs:
            assert m.direction == "out", m.direction
            assert m.message_id == ph, "optimistic placeholder id"
            assert m.mass_run_id == mr.id, m.mass_run_id
            assert m.temp_id == f"mass:{mr.id}:{m.fan_id}", m.temp_id
            assert "strokes" in (m.body or ""), m.body

        arun = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert len(arun) == 1 and arun[0].status == "ok", arun
        assert arun[0].kind == "send_mass_message", arun[0].kind
        stats = json.loads(arun[0].stats_json)
        assert stats["mass_run_id"] == mr.id and stats["recipients"] == 2, stats


# ── case_echoed_real_rows — OF echoes per-fan ids → real rows ─────────

async def case_echoed_real_rows():
    aid = "acc_mass2"
    await _seed_account(aid)
    # OF echoes a per-fan message id for 3001; 3002 is left to the optimistic path.
    fake = FakeClient(response={
        "createdAt": "2026-06-04T11:00:00+00:00",
        "messages": [{"userId": 3001, "id": 9988776655}],
    })
    _use_fake(fake)

    await enqueue_job(aid, "send_mass_message", payload={
        "text": "hey love",
        "included_users": [3001, 3002],
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res
    assert res["echoed_rows"] == 1, res
    assert res["optimistic_rows"] == 1, res

    async with get_session() as s:
        mr = (await s.execute(
            select(MassRun).where(MassRun.account_id == aid)
        )).scalar_one()
        ph = mass_placeholder_message_id(mr.id)

        m3001 = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == 3001)
        )).scalars().all()
        assert len(m3001) == 1, m3001
        # Real OF id, NOT the synthetic placeholder — and no lingering placeholder.
        assert m3001[0].message_id == 9988776655, m3001[0].message_id
        assert m3001[0].mass_run_id == mr.id, m3001[0].mass_run_id

        m3002 = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == 3002)
        )).scalars().all()
        assert len(m3002) == 1 and m3002[0].message_id == ph, m3002


# ── case_skips_empty — no text / no audience → skipped, no mass_runs ──

async def case_skips_empty():
    aid = "acc_mass3"
    await _seed_account(aid)
    _use_fake(FakeClient())

    # No funnel + no text → skip.
    await enqueue_job(aid, "send_mass_message", payload={"included_users": [4001]})
    res = await run_once(aid, "send_mass_message")
    assert res.get("reason") == "no_text", res

    async with get_session() as s:
        runs = (await s.execute(
            select(MassRun).where(MassRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 0, f"no mass_runs row on a skipped send, got {len(runs)}"
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert len(msgs) == 0, msgs


# ── case_audience_resolution — Mass Online parity knobs merge in ─────
# recent_chat_hours ADDS chatters to the audience; exclude_replied_hours DROPS
# fans we already replied to (outbound). Same resolution as the relay's
# /messages/queue handler, now wired into the automation send path so
# mass_premade can target "online fans we haven't replied to recently".

async def case_audience_resolution():
    aid = "acc_mass4"
    await _seed_account(aid)
    # 5001: we replied (outbound) recently — should be EXCLUDED.
    # 5002: messaged us (inbound) recently — stays (inbound guard set to 0 here
    # to test the outbound + recent-chat interaction in isolation; the default
    # 2h inbound guard is exercised by case_list_broadcast_syncs_exclude_list).
    await _seed_message(aid, 5001, "out", 60001)
    await _seed_message(aid, 5002, "in", 60002)
    fake = FakeClient()
    _use_fake(fake)

    await enqueue_job(aid, "send_mass_message", payload={
        "text": "online babe 😘",
        "included_users": [5009],          # an explicit fan, always kept
        "recent_chat_hours": 48,           # ADD 5001 + 5002 (both chatted)
        "exclude_replied_hours": 48,       # DROP 5001 (we replied outbound)
        "exclude_inbound_hours": 0,        # inbound guard OFF for this case
    })
    res = await run_once(aid, "send_mass_message")

    assert res["status"] == "ok", res
    # 5009 (explicit) + 5002 (chatted, not replied-to) = 2; 5001 dropped.
    assert res["recipients"] == 2, res
    assert sorted(fake.sent[0]["included_users"]) == [5002, 5009], fake.sent[0]
    # of_client subtracts excluded_users from userIds; the automation still
    # forwards the exclude list (5001) for that client-side drop.
    assert fake.sent[0]["excluded_users"] == [5001], fake.sent[0]


# ── case_list_broadcast_syncs_exclude_list — Auto_Exclude mirrors the guard ──
# The prod bug this pins down: a `userLists` broadcast can't drop individual
# fans via the queue body (OF has no such field), so the guard ids are synced
# into the Auto_Exclude OF list and attached server-side.

async def case_list_broadcast_syncs_exclude_list():
    aid = "acc_mass5"
    await _seed_account(aid)
    # 6001/6002 are recently active → both excluded by the DEFAULT-ON guard
    # (6h outbound / 2h inbound). These `messages` rows are what the guard reads
    # — the local fans table is NOT a list mirror, so the exclusion does NOT
    # depend on Fan rows existing.
    await _seed_message(aid, 6001, "out", 70001)   # we replied → excluded
    await _seed_message(aid, 6002, "in", 70002)    # fan replied → excluded
    fake = FakeListClient()
    # Pre-existing Auto_Exclude with a STALE member — must be removed, or 9999
    # stays excluded from every future broadcast forever.
    fake.lists.append({"id": FakeListClient.AUTO_LID, "name": "Auto_Exclude"})
    fake.members[FakeListClient.AUTO_LID] = {6001, 9999}
    _use_fake(fake)

    await enqueue_job(aid, "send_mass_message", payload={
        "text": "chatttt me",
        "user_lists": ["fans"],            # list audience → Auto_Exclude path
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res

    sent = fake.sent[0]
    assert sent["user_lists"] == ["fans"], sent
    assert FakeListClient.AUTO_LID in sent["excluded_user_lists"], sent
    # Auto_Exclude reconciled to exactly the guard set; stale 9999 removed.
    assert fake.members[FakeListClient.AUTO_LID] == {6001, 6002}, fake.members
    assert (FakeListClient.AUTO_LID, 9999) in fake.removed, fake.removed


async def case_exclude_sync_failure_fails_closed():
    aid = "acc_mass6"
    await _seed_account(aid)
    await _seed_message(aid, 7001, "out", 80001)   # forces a non-empty guard set
    fake = FakeListClient()  # no Auto_Exclude list yet

    def _boom(name):
        raise RuntimeError("OF down")
    fake.create_list = _boom
    _use_fake(fake)

    await enqueue_job(aid, "send_mass_message", payload={
        "text": "yo", "user_lists": ["fans"],
    })
    res = await run_once(aid, "send_mass_message")
    assert res.get("reason") == "exclude_list_sync_failed", res
    assert fake.sent == [], "no broadcast without its guard"

    async with get_session() as s:
        runs = (await s.execute(
            select(MassRun).where(MassRun.account_id == aid)
        )).scalars().all()
        assert runs == [], "no dangling mass_runs row on a failed sync"


async def case_exclude_sync_tolerates_one_bad_user():
    """A single OF 403 'Unable to add user to user list' (deleted/blocked/creator
    id) must NOT sink the whole exclude build — skip that id, list everyone else,
    let the broadcast go. But if EVERY add fails (systemic auth), re-raise so we
    still fail closed rather than blast an unguarded list."""
    from audiences import _sync_exclude_list_blocking

    fake = FakeListClient()
    fake.lists.append({"id": FakeListClient.AUTO_LID, "name": "Auto_Exclude"})
    fake.members[FakeListClient.AUTO_LID] = set()
    bad = 7463635
    real_add = fake.add_user_to_list
    fake.add_user_to_list = (lambda lid, uid: (_ for _ in ()).throw(
        RuntimeError("403 Unable to add user to user list"))
        if int(uid) == bad else real_add(lid, uid))

    lid = _sync_exclude_list_blocking(fake, {1, 2, bad, 3})
    assert lid == FakeListClient.AUTO_LID, lid
    # the un-addable id is dropped; everyone else still lands on the guard list
    assert fake.members[FakeListClient.AUTO_LID] == {1, 2, 3}, fake.members

    # systemic: ALL adds fail → re-raise (don't broadcast without a guard)
    fake2 = FakeListClient()
    fake2.lists.append({"id": FakeListClient.AUTO_LID, "name": "Auto_Exclude"})
    fake2.members[FakeListClient.AUTO_LID] = set()
    fake2.add_user_to_list = lambda lid, uid: (_ for _ in ()).throw(RuntimeError("OF down"))
    raised = False
    try:
        _sync_exclude_list_blocking(fake2, {1, 2, 3})
    except RuntimeError:
        raised = True
    assert raised, "all-adds-fail must re-raise (fail closed)"


async def case_exclude_sync_steady_state_straggler():
    """STEADY STATE — the guard list already holds every real fan and the only
    id left to add is a permanently un-addable straggler (deleted/blocked/the
    creator herself). 'Every add failed' is TRUE here but means nothing: the
    guard is 3-of-4 intact, so the broadcast must go.

    This is the live regression. An un-addable id never becomes a member, so
    it comes back in `to_add` on every later tick — the old
    `add_fail == len(to_add)` test therefore fired forever once the list
    settled, and fail-closed ~40% of ppv_send's broadcasts (47 of 116 attempts
    in 45 days). Coverage, not this tick's add success rate, decides."""
    from audiences import _sync_exclude_list_blocking

    fake = FakeListClient()
    fake.lists.append({"id": FakeListClient.AUTO_LID, "name": "Auto_Exclude"})
    fake.members[FakeListClient.AUTO_LID] = {1, 2, 3}   # already synced
    bad = 7463635                                       # never addable, ever
    fake.add_user_to_list = lambda lid, uid: (_ for _ in ()).throw(
        RuntimeError("403 Unable to add user to user list"))

    lid = _sync_exclude_list_blocking(fake, {1, 2, 3, bad})
    assert lid == FakeListClient.AUTO_LID, lid
    # the 3 real fans stay guarded; the straggler is simply absent
    assert fake.members[FakeListClient.AUTO_LID] == {1, 2, 3}, fake.members
    # and it must NOT have been removed as 'stale' — it's still a target id
    assert fake.removed == [], fake.removed


async def case_funnel_dedup_skips_answered():
    """R1/R2: a funnel send auto-excludes fans who already ANSWERED this funnel
    (funnel_responders ledger) and reports the skip. The prior answerer is
    dropped from the OF audience; a non-funnel send is unaffected."""
    aid = "acc_mass_ans"
    await _seed_account(aid)
    fid = await _seed_funnel("strokes_ans", "How many strokes? 😈")
    async with get_session() as s:  # 5002 already answered a prior run
        s.add(FunnelResponder(account_id=aid, funnel_id=fid, fan_id=5002))
    fake = FakeClient()
    _use_fake(fake)

    await enqueue_job(aid, "send_mass_message", payload={
        "funnel_id": fid,
        "included_users": [5001, 5002, 5003],
        "price": 0,
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res
    assert res["skipped_already_answered"] == 1, res
    assert res["skipped_already_answered_ids"] == [5002], res
    assert res["recipients"] == 2, res
    # 5002 dropped from the wire audience → OF only sees 5001, 5003.
    assert sorted(fake.sent[0]["included_users"]) == [5001, 5003], fake.sent[0]


# ── case_exclude_last_chat_hours (L2 #32) — both-direction "last chatted" guard ──
# The stock inbound guard only drops fans who messaged US; a still-warm two-way
# chat needs the outbound side too. `exclude_last_chat_hours` drops a fan we OR
# they messaged within the window, WITHOUT setting the separate replied/inbound
# guards.

async def case_exclude_last_chat_hours():
    aid = "acc_mass_lastchat"
    await _seed_account(aid)
    await _seed_message(aid, 9001, "out", 90001)   # WE messaged them → excluded
    await _seed_message(aid, 9002, "in", 90002)    # THEY messaged us → excluded
    # 9003 has no recent chat → survives.
    fake = FakeClient()
    _use_fake(fake)

    await enqueue_job(aid, "send_mass_message", payload={
        "text": "hey 😘",
        "included_users": [9001, 9002, 9003],
        "exclude_replied_hours": 0,        # isolate: stock guards OFF
        "exclude_inbound_hours": 0,
        "exclude_last_chat_hours": 48,     # BOTH directions within 48h
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res
    assert res["recipients"] == 1, res
    assert fake.sent[0]["included_users"] == [9003], fake.sent[0]
    assert sorted(fake.sent[0]["excluded_users"]) == [9001, 9002], fake.sent[0]


# ── case_pending_scheduled_send_excluded (L2 #31) — untracked delayed sends ──
# A fan already queued for a not-yet-fired ≤15-min `scheduled_send` writes NO
# `messages` row yet, so the time-window guard is blind to them. The pre-send
# dedup reads PENDING scheduled_jobs so a broadcast fired now doesn't double-hit.

async def case_pending_scheduled_send_excluded():
    aid = "acc_mass_pending"
    await _seed_account(aid)
    # A chatter's deferred 1:1 to 7001, firing in 15 min (still pending).
    await enqueue_job(aid, "scheduled_send",
                      payload={"fan_id": 7001, "text": "later babe"},
                      run_at=datetime.utcnow() + timedelta(minutes=15))
    # A queued mass broadcast to 7003 that also hasn't fired.
    await enqueue_job(aid, "send_mass_message",
                      payload={"text": "queued", "included_users": [7003]},
                      run_at=datetime.utcnow() + timedelta(minutes=15))
    assert await pending_send_fan_ids(aid) == {7001, 7003}, "both pending targets seen"

    fake = FakeClient()
    _use_fake(fake)
    # This broadcast runs NOW (run_at defaults to now) and claims its OWN job →
    # 'running', so it never excludes its own recipients (7001/7002/7003 here).
    await enqueue_job(aid, "send_mass_message", payload={
        "text": "blast now",
        "included_users": [7001, 7002, 7003],
        "exclude_replied_hours": 0,
        "exclude_inbound_hours": 0,
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res
    # 7001 (pending 1:1) + 7003 (pending mass) dropped; only 7002 is fresh.
    assert res["recipients"] == 1, res
    assert fake.sent[0]["included_users"] == [7002], fake.sent[0]


# ── plans/blast-splice — the SPLICE RECORD the send path now leaves ──────────
#
# A list-audience blast writes no per-fan `messages` row, so the only thing that
# can tell the chat engine what a man is answering is the run itself: the body, OF's
# send stamp, and WHO OF SENT IT TO — read off OF's own rosters at send time, never
# inferred from the audience we asked for. Every failure below leaves
# `recipients_json` NULL, and a NULL run is simply never spliced.

class FakeRosterClient(FakeListClient):
    """FakeListClient + the two built-in rosters `userLists` resolves to.

    `fans` pages `subscribers(type='active')` and `following` pages the new
    `subscriptions/subscribes` endpoint. The two are deliberately given DIFFERENT
    response shapes — the envelope `{list, hasMore}` and a BARE list — because the
    `following` params are only known from OF's web client and `_page_all_checked`
    has to cope with whichever OF actually returns."""

    def __init__(self, *, fans=(), following=(), envelope_following=False, **kw):
        super().__init__(**kw)
        self._fans = list(fans)
        self._following = list(following)
        self._envelope_following = envelope_following
        self.calls: list[str] = []

    def subscribers(self, *, type="active", limit=10, offset=0, **kw):
        self.calls.append(f"subscribers:{type}:{offset}")
        page = self._fans[offset:offset + limit]
        return {"list": [{"id": i} for i in page],
                "hasMore": offset + limit < len(self._fans)}

    def following(self, *, type="active", limit=10, offset=0,
                  format="infinite"):
        self.calls.append(f"following:{type}:{offset}:{format}")
        page = self._following[offset:offset + limit]
        rows = [{"id": i} for i in page]
        if self._envelope_following:
            return {"list": rows, "hasMore": offset + limit < len(self._following)}
        return rows        # bare list — page until an empty page


def case_resolve_recipients_reads_both_rosters():
    """The happy path, and the one that matters: `{fans, following}` minus every
    exclusion WE sent. The excluded ids ride in an OF LIST (OF has no per-user
    exclusion field for a list audience), so the list is CRAWLED rather than
    assumed — an Auto_Exclude / AUTOFENCE membership we cannot read is not a
    membership we may subtract."""
    from audiences import resolve_recipients_blocking
    c = FakeRosterClient(fans=[1, 2, 3, 4], following=[4, 5, 6])
    c.members[901] = {3, 6}                      # an exclude list, crawled
    c.members[902] = {7, 8}                      # a custom INCLUDED list
    got = resolve_recipients_blocking(
        c, user_lists=["fans", "following", "902"], included_users=[99],
        excluded_users=[2], excluded_user_lists=[901])
    assert got == [1, 4, 5, 7, 8, 99], got
    # Both rosters were actually paged, and `following` carried OF's params.
    assert any(x.startswith("subscribers:active") for x in c.calls), c.calls
    assert any(x.startswith("following:active:0:infinite") for x in c.calls), c.calls

    # …and the BARE-list shape pages to exhaustion just the same.
    c2 = FakeRosterClient(fans=[], following=[10, 11], envelope_following=True)
    assert resolve_recipients_blocking(c2, user_lists=["following"]) == [10, 11]


def case_resolve_recipients_fails_closed():
    """Every way this can go wrong returns None — never a partial set, because a
    half-recorded audience is indistinguishable from a complete one at read time
    and would mark real recipients as non-recipients.

    Each refusal is paired with the SAME call minus the refusing input, so the case
    cannot pass by the function being broken outright."""
    from audiences import resolve_recipients_blocking
    base = dict(user_lists=["fans"], included_users=[1])

    ok = FakeRosterClient(fans=[5])
    assert resolve_recipients_blocking(ok, **base) == [1, 5], "control"

    # 1) an "online now" audience is a moment, not a roster
    assert resolve_recipients_blocking(
        FakeRosterClient(fans=[5]), online_only=True, **base) is None
    assert resolve_recipients_blocking(
        FakeRosterClient(fans=[5]), filters={"online": 1}, **base) is None

    # 2) a list name we cannot resolve
    assert resolve_recipients_blocking(
        FakeRosterClient(fans=[5]), user_lists=["fans", "recent"],
        included_users=[1]) is None

    # 3) a crawl that raises
    class Boom(FakeRosterClient):
        def subscribers(self, **kw):
            raise RuntimeError("proxy 403")
    assert resolve_recipients_blocking(Boom(), **base) is None

    # 4) a crawl that hits the paging backstop — a short read would silently
    #    un-list everyone past the ceiling
    class Endless(FakeRosterClient):
        def subscribers(self, *, type="active", limit=10, offset=0, **kw):
            # A page of NEW ids every time, forever: the dedup guard never fires,
            # so only the 200-page backstop stops it. That is the truncation flag.
            base_id = 1000 + offset
            return {"list": [{"id": base_id + i} for i in range(limit)],
                    "hasMore": True}
    assert resolve_recipients_blocking(Endless(), **base) is None

    # 5) …and the same for an EXCLUDE list we cannot read: an exclusion we could
    #    not crawl is an exclusion we must not silently drop.
    class BadExclude(FakeRosterClient):
        def list_users_in(self, list_id, **kw):
            raise RuntimeError("list gone")
    assert resolve_recipients_blocking(
        BadExclude(fans=[5]), excluded_user_lists=[901], **base) is None


async def case_the_run_records_body_stamp_and_recipients():
    """The writer, end to end through the executor: a list broadcast leaves a
    `mass_runs` row carrying WHAT it said, WHEN OF says it went out, and WHOM OF
    resolved the lists to. Without all three the engine will not splice it."""
    aid = "acc_mass_rec"
    await _seed_account(aid)
    fake = FakeRosterClient(fans=[8101, 8102], following=[8103])
    _use_fake(fake)
    await enqueue_job(aid, "send_mass_message", payload={
        "text": "just say please",
        "user_lists": ["fans", "following"],
        "exclude_replied_hours": 0, "exclude_inbound_hours": 0,
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res
    async with get_session() as s:
        run = (await s.execute(
            select(MassRun).where(MassRun.account_id == aid)
            .order_by(MassRun.id.desc()))).scalars().first()
        assert run is not None and run.status == "ok", run
        assert run.body == "just say please", run.body
        # OF's own createdAt, not our close time.
        assert run.sent_at == datetime(2026, 6, 4, 10, 0, 0), run.sent_at
        assert json.loads(run.recipients_json) == [8101, 8102, 8103], \
            run.recipients_json
        # The mint records the list-shaped exclusions too (forensics only).
        af = json.loads(run.audience_filter)
        assert "excluded_user_lists" in af and "fence" in af, af


async def case_an_unreadable_roster_leaves_the_run_unrecorded():
    """The blast still goes out — the send is what matters and it already
    succeeded. Only the splice is lost, and it is lost SAFELY: NULL, which the
    engine reads as "never splice this run"."""
    aid = "acc_mass_rec_fail"
    await _seed_account(aid)

    class Boom(FakeRosterClient):
        def subscribers(self, **kw):
            raise RuntimeError("proxy 403")
    fake = Boom()
    _use_fake(fake)
    await enqueue_job(aid, "send_mass_message", payload={
        "text": "just say please", "user_lists": ["fans"],
        "exclude_replied_hours": 0, "exclude_inbound_hours": 0,
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res            # the SEND is unaffected
    async with get_session() as s:
        run = (await s.execute(
            select(MassRun).where(MassRun.account_id == aid)
            .order_by(MassRun.id.desc()))).scalars().first()
    assert run.body == "just say please", run.body
    assert run.recipients_json is None, run.recipients_json


async def case_close_mass_run_skips_a_scheduled_send():
    """`server._close_mass_run` is the composer's + the legacy route's close step.
    An IMMEDIATE send records the body, the stamp and the recipients; a SCHEDULED
    one records none of them, because OF has not sent it — a `sent_at` in the future
    would splice a line onto threads it never reached. The legacy route closes a
    scheduled send immediately, which is exactly why the flag exists."""
    import server  # noqa: E402
    aid = "acc_mass_close"
    await _seed_account(aid)
    fake = FakeRosterClient(fans=[8201, 8202])
    server._load_client = lambda account_id: fake  # type: ignore[attr-defined]
    audience = {"user_lists": ["fans"], "excluded_users": [8202]}

    async def _mint() -> int:
        async with get_session() as s:
            mr = MassRun(account_id=aid, audience_filter="{}", recipient_count=0,
                         status="running")
            s.add(mr)
            await s.flush()
            return int(mr.id)

    immediate = await _mint()
    await server._close_mass_run(
        account_id=aid, employee_id=None, mass_run_id=immediate,
        text="just say please", price=0,
        result={"id": 990001, "createdAt": "2026-06-04T10:00:00+00:00"},
        recipient_ids=[], audience=audience, scheduled=False)
    # The recipient record is backgrounded so the composer response never waits
    # on a 17-page roster crawl — drain it before asserting.
    await asyncio.gather(*list(server._bg_tasks))

    later = await _mint()
    await server._close_mass_run(
        account_id=aid, employee_id=None, mass_run_id=later,
        text="tomorrow's blast", price=0,
        result={"id": 990002, "createdAt": "2026-06-04T10:00:01+00:00"},
        recipient_ids=[], audience=audience, scheduled=True)
    await asyncio.gather(*list(server._bg_tasks))

    async with get_session() as s:
        a = await s.get(MassRun, immediate)
        b = await s.get(MassRun, later)
    assert a.body == "just say please", a.body
    assert a.sent_at == datetime(2026, 6, 4, 10, 0, 0), a.sent_at
    assert json.loads(a.recipients_json) == [8201], a.recipients_json
    assert b.body is None and b.sent_at is None, (b.body, b.sent_at)
    assert b.recipients_json is None, b.recipients_json
    # Both still CLOSE — the queue id is what the Mass Messages tab joins on.
    assert a.status == "ok" and b.status == "ok", (a.status, b.status)
    assert b.queue_id == 990002, b.queue_id


def case_init_db_heals_the_four_columns_and_the_index():
    """A live box upgrades by BOOTING, not by alembic: `init_db` ALTERs missing
    nullable columns and creates missing indexes. Both halves are asserted, and the
    index half separately, because index creation only LOGS its failures — a box
    could come up with the columns and no `ix_mass_runs_account_sent` and nothing
    would say so except `_recent_mass_runs` getting slow."""
    import sqlite3
    import tempfile
    import os
    from pathlib import Path
    old = Path(tempfile.gettempdir()) / f"blastsplice_old_{os.getpid()}.db"
    if old.exists():
        old.unlink()
    con = sqlite3.connect(old)
    # The pre-change shape: mass_runs without the splice record, and the
    # alembic_version row that sends init_db down the ADDITIVE catch-up path.
    con.executescript("""
        CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);
        INSERT INTO alembic_version VALUES ('0001_initial');
        CREATE TABLE accounts (id VARCHAR NOT NULL PRIMARY KEY);
        CREATE TABLE mass_runs (
            id INTEGER NOT NULL PRIMARY KEY,
            account_id VARCHAR NOT NULL,
            funnel_id INTEGER,
            started_by_employee_id INTEGER,
            audience_filter TEXT NOT NULL,
            recipient_count INTEGER NOT NULL,
            queue_id BIGINT,
            automation_kind VARCHAR,
            started_at DATETIME,
            completed_at DATETIME,
            status VARCHAR NOT NULL
        );
    """)
    con.commit()
    con.close()

    # `init_db` builds its own sync engine off the module-level DATABASE_URL, so
    # pointing that at the legacy file is the whole redirect — no session factory
    # is rebound and the harness DB is untouched.
    # `import db.engine as X` would hand back the AsyncEngine: db/__init__ binds
    # the name `engine` on the package and that attribute wins over the submodule.
    import importlib  # noqa: E402
    db_engine = importlib.import_module("db.engine")
    prev_url = db_engine.DATABASE_URL
    try:
        db_engine.DATABASE_URL = f"sqlite+aiosqlite:///{old}"
        asyncio.run(db_engine.init_db())
    finally:
        db_engine.DATABASE_URL = prev_url

    con = sqlite3.connect(old)
    cols = {r[1] for r in con.execute("PRAGMA table_info(mass_runs)")}
    idx = {r[1] for r in con.execute("PRAGMA index_list(mass_runs)")}
    con.close()
    old.unlink()
    for c in ("body", "sent_at", "unsent_at", "recipients_json"):
        assert c in cols, (c, sorted(cols))
    assert "ix_mass_runs_account_sent" in idx, sorted(idx)


# ── House cases (automation-test-writer): dry_run / no-id / cap / list members ──

async def case_mass_premade_dry_run_never_reaches_this_sender():
    """Covers mass_premade's preview path, not send_mass_message (which has no
    dry run of its own): the delegate's dry_run must stop before this sender —
    no OF call, no mass_runs row, no messages row."""
    import automations.mass_premade  # noqa: F401 — registers the delegate
    aid = "acc_mass_dry"
    await _seed_account(aid)
    fake = FakeClient()
    _use_fake(fake)
    res = await run_once(aid, "mass_premade", payload={
        "dry_run": True, "messages": [{"text": "a", "included_users": [9101]}],
    })
    assert res.get("dry_run") is True and res.get("sent") == 0, res
    assert fake.sent == [], fake.sent
    async with get_session() as s:
        assert (await s.execute(select(MassRun).where(MassRun.account_id == aid))
                ).scalars().all() == []
        assert (await s.execute(select(Message).where(Message.account_id == aid))
                ).scalars().all() == []


async def case_no_id_response_still_persists():
    """OF answers 200 with no queue id / createdAt / echo (`{"success": true}`):
    the broadcast went out, so the run closes ok with queue_id NULL and every
    known recipient still gets its optimistic row (else the next blast re-touches
    them blind)."""
    aid = "acc_mass_noid"
    await _seed_account(aid)
    fake = FakeClient(response={"success": True})
    _use_fake(fake)
    await enqueue_job(aid, "send_mass_message", payload={
        "text": "no id", "included_users": [9201, 9202],
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res
    assert res["queue_id"] is None and res["echoed_rows"] == 0, res
    assert res["optimistic_rows"] == 2, res
    async with get_session() as s:
        mr = (await s.execute(select(MassRun).where(MassRun.account_id == aid))
              ).scalars().one()
        assert mr.status == "ok" and mr.queue_id is None, (mr.status, mr.queue_id)
        assert mr.body == "no id" and mr.sent_at is not None, (mr.body, mr.sent_at)
        fans = sorted((await s.execute(
            select(Message.fan_id).where(Message.account_id == aid))).scalars().all())
    assert fans == [9201, 9202], fans


async def case_recent_chat_limit_caps_the_audience():
    """`recent_chat_limit` is the audience cap: only the N most recent chatters
    join; explicit fans are never capped."""
    aid = "acc_mass_cap"
    await _seed_account(aid)
    now = datetime.utcnow()
    async with get_session() as s:
        for i, fid in enumerate((9301, 9302, 9303)):     # 9303 newest
            s.add(Message(account_id=aid, fan_id=fid, message_id=93000 + i,
                          direction="in", body="hi",
                          created_at=now - timedelta(minutes=30 - i)))
    fake = FakeClient()
    _use_fake(fake)
    await enqueue_job(aid, "send_mass_message", payload={
        "text": "capped", "included_users": [9309],
        "recent_chat_hours": 2, "recent_chat_limit": 2,
        "exclude_replied_hours": 0, "exclude_inbound_hours": 0,
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res
    assert res["recipients"] == 3, res
    assert sorted(fake.sent[0]["included_users"]) == [9302, 9303, 9309], fake.sent[0]


async def case_list_members_union_minus_exclude_lists():
    """DB list members join the explicit fans (deduped, explicit first); an
    exclude list's members are dropped even when also listed explicitly."""
    aid = "acc_mass_lists"
    await _seed_account(aid)
    inc = await _seed_list(aid, "Mass_In", [9402, 9403, 9404])
    exc = await _seed_list(aid, "Mass_Out", [9401, 9404])
    fake = FakeClient()
    _use_fake(fake)
    await enqueue_job(aid, "send_mass_message", payload={
        "text": "lists", "included_users": [9401, 9402],
        "list_ids": [inc], "exclude_list_ids": [exc],
        "exclude_replied_hours": 0, "exclude_inbound_hours": 0,
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok" and res["recipients"] == 2, res
    assert fake.sent[0]["included_users"] == [9402, 9403], fake.sent[0]
    assert fake.sent[0]["excluded_users"] == [9401, 9404], fake.sent[0]
    async with get_session() as s:
        mr = (await s.execute(select(MassRun).where(MassRun.account_id == aid))
              ).scalars().one()
    af = json.loads(mr.audience_filter)
    assert af["list_ids"] == [inc] and af["included_users"] == [9402, 9403], af
    assert mr.recipient_count == 2, mr.recipient_count


_harness.run(
    case_run,
    case_echoed_real_rows,
    case_skips_empty,
    case_audience_resolution,
    case_list_broadcast_syncs_exclude_list,
    case_exclude_sync_failure_fails_closed,
    case_exclude_sync_tolerates_one_bad_user,
    case_exclude_sync_steady_state_straggler,
    case_funnel_dedup_skips_answered,
    case_exclude_last_chat_hours,
    case_pending_scheduled_send_excluded,
    case_resolve_recipients_reads_both_rosters,
    case_resolve_recipients_fails_closed,
    case_the_run_records_body_stamp_and_recipients,
    case_an_unreadable_roster_leaves_the_run_unrecorded,
    case_close_mass_run_skips_a_scheduled_send,
    case_init_db_heals_the_four_columns_and_the_index,
    case_mass_premade_dry_run_never_reaches_this_sender,
    case_no_id_response_still_persists,
    case_recent_chat_limit_caps_the_audience,
    case_list_members_union_minus_exclude_lists,
)
