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
    assert "help_assistant_do" in JSON_OBJECT_PURPOSES       # a Claude pin is refused (no json_object)
    assert llm_client.feature_label("help_assistant_do") == "The help assistant"


_harness.run()
