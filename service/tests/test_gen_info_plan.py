#!/usr/bin/env python3
"""test_gen_info_plan.py — the pure half of gen_info (gen_info_plan) + its seams.

  • build_user_prompt golden: bytes captured from main (68646e684) BEFORE the split.
  • plan_persist tables: nickname guard, facts serialise, events merge/timeline,
    language floor.
  • Through the REAL gen_info._persist on the harness temp DB: keep-if-empty fields,
    the operator's manual language pin (plan still offers the detection; SQL keeps the
    pin).
  • Seams read at call time: run() goes through gen_info_plan.plan_persist, and
    _persist reads PROFILE_KEEP_IF_EMPTY off the module (MANUAL_LANGUAGE_SOURCES: slop fault).

Run:  ./venv/bin/python service/tests/test_gen_info_plan.py   (exit 0 = green)
"""
import _harness  # noqa: F401 — MUST be first

_harness.bootstrap()

import hashlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # noqa: E402

import llm_client  # noqa: E402
import automation_executor as ax  # noqa: E402,F401 — registers gen_info
from automation_executor import run_once  # noqa: E402
from automations import gen_info, gen_info_plan as P  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, FanProfile, Message  # noqa: E402

NOW = datetime(2026, 11, 2, 12, 0, 0)
AID = "acc_plan"


def _cand(fid, **kw):
    c = P.Candidate(fid)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


_EVIDENCE = [("in", "x" * 50)]          # past LANG_EVIDENCE_MIN_CHARS (40)


# ── build_user_prompt golden (captured on main before the split) ─────

_GOLDEN_101 = (
    "Fan OF display name: Jeff Trafford  (username/handle: jeffy_t — a handle, NOT a real name)\n"
    "Fan message count: 3\nLifetime spend: $12.34\n\n"
    "KNOWN INFO (already confirmed — ground truth; confirm or correct from the chat, never drop it):\n"
    "Real name: Jeff\nLocation: Toronto, Canada\nAge: 31\nJob: Welder\nHobbies: fishing\n"
    "Relationship: single\nFetishes: feet\nRecent events: trip to Rome; new job\n"
    "Current nickname (refine + keep complete): Jeff/Toronto,Canada/31\n\n"
    "Chat history (oldest→newest):\nFAN: hey there\nFAN: how r u — ünïcode 😀\n"
)
_GOLDEN_103 = ("Fan OF display name: (unknown)\nFan message count: 0\nLifetime spend: $0.00\n\n"
               "Chat history (oldest→newest):\n\n")
# 1600 msgs, spender (≥ $50) → 500+500 fan-only window; too big to inline.
_GOLDEN_102_SHA = "e444687987ef804d17ea9ed3afb3a9ce13b3fe544db25d4eb7eda1a458b22f13"
_GOLDEN_102_LEN = 13432


def case_build_user_prompt_golden():
    a = _cand(101, of_name="Jeff Trafford", of_username="jeffy_t", fan_msg_n=3, spend_cents=1234,
              known={"real_name": "Jeff", "home_city": "Toronto", "home_country": "Canada",
                     "his_age": "31", "occupation": "Welder", "hobbies": "fishing",
                     "relationship_status": "single", "fetishes": "feet",
                     "recent_events": '["trip to Rome","new job"]',
                     "generated_nickname": "Jeff/Toronto,Canada/31/Free"},
              messages=[("in", "hey there"), ("out", "hi babe"), ("in", ""),
                        ("in", "how r u — ünïcode 😀")])
    b = _cand(102, of_name="u102", of_username="U102", fan_msg_n=1200, spend_cents=5000,
              messages=[(("in" if i % 3 else "out"), f"msg {i}") for i in range(1600)])
    c = _cand(103)
    assert P.build_user_prompt(a) == _GOLDEN_101, P.build_user_prompt(a)
    pb = P.build_user_prompt(b)
    assert (hashlib.sha256(pb.encode()).hexdigest(), len(pb)) == (_GOLDEN_102_SHA, _GOLDEN_102_LEN), len(pb)
    assert P.build_user_prompt(c) == _GOLDEN_103, repr(P.build_user_prompt(c))
    assert gen_info._build_user_prompt is P.build_user_prompt   # alias, not a copy


# ── plan_persist (pure) ──────────────────────────────────────────────

def case_nickname_guard_table():
    rows = [
        # (candidate kwargs, data nickname, expected nickname)
        (dict(fid=111222333), "111222333/Vancouver", "Vancouver"),            # id as name
        (dict(fid=5, known={"home_country": "Canada"}), "Canada/Canada/office job",
         "Canada/office job"),                                               # place as name
        (dict(fid=6), "Bob/??/31", "Bob/31"),                                # placeholder slot
        (dict(fid=7), "Bob/Toronto/31/Whale", "Bob/Toronto/31"),             # tier stripped
        (dict(fid=8, of_name="Jeff Trafford"), "Toronto/31", "Jeff/Toronto/31"),  # hint prepended
        (dict(fid=9, of_name="Jeff Trafford"), "jeff/Toronto", "jeff/Toronto"),   # hint already lead
        (dict(fid=10, known={"generated_nickname": "Old/Nick/Free"}), "", "Old/Nick"),  # keep old
        (dict(fid=11), "", ""),                                              # nothing at all
        (dict(fid=12, of_name="R342"), "", ""),                              # handle ≠ hint
    ]
    for kw, nick, want in rows:
        fid = kw.pop("fid")
        c = _cand(fid, **kw)
        plan = P.plan_persist(c, {"nickname": nick}, call_id=1, now=NOW)
        assert plan.profile_set["nickname"] == (want or None), (fid, nick, plan.profile_set, want)
        assert plan.fan_set.get("generated_nickname") == (want or None), plan.fan_set


def case_facts_serialise_table():
    data = {"has_kids": "no", "pets": ["dog Toby", "", None], "hobbies": ["golf", " ", "ski"],
            "communication_style": {"chatty": True, "blunt": None, "romantic": ""},
            "his_age": 40, "employer": "  ", "relationship_stage": "unknown-ish",
            "original_name": "Unknown", "real_name": "Mike", "fetishes": None}
    plan = P.plan_persist(_cand(20), data, call_id=9, now=NOW)
    fs = plan.facts
    assert fs["has_kids"] is False, fs
    assert fs["pets"] == '["dog Toby"]', fs["pets"]
    assert fs["hobbies"] == "golf, ski", fs["hobbies"]
    assert json.loads(fs["communication_style"]) == {"chatty": True}, fs["communication_style"]
    assert fs["his_age"] == "40", fs
    assert "employer" not in fs and "fetishes" not in fs, fs        # empty ⇒ never clobber
    assert fs["real_name"] == "Mike", fs
    assert plan.fan_set == {"grok_facts_updated_at": NOW, "updated_at": NOW}, plan.fan_set
    assert plan.events == {}, plan.events
    # 'Unknown' is truthy, so `original_name or real_name` picks it, then it blanks:
    # the profile's original_name stays NULL while the fact real_name still lands.
    assert plan.profile_set["original_name"] is None, plan.profile_set
    assert plan.profile_set["generated_by_grok_call_id"] == 9
    # original_name alone fills real_name; an explicit 'Unknown' alone blanks.
    p2 = P.plan_persist(_cand(21), {"original_name": "Zed"}, call_id=None, now=NOW)
    assert p2.facts["real_name"] == "Zed" and p2.profile_set["original_name"] == "Zed"
    p3 = P.plan_persist(_cand(22), {"original_name": "Unknown"}, call_id=None, now=NOW)
    assert "real_name" not in p3.facts and p3.profile_set["original_name"] is None
    for kind, raw, want in [
        ("bool", "yes", (True, True)), ("bool", "unknown", (False, None)), ("bool", True, (True, True)),
        ("json_arr", "[]", (False, None)), ("json_arr", "one", (True, '["one"]')),
        ("json_obj", "{}", (False, None)), ("json_obj", {}, (False, None)),
        ("str", "", (False, None)), ("str", None, (False, None)),
    ]:
        assert P.serialize_fact(kind, raw) == want, (kind, raw, P.serialize_fact(kind, raw))


def case_events_merge_order():
    known = {"recent_events": '["a","b"]',
             "recent_events_timeline": '[{"date":"2026-01-01","event":"a"}]'}
    plan = P.plan_persist(_cand(30, known=known), {"recent_events": ["b", "c", "a", "d"]},
                          call_id=1, now=NOW)
    assert json.loads(plan.events["recent_events"]) == ["a", "b", "c", "d"], plan.events
    assert json.loads(plan.events["recent_events_timeline"]) == [
        {"date": "2026-01-01", "event": "a"},
        {"date": "2026-11-02", "event": "c"},
        {"date": "2026-11-02", "event": "d"},
    ], plan.events["recent_events_timeline"]
    # nothing new → neither column written (a sparse run never clears events)
    p0 = P.plan_persist(_cand(31, known=known), {"recent_events": []}, call_id=1, now=NOW)
    assert p0.events == {}, p0.events
    # only known events → flat list rewritten as-is, timeline untouched
    p1 = P.plan_persist(_cand(32, known=known), {"recent_events": ["a"]}, call_id=1, now=NOW)
    assert json.loads(p1.events["recent_events"]) == ["a", "b"]
    assert "recent_events_timeline" not in p1.events
    # caps: flat list first 20, timeline last 30; broken prior timeline → fresh only
    big = {"recent_events": json.dumps([f"e{i}" for i in range(19)]),
           "recent_events_timeline": "not json"}
    p2 = P.plan_persist(_cand(33, known=big), {"recent_events": ["n1", "n2", "n3"]},
                        call_id=1, now=NOW)
    flat = json.loads(p2.events["recent_events"])
    assert len(flat) == 20 and flat[-1] == "n1", flat
    assert [t["event"] for t in json.loads(p2.events["recent_events_timeline"])] == ["n1", "n2", "n3"]
    tl = json.dumps([{"date": "2026-01-01", "event": f"t{i}"} for i in range(30)])
    p3 = P.plan_persist(_cand(34, known={"recent_events_timeline": tl}), {"recent_events": "solo"},
                        call_id=1, now=NOW)
    tl3 = json.loads(p3.events["recent_events_timeline"])
    assert len(tl3) == 30 and tl3[0]["event"] == "t1" and tl3[-1]["event"] == "solo", tl3[:2]


def case_language_plan_table():
    rows = [
        # (messages, raw language, write_lang)
        (_EVIDENCE, "en", "en"),
        (_EVIDENCE, "Spanish", "es"),
        (_EVIDENCE, "pt-BR", "pt"),
        (_EVIDENCE, "xx", None),
        ([("in", "x" * 39)], "en", None),          # under the evidence floor
        ([("out", "x" * 500)], "en", None),        # creator text is not evidence
    ]
    for msgs, raw, wl in rows:
        plan = P.plan_persist(_cand(40, messages=msgs), {"language": raw}, call_id=1, now=NOW)
        assert plan.write_lang == wl, (raw, plan.write_lang)
        cols = {**plan.fan_set, **plan.facts, **plan.events}
        assert "language" not in cols and "language_source" not in cols, cols


# ── Through the real _persist (harness temp DB) ──────────────────────

async def _seed(fid, *, fan=None, profile=None):
    async with get_session() as s:
        await s.execute(sqlite_insert(Account).values(id=AID).on_conflict_do_nothing())
        if fan is not None:
            await s.execute(sqlite_insert(Fan).values(account_id=AID, fan_id=fid, **fan))
        if profile is not None:
            await s.execute(sqlite_insert(FanProfile).values(account_id=AID, fan_id=fid, **profile))


async def _write(c, data):
    plan = P.plan_persist(c, data, call_id=7, now=NOW)
    await gen_info._persist(AID, c, plan, NOW)
    return plan


async def _rows(fid):
    async with get_session() as s:
        return await s.get(Fan, (AID, fid)), await s.get(FanProfile, (AID, fid))


_STORED = {"nickname": "Old/Nick", "short_bio": "old bio", "bullet_points": "- Job: old",
           "original_name": "Old"}


async def case_keep_if_empty_through_persist():
    assert P.PROFILE_KEEP_IF_EMPTY == frozenset(_STORED), P.PROFILE_KEEP_IF_EMPTY
    empty = {"nickname": "", "short_bio": "", "bullet_points": ["- Rel:"], "original_name": ""}
    full = {"nickname": "Neo/Paris", "short_bio": "new bio", "bullet_points": ["- Job: new"],
            "original_name": "Neo"}
    want_full = {"nickname": "Neo/Paris", "short_bio": "new bio", "bullet_points": "- Job: new",
                 "original_name": "Neo"}
    fid = 500
    for field in sorted(_STORED):
        for label, data, want in (("empty", empty, _STORED[field]), ("full", full, want_full[field])):
            fid += 1
            await _seed(fid, fan={}, profile=dict(_STORED, message_count_at_gen=1))
            await _write(_cand(fid, fan_msg_n=12, spend_cents=300), {field: data[field]})
            _f, p = await _rows(fid)
            assert getattr(p, field) == want, (field, label, getattr(p, field), want)
            # metadata always takes the new value
            assert (p.message_count_at_gen, p.total_spend_at_gen_cents, p.generated_by_grok_call_id,
                    p.last_generated_at) == (12, 300, 7, NOW), (field, label)


async def case_manual_language_pin_through_persist():
    rows = [
        # (fid, stored language, stored source, want language, want source)
        (601, "es", "manual", "es", "manual"),   # operator pin wins
        (602, "es", "ai", "en", "ai"),           # prior AI guess is refreshed
        (603, None, None, "en", "ai"),           # never set
    ]
    for fid, lang, src, want_lang, want_src in rows:
        await _seed(fid, fan={"language": lang, "language_source": src})
        c = _cand(fid, messages=_EVIDENCE)
        plan = await _write(c, {"language": "en", "nickname": "Al/Rome", "occupation": f"job{fid}"})
        assert plan.write_lang == "en", plan.write_lang                # plan still offers it
        f, _p = await _rows(fid)
        assert (f.language, f.language_source) == (want_lang, want_src), (fid, f.language, f.language_source)
        assert (f.generated_nickname, f.occupation) == ("Al/Rome", f"job{fid}"), (
            fid, f.generated_nickname, f.occupation)                     # rest of the row lands, own fan
    # under the evidence floor nothing is written, pin or not
    await _seed(604, fan={"language": "de", "language_source": "ai"})
    await _write(_cand(604, messages=[("in", "hi")]), {"language": "en"})
    f, _p = await _rows(604)
    assert (f.language, f.language_source) == ("de", "ai"), (f.language, f.language_source)


# ── Seams: module attrs read at call time ────────────────────────────

class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
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
        body = {"nickname": "Bob/Toronto", "short_bio": "dev", "language": "en"}
        return _FakeResponse({
            "choices": [{"message": {"content": __import__("json").dumps(body)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })


async def case_run_goes_through_plan_persist_seam():
    llm_client.httpx.AsyncClient = _FakeAsyncClient  # type: ignore[attr-defined]
    ax._make_client = lambda account_id: None  # type: ignore[attr-defined]
    aid, fid = "acc_plan_seam", 801
    base = datetime(2026, 6, 1, 10, 0, 0)
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(Fan(account_id=aid, fan_id=fid, of_display_name="Bob", of_username="bob"))
        for i in range(9):
            s.add(Message(account_id=aid, fan_id=fid, message_id=fid * 1000 + i, direction="in",
                          body=f"real message number {i} here", created_at=base + timedelta(minutes=i)))
    seen = []
    real = P.plan_persist

    def spy(c, data, **kw):
        seen.append((c.fan_id, data.get("nickname"), sorted(kw)))
        return real(c, data, **kw)

    P.plan_persist = spy
    try:
        res = await run_once(aid, "gen_info", payload={"force_ids": [fid]})
    finally:
        P.plan_persist = real
    assert res["status"] == "ok" and res["generated"] == 1, res
    assert seen == [(fid, "Bob/Toronto", ["call_id", "now"])], seen
    for k in ("candidates", "deferred_for_scrape", "skipped_fresh", "attempted", "generated",
              "capped", "failed", "model"):
        assert k in res, (k, res)


async def case_persist_reads_keep_if_empty_at_call_time():
    fid = 901
    await _seed(fid, fan={}, profile=dict(_STORED))
    saved = P.PROFILE_KEEP_IF_EMPTY
    P.PROFILE_KEEP_IF_EMPTY = frozenset()
    try:
        await _write(_cand(fid), {"short_bio": ""})
    finally:
        P.PROFILE_KEEP_IF_EMPTY = saved
    _f, p = await _rows(fid)
    assert p.short_bio is None, p.short_bio     # guard off ⇒ the empty value went through


if __name__ == "__main__":
    _harness.run()
