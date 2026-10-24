#!/usr/bin/env python3
"""
A02 — gen_info automation tests (library/one_section_of_automations/02_gen_info.md).

Acceptance (the 🔴 carry): a fan with messages gets a `fan_profiles` row
populated AND a `grok_calls` row recorded.

  case_gen_info_acceptance:
      a qualifying fan (>=7 inbound msgs) → run_once("gen_info") → fan_profiles
      row (nickname/bio/original_name, and NO Q/Tease lines: the prompt asks for
      none and any the model volunteers are dropped) + extracted facts on the fans
      row + a grok_calls audit row (provider/status=done) + an ok automation_runs row.
  case_of_nickname_resynced / case_hand_typed_note_kept:
      after a regen gen_info pushes the drawer's Nickname (OF displayName) and Fan
      notes (OF notice, the 200-char fact sheet); a note a chatter typed is kept.
  case_lineless_profile_not_reprofiled / case_stored_lines_left_alone:
      no lines-based regen exemption any more; old stored lines are untouched.
  case_qualification_gate:
      a fan below BOTH gates (few msgs, no spend) is not processed; a fan that
      clears the spend gate ($1) is.
  case_rerun_gate:
      a second run on an unchanged fan is skipped (count didn't grow 22%); a
      forced id is regenerated regardless.
  case_rule_schedules_gen_info:
      an automation_rules row (kind=gen_info, every_seconds) materializes a job
      that run_once consumes — scheduling needs NO executor edit.

The LLM HTTP call is faked at the httpx layer (no network, no real key spend), so
llm_client still writes its real grok_calls audit row exactly as in prod.

Run: ./venv/bin/python service/tests/test_gen_info.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import llm_client  # noqa: E402
import automation_executor as ax  # noqa: E402,F401 — registers scrape_chats + plugin loader
from automation_executor import enqueue_job, run_once  # noqa: E402
from automations import gen_info  # noqa: E402
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

# The canned Grok JSON every faked call returns.
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
    """Drop-in for httpx.AsyncClient — returns a canned chat-completions body."""

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


_LLM_REQUESTS: list[dict] = []   # every faked chat-completions body, in order


def _system_prompt_of(req: dict) -> str:
    return next(m["content"] for m in req["messages"] if m["role"] == "system")


def json_dump(obj) -> str:
    return json.dumps(obj)


def _install_fake_llm() -> None:
    llm_client.httpx.AsyncClient = _FakeAsyncClient  # type: ignore[attr-defined]


class _FakeOF:
    """Captures the structured-nickname re-push gen_info now does at profile time."""

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
    """Create a fans row + `in_msgs` inbound messages (and one paid outbound if
    spend_cents>0) so the fan clears the qualification gate."""
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


# ── 🔴 Acceptance ────────────────────────────────────────────────────

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

    # No Q&A: the prompt never asks for the opener lines…
    assert len(_LLM_REQUESTS) == 1, _LLM_REQUESTS
    system = _system_prompt_of(_LLM_REQUESTS[0])
    for key in ("Q1", "Q2", "Q3", "Tease1", "Tease2", "Tease3"):
        assert f'"{key}"' not in system, key
    assert '"nickname"' in system and '"occupation"' in system, system

    async with get_session() as s:
        prof = await s.get(FanProfile, (aid, fan))
        assert prof is not None, "fan_profiles row written"
        assert prof.nickname == "Bob/Toronto/31/Dev", prof.nickname  # // collapsed
        assert prof.short_bio and "dev" in prof.short_bio.lower(), prof.short_bio
        # …and the ones the fake model volunteers anyway are never stored.
        lines = (prof.q1, prof.q2, prof.q3, prof.tease1, prof.tease2, prof.tease3)
        assert lines == (None,) * 6, lines
        assert prof.original_name == "Bob", prof.original_name
        assert prof.message_count_at_gen == 9, prof.message_count_at_gen
        assert prof.generated_by_grok_call_id is not None, "links to grok_calls"

        # Extracted facts written back onto the fans row.
        f = await s.get(Fan, (aid, fan))
        assert f.his_age == "31" and f.home_city == "Toronto", (f.his_age, f.home_city)
        assert f.occupation == "Software Dev", f.occupation
        assert f.generated_nickname == "Bob/Toronto/31/Dev", f.generated_nickname
        assert f.grok_facts_updated_at is not None, "grok_facts_updated_at stamped"

        # grok_calls audit row recorded by llm_client.
        calls = (await s.execute(
            select(GrokCall).where(GrokCall.account_id == aid,
                                   GrokCall.purpose == "gen_info")
        )).scalars().all()
        assert len(calls) == 1, f"one grok_calls row, got {len(calls)}"
        assert calls[0].status == "done", calls[0].status
        assert calls[0].fan_id == fan, calls[0].fan_id
        assert calls[0].id == prof.generated_by_grok_call_id, "profile↔call link"

        # automation_runs row ok with stats.
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid,
                                        AutomationRun.kind == "gen_info")
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "ok", runs
        stats = json.loads(runs[0].stats_json)
        assert stats["generated"] == 1, stats


# ── Qualification gate ───────────────────────────────────────────────

async def _seed_scrape_history(aid: str, fan_id: int, when: datetime) -> None:
    """Mark a fan as already deep-scraped at `when` so the auto-scrape guard treats
    its thin history as genuine (OF really has little) and profiles it normally."""
    async with get_session() as s:
        s.add(ScrapeHistory(account_id=aid, fan_id=fan_id, last_message_id=1,
                            last_scrape_at=when))


async def case_qualification_gate():
    """Candidate selection still ignores spend (≥1 msg OR any spend qualifies), but the
    ≥8-new-message FLOOR decides whether we actually compile: a fan with ≥8 inbound is
    profiled; a thin <8-message fan is a candidate that's skipped_fresh (no LLM call)
    until they talk more — no fresh chat ⇒ nothing to mine."""
    aid = "acc_gi_qual"
    _install_fake_llm()
    await _seed_account(aid)
    # 8 inbound, no spend → crosses the floor → profiled (spend doesn't gate).
    await _seed_fan_with_msgs(aid, 6002, in_msgs=8)
    # 1 inbound only → qualifies as a candidate but is below the 8 floor → skipped.
    await _seed_fan_with_msgs(aid, 6004, in_msgs=1)

    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    assert res["candidates"] == 2, res          # both qualify as candidates
    assert res["deferred_for_scrape"] == 0, res
    assert res["generated"] == 1, res           # only the ≥8-msg fan compiles
    assert res["skipped_fresh"] == 1, res        # the thin fan is gated, not profiled

    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 6002)) is not None, "8-msg fan profiled"
        assert await s.get(FanProfile, (aid, 6004)) is None, "1-msg fan below the floor"


async def case_thin_paying_fan_autoscraped():
    """Prevention (the Alex Nielsen case): a PAYING fan with thin local history is a
    fan we never deep-scraped — defer profiling and enqueue a one-fan scrape_chats so
    the next pass profiles on the real transcript. A free thin fan and an
    already-scraped thin fan are profiled normally; a force bypasses the defer."""
    aid = "acc_gi_thin"
    _install_fake_llm()
    await _seed_account(aid)
    # A: thin (5 msgs) + paying ($5) + NEVER scraped → deferred + scrape enqueued.
    await _seed_fan_with_msgs(aid, 8001, in_msgs=5, spend_cents=500)
    # B: thin (8 msgs, still <30) + paying but ALREADY scraped recently → profiled
    # (OF genuinely has little). Date is relative so the scrape stays within
    # _SCRAPE_REFRESH_AGE regardless of the wall clock.
    await _seed_fan_with_msgs(aid, 8002, in_msgs=8, spend_cents=500)
    await _seed_scrape_history(aid, 8002, datetime.utcnow() - timedelta(days=1))
    # C: thin (8 msgs) but FREE (no spend) → guard ignores it, profiled normally.
    await _seed_fan_with_msgs(aid, 8003, in_msgs=8, spend_cents=0)

    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    assert res["deferred_for_scrape"] == 1, res

    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 8001)) is None, "A deferred, not profiled"
        assert await s.get(FanProfile, (aid, 8002)) is not None, "B already scraped → profiled"
        assert await s.get(FanProfile, (aid, 8003)) is not None, "C free → profiled"
        # A one-fan scrape_chats job was enqueued for exactly fan A.
        jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.kind == "scrape_chats")
        )).scalars().all()
        assert len(jobs) == 1, jobs
        assert json.loads(jobs[0].payload_json)["fan_ids"] == [8001], jobs[0].payload_json

    # A force bypasses the defer — an explicit force profiles A now, thin history and all.
    rf = await run_once(aid, "gen_info", payload={"force_ids": [8001]})
    assert rf["deferred_for_scrape"] == 0, rf
    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 8001)) is not None, "force profiles A"


# ── Re-run gate + force_ids bypass ───────────────────────────────────

async def case_rerun_gate():
    """Re-run gate: needs ≥8 new inbound messages, THEN a spend-tiered time window or
    volume cap. A small recent jump no longer regenerates on its own (the old Fibonacci
    cross is gone); an aged profile with ≥8 new does; force bypasses everything."""
    aid, fan = "acc_gi_rerun", 7001
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=10)

    r1 = await run_once(aid, "gen_info", payload={})
    assert r1["generated"] == 1, r1

    # No new messages → gate skips it.
    r2 = await run_once(aid, "gen_info", payload={})
    assert r2["candidates"] == 1 and r2["skipped_fresh"] == 1, r2
    assert r2["generated"] == 0, r2

    # Grow 10 → 18 (8 new) but the profile is fresh and far under the volume cap →
    # still skipped: a small recent jump no longer forces a regen.
    base = datetime(2026, 6, 2, 10, 0, 0)
    async with get_session() as s:
        for i in range(8):
            s.add(Message(account_id=aid, fan_id=fan, message_id=fan * 1000 + 500 + i,
                          direction="in", body=f"<p>more {i}</p>",
                          created_at=base + timedelta(minutes=i)))
    r_small = await run_once(aid, "gen_info", payload={})
    assert r_small["generated"] == 0 and r_small["skipped_fresh"] == 1, r_small

    # Age the profile past the (cold-tier) time window → the 8 new now regenerate it.
    async with get_session() as s:
        prof = await s.get(FanProfile, (aid, fan))
        prof.last_generated_at = datetime.utcnow() - timedelta(days=8)
    r_aged = await run_once(aid, "gen_info", payload={})
    assert r_aged["generated"] == 1 and r_aged["skipped_fresh"] == 0, r_aged

    # force_ids bypasses the gate even when not stale.
    r3 = await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    assert r3["generated"] == 1, r3
    assert r3["skipped_fresh"] == 0, r3


# ── Prompt is fan-only (W1a: drop CREATOR lines) ─────────────────────

async def case_prompt_is_fan_only():
    """The transcript fed to the LLM must contain only the fan's inbound lines —
    V1 produced sharper profiles from FAN-only history (W1a fix)."""
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

    # Same guarantee end-to-end through the user prompt builder.
    prompt = gen_info._build_user_prompt(c)
    assert "CREATOR" not in prompt, prompt


# ── W2h: nickname guard + '??' cleaning + ground-truth block ─────────

def case_w2h_helpers():
    # '??' + empty placeholder segments are dropped; real segments kept.
    assert gen_info._clean_nickname("Derek/Vancouver/??/??/??") == "Derek/Vancouver"
    assert gen_info._clean_nickname("Bob//Toronto//31//Dev") == "Bob/Toronto/31/Dev"
    # Name guard blanks any name with a digit (number / u<id> / handle), keeps real
    # plain-letter names.
    c = gen_info._Candidate(800000482)
    assert gen_info._guard_name("800000482/,/Obsessed Fan", c) == "Obsessed Fan"
    assert gen_info._guard_name("u1000002/Vancouver", gen_info._Candidate(1000002)) == "Vancouver"
    assert gen_info._guard_name("R342/Vancouver,Canada/8in BWC", c) == "Vancouver,Canada/8in BWC"
    assert gen_info._guard_name("FanB10/,/BIG TIME WASTER", c) == "BIG TIME WASTER"
    real = gen_info._Candidate(5)
    real.of_username = "bob"            # username == real name must NOT trip the guard
    assert gen_info._guard_name("Bob/Toronto", real) == "Bob/Toronto"
    # A PLACE is not a name either: with no name to find, the model writes the
    # country into the Name slot ("Canada/Canada/office job" on 132 prod fans).
    ca = gen_info._Candidate(800000519); ca.known = {"home_country": "Canada"}
    assert gen_info._guard_name("Canada/Canada/office job", ca) == "Canada/office job"
    assert gen_info._guard_name("Hawaii/34/Contractor", ca) == "34/Contractor"
    # His OWN city, which no static list can hold, is dropped the same way ...
    kel = gen_info._Candidate(6); kel.known = {"home_city": "Kelowna"}
    assert gen_info._guard_name("Kelowna/29/Welder", kel) == "29/Welder"
    # ... while a place that is also a real first name survives for everyone else.
    assert gen_info._guard_name("Chad/Toronto,Canada/31", ca) == "Chad/Toronto,Canada/31"
    # _name_hint runs AFTER the guard and re-prepends what it finds, so it must use
    # the same predicate — otherwise a fan whose OF display name is 'Canada' gets
    # 'Canada' re-installed as his name one line after the guard dropped it.
    hp = gen_info._Candidate(7); hp.of_name = "Canada"; hp.known = {"home_country": "Canada"}
    assert gen_info._name_hint(hp) == ""
    hk = gen_info._Candidate(8); hk.of_name = "Kelowna"; hk.known = {"home_city": "Kelowna"}
    assert gen_info._name_hint(hk) == ""
    hu = gen_info._Candidate(9); hu.of_name = "Fan_c"   # handle, not a name
    assert gen_info._name_hint(hu) == ""
    # _name_hint: real chat name first, else OF display name; handles/junk skipped.
    h1 = gen_info._Candidate(1); h1.of_name = "Jeff Trafford"
    assert gen_info._name_hint(h1) == "Jeff"
    h2 = gen_info._Candidate(2); h2.of_name = "R342"          # handle → no hint
    assert gen_info._name_hint(h2) == ""
    h3 = gen_info._Candidate(3); h3.of_name = "."             # junk → no hint
    assert gen_info._name_hint(h3) == ""
    h4 = gen_info._Candidate(4); h4.of_name = "Jeff"; h4.known = {"real_name": "Mike"}
    assert gen_info._name_hint(h4) == "Mike"                  # chat real_name wins
    # Numeric display name but a real-word USERNAME → use the username, never the
    # number (id 800000482 / name "mani k" → "Mani"; here name is the bare id).
    h5 = gen_info._Candidate(800000482)
    h5.of_name = "800000482"; h5.of_username = "malakakyria"
    assert gen_info._name_hint(h5) == "Malakakyria"
    h6 = gen_info._Candidate(6); h6.of_name = "mani k"; h6.of_username = "malakakyria"
    assert gen_info._name_hint(h6) == "Mani"                  # display name wins over username
    # KNOWN-INFO block reflects prior facts + parses the recent_events JSON array.
    k = gen_info._Candidate(7)
    k.known = {"real_name": "Alex", "his_age": "31",
               "recent_events": '["new job","trip to NYC"]',
               "generated_nickname": "Alex/NYC/31"}
    blk = gen_info._known_block(k)
    assert "Real name: Alex" in blk, blk
    assert "Recent events: new job; trip to NYC" in blk, blk
    assert "Alex/NYC/31" in blk, blk
    assert gen_info._known_block(gen_info._Candidate(8)) == ""   # nothing known → no block
    # The spend tier is RETIRED as a nickname slot: _clean_nickname strips it on the
    # way in as well as out, which is what stops _known_block handing a stale '/Free'
    # back to the model as ground truth to "keep complete".
    C = gen_info._clean_nickname
    assert C("DaddyWilko/Free") == "DaddyWilko"
    assert C("Garrett/Delta,Canada/30/Spender") == "Garrett/Delta,Canada/30"
    assert C("Jim/whale") == "Jim"                 # case-insensitive
    assert C("Spender") == ""                      # tier-only label carries nothing
    # Segment-exact, never a substring — real names/jobs/cities that merely CONTAIN
    # a tier word survive untouched.
    assert C("Freeman/UK") == "Freeman/UK"
    assert C("Tom/Freetown,Sierra Leone/Freelancer") == "Tom/Freetown,Sierra Leone/Freelancer"
    # The KNOWN-INFO block is the read path that used to re-assert the tier forever.
    kt = gen_info._Candidate(9)
    kt.known = {"generated_nickname": "DaddyWilko/Free"}
    assert "Free" not in gen_info._known_block(kt), gen_info._known_block(kt)
    from datetime import datetime as _dt, timedelta as _td
    now = _dt(2026, 6, 5, 12, 0, 0)
    S = gen_info.profile_is_stale
    # HARD GATE — fewer than _MIN_NEW_MSGS (8) new inbound msgs ⇒ never (re)compile.
    assert S(None, None, 0, now) is False      # never profiled, 0 msgs
    assert S(None, None, 7, now) is False       # never profiled, <8 total
    assert S(None, None, 8, now) is True        # never profiled, hits the 8 floor
    assert S(10, now, 17, now) is False         # only 7 new → gated
    assert S(10, now, 18, now) is False         # 8 new but fresh & under cap → still no
    # Volume cap (MIDDLE default = 89 new msgs) fires regardless of time:
    assert S(10, now, 98, now) is False         # 88 new < cap
    assert S(10, now, 99, now) is True          # 89 new ≥ cap
    # Time window (MIDDLE default = 2 days), but only once ≥8 new have arrived:
    assert S(10, now - _td(days=3), 20, now) is True   # 2d+ old AND 10 new
    assert S(10, now - _td(days=3), 13, now) is False  # old but only 3 new → gated
    assert S(10, now, 20, now) is False                # 10 new, fresh, under cap
    # Spend tiers: paying (recent spend OR ≥$500 lifetime) → tighter; lapsed/new → middle.
    assert gen_info._tier_knobs(0, 500, None, now) == gen_info._CADENCE_PAYING       # recent spend
    assert gen_info._tier_knobs(50000, 0, None, now) == gen_info._CADENCE_PAYING     # whale floor
    assert gen_info._tier_knobs(0, 0, now - _td(days=3), now) == gen_info._CADENCE_MIDDLE  # new sub
    assert gen_info._tier_knobs(100, 0, None, now) == gen_info._CADENCE_MIDDLE       # lapsed payer
    assert gen_info._tier_knobs(0, 0, now - _td(days=30), now) == gen_info._CADENCE_COLD  # $0, old sub
    assert gen_info._tier_knobs(0, 0, None, now) == gen_info._CADENCE_COLD           # $0, no sub
    # Paying tier's tighter 55-cap fires where the middle 89-cap would not:
    pay_fresh, pay_cap = gen_info._CADENCE_PAYING
    assert S(10, now, 65, now, fresh_after=pay_fresh, volume_cap=pay_cap) is True    # 55 new ≥ 55
    assert S(10, now, 64, now, fresh_after=pay_fresh, volume_cap=pay_cap) is False   # 54 new < 55


# ── Model returns list-shaped fields → coerced to TEXT (no DB bind crash) ──

async def case_list_shaped_fields_are_coerced():
    """The improved bullet_points prompt makes the model often return bullet_points
    (and sometimes hobbies/fetishes) as a JSON ARRAY. A list must never reach the
    TEXT/VARCHAR column (sqlite 'type list is not supported'): bullet_points joins
    with newlines, list facts join with commas. Regression for the 19/22 failure."""
    aid, fan = "acc_gi_list", 8101
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=9)

    list_profile = dict(_GROK_PROFILE)
    # bullet_points as a JSON array, incl. an EMPTY "- Job: " line that must be dropped.
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
        # The empty "- Job: " line is dropped; arrays joined to text.
        assert prof.bullet_points == "- Recent: new job\n- Intr: gaming", prof.bullet_points
        f = await s.get(Fan, (aid, fan))
        assert f.hobbies == "gaming, hiking", f.hobbies
        assert f.fetishes == "feet, bondage", f.fetishes


# ── Spend = max(transactions, messages); bare nickname STAYS bare ────

async def case_spend_max_and_tier_fallback():
    """Lifetime spend takes the HIGHER of the transactions ledger vs the
    message-derived PPV sum — and a name-only nickname now STAYS name-only ("Mani",
    not "Mani/Spender"). Spend is still measured and still recorded on the profile;
    it just no longer gets frozen into the label a human reads days later."""
    from datetime import datetime as _dt
    aid, fan = "acc_gi_tier", 8201
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=9, name="Mani", spend_cents=2000)  # $20 via msgs
    # A bigger CLEARED transaction ($80) → the higher source wins → Spender tier.
    async with get_session() as s:
        s.add(Transaction(account_id=aid, fan_id=fan, kind="tip", amount_cents=8000,
                          status="cleared", occurred_at=_dt(2026, 6, 1, 12, 0, 0)))

    # Model returns just a bare first name — no city/age/job/bonus.
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
        # max($20 msgs, $80 tx) = $80 — still MEASURED and recorded on the profile…
        assert prof.total_spend_at_gen_cents == 8000, prof.total_spend_at_gen_cents
        # …and no longer stamped onto the label. This is the regression guard: the
        # $80 that used to read "Spender" here is exactly the figure that goes stale.
        assert prof.nickname == "Mani", prof.nickname


# ── No lines: no lines-based regen, old lines left alone ─────────────

async def _add_inbound(aid: str, fan_id: int, n: int) -> None:
    base = datetime(2026, 6, 3, 10, 0, 0)
    async with get_session() as s:
        for i in range(n):
            s.add(Message(account_id=aid, fan_id=fan_id, message_id=fan_id * 1000 + 700 + i,
                          direction="in", body=f"<p>new {i}</p>",
                          created_at=base + timedelta(minutes=i)))


async def case_lineless_profile_not_reprofiled():
    """A profile with no Q/Tease lines (every profile now) plus one new inbound is NOT
    regenerated: the old "lines ran out" exemption is gone, so the hard gate (8 new
    messages) holds and no LLM call is spent. Under the exemption this fan would be
    re-profiled on every new message, for ever."""
    aid, fan = "acc_gi_lineless", 8401
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=9)
    r1 = await run_once(aid, "gen_info", payload={})
    assert r1["generated"] == 1, r1

    await _add_inbound(aid, fan, 1)         # 9 → 10 inbound, well under the gate

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
    """Lines stored before gen_info stopped writing them survive a regen untouched,
    even though the model's reply carries different Q/Tease values."""
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
        assert p.nickname == "Bob/Toronto/31/Dev", p.nickname   # the profile did refresh


# ── Scheduling via automation_rules (no executor edit) ───────────────

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

    # The supervisor tick consumes it end-to-end.
    await ax._drain_due_jobs_once()
    await ax._join_inflight_runs()  # non-blocking drain spawns tasks
    async with get_session() as s:
        prof = await s.get(FanProfile, (aid, fan))
        assert prof is not None, "scheduled gen_info produced a profile"
        job = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == "gen_info")
        )).scalar_one()
        assert job.status == "done", job.status


async def case_peer_creator_not_profiled():
    """Promo-spam guard: a peer creator who has ACTUALLY blasted promo is NOT
    profiled — no wasted LLM. A PAYING one still is (spend umbrella), and a real fan
    on a non-"fan" source (onlyfans) is profiled normally. The creator_we_follow flag
    ALONE is not enough — see case_labelled_fan_without_promo_profiled."""
    aid = "acc_gi_spam"
    _install_fake_llm()
    await _seed_account(aid)
    # A: peer creator, $0, with real promo on the wire → skipped (not a candidate).
    await _seed_fan_with_msgs(aid, 9001, in_msgs=8)
    # B: peer creator but PAID $0.50 → profiled via spend umbrella.
    await _seed_fan_with_msgs(aid, 9002, in_msgs=8, spend_cents=50)
    # C: real fan on a non-"fan" source, $0 → profiled (not creator_we_follow).
    await _seed_fan_with_msgs(aid, 9003, in_msgs=8)
    async with get_session() as s:
        (await s.get(Fan, (aid, 9001))).source = "creator_we_follow"
        (await s.get(Fan, (aid, 9002))).source = "creator_we_follow"
        (await s.get(Fan, (aid, 9003))).source = "onlyfans"
        # A's promo evidence: OF rich-text editor spans, how a blast really arrives.
        s.add(Message(account_id=aid, fan_id=9001, message_id=9001 * 1000 + 777,
                      direction="in", created_at=datetime(2026, 6, 1, 9, 0, 0),
                      body='<p><strong>FLASH SALE!!</strong> onlyfans.com/promo</p>'))

    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 9001)) is None, "peer creator must be skipped"
        assert await s.get(FanProfile, (aid, 9002)) is not None, "paying collab profiled"
        assert await s.get(FanProfile, (aid, 9003)) is not None, "real fan (onlyfans) profiled"

    # force_ids overrides the guard.
    res2 = await run_once(aid, "gen_info", payload={"force_ids": [9001]})
    assert res2["status"] == "ok", res2
    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 9001)) is not None, "force_ids overrides spam guard"


async def case_labelled_fan_without_promo_profiled():
    """REGRESSION (2026-07-24): a $0 fan carrying OF's creator_we_follow flag who
    never blasted promo must still be PROFILED. The flag only means we're subscribed
    to them — true of any fan a free page followed back — and treating it as proof
    quietly stopped profiling 71 real fans on a live account."""
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
    """The promo-blaster SET reads `fans.lifetime_spend_cents`, which LAGS ingest.
    A fan who HAS paid (message-derived spend this pass can see) but whose column
    still says $0 lands in that set — and must still be profiled. The spam gate has
    to fail toward profiling, never toward silencing a payer."""
    aid = "acc_gi_lag"
    _install_fake_llm()
    await _seed_account(aid)
    # spend_cents>0 seeds a PAID outbound (→ c.spend_cents) but never touches
    # fans.lifetime_spend_cents — exactly the ingest-lag shape. Kept at/below
    # _THIN_HISTORY_MIN_SPEND_CENTS so the auto-scrape deferral isn't what we
    # end up measuring.
    await _seed_fan_with_msgs(aid, 9201, in_msgs=8, spend_cents=50)
    async with get_session() as s:
        f = await s.get(Fan, (aid, 9201))
        f.source = "creator_we_follow"
        f.lifetime_spend_cents = 0          # the lagging column
        # …and he DID blast promo, so the SQL set will contain him.
        s.add(Message(account_id=aid, fan_id=9201, message_id=9201 * 1000 + 777,
                      direction="in", created_at=datetime(2026, 6, 1, 9, 0, 0),
                      body='<p><strong>FLASH SALE!!</strong> onlyfans.com/promo</p>'))

    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 9201)) is not None, \
            "a payer the spend column hasn't caught up on must NOT be gated as spam"


async def case_muted_creator_not_profiled():
    """A muted creator we follow is NOT profiled even when PAYING — the mute, not
    the $0 spam umbrella, is what drops it (mirrors welcome_chatter_for_info). An unmuted paying
    collab of the same source IS still profiled."""
    aid = "acc_gi_muted"
    _install_fake_llm()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, 9101, in_msgs=8, spend_cents=50)  # paying + muted → skip
    await _seed_fan_with_msgs(aid, 9102, in_msgs=8, spend_cents=50)  # paying, not muted → profiled
    async with get_session() as s:
        a = await s.get(Fan, (aid, 9101)); a.source = "creator_we_follow"; a.is_muted = True
        b = await s.get(Fan, (aid, 9102)); b.source = "creator_we_follow"

    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 9101)) is None, "muted creator must be skipped"
        assert await s.get(FanProfile, (aid, 9102)) is not None, "unmuted paying collab profiled"

    # force_ids overrides the guard.
    res2 = await run_once(aid, "gen_info", payload={"force_ids": [9101]})
    assert res2["status"] == "ok", res2
    async with get_session() as s:
        assert await s.get(FanProfile, (aid, 9101)) is not None, "force_ids overrides muted guard"


_EXPECTED_NOTE = ("Intr: gaming, coffee\nJob: Software Dev\nRel: single\n"
                  "31yo dev from Toronto who tips often")


async def case_of_nickname_resynced():
    """gen_info re-asserts the structured OF nickname after a regen (the self-heal:
    once a fan graduates the name is only pushed once, so any later
    enrichment or an external edit on OF that clears it never propagates). The push
    uses the canonical build_structured_nickname format and mirrors into the local
    custom_nickname column."""
    aid, fan = "acc_gi_ofsync", 7700
    _install_fake_llm()
    fake = _use_fake_of()
    await _seed_account(aid)
    await _seed_fan_with_msgs(aid, fan, in_msgs=9)

    res = await run_once(aid, "gen_info", payload={})
    assert res["status"] == "ok", res
    assert res["generated"] == 1, res

    # Canonical structured name (Name/City,Country/Age/Job) pushed to OF.
    expected = "Bob/Toronto,Canada/31/Software Dev"
    assert fake.nicks == [(fan, expected)], fake.nicks

    # The drawer's Fan notes tab (OF notice): the 200-char fact sheet, bio last.
    # Name / age / location are left out: they are in the nickname.
    assert fake.notes == [(fan, _EXPECTED_NOTE)], fake.notes

    # And mirrored locally so the chat-list rail/reconciler agree with OF; the note
    # is also remembered as ours (applied_notes) so the next regen may replace it.
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.custom_nickname == expected, f.custom_nickname
        assert f.notes == _EXPECTED_NOTE, f.notes
        assert f.applied_notes == _EXPECTED_NOTE, f.applied_notes

    # Re-assertion is UNCONDITIONAL on every regen (not gated on the local mirror):
    # the bug class is local=full but OF reverted to the bare profile name, where a
    # "changed vs local" guard would wrongly skip. So a forced re-run pushes again.
    fake.nicks.clear()
    fake.notes.clear()
    res2 = await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    assert res2["status"] == "ok", res2
    assert fake.nicks == [(fan, expected)], fake.nicks
    # The note is unchanged, so there is no second PUT for it.
    assert fake.notes == [], fake.notes


async def case_hand_typed_note_kept():
    """A Fan note a chatter typed (fans.notes set, and not the one gen_info last
    wrote) is never overwritten; the nickname still goes out. Once the note is
    cleared, gen_info fills it on the next regen."""
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
        f.notes = None                      # the chatter clears it

    res = await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    assert res["generated"] == 1, res
    assert fake.notes == [(fan, _EXPECTED_NOTE)], fake.notes


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
    case_rerun_gate,
    case_prompt_is_fan_only,
    case_w2h_helpers,
    case_list_shaped_fields_are_coerced,
    case_spend_max_and_tier_fallback,
    case_lineless_profile_not_reprofiled,
    case_stored_lines_left_alone,
    case_rule_schedules_gen_info,
)
