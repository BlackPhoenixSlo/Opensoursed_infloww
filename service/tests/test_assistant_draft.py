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
from datetime import date, datetime  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"  # read per call; a case flips it back

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

import assistant_draft  # noqa: E402
import assistant_report  # noqa: E402
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

def case_a_mass_draft_for_another_feature_or_an_existing_rule_is_vetoed():
    v = assistant_draft.vetoed
    for req in ("set up auto posting from the beach folder", "send new fans a hello message automatically",
                "update my auto mass interval to 30 min",
                "remove whales from my Morning mass"):
        assert v(req, refine=False), req
    for req in ("Settuo a mass post with nice captions and sfw photos", "delete the previous one each time 40 captions",
                "auto mass every hour to fans", "make a mass for whales from the beach folder",
                "update: every 3 hours, to my VIP list"):
        assert not v(req, refine=False), req
    assert not v("remove whales from my Morning mass", refine=True)       # a refine edits the draft, not a rule
    o = assistant_draft.interpret(json.dumps(_pilot_intent()), request="set up auto posting from the beach folder",
                                  lists=[], folders=[], existing=[])
    assert (o.flow, o.answer) == (None, assistant_draft.UNSUPPORTED_ANSWER), o


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
    assert len(shots) == 12, len(shots)
    every = [Intent.model_validate(json.loads(s)) for s in shots]
    parsed, exports = every[:9], every[9:]                        # the 3 report_export shots come last
    requests = re.findall(r"^REQUEST: (.*)$", assistant_draft._FEWSHOTS, re.M)[9:]
    ctx = assistant_report.ReportCtx((("a1", "Luna"), ("a2", "Mia Rose")), ((1, "Anna"), (2, "Marco")),
                                     "Europe/London", date(2026, 3, 14), "monday", frozenset())
    got = [assistant_report.resolve_export(i.report, ctx, request=r) for i, r in zip(exports, requests)]
    assert all(d is not None and not d.unresolved for d, _ in got), got
    assert exports[0].report["creators"] == ["Mia"], "the shot must keep the request's words (F3)"
    mia, chatters, top = (d.slots for d, _ in got)
    assert (mia["recipe"]["creators"], mia["window"]["from"], mia["window"]["to"], mia["format"]) == (
        ["a2"], "2026-02-01", "2026-02-28", "xlsx"), mia
    assert (chatters["recipe"]["dataset"], chatters["recipe"]["kinds"], chatters["window"]["from"]) == (
        "employee_sales", ["tip", "ppv"], "2026-03-09"), chatters
    assert (top["recipe"]["sort"], top["recipe"]["limit"], top["recipe"]["window"]) == (
        "total", 20, {"from": "2025-12-15", "to": "2026-03-14"}), top
    assert parsed[0].flow == "mass_premade" and len(parsed[0].captions.generated) == 10
    assert parsed[-1].flow is None and parsed[-6].every is None   # a mass with no timing is still one
    unsend, pause = parsed[-5], parsed[-4]                        # mass_edit: unsend off ≠ switch off
    assert unsend.flow == pause.flow == "mass_edit"
    assert (unsend.edit.scope, unsend.edit.changes.unsend_after_hours, unsend.edit.changes.disable_rule) == (
        "all", 0, False)
    assert (pause.edit.scope, pause.edit.match, pause.edit.changes.disable_rule) == ("this", "Morning mass", True)
    clock, interval = parsed[-3], parsed[-2]                      # auto_story: a clock time vs "every"
    assert clock.flow == interval.flow == "auto_story"
    beach = assistant_draft.resolve_story(clock, folders=[_f("Beach pics", "12", sfw=4)]).slots
    assert (beach["mode"], beach["times"], beach["per_run"], beach["hours_to_live"]) == (
        "clock", ["09:00", "20:00"], 2, 12), beach
    safe = assistant_draft.resolve_story(interval, folders=[_f("Daytime", "11", sfw=4)]).slots
    assert (safe["mode"], safe["every_hours"], safe["hours_to_live"], safe["max_runs"]) == (
        "interval", 4, 0, 30), safe
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
    _patch(_Spy(json.dumps({"flow": None})))
    out = await _draft("send a mass to VIP right now")     # names a mass: says what would work, not "ask Q&A"
    assert (out["flow"], out["answer"]) == (None, assistant_draft.ONE_OFF_MASS_ANSWER), out


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

    async def refuse(pages, account_id):   # neither do-mode page: refused before any call
        assert pages in (("/growth/auto-mass",), ("/growth/auto-story",)), pages
        return "Your role does not allow it"
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
    # DeepSeek dropped the outer "}": closed, never the nested {"count": 1} (which read as flow null)
    assert assistant_draft.parse_json_object(js[:-1]) == obj
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
    assert usage.pop("raw") and usage == {"model": "deepseek-v4-flash", "tokens_in": 100, "tokens_cached": 90,
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
    assert usage.pop("raw") and usage == {"model": "claude-sonnet-5-5", "tokens_in": 6000, "tokens_cached": 3000,
                     "tokens_cache_write": 2000, "tokens_out": 500, "cost_cents": 1.23,
                     "cost_millicents": 123}, usage


# ── mass_edit (spec D11): bulk edits of existing Auto mass rules ──────

import assistant_edit  # noqa: E402
from assistant_edit import Skip, apply_changes, clean_changes, plan_rules, RuleRow, rule_version  # noqa: E402

OWNER_PHRASE = "please turn off auto mass unsend for every model"


def _msg(**kw) -> dict:
    return {"text": "hi", "user_lists": ["fans"], "media_folder_id": 11, **kw}


def case_clean_changes_whitelists_and_clamps():
    assert clean_changes({"unsend_after_hours": 0, "online_only": "yes", "every_seconds": 60,
                          "price": 1000, "media_count": 99, "exclude_last_chat_hours": -3,
                          "disable_rule": False, "is_enabled": True, "text": "x"}) == {
        "unsend_after_hours": 0, "every_seconds": 300, "price": 200, "media_count": 40,
        "exclude_last_chat_hours": 0}
    assert clean_changes({"unsend_after_hours": 500, "price": 1, "every_seconds": True}) == {
        "unsend_after_hours": 168.0, "price": 3}
    assert clean_changes({"disable_rule": True, "online_only": False}) == {"disable_rule": True,
                                                                          "online_only": False}
    assert clean_changes("junk") == {} and clean_changes({"price": float("nan")}) == {}


def case_apply_changes_table():
    P = lambda *ms: {"messages": list(ms)}     # noqa: E731
    table = [
        # changes, payload, every, enabled → payload messages, every, enabled, diff fields
        ({"unsend_after_hours": 0}, P(_msg(unsend_after_hours=8)), 3600, True,
         [_msg()], 3600, True, ["unsend_after_hours"]),
        ({"unsend_after_hours": 2}, P(_msg(), _msg(unsend_after_hours=8)), 3600, False,
         [_msg(unsend_after_hours=2), _msg(unsend_after_hours=2)], 3600, False, ["unsend_after_hours"]),
        ({"online_only": False}, P(_msg(online_only=True)), 3600, True, [_msg()], 3600, True, ["online_only"]),
        ({"online_only": True}, P(_msg()), 3600, True, [_msg(online_only=True)], 3600, True, ["online_only"]),
        ({"every_seconds": 7200}, P(_msg()), 3600, True, [_msg()], 7200, True, ["every_seconds"]),
        ({"exclude_last_chat_hours": 0}, P(_msg(exclude_last_chat_hours=1)), 3600, True,
         [_msg()], 3600, True, ["exclude_last_chat_hours"]),
        ({"price": 15, "media_count": 3}, P(_msg()), 3600, True,
         [_msg(price=15, media_count=3)], 3600, True, ["price", "media_count"]),
        ({"disable_rule": True}, P(_msg()), 3600, True, [_msg()], 3600, False, ["is_enabled"]),
        ({"disable_rule": True}, P(_msg()), 3600, False, [_msg()], 3600, False, []),      # already off
        ({"unsend_after_hours": 0}, P(_msg()), 3600, True, [_msg()], 3600, True, []),     # already no unsend
    ]
    for ch, payload, every, enabled, want_msgs, want_every, want_enabled, fields in table:
        before = json.dumps(payload)
        out, ev, en, diffs = apply_changes("mass_premade", payload, every, enabled, ch)
        assert out["messages"] == want_msgs, (ch, out)
        assert (ev, en, [d["field"] for d in diffs]) == (want_every, want_enabled, fields), (ch, ev, en, diffs)
        assert json.dumps(payload) == before, "apply_changes mutated its input"
    d = apply_changes("mass_premade", P(_msg(unsend_after_hours=8)), 3600, True, {"unsend_after_hours": 0})[3]
    assert d == [{"field": "unsend_after_hours", "label": "Unsend after", "before": 8, "after": None}], d
    for ch, payload, every, why in [
            ({"price": 10}, P({"text": "x", "user_lists": ["fans"]}), 3600, "a price needs photos"),
            ({"media_count": 2}, P({"text": "x"}), 3600, "photo count needs"),
            ({"online_only": True}, P({"text": "x"}), 3600, "online-only needs a fan list"),
            ({"every_seconds": 600}, P(_msg()), None, "runs at set times"),
            ({"unsend_after_hours": 0}, {}, 3600, "has no message")]:
        try:
            apply_changes("mass_premade", payload, every, True, ch)
        except Skip as e:
            assert why in str(e), (ch, e)
        else:
            raise AssertionError(f"{ch} did not skip")
    try:
        apply_changes("auto_posts", P(_msg()), 3600, True, {"unsend_after_hours": 0})
    except Skip:
        pass
    else:
        raise AssertionError("an unknown kind was edited")


def case_online_only_off_also_clears_filters_online():
    # the sender reads filters.online as online-only too (review P1): off must clear it, never a silent no-op
    m = _msg(filters={"online": 1})
    out, _, _, diffs = apply_changes("mass_premade", {"messages": [m]}, 3600, True, {"online_only": False})
    assert "filters" not in out["messages"][0] and [d["field"] for d in diffs] == ["online_only"], (out, diffs)
    m = _msg(filters={"online": "1", "min_spent": 5})
    out, *_ = apply_changes("mass_premade", {"messages": [m]}, 3600, True, {"online_only": False})
    assert out["messages"][0]["filters"] == {"min_spent": 5}, out
    try:   # online fans were its only audience: clearing it would send to nobody
        apply_changes("mass_premade", {"messages": [{"text": "hi", "filters": {"online": 1}}]}, 3600, True,
                      {"online_only": False})
        raise AssertionError("expected Skip")
    except assistant_edit.Skip:
        pass


def case_apply_changes_never_turns_a_rule_on():
    for ch in ({"is_enabled": True}, {"disable_rule": False}, {"enabled": True, "unsend_after_hours": 2},
               {"disable_rule": "false"}):
        _, _, en, diffs = apply_changes("mass_premade", {"messages": [_msg()]}, 3600, False, ch)
        assert en is False and all(d["field"] != "is_enabled" for d in diffs), (ch, diffs)


def case_plan_groups_rules_per_model_and_counts_already_and_skipped():
    rows = [RuleRow(1, "b", "Night mass", "mass_premade", json.dumps({"messages": [_msg(unsend_after_hours=8)]}),
                    '{"every_seconds": 3600}', True),
            RuleRow(2, "a", "Morning mass", "mass_premade", json.dumps({"messages": [_msg(unsend_after_hours=4)]}),
                    '{"every_seconds": 3600}', False),
            RuleRow(3, "a", "Hourly", "mass_premade", json.dumps({"messages": [_msg()]}), "{}", True),
            RuleRow(4, "a", "Empty", "mass_premade", "{}", "{}", True),
            RuleRow(5, "a", "Post", "auto_posts", json.dumps({"posts": [_msg()]}), "{}", True)]
    plan = plan_rules(rows, {"unsend_after_hours": 0}, None, {"a": "Alice", "b": "Bea"})
    assert [(r["id"], r["account_name"]) for r in plan.rules] == [(2, "Alice"), (1, "Bea")], plan.rules
    assert plan.already == 1 and [x["id"] for x in plan.skipped] == [4], plan
    assert plan.rules[0]["version"] == rule_version(rows[1].steps_json, rows[1].trigger_json, False)
    assert plan.rules[1]["is_enabled"] is True and plan.rules[1]["diffs"][0]["before"] == 8
    named = plan_rules(rows, {"unsend_after_hours": 0}, "the night MASS", {})
    assert [r["id"] for r in named.rules] == [1], named.rules
    assert [r["id"] for r in plan_rules(rows, {"unsend_after_hours": 0}, "auto masses", {}).rules] == [2, 1]
    assert plan_rules(rows, {"unsend_after_hours": 0}, "Gym", {}).rules == []


def case_a_mass_edit_draft_is_not_vetoed_and_resolves_the_change_spec():
    v = assistant_draft.vetoed
    assert v("pause my Morning mass", refine=False) and not v("pause my Morning mass", refine=False,
                                                               flow="mass_edit")
    assert v("pause my auto posting", refine=False, flow="mass_edit")     # another feature, no mass word
    intent = {"flow": "mass_edit", "edit": {"scope": "all", "match": None, "changes": {
        "unsend_after_hours": 0, "online_only": None, "every": None, "exclude_last_chat_hours": None,
        "price": None, "media_count": None, "disable_rule": None}}, "assumptions": [], "unresolved": []}
    o = assistant_draft.interpret(json.dumps(intent), request=OWNER_PHRASE, lists=[], folders=[], existing=[])
    assert o.flow == "mass_edit" and o.draft.slots == {
        "scope": "all", "match": None, "changes": {"unsend_after_hours": 0}, "rules": [], "already": 0,
        "skipped": []}, o
    assert "unsend off" in o.answer and "every model" in o.answer, o.answer
    # price on every model: dropped + said; nothing else left → the "what I can do" sentence
    intent["edit"]["changes"] = {"price": 20}
    o = assistant_draft.interpret(json.dumps(intent), request="set price to $20 on every model's auto mass",
                                  lists=[], folders=[], existing=[])
    assert (o.flow, o.answer) == (None, assistant_draft.ONE_OFF_MASS_ANSWER), o
    intent["edit"]["changes"] = {"price": 20, "unsend_after_hours": 0}
    o = assistant_draft.interpret(json.dumps(intent), request="no unsend, $20, every model", lists=[], folders=[],
                                  existing=[])
    assert o.draft.slots["changes"] == {"unsend_after_hours": 0}, o.draft.slots
    assert assistant_edit.ONE_MODEL_NOTE in o.draft.unresolved, o.draft.unresolved
    # scope "all" without a word naming several models → this model, said (eval: "pause all auto masses")
    o = assistant_draft.interpret(json.dumps(intent), request="pause all auto masses", lists=[], folders=[],
                                  existing=[])
    assert o.draft.slots["scope"] == "this" and assistant_draft.ONLY_THIS_NOTE in o.draft.assumptions, o.draft
    intent["edit"] = {"scope": "this", "match": "Morning", "changes": {"every": {"value": 2, "unit": "hours"}}}
    o = assistant_draft.interpret(json.dumps(intent), request="x", lists=[], folders=[], existing=[])
    assert o.draft.slots["changes"] == {"every_seconds": 7200} and o.draft.slots["match"] == "Morning"
    o = assistant_draft.interpret(json.dumps({"flow": "mass_edit"}), request="edit my mass", lists=[],
                                  folders=[], existing=[])
    assert (o.flow, o.answer) == (None, assistant_draft.ONE_OFF_MASS_ANSWER), o


EA, EB, EC = "acc_edit_a", "acc_edit_b", "acc_edit_c"


async def _seed_edit() -> dict[str, int]:
    """Three models with an hourly Auto mass, unsend 8h. A on, B off; C's
    caller has no Auto Mass opt-in (patched per case)."""
    ids = {}
    async with get_session() as s:
        for aid, on in ((EA, True), (EB, False), (EC, True)):
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid, nickname=f"Model {aid[-1].upper()}"))
            r = AutomationRule(account_id=aid, name=f"Hourly {aid[-1]}", kind="mass_premade",
                               trigger_json='{"every_seconds": 3600}', is_enabled=on,
                               steps_json=json.dumps({"messages": [_msg(unsend_after_hours=8)]}))
            s.add(r)
            await s.flush()
            ids[aid] = r.id
    return ids


async def _rule(rid: int) -> AutomationRule:
    async with get_session() as s:
        return await s.get(AutomationRule, rid)


async def case_the_owner_phrase_edits_every_opted_in_model_and_nothing_else():
    ids = await _seed_edit()
    intent = {"flow": "mass_edit", "edit": {"scope": "all", "match": None,
                                            "changes": {"unsend_after_hours": 0}}}
    _patch(_Spy(json.dumps(intent)))
    real = assistant_draft.opt_in_refusal

    async def refuse_c(pages, account_id):
        return "no Auto Mass" if account_id == EC else None
    assistant_draft.opt_in_refusal = refuse_c
    token = auth._request_user.set(auth.AuthedUser("u_edit", "edit", frozenset({EA, EB, EC})))
    try:
        out = await draft(DraftBody(request=OWNER_PHRASE, account_id=EA))
        assert out["flow"] == "mass_edit" and out["error"] is None, out
        mine = [r for r in out["slots"]["rules"] if r["id"] in ids.values()]
        assert sorted(r["account_id"] for r in mine) == [EA, EB], out["slots"]["rules"]
        assert {r["account_name"] for r in mine} == {"Model A", "Model B"}
        assert "2 Auto mass rules on 2 models" in out["summary"], out["summary"]
        refs = [{"id": r["id"], "version": r["version"]} for r in mine] + [
            {"id": ids[EC], "version": "x"}]
        res = await assistant_draft.edit_apply(assistant_draft.EditApplyBody(
            account_id=EA, rules=refs, changes={**out["slots"]["changes"], "is_enabled": True, "text": "hacked"}))
    finally:
        auth._request_user.reset(token)
        assistant_draft.opt_in_refusal = real
    by = {r["id"]: r for r in res["results"]}
    assert by[ids[EA]]["ok"] and by[ids[EB]]["ok"] and res["changed"] == 2, res
    assert by[ids[EC]] == {"id": ids[EC], "ok": False, "reason": "not allowed"}, by[ids[EC]]
    a, b, c = (await _rule(ids[EA]), await _rule(ids[EB]), await _rule(ids[EC]))
    for r, on in ((a, True), (b, False)):
        msg = json.loads(r.steps_json)["messages"][0]
        assert "unsend_after_hours" not in msg and msg["text"] == "hi", msg
        assert r.is_enabled is on, (r.id, r.is_enabled)              # never enabled, never disabled
    assert json.loads(c.steps_json)["messages"][0]["unsend_after_hours"] == 8, c.steps_json


async def case_apply_skips_a_rule_changed_since_the_plan_and_reapplies_to_the_fresh_row():
    ids = await _seed_edit()
    a = await _rule(ids[EA])
    seen = rule_version(a.steps_json, a.trigger_json, a.is_enabled)
    async with get_session() as s:                    # someone edits the rule after the card showed it
        r = await s.get(AutomationRule, ids[EA])
        r.steps_json = json.dumps({"messages": [_msg(unsend_after_hours=8, text="edited")]})
    res = await assistant_draft.edit_apply(assistant_draft.EditApplyBody(
        account_id=EA, rules=[{"id": ids[EA], "version": seen}], changes={"unsend_after_hours": 0}))
    assert res["results"] == [{"id": ids[EA], "ok": False, "reason": assistant_edit.CHANGED_SINCE}], res
    a = await _rule(ids[EA])
    fresh = rule_version(a.steps_json, a.trigger_json, a.is_enabled)
    res = await assistant_draft.edit_apply(assistant_draft.EditApplyBody(
        account_id=EA, rules=[{"id": ids[EA], "version": fresh}],
        changes={"unsend_after_hours": 0, "disable_rule": True, "payload": {"messages": []}}))
    assert res["changed"] == 1, res
    a = await _rule(ids[EA])
    assert json.loads(a.steps_json) == {"messages": [_msg(text="edited")]}, a.steps_json   # fresh row kept
    assert a.is_enabled is False


async def case_price_on_another_model_is_skipped_at_apply():
    ids = await _seed_edit()
    b = await _rule(ids[EB])
    res = await assistant_draft.edit_apply(assistant_draft.EditApplyBody(
        account_id=EA, rules=[{"id": ids[EB], "version": rule_version(b.steps_json, b.trigger_json, b.is_enabled)}],
        changes={"price": 20}))
    assert res["results"][0]["ok"] is False and "one model" in res["results"][0]["reason"], res


async def case_an_edit_with_nothing_to_change_is_flow_null_with_why():
    await _seed_edit()
    _patch(_Spy(json.dumps({"flow": "mass_edit", "edit": {"scope": "this", "match": "Gym",
                                                          "changes": {"unsend_after_hours": 0}}})))
    out = await draft(DraftBody(request="stop unsending the gym mass", account_id=EA))
    assert out["flow"] is None and out["error"] is None and 'called "Gym"' in out["answer"], out


def case_the_apply_route_is_served_over_http():
    client = _harness.make_client()
    r = client.post("/admin/assistant/edit/apply", json={"account_id": AID, "rules": [], "changes": {}})
    assert r.status_code == 422, r.status_code
    r = client.post("/admin/assistant/edit/apply", json={"account_id": AID, "rules": [{"id": 1, "version": "v"}],
                                                          "changes": {"bogus": 1}})
    assert r.status_code == 422 and "nothing to change" in r.text, (r.status_code, r.text)


def case_create_extras_are_clamped_and_need_a_folder():
    d = _resolve(_pilot_intent(price=500, media_count=3, exclude_replied_hours=0, exclude_inbound_hours=4,
                               unread_limit=50, recent_chat_hours=12, recent_chat_limit=5000),
                 folders=[_f("Daytime", "11", sfw=5)])
    s = d.slots
    assert (s["price"], s["media_count"], s["exclude_replied_hours"], s["exclude_inbound_hours"]) == (200, 3, 0, 4), s
    assert (s["unread_limit"], s["recent_chat_hours"], s["recent_chat_limit"]) == (50, 12, 1000), s
    assert any("allowed range" in a for a in d.assumptions), d.assumptions
    d = _resolve(_pilot_intent(folder={"want": "none", "name": None}, price=10, media_count=2))
    assert d.slots["price"] == 10 and d.slots["media_count"] is None, d.slots
    assert any("price needs photos" in u for u in d.unresolved) and any("needs a folder" in u for u in d.unresolved)
    d = _resolve(_pilot_intent())
    assert all(d.slots[k] is None for k in assistant_draft.EXTRA_KEYS), d.slots



# ── auto_story (spec D13) ─────────────────────────────────────────────

def _story(**over) -> dict:
    d = {"flow": "auto_story", "folder": {"want": "named", "name": "Daytime"}, "every": None,
         "times": [], "per_run": None, "hours_to_live": None, "max_runs": None}
    d.update(over)
    return d


def _rs(intent: dict, folders=None):
    return assistant_draft.resolve_story(Intent.model_validate(intent), folders=list(
        folders if folders is not None else [_f("Daytime", "11", sfw=8), _f("Empty", "19")]))


def case_a_story_draft_needs_a_story_word_and_is_never_an_edit_or_a_mass():
    v = lambda r, **kw: assistant_draft.vetoed(r, refine=kw.get("refine", False), flow="auto_story")  # noqa: E731
    for req in ("auto story every 3 hours", "post a story every morning automatically", "daily story at 9pm please",
                "historia automática cada 4 horas", "stories every 4 hours from beach pics"):
        assert not v(req), req
    for req in ("auto mass every 3 hours to fans saying check my new story", "auto post every 2 hours",
                "change my auto story to every 2 hours", "delete my auto story", "turn on my auto story",
                "show my message history"):
        assert v(req), req
    assert v("auto story every 3 hours", refine=True)                     # a refine is of an Auto mass plan
    o = assistant_draft.interpret(json.dumps(_story()), request="change my auto story to every 2 hours",
                                  lists=[], folders=[], existing=[])
    assert (o.flow, o.answer) == (None, assistant_draft.UNSUPPORTED_ANSWER), o


def case_story_slots_are_clamped_and_default_like_the_blank_form():
    rows = [   # intent overrides → (mode, times, every_hours, per_run, hours_to_live, max_runs)
        ({}, ("clock", ["09:00"], 6, 1, 6, None)),
        ({"times": ["21:00", "9:00", "9", "25:00", "x"]}, ("clock", ["09:00", "21:00"], 6, 1, 6, None)),
        ({"times": ["6pm", "12am", "12 PM", "9:30 a.m.", "13pm"]}, ("clock", ["00:00", "09:30", "12:00", "18:00"], 6, 1, 6, None)),
        ({"every": {"value": 3, "unit": "hours"}}, ("interval", ["09:00"], 3, 1, 6, None)),
        ({"every": {"value": 90, "unit": "minutes"}}, ("interval", ["09:00"], 2, 1, 6, None)),
        ({"every": {"value": 500, "unit": "hours"}}, ("interval", ["09:00"], 168, 1, 6, None)),
        ({"times": ["08:00"], "every": {"value": 3, "unit": "hours"}}, ("clock", ["08:00"], 6, 1, 6, None)),
        ({"per_run": 50, "hours_to_live": 0, "max_runs": 5000}, ("clock", ["09:00"], 6, 10, 0, 1000)),
        ({"hours_to_live": 0.2, "max_runs": -3, "per_run": 0}, ("clock", ["09:00"], 6, 1, 1, None)),
        ({"unsend_after_hours": 12}, ("clock", ["09:00"], 6, 1, 12, None)),
        ({"hours_to_live": 900}, ("clock", ["09:00"], 6, 1, 168, None)),
    ]
    for over, want in rows:
        d = _rs(_story(**over))
        s = d.slots
        assert tuple(s[k] for k in ("mode", "times", "every_hours", "per_run", "hours_to_live", "max_runs")) == want, (
            over, s)
        assert set(s) == set(assistant_draft.STORY_SLOT_KEYS), s
        assert not any(re.search(r"(^|_)(is_)?enabled$|^dry_run$|^run_now$|^live$", k) for k in s), s
    assert any("09:00" in a for a in _rs(_story()).assumptions)
    assert any("deleted after 6 h" in a for a in _rs(_story()).assumptions)
    assert not any("deleted after" in a for a in _rs(_story(hours_to_live=12)).assumptions)


def case_a_story_folder_must_hold_photos():
    d = _rs(_story())
    assert d.slots["folder"]["id"] == "11" and d.unresolved == [], d
    d = _rs(_story(folder={"want": "named", "name": "Empty"}))
    assert d.slots["folder"] is None and any("no photos" in u for u in d.unresolved), d
    d = _rs(_story(folder={"want": "named", "name": "Nope"}))
    assert d.slots["folder"] is None and any('"Nope"' in u for u in d.unresolved), d
    d = _rs(_story(folder={"want": "none", "name": None}))
    assert d.slots["folder"] is None and d.unresolved == [assistant_draft.NO_STORY_FOLDER_NOTE], d
    d = _rs(_story(folder={"want": "sfw", "name": None}))
    assert d.slots["folder"]["name"] == "Daytime", d
    s = assistant_draft.story_summary(_rs(_story(times=["09:00", "20:00"], per_run=2, max_runs=30)).slots)
    assert s == ('Auto Story: 2 stories daily at 09:00, 20:00; photos from "Daytime"; each deleted after 6 h; '
                 "stops after 30 runs. It's saved switched off — you turn it on."), s


async def case_a_story_draft_is_gated_by_the_story_opt_in_and_one_rule_per_account():
    await _seed()
    req = "auto story from the daytime folder every 4 hours"
    _patch(_Spy(json.dumps(_story(every={"value": 4, "unit": "hours"}))))
    out = await _draft(req)
    assert (out["flow"], out["error"]) == ("auto_story", None), out
    assert out["slots"]["folder"]["id"] == "11" and out["slots"]["every_hours"] == 4, out["slots"]
    assert out["answer"] == out["summary"] and "switched off" in out["answer"], out

    real, seen = assistant_draft.opt_in_refusal, []

    async def refuse_story(pages, account_id):
        seen.append(pages)
        return "no Auto Story" if pages == ("/growth/auto-story",) else None
    assistant_draft.opt_in_refusal = refuse_story
    try:
        _patch(_Spy(json.dumps(_story(every={"value": 4, "unit": "hours"}))))
        out = await _draft(req)
    finally:
        assistant_draft.opt_in_refusal = real
    assert ("/growth/auto-story",) in seen, seen
    assert (out["flow"], out["error"], out["answer"], out["slots"]) == (
        None, "not_allowed", assistant_draft.STORY_NOT_ALLOWED_ANSWER, None), out

    async with get_session() as ses:
        (await ses.get(Account, AID)).nickname = "Mia"
        ses.add(AutomationRule(account_id=AID, name="Auto stories", kind="auto_stories",
                               trigger_json="{}", steps_json="{}", is_enabled=True))
    try:
        _patch(_Spy(json.dumps(_story(every={"value": 4, "unit": "hours"}))))
        out = await _draft(req)
    finally:
        async with get_session() as ses:
            for r in (await ses.execute(select(AutomationRule).where(
                    AutomationRule.account_id == AID, AutomationRule.kind == "auto_stories"))).scalars():
                await ses.delete(r)
    assert (out["flow"], out["slots"], out["error"]) == (None, None, None), out
    assert out["answer"] == ("Auto Story is already set up for Mia — open it to edit: My Automations → Auto Story. "
                             "I only set up a new one."), out


async def case_story_only_role_gets_story_drafts_and_mass_is_refused_after_the_call():
    await _seed()
    real = assistant_draft.opt_in_refusal

    async def mass_refused(pages, account_id):
        return "no Auto Mass" if pages == ("/growth/auto-mass",) else None
    assistant_draft.opt_in_refusal = mass_refused
    try:
        caps = await do_caps(account_id=AID)
        _patch(_Spy(json.dumps(_story(every={"value": 4, "unit": "hours"}))))
        story = await _draft("auto story from the daytime folder every 4 hours")
        _patch(_Spy(json.dumps(_pilot_intent())))
        mass = await _draft()
    finally:
        assistant_draft.opt_in_refusal = real
    assert caps["can_do"] is True, caps
    assert (story["flow"], story["error"]) == ("auto_story", None), story
    assert (mass["flow"], mass["error"], mass["answer"]) == (
        None, "not_allowed", assistant_draft.NOT_ALLOWED_ANSWER), mass


async def case_a_folder_named_like_mass_does_not_veto_a_story():
    assert not assistant_draft.vetoed("auto story from my Massage folder every 4 hours",
                                      refine=False, flow=assistant_draft.STORY_FLOW)
    assert assistant_draft.vetoed("auto story and a mass message every 4 hours",
                                  refine=False, flow=assistant_draft.STORY_FLOW)


# ── report_export (ultra-mode ticket 02) ──────────────────────────────

from assistant_draft import REPORT_FLOW  # noqa: E402
from assistant_report import ReportCtx, resolve_export, resolve_name  # noqa: E402
from db.models import Employee  # noqa: E402

CREATORS = (("a1", "Luna"), ("a2", "Luna B"), ("a3", "Mia Rose"), ("a4", "Kim"))
EMPLOYEES = ((1, "Anna"), (2, "Marco"), (3, "Marco Polo"))
TODAY = date(2026, 11, 13)


def _ctx(creators=CREATORS, employees=EMPLOYEES, shared=frozenset()) -> ReportCtx:
    return ReportCtx(tuple(creators), tuple(employees), "Europe/London", TODAY, "monday", frozenset(shared))


def _rx(report, *, request="export it", creators=CREATORS, employees=EMPLOYEES, shared=frozenset()):
    return resolve_export(report, _ctx(creators, employees, shared), request=request)


def _export(**over) -> dict:
    return {"flow": REPORT_FLOW, "report": {"dataset": "sales", "window": {"preset": "last_7_days"},
                                            "creators": [], "employees": [], "kinds": [], "format": "csv", **over},
            "assumptions": [], "unresolved": []}


def case_report_names_resolve_uniquely_or_stay_unresolved():
    opts = list(CREATORS)
    table = [("Luna", "a1", None),            # exact wins over containment ("Luna B")
             ("luna b", "a2", None), ("mia", "a3", None), ("Mia Rose OF", "a3", None), ("a4", "a4", None),
             ("lun", None, '"lun" could be Luna or Luna B — say which Creator.'),
             ("Lunna", None, 'No Creator called "Lunna" — name one of yours.'),   # close spelling never resolves
             ("Bob", None, 'No Creator called "Bob" — name one of yours.'),
             ("", None, 'Which Creator is ""?')]
    for want, key, problem in table:
        assert resolve_name(want, opts, "Creator") == (key, problem), (want, resolve_name(want, opts, "Creator"))
    dup = [("x1", "Kim"), ("x2", "Kim")]                   # two Creators with one nickname: never a guess
    assert resolve_name("Kim", dup, "Creator")[0] is None


def case_resolve_export_table():
    d, why = _rx({"dataset": "sales", "window": None, "creators": []})
    assert why is None and d.slots["recipe"]["creators"] == [] and d.unresolved == [], (d, why)   # all of them
    assert assistant_report.WHEN_NOTE in d.assumptions, d.assumptions
    assert d.slots["recipe"]["window"] == {"from": "2026-10-15", "to": "2026-11-13"}, d.slots     # fixed at draft
    assert d.slots["window"] == {"from": "2026-10-15", "to": "2026-11-13", "tz": "Europe/London"}
    assert d.slots["filename"] == "sales_2026-10-15_to_2026-11-13.csv" and d.slots["format"] == "csv"
    assert d.slots["columns"] == ["Creator", "Gross ($)", "Net or 80% ($)", "Sales"], d.slots["columns"]
    assert d.slots["labels"]["creators"] == [] and d.slots["labels"]["all_creators"] == 4
    # Names: resolved → ids + labels; ambiguous → unresolved and NO recipe (Download off), never all Creators.
    d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}, "creators": ["Mia", "Kim"]})
    assert (d.slots["recipe"]["creators"], d.slots["labels"]["creators"]) == (["a3", "a4"], ["Mia Rose", "Kim"])
    d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}, "creators": ["Mia", "lun"]})
    assert d.slots["recipe"] is None and len(d.unresolved) == 1 and "Luna or Luna B" in d.unresolved[0], d
    d, _ = _rx({"dataset": "employee_sales", "window": {"preset": "today"}, "employees": ["Marco"]})
    assert d.slots["recipe"]["employees"] == [2] and d.slots["labels"]["employees"] == ["Marco"], d.slots
    d, _ = _rx({"dataset": "chat_activity", "window": {"preset": "today"}, "employees": ["Marc"]})
    assert d.slots["recipe"] is None and "Marco or Marco Polo" in d.unresolved[0], d
    # Kinds as the model writes them; xlsx only when the request says so.
    d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}, "kinds": ["Tips", "PPVs"], "format": "xlsx"},
               request="export tips and ppv to excel")
    assert (d.slots["recipe"]["kinds"], d.slots["format"]) == (["tip", "ppv"], "xlsx"), d.slots
    assert d.slots["labels"]["kinds"] == ["Tips", "PPV"] and d.slots["filename"].endswith(".xlsx")
    d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}, "format": "xlsx"}, request="export sales")
    assert d.slots["format"] == "csv", d.slots
    # Refusals: a restriction that does not parse never widens the report.
    for report, needle in [
        ({"dataset": "messages", "window": {"preset": "today"}}, "dataset: not available; nearest is chat_activity"),
        ({"dataset": "sales", "window": {"preset": "today"}, "kinds": ["refunds"]}, "kinds: unknown kind refunds"),
        ({"dataset": "sales", "window": {"preset": "today"}, "employees": ["Anna"]}, "employees: sales has no Employees"),
        ({"dataset": "sales", "window": {"preset": "last_decade"}}, "window: unknown preset"),
        ({"dataset": "sales", "window": {"from": "2026-11-01", "to": "2026-10-01"}}, "window: to is before from"),
        ({"dataset": "employee_sales", "window": {"preset": "last_365_days"}}, "window: the window is 365 days"),
        ({"dataset": "sales", "window": {"preset": "today"}, "group_by": ["planet"]}, "group_by: unknown key planet"),
        ({"dataset": "chat_activity", "window": {"preset": "today"}, "kinds": ["tip"]}, "kinds: chat_activity has no kinds"),
    ]:
        d, why = _rx(report)
        assert d is None and why and needle in why, (report, why)
    assert _rx(None) == (None, assistant_report.NO_REPORT_ANSWER)
    # Only sort / limit are dropped, each with a line why.
    d, why = _rx({"dataset": "fan_spend", "window": {"preset": "today"}, "sort": "planet", "limit": 0})
    assert why is None and d.slots["recipe"]["sort"] is None and d.slots["recipe"]["limit"] is None, (d, why)
    assert any("couldn't sort by" in a for a in d.assumptions) and any("Every row" in a for a in d.assumptions)
    # No Creators at all, or more than a report takes with none named: unresolved.
    d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}}, creators=())
    assert d.slots["recipe"] is None and "no Creators" in d.unresolved[0], d.unresolved
    many = tuple((f"c{i}", f"Creator {i}") for i in range(60))
    d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}}, creators=many)
    assert d.slots["recipe"] is None and "at most 50" in d.unresolved[0], d.unresolved


def case_a_malformed_restriction_refuses_and_never_widens():
    base = {"dataset": "sales", "window": {"preset": "today"}}
    for kinds in ("", False, 0, {}, "tip"):                 # F2: never read as "all kinds"
        d, why = _rx({**base, "kinds": kinds})
        assert d is None and why == "I can't make that report — kinds: a list of kinds.", (kinds, why)
    for key, bad, needle in [("filters", {"minimum_spend": 1000}, "filters: unknown field"),
                             ("window", {}, "window: give {preset} or {from, to}"),
                             ("creators", "Mia", "creators: a list of Creator names"),
                             ("creators", {}, "creators: a list of Creator names"),
                             ("group_by", "", "group_by: a list of keys"),
                             ("metrics", 0, "metrics: a list of metrics")]:
        d, why = _rx({**base, key: bad})
        assert d is None and why and needle in why, (key, bad, why)
    d, why = _rx({**base, "employees": {}})
    assert d is None and "employees: sales has no Employees" in why, why
    for absent in ({}, {"kinds": None, "group_by": None, "metrics": None, "creators": None, "employees": None}):
        d, why = _rx({**base, **absent})                     # absent / null = the dataset's default
        assert why is None and d.slots["recipe"]["kinds"] == [] and d.slots["recipe"]["creators"] == [], (absent, why)
    d, why = _rx({"dataset": "sales", "window": None})
    assert why is None and assistant_report.WHEN_NOTE in d.assumptions, why


def case_a_name_the_model_widened_stays_a_question():
    two_mias = (("a1", "Mia Rose"), ("a2", "Mia Lux"), ("a3", "Luna"))
    d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}, "creators": ["Mia Rose"]},
               request="export today's sales for Mia", creators=two_mias)      # F3: "Mia" is two Creators
    assert d.slots["recipe"] is None and d.unresolved == ['"Mia" could be Mia Rose or Mia Lux — say which Creator.'], d
    d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}, "creators": ["Mia Rose"]},
               request="export today's sales for mia rose", creators=two_mias)
    assert d.slots["recipe"]["creators"] == ["a1"] and d.unresolved == [], d
    exact = (("a1", "Mia"), ("a2", "Mia Rose"))
    d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}, "creators": ["Mia Rose"]},
               request="export Mia's sales", creators=exact)
    assert d.slots["recipe"] is None and "Mia or Mia Rose" in d.unresolved[0], d
    d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}, "creators": ["Mia Rose"]},
               request="export Mia's sales")                               # one Mia: resolves
    assert d.slots["recipe"]["creators"] == ["a3"] and d.unresolved == [], d
    # F20: a short name widens too — "Li" (2 letters), "李" (one character, a whole word of the name)
    for short, rose, lux in (("Li", "Li Rose", "Li Lux"), ("李", "李 Rose", "李 Lux")):
        two = (("a1", rose), ("a2", lux), ("a3", "Luna"))
        d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}, "creators": [rose]},
                   request=f"export {short} sales today", creators=two)
        assert d.slots["recipe"] is None and d.unresolved == [f'"{short}" could be {rose} or {lux} — say which '
                                                              'Creator.'], d
        d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}, "creators": [rose]},
                   request=f"export {short} sales today", creators=two[::2])  # one of them: resolves
        assert d.slots["recipe"]["creators"] == ["a1"] and d.unresolved == [], d
    d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}, "creators": ["Mia Rose"]},
               request="give me a report on her")                          # "a": no name's word, not a question
    assert d.slots["recipe"]["creators"] == ["a3"] and d.unresolved == [], d


def case_a_name_the_model_shortened_is_the_longer_one_or_a_question():
    today = {"dataset": "sales", "window": {"preset": "today"}}
    mias = (("a1", "Mia"), ("a2", "Mia Rose"), ("a3", "Luna"))
    d, _ = _rx({**today, "creators": ["Mia"]}, request="export Mia Rose's sales", creators=mias)   # F22
    assert d.slots["recipe"]["creators"] == ["a2"] and d.unresolved == [], d
    d, _ = _rx({"dataset": "employee_sales", "window": {"preset": "today"}, "employees": ["Anna"]},
               request="export Anna Lee's sales", employees=((1, "Anna"), (2, "Anna Lee")))
    assert d.slots["recipe"]["employees"] == [2] and d.unresolved == [], d
    d, _ = _rx({**today, "creators": ["Mia"]}, request="export Mia's sales", creators=mias)   # exact: no question
    assert d.slots["recipe"]["creators"] == ["a1"] and d.unresolved == [], d
    d, _ = _rx({**today, "creators": ["Mia", "Mia Rose"]}, request="export Mia and Mia Rose", creators=mias)
    assert d.slots["recipe"]["creators"] == ["a1", "a2"] and d.unresolved == [], d                # both named
    d, _ = _rx({**today, "creators": ["Mia", "Rose"]}, request="export Mia, Rose",
               creators=(*mias, ("a4", "Rose")))                                                  # a list, not "Mia Rose"
    assert d.slots["recipe"]["creators"] == ["a1", "a4"] and d.unresolved == [], d
    d, _ = _rx({**today, "creators": ["Lee"]}, request="export Anna Lee Kim",
               creators=(("a1", "Lee"), ("a2", "Anna Lee"), ("a3", "Lee Kim")))                   # two longer: ask
    assert d.slots["recipe"] is None and d.unresolved == ['"Lee" could be Lee or Anna Lee or Lee Kim — say which '
                                                          'Creator.'], d
    d, _ = _rx({**today, "creators": ["李"]}, request="导出李明的销售", creators=(("a1", "李"), ("a2", "李明")))
    assert d.slots["recipe"]["creators"] == ["a2"] and d.unresolved == [], d


def case_names_match_in_any_script_and_short_parts_never_widen():
    opts = [(1, "Anna"), (2, "李"), (3, "Žana"), (4, "Zoë")]
    assert resolve_name("Žan", opts, "Employee") == (3, None)          # not Anna (F4: "an" ⊂ "anna")
    assert resolve_name("Zan", opts, "Employee") == (3, None)
    assert resolve_name("李", opts, "Employee") == (2, None)
    assert resolve_name("zoe", opts, "Employee") == (4, None)
    assert resolve_name("Ž", opts, "Employee") == (None, 'No Employee called "Ž" — name one of yours.')
    assert resolve_name("Ivan", [(1, "Anna")], "Employee")[0] is None


def case_employee_sales_with_a_shared_creator_is_a_question():
    d, why = _rx({"dataset": "employee_sales", "window": {"preset": "today"}}, shared={"a3"})
    assert why is None and d.slots["recipe"] is None, (d, why)               # F15: Download off, never a 400
    assert d.unresolved == ["Mia Rose is shared with another Agency — employee sales can't read it yet; "
                            "name your other Creators."], d.unresolved
    d, _ = _rx({"dataset": "employee_sales", "window": {"preset": "today"}, "creators": ["Luna"]}, shared={"a3"})
    assert d.slots["recipe"]["creators"] == ["a1"] and d.unresolved == [], d
    d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}}, shared={"a3"})   # sales reads shared ones
    assert d.slots["recipe"] is not None and d.unresolved == [], d


def case_the_card_labels_say_the_order_and_the_row_limit():
    d, _ = _rx({"dataset": "fan_spend", "window": {"preset": "today"}, "metrics": ["tips"], "limit": 20})
    assert (d.slots["labels"]["order"], d.slots["labels"]["limit"]) == ("Tips ($), high to low", 20), d.slots
    d, _ = _rx({"dataset": "sales", "window": {"preset": "today"}, "group_by": ["day"]})
    assert (d.slots["labels"]["order"], d.slots["labels"]["limit"]) == ("Day, oldest first", None), d.slots


def case_a_report_draft_needs_a_report_word_and_is_never_a_refine():
    v = assistant_draft.vetoed
    for ok in ("export last month's sales per creator", "csv of my chatters' earnings", "download my top spenders",
               "Excel with tips by day", "exportar ventas del mes", "izvozi prodajo"):
        assert not v(ok, refine=False, flow=REPORT_FLOW), ok
    for bad in ("how much did Mia make last month?", "who is my best chatter"):
        assert v(bad, refine=False, flow=REPORT_FLOW), bad
    assert v("export sales", refine=True, flow=REPORT_FLOW)


def case_the_system_prompt_holds_the_catalogue_and_no_account_data():
    sp = assistant_draft.system_prompt()
    assert assistant_draft.rd.catalogue_text() in sp and "<<DATASETS>>" not in sp
    assert sp == assistant_draft.system_prompt()
    block = assistant_draft.user_block("export sales", lists=None, folders=[], existing=[], previous=None,
                                       report=_ctx(), account=False)
    assert block == ("CREATORS: Kim, Luna, Luna B, Mia Rose\n\nEMPLOYEES: Anna, Marco, Marco Polo\n\n"
                     "TODAY: 2026-11-13 (Europe/London)\n\n<request>\nexport sales\n</request>"), block


def case_no_creator_keeps_an_export_or_its_refusal_and_asks_for_a_creator_otherwise():
    ad = assistant_draft

    def general(intent: dict, request: str, report=None) -> ad.Outcome:
        return ad.no_creator(ad.interpret(json.dumps(intent), request=request, lists=[], folders=[], existing=[],
                                          report=report))
    export = {"flow": "report_export", "report": {"dataset": "sales"}}
    assert general(export, "export sales", _ctx()).flow == ad.REPORT_FLOW
    refused = general({**export, "report": {"dataset": "weather"}}, "export the weather", _ctx())
    assert refused.flow is None and refused.answer.startswith("I can't make that report"), refused
    assert general(export, "export sales").error == "not_allowed"
    # An edit with nothing usable still asks for a Creator (it was an account flow), not UNSUPPORTED.
    assert general({"flow": "mass_edit"}, "edit my mass").answer == ad.PICK_CREATOR_ANSWER
    assert general(_story(), "post a story every 4 hours").answer == ad.PICK_CREATOR_ANSWER
    assert general({"flow": None}, "send a one-off mass").answer == ad.UNSUPPORTED_ANSWER
    assert general({"flow": "auto_posts"}, "x").answer == ad.UNSUPPORTED_ANSWER
    assert ad.no_creator(ad.interpret("not json", request="x", lists=[], folders=[], existing=[])).error == "bad_draft"


OWNER ="u_export_owner"


async def _seed_owner():
    async with get_session() as s:
        if await s.get(User, OWNER) is not None:
            return
        s.add(User(id=OWNER, username="export_owner", password="x", is_admin=False))
        for aid, nick in (("acc_x_luna", "Luna"), ("acc_x_mia", "Mia Rose")):
            s.add(Account(id=aid, nickname=nick))
            s.add(UserAccount(user_id=OWNER, account_id=aid))
        s.add(Employee(display_name="Anna", color="#cccccc", is_active=True, user_id=OWNER))


def _as_owner():
    return auth._request_user.set(auth.AuthedUser(OWNER, "export_owner", frozenset({"acc_x_luna", "acc_x_mia"})))


async def case_an_owner_exports_from_general_focus():
    await _seed_owner()
    spy = _patch(_Spy(json.dumps(_export(creators=["Mia"]))))
    token = _as_owner()
    try:
        out = await draft(DraftBody(request="export this week's sales for Mia"))
    finally:
        auth._request_user.reset(token)
    kw = spy.calls[0]
    assert kw["account_id"] is None and kw["user_id"] == OWNER, kw
    user = kw["messages"][1]["content"]
    assert "CREATORS: Luna, Mia Rose" in user and "EMPLOYEES: Anna" in user and "TODAY: " in user, user
    assert "ACCOUNT LISTS" not in user, user
    assert (out["flow"], out["error"], out["account_id"]) == (REPORT_FLOW, None, None), out
    assert out["slots"]["recipe"]["creators"] == ["acc_x_mia"] and out["unresolved"] == [], out
    assert out["slots"]["window"]["tz"] == "UTC" and out["answer"].startswith("Export sales for Mia Rose"), out
    async with get_session() as ses:
        row = await ses.get(AssistantTurn, out["id"])
    assert (row.user_id, row.account_id) == (OWNER, None), vars(row)


async def case_general_focus_is_a_report_only_and_owners_only():
    await _seed_owner()
    spy = _patch(_Spy(json.dumps(_pilot_intent())))
    token = _as_owner()
    try:
        out = await draft(DraftBody(request=PILOT))
    finally:
        auth._request_user.reset(token)
    assert (out["flow"], out["answer"]) == (None, assistant_draft.PICK_CREATOR_ANSWER), out
    # A chatter (or the anonymous dev admin) with no Creator: a sentence, no completion.
    spy = _patch(_Spy(json.dumps(_export())))
    real = assistant_draft.get_request_chatter
    assistant_draft.get_request_chatter = lambda: object()
    try:
        out = await draft(DraftBody(request="export sales"))
    finally:
        assistant_draft.get_request_chatter = real
    assert (out["flow"], out["error"], out["answer"]) == (
        None, "not_allowed", assistant_draft.EXPORT_NOT_ALLOWED_ANSWER), out
    assert spy.calls == [], "a chatter bought a completion"
    try:
        await draft(DraftBody(request="export sales"))       # nobody signed in, no Creator
    except HTTPException as e:
        assert e.status_code == 401, e.status_code
    else:
        raise AssertionError("an anonymous General draft sailed through")
    # On a Creator, a non-owner's export draft is refused after the call.
    await _seed()
    _patch(_Spy(json.dumps(_export())))
    out = await _draft("export sales")
    assert (out["flow"], out["answer"]) == (None, assistant_draft.EXPORT_NOT_ALLOWED_ANSWER), out


async def case_an_owner_on_a_creator_exports_all_creators_and_a_report_is_never_refined():
    await _seed_owner()
    _patch(_Spy(json.dumps(_export())))
    token = _as_owner()
    try:
        out = await draft(DraftBody(request="export sales", account_id="acc_x_luna"))
        refined = await draft(DraftBody(request="export sales", account_id="acc_x_luna", previous={"name": "x"}))
    finally:
        auth._request_user.reset(token)
    assert out["flow"] == REPORT_FLOW and out["slots"]["recipe"]["creators"] == [], out   # all, not the focused one
    assert out["slots"]["labels"]["all_creators"] == 2, out["slots"]["labels"]
    assert refined["flow"] is None, refined


async def case_an_owner_keeps_the_account_gate_and_report_names_ride_only_report_asks():
    await _seed_owner()
    real = assistant_draft.opt_in_refusal

    async def refuse(pages, account_id):
        return "Your role does not allow it"
    token = _as_owner()
    try:
        spy = _patch(_Spy(json.dumps(_pilot_intent())))
        assistant_draft.opt_in_refusal = refuse
        out = await draft(DraftBody(request=PILOT, account_id="acc_x_luna"))   # F7: no report word, no call
        assert (out["error"], out["answer"]) == ("not_allowed", assistant_draft.NOT_ALLOWED_ANSWER), out
        assert spy.calls == [], "a refused owner bought a completion"
        spy = _patch(_Spy(json.dumps({"flow": None})))
        out = await draft(DraftBody(request="export my auto mass rules", account_id="acc_x_luna"))
        assert (out["error"], out["answer"]) == ("not_allowed", assistant_draft.NOT_ALLOWED_ANSWER), out
        _patch(_Spy(json.dumps(_export())))
        out = await draft(DraftBody(request="export sales", account_id="acc_x_luna"))
        assert out["flow"] == REPORT_FLOW, out                                  # an export is not the account's gate
        assistant_draft.opt_in_refusal = real
        spy = _patch(_Spy(json.dumps(_pilot_intent())))
        await draft(DraftBody(request=PILOT, account_id="acc_x_luna"))
        assert "CREATORS:" not in spy.calls[0]["messages"][1]["content"]       # F13: a mass ask reads no names
    finally:
        assistant_draft.opt_in_refusal = real
        auth._request_user.reset(token)


_harness.run()
