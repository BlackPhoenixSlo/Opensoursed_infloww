#!/usr/bin/env python3
"""test_gen_info_richer.py — R1 fixes (build step 3): typed serializers + guarded upsert.

Three cases, each pinning one adversarial finding:

  1. RICHER FACTS PERSIST TYPE-CORRECTLY. has_kids=false lands as a real bool (not ""),
     pets/communication_style land as JSON (not a Python dict repr), employer as text.
     Also proves the whole persist does NOT abort (the is_name_real→'True'→StatementError
     class of bug) — `generated==1` and the fan row is populated.

  2. FIX-2: an EMPTY response does NOT wipe the stored nickname / bio / bullets. Stored
     q / tease lines are never written by gen_info at all, so they survive too.

  3. FIX-2 corollary: a partial response overwrites only the fields it fills, and a
     Q1 the model volunteers is still not stored.

Run:  ./venv/bin/python service/tests/test_gen_info_richer.py
"""
import _harness  # noqa: F401 — MUST be first

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import llm_client  # noqa: E402
import automation_executor as ax  # noqa: E402,F401
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, FanProfile, Message  # noqa: E402

# A per-call controllable fake: the test sets _NEXT before each run.
_NEXT: dict = {}


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def raise_for_status(self):
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
        return _FakeResponse({
            "choices": [{"message": {"content": __import__("json").dumps(_NEXT)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })


class _FakeOF:
    def set_fan_custom_name(self, user_id, name):
        return {"success": True}

    def set_fan_note(self, user_id, note):
        return {"success": True}


def _install():
    llm_client.httpx.AsyncClient = _FakeAsyncClient  # type: ignore[attr-defined]
    ax._make_client = lambda account_id: _FakeOF()  # type: ignore[attr-defined]


async def _seed(aid: str, fan: int, in_msgs: int = 9):
    base = datetime(2026, 6, 1, 10, 0, 0)
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(Fan(account_id=aid, fan_id=fan, of_display_name="Bob", of_username="bob"))
        for i in range(in_msgs):
            s.add(Message(account_id=aid, fan_id=fan, message_id=fan * 1000 + i,
                          direction="in", body=f"<p>real message number {i} here</p>",
                          created_at=base + timedelta(minutes=i)))


_RICH = {
    "nickname": "Bob/Toronto/31/Dev", "short_bio": "31yo dev from Toronto",
    "bullet_points": "- Job: Dev", "Q1": "fav game?", "Q2": "new job?", "Q3": "travel?",
    "Tease1": "your setup is insane", "Tease2": "miss you", "Tease3": "so hot",
    "original_name": "Bob", "real_name": "Bob", "his_age": "31",
    "home_country": "Canada", "home_city": "Toronto", "hobbies": "gaming",
    "occupation": "Dev", "relationship_status": "single", "fetishes": "",
    # the richer fields:
    "employer": "Acme Corp", "partner_name": "", "relationship_stage": "regular",
    "has_kids": False, "pets": ["dog Toby", "cat Mia"],
    "communication_style": {"chatty": True, "kink_forward": False, "blunt": None},
}
_EMPTY = {k: ("" if not isinstance(v, (list, dict, bool)) else ([] if isinstance(v, list) else ({} if isinstance(v, dict) else "")))
          for k, v in _RICH.items()}


async def case_richer_facts_persist():
    global _NEXT
    aid, fan = "acc_rich", 7001
    _install()
    await _seed(aid, fan)
    _NEXT = dict(_RICH)

    res = await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    assert res["status"] == "ok", res
    assert res["generated"] == 1, res  # did NOT abort (the is_name_real class of bug)

    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.employer == "Acme Corp", f.employer
        assert f.relationship_stage == "regular", f.relationship_stage
        # has_kids=False is a REAL bool, meaningful "no kids" — not dropped, not "False".
        assert f.has_kids is False, repr(f.has_kids)
        # pets is valid JSON (not a Python repr) — round-trips.
        assert json.loads(f.pets) == ["dog Toby", "cat Mia"], f.pets
        # communication_style: None value filtered, valid JSON.
        assert json.loads(f.communication_style) == {"chatty": True, "kink_forward": False}, f.communication_style
        # existing facts still land.
        assert f.his_age == "31" and f.home_city == "Toronto", (f.his_age, f.home_city)
        # is_name_real untouched (never in the fact set → default preserved, no abort).
        assert f.is_name_real is True, f.is_name_real


async def _seed_lines(aid: str, fan: int) -> None:
    """Lines stored before gen_info stopped writing them."""
    async with get_session() as s:
        p = await s.get(FanProfile, (aid, fan))
        p.q1, p.tease1 = "fav game?", "your setup is insane"


async def case_empty_response_keeps_profile():
    """FIX-2: a fully-empty second gen must NOT null nickname / bio / bullets, and the
    stored q / tease lines are left alone."""
    global _NEXT
    aid, fan = "acc_keep", 7002
    _install()
    await _seed(aid, fan)

    _NEXT = dict(_RICH)
    r1 = await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    assert r1["generated"] == 1, r1
    await _seed_lines(aid, fan)
    async with get_session() as s:
        p1 = await s.get(FanProfile, (aid, fan))
        assert p1.nickname and p1.short_bio, "seeded profile"
        nick0, bio0, bp0 = p1.nickname, p1.short_bio, p1.bullet_points

    # second run: the model returns everything empty.
    _NEXT = dict(_EMPTY)
    r2 = await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    assert r2["generated"] == 1, r2  # the write still "succeeds" — but keeps prior content

    async with get_session() as s:
        p2 = await s.get(FanProfile, (aid, fan))
        assert p2.nickname == nick0, (p2.nickname, nick0)
        assert p2.short_bio == bio0, (p2.short_bio, bio0)
        assert p2.bullet_points == bp0, (p2.bullet_points, bp0)
        assert (p2.q1, p2.tease1) == ("fav game?", "your setup is insane"), (p2.q1, p2.tease1)


async def case_partial_response_merges():
    """A partial response overwrites only what it fills; the rest is kept. Q1 is not a
    field gen_info stores, so a volunteered one changes nothing."""
    global _NEXT
    aid, fan = "acc_partial", 7003
    _install()
    await _seed(aid, fan)

    _NEXT = dict(_RICH)
    await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    await _seed_lines(aid, fan)

    # second run: a new bio (and a volunteered Q1) only, everything else empty.
    partial = dict(_EMPTY)
    partial["short_bio"] = "31yo dev who just got a dog"
    partial["Q1"] = "brand new question about your dog?"
    _NEXT = partial
    await run_once(aid, "gen_info", payload={"force_ids": [fan]})

    async with get_session() as s:
        p = await s.get(FanProfile, (aid, fan))
        assert p.short_bio == "31yo dev who just got a dog", p.short_bio  # overwritten
        assert p.nickname == "Bob/Toronto/31/Dev", p.nickname             # kept
        assert p.q1 == "fav game?", p.q1                                  # never written


async def case_language_detected_when_evidence():
    """gen_info stores a detected language (source='ai') past the evidence floor."""
    global _NEXT
    aid, fan = "acc_lang", 7004
    _install()
    await _seed(aid, fan)  # 9 inbound × ~30 chars each → well over the 40-char floor
    _NEXT = dict(_RICH, language="es")

    await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.language == "es", f.language
        assert f.language_source == "ai", f.language_source


async def case_language_manual_override_wins():
    """FIX-3: gen_info must NOT overwrite a language an operator pinned manually."""
    global _NEXT
    aid, fan = "acc_lang_manual", 7005
    _install()
    await _seed(aid, fan)
    # operator pins Spanish manually first
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        f.language = "es"
        f.language_source = "manual"

    # gen_info then detects English — must be IGNORED (manual wins).
    _NEXT = dict(_RICH, language="en")
    await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.language == "es", f.language              # kept
        assert f.language_source == "manual", f.language_source


async def case_language_skipped_below_floor():
    """Too little fan text ⇒ no language written (stays NULL → account default)."""
    global _NEXT
    aid, fan = "acc_lang_thin", 7006
    _install()
    # one short inbound, under the 40-char floor
    from datetime import datetime as _dt
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(Fan(account_id=aid, fan_id=fan, of_display_name="Al", of_username="al"))
        s.add(Message(account_id=aid, fan_id=fan, message_id=fan * 1000,
                      direction="in", body="<p>hi</p>", created_at=_dt(2026, 6, 1)))
    _NEXT = dict(_RICH, language="es")
    await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.language is None, f.language              # left NULL


async def case_junk_language_rejected():
    """A non-ISO junk language value is never stored."""
    global _NEXT
    aid, fan = "acc_lang_junk", 7007
    _install()
    await _seed(aid, fan)
    _NEXT = dict(_RICH, language="klingon")
    await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.language is None, f.language


async def case_timeline_dated_and_accretes():
    """recent_events become a dated timeline; a later run adds only NEW events."""
    global _NEXT
    aid, fan = "acc_timeline", 7008
    _install()
    await _seed(aid, fan)
    _NEXT = dict(_RICH, recent_events=["started a new job", "his dog got sick"])
    await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        tl = json.loads(f.recent_events_timeline or "[]")
        assert len(tl) == 2, tl
        assert all(t.get("date") and t.get("event") for t in tl), tl
        events = {t["event"] for t in tl}
        assert events == {"started a new job", "his dog got sick"}, events

    # a later run with one repeat + one new → only the new one is added
    _NEXT = dict(_RICH, recent_events=["his dog got sick", "moved apartments"])
    await run_once(aid, "gen_info", payload={"force_ids": [fan]})
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        tl = json.loads(f.recent_events_timeline or "[]")
        events = [t["event"] for t in tl]
        assert events == ["started a new job", "his dog got sick", "moved apartments"], events


if __name__ == "__main__":
    _harness.run(
        case_richer_facts_persist,
        case_empty_response_keeps_profile,
        case_partial_response_merges,
        case_language_detected_when_evidence,
        case_language_manual_override_wins,
        case_language_skipped_below_floor,
        case_junk_language_rejected,
        case_timeline_dated_and_accretes,
    )
