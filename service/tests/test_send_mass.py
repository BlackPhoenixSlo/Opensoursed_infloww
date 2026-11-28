#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
from _of_fixtures import UNLISTABLE_403, of_error  # noqa: E402
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
    AccountAiConfig,
    AutomationRun,
    Fan,
    FunnelResponder,
    List,
    ListMember,
    MassMessageFunnel,
    MassRun,
    Message,
    ScheduledJob,
)



class FakeClient:

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
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan_id, message_id=msg_id,
            direction=direction, body="hi", created_at=datetime.utcnow(),
        ))



async def case_run():
    aid = "acc_mass1"
    await _seed_account(aid)
    funnel_id = await _seed_funnel("strokes", "How many strokes? 😈")
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
    assert res["recipients"] == 2, res
    assert res["optimistic_rows"] == 2, res
    assert res["echoed_rows"] == 0, res

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


async def case_a_refused_post_closes_its_minted_run():
    from types import SimpleNamespace
    from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError, ProxyError, ReadTimeout
    from db.models import MASS_RUN_FAILED, MASS_RUN_REFUSED
    from of_client import OFAPIError
    import run_decide
    noconn = CurlConnectionError("Failed to connect to 127.0.0.1 port 9")
# curl_cffi CurlECode.COULDNT_CONNECT
    noconn.code = 7
    of_400 = OFAPIError("400 for https://onlyfans.com/api2/v2/messages/queue\n{}",
                        response=SimpleNamespace(status_code=400, text="{}"))
    for aid, err, want_run, want_err in (
            ("acc_mass_refused", ProxyError("CONNECT tunnel failed, response 403"), MASS_RUN_REFUSED,
             f"{run_decide.PROXY_RETRY}:1 ("),
            ("acc_mass_timeout", ReadTimeout("Operation timed out"), "running", run_decide.MAY_HAVE_SENT),
            ("acc_mass_noconn", noconn, MASS_RUN_FAILED, None),
            ("acc_mass_of_400", of_400, MASS_RUN_FAILED, None)):
        await _seed_account(aid)

        class _Fails(FakeClient):
            def send_mass_message(self, text, **kw):
                raise err
        _use_fake(_Fails())
        job_id = await enqueue_job(aid, "send_mass_message", payload={"text": "hi", "included_users": [2001]})
        res = await run_once(aid, "send_mass_message")
        assert res["status"] == "error", res
        async with get_session() as s:
            runs = (await s.execute(select(MassRun).where(MassRun.account_id == aid))).scalars().all()
            assert [r.status for r in runs] == [want_run], (aid, [r.status for r in runs])
            assert (runs[0].completed_at is not None) == (want_run != "running"), runs[0].completed_at
            job = await s.get(ScheduledJob, job_id)
            assert (job.last_error.startswith(want_err) if want_err
                    else not job.last_error.startswith(run_decide.PROXY_RETRY)), (aid, job.last_error)


async def case_an_exclude_sync_the_proxy_refused_raises_for_the_proxy_wait():
    from curl_cffi.requests.exceptions import ProxyError
    import audiences
    import run_decide
    for aid, err in (("acc_excl_refused", ProxyError("CONNECT tunnel failed, response 403")),
                     ("acc_excl_broken", RuntimeError("lists 500"))):
        await _seed_account(aid)
        _use_fake(FakeClient())

        async def _boom(*a, _err=err, **kw):
            raise _err
        real, audiences.ensure_exclude_list = audiences.ensure_exclude_list, _boom
        try:
            job_id = await enqueue_job(aid, "send_mass_message", payload={
                "text": "hi", "user_lists": ["fans"], "excluded_users": [2002]})
            res = await run_once(aid, "send_mass_message")
        finally:
            audiences.ensure_exclude_list = real
        async with get_session() as s:
            assert (await s.execute(select(MassRun).where(MassRun.account_id == aid))).scalars().all() == []
            job = await s.get(ScheduledJob, job_id)
        if isinstance(err, ProxyError):
            assert (job.last_error or "").startswith(f"{run_decide.PROXY_RETRY}:1 ("), (res, job.last_error)
        else:
            assert "exclude_list_sync_failed" in json.dumps(res), res
            assert not (job.last_error or "").startswith(run_decide.PROXY_RETRY), job.last_error



async def case_echoed_real_rows():
    aid = "acc_mass2"
    await _seed_account(aid)
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
        assert m3001[0].message_id == 9988776655, m3001[0].message_id
        assert m3001[0].mass_run_id == mr.id, m3001[0].mass_run_id

        m3002 = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == 3002)
        )).scalars().all()
        assert len(m3002) == 1 and m3002[0].message_id == ph, m3002



async def case_skips_empty():
    aid = "acc_mass3"
    await _seed_account(aid)
    _use_fake(FakeClient())

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



async def case_audience_resolution():
    aid = "acc_mass4"
    await _seed_account(aid)
    await _seed_message(aid, 5001, "out", 60001)
    await _seed_message(aid, 5002, "in", 60002)
    fake = FakeClient()
    _use_fake(fake)

    await enqueue_job(aid, "send_mass_message", payload={
        "text": "online babe 😘",
        "included_users": [5009],
        "recent_chat_hours": 48,
        "exclude_replied_hours": 48,
        "exclude_inbound_hours": 0,
    })
    res = await run_once(aid, "send_mass_message")

    assert res["status"] == "ok", res
    assert res["recipients"] == 2, res
    assert sorted(fake.sent[0]["included_users"]) == [5002, 5009], fake.sent[0]
    assert fake.sent[0]["excluded_users"] == [5001], fake.sent[0]



async def case_list_broadcast_syncs_exclude_list():
    aid = "acc_mass5"
    await _seed_account(aid)
    await _seed_message(aid, 6001, "out", 70001)
    await _seed_message(aid, 6002, "in", 70002)
    fake = FakeListClient()
# OF has no per-user exclusion field on broadcasts (excludedUsers is silently dropped)
    fake.lists.append({"id": FakeListClient.AUTO_LID, "name": "Auto_Exclude"})
    fake.members[FakeListClient.AUTO_LID] = {6001, 9999}
    _use_fake(fake)

    await enqueue_job(aid, "send_mass_message", payload={
        "text": "chatttt me",
        "user_lists": ["fans"],
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res

    sent = fake.sent[0]
    assert sent["user_lists"] == ["fans"], sent
    assert FakeListClient.AUTO_LID in sent["excluded_user_lists"], sent
    assert fake.members[FakeListClient.AUTO_LID] == {6001, 6002}, fake.members
    assert (FakeListClient.AUTO_LID, 9999) in fake.removed, fake.removed


async def case_exclude_sync_failure_fails_closed():
    aid = "acc_mass6"
    await _seed_account(aid)
    await _seed_message(aid, 7001, "out", 80001)
    fake = FakeListClient()

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
    from audiences import _ensure_exclude_blocking

    fake = FakeListClient()
    fake.lists.append({"id": FakeListClient.AUTO_LID, "name": "Auto_Exclude"})
    fake.members[FakeListClient.AUTO_LID] = set()
    bad = 7463635
    real_add = fake.add_user_to_list
    fake.add_user_to_list = (lambda lid, uid: (_ for _ in ()).throw(
        of_error(403, UNLISTABLE_403))
        if int(uid) == bad else real_add(lid, uid))

    lid, _ = _ensure_exclude_blocking("of-bad-user", fake, {1, 2, bad, 3})
    assert lid == FakeListClient.AUTO_LID, lid
    assert fake.members[FakeListClient.AUTO_LID] == {1, 2, 3}, fake.members

    fake2 = FakeListClient()
    fake2.lists.append({"id": FakeListClient.AUTO_LID, "name": "Auto_Exclude"})
    fake2.members[FakeListClient.AUTO_LID] = set()
    fake2.add_user_to_list = lambda lid, uid: (_ for _ in ()).throw(RuntimeError("OF down"))
    raised = False
    try:
        _ensure_exclude_blocking("of-down", fake2, {1, 2, 3})
    except RuntimeError:
        raised = True
    assert raised, "all-adds-fail must re-raise (fail closed)"


async def case_exclude_sync_steady_state_straggler():
    from audiences import _ensure_exclude_blocking

    fake = FakeListClient()
    fake.lists.append({"id": FakeListClient.AUTO_LID, "name": "Auto_Exclude"})
    fake.members[FakeListClient.AUTO_LID] = {1, 2, 3}
    bad = 7463635
    fake.add_user_to_list = lambda lid, uid: (_ for _ in ()).throw(
        of_error(403, UNLISTABLE_403))

    lid, _ = _ensure_exclude_blocking("of-straggler", fake, {1, 2, 3, bad})
    assert lid == FakeListClient.AUTO_LID, lid
    assert fake.members[FakeListClient.AUTO_LID] == {1, 2, 3}, fake.members
    assert fake.removed == [], fake.removed


async def case_funnel_dedup_skips_answered():
    aid = "acc_mass_ans"
    await _seed_account(aid)
    fid = await _seed_funnel("strokes_ans", "How many strokes? 😈")
    async with get_session() as s:
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
    assert sorted(fake.sent[0]["included_users"]) == [5001, 5003], fake.sent[0]



async def case_exclude_last_chat_hours():
    aid = "acc_mass_lastchat"
    await _seed_account(aid)
    await _seed_message(aid, 9001, "out", 90001)
    await _seed_message(aid, 9002, "in", 90002)
    fake = FakeClient()
    _use_fake(fake)

    await enqueue_job(aid, "send_mass_message", payload={
        "text": "hey 😘",
        "included_users": [9001, 9002, 9003],
        "exclude_replied_hours": 0,
        "exclude_inbound_hours": 0,
        "exclude_last_chat_hours": 48,
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res
    assert res["recipients"] == 1, res
    assert fake.sent[0]["included_users"] == [9003], fake.sent[0]
    assert sorted(fake.sent[0]["excluded_users"]) == [9001, 9002], fake.sent[0]



async def case_pending_scheduled_send_excluded():
    aid = "acc_mass_pending"
    await _seed_account(aid)
    await enqueue_job(aid, "scheduled_send",
                      payload={"fan_id": 7001, "text": "later babe"},
                      run_at=datetime.utcnow() + timedelta(minutes=15))
    await enqueue_job(aid, "send_mass_message",
                      payload={"text": "queued", "included_users": [7003]},
                      run_at=datetime.utcnow() + timedelta(minutes=15))
    assert await pending_send_fan_ids(aid) == {7001, 7003}, "both pending targets seen"

    fake = FakeClient()
    _use_fake(fake)
    await enqueue_job(aid, "send_mass_message", payload={
        "text": "blast now",
        "included_users": [7001, 7002, 7003],
        "exclude_replied_hours": 0,
        "exclude_inbound_hours": 0,
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res
    assert res["recipients"] == 1, res
    assert fake.sent[0]["included_users"] == [7002], fake.sent[0]



class FakeRosterClient(FakeListClient):

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
        return rows

def case_roster_audience_reads_both_rosters():
    from audiences import roster_audience_blocking
    c = FakeRosterClient(fans=[1, 2, 3, 4], following=[4, 5, 6])
    c.members[901] = {3, 6}
    c.members[902] = {7, 8}
    got = roster_audience_blocking(
        c, account_id="of-test", user_lists=["fans", "following", "902"], excluded_user_lists=[901])
    assert got == [1, 2, 4, 5, 7, 8], got
    assert any(x.startswith("subscribers:active") for x in c.calls), c.calls
    assert any(x.startswith("following:active:0:infinite") for x in c.calls), c.calls

    c2 = FakeRosterClient(fans=[], following=[10, 11], envelope_following=True)
    assert roster_audience_blocking(c2, account_id="of-test", user_lists=["following"]) == [10, 11]


def case_roster_audience_fails_closed():
    from audiences import roster_audience_blocking
    base = dict(user_lists=["fans"])

    ok = FakeRosterClient(fans=[5])
    assert roster_audience_blocking(ok, account_id="of-test", **base) == [5], "control"

    assert roster_audience_blocking(
        FakeRosterClient(fans=[5]), account_id="of-test", user_lists=["fans", "recent"]) is None

    class Boom(FakeRosterClient):
        def subscribers(self, **kw):
            raise RuntimeError("proxy 403")
    assert roster_audience_blocking(Boom(), account_id="of-test", **base) is None

    class Endless(FakeRosterClient):
        def subscribers(self, *, type="active", limit=10, offset=0, **kw):
            base_id = 1000 + offset
            return {"list": [{"id": base_id + i} for i in range(limit)],
                    "hasMore": True}
    assert roster_audience_blocking(Endless(), account_id="of-test", **base) is None

    class BadExclude(FakeRosterClient):
        def list_users_in(self, list_id, **kw):
            raise RuntimeError("list gone")
    assert roster_audience_blocking(
        BadExclude(fans=[5]), account_id="of-test", excluded_user_lists=[901], **base) is None


async def case_the_run_records_body_and_stamp_and_reads_no_roster():
    aid = "acc_mass_rec"
    await _seed_account(aid)
    await _seed_message(aid, 8102, "out", 81002)
    fake = FakeRosterClient(fans=[8101, 8102], following=[8103])
    _use_fake(fake)
    await enqueue_job(aid, "send_mass_message", payload={
        "text": "just say please",
        "user_lists": ["fans", "following"],
    })
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok", res
    assert fake.calls == [], fake.calls
    async with get_session() as s:
        run = (await s.execute(
            select(MassRun).where(MassRun.account_id == aid)
            .order_by(MassRun.id.desc()))).scalars().first()
        assert run is not None and run.status == "ok", run
        assert run.body == "just say please", run.body
        assert run.sent_at == datetime(2026, 6, 4, 10, 0, 0), run.sent_at
        assert run.recipients_json is None and run.crawl_outcome is None, run.recipients_json
        af = json.loads(run.audience_filter)
        assert "excluded_user_lists" in af and "fence" in af, af
        assert 8102 in af["excluded_users"], af


class CountingRosterClient(FakeRosterClient):

    def __init__(self, **kw):
        super().__init__(**kw)
        self.list_reads = 0

    def list_users_in(self, list_id, *, limit=20, offset=0):
        if offset == 0:
            self.list_reads += 1
        return super().list_users_in(list_id, limit=limit, offset=offset)


async def case_the_composer_reads_no_roster():
    import mass_queue_api  # noqa: E402
    import server  # noqa: E402
    aid = "acc_mass_composer_no_roster"
    await _seed_account(aid)
    fake = CountingRosterClient(fans=[8501, 8502, 8503])
    run_ids: list[int] = []

    async def _open(_request, **kw):
        async with get_session() as s:
            mr = MassRun(account_id=aid, audience_filter="{}", recipient_count=0, status="running")
            s.add(mr)
            await s.flush()
            run_ids.append(int(mr.id))
        return aid, None, run_ids[-1]
    orig = (server._resolve_account_id, server._get_client, mass_queue_api._open_mass_run)
    server._resolve_account_id = lambda _req: aid
    server._get_client = lambda *_a: fake
    mass_queue_api._open_mass_run = _open
    try:
        await mass_queue_api.of_send_or_schedule_mass(None, mass_queue_api._MassScheduleBody(
            text="composer", user_lists=["fans"], excluded_users=[8502]))
        assert FakeListClient.AUTO_LID in fake.sent[0]["excluded_user_lists"], fake.sent
    finally:
        (server._resolve_account_id, server._get_client, mass_queue_api._open_mass_run) = orig
    assert fake.list_reads == 1, fake.list_reads
    assert fake.calls == [], fake.calls
    async with get_session() as s:
        run = await s.get(MassRun, run_ids[0])
    assert run.status == "ok" and run.recipients_json is None, (run.status, run.recipients_json)


async def case_the_composer_reports_kept_ids_and_refuses_nobody_on_request():
    import audiences  # noqa: E402
    import mass_queue_api  # noqa: E402
    import server  # noqa: E402
    from fastapi import HTTPException  # noqa: E402
    aid = "acc_mass_composer_kept_ids"
    await _seed_account(aid)
    opened: list[int] = []

    async def _open(_request, **kw):
        opened.append(1)
        return aid, None, None

    async def _opted_out(_aid, _name):
        return {8602}
    fake = FakeListClient()
    orig = (server._resolve_account_id, server._get_client, mass_queue_api._open_mass_run,
            audiences.exclude_list_fan_ids)
    server._resolve_account_id = lambda _req: aid
    server._get_client = lambda *_a: fake
    mass_queue_api._open_mass_run = _open
    audiences.exclude_list_fan_ids = _opted_out
    body = lambda ids, **kw: mass_queue_api._MassScheduleBody(text="hi", user_ids=ids, **kw)  # noqa: E731
    try:
        out = await mass_queue_api.of_send_or_schedule_mass(None, body([8601, 8602, 8601]))
        assert out["_user_ids_kept"] == {"asked": 2, "kept": 1}, out
        assert set(fake.sent[-1]["included_users"]) == {8601}, fake.sent
        n_open = len(opened)
        for kw in ({}, {"require_recipients": True}):
            try:
                await mass_queue_api.of_send_or_schedule_mass(None, body([8602], **kw))
                raise AssertionError(f"nobody left must refuse ({kw})")
            except HTTPException as e:
                assert e.status_code == 422 and "nobody left to send to: 1 of 1 fan" in e.detail, e.detail
        assert len(fake.sent) == 1 and len(opened) == n_open, (fake.sent, opened)
        out = await mass_queue_api.of_send_or_schedule_mass(None, body([8602], require_recipients=True,
                                                                       user_lists=["fans"]))
        assert len(fake.sent) == 2 and out["_user_ids_kept"] == {"asked": 1, "kept": 0}, out
        fake._response = {"id": 770002}
        out = await mass_queue_api.of_send_or_schedule_mass(None, mass_queue_api._MassScheduleBody(
            text="hi", user_lists=["fans"]))
        assert "_user_ids_kept" not in out, out
    finally:
        (server._resolve_account_id, server._get_client, mass_queue_api._open_mass_run,
         audiences.exclude_list_fan_ids) = orig


async def case_close_mass_run_skips_a_scheduled_send():
    import mass_queue_api  # noqa: E402
    aid = "acc_mass_close"
    await _seed_account(aid)

    async def _mint() -> int:
        async with get_session() as s:
            mr = MassRun(account_id=aid, audience_filter="{}", recipient_count=0,
                         status="running")
            s.add(mr)
            await s.flush()
            return int(mr.id)

    immediate = await _mint()
    await mass_queue_api._close_mass_run(
        account_id=aid, employee_id=None, mass_run_id=immediate,
        text="just say please", price=0,
        result={"id": 990001, "createdAt": "2026-06-04T10:00:00+00:00"},
        recipient_ids=[], scheduled=False)

    later = await _mint()
    await mass_queue_api._close_mass_run(
        account_id=aid, employee_id=None, mass_run_id=later,
        text="tomorrow's blast", price=0,
        result={"id": 990002, "createdAt": "2026-06-04T10:00:01+00:00"},
        recipient_ids=[], scheduled=True)

    async with get_session() as s:
        a = await s.get(MassRun, immediate)
        b = await s.get(MassRun, later)
    assert a.body == "just say please", a.body
    assert a.sent_at == datetime(2026, 6, 4, 10, 0, 0), a.sent_at
    assert b.body is None and b.sent_at is None, (b.body, b.sent_at)
    assert a.recipients_json is None and b.recipients_json is None
    assert a.status == "ok" and b.status == "ok", (a.status, b.status)
    assert b.queue_id == 990002, b.queue_id


def case_init_db_heals_the_four_columns_and_the_index():
    import sqlite3
    import tempfile
    import os
    from pathlib import Path
    old = Path(tempfile.gettempdir()) / f"blastsplice_old_{os.getpid()}.db"
    if old.exists():
        old.unlink()
    con = sqlite3.connect(old)
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

    import importlib  # noqa: E402
# `import db.engine as X` yields the AsyncEngine: the package binds `engine` over the submodule
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
    for c in ("body", "sent_at", "unsent_at", "recipients_json", "crawl_outcome"):
        assert c in cols, (c, sorted(cols))
    assert "ix_mass_runs_account_sent" in idx, sorted(idx)



async def case_mass_premade_dry_run_never_reaches_this_sender():
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
    aid = "acc_mass_cap"
    await _seed_account(aid)
    now = datetime.utcnow()
    async with get_session() as s:
        for i, fid in enumerate((9301, 9302, 9303)):
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



class FakeDryClient(FakeRosterClient):

    def __init__(self, **kw):
        super().__init__(**kw)
        self.writes: list[tuple] = []

    def create_list(self, name):
        self.writes.append(("create", name))
        return super().create_list(name)

    def add_user_to_list(self, list_id, user_id):
        self.writes.append(("add", int(list_id), int(user_id)))
        super().add_user_to_list(list_id, user_id)

    def remove_user_from_list(self, list_id, user_id):
        self.writes.append(("remove", int(list_id), int(user_id)))
        super().remove_user_from_list(list_id, user_id)


async def _written(aid: str) -> tuple[int, int]:
    async with get_session() as s:
        runs = (await s.execute(select(MassRun).where(MassRun.account_id == aid))).scalars().all()
        msgs = (await s.execute(select(Message).where(Message.account_id == aid))).scalars().all()
    return len(runs), len(msgs)


async def case_dry_run_explicit_sends_nothing_and_matches_the_real_run():
    aid = "acc_mass_dry_exp"
    await _seed_account(aid)
    await _seed_message(aid, 9601, "out", 96001)
    fake = FakeDryClient()
    _use_fake(fake)
    payload = {"text": "dry hi", "included_users": [9601, 9602, 9603, 9604],
               "excluded_users": [9603]}
    job = await enqueue_job(aid, "send_mass_message", payload={**payload, "dry_run": True})
    res = await run_once(aid, "send_mass_message")
    assert res["status"] == "ok" and res["dry_run"] is True and res["sent"] == 0, res
    assert res["would_send"] == [9602, 9604] and res["would_send_count"] == 2, res
    assert res["audience"] == "explicit", res
    assert fake.sent == [] and fake.writes == [], (fake.sent, fake.writes)
    assert await _written(aid) == (0, 1), "no mass_runs row, only the seeded guard row"
    async with get_session() as s:
        j = await s.get(ScheduledJob, job)
        arun = (await s.execute(select(AutomationRun).where(
            AutomationRun.account_id == aid))).scalars().one()
    assert j.status == "done", j.status
    assert arun.status == "ok" and json.loads(arun.stats_json)["dry_run"] is True, arun.stats_json

    res2 = await run_once(aid, "send_mass_message", payload=payload)
    assert res2["status"] == "ok" and "dry_run" not in res2, res2
    assert fake.sent[0]["included_users"] == res["would_send"], fake.sent


async def case_dry_run_list_reads_no_roster_and_writes_no_list():
    aid = "acc_mass_dry_list"
    await _seed_account(aid)
    await _seed_message(aid, 9701, "out", 97001)
    async with get_session() as s:
        lst = List(account_id=aid, name="MASSdmEXCLUDE", kind="exclude", is_system=True)
        s.add(lst)
        await s.flush()
        s.add(ListMember(list_id=lst.id, fan_id=9702))
    fake = FakeDryClient()
    fake.lists.append({"id": 9700, "name": "vip"})
    fake.members[9700] = {9701, 9702, 9703, 9704, 9705}
    _use_fake(fake)
    payload = {"text": "dry list", "user_lists": ["9700"], "excluded_users": [9703]}
    res = await run_once(aid, "send_mass_message", payload={**payload, "dry_run": True})
    assert res["dry_run"] is True and res["audience"] == "list", res
    assert res["would_send"] is None and res["reason"] == "list_audience", res
    assert fake.sent == [] and fake.writes == [] and fake.calls == [], (fake.sent, fake.writes)
    assert [x["name"] for x in fake.lists] == ["vip"], "no Auto_Exclude made"
    assert await _written(aid) == (0, 1), await _written(aid)

    res2 = await run_once(aid, "send_mass_message", payload=payload)
    assert res2["status"] == "ok" and fake.sent and fake.writes, (res2, fake.writes)
    async with get_session() as s:
        run = (await s.execute(select(MassRun).where(MassRun.account_id == aid))).scalars().one()
    assert run.recipients_json is None, run.recipients_json


async def _seed_enforce(aid: str, members: tuple, universe: tuple) -> int:
    await _seed_account(aid)
    async with get_session() as s:
        inc = List(account_id=aid, name="Include", kind="automation_include",
                   synced_at=datetime.utcnow())
        s.add(inc)
        await s.flush()
        for fid in members:
            s.add(ListMember(list_id=inc.id, fan_id=fid))
        for fid in universe:
            s.add(Fan(account_id=aid, fan_id=fid))
        s.add(AccountAiConfig(account_id=aid, audience_mode="enforce",
                              audience_list_id=int(inc.id)))
        return int(inc.id)


async def case_dry_run_enforce_fence_in_memory():
    aid = "acc_mass_dry_fence"
    await _seed_enforce(aid, (9801, 9802), (9801, 9802, 9803))
    fake = FakeDryClient()
    fake.lists.append({"id": 9800, "name": "vip"})
    fake.members[9800] = {9801, 9803, 9804}
    _use_fake(fake)
    base = {"text": "fenced", "exclude_replied_hours": 0, "exclude_inbound_hours": 0,
            "dry_run": True}
    res = await run_once(aid, "send_mass_message",
                         payload={**base, "included_users": [9801, 9803]})
    assert res["would_send"] == [9801], res
    res = await run_once(aid, "send_mass_message", payload={**base, "user_lists": ["9800"]})
    assert res["would_send"] is None and res["reason"] == "list_audience", res
    res = await run_once(aid, "send_mass_message", payload={**base, "included_users": [9803]})
    assert (res["status"], res["reason"], res["dry_run"], res["sent"]) == (
        "skipped", "audience_empty", True, 0), res
    assert fake.sent == [] and fake.writes == [], (fake.sent, fake.writes)


async def case_dry_run_enforce_halts_like_the_real_run():
    import audience_include
    aid = "acc_mass_dry_halt"
    inc = await _seed_enforce(aid, (9851,), (9851, 9852))
    fake = FakeDryClient()
    fake.lists.append({"id": 9850, "name": "vip"})
    fake.members[9850] = {9851, 9852}
    _use_fake(fake)
    payload = {"text": "halt", "user_lists": ["9850"],
               "exclude_replied_hours": 0, "exclude_inbound_hours": 0}

    async def both() -> tuple[dict, dict]:
        dry = await run_once(aid, "send_mass_message", payload={**payload, "dry_run": True})
        assert fake.sent == [] and fake.writes == [], (fake.sent, fake.writes)
        return dry, await run_once(aid, "send_mass_message", payload=payload)

    for meta, want in (('{"paused": true}', "kill_switch"),
                       ('{"truncated": true}', "sync_truncated")):
        async with get_session() as s:
            (await s.get(List, inc)).sync_meta_json = meta
        dry, real = await both()
        assert dry["reason"] == real["reason"] == f"audience_halt:{want}", (dry, real)
        assert dry["status"] == "error" and dry["dry_run"] is True and dry["sent"] == 0, dry
    async with get_session() as s:
        (await s.get(List, inc)).sync_meta_json = None
    bound = audience_include.AUDIENCE_MAX_LIST_ROWS
    audience_include.AUDIENCE_MAX_LIST_ROWS = 0
    try:
        dry, real = await both()
    finally:
        audience_include.AUDIENCE_MAX_LIST_ROWS = bound
    assert dry["reason"] == real["reason"] == "audience_halt:fence_scale", (dry, real)
    assert dry["dry_run"] is True and dry["sent"] == 0, dry
    assert fake.sent == [] and fake.writes == [], (fake.sent, fake.writes)
    assert await _written(aid) == (0, 0)


async def case_dry_run_explicit_with_exclude_lists_reads_no_list():
    aid = "acc_mass_dry_unread"
    await _seed_account(aid)
    fake = FakeDryClient()
    fake.members[9871] = {9872}
    _use_fake(fake)
    payload = {"text": "read", "exclude_replied_hours": 0, "exclude_inbound_hours": 0,
               "included_users": [9872, 9873], "excluded_user_lists": [9871]}
    res = await run_once(aid, "send_mass_message", payload={**payload, "dry_run": True})
    assert res["would_send"] is None and res["audience"] == "explicit", res
    assert res["reason"] == "excluded_lists_unresolved", res
    assert fake.calls == [] and fake.sent == [], (fake.calls, fake.sent)


class _UnreadableListClient(FakeRosterClient):
    def list_users_in(self, list_id, *, limit=20, offset=0):
        raise RuntimeError("OF 502 on /lists/users")


async def case_explicit_send_subtracts_its_exclude_lists():
    aid = "acc_mass_explicit_excl"
    await _seed_account(aid)
    base = {"exclude_replied_hours": 0, "exclude_inbound_hours": 0,
            "excluded_user_lists": [9881]}
    fake = FakeRosterClient()
    fake.members[9881] = {9882}
    _use_fake(fake)
    res = await run_once(aid, "send_mass_message", payload={
        **base, "text": "x", "included_users": [9882, 9883]})
    assert res["status"] == "ok" and res["recipients"] == 1, res
    assert fake.sent[0]["included_users"] == [9883], fake.sent[0]
    assert await _written(aid) == (1, 1), await _written(aid)

    bad = _UnreadableListClient()
    _use_fake(bad)
    res = await run_once(aid, "send_mass_message", payload={
        **base, "text": "y", "included_users": [9884]})
    assert res["status"] == "error" and res["reason"] == "excluded_lists_unreadable", res
    assert bad.sent == [] and await _written(aid) == (1, 1), bad.sent

    fake2 = FakeRosterClient()
    fake2.members[9881] = {9885}
    _use_fake(fake2)
    res = await run_once(aid, "send_mass_message", payload={
        **base, "text": "z", "included_users": [9885]})
    assert res["status"] == "skipped" and res["reason"] == "audience_empty", res
    assert fake2.sent == [] and await _written(aid) == (1, 1), fake2.sent

async def case_dry_run_online_refuses_a_list():
    aid = "acc_mass_dry_online"
    await _seed_account(aid)
    fake = FakeDryClient(fans=[1, 2])
    _use_fake(fake)
    res = await run_once(aid, "send_mass_message", payload={
        "text": "who is on", "online_only": True, "dry_run": True})
    assert res["dry_run"] is True and res["would_send"] is None, res
    assert res["reason"] == "online_or_filtered", res
    assert fake.sent == [] and fake.writes == [], (fake.sent, fake.writes)
    assert await _written(aid) == (0, 0)


async def case_dry_run_ignores_queued_dry_runs():
    aid = "acc_mass_dry_pending"
    await _seed_account(aid)
    later = datetime.utcnow() + timedelta(minutes=15)
    await enqueue_job(aid, "send_mass_message", run_at=later, payload={
        "text": "queued dry", "included_users": [9901], "dry_run": True})
    await enqueue_job(aid, "send_mass_message", run_at=later, payload={
        "text": "queued real", "included_users": [9902]})
    _use_fake(FakeDryClient())
    res = await run_once(aid, "send_mass_message", payload={
        "text": "now", "included_users": [9901, 9902, 9903], "dry_run": True})
    assert res["would_send"] == [9901, 9903], res


async def case_dry_pending_ids_mirror_pending_send_fan_ids():
    aid = "acc_mass_dry_mirror"
    await _seed_account(aid)
    later = datetime.utcnow() + timedelta(minutes=15)
    for kind, payload in (("scheduled_send", {"fan_id": 9951}),
                          ("send_mass_message", {"fan_ids": [9952]}),
                          ("mass_premade", {"messages": [{"included_users": [9953]}]})):
        await enqueue_job(aid, kind, run_at=later, payload=payload)
    assert await a10._pending_send_ids_but_dry(aid) == await pending_send_fan_ids(aid) \
        == {9951, 9952, 9953}
    await enqueue_job(aid, "send_mass_message", run_at=later, payload={
        "included_users": [9954], "dry_run": True})
    assert await pending_send_fan_ids(aid) - await a10._pending_send_ids_but_dry(aid) == {9954}


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
    case_roster_audience_reads_both_rosters,
    case_roster_audience_fails_closed,
    case_the_run_records_body_and_stamp_and_reads_no_roster,
    case_the_composer_reads_no_roster,
    case_close_mass_run_skips_a_scheduled_send,
    case_init_db_heals_the_four_columns_and_the_index,
    case_mass_premade_dry_run_never_reaches_this_sender,
    case_no_id_response_still_persists,
    case_recent_chat_limit_caps_the_audience,
    case_list_members_union_minus_exclude_lists,
    case_dry_run_explicit_sends_nothing_and_matches_the_real_run,
    case_dry_run_list_reads_no_roster_and_writes_no_list,
    case_dry_run_enforce_fence_in_memory,
    case_dry_run_enforce_halts_like_the_real_run,
    case_dry_run_explicit_with_exclude_lists_reads_no_list,
    case_explicit_send_subtracts_its_exclude_lists,
    case_dry_run_online_refuses_a_list,
    case_dry_run_ignores_queued_dry_runs,
    case_dry_pending_ids_mirror_pending_send_fan_ids,
    case_a_refused_post_closes_its_minted_run,
    case_an_exclude_sync_the_proxy_refused_raises_for_the_proxy_wait,
    case_the_composer_reports_kept_ids_and_refuses_nobody_on_request,
)
