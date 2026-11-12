#!/usr/bin/env python3
"""
assistant_draft — POST /admin/assistant/draft, the help bot's "Do it for me"
form-fill draft (pilot: Auto mass). Spec: docs/spec/assistant-do-mode.md.

Drives the route coroutine against the temp DB with `llm_client.chat` patched
(never a real completion) and the OF list read patched at `_read_lists` (the one
OF wire call). Covers: validation + clamps, the SFW folder ranking table, list
resolution, MASSdmEXCLUDE never stored, flow null, every LLM failure as a 200,
the role gate as a sentence (not a 403), the turn row, and a byte-stable system
prompt whose few-shots parse as the intent schema they teach.

Run: ./venv/bin/python service/tests/test_assistant_draft.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
from datetime import datetime  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"  # read per call; a case flips it back

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

import assistant_draft  # noqa: E402
import auth  # noqa: E402
import llm_client  # noqa: E402

REAL_CHAT = llm_client.chat     # cases spy on `chat`; a few need the real one
from assistant_draft import (  # noqa: E402
    DraftBody, FolderStat, Intent, draft, do_caps, folder_stats, match_named,
    pick_sfw, rank_sfw, resolve,
)
from automations._common import JSON_OBJECT_PURPOSES, MODEL_PURPOSES, PURPOSE_DEFAULT_MODELS  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AssistantTurn, AutomationRule, VaultItem  # noqa: E402
from llm_client import LLMCapExceeded, LLMHTTPError, LLMKeyError, LLMResult  # noqa: E402

AID = "acc_draft_test"
PILOT = ("make a auto mass to fans every hour and delete to everyone exclude mass-exclude "
         "list, pick the sfw folder or one that is close has no nude photos and insert 10 "
         "captions I will add the rest later")
LISTS = [{"id": "fans", "name": "Fans", "type": "build-in"},
         {"id": 501, "name": "VIP", "type": "custom"},
         {"id": 502, "name": "Whales 💰", "type": "custom"},
         {"id": 503, "name": "MASSdmEXCLUDE", "type": "custom"}]


class _Spy:
    def __init__(self, content: str = "{}", raises: Exception | None = None):
        self.content, self.raises, self.calls = content, raises, []

    async def __call__(self, **kw):
        self.calls.append(kw)
        if self.raises is not None:
            raise self.raises
        return LLMResult(call_id=1, model=kw["model"], provider="deepseek",
                         content=self.content, parsed=None, reasoning_content=None,
                         tokens_in=100, tokens_out=10, cache_hit_tokens=90,
                         cost_cents=0, latency_ms=5)


def _patch(spy: _Spy, lists=LISTS) -> _Spy:
    llm_client.chat = spy

    async def _lists(_aid):
        return lists
    assistant_draft._read_lists = _lists
    return spy


def _pilot_intent(**over) -> dict:
    d = {"flow": "mass_premade", "name": "Hourly SFW mass",
         "every": {"value": 1, "unit": "hours"}, "delete_after": True,
         "unsend_after_hours": None, "online_only": False,
         "audience": {"include": ["everyone"], "exclude": ["mass-exclude"]},
         "folder": {"want": "sfw", "name": None},
         "captions": {"count": 10, "provided": [], "generated": [f"Teaser {i}" for i in range(10)]},
         "keep_skip_recent": True, "assumptions": [], "unresolved": []}
    d.update(over)
    return d


def _f(name, fid="1", **tiers) -> FolderStat:
    f = FolderStat(id=fid, name=name)
    for t, n in tiers.items():
        f.tiers[t] = n
    f.photos = sum(f.tiers.values())
    return f


def _resolve(intent: dict, *, lists=LISTS, folders=(), existing=(), request="x"):
    return resolve(Intent.model_validate(intent), request=request, lists=lists,
                   folders=list(folders), existing_names=list(existing))


async def _seed():
    """An account, three folders in the mirror, one existing Auto mass."""
    async with get_session() as s:
        if await s.get(Account, AID) is not None:
            return
        s.add(Account(id=AID))
        now = datetime(2026, 11, 1)

        def item(mid, kind, tier, folders):
            raw = {"id": mid, "type": kind, "listStates": [
                {"id": fid, "name": nm, "hasMedia": True} for fid, nm in folders]}
            s.add(VaultItem(account_id=AID, media_id=mid, kind=kind, explicitness_tier=tier,
                            raw_json=json.dumps(raw), created_at=now))
        mid = 1000
        for tier in ["sfw"] * 8 + ["suggestive"] * 2 + [None] * 2:     # Daytime: likely SFW
            mid += 1; item(mid, "photo", tier, [(11, "Daytime")])
        for tier in ["sfw"] * 5 + ["explicit"]:                          # Mixed: one explicit
            mid += 1; item(mid, "photo", tier, [(12, "Mixed")])
        for tier in [None] * 4:                                          # Fresh: unflagged
            mid += 1; item(mid, "photo", tier, [(13, "Fresh")])
        mid += 1; item(mid, "video", "sfw", [(11, "Daytime")])           # not a photo
        s.add(AutomationRule(account_id=AID, name="Hourly SFW mass", kind="mass_premade",
                             trigger_json="{}", steps_json="{}", is_enabled=False))


async def _draft(request=PILOT, **kw):
    return await draft(DraftBody(request=request, account_id=AID, **kw))


# ── Pure: validation / clamps ─────────────────────────────────────────

def case_interval_is_clamped_and_expressed_in_whole_units():
    table = [({"value": 1, "unit": "minutes"}, {"value": 5, "unit": "minutes"}, True),
             ({"value": 500, "unit": "hours"}, {"value": 168, "unit": "hours"}, True),
             ({"value": 90, "unit": "minutes"}, {"value": 90, "unit": "minutes"}, False),
             ({"value": 120, "unit": "minutes"}, {"value": 2, "unit": "hours"}, False),
             ({"value": 1.5, "unit": "hours"}, {"value": 90, "unit": "minutes"}, False),
             (None, {"value": 1, "unit": "hours"}, True)]
    for every, want, noted in table:
        d = _resolve(_pilot_intent(every=every))
        assert d.slots["interval"] == want, (every, d.slots["interval"])
        clamp_or_default = any("allowed range" in a or "didn't say" in a for a in d.assumptions)
        assert clamp_or_default == noted, (every, d.assumptions)


def case_captions_are_trimmed_capped_and_counted():
    d = _resolve(_pilot_intent(captions={
        "count": 50, "provided": ["  Hi  babe ", "", "   "],
        "generated": [f"G{i}" for i in range(30)] + ["x" * (assistant_draft.CAPTION_MAX + 1)]}))
    caps = d.slots["captions"]
    assert len(caps) == 20 and caps[0] == "Hi babe", caps[:3]
    assert d.slots["captions_ai"] == 19, d.slots["captions_ai"]
    assert all(c.strip() and len(c) <= assistant_draft.CAPTION_MAX for c in caps)
    assert any("capped at 20" in a for a in d.assumptions), d.assumptions
    assert any("over" in u and "characters" in u for u in d.unresolved), d.unresolved
    # Fewer written than asked: said, not hidden.
    d = _resolve(_pilot_intent(captions={"count": 10, "provided": [], "generated": ["a", "b"]}))
    assert d.slots["captions_ai"] == 2 and any("2 of 10" in a for a in d.assumptions), d.assumptions
    d = _resolve(_pilot_intent(captions={"count": 0, "provided": [], "generated": []}))
    assert d.slots["captions"] == [] and any("No captions" in u for u in d.unresolved)


def case_delete_without_hours_is_the_interval_and_said():
    d = _resolve(_pilot_intent(every={"value": 2, "unit": "hours"}))
    assert d.slots["unsend_after_hours"] == 2.0, d.slots
    assert any("deleted after 2 h" in a for a in d.assumptions), d.assumptions
    d = _resolve(_pilot_intent(unsend_after_hours=6))
    assert d.slots["unsend_after_hours"] == 6, d.slots
    d = _resolve(_pilot_intent(delete_after=False))
    assert d.slots["unsend_after_hours"] is None, d.slots


def case_defaults_only_move_when_asked():
    d = _resolve(_pilot_intent(online_only=None, audience={"include": [], "exclude": []}))
    s = d.slots
    assert s["online_only"] is True and s["includes"] == ["fans", "following"], s
    assert s["exclude_last_chat_hours"] is None, s       # null = keep the form's default
    d = _resolve(_pilot_intent(keep_skip_recent=False))
    assert d.slots["exclude_last_chat_hours"] == 0 and any("NOT skipped" in a for a in d.assumptions)


def case_name_never_collides_with_an_existing_rule():
    d = _resolve(_pilot_intent(), existing=["hourly sfw mass", "Hourly SFW mass 2"])
    assert d.slots["name"] == "Hourly SFW mass 3", d.slots["name"]
    d = _resolve(_pilot_intent(name="   "))
    assert d.slots["name"] == "Auto mass", d.slots["name"]


def case_nulls_from_the_model_are_defaults_not_crashes():
    i = Intent.model_validate({"flow": "mass_premade", "audience": None, "folder": None,
                               "captions": None, "assumptions": None, "keep_skip_recent": None})
    assert i.audience.include == [] and i.folder.want == "none" and i.keep_skip_recent is True


# ── Pure: folder ranking ──────────────────────────────────────────────

def case_sfw_folder_ranking_table():
    rows = [
        # (folders, expected pick name or None, expected unresolved)
        ([_f("A", sfw=5, unknown=5), _f("B", sfw=9, unknown=1)], "B", None),       # flagged share
        ([_f("A", sfw=4), _f("B", sfw=8)], "B", None),                             # tie → sfw count
        ([_f("b", sfw=3), _f("a", sfw=3)], "a", None),                             # tie → name
        ([_f("Hot", sfw=9, explicit=1), _f("Ok", sfw=1, unknown=9)], "Ok", None),  # explicit out
        ([_f("Hard", sfw=9, hardcore=1)], None, assistant_draft.NO_SFW_NOTE),
        ([_f("Tease", suggestive=3)], None, assistant_draft.NO_SFW_NOTE),          # suggestive ≠ SFW
        ([_f("Spice", suggestive=1), _f("Clean", sfw=59, unknown=1)], "Clean", None),  # SFW share wins
        ([_f("Mostly", sfw=8, suggestive=2), _f("All", sfw=5)], "All", None),
        ([_f("Posts", fid="p", sfw=9), _f("Mine", sfw=1, unknown=1)], "Mine", None),  # built-in skipped
        ([_f("New", unknown=6), _f("Also", unknown=2)], None, assistant_draft.NO_FLAGS_NOTE),
        ([], None, assistant_draft.NO_FLAGS_NOTE),
        ([_f("Empty"), _f("Real", sfw=1)], "Real", None),                          # photos > 0
    ]
    for folders, want, why in rows:
        got, note = pick_sfw(folders)
        assert (got.name if got else None, note) == (want, why), (
            [(f.name, f.tiers) for f in folders], got, note)
    assert [f.name for f in rank_sfw([_f("A", sfw=1, unknown=1), _f("B", sfw=2)])] == ["B", "A"]


def case_named_folder_match_is_fuzzy_but_not_wild():
    fs = [_f("Beach pics", fid="1", sfw=3), _f("Gym", fid="2", sfw=1), _f("Lingerie set", fid="3", sfw=2)]
    assert match_named(fs, "beach").id == "1"
    assert match_named(fs, "BEACH PICS").id == "1"
    assert match_named(fs, "lingere set").id == "3"          # a typo
    assert match_named(fs, "kitchen") is None
    assert match_named(fs, "") is None


def case_folder_stats_count_photos_per_tier_and_respect_the_chatter_allowlist():
    def raw(*folders):
        return json.dumps({"listStates": [{"id": i, "name": n, "hasMedia": True} for i, n in folders]
                          + [{"id": 99, "name": "Gone", "hasMedia": False}]})
    rows = [(raw((1, "A")), "photo", "sfw"), (raw((1, "A"), (2, "B")), "photo", "Explicit "),
            (raw((1, "A")), "photo", "weird"), (raw((1, "A")), "video", "sfw"), (None, "photo", "sfw")]
    by = {f.name: f for f in folder_stats(rows)}
    assert set(by) == {"A", "B"}, by                          # hasMedia False never counts
    assert by["A"].photos == 3 and by["A"].tiers == {
        "sfw": 1, "suggestive": 0, "explicit": 1, "hardcore": 0, "unknown": 1}, by["A"].tiers
    assert by["A"].slot()["id"] == "1"
    assert [f.name for f in folder_stats(rows, frozenset({2}))] == ["B"]


# ── Pure: lists ───────────────────────────────────────────────────────

def case_list_names_resolve_to_of_ids_and_unknowns_are_unresolved():
    d = _resolve(_pilot_intent(online_only=True, audience={
        "include": ["vip", "whales", "Gold"], "exclude": ["fans", "Nope"]}))
    # Names match case- and symbol-blind ("whales" = "Whales 💰"), never by guess.
    assert d.slots["includes"] == ["501", "502"], d.slots["includes"]
    assert d.slots["excludes"] == [], d.slots["excludes"]
    joined = " ".join(d.unresolved)
    assert '"Gold"' in joined and '"Nope"' in joined and "can't be excluded" in joined, d.unresolved
    d = _resolve(_pilot_intent(audience={"include": ["Whales 💰", "fans"], "exclude": ["VIP"]}))
    assert d.slots["includes"] == ["502", "fans"] and d.slots["excludes"] == ["501"], d.slots
    assert d.names == {"502": "Whales 💰", "501": "VIP"}, d.names


def case_everyone_is_both_system_audiences_online_or_not():
    d = _resolve(_pilot_intent(online_only=None, audience={"include": ["everyone"], "exclude": []}))
    assert d.slots["includes"] == ["fans", "following"] and d.slots["online_only"] is False, d.slots
    assert any("online or not" in a for a in d.assumptions), d.assumptions


def case_cross_checks_flag_silent_misses_and_stay_quiet_otherwise():
    def checks(request, **over):
        d = _resolve(_pilot_intent(**over), request=request)
        return [a for a in d.assumptions if a.startswith(assistant_draft.CHECK_PREFIX)]
    fans = {"audience": {"include": ["fans", "following"], "exclude": []}}
    assert checks("solo ai fan online, ogni ora, 10 captions", online_only=True, **fans), "following widened"
    assert checks("only online fans, hourly, 10 captions", online_only=False,
                  audience={"include": ["fans"], "exclude": []}), "online dropped"
    assert not checks("online or offline, everyone, hourly, 10 captions")
    assert not checks("to everyone online, hourly, 10 captions", online_only=True,
                      audience={"include": ["everyone"], "exclude": []})
    assert checks("every 4 hours, 10 captions"), "4 used nowhere"
    assert not checks("every 1 hour, 10 captions, delete after 30 minutes", unsend_after_hours=0.5)
    assert not checks("every 2 days, 10 captions", every={"value": 48, "unit": "hours"})
    assert not checks("50 captions hourly", captions={"count": 50, "provided": [], "generated": ["a"] * 20})


def case_everyone_keeps_an_explicit_online_only():
    d = _resolve(_pilot_intent(online_only=True, audience={"include": ["everyone"], "exclude": []}))
    assert d.slots["includes"] == ["fans", "following"] and d.slots["online_only"] is True, d.slots


def case_huge_numbers_clamp_and_unsend_stays_in_range():
    d = _resolve(_pilot_intent(every={"value": 1e308, "unit": "hours"}, unsend_after_hours=1e9))
    assert d.slots["interval"] == {"value": 168, "unit": "hours"}, d.slots["interval"]
    assert d.slots["unsend_after_hours"] == 168.0, d.slots
    d = _resolve(_pilot_intent(unsend_after_hours=0.01))
    assert d.slots["unsend_after_hours"] == assistant_draft.MIN_UNSEND_H, d.slots
    assert any("Delete time set" in a for a in d.assumptions), d.assumptions


def case_an_unresolved_list_is_never_widened_to_everyone():
    d = _resolve(_pilot_intent(audience={"include": ["Ghost"], "exclude": []}))
    assert d.slots["includes"] == [], d.slots["includes"]
    d = _resolve(_pilot_intent(audience={"include": ["VIP"], "exclude": []}), lists=None)
    assert d.slots["includes"] == [] and any("Couldn't read" in u for u in d.unresolved), d.unresolved


def case_massdmexclude_is_never_stored_and_always_explained():
    for name in ("mass-exclude", "MASSdmEXCLUDE", "mass exclude list", "Do Not Mass"):
        d = _resolve(_pilot_intent(audience={"include": ["fans"], "exclude": [name]}),
                     request="send it, exclude the list")
        assert d.slots["excludes"] == [] and "503" not in d.slots["includes"], (name, d.slots)
        assert assistant_draft.MASS_EXCLUDE_NOTE in d.assumptions, (name, d.assumptions)
    d = _resolve(_pilot_intent(audience={"include": ["fans"], "exclude": []}), request="hourly mass")
    assert assistant_draft.MASS_EXCLUDE_NOTE not in d.assumptions, d.assumptions


# ── The prompt ────────────────────────────────────────────────────────

def case_the_fewshots_parse_as_the_schema_they_teach():
    shots = re.findall(r"^JSON: (.*)$", assistant_draft._FEWSHOTS, re.M)
    assert len(shots) == 4, len(shots)
    parsed = [Intent.model_validate(json.loads(s)) for s in shots]
    assert parsed[0].flow == "mass_premade" and len(parsed[0].captions.generated) == 10
    assert parsed[-1].flow is None
    assert PILOT in assistant_draft._FEWSHOTS


async def case_the_system_prompt_is_byte_stable_and_the_request_is_not_in_it():
    await _seed()
    spy = _patch(_Spy(json.dumps(_pilot_intent())))
    await _draft("hourly mass to VIP [one]")
    await _draft("something else entirely [two]", previous={"name": "x"})
    s1, u1 = spy.calls[0]["messages"]
    s2, u2 = spy.calls[1]["messages"]
    assert s1 == s2 and s1["content"] == assistant_draft.system_prompt(), "system prompt varies"
    for leak in ("[one]", "[two]", "Whales", "Daytime", AID):
        assert leak not in s1["content"], leak
    assert "<request>\nhourly mass to VIP [one]\n</request>" in u1["content"], u1["content"]
    assert "Whales 💰" in u1["content"] and "Daytime (12 photos)" in u1["content"], u1["content"]
    assert "MASSdmEXCLUDE" in u1["content"]                   # listed; resolution drops it
    assert "EXISTING AUTO MASS RULES: Hourly SFW mass" in u1["content"]
    assert 'PREVIOUS DRAFT: {"name": "x"}' in u2["content"], u2["content"]


# ── The route ─────────────────────────────────────────────────────────

async def case_the_pilot_phrase_drafts_the_acceptance_rule():
    await _seed()
    spy = _patch(_Spy(json.dumps(_pilot_intent())))
    token = auth._request_user.set(auth.AuthedUser("u_draft", "draft", frozenset({AID})))
    try:
        out = await _draft()
    finally:
        auth._request_user.reset(token)
    kw = spy.calls[0]
    assert kw["purpose"] == "help_assistant_do" and kw["account_id"] == AID, kw
    assert kw["response_format"] == {"type": "json_object"}, kw
    assert kw["model"] == "deepseek-v4-flash", kw["model"]
    assert out["flow"] == "mass_premade" and out["error"] is None, out
    s = out["slots"]
    assert s["interval"] == {"value": 1, "unit": "hours"}, s
    assert s["online_only"] is False and s["includes"] == ["fans", "following"], s
    assert s["excludes"] == [] and s["unsend_after_hours"] == 1.0, s
    assert s["folder"]["name"] == "Daytime" and s["folder"]["id"] == "11", s["folder"]
    assert s["folder"]["photos"] == 12 and s["folder"]["tiers"]["unknown"] == 2, s["folder"]
    assert len(s["captions"]) == 10 and s["captions_ai"] == 10, s
    assert s["name"] == "Hourly SFW mass 2", s["name"]      # the seeded rule holds the name
    assert assistant_draft.MASS_EXCLUDE_NOTE in out["assumptions"], out["assumptions"]
    assert any("8/12 photos AI-flagged SFW · 2 suggestive · 0 explicit · 2 unknown" in a
               for a in out["assumptions"]), out["assumptions"]
    assert out["answer"] == out["summary"] and "switched off" in out["summary"], out
    assert set(out) == {"id", "flow", "account_id", "summary", "slots", "assumptions",
                        "unresolved", "answer", "error"}, set(out)
    async with get_session() as ses:
        row = await ses.get(AssistantTurn, out["id"])
    assert (row.question, row.answer, row.error, row.user_id, row.account_id) == (
        PILOT, out["summary"], None, "u_draft", AID), vars(row)


async def case_an_unsupported_request_is_flow_null_with_a_sentence():
    await _seed()
    _patch(_Spy(json.dumps({"flow": None})))
    out = await _draft("turn on auto reply")
    assert (out["flow"], out["slots"], out["error"]) == (None, None, None), out
    assert out["answer"] == assistant_draft.UNSUPPORTED_ANSWER and isinstance(out["id"], int), out


async def case_llm_failures_come_back_as_200s():
    await _seed()
    for exc, tag in [(LLMCapExceeded(AID, 100, 200), "cap"),
                     (LLMHTTPError("502", status=502), "provider"),
                     (LLMKeyError("invalid", "deepseek", "help_assistant_do", status=401), "config")]:
        _patch(_Spy(raises=exc))
        out = await _draft()
        assert out["error"] == tag and out["flow"] is None and out["slots"] is None, (exc, out)
        assert out["answer"], out
    for content in ("not json", "[1, 2]", json.dumps({"flow": "mass_premade", "every": "soon"}),
                    json.dumps(_pilot_intent(every={"value": float("nan"), "unit": "hours"})),
                    json.dumps(_pilot_intent(unsend_after_hours=float("inf")))):
        _patch(_Spy(content))
        out = await _draft()
        assert (out["error"], out["answer"]) == ("bad_draft", assistant_draft.BAD_DRAFT_ANSWER), (content, out)
    _patch(_Spy("   "))
    out = await _draft()
    assert out["error"] == "empty_answer", out


async def case_a_bad_draft_is_retried_once_on_the_same_model():
    await _seed()

    class _Seq(_Spy):
        async def __call__(self, **kw):
            self.content = "not json" if not self.calls else json.dumps(_pilot_intent())
            return await super().__call__(**kw)
    spy = _patch(_Seq())
    out = await _draft()
    assert len(spy.calls) == 2 and spy.calls[0]["model"] == spy.calls[1]["model"], spy.calls
    assert out["flow"] == "mass_premade" and out["error"] is None, out
    spy = _patch(_Spy("not json"))
    out = await _draft()
    assert len(spy.calls) == 2 and out["error"] == "bad_draft", (spy.calls, out)


async def case_a_caller_who_cannot_create_the_rule_gets_a_sentence_not_a_403():
    await _seed()
    spy = _patch(_Spy(json.dumps(_pilot_intent())))
    real = assistant_draft.opt_in_refusal

    async def refuse(pages, account_id):
        assert pages == ("/growth/auto-mass",), pages
        return "Your role does not allow Auto Mass"
    assistant_draft.opt_in_refusal = refuse
    try:
        out = await _draft()
        caps = await do_caps(account_id=AID)
    finally:
        assistant_draft.opt_in_refusal = real
    assert (out["flow"], out["error"], out["answer"]) == (
        None, "not_allowed", assistant_draft.NOT_ALLOWED_ANSWER), out
    assert spy.calls == [], "a refused caller bought a completion"
    assert caps == {"account_id": AID, "can_do": False, "reason": "not_allowed"}, caps
    assert await do_caps(account_id=AID) == {"account_id": AID, "can_do": True, "reason": None}


async def case_do_caps_says_no_key_when_the_drafts_model_has_none():
    await _seed()
    real, seen = llm_client.llm_key_available, []

    async def none(account_id, provider, purpose=""):
        seen.append((account_id, provider, purpose))
        return False
    llm_client.llm_key_available = none
    spy = _patch(_Spy())
    try:
        caps = await do_caps(account_id=AID)
    finally:
        llm_client.llm_key_available = real
    assert caps == {"account_id": AID, "can_do": False, "reason": "no_key"}, caps
    assert seen == [(AID, "deepseek", "help_assistant_do")], seen
    assert spy.calls == [], "do-caps bought a completion"


async def case_the_account_gate_is_asks_own():
    _patch(_Spy())
    os.environ["ALLOW_ANONYMOUS_ADMIN"] = "0"
    try:
        for call in (_draft, lambda: do_caps(account_id=AID)):
            try:
                await call()
            except HTTPException as e:
                assert e.status_code == 401, e.status_code
            else:
                raise AssertionError("an anonymous draft sailed through the gate")
    finally:
        os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"


async def case_a_blank_request_buys_nothing_and_writes_nothing():
    await _seed()
    spy = _patch(_Spy())
    async with get_session() as s:
        before = len((await s.execute(select(AssistantTurn.id))).all())
    out = await _draft("   ")
    async with get_session() as s:
        after = len((await s.execute(select(AssistantTurn.id))).all())
    assert out["error"] == "empty_request" and spy.calls == [] and before == after, out


def case_both_routes_are_served_over_http():
    import asyncio
    asyncio.run(_seed())
    _patch(_Spy(json.dumps(_pilot_intent())))
    client = _harness.make_client()
    r = client.post("/admin/assistant/draft", json={"request": PILOT, "account_id": AID})
    assert r.status_code == 200 and r.json()["flow"] == "mass_premade", (r.status_code, r.text)
    r = client.post("/admin/assistant/draft", json={"request": "x" * 1001, "account_id": AID})
    assert r.status_code == 422, r.status_code
    r = client.post("/admin/assistant/draft", json={
        "request": "x", "account_id": AID, "previous": {"k": "v" * 9000}})
    assert r.status_code == 422, r.status_code
    r = client.get("/admin/assistant/do-caps", params={"account_id": AID})
    assert r.status_code == 200 and r.json() == {
        "account_id": AID, "can_do": True, "reason": None}, r.text


def case_the_purpose_is_registered_like_the_help_bot():
    assert "help_assistant_do" in MODEL_PURPOSES
    assert PURPOSE_DEFAULT_MODELS["help_assistant_do"] == "deepseek-v4-flash"
    # Owner 2026-11-11: a Sonnet/Opus pin is allowed — the draft parses Claude's
    # plain-text JSON itself (`parse_json_object`), so it is no json_object lane.
    assert "help_assistant_do" not in JSON_OBJECT_PURPOSES
    assert llm_client.feature_label("help_assistant_do") == "The help assistant"


async def case_a_refine_sees_list_and_folder_names_and_keeps_the_custom_list():
    """`previous` is the prior response's slots (OF ids + a folder object); the
    model only knows NAMES, so PREVIOUS DRAFT is rendered with names."""
    await _seed()
    prev = {"name": "VIP mass", "interval": {"value": 1, "unit": "hours"},
            "includes": ["501", "fans"], "excludes": ["502", "999"],
            "folder": {"id": "11", "name": "Daytime", "photos": 12, "tiers": {"sfw": 8}},
            "captions": ["Hi"], "online_only": True}
    refined = _pilot_intent(every={"value": 3, "unit": "hours"}, online_only=True,
                            audience={"include": ["VIP", "fans"], "exclude": ["Whales 💰"]},
                            folder={"want": "named", "name": "Daytime"})
    spy = _patch(_Spy(json.dumps(refined)))
    out = await _draft("make it every 3 hours", previous=prev)
    user = spy.calls[0]["messages"][1]["content"]
    line = next(x for x in user.split("\n\n") if x.startswith("PREVIOUS DRAFT: "))
    shown = json.loads(line[len("PREVIOUS DRAFT: "):])
    assert shown["includes"] == ["VIP", "fans"], shown
    assert shown["excludes"] == ["Whales 💰", "999"], shown          # unknown id kept
    assert shown["folder"] == {"name": "Daytime"}, shown
    assert out["slots"]["includes"] == ["501", "fans"], out["slots"]
    assert out["slots"]["excludes"] == ["502"], out["slots"]
    assert out["slots"]["interval"] == {"value": 3, "unit": "hours"}, out["slots"]
    # Same rendering on the eval seam.
    spy = _patch(_Spy(json.dumps(refined)))
    await assistant_draft.draft_for_eval("make it every 3 hours", assistant_draft.EvalContext(
        lists=LISTS), "deepseek-v4-flash", previous=prev)
    assert '"includes": ["VIP", "fans"]' in spy.calls[0]["messages"][1]["content"]


# ── Who pays: the agency, else the deployment's help-bot DeepSeek key ─

import llm_providers  # noqa: E402
import tenant_keys  # noqa: E402
from db.models import AccountAiConfig, User, UserAccount  # noqa: E402

PLATFORM_KEY = "sk-deployment-help"


async def _owned(aid: str, *, cap_cents: int = 1_000_000, agency_key: str | None = None,
                 pin: str | None = None) -> str:
    """An account with ONE agency owner (so the house key is out of reach)."""
    import uuid
    uid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username=f"agency_{aid}", password="x", is_admin=False))
        s.add(Account(id=aid, nickname=aid))
        s.add(AccountAiConfig(account_id=aid, daily_cost_cap_cents=cap_cents,
                              model_by_purpose=json.dumps({"help_assistant_do": pin}) if pin else None))
        s.add(UserAccount(user_id=uid, account_id=aid))
    if agency_key:
        await tenant_keys.set_keys(uid, {"deepseek": agency_key})
    return uid


class _PlatformKey:
    """`llm_providers._api_key` answering only for the given env ids."""
    def __init__(self, **envs):
        self.envs, self.real = envs, llm_providers._api_key

    def __enter__(self):
        llm_providers._api_key = lambda env: self.envs.get(env, "")

    def __exit__(self, *a):
        llm_providers._api_key = self.real


async def case_a_keyless_agency_drafts_on_the_platform_deepseek_key():
    aid = "acc_draft_keyless"
    await _owned(aid)
    ds, an = llm_providers.PROVIDERS["deepseek"], llm_providers.PROVIDERS["anthropic"]
    with _PlatformKey(HELP_ASSISTANT_DEEPSEEK_KEY=PLATFORM_KEY,
                      HELP_ASSISTANT_ANTHROPIC_KEY="sk-deployment-claude"):
        assert await llm_client._tenant_api_key(aid, ds, "help_assistant_do") == PLATFORM_KEY
        # The Q&A's Anthropic row is NOT shared: a Claude pin bills the agency.
        try:
            await llm_client._tenant_api_key(aid, an, "help_assistant_do")
            raise AssertionError("the platform Claude key leaked to the draft")
        except LLMKeyError:
            pass
        # …and the platform key still pays for no lane.
        try:
            await llm_client._tenant_api_key(aid, ds, "gen_info")
            raise AssertionError("the platform key leaked to gen_info")
        except LLMKeyError:
            pass
        # End to end on the route: the draft goes out (spied at chat).
        spy = _patch(_Spy(json.dumps(_pilot_intent())))
        out = await draft(DraftBody(request=PILOT, account_id=aid))
    assert out["flow"] == "mass_premade" and out["error"] is None, out
    assert spy.calls[0]["account_id"] == aid, spy.calls[0]
    # An agency's own key still beats the platform's.
    aid2 = "acc_draft_ownkey"
    await _owned(aid2, agency_key="sk-agency-own")
    with _PlatformKey(HELP_ASSISTANT_DEEPSEEK_KEY=PLATFORM_KEY):
        assert await llm_client._tenant_api_key(aid2, ds, "help_assistant_do") == "sk-agency-own"


async def case_platform_paid_drafts_stop_at_the_accounts_daily_cap():
    """The bound is Q&A's: the account's daily cost cap, enforced in
    llm_client._reserve BEFORE any wire call. Real chat(), no spy; the wire
    (`_fire`) explodes if reached, so nothing is ever bought."""
    aid = "acc_draft_capped"
    await _owned(aid, cap_cents=0)
    real_fire = llm_client._fire
    llm_client.chat = REAL_CHAT

    async def no_wire(*a, **kw):
        raise AssertionError("a capped draft reached the provider")
    llm_client._fire = no_wire
    try:
        async def _lists(_a):
            return LISTS
        assistant_draft._read_lists = _lists
        with _PlatformKey(HELP_ASSISTANT_DEEPSEEK_KEY=PLATFORM_KEY):
            out = await draft(DraftBody(request=PILOT, account_id=aid))
    finally:
        llm_client._fire = real_fire
    assert out["error"] == "cap" and out["flow"] is None, out
    assert "budget" in out["answer"], out["answer"]


async def case_do_caps_no_key_only_when_neither_agency_nor_platform_key_resolves():
    llm_client.chat = REAL_CHAT
    aid = "acc_draft_caps"
    await _owned(aid)
    with _PlatformKey():
        assert await do_caps(account_id=aid) == {"account_id": aid, "can_do": False, "reason": "no_key"}
    with _PlatformKey(HELP_ASSISTANT_DEEPSEEK_KEY=PLATFORM_KEY):
        assert await do_caps(account_id=aid) == {"account_id": aid, "can_do": True, "reason": None}
    aid2 = "acc_draft_caps_own"
    await _owned(aid2, agency_key="sk-agency-own")
    with _PlatformKey():
        assert await do_caps(account_id=aid2) == {"account_id": aid2, "can_do": True, "reason": None}
    # A Claude pin with no agency Anthropic key: the platform's DeepSeek key
    # does not pay for it → no_key, said up front.
    aid3 = "acc_draft_caps_claude"
    await _owned(aid3, pin="claude-sonnet-5-5")
    with _PlatformKey(HELP_ASSISTANT_DEEPSEEK_KEY=PLATFORM_KEY,
                      HELP_ASSISTANT_ANTHROPIC_KEY="sk-deployment-claude"):
        assert (await do_caps(account_id=aid3))["reason"] == "no_key"


# ── Claude: no JSON mode, the JSON parsed out of plain text ───────────

def case_parse_json_object_takes_fences_and_prose():
    obj = {"flow": "mass_premade", "name": "a {curly} \"name\"", "captions": {"count": 1}}
    js = json.dumps(obj)
    for text in (js, f"```json\n{js}\n```", f"```\n{js}\n```",
                 f"Here is the JSON you asked for:\n\n```json\n{js}\n```\nLet me know!",
                 f"Sure — {js} — done.", f"{{not json}} then {js}",
                 f"```json\n{js}"):                       # an unclosed fence
        assert assistant_draft.parse_json_object(text) == obj, text
    for bad in ("", "no json here", "{broken: ", "```json\n```"):
        try:
            assistant_draft.parse_json_object(bad)
            raise AssertionError(f"parsed {bad!r}")
        except ValueError:
            pass
    assert assistant_draft.response_format_for("deepseek-v4-flash") == {"type": "json_object"}
    for m in ("claude-sonnet-5-5", "claude-opus-5-5"):
        assert assistant_draft.response_format_for(m) is None, m


async def case_a_claude_pin_drafts_without_json_mode():
    aid = "acc_draft_claude"
    await _owned(aid, pin="claude-opus-5-5")
    fenced = "Here you go:\n```json\n" + json.dumps(_pilot_intent()) + "\n```"
    spy = _patch(_Spy(fenced))
    out = await draft(DraftBody(request=PILOT, account_id=aid))
    kw = spy.calls[0]
    assert kw["model"] == "claude-opus-5-5" and "response_format" not in kw, kw
    assert out["flow"] == "mass_premade" and out["error"] is None, out
    assert out["slots"]["includes"] == ["fans", "following"] and len(out["slots"]["captions"]) == 10
    _patch(_Spy("I can't help with that."))
    out = await draft(DraftBody(request=PILOT, account_id=aid))
    assert (out["error"], out["answer"]) == ("bad_draft", assistant_draft.BAD_DRAFT_ANSWER), out


# ── The eval seam ─────────────────────────────────────────────────────

EVAL_CTX = assistant_draft.EvalContext(
    lists=[{"id": 501, "name": "VIP"}, {"id": 503, "name": "MASSdmEXCLUDE"}],
    folders=[_f("Daytime", fid="11", sfw=40, suggestive=5, unknown=15),
             _f("Spicy", fid="13", sfw=2, explicit=20)],
    existing_names=["Hourly SFW mass"])


async def case_draft_for_eval_runs_the_real_prompt_and_returns_usage():
    spy = _patch(_Spy(json.dumps(_pilot_intent())))
    out, usage = await assistant_draft.draft_for_eval(PILOT, EVAL_CTX, "deepseek-v4-flash")
    kw = spy.calls[0]
    assert kw["account_id"] is None and kw["purpose"] == "help_assistant_do", kw
    assert kw["response_format"] == {"type": "json_object"}, kw
    sys_msg, user_msg = kw["messages"]
    assert sys_msg["content"] == assistant_draft.system_prompt()
    assert "VIP" in user_msg["content"] and "Daytime (60 photos)" in user_msg["content"]
    assert out["flow"] == "mass_premade" and out["error"] is None and out["id"] is None, out
    assert out["slots"]["folder"]["id"] == "11" and out["slots"]["name"] == "Hourly SFW mass 2", out
    assert usage == {"model": "deepseek-v4-flash", "tokens_in": 100, "tokens_cached": 90,
                     "tokens_cache_write": 0, "tokens_out": 10, "cost_cents": 0.0,
                     "cost_millicents": 0}, usage
    _patch(_Spy(raises=LLMHTTPError("502", status=502)))
    out, usage = await assistant_draft.draft_for_eval(PILOT, EVAL_CTX, "deepseek-v4-flash")
    assert out["error"] == "provider" and usage["cost_millicents"] == 0, (out, usage)


async def case_draft_for_eval_prices_claude_usage_from_the_provider_reply():
    """Real llm_client.chat on Claude Sonnet, faked only at the wire (`_fire`):
    the house ANTHROPIC_API_KEY pays (account None), no response_format goes
    out, and usage — cache read/write + output incl. thinking — is priced by
    llm_models, not estimated."""
    llm_client.chat = REAL_CHAT
    seen = {}
    native = {"id": "msg_1", "model": "claude-sonnet-5-5", "stop_reason": "end_turn",
              "content": [{"type": "thinking", "thinking": "hmm"},
                          {"type": "text", "text": "```json\n" + json.dumps(_pilot_intent()) + "\n```"}],
              "usage": {"input_tokens": 1000, "cache_creation_input_tokens": 2000,
                        "cache_read_input_tokens": 3000, "output_tokens": 500}}

    async def wire(url, headers, body, **kw):
        seen.update(url=url, headers=headers, body=body)
        return native, 7
    real_fire = llm_client._fire
    llm_client._fire = wire
    try:
        with _PlatformKey(ANTHROPIC_API_KEY="sk-house-claude"):
            out, usage = await assistant_draft.draft_for_eval(PILOT, EVAL_CTX, "claude-sonnet-5-5")
    finally:
        llm_client._fire = real_fire
    assert seen["url"].endswith("/messages") and seen["headers"]["x-api-key"] == "sk-house-claude"
    assert "response_format" not in seen["body"] and seen["body"]["thinking"] == {"type": "adaptive"}
    assert out["flow"] == "mass_premade" and out["error"] is None, out
    # Sonnet 5.5: 0.2 in / 0.25 write / 0.01 hit / 1.0 out (cents per 1k).
    want_mc = round((1000 * 0.2 + 2000 * 0.25 + 3000 * 0.01 + 500 * 1.0) / 1000 * 100)
    assert want_mc == 123 == llm_client._cost_millicents("claude-sonnet-5-5", 6000, 500, 3000, 2000)
    assert usage == {"model": "claude-sonnet-5-5", "tokens_in": 6000, "tokens_cached": 3000,
                     "tokens_cache_write": 2000, "tokens_out": 500, "cost_cents": 1.23,
                     "cost_millicents": 123}, usage


_harness.run()
