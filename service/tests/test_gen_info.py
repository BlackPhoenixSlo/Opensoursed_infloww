#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import llm_client  # noqa: E402
import automation_executor as ax  # noqa: E402,F401 — registers scrape_chats + plugin loader
from automation_executor import enqueue_job, run_once  # noqa: E402
from automations import gen_info, gen_info_plan  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    AutomationRule,
    AutomationRun,
    Fan,
    FanProfile,
    GrokCall,
    Message,
    ScheduledJob,
    ScrapeHistory,
    Transaction,
)

_GROK_PROFILE = {
    "nickname": "Bob//Toronto//31//Dev",
    "short_bio": "31yo dev from Toronto who tips often",
    "bullet_points": "- Age: 31\n- Job: Software Dev\n- Loc: Toronto",
    "Q1": "What game are you hooked on lately?",
    "Q2": "How's the new job?",
    "Q3": "Any travel plans?",
    "Tease1": "Bet your setup is insane...",
    "Tease2": "Missing our late-night chats...",
    "Tease3": "Your coffee obsession is so hot...",
    "original_name": "Bob",
    "real_name": "Bob",
    "his_age": "31",
    "home_country": "Canada",
    "home_city": "Toronto",
    "hobbies": "gaming, coffee",
    "occupation": "Software Dev",
    "relationship_status": "single",
    "fetishes": "",
}


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def raise_for_status(self):  # noqa: D401
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):  # noqa: A002
        _LLM_REQUESTS.append(json)
        return _FakeResponse({
            "choices": [{"message": {"content": json_dump(_GROK_PROFILE)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })


_LLM_REQUESTS: list[dict] = []


def _system_prompt_of(req: dict) -> str:
    return next(m["content"] for m in req["messages"] if m["role"] == "system")


def json_dump(obj) -> str:
    return json.dumps(obj)


def _install_fake_llm() -> None:
    llm_client.httpx.AsyncClient = _FakeAsyncClient  # type: ignore[attr-defined]


class _FakeOF:

    def __init__(self):
        self.nicks: list[tuple[int, str]] = []
        self.notes: list[tuple[int, str]] = []

    def set_fan_custom_name(self, user_id, name) -> dict:
        self.nicks.append((int(user_id), name))
        return {"success": True}

    def set_fan_note(self, user_id, note) -> dict:
        self.notes.append((int(user_id), note))
        return {"success": True}


def _use_fake_of() -> _FakeOF:
    fake = _FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_fan_with_msgs(
    aid: str, fan_id: int, *, in_msgs: int = 8, name: str = "Bob",
    spend_cents: int = 0,
) -> None:
    base = datetime(2026, 6, 1, 10, 0, 0)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fan_id, of_display_name=name,
                  of_username=name.lower()))
        mid = fan_id * 1000
        for i in range(in_msgs):
            s.add(Message(
                account_id=aid, fan_id=fan_id, message_id=mid + i,
                direction="in", body=f"<p>hey msg {i}</p>",
                created_at=base + timedelta(minutes=i),
            ))
        if spend_cents > 0:
            s.add(Message(
                account_id=aid, fan_id=fan_id, message_id=mid + 900,
                direction="out", body="<p>ppv</p>", price_cents=spend_cents,
                is_paid=True, created_at=base + timedelta(minutes=99),
            ))



async def case_gen_info_acceptance():
    aid, fan = "acc_gi_accept", 5001
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=9)

    _LLM_REQUESTS.clear()
    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    assert res["generated"] == 1, res
    assert res["attempted"] == 1, res

    assert len(_LLM_REQUESTS) == 1, _LLM_REQUESTS
    system = _system_prompt_of(_LLM_REQUESTS[0])
    for key in ("Q1", "Q2", "Q3", "Tease1", "Tease2", "Tease3"):
        assert f'"{key}"' not in system, key
    assert '"nickname"' in system and '"occupation"' in system, system

    async with get_session() as s:
        prof = await s.get(FanProfile, (aid, fan))
        assert prof is not None, "fan_profiles row written"
        assert prof.nickname == "Bob/Toronto/31/Dev", prof.nickname
        assert prof.short_bio and "dev" in prof.short_bio.lower(), prof.short_bio
        lines = (prof.q1, prof.q2, prof.q3, prof.tease1, prof.tease2, prof.tease3)
        assert lines == (None,) * 6, lines
        assert prof.original_name == "Bob", prof.original_name
        assert prof.message_count_at_gen == 9, prof.message_count_at_gen
        assert prof.generated_by_grok_call_id is not None, "links to grok_calls"

        f = await s.get(Fan, (aid, fan))
        assert f.his_age == "31" and f.home_city == "Toronto", (f.his_age, f.home_city)
        assert f.occupation == "Software Dev", f.occupation
        assert f.generated_nickname == "Bob/Toronto/31/Dev", f.generated_nickname
        assert f.grok_facts_updated_at is not None, "grok_facts_updated_at stamped"

        calls = (await s.execute(
            select(GrokCall).where(GrokCall.account_id == aid,
                                   GrokCall.purpose == "gen_info")
        )).scalars().all()
        assert len(calls) == 1, f"one grok_calls row, got {len(calls)}"
        assert calls[0].status == "done", calls[0].status
        assert calls[0].fan_id == fan, calls[0].fan_id
        assert calls[0].id == prof.generated_by_grok_call_id, "profile↔call link"

        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid,
                                        AutomationRun.kind == "gen_info")
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "ok", runs
        stats = json.loads(runs[0].stats_json)
        assert stats["generated"] == 1, stats



async def _seed_scrape_history(aid: str, fan_id: int, when: datetime) -> None:
    async with get_session() as s:
        s.add(ScrapeHistory(account_id=aid, fan_id=fan_id, last_message_id=1,
                            last_scrape_at=when))


async def case_qualification_gate():
    aid = "acc_gi_qual"
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, 6002, in_msgs=8)
    await _seed_fan_with_msgs(aid, 6004, in_msgs=1)

    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    assert res["candidates"] == 2, res
    assert res["deferred_for_scrape"] == 0, res
    assert res["generated"] == 1, res
    assert res["skipped_fresh"] == 1, res

    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 6002)) is not None, "8-msg fan profiled"
        assert await s.get(FanProfile, (aid, 6004)) is None, "1-msg fan below the floor"


async def case_thin_paying_fan_autoscraped():
    aid = "acc_gi_thin"
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, 8001, in_msgs=5, spend_cents=500)
    await _seed_fan_with_msgs(aid, 8002, in_msgs=8, spend_cents=500)
    await _seed_scrape_history(aid, 8002, datetime.utcnow() - timedelta(days=1))
    await _seed_fan_with_msgs(aid, 8003, in_msgs=8, spend_cents=0)

    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    assert res["deferred_for_scrape"] == 1, res

    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 8001)) is None, "A deferred, not profiled"
        assert await s.get(FanProfile, (aid, 8002)) is not None, "B already scraped → profiled"
        assert await s.get(FanProfile, (aid, 8003)) is not None, "C free → profiled"
        jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.kind == "scrape_chats")
        )).scalars().all()
        assert len(jobs) == 1, jobs
        assert json.loads(jobs[0].payload_json)["fan_ids"] == [8001], jobs[0].payload_json

    rf = await run_once(aid, "gen_info", payload={"force_ids": [8001]})
    assert rf["deferred_for_scrape"] == 0, rf
    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 8001)) is not None, "force profiles A"


async def _scrape_jobs(aid: str) -> list[dict]:
    async with get_session() as s:
        return [json.loads(j.payload_json) for j in (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind.in_(("scrape_chats", "scrape_fan")))
            .order_by(ScheduledJob.id))).scalars().all()]


def _thin(fan_id: int) -> gen_info_plan.Candidate:
    c = gen_info_plan.Candidate(fan_id)
    c.fan_msg_n, c.spend_cents = 2, 5000
    return c


async def case_deferred_row_honors_cooldown_and_only_skips_when_queued():
    import webhook_dispatch as wd
    aid, now = "acc_gi_deferred", datetime.utcnow()
    await _seed_account(aid)
    deferred, claimed, plain, fresh = 8101, 8102, 8103, 8104
    old = now - gen_info._SCRAPE_REFRESH_AGE - timedelta(seconds=1)
    async with get_session() as s:
        for fid, at in ((deferred, old), (claimed, old), (fresh, now)):
            s.add(ScrapeHistory(account_id=aid, fan_id=fid, last_message_id=None,
                                last_scrape_at=at, history_deferred_at=at))
    wd._fan_scrape_claims.clear()
    try:
        await wd.enqueue_fan_scrape(aid, claimed, "blast_reply")
        candidates = [_thin(f) for f in (deferred, claimed, plain, fresh)]
        out = await gen_info._enqueue_thin_fan_scrapes(aid, candidates, set(), now)
        assert out == {deferred, plain}, out
        out = await gen_info._enqueue_thin_fan_scrapes(aid, candidates[:2], set(), now)
        assert out == set(), out
        for _ in range(2):
            await wd.backfill_if_deferred(aid, deferred, 1)
        assert await _scrape_jobs(aid) == [
            {"fan_ids": [claimed], "source": "blast_reply"},
            {"fan_ids": [deferred], "source": "gen_info_pick"},
            {"fan_ids": [plain]},
            {"fan_ids": [deferred], "source": "deferred_history", "after_click_at": "1970-01-01T00:00:00.001000+00:00"},
        ]
    finally:
        wd._fan_scrape_claims.clear()


async def case_gone_deferred_chat_not_reenqueued():
    from automations import scrape_chats
    aid, now = "acc_gi_gone", datetime.utcnow()
    await _seed_account(aid)
    gone = 8201
    async with get_session() as s:
        s.add(ScrapeHistory(account_id=aid, fan_id=gone, last_message_id=None,
                            last_scrape_at=now - timedelta(days=30), history_deferred_at=now))
    await scrape_chats._stamp_scrape_history(aid, gone, gone=True)
    async with get_session() as s:
        row = (await s.execute(select(ScrapeHistory).where(
            ScrapeHistory.account_id == aid, ScrapeHistory.fan_id == gone))).scalar_one()
    assert row.history_deferred_at is None and row.last_scrape_at > now - timedelta(minutes=1), row
    out = await gen_info._enqueue_thin_fan_scrapes(aid, [_thin(gone)], set(), datetime.utcnow())
    assert out == set(), out
    assert await _scrape_jobs(aid) == [], await _scrape_jobs(aid)



async def case_rerun_gate():
    aid, fan = "acc_gi_rerun", 7001
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=10)

    r1 = await run_once(aid, "gen_info", payload={})
    assert r1["generated"] == 1, r1

    r2 = await run_once(aid, "gen_info", payload={})
    assert r2["candidates"] == 1 and r2["skipped_fresh"] == 1, r2
    assert r2["generated"] == 0, r2

    base = datetime(2026, 6, 2, 10, 0, 0)
    async with get_session() as s:
        for i in range(8):
            s.add(Message(account_id=aid, fan_id=fan, message_id=fan * 1000 + 500 + i,
                          direction="in", body=f"<p>more {i}</p>",
                          created_at=base + timedelta(minutes=i)))
    r_small = await run_once(aid, "gen_info", payload={})
    assert r_small["generated"] == 0 and r_small["skipped_fresh"] == 1, r_small

    async with get_session() as s:
        prof = await s.get(FanProfile, (aid, fan))
        prof.last_generated_at = datetime.utcnow() - timedelta(days=8)
    r_aged = await run_once(aid, "gen_info", payload={})
    assert r_aged["generated"] == 1 and r_aged["skipped_fresh"] == 0, r_aged

    r3 = await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    assert r3["generated"] == 1, r3
    assert r3["skipped_fresh"] == 0, r3



async def case_prompt_is_fan_only():
    c = gen_info._Candidate(9999)
    c.of_name = "Bob"
    c.fan_msg_n = 2
    c.messages = [
        ("in", "hey i love hiking and coffee"),
        ("out", "thanks babe, tell me more"),
        ("in", "i work as a nurse in chicago"),
        ("out", "that's so hot"),
    ]

    transcript = gen_info._trim_messages(c.messages)
    assert "CREATOR" not in transcript, transcript
    assert "tell me more" not in transcript, "outbound body leaked"
    assert "that's so hot" not in transcript, "outbound body leaked"
    assert "FAN: hey i love hiking and coffee" in transcript, transcript
    assert "FAN: i work as a nurse in chicago" in transcript, transcript
    assert transcript.count("FAN:") == 2, transcript

    prompt = gen_info._build_user_prompt(c)
    assert "CREATOR" not in prompt, prompt



def case_w2h_helpers():
    assert gen_info._clean_nickname("Derek/Vancouver/??/??/??") == "Derek/Vancouver"
    assert gen_info._clean_nickname("Bob//Toronto//31//Dev") == "Bob/Toronto/31/Dev"
    c = gen_info._Candidate(800000482)
    assert gen_info._guard_name("800000482/,/Obsessed Fan", c) == "Obsessed Fan"
    assert gen_info._guard_name("u1000002/Vancouver", gen_info._Candidate(1000002)) == "Vancouver"
    assert gen_info._guard_name("R342/Vancouver,Canada/8in BWC", c) == "Vancouver,Canada/8in BWC"
    assert gen_info._guard_name("FanB10/,/BIG TIME WASTER", c) == "BIG TIME WASTER"
    real = gen_info._Candidate(5)
    real.of_username = "bob"
    assert gen_info._guard_name("Bob/Toronto", real) == "Bob/Toronto"
    ca = gen_info._Candidate(800000519); ca.known = {"home_country": "Canada"}
    assert gen_info._guard_name("Canada/Canada/office job", ca) == "Canada/office job"
    assert gen_info._guard_name("Hawaii/34/Contractor", ca) == "34/Contractor"
    kel = gen_info._Candidate(6); kel.known = {"home_city": "Kelowna"}
    assert gen_info._guard_name("Kelowna/29/Welder", kel) == "29/Welder"
    assert gen_info._guard_name("Chad/Toronto,Canada/31", ca) == "Chad/Toronto,Canada/31"
    hp = gen_info._Candidate(7); hp.of_name = "Canada"; hp.known = {"home_country": "Canada"}
    assert gen_info._name_hint(hp) == ""
    hk = gen_info._Candidate(8); hk.of_name = "Kelowna"; hk.known = {"home_city": "Kelowna"}
    assert gen_info._name_hint(hk) == ""
    hu = gen_info._Candidate(9); hu.of_name = "Fan_c"
    assert gen_info._name_hint(hu) == ""
    h1 = gen_info._Candidate(1); h1.of_name = "Jeff Trafford"
    assert gen_info._name_hint(h1) == "Jeff"
    h2 = gen_info._Candidate(2); h2.of_name = "R342"
    assert gen_info._name_hint(h2) == ""
    h3 = gen_info._Candidate(3); h3.of_name = "."
    assert gen_info._name_hint(h3) == ""
    h4 = gen_info._Candidate(4); h4.of_name = "Jeff"; h4.known = {"real_name": "Mike"}
    assert gen_info._name_hint(h4) == "Mike"
    h5 = gen_info._Candidate(800000482)
    h5.of_name = "800000482"; h5.of_username = "malakakyria"
    assert gen_info._name_hint(h5) == "Malakakyria"
    h6 = gen_info._Candidate(6); h6.of_name = "mani k"; h6.of_username = "malakakyria"
    assert gen_info._name_hint(h6) == "Mani"
    k = gen_info._Candidate(7)
    k.known = {"real_name": "Alex", "his_age": "31",
               "recent_events": '["new job","trip to NYC"]',
               "generated_nickname": "Alex/NYC/31"}
    blk = gen_info._known_block(k)
    assert "Real name: Alex" in blk, blk
    assert "Recent events: new job; trip to NYC" in blk, blk
    assert "Alex/NYC/31" in blk, blk
    assert gen_info._known_block(gen_info._Candidate(8)) == ""
    C = gen_info._clean_nickname
    assert C("DaddyWilko/Free") == "DaddyWilko"
    assert C("Garrett/Delta,Canada/30/Spender") == "Garrett/Delta,Canada/30"
    assert C("Jim/whale") == "Jim"
    assert C("Spender") == ""
    assert C("Freeman/UK") == "Freeman/UK"
    assert C("Tom/Freetown,Sierra Leone/Freelancer") == "Tom/Freetown,Sierra Leone/Freelancer"
    kt = gen_info._Candidate(9)
    kt.known = {"generated_nickname": "DaddyWilko/Free"}
    assert "Free" not in gen_info._known_block(kt), gen_info._known_block(kt)
    from datetime import datetime as _dt, timedelta as _td
    now = _dt(2026, 6, 5, 12, 0, 0)
    S = gen_info.profile_is_stale
    assert S(None, None, 0, now) is False
    assert S(None, None, 7, now) is False
    assert S(None, None, 8, now) is True
    assert S(10, now, 17, now) is False
    assert S(10, now, 18, now) is False
    assert S(10, now, 98, now) is False
    assert S(10, now, 99, now) is True
    assert S(10, now - _td(days=3), 20, now) is True
    assert S(10, now - _td(days=3), 13, now) is False
    assert S(10, now, 20, now) is False
    assert gen_info._tier_knobs(0, 500, None, now) == gen_info._CADENCE_PAYING
    assert gen_info._tier_knobs(50000, 0, None, now) == gen_info._CADENCE_PAYING
    assert gen_info._tier_knobs(0, 0, now - _td(days=3), now) == gen_info._CADENCE_MIDDLE
    assert gen_info._tier_knobs(100, 0, None, now) == gen_info._CADENCE_MIDDLE
    assert gen_info._tier_knobs(0, 0, now - _td(days=30), now) == gen_info._CADENCE_COLD
    assert gen_info._tier_knobs(0, 0, None, now) == gen_info._CADENCE_COLD
    pay_fresh, pay_cap = gen_info._CADENCE_PAYING
    assert S(10, now, 65, now, fresh_after=pay_fresh, volume_cap=pay_cap) is True
    assert S(10, now, 64, now, fresh_after=pay_fresh, volume_cap=pay_cap) is False



async def case_list_shaped_fields_are_coerced():
    aid, fan = "acc_gi_list", 8101
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=9)

    list_profile = dict(_GROK_PROFILE)
    list_profile["bullet_points"] = ["- Recent: new job", "- Intr: gaming", "- Job: "]
    list_profile["hobbies"] = ["gaming", "hiking"]
    list_profile["fetishes"] = ["feet", "bondage"]

    class _ListClient(_FakeAsyncClient):
        async def post(self, url, headers=None, json=None):  # noqa: A002
            return _FakeResponse({
                "choices": [{"message": {"content": json_dump(list_profile)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            })

    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _ListClient  # type: ignore[attr-defined]
    try:
        res = await run_once(aid, "gen_info", payload={})
    finally:
        llm_client.httpx.AsyncClient = orig

    assert res["status"] == "ok" and res["generated"] == 1 and res["failed"] == 0, res
    async with get_session() as s:
        prof = await s.get(FanProfile, (aid, fan))
        assert prof.bullet_points == "- Recent: new job\n- Intr: gaming", prof.bullet_points
        f = await s.get(Fan, (aid, fan))
        assert f.hobbies == "gaming, hiking", f.hobbies
        assert f.fetishes == "feet, bondage", f.fetishes



async def case_spend_max_and_tier_fallback():
    from datetime import datetime as _dt
    aid, fan = "acc_gi_tier", 8201
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=9, name="Mani", spend_cents=2000)
    async with get_session() as s:
        s.add(Transaction(account_id=aid, fan_id=fan, kind="tip", amount_cents=8000,
                          status="cleared", occurred_at=_dt(2026, 6, 1, 12, 0, 0)))

    bare = dict(_GROK_PROFILE)
    bare["nickname"] = "Mani"

    class _BareClient(_FakeAsyncClient):
        async def post(self, url, headers=None, json=None):  # noqa: A002
            return _FakeResponse({
                "choices": [{"message": {"content": json_dump(bare)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            })

    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _BareClient  # type: ignore[attr-defined]
    try:
        res = await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    finally:
        llm_client.httpx.AsyncClient = orig

    assert res["generated"] == 1, res
    async with get_session() as s:
        prof = await s.get(FanProfile, (aid, fan))
        assert prof.total_spend_at_gen_cents == 8000, prof.total_spend_at_gen_cents
        assert prof.nickname == "Mani", prof.nickname



async def _add_inbound(aid: str, fan_id: int, n: int) -> None:
    base = datetime(2026, 6, 3, 10, 0, 0)
    async with get_session() as s:
        for i in range(n):
            s.add(Message(account_id=aid, fan_id=fan_id, message_id=fan_id * 1000 + 700 + i,
                          direction="in", body=f"<p>new {i}</p>",
                          created_at=base + timedelta(minutes=i)))


async def case_lineless_profile_not_reprofiled():
    aid, fan = "acc_gi_lineless", 8401
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=9)
    r1 = await run_once(aid, "gen_info", payload={})
    assert r1["generated"] == 1, r1

    await _add_inbound(aid, fan, 1)

    for payload in ({}, {"refill_ids": [fan]}):
        res = await run_once(aid, "gen_info", payload=payload)
        assert res["candidates"] == 1, (payload, res)
        assert res["skipped_fresh"] == 1, (payload, res)
        assert res["attempted"] == 0 and res["generated"] == 0, (payload, res)
    async with get_session() as s:
        calls = (await s.execute(
            select(GrokCall).where(GrokCall.account_id == aid,
                                   GrokCall.purpose == "gen_info")
        )).scalars().all()
        assert len(calls) == 1, f"no second LLM call, got {len(calls)}"


async def case_stored_lines_left_alone():
    aid, fan = "acc_gi_oldlines", 8402
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=9)
    async with get_session() as s:
        s.add(FanProfile(account_id=aid, fan_id=fan, q1="old question?", q2=None,
                         q3=None, tease1="old tease", message_count_at_gen=0))

    res = await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    assert res["generated"] == 1, res
    async with get_session() as s:
        p = await s.get(FanProfile, (aid, fan))
        assert (p.q1, p.q2, p.tease1, p.tease2) == ("old question?", None, "old tease", None), \
            (p.q1, p.q2, p.tease1, p.tease2)
        assert p.nickname == "Bob/Toronto/31/Dev", p.nickname



async def case_rule_schedules_gen_info():
    aid, fan = "acc_gi_rule", 8001
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=8)
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="periodic gen_info", kind="gen_info",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({}),
            is_enabled=True,
        ))

    n = await ax._materialize_due_rules()
    assert n >= 1, f"rule materialized a job, got {n}"

    async with get_session() as s:
        job = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == "gen_info")
        )).scalar_one()
        assert job.status == "pending", job.status

    await ax._drain_due_jobs_once()
    await ax._join_inflight_runs()
    async with get_session() as s:
        prof = await s.get(FanProfile, (aid, fan))
        assert prof is not None, "scheduled gen_info produced a profile"
        job = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == "gen_info")
        )).scalar_one()
        assert job.status == "done", job.status


async def case_peer_creator_not_profiled():
    aid = "acc_gi_spam"
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, 9001, in_msgs=8)
    await _seed_fan_with_msgs(aid, 9002, in_msgs=8, spend_cents=50)
    await _seed_fan_with_msgs(aid, 9003, in_msgs=8)
    async with get_session() as s:
        (await s.get(Fan, (aid, 9001))).source = "creator_we_follow"
        (await s.get(Fan, (aid, 9002))).source = "creator_we_follow"
        (await s.get(Fan, (aid, 9003))).source = "onlyfans"
        s.add(Message(account_id=aid, fan_id=9001, message_id=9001 * 1000 + 777,
                      direction="in", created_at=datetime(2026, 6, 1, 9, 0, 0),
                      body='<p><strong>FLASH SALE!!</strong> onlyfans.com/promo</p>'))

    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 9001)) is None, "peer creator must be skipped"
        assert await s.get(FanProfile, (aid, 9002)) is not None, "paying collab profiled"
        assert await s.get(FanProfile, (aid, 9003)) is not None, "real fan (onlyfans) profiled"

    res2 = await run_once(aid, "gen_info", payload={"force_ids": [9001]})
    assert res2["status"] == "ok", res2
    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 9001)) is not None, "force_ids overrides spam guard"


async def case_labelled_fan_without_promo_profiled():
    aid = "acc_gi_labelled"
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, 9101, in_msgs=8)
    async with get_session() as s:
        (await s.get(Fan, (aid, 9101))).source = "creator_we_follow"

    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 9101)) is not None, \
            "no promo evidence ⇒ a real fan, must be profiled"


async def case_lagging_spend_column_rescues_payer():
    aid = "acc_gi_lag"
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, 9201, in_msgs=8, spend_cents=50)
    async with get_session() as s:
        f = await s.get(Fan, (aid, 9201))
        f.source = "creator_we_follow"
        f.lifetime_spend_cents = 0
        s.add(Message(account_id=aid, fan_id=9201, message_id=9201 * 1000 + 777,
                      direction="in", created_at=datetime(2026, 6, 1, 9, 0, 0),
                      body='<p><strong>FLASH SALE!!</strong> onlyfans.com/promo</p>'))

    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 9201)) is not None, \
            "a payer the spend column hasn't caught up on must NOT be gated as spam"


async def case_muted_creator_not_profiled():
    aid = "acc_gi_muted"
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, 9101, in_msgs=8, spend_cents=50)
    await _seed_fan_with_msgs(aid, 9102, in_msgs=8, spend_cents=50)
    async with get_session() as s:
        a = await s.get(Fan, (aid, 9101)); a.source = "creator_we_follow"; a.is_muted = True
        b = await s.get(Fan, (aid, 9102)); b.source = "creator_we_follow"

    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 9101)) is None, "muted creator must be skipped"
        assert await s.get(FanProfile, (aid, 9102)) is not None, "unmuted paying collab profiled"

    res2 = await run_once(aid, "gen_info", payload={"force_ids": [9101]})
    assert res2["status"] == "ok", res2
    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 9101)) is not None, "force_ids overrides muted guard"


_EXPECTED_NOTE = ("Intr: gaming, coffee\nJob: Software Dev\nRel: single\n"
                  "31yo dev from Toronto who tips often")


async def case_of_nickname_resynced():
    aid, fan = "acc_gi_ofsync", 7700
    _install_fake_llm()
    fake = _use_fake_of()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=9)

    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    assert res["generated"] == 1, res

    expected = "Bob/Toronto,Canada/31/Software Dev"
    assert fake.nicks == [(fan, expected)], fake.nicks

    assert fake.notes == [(fan, _EXPECTED_NOTE)], fake.notes

    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.custom_nickname == expected, f.custom_nickname
        assert f.notes == _EXPECTED_NOTE, f.notes
        assert f.applied_notes == _EXPECTED_NOTE, f.applied_notes

    fake.nicks.clear()
    fake.notes.clear()
    res2 = await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    assert res2["status"] == "ok", res2
    assert fake.nicks == [(fan, expected)], fake.nicks
    assert fake.notes == [], fake.notes


async def case_hand_typed_note_kept():
    aid, fan = "acc_gi_handnote", 7701
    _install_fake_llm()
    fake = _use_fake_of()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=9)
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        f.notes = "VIP, call him Bobby"

    res = await run_once(aid, "gen_info", payload={})
    assert res["generated"] == 1, res
    assert fake.nicks == [(fan, "Bob/Toronto,Canada/31/Software Dev")], fake.nicks
    assert fake.notes == [], fake.notes
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.notes == "VIP, call him Bobby", f.notes
        f.notes = None

    res = await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    assert res["generated"] == 1, res
    assert fake.notes == [(fan, _EXPECTED_NOTE)], fake.notes



def case_select_candidates_table():
    def C(fid, msgs=0, spend=0, source="", muted=False):
        c = gen_info._Candidate(fid)
        c.fan_msg_n, c.spend_cents, c.source, c.is_muted = msgs, spend, source, muted
        return c

    mc = {"source": "creator_we_follow", "muted": True}
    rows = [
        ("empty", [], set(), 10, set(), []),
        ("below both gates dropped", [(1, 0, 0, {})], set(), 10, set(), []),
        ("one msg qualifies", [(1, 1, 0, {})], set(), 10, set(), [1]),
        ("spend alone qualifies", [(1, 0, 1, {})], set(), 10, set(), [1]),
        ("forced passes gate", [(1, 0, 0, {})], {1}, 10, set(), [1]),
        ("muted creator dropped", [(1, 5, 900, mc)], set(), 10, set(), []),
        ("muted creator forced kept", [(1, 5, 900, mc)], {1}, 10, set(), [1]),
        ("muted but not creator kept", [(1, 5, 0, {"muted": True})], set(), 10, set(), [1]),
        ("promo $0 dropped", [(1, 5, 0, {})], set(), 10, {1}, []),
        ("promo payer rescued", [(1, 5, 100, {})], set(), 10, {1}, [1]),
        ("promo $0 forced kept", [(1, 5, 0, {})], {1}, 10, {1}, [1]),
        ("spend desc then msgs desc then id",
         [(3, 2, 0, {}), (1, 9, 0, {}), (2, 1, 500, {}), (4, 9, 0, {})], set(), 10, set(),
         [2, 1, 4, 3]),
        ("limit caps", [(1, 1, 300, {}), (2, 1, 200, {}), (3, 1, 100, {})], set(), 2, set(),
         [1, 2]),
        ("forced first survives limit",
         [(1, 1, 300, {}), (2, 1, 200, {}), (3, 1, 0, {})], {3}, 1, set(), [3]),
        ("limit grows to #forced",
         [(1, 1, 300, {}), (2, 0, 0, {}), (3, 0, 0, {})], {2, 3}, 1, set(), [2, 3]),
    ]
    for name, specs, force, limit, promo, want in rows:
        counts = {fid: C(fid, m, sp, **kw) for fid, m, sp, kw in specs}
        got = gen_info.select_candidates(
            counts, force_ids=force, limit=limit, promo_spam=promo)
        assert [c.fan_id for c in got] == want, (name, [c.fan_id for c in got], want)


_harness.run(
    case_gen_info_acceptance,
    case_of_nickname_resynced,
    case_hand_typed_note_kept,
    case_qualification_gate,
    case_peer_creator_not_profiled,
    case_labelled_fan_without_promo_profiled,
    case_lagging_spend_column_rescues_payer,
    case_muted_creator_not_profiled,
    case_thin_paying_fan_autoscraped,
    case_deferred_row_honors_cooldown_and_only_skips_when_queued,
    case_gone_deferred_chat_not_reenqueued,
    case_rerun_gate,
    case_prompt_is_fan_only,
    case_w2h_helpers,
    case_select_candidates_table,
    case_list_shaped_fields_are_coerced,
    case_spend_max_and_tier_fallback,
    case_lineless_profile_not_reprofiled,
    case_stored_lines_left_alone,
    case_rule_schedules_gen_info,
)
